import io
import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

import numpy as np
from PIL import Image

from src.labeling.llm.base import DescriptionResult, EmbeddingResult, TaggingResult
from src.labeling.llm.deepseek_describer import filter_name_leaks
from src.labeling.models import CardTags
from src.labeling.pipeline import LabelingPipeline
from src.labeling.storage import LabelingStorage


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


def _save_card(
    storage: LabelingStorage,
    card_id: str,
    description: str | None = None,
    facts: list[str] | None = None,
    description_model: str | None = None,
):
    image_bytes = _make_test_image_bytes((10, 20, 30))
    normalized, thumb, mime = storage.normalize_image(image_bytes)
    return storage.save_card(
        card_id=card_id,
        name=card_id,
        wiki_url=None,
        image_bytes=normalized,
        image_mime=mime,
        thumbnail_bytes=thumb,
        image_sha256=storage.sha256_digest(normalized) + card_id,
        tags=_make_tags(),
        appearance_text=f"{card_id} appearance",
        embedding=np.asarray([0.1, 0.2, 0.3], dtype=np.float32),
        embedding_model="test-model",
        vision_model="test-model",
        dataset_categories=["anime"],
        description=description,
        facts=facts,
        description_model=description_model,
    )


class _FakeTagger:
    vision_model = "fake-vision"

    def tag_image(self, image_bytes: bytes, name: str) -> TaggingResult:
        return TaggingResult(tags=_make_tags(), usage={}, estimated_cost_usd=0.0)

    def build_appearance_text(self, tags: CardTags) -> str:
        return "fake appearance"


class _FakeEmbedder:
    embedding_model = "fake-embedding"

    def embed_text(self, text: str) -> EmbeddingResult:
        return EmbeddingResult(
            vector=np.asarray([0.1, 0.2, 0.3], dtype=np.float32),
            usage={},
            estimated_cost_usd=0.0,
        )


