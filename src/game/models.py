from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class GameState(StrEnum):
    LOBBY = "lobby"
    CUSTOM_SETUP = "custom_setup"
    PLAYING = "playing"
    VOTING = "voting"
    FINISHED = "finished"


class GameMode(StrEnum):
    WORDS = "words"
    BLANK = "blank"
    CUSTOM = "custom"
    IMAGE_DB = "image_db"


class PayloadType(StrEnum):
    TEXT = "text"
    PHOTO = "photo"


@dataclass(slots=True)
class Player:
    user_id: int
    name: str


@dataclass(slots=True)
class Game:
    chat_id: int
    admin_id: int
    state: GameState
    mode: GameMode
    players: list[Player] = field(default_factory=list)
    spy_id: int | None = None
    payload_type: PayloadType = PayloadType.PHOTO
    theme: str | None = None
    civilian_payload: str | None = None
    spy_payload: str | None = None
    civilian_name: str | None = None
    spy_name: str | None = None
    civilian_wiki_url: str | None = None
    spy_wiki_url: str | None = None
    civilian_search_url: str | None = None
    spy_search_url: str | None = None
    selected_categories: list[str] = field(default_factory=list)
    available_categories: list[str] = field(default_factory=list)
    votes: dict[int, int] = field(default_factory=dict)
    lobby_message_id: int | None = None
    speaking_order: list[int] = field(default_factory=list)
    round_started_at_ts: float | None = None

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["state"] = self.state.value
        raw["mode"] = self.mode.value
        raw["payload_type"] = self.payload_type.value
        return raw

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Game":
        return cls(
            chat_id=payload["chat_id"],
            admin_id=payload["admin_id"],
            state=GameState(payload["state"]),
            mode=GameMode(payload["mode"]),
            players=[Player(**item) for item in payload.get("players", [])],
            spy_id=payload.get("spy_id"),
            payload_type=PayloadType(payload.get("payload_type", PayloadType.PHOTO.value)),
            theme=payload.get("theme"),
            civilian_payload=payload.get("civilian_payload"),
            spy_payload=payload.get("spy_payload"),
            civilian_name=payload.get("civilian_name"),
            spy_name=payload.get("spy_name"),
            civilian_wiki_url=payload.get("civilian_wiki_url"),
            spy_wiki_url=payload.get("spy_wiki_url"),
            civilian_search_url=payload.get("civilian_search_url"),
            spy_search_url=payload.get("spy_search_url"),
            selected_categories=[str(v) for v in payload.get("selected_categories", [])],
            available_categories=[str(v) for v in payload.get("available_categories", [])],
            votes={int(k): int(v) for k, v in payload.get("votes", {}).items()},
            lobby_message_id=payload.get("lobby_message_id"),
            speaking_order=[int(v) for v in payload.get("speaking_order", [])],
            round_started_at_ts=(
                float(payload["round_started_at_ts"])
                if payload.get("round_started_at_ts") is not None
                else None
            ),
        )
