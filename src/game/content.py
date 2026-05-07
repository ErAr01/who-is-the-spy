import random
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from src.labeling.models import CardRecord, CardTags
from src.labeling.storage import LabelingStorage
from src.labeling.taxonomy import GenderPresentation
from src.game.pair_selection import PairSelectionMode, normalize_pair_selection_mode


class PayloadType(StrEnum):
    PHOTO = "photo"


@dataclass(slots=True)
class ContentPair:
    theme: str
    civilian: str
    spy: str
    payload_type: PayloadType
    civilian_name: str
    spy_name: str
    civilian_wiki_url: str | None = None
    spy_wiki_url: str | None = None


class ContentProvider:
    _PAIR_TTL = timedelta(hours=24)
    _PAIR_SCORE_WEIGHTS: dict[str, float] = {
        "hair_color": 8.0,
        "age_group": 5.0,
        "skin_tone": 4.0,
        "hair_length": 3.0,
        "hair_style": 3.0,
        "eye_color": 3.0,
        "facial_hair": 2.0,
        "glasses": 1.5,
        "headwear": 1.5,
        "clothing_primary_color": 1.0,
        "mood": 0.5,
        "pose": 0.5,
    }

    def __init__(
        self,
        labeling_db_path: Path,
        pair_history_size: int = 50,
        pair_selection_mode: PairSelectionMode | str = PairSelectionMode.PAIRWISE_TOPK,
        pair_seed_retry_limit: int = 3,
        pair_logprob_threshold: float = -2.3,
    ) -> None:
        self._storage = LabelingStorage(labeling_db_path)
        self._storage.init_db()
        self._pair_history_size = max(0, pair_history_size)
        self._pair_selection_mode = normalize_pair_selection_mode(pair_selection_mode)
        self._pair_seed_retry_limit = max(0, pair_seed_retry_limit)
        self._pair_logprob_threshold = pair_logprob_threshold if pair_logprob_threshold <= 0 else -2.3

    def get_available_categories(self) -> list[str]:
        return self._storage.list_dataset_categories()

    def get_random_image_pair(self, categories: list[str] | None = None, chat_id: int | None = None) -> ContentPair:
        cards = self._storage.list_cards_by_dataset_categories(categories)
        if len(cards) < 2:
            raise ValueError("Недостаточно карточек в выбранных категориях")

        normalized_categories = self._normalize_categories(categories)
        recent_pairs = self._resolve_recent_pairs(chat_id=chat_id)
        if self._pair_selection_mode == PairSelectionMode.SEED_TOPK:
            pair = self._select_seed_topk_pair(cards, normalized_categories, recent_pairs, chat_id=chat_id)
        else:
            pair = self._select_pairwise_topk_pair(cards, normalized_categories, recent_pairs)
        if pair is None and chat_id is not None:
            pair = self._select_earliest_available_pair(cards, normalized_categories, chat_id)
        if pair is None:
            raise ValueError("Не удалось подобрать пару с учетом фильтров категорий и истории")

        civilian, spy = pair
        self.register_pair(civilian.id, spy.id, chat_id=chat_id)
        theme = ", ".join(categories or []) or "Все категории"
        return self._build_content_pair(theme=theme, civilian=civilian, spy=spy)

    def get_image_bytes(self, card_id: str) -> bytes | None:
        return self._storage.get_image_bytes(card_id)

    def register_pair(self, civilian_id: str, spy_id: str, chat_id: int | None = None) -> None:
        self._storage.add_pair_history(civilian_id, spy_id, chat_id=chat_id)

    def _resolve_recent_pairs(self, chat_id: int | None) -> set[tuple[str, str]]:
        if chat_id is None:
            return self._storage.get_recent_pair_set(self._pair_history_size)
        cutoff = datetime.now(UTC) - self._PAIR_TTL
        return self._storage.get_recent_pair_set(limit=None, chat_id=chat_id, since=cutoff)

    @staticmethod
    def _build_content_pair(theme: str, civilian: CardRecord, spy: CardRecord) -> ContentPair:
        return ContentPair(
            theme=theme,
            civilian=civilian.id,
            spy=spy.id,
            payload_type=PayloadType.PHOTO,
            civilian_name=civilian.name,
            spy_name=spy.name,
            civilian_wiki_url=civilian.wiki_url,
            spy_wiki_url=spy.wiki_url,
        )

    @staticmethod
    def _normalize_categories(categories: list[str] | None) -> list[str]:
        if not categories:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for category in categories:
            cleaned = category.strip().lower()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

    @staticmethod
    def _compute_top_k(total_count: int) -> int:
        candidate = round(0.2 * total_count)
        return max(5, min(15, candidate))

    @staticmethod
    def _stable_logprobs(scores: list[float]) -> list[float]:
        if not scores:
            return []
        sanitized = [score if math.isfinite(score) else 0.0 for score in scores]
        min_score = min(sanitized)
        shifted = [score - min_score for score in sanitized]
        total = sum(shifted)
        epsilon = 1e-12
        if total <= epsilon:
            probability = 1.0 / len(shifted)
            probs = [probability] * len(shifted)
        else:
            probs = [max(value / total, epsilon) for value in shifted]
            normalizer = sum(probs)
            probs = [value / normalizer for value in probs]
        return [math.log(probability) for probability in probs]

    def _best_pair_by_logprob(
        self,
        candidates: list[tuple[CardRecord, CardRecord, float]],
    ) -> tuple[CardRecord, CardRecord] | None:
        logprobs = self._stable_logprobs([score for _, _, score in candidates])
        for (left, right, _), logprob in zip(candidates, logprobs, strict=False):
            if logprob >= self._pair_logprob_threshold:
                return left, right
        return None

    def _best_seed_candidate_by_logprob(self, candidates: list[tuple[CardRecord, float]]) -> CardRecord | None:
        logprobs = self._stable_logprobs([score for _, score in candidates])
        for (candidate, _), logprob in zip(candidates, logprobs, strict=False):
            if logprob >= self._pair_logprob_threshold:
                return candidate
        return None

    def _build_scored_candidates(
        self,
        cards: list[CardRecord],
        selected_categories: list[str],
        recent_pairs: set[tuple[str, str]],
        require_same_gender: bool,
    ) -> list[tuple[CardRecord, CardRecord, float]]:
        scored: list[tuple[CardRecord, CardRecord, float]] = []
        for idx in range(len(cards)):
            left = cards[idx]
            for right in cards[idx + 1 :]:
                if self._is_recent_pair(left.id, right.id, recent_pairs):
                    continue
                if not self._is_category_pair_allowed(left.dataset_categories, right.dataset_categories, selected_categories):
                    continue
                if require_same_gender and self._effective_gender(left.tags.gender_presentation) != self._effective_gender(
                    right.tags.gender_presentation
                ):
                    continue
                score = self._pair_score(left.tags, right.tags)
                scored.append((left, right, score))
        scored.sort(key=lambda item: item[2], reverse=True)
        return scored

    def _select_pairwise_topk_pair(
        self,
        cards: list[CardRecord],
        selected_categories: list[str],
        recent_pairs: set[tuple[str, str]],
    ) -> tuple[CardRecord, CardRecord] | None:
        candidates = self._build_scored_candidates(
            cards=cards,
            selected_categories=selected_categories,
            recent_pairs=recent_pairs,
            require_same_gender=True,
        )
        if not candidates:
            candidates = self._build_scored_candidates(
                cards=cards,
                selected_categories=selected_categories,
                recent_pairs=recent_pairs,
                require_same_gender=False,
            )
        if not candidates:
            return None
        validated_pair = self._best_pair_by_logprob(candidates)
        if validated_pair is not None:
            return validated_pair
        civilian, spy, _ = candidates[0]
        return civilian, spy

    def _select_seed_topk_pair(
        self,
        cards: list[CardRecord],
        selected_categories: list[str],
        recent_pairs: set[tuple[str, str]],
        chat_id: int | None = None,
    ) -> tuple[CardRecord, CardRecord] | None:
        attempts_limit = min(len(cards), self._pair_seed_retry_limit)
        if attempts_limit <= 0:
            return self._select_pairwise_topk_pair(cards, selected_categories, recent_pairs)

        recent_seed_counts = self._storage.get_recent_seed_counts(self._pair_history_size, chat_id=chat_id)
        attempted_seed_ids: set[str] = set()
        attempts = 0
        while attempts < attempts_limit and len(attempted_seed_ids) < len(cards):
            seed = self._pick_seed_card(cards, recent_seed_counts, attempted_seed_ids)
            attempted_seed_ids.add(seed.id)
            attempts += 1

            candidates = self._build_seed_candidates(
                seed=seed,
                cards=cards,
                selected_categories=selected_categories,
                recent_pairs=recent_pairs,
                require_same_gender=True,
            )
            if not candidates:
                candidates = self._build_seed_candidates(
                    seed=seed,
                    cards=cards,
                    selected_categories=selected_categories,
                    recent_pairs=recent_pairs,
                    require_same_gender=False,
                )
            if not candidates:
                continue
            partner = self._best_seed_candidate_by_logprob(candidates)
            if partner is not None:
                return seed, partner

        return self._select_pairwise_topk_pair(cards, selected_categories, recent_pairs)

    def _select_earliest_available_pair(
        self,
        cards: list[CardRecord],
        selected_categories: list[str],
        chat_id: int,
    ) -> tuple[CardRecord, CardRecord] | None:
        candidates = self._build_scored_candidates(
            cards=cards,
            selected_categories=selected_categories,
            recent_pairs=set(),
            require_same_gender=True,
        )
        if not candidates:
            candidates = self._build_scored_candidates(
                cards=cards,
                selected_categories=selected_categories,
                recent_pairs=set(),
                require_same_gender=False,
            )
        if not candidates:
            return None
        pair_last_used = self._storage.get_pair_last_used_map(chat_id=chat_id)
        ranked = sorted(
            candidates,
            key=lambda item: (
                pair_last_used.get(tuple(sorted((item[0].id, item[1].id))), datetime.min.replace(tzinfo=UTC)),
                -item[2],
                item[0].id,
                item[1].id,
            ),
        )
        earliest = ranked[0]
        return earliest[0], earliest[1]

    def _pick_seed_card(
        self,
        cards: list[CardRecord],
        recent_seed_counts: dict[str, int],
        excluded_ids: set[str],
    ) -> CardRecord:
        available = [card for card in cards if card.id not in excluded_ids]
        if not available:
            raise ValueError("No cards available for seed selection")
        weights = [1.0 / (1.0 + recent_seed_counts.get(card.id, 0)) for card in available]
        return random.choices(available, weights=weights, k=1)[0]

    def _build_seed_candidates(
        self,
        seed: CardRecord,
        cards: list[CardRecord],
        selected_categories: list[str],
        recent_pairs: set[tuple[str, str]],
        require_same_gender: bool,
    ) -> list[tuple[CardRecord, float]]:
        scored: list[tuple[CardRecord, float]] = []
        for candidate in cards:
            if candidate.id == seed.id:
                continue
            if self._is_recent_pair(seed.id, candidate.id, recent_pairs):
                continue
            if not self._is_category_pair_allowed(seed.dataset_categories, candidate.dataset_categories, selected_categories):
                continue
            if require_same_gender and self._effective_gender(seed.tags.gender_presentation) != self._effective_gender(
                candidate.tags.gender_presentation
            ):
                continue
            score = self._pair_score(seed.tags, candidate.tags)
            scored.append((candidate, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored

    @staticmethod
    def _is_recent_pair(card_a: str, card_b: str, recent_pairs: set[tuple[str, str]]) -> bool:
        left, right = sorted((card_a, card_b))
        return (left, right) in recent_pairs

    @staticmethod
    def _is_category_pair_allowed(
        left_categories: list[str],
        right_categories: list[str],
        selected_categories: list[str],
    ) -> bool:
        if len(selected_categories) < 2:
            return True
        selected = set(selected_categories)
        left_selected = [category for category in left_categories if category in selected]
        right_selected = [category for category in right_categories if category in selected]
        if not left_selected or not right_selected:
            return False
        return any(left_category != right_category for left_category in left_selected for right_category in right_selected)

    @classmethod
    def _pair_score(cls, left_tags: CardTags, right_tags: CardTags) -> float:
        score = 0.0
        for field_name, weight in cls._PAIR_SCORE_WEIGHTS.items():
            if getattr(left_tags, field_name) == getattr(right_tags, field_name):
                score += weight

        left_features = {item.strip().lower() for item in left_tags.notable_features if item.strip()}
        right_features = {item.strip().lower() for item in right_tags.notable_features if item.strip()}
        overlap_count = len(left_features & right_features)
        score += min(2.0, overlap_count * 0.5)
        return score

    @staticmethod
    def _effective_gender(gender_presentation: GenderPresentation | str) -> str:
        male_like = {
            GenderPresentation.MALE.value,
            GenderPresentation.ANDROGYNOUS.value,
            GenderPresentation.NON_HUMAN.value,
            GenderPresentation.UNKNOWN.value,
        }
        value = (
            gender_presentation.value
            if isinstance(gender_presentation, GenderPresentation)
            else str(gender_presentation).strip().lower()
        )
        return "male" if value in male_like else "female"
