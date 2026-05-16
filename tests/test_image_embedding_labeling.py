import io
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

import numpy as np
from PIL import Image

from src.game.content import ContentProvider
from src.game.matching_strategy import ImageEmbeddingPairMatcherStrategy, TagBasedPairMatcherStrategy
from src.labeling.image_embedding_pipeline import ImageEmbeddingPipeline
from src.labeling.image_embedding_provider import ImageEmbeddingResult, _l2_normalize
from src.labeling.image_embedding_storage import ImageEmbeddingStorage
from src.labeling.models import CardRecord, CardTags
from src.labeling.storage import LabelingStorage


class _FakeImageEmbeddingProvider:
    def __init__(self, model: str = "fake-image-embedding-v1") -> None:
        self.model = model
        self.calls = 0

    def embed_image(self, image_bytes: bytes) -> ImageEmbeddingResult:
        self.calls += 1
        size_factor = float(len(image_bytes) % 7)
        vector = np.asarray([size_factor, 1.0, 2.0, 3.0], dtype=np.float32)
        return ImageEmbeddingResult(vector=vector, model=self.model, usage={"total_tokens": 0})


def _make_test_image_bytes(color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (48, 48), color=color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _make_tags() -> CardTags:
    return CardTags(
        character_type="real_person",
        franchise_kind="none",
        gender_presentation="male",
        age_group="adult",
        body_build="average",
        face_shape="oval",
        hair_color="black",
        hair_length="short",
        hair_style="straight",
        eye_color="brown",
        skin_tone="medium",
        facial_hair="none",
        glasses="none",
        headwear="none",
        clothing_primary_color="black",
        mood="neutral",
        pose="front",
    )


def _seed_legacy_card(storage: LabelingStorage, card_id: str, image_bytes: bytes) -> None:
    normalized, thumb, mime = storage.normalize_image(image_bytes)
    storage.save_card(
        card_id=card_id,
        name=card_id,
        wiki_url=None,
        image_bytes=normalized,
        image_mime=mime,
        thumbnail_bytes=thumb,
        image_sha256=storage.sha256_digest(normalized),
        tags=_make_tags(),
        appearance_text=f"{card_id} appearance",
        embedding=np.asarray([0.1, 0.2, 0.3], dtype=np.float32),
        embedding_model="test-model",
        vision_model="test-model",
        dataset_categories=["anime"],
    )


def _make_card(card_id: str) -> CardRecord:
    return CardRecord(
        id=card_id,
        name=card_id,
        wiki_url=None,
        image_sha256=f"sha-{card_id}",
        tags=_make_tags(),
        appearance_text=f"{card_id} appearance",
        embedding_model="test-model",
        vision_model="test-model",
        labeled_at=datetime.now(UTC),
        dataset_categories=["anime"],
    )


class ImageEmbeddingStorageTest(TestCase):
    def test_upsert_and_read_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "image_embeddings.db"
            storage = ImageEmbeddingStorage(db_path)
            storage.init_db()
            vector = np.asarray([0.1, 0.2, 0.3], dtype=np.float32)

            record = storage.upsert_embedding(
                card_id="card-1",
                image_sha256="sha-1",
                file_path="/tmp/image.png",
                embedding=vector,
                model="test-model",
            )
            loaded = storage.get_by_sha256("sha-1")

        self.assertEqual(record.card_id, "card-1")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.dimension, 3)
        self.assertEqual(loaded.model, "test-model")
        self.assertEqual(loaded.file_path, "/tmp/image.png")
        np.testing.assert_allclose(loaded.embedding, vector)


class ImageEmbeddingPipelineTest(TestCase):
    def test_pipeline_deduplicates_by_normalized_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            embeddings_db = Path(tmp) / "image_embeddings.db"
            legacy_db = Path(tmp) / "cards.db"
            provider = _FakeImageEmbeddingProvider()
            image_bytes = _make_test_image_bytes((120, 10, 20))
            legacy_storage = LabelingStorage(legacy_db)
            legacy_storage.init_db()
            _seed_legacy_card(legacy_storage, "card-a", image_bytes)
            _seed_legacy_card(legacy_storage, "card-b", _make_test_image_bytes((50, 160, 80)))
            pipeline = ImageEmbeddingPipeline(
                storage=ImageEmbeddingStorage(embeddings_db),
                provider=provider,
                legacy_normalizer=legacy_storage,
            )

            first = pipeline.ingest_image(image_bytes=image_bytes, card_id="card-a", file_path="/tmp/a.png")
            second = pipeline.ingest_image(image_bytes=image_bytes, card_id="card-b", file_path="/tmp/b.png")

        self.assertFalse(first.skipped_duplicate)
        self.assertTrue(second.skipped_duplicate)
        self.assertEqual(first.record.card_id, "card-a")
        self.assertEqual(second.record.card_id, "card-a")
        self.assertEqual(provider.calls, 1)

    def test_pipeline_does_not_touch_legacy_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy_db = Path(tmp) / "cards.db"
            emb_db = Path(tmp) / "image_embeddings.db"
            legacy_storage = LabelingStorage(legacy_db)
            legacy_storage.init_db()
            image_bytes = _make_test_image_bytes((5, 100, 200))
            _seed_legacy_card(legacy_storage, "new-card", image_bytes)
            before_counts = _legacy_counts(legacy_db)

            pipeline = ImageEmbeddingPipeline(
                storage=ImageEmbeddingStorage(emb_db),
                provider=_FakeImageEmbeddingProvider(),
                legacy_normalizer=legacy_storage,
            )
            pipeline.ingest_image(
                image_bytes=image_bytes,
                card_id="new-card",
                file_path="/tmp/new-card.png",
            )
            after_counts = _legacy_counts(legacy_db)
            with sqlite3.connect(emb_db) as conn:
                embedding_rows = conn.execute("SELECT COUNT(*) FROM image_embeddings").fetchone()[0]

        self.assertEqual(before_counts, after_counts)
        self.assertEqual(embedding_rows, 1)


