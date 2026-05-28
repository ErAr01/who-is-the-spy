from __future__ import annotations

from pydantic import BaseModel, Field

from src.game.models import GameState


class MiniAppErrorBody(BaseModel):
    code: str
    message: str


class MiniAppErrorResponse(BaseModel):
    error: MiniAppErrorBody


class MiniAppUserDTO(BaseModel):
    user_id: int
    name: str


class MiniAppAuthRequest(BaseModel):
    init_data: str = Field(min_length=1)
    chat_id: int


class MiniAppAuthResponse(BaseModel):
    session_token: str
    expires_at: int
    user: MiniAppUserDTO


class MiniAppBaseActionRequest(BaseModel):
    chat_id: int


class MiniAppToggleCategoryRequest(MiniAppBaseActionRequest):
    category: str = Field(min_length=1)


class MiniAppVoteRequest(MiniAppBaseActionRequest):
    target_id: int


class MiniAppActionResponse(BaseModel):
    ok: bool = True
    version: int
    updated_at_ts: float | None


class MiniAppPlayerDTO(BaseModel):
    user_id: int
    name: str


class MiniAppSnapshotDataDTO(BaseModel):
    chat_id: int
    state: GameState
    admin_id: int
    players: list[MiniAppPlayerDTO]
    selected_categories: list[str]
    available_categories: list[str]
    votes_count: int
    version: int
    updated_at_ts: float | None
    is_admin: bool
    is_member: bool


class MiniAppSnapshotResponse(BaseModel):
    no_change: bool
    version: int
    updated_at_ts: float | None
    snapshot: MiniAppSnapshotDataDTO | None = None


class MiniAppRoleResponse(BaseModel):
    has_role: bool
    is_spy: bool | None = None
    role_name: str | None = None
    payload_type: str | None = None
    payload: str | None = None
