import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import ANY, Mock, patch

from src.config import Settings
from src.game.content import ContentProvider
from src.game.pair_selection import PairSelectionMode
from src.labeling.models import CardRecord, CardTags
from src.labeling.similarity import PairSelector
from src.labeling.storage import LabelingStorage


def _make_tags(gender: str) -> CardTags:
    return CardTags(
        character_type="real_person",
        franchise_kind="none",
        gender_presentation=gender,
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


def _make_card(card_id: str, *, gender: str = "male", categories: list[str] | None = None) -> CardRecord:
    return CardRecord(
        id=card_id,
        name=card_id,
        wiki_url=None,
        image_sha256=f"sha-{card_id}",
        tags=_make_tags(gender),
        appearance_text=f"{card_id} appearance",
        embedding_model="test",
        vision_model="test",
        labeled_at=datetime.now(UTC),
        dataset_categories=categories or ["anime"],
    )


class PairSelectionSettingsTest(TestCase):
    def test_invalid_mode_falls_back_to_pairwise(self) -> None:
        settings = Settings(BOT_TOKEN="token", PAIR_SELECTION_MODE="unexpected_mode")
        self.assertEqual(settings.pair_selection_mode, PairSelectionMode.PAIRWISE_TOPK.value)

    def test_seed_retry_limit_invalid_value_falls_back_to_default(self) -> None:
        settings = Settings(BOT_TOKEN="token", PAIR_SEED_RETRY_LIMIT="invalid")
        self.assertEqual(settings.pair_seed_retry_limit, 3)

    def test_logprob_threshold_invalid_value_falls_back_to_default(self) -> None:
        settings = Settings(BOT_TOKEN="token", PAIR_LOGPROB_THRESHOLD="invalid")
        self.assertEqual(settings.pair_logprob_threshold, -2.3)

    def test_logprob_threshold_positive_value_falls_back_to_default(self) -> None:
        settings = Settings(BOT_TOKEN="token", PAIR_LOGPROB_THRESHOLD="0.5")
        self.assertEqual(settings.pair_logprob_threshold, -2.3)

    def test_logprob_mode_alias_is_normalized(self) -> None:
        settings = Settings(BOT_TOKEN="token", PAIR_SELECTION_MODE="seed_logprob")
        self.assertEqual(settings.pair_selection_mode, PairSelectionMode.SEED_TOPK.value)

    def test_metrics_enabled_parses_boolean_env_value(self) -> None:
        settings = Settings(BOT_TOKEN="token", METRICS_ENABLED="true")
        self.assertTrue(settings.metrics_enabled)


class SeedTopKBehaviorTest(TestCase):
    def _provider_with_mocked_storage(self) -> tuple[ContentProvider, Mock]:
        provider = ContentProvider.__new__(ContentProvider)
        storage = Mock()
        provider._storage = storage
        provider._pair_history_size = 50
        provider._pair_seed_retry_limit = 3
        provider._pair_logprob_threshold = -2.3
        provider._pair_selection_mode = PairSelectionMode.SEED_TOPK
        return provider, storage

    def test_seed_weights_follow_anti_repeat_counts(self) -> None:
        provider, _ = self._provider_with_mocked_storage()
        cards = [_make_card("a"), _make_card("b"), _make_card("c")]
        counts = {"a": 5, "b": 0, "c": 1}

        with patch("src.game.content.random.choices", return_value=[cards[1]]) as choices_mock:
            chosen = provider._pick_seed_card(cards, counts, excluded_ids=set())

        self.assertEqual(chosen.id, "b")
        self.assertEqual(choices_mock.call_args.kwargs["weights"], [1.0 / 6.0, 1.0, 0.5])

    def test_seed_retries_then_falls_back_to_pairwise(self) -> None:
        provider, _ = self._provider_with_mocked_storage()
        cards = [_make_card("seed-a"), _make_card("seed-b"), _make_card("pair-c")]
        provider._pair_seed_retry_limit = 2

        with (
            patch.object(provider._storage, "get_recent_seed_counts", return_value={"seed-a": 3, "seed-b": 1}),
            patch.object(provider, "_pick_seed_card", side_effect=[cards[0], cards[1]]) as pick_seed_mock,
            patch.object(provider, "_build_seed_candidates", return_value=[]),
            patch.object(provider, "_select_pairwise_topk_pair", return_value=(cards[1], cards[2])) as fallback_mock,
        ):
            pair = provider._select_seed_topk_pair(cards, selected_categories=["anime"], recent_pairs=set())

        self.assertEqual(pair, (cards[1], cards[2]))
        self.assertEqual(pick_seed_mock.call_count, 2)
        fallback_mock.assert_called_once()

    def test_seed_skips_candidates_below_logprob_threshold(self) -> None:
        provider, _ = self._provider_with_mocked_storage()
        cards = [_make_card("seed"), _make_card("pair-low"), _make_card("pair-high")]
        provider._pair_logprob_threshold = -1.0

        with (
            patch.object(provider._storage, "get_recent_seed_counts", return_value={}),
            patch.object(provider, "_pick_seed_card", return_value=cards[0]),
            patch.object(
                provider,
                "_build_seed_candidates",
                return_value=[(cards[1], 0.91), (cards[2], 0.89)],
            ),
            patch.object(provider, "_stable_logprobs", return_value=[-1.5, -0.3]),
        ):
            pair = provider._select_seed_topk_pair(cards, selected_categories=["anime"], recent_pairs=set())

        self.assertEqual(pair, (cards[0], cards[2]))

    def test_pairwise_uses_best_validated_logprob_candidate(self) -> None:
        provider, _ = self._provider_with_mocked_storage()
        cards = [_make_card("a"), _make_card("b"), _make_card("c")]
        provider._pair_logprob_threshold = -1.0

        with (
            patch.object(
                provider,
                "_build_scored_candidates",
                return_value=[(cards[0], cards[1], 0.9), (cards[0], cards[2], 0.88)],
            ),
            patch.object(provider, "_stable_logprobs", return_value=[-1.5, -0.2]),
        ):
            pair = provider._select_pairwise_topk_pair(cards, selected_categories=["anime"], recent_pairs=set())

        self.assertEqual(pair, (cards[0], cards[2]))

    def test_pairwise_falls_back_to_best_score_when_no_logprob_match(self) -> None:
        provider, _ = self._provider_with_mocked_storage()
        cards = [_make_card("a"), _make_card("b"), _make_card("c")]
        provider._pair_logprob_threshold = -0.1

        with (
            patch.object(
                provider,
                "_build_scored_candidates",
                return_value=[(cards[0], cards[1], 0.95), (cards[1], cards[2], 0.9)],
            ),
            patch.object(provider, "_stable_logprobs", return_value=[-1.2, -0.8]),
        ):
            pair = provider._select_pairwise_topk_pair(cards, selected_categories=["anime"], recent_pairs=set())

        self.assertEqual(pair, (cards[0], cards[1]))

    def test_group_mode_uses_ttl_filtered_history(self) -> None:
        provider, storage = self._provider_with_mocked_storage()
        provider._pair_selection_mode = PairSelectionMode.PAIRWISE_TOPK
        cards = [_make_card("a"), _make_card("b"), _make_card("c")]
        now = datetime.now(UTC)
        storage.list_cards_by_dataset_categories.return_value = cards
        storage.get_recent_pair_set.return_value = {("a", "b")}
        provider._select_pairwise_topk_pair = Mock(return_value=(cards[0], cards[2]))

        result = provider.get_random_image_pair(categories=["anime"], chat_id=777)

        self.assertEqual(result.civilian, "a")
        self.assertEqual(result.spy, "c")
        storage.get_recent_pair_set.assert_called_once_with(limit=None, chat_id=777, since=ANY)
        used_since = storage.get_recent_pair_set.call_args.kwargs["since"]
        self.assertTrue(now - timedelta(hours=24, minutes=1) <= used_since <= datetime.now(UTC))
        storage.add_pair_history.assert_called_once_with("a", "c", chat_id=777)

    def test_group_mode_uses_earliest_pair_fallback_after_ttl(self) -> None:
        provider, storage = self._provider_with_mocked_storage()
        provider._pair_selection_mode = PairSelectionMode.PAIRWISE_TOPK
        cards = [_make_card("a"), _make_card("b"), _make_card("c")]
        storage.list_cards_by_dataset_categories.return_value = cards
        storage.get_recent_pair_set.return_value = {("a", "b"), ("a", "c"), ("b", "c")}
        provider._select_pairwise_topk_pair = Mock(return_value=None)
        provider._select_earliest_available_pair = Mock(return_value=(cards[1], cards[2]))

        result = provider.get_random_image_pair(categories=["anime"], chat_id=1001)

        self.assertEqual(result.civilian, "b")
        self.assertEqual(result.spy, "c")
        provider._select_earliest_available_pair.assert_called_once_with(cards, ["anime"], 1001)
        storage.add_pair_history.assert_called_once_with("b", "c", chat_id=1001)

    def test_earliest_fallback_uses_oldest_last_used_pair(self) -> None:
        provider, storage = self._provider_with_mocked_storage()
        cards = [_make_card("a"), _make_card("b"), _make_card("c")]
        oldest = datetime.now(UTC) - timedelta(hours=20)
        newest = datetime.now(UTC) - timedelta(hours=1)
        with patch.object(
            provider,
            "_build_scored_candidates",
            return_value=[(cards[0], cards[1], 0.9), (cards[1], cards[2], 0.7)],
        ):
            storage.get_pair_last_used_map.return_value = {
                ("a", "b"): newest,
                ("b", "c"): oldest,
            }
            pair = provider._select_earliest_available_pair(cards, ["anime"], chat_id=42)

        self.assertEqual(pair, (cards[1], cards[2]))


class PairSelectorLogprobBehaviorTest(TestCase):
    def _build_selector(self, threshold: float = -1.0) -> PairSelector:
        return PairSelector(storage=Mock(), threshold=0.0, pair_logprob_threshold=threshold)

    def test_pairwise_picks_best_candidate_that_passes_logprob_threshold(self) -> None:
        selector = self._build_selector(threshold=-1.0)
        card_a = _make_card("a")
        card_b = _make_card("b")
        card_c = _make_card("c")
        cards_by_id = {card.id: card for card in [card_a, card_b, card_c]}

        with (
            patch.object(
                selector,
                "_score_all_pairs",
                return_value=[(card_a, card_b, 0.93), (card_a, card_c, 0.9)],
            ),
            patch.object(selector, "_stable_logprobs", return_value=[-1.4, -0.6]),
        ):
            result = selector._pick_pairwise_topk_pair(cards_by_id, embeddings={}, recent_pairs=set())

        self.assertIsNotNone(result)
        picked_a, picked_b, _, _, _, breakdown = result  # type: ignore[misc]
        self.assertEqual((picked_a.id, picked_b.id), ("a", "c"))
        self.assertEqual(breakdown["selected_logprob"], -0.6)

    def test_pairwise_uses_best_score_fallback_when_no_logprob_match(self) -> None:
        selector = self._build_selector(threshold=-0.1)
        card_a = _make_card("a")
        card_b = _make_card("b")
        card_c = _make_card("c")
        cards_by_id = {card.id: card for card in [card_a, card_b, card_c]}

        with (
            patch.object(
                selector,
                "_score_all_pairs",
                return_value=[(card_a, card_b, 0.95), (card_b, card_c, 0.91)],
            ),
            patch.object(selector, "_stable_logprobs", return_value=[-1.5, -0.7]),
        ):
            result = selector._pick_pairwise_topk_pair(cards_by_id, embeddings={}, recent_pairs=set())

        self.assertIsNotNone(result)
        picked_a, picked_b, _, _, _, breakdown = result  # type: ignore[misc]
        self.assertEqual((picked_a.id, picked_b.id), ("a", "b"))
        self.assertEqual(breakdown["fallback_reason"], "no_candidate_passed_logprob_threshold")


class PairHistoryStorageTest(TestCase):
    def test_pair_history_is_chat_scoped_ttl_filtered_and_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = LabelingStorage(Path(tmp) / "cards.db")
            storage.init_db()
            now = datetime.now(UTC)
            storage.add_pair_history("b", "a", chat_id=1, used_at=now - timedelta(hours=1))
            storage.add_pair_history("a", "c", chat_id=1, used_at=now - timedelta(hours=30))
            storage.add_pair_history("a", "b", chat_id=2, used_at=now - timedelta(hours=1))

            recent = storage.get_recent_pair_set(limit=None, chat_id=1, since=now - timedelta(hours=24))

        self.assertEqual(recent, {("a", "b")})

