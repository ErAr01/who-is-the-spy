import re
from dataclasses import dataclass

from src.labeling.llm.base import Embedder, LLMTagger
from src.labeling.models import CardRecord
from src.labeling.storage import LabelingStorage


@dataclass(slots=True)
class IngestResult:
    card: CardRecord
    skipped_duplicate: bool


class LabelingPipeline:
    def __init__(self, storage: LabelingStorage, tagger: LLMTagger, embedder: Embedder) -> None:
        self._storage = storage
        self._tagger = tagger
        self._embedder = embedder
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
    ) -> IngestResult:
        normalized_bytes, thumbnail_bytes, mime_type = self._storage.normalize_image(image_bytes)
        image_sha256 = self._storage.sha256_digest(normalized_bytes)
        existing = self._storage.find_card_by_sha256(image_sha256)
        if existing and not force:
            return IngestResult(card=existing, skipped_duplicate=True)

        resolved_card_id = card_id or self._slugify(name)
        tagging = self._tagger.tag_image(normalized_bytes, name=name)
        appearance_text = self._tagger.build_appearance_text(tagging.tags)
        embedding = self._embedder.embed_text(appearance_text)
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
        )
        return IngestResult(card=card, skipped_duplicate=False)

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
        ).card

    def re_embed_card(self, card_id: str) -> CardRecord:
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

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = value.strip().lower()
        normalized = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "-", normalized)
        normalized = normalized.strip("-")
        return normalized or "card"