class _FakeDescriber:
    model = "fake-deepseek"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0
        self.last_appearance_text: str | None = None
        self.last_wiki_url: str | None = None
        self.last_notes: str | None = None

    def describe(
        self,
        name: str,
        categories: list[str],
        appearance_text: str | None = None,
        wiki_url: str | None = None,
        notes: str | None = None,
    ) -> DescriptionResult:
        self.calls += 1
        self.last_appearance_text = appearance_text
        self.last_wiki_url = wiki_url
        self.last_notes = notes
        if self.fail:
            raise RuntimeError("deepseek unavailable")
        return DescriptionResult(
            description=f"Описание {name}",
            facts=[f"Факт {index} ({', '.join(categories)})" for index in range(10)],
            usage={"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
            estimated_cost_usd=0.00025,
        )


_LEGACY_CARDS_DDL = """
CREATE TABLE cards (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    wiki_url           TEXT,
    image_bytes        BLOB NOT NULL,
    image_mime         TEXT NOT NULL,
    thumbnail_bytes    BLOB NOT NULL,
    image_sha256       TEXT NOT NULL UNIQUE,
    tags_json          TEXT NOT NULL,
    appearance_text    TEXT NOT NULL,
    embedding          BLOB NOT NULL,
    embedding_model    TEXT NOT NULL,
    vision_model       TEXT NOT NULL,
    labeled_at         TEXT NOT NULL,
    notes              TEXT
)
"""


class DescriptionSchemaMigrationTest(TestCase):
    def test_init_db_adds_description_columns_to_legacy_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cards.db"
            conn = sqlite3.connect(db_path)
            conn.execute(_LEGACY_CARDS_DDL)
            conn.execute(
                """
                INSERT INTO cards (
                    id, name, wiki_url, image_bytes, image_mime, thumbnail_bytes, image_sha256,
                    tags_json, appearance_text, embedding, embedding_model, vision_model, labeled_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-card",
                    "Legacy Card",
                    None,
                    b"img",
                    "image/jpeg",
                    b"thumb",
                    "sha-legacy",
                    _make_tags().model_dump_json(),
                    "legacy appearance",
                    np.asarray([0.1], dtype=np.float32).tobytes(),
                    "test-model",
                    "test-model",
                    "2026-01-01T00:00:00+00:00",
                    None,
                ),
            )
            conn.commit()
            conn.close()

            storage = LabelingStorage(db_path)
            storage.init_db()

            conn = sqlite3.connect(db_path)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(cards)").fetchall()}
            conn.close()
            self.assertIn("description", columns)
            self.assertIn("facts_json", columns)
            self.assertIn("description_model", columns)
            self.assertIn("described_at", columns)

            card = storage.get_card("legacy-card")
            assert card is not None
            self.assertIsNone(card.description)
            self.assertEqual(card.facts, [])
            self.assertIsNone(card.description_model)
            self.assertIsNone(card.described_at)


class DescriptionStorageTest(TestCase):
    def _storage(self, tmp: str) -> LabelingStorage:
        storage = LabelingStorage(Path(tmp) / "cards.db")
        storage.init_db()
        return storage

    def test_save_card_roundtrip_with_description_and_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._storage(tmp)
            facts = [f"Факт {index}" for index in range(10)]
            _save_card(storage, "card-1", description="Описание", facts=facts, description_model="deepseek-chat")

            card = storage.get_card("card-1")
            assert card is not None
            self.assertEqual(card.description, "Описание")
            self.assertEqual(card.facts, facts)
            self.assertEqual(card.description_model, "deepseek-chat")
            self.assertIsNotNone(card.described_at)

    def test_save_card_without_description_preserves_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._storage(tmp)
            _save_card(storage, "card-1", description="Описание", facts=["Факт"], description_model="deepseek-chat")
            # Повторное сохранение без описания (сценарий relabel/re-embed).
            _save_card(storage, "card-1")

            card = storage.get_card("card-1")
            assert card is not None
            self.assertEqual(card.description, "Описание")
            self.assertEqual(card.facts, ["Факт"])
            self.assertEqual(card.description_model, "deepseek-chat")

    def test_update_card_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._storage(tmp)
            _save_card(storage, "card-1")

            updated = storage.update_card_description(
                card_id="card-1",
                description="Новое описание",
                facts=["Факт 1", "Факт 2"],
                description_model="deepseek-chat",
            )
            self.assertEqual(updated.description, "Новое описание")
            self.assertEqual(updated.facts, ["Факт 1", "Факт 2"])
            self.assertIsNotNone(updated.described_at)
            # Остальные поля не тронуты.
            self.assertEqual(updated.appearance_text, "card-1 appearance")

    def test_update_card_description_unknown_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._storage(tmp)
            with self.assertRaises(ValueError):
                storage.update_card_description(
                    card_id="missing",
                    description="x",
                    facts=[],
                    description_model="deepseek-chat",
                )

    def test_list_card_ids_missing_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._storage(tmp)
            _save_card(storage, "with-description", description="Описание", facts=["Факт"])
            _save_card(storage, "without-description")

            self.assertEqual(storage.list_card_ids_missing_description(), ["without-description"])


class DescriptionPipelineTest(TestCase):
    def test_ingest_stores_description_and_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = LabelingStorage(Path(tmp) / "cards.db")
            describer = _FakeDescriber()
            pipeline = LabelingPipeline(storage, _FakeTagger(), _FakeEmbedder(), describer=describer)

            result = pipeline.ingest_card(
                image_bytes=_make_test_image_bytes((1, 2, 3)),
                name="Test Hero",
                categories=["anime"],
            )
            self.assertEqual(describer.calls, 1)
            self.assertEqual(result.card.description, "Описание Test Hero")
            self.assertEqual(len(result.card.facts), 10)
            self.assertEqual(result.card.description_model, "fake-deepseek")
            # Якоря с картинки доходят до describer'а — без них модель путает тёзок.
            self.assertEqual(describer.last_appearance_text, "fake appearance")

    def test_ingest_survives_describer_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = LabelingStorage(Path(tmp) / "cards.db")
            pipeline = LabelingPipeline(storage, _FakeTagger(), _FakeEmbedder(), describer=_FakeDescriber(fail=True))

            result = pipeline.ingest_card(
                image_bytes=_make_test_image_bytes((1, 2, 3)),
                name="Test Hero",
            )
            self.assertFalse(result.skipped_duplicate)
            self.assertIsNone(result.card.description)
            self.assertEqual(result.card.facts, [])

    def test_ingest_without_describer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = LabelingStorage(Path(tmp) / "cards.db")
            pipeline = LabelingPipeline(storage, _FakeTagger(), _FakeEmbedder())

            result = pipeline.ingest_card(
                image_bytes=_make_test_image_bytes((1, 2, 3)),
                name="Test Hero",
            )
            self.assertIsNone(result.card.description)

    def test_describe_card_backfill_and_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = LabelingStorage(Path(tmp) / "cards.db")
            storage.init_db()
            _save_card(storage, "card-1")
            describer = _FakeDescriber()
            pipeline = LabelingPipeline(storage, None, None, describer=describer)

            first = pipeline.describe_card("card-1")
            self.assertFalse(first.skipped_existing)
            self.assertEqual(first.card.description, "Описание card-1")
            self.assertEqual(len(first.card.facts), 10)
            # Категории карточки передаются в describer.
            self.assertIn("anime", first.card.facts[0])
            # Якоря с карточки тоже передаются — иначе модель путает тёзок.
            self.assertEqual(describer.last_appearance_text, "card-1 appearance")

            second = pipeline.describe_card("card-1")
            self.assertTrue(second.skipped_existing)
            self.assertEqual(describer.calls, 1)

            third = pipeline.describe_card("card-1", force=True)
            self.assertFalse(third.skipped_existing)
            self.assertEqual(describer.calls, 2)

    def test_relabel_preserves_description_and_skips_describer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = LabelingStorage(Path(tmp) / "cards.db")
            storage.init_db()
            describer = _FakeDescriber()
            pipeline = LabelingPipeline(storage, _FakeTagger(), _FakeEmbedder(), describer=describer)
            ingested = pipeline.ingest_card(
                image_bytes=_make_test_image_bytes((1, 2, 3)),
                name="Test Hero",
                categories=["anime"],
            )
            self.assertEqual(describer.calls, 1)
            original_description = ingested.card.description

            relabeled = pipeline.relabel_card(ingested.card.id)

            # relabel пере-тэггирует изображение, но не перегенерирует описание.
            self.assertEqual(describer.calls, 1)
            self.assertEqual(relabeled.description, original_description)
            self.assertEqual(len(relabeled.facts), 10)

    def test_list_describe_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = LabelingStorage(Path(tmp) / "cards.db")
            storage.init_db()
            _save_card(storage, "described", description="Описание", facts=["Факт"])
            _save_card(storage, "missing")
            pipeline = LabelingPipeline(storage, None, None, describer=_FakeDescriber())

            self.assertEqual(pipeline.list_describe_targets(), ["missing"])
            self.assertEqual(set(pipeline.list_describe_targets(force=True)), {"described", "missing"})


class FilterNameLeaksTest(TestCase):
    def test_drops_facts_with_name_tokens(self) -> None:
        facts = [
            "Гарри живёт в чулане под лестницей",
            "Носит круглые очки",
            "Учился в школе магии",
            "Лучший друг — Рон",
        ]
        filtered = filter_name_leaks(facts, "Гарри Поттер")
        self.assertEqual(filtered, ["Носит круглые очки", "Учился в школе магии", "Лучший друг — Рон"])

    def test_case_insensitive(self) -> None:
        filtered = filter_name_leaks(["ГАРРИ носит очки", "Носит очки"], "гарри поттер")
        self.assertEqual(filtered, ["Носит очки"])

    def test_short_tokens_ignored(self) -> None:
        # Токены короче 3 символов не фильтруются — иначе отсеется любой текст.
        filtered = filter_name_leaks(["Лидер группы", "Любит музыку"], "Лу Ан")
        self.assertEqual(filtered, ["Лидер группы", "Любит музыку"])

    def test_latin_name(self) -> None:
        filtered = filter_name_leaks(["Naruto ест рамен", "Ест рамен"], "Naruto Uzumaki")
        self.assertEqual(filtered, ["Ест рамен"])

    def test_no_false_positive_on_substrings(self) -> None:
        # Короткие имена не должны вырезать факты, где имя — лишь подстрока слова.
        self.assertEqual(
            filter_name_leaks(["Живёт в коробке, в которой спит"], "Кот"),
            ["Живёт в коробке, в которой спит"],
        )
        self.assertEqual(
            filter_name_leaks(["Электрон вращается вокруг ядра"], "Рон"),
            ["Электрон вращается вокруг ядра"],
        )
        self.assertEqual(
            filter_name_leaks(["Носит налевую перчатку"], "Лев"),
            ["Носит налевую перчатку"],
        )

    def test_short_name_exact_word_still_filtered(self) -> None:
        filtered = filter_name_leaks(["Этот кот живёт в коробке", "Живёт в коробке"], "Кот")
        self.assertEqual(filtered, ["Живёт в коробке"])

    def test_declensions_of_long_tokens_filtered(self) -> None:
        # Для длинных токенов ловим склонения: «Поттера», «Поттеру».
        filtered = filter_name_leaks(
            ["Враг Поттера с детства", "Учился в школе магии"],
            "Гарри Поттер",
        )
        self.assertEqual(filtered, ["Учился в школе магии"])
