import numpy as np

from src.game.pair_selection import PairSelectionMode, normalize_pair_selection_mode
from src.labeling.models import CardRecord, PairResult
from src.labeling.storage import LabelingStorage


class PairSelector:
    def __init__(
        self,
        storage: LabelingStorage,
        threshold: float = 0.55,
        pair_history_size: int = 50,
        min_k: int = 5,
        max_k: int = 15,
        pair_selection_mode: PairSelectionMode | str = PairSelectionMode.PAIRWISE_TOPK,
        pair_seed_retry_limit: int = 3,
        pair_logprob_threshold: float = -2.3,
    ) -> None:
        self._storage = storage
        self._threshold = threshold
        self._pair_history_size = pair_history_size
        self._min_k = min_k
        self._max_k = max_k
        self._pair_selection_mode = normalize_pair_selection_mode(pair_selection_mode)
        self._pair_seed_retry_limit = max(0, pair_seed_retry_limit)
        self._pair_logprob_threshold = pair_logprob_threshold if pair_logprob_threshold <= 0 else -2.3

    def pick_pair(self, seed_id: str | None = None) -> PairResult:
        cards = self._storage.list_cards()
        if len(cards) < 2:
            raise ValueError("At least two cards are required to build a pair")
        cards_by_id = {card.id: card for card in cards}
        embeddings = dict(self._storage.load_all_embeddings())
        recent_pairs = self._storage.get_recent_pair_set(self._pair_history_size)

        if seed_id:
            seed_card = cards_by_id[seed_id]
            result = self._pick_seed_topk_pair(
                cards=cards,
                cards_by_id=cards_by_id,
                embeddings=embeddings,
                recent_pairs=recent_pairs,
                fixed_seed=seed_card,
            )
        elif self._pair_selection_mode == PairSelectionMode.SEED_TOPK:
            result = self._pick_seed_topk_pair(
                cards=cards,
                cards_by_id=cards_by_id,
                embeddings=embeddings,
                recent_pairs=recent_pairs,
            )
        else:
            result = self._pick_pairwise_topk_pair(cards_by_id=cards_by_id, embeddings=embeddings, recent_pairs=recent_pairs)

        if result is None:
            raise ValueError("No suitable candidate cards were found")

        card_a, card_b, similarity, k, candidates_count, breakdown = result

        self._storage.add_pair_history(card_a.id, card_b.id)
        self._storage.trim_pair_history(self._pair_history_size)
        return PairResult(
            card_a=card_a,
            card_b=card_b,
            similarity=float(similarity),
            k_used=k,
            candidates_count=candidates_count,
            breakdown=breakdown,
        )

    def _pick_seed_topk_pair(
        self,
        cards: list[CardRecord],
        cards_by_id: dict[str, CardRecord],
        embeddings: dict[str, np.ndarray],
        recent_pairs: set[tuple[str, str]],
        fixed_seed: CardRecord | None = None,
    ) -> tuple[CardRecord, CardRecord, float, int, int, dict[str, str | int | float]] | None:
        if fixed_seed is not None:
            seeds = [fixed_seed]
        else:
            retry_limit = min(len(cards), max(1, self._pair_seed_retry_limit))
            usage = self._storage.get_recent_seed_counts(self._pair_history_size)
            remaining = list(cards)
            seeds: list[CardRecord] = []
            while remaining and len(seeds) < retry_limit:
                weights = [1.0 / (1.0 + usage.get(card.id, 0)) for card in remaining]
                seed = random.choices(remaining, weights=weights, k=1)[0]
                seeds.append(seed)
                remaining = [card for card in remaining if card.id != seed.id]

        for seed_card in seeds:
            seed_vector = embeddings.get(seed_card.id)
            if seed_vector is None:
                continue
            scored = self._score_candidates(seed_card.id, seed_vector, cards_by_id, embeddings)
            filtered = self._filter_scored_candidates(seed_card.id, scored, recent_pairs)
            if not filtered:
                continue
            validated = self._pick_best_seed_candidate(filtered)
            if validated is None:
                continue
            pair_card, similarity, selected_logprob = validated
            return (
                seed_card,
                pair_card,
                similarity,
                1,
                len(filtered),
                {
                    "threshold": self._threshold,
                    "history_window": self._pair_history_size,
                    "seed_id": seed_card.id,
                    "pair_logprob_threshold": self._pair_logprob_threshold,
                    "selected_logprob": selected_logprob,
                    "selection_mode": PairSelectionMode.SEED_TOPK.value,
                },
            )
        return None

    def _pick_pairwise_topk_pair(
        self,
        cards_by_id: dict[str, CardRecord],
        embeddings: dict[str, np.ndarray],
        recent_pairs: set[tuple[str, str]],
    ) -> tuple[CardRecord, CardRecord, float, int, int, dict[str, str | int | float]] | None:
        scored = self._score_all_pairs(cards_by_id, embeddings)
        filtered: list[tuple[CardRecord, CardRecord, float]] = []
        for left, right, score in scored:
            if score < self._threshold:
                continue
            if tuple(sorted((left.id, right.id))) in recent_pairs:
                continue
            filtered.append((left, right, score))
        if not filtered:
            filtered = scored[:5]
        if not filtered:
            return None

        validated = self._pick_best_pair_candidate(filtered)
        if validated is not None:
            card_a, card_b, similarity, selected_logprob = validated
            return (
                card_a,
                card_b,
                similarity,
                1,
                len(filtered),
                {
                    "threshold": self._threshold,
                    "history_window": self._pair_history_size,
                    "pair_logprob_threshold": self._pair_logprob_threshold,
                    "selected_logprob": selected_logprob,
                    "selection_mode": PairSelectionMode.PAIRWISE_TOPK.value,
                },
            )

        card_a, card_b, similarity = filtered[0]
        return (
            card_a,
            card_b,
            similarity,
            1,
            len(filtered),
            {
                "threshold": self._threshold,
                "history_window": self._pair_history_size,
                "pair_logprob_threshold": self._pair_logprob_threshold,
                "selected_logprob": None,
                "selection_mode": PairSelectionMode.PAIRWISE_TOPK.value,
                "fallback_reason": "no_candidate_passed_logprob_threshold",
            },
        )

    @staticmethod
    def _stable_logprobs(scores: list[float]) -> list[float]:
        if not scores:
            return []
        values = np.asarray(scores, dtype=float)
        values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
        shifted = values - float(np.min(values))
        epsilon = 1e-12
        total = float(np.sum(shifted))
        if total <= epsilon:
            probs = np.full(shape=shifted.shape, fill_value=1.0 / float(shifted.size), dtype=float)
        else:
            probs = np.clip(shifted / total, epsilon, None)
            probs = probs / float(np.sum(probs))
        return np.log(probs).tolist()

    def _pick_best_seed_candidate(
        self,
        filtered: list[tuple[CardRecord, float]],
    ) -> tuple[CardRecord, float, float] | None:
        logprobs = self._stable_logprobs([score for _, score in filtered])
        for (candidate, score), logprob in zip(filtered, logprobs, strict=False):
            if logprob >= self._pair_logprob_threshold:
                return candidate, score, logprob
        return None

    def _pick_best_pair_candidate(
        self,
        filtered: list[tuple[CardRecord, CardRecord, float]],
    ) -> tuple[CardRecord, CardRecord, float, float] | None:
        logprobs = self._stable_logprobs([score for _, _, score in filtered])
        for (left, right, score), logprob in zip(filtered, logprobs, strict=False):
            if logprob >= self._pair_logprob_threshold:
                return left, right, score, logprob
        return None

    def _filter_scored_candidates(
        self,
        seed_id: str,
        scored: list[tuple[CardRecord, float]],
        recent_pairs: set[tuple[str, str]],
    ) -> list[tuple[CardRecord, float]]:
        filtered: list[tuple[CardRecord, float]] = []
        for candidate, score in scored:
            if score < self._threshold:
                continue
            pair_key = tuple(sorted((seed_id, candidate.id)))
            if pair_key in recent_pairs:
                continue
            filtered.append((candidate, score))
        if not filtered:
            filtered = scored[:5]
        return filtered

    @staticmethod
    def _score_candidates(
        seed_id: str,
        seed_vector: np.ndarray,
        cards_by_id: dict[str, CardRecord],
        embeddings: dict[str, np.ndarray],
    ) -> list[tuple[CardRecord, float]]:
        candidates: list[tuple[CardRecord, float]] = []
        seed_norm = np.linalg.norm(seed_vector)
        if seed_norm == 0:
            return candidates

        for card_id, vector in embeddings.items():
            if card_id == seed_id:
                continue
            denominator = seed_norm * np.linalg.norm(vector)
            if denominator == 0:
                continue
            score = float(np.dot(seed_vector, vector) / denominator)
            candidate = cards_by_id.get(card_id)
            if candidate is None:
                continue
            candidates.append((candidate, score))

        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates

    @staticmethod
    def _score_all_pairs(
        cards_by_id: dict[str, CardRecord],
        embeddings: dict[str, np.ndarray],
    ) -> list[tuple[CardRecord, CardRecord, float]]:
        scored: list[tuple[CardRecord, CardRecord, float]] = []
        card_ids = [card_id for card_id in cards_by_id if card_id in embeddings]
        for idx, left_id in enumerate(card_ids):
            left_vec = embeddings[left_id]
            left_norm = np.linalg.norm(left_vec)
            if left_norm == 0:
                continue
            left_card = cards_by_id[left_id]
            for right_id in card_ids[idx + 1 :]:
                right_vec = embeddings[right_id]
                denominator = left_norm * np.linalg.norm(right_vec)
                if denominator == 0:
                    continue
                score = float(np.dot(left_vec, right_vec) / denominator)
                right_card = cards_by_id[right_id]
                scored.append((left_card, right_card, score))
        scored.sort(key=lambda item: item[2], reverse=True)
        return scored

