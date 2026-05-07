from src.config import Settings, get_settings
from src.game.content import ContentProvider


def build_content_provider(settings: Settings | None = None) -> ContentProvider:
    effective_settings = settings or get_settings()
    return ContentProvider(
        labeling_db_path=effective_settings.labeling_db_path,
        pair_history_size=effective_settings.pair_history_size,
        pair_selection_mode=effective_settings.pair_selection_mode,
        pair_seed_retry_limit=effective_settings.pair_seed_retry_limit,
        pair_logprob_threshold=effective_settings.pair_logprob_threshold,
    )
