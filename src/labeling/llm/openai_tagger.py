import base64
import json
import logging
import re
import time
from typing import Callable, TypeVar

import numpy as np
from openai import OpenAI

from src.labeling.llm.base import EmbeddingResult, Embedder, LLMTagger, TaggingResult
from src.labeling.models import CardTags
from src.labeling.taxonomy import APPEARANCE_CATEGORIES

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


def _extract_retry_seconds(error_message: str) -> float:
    match = re.search(r"try again in (\d+)ms", error_message, flags=re.IGNORECASE)
    if not match:
        return 1.0
    milliseconds = int(match.group(1))
    return max(0.1, milliseconds / 1000.0)


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return type(exc).__name__ == "RateLimitError" or ("rate" in text and "limit" in text)


def _call_with_rate_limit_retry(
    *,
    run_id: str,
    hypothesis_id: str,
    location: str,
    call: Callable[[], _T],
    max_attempts: int = 8,
) -> _T:
    attempt = 0
    while True:
        attempt += 1
        try:
            return call()
        except Exception as exc:
            if not _is_rate_limit_error(exc) or attempt >= max_attempts:
                logger.warning(
                    "OpenAI call failed without retry recovery: location=%s attempt=%s error_type=%s",
                    location,
                    attempt,
                    type(exc).__name__,
                )
                raise
            retry_in = _extract_retry_seconds(str(exc))
            logger.info(
                "OpenAI rate limit retry: location=%s attempt=%s sleep=%.3fs",
                location,
                attempt,
                retry_in,
            )
            time.sleep(retry_in)


def _ensure_no_additional_properties(schema: dict) -> dict:
    if isinstance(schema, dict):
        normalized: dict = {}
        for key, value in schema.items():
            if isinstance(value, dict):
                normalized[key] = _ensure_no_additional_properties(value)
            elif isinstance(value, list):
                normalized[key] = [
                    _ensure_no_additional_properties(item) if isinstance(item, dict) else item for item in value
                ]
            else:
                normalized[key] = value
        if normalized.get("type") == "object" and "additionalProperties" not in normalized:
            normalized["additionalProperties"] = False
        return normalized
    return schema


def _ensure_required_matches_properties(schema: dict) -> dict:
    if isinstance(schema, dict):
        normalized: dict = {}
        for key, value in schema.items():
            if isinstance(value, dict):
                normalized[key] = _ensure_required_matches_properties(value)
            elif isinstance(value, list):
                normalized[key] = [
                    _ensure_required_matches_properties(item) if isinstance(item, dict) else item for item in value
                ]
            else:
                normalized[key] = value
        if normalized.get("type") == "object" and isinstance(normalized.get("properties"), dict):
            normalized["required"] = list(normalized["properties"].keys())
        return normalized
    return schema


def _strip_default_next_to_ref(schema: dict) -> dict:
    if isinstance(schema, dict):
        normalized: dict = {}
        for key, value in schema.items():
            if isinstance(value, dict):
                normalized[key] = _strip_default_next_to_ref(value)
            elif isinstance(value, list):
                normalized[key] = [_strip_default_next_to_ref(item) if isinstance(item, dict) else item for item in value]
            else:
                normalized[key] = value
        if "$ref" in normalized and "default" in normalized:
            del normalized["default"]
        return normalized
    return schema


