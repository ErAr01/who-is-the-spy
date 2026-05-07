from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class AnalyticsEventName(StrEnum):
    """Канонические имена аналитических событий."""

    GAME_CREATED = "game_created"
    GAME_STARTED = "game_started"
    ROUND_FINISHED = "round_finished"
    GAME_CANCELLED = "game_cancelled"
    PLAYER_JOINED = "player_joined"
    VOTING_STARTED = "voting_started"
    VOTE_CAST = "vote_cast"
    CATEGORY_TOGGLED = "category_toggled"
    USER_STARTED_PRIVATE = "user_started_private"
    ROLE_DELIVERY_FAILED = "role_delivery_failed"
    CONTENT_SELECTION_FAILED = "content_selection_failed"
    HANDLER_EXCEPTION = "handler_exception"


@dataclass(slots=True, frozen=True)
class AnalyticsEvent:
    """Типизированный слой аналитического события."""

    event_name: AnalyticsEventName | str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    chat_id: int | None = None
    user_id: int | None = None
    game_id: str | None = None
    round_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.payload, dict):
            raise TypeError("payload must be dict[str, Any]")
        _ensure_json_serializable(self.payload)

        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        event_name = self.event_name.value if isinstance(self.event_name, AnalyticsEventName) else self.event_name
        return {
            "event_name": event_name,
            "timestamp": self.timestamp.isoformat(),
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "game_id": self.game_id,
            "round_id": self.round_id,
            "payload": self.payload,
        }


def _ensure_json_serializable(payload: dict[str, Any]) -> None:
    try:
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must be JSON-serializable") from exc
