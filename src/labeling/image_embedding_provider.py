import base64
import io
import logging
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from openai import OpenAI
from PIL import Image

logger = logging.getLogger(__name__)


class ImageEmbeddingProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class ImageEmbeddingResult:
    vector: np.ndarray
    model: str
    usage: dict[str, int]


class ImageEmbeddingProvider(Protocol):
    def embed_image(self, image_bytes: bytes) -> ImageEmbeddingResult:
        raise NotImplementedError


def _l2_normalize(vector: np.ndarray) -> np.ndarray:
    normalized = np.asarray(vector, dtype=np.float32)
    if normalized.ndim != 1:
        raise ImageEmbeddingProviderError("Image embedding vector must be 1D")
    norm = float(np.linalg.norm(normalized))
    if norm <= 0.0:
        raise ImageEmbeddingProviderError("Image embedding vector norm must be > 0")
    return normalized / norm


class OpenAIImageEmbeddingProvider(ImageEmbeddingProvider):
    # 📚 Что здесь происходит:
    # Мы инкапсулируем вызов внешнего API в отдельный provider, чтобы pipeline не зависел
    # от конкретного вендора. Это как "адаптер розетки": бизнес-логика работает одинаково,
    # а детали конкретного API изолированы в одном месте.
    #
    # ⚠️ Важно знать:
    # - Image embedding API и формат payload у провайдеров могут меняться.
    # - Каждый вызов тарифицируется; batch-обработка больших каталогов может быть дорогой.
    # - При сетевых сбоях/лимитах мы пробрасываем прозрачную ошибку, чтобы fallback-цепочка
    #   могла попытаться использовать следующий provider.
    def __init__(self, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self.model = model

    def embed_image(self, image_bytes: bytes) -> ImageEmbeddingResult:
        # NOTE: payload intentionally explicit and isolated in this adapter;
        # if OpenAI image embedding contract changes, only this block needs update.
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{image_b64}"
        try:
            response = self._client.embeddings.create(
                model=self.model,
                input=[{"type": "input_image", "image_url": data_url}],
            )
        except Exception as exc:  # pragma: no cover - covered by provider fallback tests via stubs
            raise ImageEmbeddingProviderError(
                f"OpenAI image embedding failed for model '{self.model}': {exc}"
            ) from exc
        vector = np.asarray(response.data[0].embedding, dtype=np.float32)
        usage = {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
        }
        return ImageEmbeddingResult(vector=_l2_normalize(vector), model=self.model, usage=usage)


class LocalClipImageEmbeddingProvider(ImageEmbeddingProvider):
    # 📚 Что здесь происходит:
    # Мы считаем image embedding локально через CLIP-модель без внешнего API.
    # Аналогия: вместо "звонка в облако" ставим мини-лабораторию у себя на машине,
    # которая выдаёт вектор-координаты картинки на "карте смыслов изображений".
    #
    # Почему так:
    # - Для тестов и исследований локальный CLIP дешевле и предсказуемее по latency.
    # - Пайплайн остаётся совместимым с другими провайдерами благодаря общему интерфейсу.
    #
    # ⚠️ Важно знать:
    # - Нужны локальные зависимости `torch` и `transformers`.
    # - На CPU throughput будет ниже, чем на GPU/MPS.
    # - Разные CLIP-модели дают векторы разной размерности; это важно учитывать при матчинге.
    def __init__(self, model_name: str, device: str = "cpu") -> None:
        self.model = model_name
        self._device = device
        try:
            import torch
            from transformers import CLIPModel, CLIPProcessor
        except Exception as exc:  # pragma: no cover - depends on optional runtime deps
            raise ImageEmbeddingProviderError(
                "Local CLIP provider requires optional dependencies: torch and transformers"
            ) from exc

        self._torch = torch
        try:
            self._processor = CLIPProcessor.from_pretrained(model_name)
            self._model = CLIPModel.from_pretrained(model_name).to(device)
            self._model.eval()
        except Exception as exc:  # pragma: no cover - depends on local environment/model files
            raise ImageEmbeddingProviderError(
                f"Failed to initialize local CLIP model '{model_name}' on device '{device}': {exc}"
            ) from exc

    def embed_image(self, image_bytes: bytes) -> ImageEmbeddingResult:
        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                rgb_image = image.convert("RGB")
        except Exception as exc:
            raise ImageEmbeddingProviderError(f"Failed to decode image bytes for CLIP embedding: {exc}") from exc

        try:
            inputs = self._processor(images=rgb_image, return_tensors="pt")
            inputs = {key: value.to(self._device) for key, value in inputs.items()}
            with self._torch.no_grad():
                image_features = self._model.get_image_features(**inputs)
            tensor = image_features
            if not hasattr(tensor, "detach"):
                tensor = getattr(image_features, "image_embeds", None) or getattr(
                    image_features, "pooler_output", None
                )
            if tensor is None or not hasattr(tensor, "detach"):
                raise ImageEmbeddingProviderError(
                    f"Unexpected CLIP output type: {type(image_features).__name__}"
                )
            vector = np.asarray(tensor.detach().cpu().numpy(), dtype=np.float32)
            vector = np.squeeze(vector)
            if vector.ndim != 1:
                vector = vector.reshape(-1)
        except Exception as exc:
            raise ImageEmbeddingProviderError(
                f"Local CLIP embedding failed for model '{self.model}' on device '{self._device}': {exc}"
            ) from exc

        return ImageEmbeddingResult(
            vector=_l2_normalize(vector),
            model=self.model,
            usage={"prompt_tokens": 0, "total_tokens": 0},
        )


class FallbackImageEmbeddingProvider(ImageEmbeddingProvider):
    # 📚 Что здесь происходит:
    # Здесь реализован "каскад провайдеров": сначала пробуем основной (primary), затем fallback.
    # Аналогия: как несколько DNS-серверов — если первый недоступен, запрос не падает сразу.
    #
    # ⚠️ Важно знать:
    # - Fallback не исправляет системные ошибки в данных (например, битое изображение).
    # - В логах сохраняется причина каждого падения, чтобы дебажить интеграцию было проще.
    # - Если все провайдеры упали, мы выбрасываем понятное исключение с корневой причиной.
    def __init__(self, providers: list[ImageEmbeddingProvider]) -> None:
        if not providers:
            raise ValueError("At least one image embedding provider is required")
        self._providers = providers

    def embed_image(self, image_bytes: bytes) -> ImageEmbeddingResult:
        last_error: Exception | None = None
        for idx, provider in enumerate(self._providers):
            try:
                return provider.embed_image(image_bytes)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Image embedding provider failed: provider_index=%s provider=%s error=%s",
                    idx,
                    type(provider).__name__,
                    exc,
                )
        raise ImageEmbeddingProviderError(
            f"All image embedding providers failed ({len(self._providers)} attempted): {last_error}"
        ) from last_error


class UnsupportedImageEmbeddingProvider(ImageEmbeddingProvider):
    def __init__(self, reason: str) -> None:
        self._reason = reason

    def embed_image(self, image_bytes: bytes) -> ImageEmbeddingResult:
        raise ImageEmbeddingProviderError(self._reason)