class OpenAITagger(LLMTagger, Embedder):
    def __init__(
        self,
        api_key: str,
        vision_model: str = "gpt-4o-mini",
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        self._client = OpenAI(api_key=api_key)
        self.vision_model = vision_model
        self.embedding_model = embedding_model

    def tag_image(self, image_bytes: bytes, name: str) -> TaggingResult:
        run_id = f"ingest-{int(time.time() * 1000)}"
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{image_b64}"
        schema = CardTags.model_json_schema()
        strict_schema = _ensure_no_additional_properties(schema)
        strict_schema = _ensure_required_matches_properties(strict_schema)
        strict_schema = _strip_default_next_to_ref(strict_schema)
        try:
            completion = _call_with_rate_limit_retry(
                run_id=run_id,
                hypothesis_id="H6",
                location="src/labeling/llm/openai_tagger.py:tag_image:retry",
                call=lambda: self._client.chat.completions.create(
                model=self.vision_model,
                temperature=0,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "card_tags",
                        "strict": True,
                        "schema": strict_schema,
                    },
                },
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты анализируешь портретные изображения персонажей и актёров. "
                            "Верни только JSON по схеме без лишнего текста. "
                            "Заполни все поля схемы. "
                            "Для notable_features укажи минимум 4 конкретных различающих признака "
                            "(детали одежды, формы лица, прически, шрамов, аксессуаров, выражения), "
                            "избегай общих и бесполезных слов вроде 'обычный', 'красивый', 'интересный', 'стильный'."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Это персонаж или актёр: {name}. Определи теги внешности."},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
            ),
            )
        except Exception as exc:
            logger.error("Vision completion failed: model=%s error_type=%s", self.vision_model, type(exc).__name__)
            raise
        content = completion.choices[0].message.content or "{}"
        tags = CardTags.model_validate(json.loads(content))
        usage = {
            "prompt_tokens": completion.usage.prompt_tokens if completion.usage else 0,
            "completion_tokens": completion.usage.completion_tokens if completion.usage else 0,
            "total_tokens": completion.usage.total_tokens if completion.usage else 0,
        }
        # Approximation for gpt-4o-mini ($0.15 / 1M input, $0.60 / 1M output).
        estimated_cost = (usage["prompt_tokens"] * 0.15 + usage["completion_tokens"] * 0.60) / 1_000_000
        logger.info(
            "Vision tagging completed: model=%s prompt=%s completion=%s estimated_cost=%.6f",
            self.vision_model,
            usage["prompt_tokens"],
            usage["completion_tokens"],
            estimated_cost,
        )
        return TaggingResult(tags=tags, usage=usage, estimated_cost_usd=estimated_cost)

    def build_appearance_text(self, tags: CardTags) -> str:
        payload = tags.model_dump(mode="json")
        parts: list[str] = []
        for category in APPEARANCE_CATEGORIES:
            value = payload[category]
            if isinstance(value, list):
                if not value:
                    continue
                readable = ", ".join(str(item).replace("_", " ") for item in value)
                parts.append(f"{category}: {readable}")
            else:
                readable = str(value).replace("_", " ")
                parts.append(f"{category}: {readable}")
        return "; ".join(parts)

    def embed_text(self, text: str) -> EmbeddingResult:
        run_id = f"embed-{int(time.time() * 1000)}"
        try:
            embedding_response = _call_with_rate_limit_retry(
                run_id=run_id,
                hypothesis_id="H6",
                location="src/labeling/llm/openai_tagger.py:embed_text:retry",
                call=lambda: self._client.embeddings.create(model=self.embedding_model, input=text),
            )
        except Exception as exc:
            logger.error("Embedding failed: model=%s error_type=%s", self.embedding_model, type(exc).__name__)
            raise
        vector = np.asarray(embedding_response.data[0].embedding, dtype=np.float32)
        usage = {
            "prompt_tokens": embedding_response.usage.prompt_tokens if embedding_response.usage else 0,
            "total_tokens": embedding_response.usage.total_tokens if embedding_response.usage else 0,
        }
        # Approximation for text-embedding-3-small ($0.02 / 1M input tokens).
        estimated_cost = usage["prompt_tokens"] * 0.02 / 1_000_000
        logger.info(
            "Embedding completed: model=%s tokens=%s estimated_cost=%.8f",
            self.embedding_model,
            usage["prompt_tokens"],
            estimated_cost,
        )
        return EmbeddingResult(vector=vector, usage=usage, estimated_cost_usd=estimated_cost)

