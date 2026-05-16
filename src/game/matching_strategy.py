import logging
from typing import TYPE_CHECKING, Protocol

import numpy as np

from src.game.pair_selection import PairSelectionMode
from src.labeling.models import CardRecord
from src.labeling.image_embedding_storage import ImageEmbeddingStorage

if TYPE_CHECKING:
    from src.game.content import ContentProvider

logger = logging.getLogger(__name__)


class PairMatcherStrategy(Protocol):
    def select_pair(
        self,
        provider: "ContentProvider",
        cards: list[CardRecord],
        selected_categories: list[str],
        recent_pairs: set[tuple[str, str]],
        *,
        chat_id: int | None = None,
    ) -> tuple[CardRecord, CardRecord] | None:
        raise NotImplementedError


class TagBasedPairMatcherStrategy:
    def select_pair(
        self,
        provider: "ContentProvider",
        cards: list[CardRecord],
        selected_categories: list[str],
        recent_pairs: set[tuple[str, str]],
        *,
        chat_id: int | None = None,
    ) -> tuple[CardRecord, CardRecord] | None:
        if provider._pair_selection_mode == PairSelectionMode.SEED_TOPK:  # pylint: disable=protected-access
            return provider._select_seed_topk_pair(  # pylint: disable=protected-access
                cards,
                selected_categories,
                recent_pairs,
                chat_id=chat_id,
            )
        return provider._select_pairwise_topk_pair(cards, selected_categories, recent_pairs)  # pylint: disable=protected-access


class ImageEmbeddingMatcherPlaceholderStrategy:
    # 📚 Что здесь происходит:
    # Это "точка расширения" под будущий image-embedding matchинг в рантайме.
    # Сейчас стратегия безопасно делегирует в tag-based логику, чтобы поведение игры
    # осталось прежним до полноценного внедрения нового алгоритма.
    #
    # ⚠️ Важно знать:
    # - Включение feature flag пока не активирует новый алгоритм автоматически.
    # - Такое поэтапное включение снижает риск регрессий в проде: сначала готовим
    #   контур данных и интерфейс, затем отдельно включаем новую стратегию.
    def __init__(self, fallback: PairMatcherStrategy) -> None:
        self._fallback = fallback

    def select_pair(
        self,
        provider: "ContentProvider",
        cards: list[CardRecord],
        selected_categories: list[str],
        recent_pairs: set[tuple[str, str]],
        *,
        chat_id: int | None = None,
    ) -> tuple[CardRecord, CardRecord] | None:
        logger.info(
            "Image embedding matcher feature flag enabled, using placeholder fallback strategy",
        )
        return self._fallback.select_pair(
            provider=provider,
            cards=cards,
            selected_categories=selected_categories,
            recent_pairs=recent_pairs,
            chat_id=chat_id,
        )


