from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic.types import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.game.pair_selection import normalize_pair_selection_mode


class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_vision_model: str = Field(default="gpt-4o-mini", alias="OPENAI_VISION_MODEL")
    openai_embedding_model: str = Field(default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL")
    labeling_db_path: Path = Field(default=Path("data/images/cards.db"), alias="LABELING_DB_PATH")
    image_embedding_db_path: Path = Field(
        default=Path("data/images/image_embeddings.db"),
        alias="IMAGE_EMBEDDING_DB_PATH",
    )
    image_embedding_provider: str = Field(default="local_clip", alias="IMAGE_EMBEDDING_PROVIDER")
    local_clip_model_name: str = Field(default="openai/clip-vit-base-patch32", alias="LOCAL_CLIP_MODEL_NAME")
    image_embedding_device: str = Field(default="cpu", alias="IMAGE_EMBEDDING_DEVICE")
    image_embedding_batch_size: int = Field(default=8, alias="IMAGE_EMBEDDING_BATCH_SIZE")
    enable_image_embedding_matcher: bool = Field(default=False, alias="ENABLE_IMAGE_EMBEDDING_MATCHER")
    pair_similarity_threshold: float = Field(default=0.55, alias="PAIR_SIMILARITY_THRESHOLD")
    pair_history_size: int = Field(default=50, alias="PAIR_HISTORY_SIZE")
    pair_selection_mode: str = Field(default="pairwise_topk", alias="PAIR_SELECTION_MODE")
    pair_seed_retry_limit: int = Field(default=3, alias="PAIR_SEED_RETRY_LIMIT")
    pair_logprob_threshold: float = Field(default=-2.3, alias="PAIR_LOGPROB_THRESHOLD")
    metrics_enabled: bool = Field(default=False, alias="METRICS_ENABLED")
    metrics_host: str = Field(default="0.0.0.0", alias="METRICS_HOST")
    metrics_port: int = Field(default=8001, alias="METRICS_PORT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("pair_selection_mode", mode="before")
    @classmethod
    def _validate_pair_selection_mode(cls, value: object) -> str:
        return normalize_pair_selection_mode(value).value

    @field_validator("pair_seed_retry_limit", mode="before")
    @classmethod
    def _validate_pair_seed_retry_limit(cls, value: object) -> int:
        if isinstance(value, bool):
            return 3
        try:
            parsed = int(str(value).strip()) if isinstance(value, str) else int(value)
        except (TypeError, ValueError):
            return 3
        return parsed if parsed >= 0 else 3

    @field_validator("pair_logprob_threshold", mode="before")
    @classmethod
    def _validate_pair_logprob_threshold(cls, value: object) -> float:
        if isinstance(value, bool):
            return -2.3
        try:
            parsed = float(str(value).strip()) if isinstance(value, str) else float(value)
        except (TypeError, ValueError):
            return -2.3
        return parsed if parsed <= 0.0 else -2.3

    @field_validator("image_embedding_provider", mode="before")
    @classmethod
    def _validate_image_embedding_provider(cls, value: object) -> str:
        if value is None:
            return "local_clip"
        normalized = str(value).strip().lower()
        return normalized if normalized in {"local_clip", "openai"} else "local_clip"

    @field_validator("image_embedding_batch_size", mode="before")
    @classmethod
    def _validate_image_embedding_batch_size(cls, value: object) -> int:
        if isinstance(value, bool):
            return 8
        try:
            parsed = int(str(value).strip()) if isinstance(value, str) else int(value)
        except (TypeError, ValueError):
            return 8
        return parsed if parsed > 0 else 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
