import logging
import re
from dataclasses import dataclass

from src.labeling.llm.base import CharacterDescriber, DescriptionResult, Embedder, LLMTagger
from src.labeling.models import CardRecord
from src.labeling.storage import LabelingStorage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestResult:
    card: CardRecord
    skipped_duplicate: bool


@dataclass(slots=True)
class DescribeResult:
    card: CardRecord
    skipped_existing: bool
    estimated_cost_usd: float


class LabelingPipeline:
    def __init__(
        self,
        storage: LabelingStorage,
        tagger: LLMTagger | None,
        embedder: Embedder | None,
        describer: CharacterDescriber | None = None,
    ) -> None:
        # tagger/embedder обязательны для ingest/relabel/re-embed,
        # но не нужны для describe-команд (бэкфилл описаний).
        self._storage = storage
        self._tagger = tagger
        self._embedder = embedder
        self._describer = describer
        self._storage.init_db()

    def ingest_card(
        self,
        image_bytes: bytes,
        name: str,
        wiki_url: str | None = None,
        card_id: str | None = None,
        force: bool = False,
        categories: list[str] | None = None,
        notes: str | None = None,
        generate_description: bool = True,
    ) -> IngestResult:
        if self._tagger is None or self._embedder is None:
            raise ValueError("Tagger and embedder are required for ingest commands")
        normalized_bytes, thumbnail_bytes, mime_type = self._storage.normalize_image(image_bytes)
        image_sha256 = self._storage.sha256_digest(normalized_bytes)
        existing = self._storage.find_card_by_sha256(image_sha256)
        if existing and not force:
            return IngestResult(card=existing, skipped_duplicate=True)

        resolved_card_id = card_id or self._slugify(name)
        tagging = self._tagger.tag_image(normalized_bytes, name=name)
        appearance_text = self._tagger.build_appearance_text(tagging.tags)
        embedding = self._embedder.embed_text(appearance_text)
        description_result = (
            self._try_describe(
                name=name,
                categories=categories or [],
                appearance_text=appearance_text,
                wiki_url=wiki_url,
                notes=notes,
            )
            if generate_description
            else None
        )
        card = self._storage.save_card(
            card_id=resolved_card_id,
            name=name,
            wiki_url=wiki_url,
            image_bytes=normalized_bytes,
            image_mime=mime_type,
            thumbnail_bytes=thumbnail_bytes,
            image_sha256=image_sha256,
            tags=tagging.tags,
            appearance_text=appearance_text,
            embedding=embedding.vector,
            embedding_model=getattr(self._embedder, "embedding_model", "unknown"),
            vision_model=getattr(self._tagger, "vision_model", "unknown"),
            dataset_categories=categories,
            notes=notes,
            description=description_result.description if description_result else None,
            facts=description_result.facts if description_result else None,
            description_model=getattr(self._describer, "model", "unknown") if description_result else None,
        )
        return IngestResult(card=card, skipped_duplicate=False)

    def _try_describe(
        self,
        name: str,
        categories: list[str],
        appearance_text: str | None = None,
        wiki_url: str | None = None,
        notes: str | None = None,
    ) -> DescriptionResult | None:
        # Ошибка генерации описания не должна срывать ingest:
        # карточку можно дополнить позже командой `describe`.
        if self._describer is None:
            return None
        try:
            return self._describer.describe(
                name=name,
                categories=categories,
                appearance_text=appearance_text,
                wiki_url=wiki_url,
                notes=notes,
            )
        except Exception as exc:
            logger.warning(
                "Description generation failed, card will be saved without it: name=%s error_type=%s",
                name,
                type(exc).__name__,
            )
            return None

    def relabel_card(self, card_id: str, force: bool = True) -> CardRecord:
        card = self._storage.get_card(card_id)
        if card is None:
            raise ValueError(f"Card '{card_id}' not found")
        image_bytes = self._storage.get_image_bytes(card_id, thumbnail=False)
        if image_bytes is None:
            raise ValueError(f"Image for card '{card_id}' is missing")
        return self.ingest_card(
            image_bytes=image_bytes,
            name=card.name,
            wiki_url=card.wiki_url,
            card_id=card.id,
            force=force,
            categories=self._storage.get_dataset_categories(card.id),
            notes=card.notes,
            # relabel — это пере-тэггинг изображения: существующее описание не трогаем
            # (перезаписало бы и ручную правку, и describe --force). Для перегенерации
            # описания есть отдельная команда `describe --force`.
            generate_description=False,
        ).card

    def re_embed_card(self, card_id: str) -> CardRecord:
        if self._embedder is None:
            raise ValueError("Embedder is required for re-embed commands")
        card = self._storage.get_card(card_id)
        if card is None:
            raise ValueError(f"Card '{card_id}' not found")
        image_bytes = self._storage.get_image_bytes(card_id, thumbnail=False)
        if image_bytes is None:
            raise ValueError(f"Image for card '{card_id}' is missing")
        thumbnail = self._storage.get_image_bytes(card_id, thumbnail=True)
        if thumbnail is None:
            raise ValueError(f"Thumbnail for card '{card_id}' is missing")

        embedding = self._embedder.embed_text(card.appearance_text)
        return self._storage.save_card(
            card_id=card.id,
            name=card.name,
            wiki_url=card.wiki_url,
            image_bytes=image_bytes,
            image_mime="image/jpeg",
            thumbnail_bytes=thumbnail,
            image_sha256=card.image_sha256,
            tags=card.tags,
            appearance_text=card.appearance_text,
            embedding=embedding.vector,
            embedding_model=getattr(self._embedder, "embedding_model", "unknown"),
            vision_model=card.vision_model,
            dataset_categories=self._storage.get_dataset_categories(card.id),
            notes=card.notes,
        )

    def relabel_all(self) -> list[CardRecord]:
        cards = self._storage.list_cards()
        return [self.relabel_card(card.id) for card in cards]

    def re_embed_all(self) -> list[CardRecord]:
        cards = self._storage.list_cards()
        return [self.re_embed_card(card.id) for card in cards]

    def describe_card(self, card_id: str, force: bool = False) -> DescribeResult:
        if self._describer is None:
            raise ValueError("Character describer is not configured")
        card = self._storage.get_card(card_id)
        if card is None:
            raise ValueError(f"Card '{card_id}' not found")
        if card.description and not force:
            return DescribeResult(card=card, skipped_existing=True, estimated_cost_usd=0.0)
        result = self._describer.describe(
            name=card.name,
            categories=self._storage.get_dataset_categories(card.id),
            # Якоря с карточки: теги внешности сняты с самого изображения и не дают
            # модели перепутать персонажа с тёзкой при неоднозначном имени.
            appearance_text=card.appearance_text,
            wiki_url=card.wiki_url,
            notes=card.notes,
        )
        updated = self._storage.update_card_description(
            card_id=card.id,
            description=result.description,
            facts=result.facts,
            description_model=getattr(self._describer, "model", "unknown"),
        )
        return DescribeResult(card=updated, skipped_existing=False, estimated_cost_usd=result.estimated_cost_usd)

    def list_describe_targets(self, force: bool = False) -> list[str]:
        if force:
            return [card.id for card in self._storage.list_cards()]
        return self._storage.list_card_ids_missing_description()

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = value.strip().lower()
        normalized = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "-", normalized)
        normalized = normalized.strip("-")
        return normalized or "card"

