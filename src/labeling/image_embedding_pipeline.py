import re
from dataclasses import dataclass
from pathlib import Path

from src.labeling.image_embedding_provider import ImageEmbeddingProvider
from src.labeling.image_embedding_storage import ImageEmbeddingRecord, ImageEmbeddingStorage
from src.labeling.storage import LabelingStorage


@dataclass(slots=True)
class ImageEmbeddingIngestResult:
    record: ImageEmbeddingRecord
    skipped_duplicate: bool


class ImageEmbeddingPipeline:
    # 📚 Что здесь происходит:
    # Этот pipeline — отдельный контур для image embeddings: он нормализует изображение,
    # считает embedding и пишет результат в выделенную БД. Мы специально не используем
    # таблицы cards/card_tags/pair_history, чтобы не ломать текущий игровой путь.
    #
    # ⚠️ Важно знать:
    # - Нормализация до SHA256 обязательна: одинаковые картинки в разных форматах
    #   должны давать один и тот же fingerprint (иначе дедупликация будет шумной).
    # - API эмбеддингов может быть медленным/дорогим; для больших batch лучше запускать
    #   поэтапно и мониторить расход токенов.
    # - Текущий pipeline не меняет runtime-матчинг автоматически, это только подготовка данных.
    def __init__(
        self,
        *,
        storage: ImageEmbeddingStorage,
        provider: ImageEmbeddingProvider,
        legacy_normalizer: LabelingStorage,
    ) -> None:
        self._storage = storage
        self._provider = provider
        self._legacy_normalizer = legacy_normalizer
        self._storage.init_db()

    def ingest_image(
        self,
        *,
        image_bytes: bytes,
        card_id: str,
        file_path: str | None = None,
        force: bool = False,
    ) -> ImageEmbeddingIngestResult:
        if self._legacy_normalizer.get_card(card_id) is None:
            raise ValueError(
                f"Card '{card_id}' is missing in legacy cards DB. "
                "Add card via labeling pipeline first, then ingest image embeddings."
            )
        normalized_bytes, _, _ = self._legacy_normalizer.normalize_image(image_bytes)
        image_sha256 = self._storage.sha256_digest(normalized_bytes)
        existing = self._storage.get_by_sha256(image_sha256)
        if existing is not None and not force:
            return ImageEmbeddingIngestResult(record=existing, skipped_duplicate=True)

        result = self._provider.embed_image(normalized_bytes)
        record = self._storage.upsert_embedding(
            card_id=card_id,
            image_sha256=image_sha256,
            file_path=file_path,
            embedding=result.vector,
            model=result.model,
        )
        return ImageEmbeddingIngestResult(record=record, skipped_duplicate=False)

    def reembed_image(
        self,
        *,
        image_bytes: bytes,
        card_id: str,
        file_path: str | None = None,
    ) -> ImageEmbeddingRecord:
        return self.ingest_image(
            image_bytes=image_bytes,
            card_id=card_id,
            file_path=file_path,
            force=True,
        ).record

    def ingest_directory(self, dir_path: Path, *, force: bool = False) -> list[ImageEmbeddingIngestResult]:
        allowed_ext = {".jpg", ".jpeg", ".png", ".webp"}
        results: list[ImageEmbeddingIngestResult] = []
        for image_path in sorted(dir_path.iterdir()):
            if image_path.suffix.lower() not in allowed_ext:
                continue
            card_id = self._slugify(image_path.stem)
            results.append(
                self.ingest_image(
                    image_bytes=image_path.read_bytes(),
                    card_id=card_id,
                    file_path=str(image_path),
                    force=force,
                )
            )
        return results

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = value.strip().lower()
        normalized = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "-", normalized)
        normalized = normalized.strip("-")
        return normalized or "image"