class ImageEmbeddingMatcherFlagTest(TestCase):
    def test_content_provider_uses_tag_strategy_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = ContentProvider(labeling_db_path=Path(tmp) / "cards.db")
        self.assertIsInstance(provider._matcher_strategy, TagBasedPairMatcherStrategy)  # pylint: disable=protected-access

    def test_content_provider_can_build_embedding_placeholder_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = ContentProvider(
                labeling_db_path=Path(tmp) / "cards.db",
                enable_image_embedding_matcher=True,
            )
        self.assertIsInstance(
            provider._matcher_strategy,  # pylint: disable=protected-access
            ImageEmbeddingPairMatcherStrategy,
        )

    def test_embedding_strategy_falls_back_when_embeddings_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = ContentProvider(
                labeling_db_path=Path(tmp) / "cards.db",
                image_embedding_db_path=Path(tmp) / "image_embeddings.db",
                enable_image_embedding_matcher=True,
            )
            cards = [_make_card("a"), _make_card("b")]
            provider._pair_selection_mode = "pairwise_topk"  # pylint: disable=protected-access
            provider._select_pairwise_topk_pair = lambda *_args, **_kwargs: (cards[0], cards[1])  # type: ignore[method-assign]  # pylint: disable=protected-access

            pair = provider._matcher_strategy.select_pair(  # pylint: disable=protected-access
                provider=provider,
                cards=cards,
                selected_categories=["anime"],
                recent_pairs=set(),
                chat_id=None,
            )
        self.assertEqual(pair, (cards[0], cards[1]))

    def test_embedding_strategy_supports_seed_mode_by_vector_similarity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cards_db = Path(tmp) / "cards.db"
            emb_db = Path(tmp) / "image_embeddings.db"
            provider = ContentProvider(
                labeling_db_path=cards_db,
                image_embedding_db_path=emb_db,
                enable_image_embedding_matcher=True,
                pair_selection_mode="seed_topk",
            )
            cards = [_make_card("seed"), _make_card("low"), _make_card("high")]
            image_storage = ImageEmbeddingStorage(emb_db)
            image_storage.init_db()
            image_storage.upsert_embedding(
                card_id="seed",
                image_sha256="sha-seed",
                file_path=None,
                embedding=np.asarray([1.0, 0.0], dtype=np.float32),
                model="clip-test",
            )
            image_storage.upsert_embedding(
                card_id="low",
                image_sha256="sha-low",
                file_path=None,
                embedding=np.asarray([0.1, 1.0], dtype=np.float32),
                model="clip-test",
            )
            image_storage.upsert_embedding(
                card_id="high",
                image_sha256="sha-high",
                file_path=None,
                embedding=np.asarray([0.99, 0.01], dtype=np.float32),
                model="clip-test",
            )
            provider._storage.get_recent_seed_counts = Mock(return_value={})  # type: ignore[method-assign]  # pylint: disable=protected-access
            provider._pick_seed_card = Mock(return_value=cards[0])  # type: ignore[method-assign]  # pylint: disable=protected-access

            pair = provider._matcher_strategy.select_pair(  # pylint: disable=protected-access
                provider=provider,
                cards=cards,
                selected_categories=["anime"],
                recent_pairs=set(),
                chat_id=42,
            )
        self.assertEqual(pair, (cards[0], cards[2]))
        provider._pick_seed_card.assert_called_once()  # pylint: disable=protected-access


class ImageEmbeddingProviderMathTest(TestCase):
    def test_l2_normalize_returns_unit_vector(self) -> None:
        vector = np.asarray([3.0, 4.0], dtype=np.float32)
        normalized = _l2_normalize(vector)
        self.assertAlmostEqual(float(np.linalg.norm(normalized)), 1.0, places=6)

    def test_l2_normalize_raises_for_zero_vector(self) -> None:
        with self.assertRaisesRegex(Exception, "norm"):
            _l2_normalize(np.asarray([0.0, 0.0], dtype=np.float32))


def _legacy_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            "cards": conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
            "card_tags": conn.execute("SELECT COUNT(*) FROM card_tags").fetchone()[0],
            "pair_history": conn.execute("SELECT COUNT(*) FROM pair_history").fetchone()[0],
        }