class ImageEmbeddingPairMatcherStrategy:
    # 📚 Что здесь происходит:
    # Эта стратегия подбирает пары по cosine similarity между эмбеддингами самих изображений
    # из отдельной image-embedding БД. Аналогия: если tag-based матчинг сравнивает "анкеты",
    # то здесь мы сравниваем "координаты картинок на карте визуального смысла".
    #
    # Почему так:
    # - Новый контур включается флагом и не ломает дефолтную механику.
    # - Если image-embedding данных недостаточно, стратегия безопасно откатывается в fallback.
    #
    # ⚠️ Важно знать:
    # - Cosine работает корректно, когда векторы нормализованы (L2).
    # - Нельзя смешивать в одном расчёте несовместимые модели/размерности эмбеддингов.
    def __init__(self, image_storage: ImageEmbeddingStorage, fallback: PairMatcherStrategy) -> None:
        self._image_storage = image_storage
        self._fallback = fallback

    def select_pair(
        self,
        provider: "ContentProvider",
        cards: list[CardRecord],
        selected_categories: list[str],
        recent_pairs: set[tuple[str, str]],
        *,
        chat_id: int | None = None,
    ) -> tuple[CardRecord, CardRecord] | None:
        embeddings = self._load_embeddings(cards)
        if len(embeddings) < 2:
            return self._fallback.select_pair(
                provider=provider,
                cards=cards,
                selected_categories=selected_categories,
                recent_pairs=recent_pairs,
                chat_id=chat_id,
            )

        if provider._pair_selection_mode == PairSelectionMode.SEED_TOPK:  # pylint: disable=protected-access
            return self._select_seed_embedding_pair(
                provider=provider,
                cards=cards,
                embeddings=embeddings,
                selected_categories=selected_categories,
                recent_pairs=recent_pairs,
                chat_id=chat_id,
            )
        return self._select_pairwise_embedding_pair(
            provider=provider,
            cards=cards,
            embeddings=embeddings,
            selected_categories=selected_categories,
            recent_pairs=recent_pairs,
            chat_id=chat_id,
        )

    def _select_pairwise_embedding_pair(
        self,
        *,
        provider: "ContentProvider",
        cards: list[CardRecord],
        embeddings: dict[str, np.ndarray],
        selected_categories: list[str],
        recent_pairs: set[tuple[str, str]],
        chat_id: int | None = None,
    ) -> tuple[CardRecord, CardRecord] | None:
        candidates = self._build_embedding_candidates(
            provider=provider,
            cards=cards,
            embeddings=embeddings,
            selected_categories=selected_categories,
            recent_pairs=recent_pairs,
            require_same_gender=True,
        )
        if not candidates:
            candidates = self._build_embedding_candidates(
                provider=provider,
                cards=cards,
                embeddings=embeddings,
                selected_categories=selected_categories,
                recent_pairs=recent_pairs,
                require_same_gender=False,
            )
        if not candidates:
            return self._fallback.select_pair(
                provider=provider,
                cards=cards,
                selected_categories=selected_categories,
                recent_pairs=recent_pairs,
                chat_id=chat_id,
            )
        validated_pair = provider._best_pair_by_logprob(candidates)  # pylint: disable=protected-access
        if validated_pair is not None:
            return validated_pair
        left, right, _ = candidates[0]
        return left, right

    def _select_seed_embedding_pair(
        self,
        *,
        provider: "ContentProvider",
        cards: list[CardRecord],
        embeddings: dict[str, np.ndarray],
        selected_categories: list[str],
        recent_pairs: set[tuple[str, str]],
        chat_id: int | None = None,
    ) -> tuple[CardRecord, CardRecord] | None:
        attempts_limit = min(len(cards), provider._pair_seed_retry_limit)  # pylint: disable=protected-access
        if attempts_limit <= 0:
            return self._select_pairwise_embedding_pair(
                provider=provider,
                cards=cards,
                embeddings=embeddings,
                selected_categories=selected_categories,
                recent_pairs=recent_pairs,
                chat_id=chat_id,
            )
        recent_seed_counts = provider._storage.get_recent_seed_counts(  # pylint: disable=protected-access
            provider._pair_history_size,  # pylint: disable=protected-access
            chat_id=chat_id,
        )
        attempted_seed_ids: set[str] = set()
        attempts = 0
        while attempts < attempts_limit and len(attempted_seed_ids) < len(cards):
            seed = provider._pick_seed_card(cards, recent_seed_counts, attempted_seed_ids)  # pylint: disable=protected-access
            attempted_seed_ids.add(seed.id)
            attempts += 1
            candidates = self._build_seed_embedding_candidates(
                provider=provider,
                seed=seed,
                cards=cards,
                embeddings=embeddings,
                selected_categories=selected_categories,
                recent_pairs=recent_pairs,
                require_same_gender=True,
            )
            if not candidates:
                candidates = self._build_seed_embedding_candidates(
                    provider=provider,
                    seed=seed,
                    cards=cards,
                    embeddings=embeddings,
                    selected_categories=selected_categories,
                    recent_pairs=recent_pairs,
                    require_same_gender=False,
                )
            if not candidates:
                continue
            partner = provider._best_seed_candidate_by_logprob(candidates)  # pylint: disable=protected-access
            if partner is not None:
                return seed, partner
        return self._select_pairwise_embedding_pair(
            provider=provider,
            cards=cards,
            embeddings=embeddings,
            selected_categories=selected_categories,
            recent_pairs=recent_pairs,
            chat_id=chat_id,
        )

    def _load_embeddings(self, cards: list[CardRecord]) -> dict[str, np.ndarray]:
        records = {record.card_id: record for record in self._image_storage.list_records()}
        card_ids = {card.id for card in cards}
        filtered: dict[str, np.ndarray] = {}
        for card_id, record in records.items():
            if card_id not in card_ids:
                continue
            filtered[card_id] = record.embedding.astype(np.float32)
        return filtered

    @staticmethod
    def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
        if left.shape != right.shape:
            return float("-inf")
        left_norm = float(np.linalg.norm(left))
        right_norm = float(np.linalg.norm(right))
        if left_norm <= 0.0 or right_norm <= 0.0:
            return float("-inf")
        score = float(np.dot(left, right) / (left_norm * right_norm))
        return score if np.isfinite(score) else float("-inf")

    def _build_embedding_candidates(
        self,
        *,
        provider: "ContentProvider",
        cards: list[CardRecord],
        embeddings: dict[str, np.ndarray],
        selected_categories: list[str],
        recent_pairs: set[tuple[str, str]],
        require_same_gender: bool,
    ) -> list[tuple[CardRecord, CardRecord, float]]:
        scored: list[tuple[CardRecord, CardRecord, float]] = []
        for idx in range(len(cards)):
            left = cards[idx]
            left_vector = embeddings.get(left.id)
            if left_vector is None:
                continue
            for right in cards[idx + 1 :]:
                right_vector = embeddings.get(right.id)
                if right_vector is None:
                    continue
                if provider._is_recent_pair(left.id, right.id, recent_pairs):  # pylint: disable=protected-access
                    continue
                if not provider._is_category_pair_allowed(  # pylint: disable=protected-access
                    left.dataset_categories,
                    right.dataset_categories,
                    selected_categories,
                ):
                    continue
                if require_same_gender and provider._effective_gender(  # pylint: disable=protected-access
                    left.tags.gender_presentation
                ) != provider._effective_gender(  # pylint: disable=protected-access
                    right.tags.gender_presentation
                ):
                    continue
                similarity = self._cosine_similarity(left_vector, right_vector)
                if not np.isfinite(similarity):
                    continue
                scored.append((left, right, similarity))
        scored.sort(key=lambda item: item[2], reverse=True)
        return scored

    def _build_seed_embedding_candidates(
        self,
        *,
        provider: "ContentProvider",
        seed: CardRecord,
        cards: list[CardRecord],
        embeddings: dict[str, np.ndarray],
        selected_categories: list[str],
        recent_pairs: set[tuple[str, str]],
        require_same_gender: bool,
    ) -> list[tuple[CardRecord, float]]:
        seed_vector = embeddings.get(seed.id)
        if seed_vector is None:
            return []
        scored: list[tuple[CardRecord, float]] = []
        for candidate in cards:
            if candidate.id == seed.id:
                continue
            candidate_vector = embeddings.get(candidate.id)
            if candidate_vector is None:
                continue
            if provider._is_recent_pair(seed.id, candidate.id, recent_pairs):  # pylint: disable=protected-access
                continue
            if not provider._is_category_pair_allowed(  # pylint: disable=protected-access
                seed.dataset_categories,
                candidate.dataset_categories,
                selected_categories,
            ):
                continue
            if require_same_gender and provider._effective_gender(  # pylint: disable=protected-access
                seed.tags.gender_presentation
            ) != provider._effective_gender(  # pylint: disable=protected-access
                candidate.tags.gender_presentation
            ):
                continue
            similarity = self._cosine_similarity(seed_vector, candidate_vector)
            if not np.isfinite(similarity):
                continue
            scored.append((candidate, similarity))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored
