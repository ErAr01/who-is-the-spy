from enum import StrEnum


class PairSelectionMode(StrEnum):
    PAIRWISE_TOPK = "pairwise_topk"
    SEED_TOPK = "seed_topk"


def normalize_pair_selection_mode(raw_value: object) -> PairSelectionMode:
    if isinstance(raw_value, PairSelectionMode):
        return raw_value
    if isinstance(raw_value, str):
        value = raw_value.strip().lower()
        if value in {PairSelectionMode.SEED_TOPK.value, "seed_logprob"}:
            return PairSelectionMode.SEED_TOPK
        if value in {PairSelectionMode.PAIRWISE_TOPK.value, "pairwise_logprob"}:
            return PairSelectionMode.PAIRWISE_TOPK
    return PairSelectionMode.PAIRWISE_TOPK
