from __future__ import annotations

from typing import Awaitable, Callable, TypeVar

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.analytics import AnalyticsEmitter, AnalyticsEvent, AnalyticsEventName
from src.bot import AppContext
from src.config import Settings
from src.game.models import Game
from src.miniapp.auth import TelegramInitDataValidator
from src.miniapp.dto import (
    MiniAppBaseActionRequest,
    MiniAppActionResponse,
    MiniAppAuthRequest,
    MiniAppAuthResponse,
    MiniAppErrorBody,
    MiniAppErrorResponse,
    MiniAppRoleResponse,
    MiniAppRoundRoleCardDTO,
    MiniAppRoundRolesResponse,
    MiniAppSnapshotDataDTO,
    MiniAppSnapshotResponse,
    MiniAppTestPairCardDTO,
    MiniAppTestPairResponse,
    MiniAppToggleCategoryRequest,
    MiniAppPlayerDTO,
    MiniAppUserDTO,
    MiniAppVoteRequest,
)
from src.miniapp.errors import MiniAppError
from src.miniapp.service import GameService, MiniAppActionResult
from src.miniapp.session import MiniAppSessionClaims, MiniAppSessionManager

_security = HTTPBearer(auto_error=False)
_T = TypeVar("_T")


class MiniAppApiContext:
    def __init__(
        self,
        *,
        auth_validator: TelegramInitDataValidator,
        session_manager: MiniAppSessionManager,
        game_service: GameService,
        analytics_emitter: AnalyticsEmitter,
    ) -> None:
        self.auth_validator = auth_validator
        self.session_manager = session_manager
        self.game_service = game_service
        self.analytics_emitter = analytics_emitter


def build_miniapp_api(settings: Settings, app_context: AppContext, analytics_emitter: AnalyticsEmitter) -> FastAPI:
    if settings.miniapp_session_secret is None or not settings.miniapp_session_secret.get_secret_value().strip():
        raise RuntimeError("MINIAPP_SESSION_SECRET is required when MINIAPP_ENABLED=true.")

    api_context = MiniAppApiContext(
        auth_validator=TelegramInitDataValidator(
            bot_token=settings.bot_token,
            auth_ttl_seconds=settings.miniapp_init_data_ttl_seconds,
        ),
        session_manager=MiniAppSessionManager(
            secret=settings.miniapp_session_secret.get_secret_value(),
            ttl_seconds=settings.miniapp_session_ttl_seconds,
        ),
        game_service=GameService(
            repo=app_context.redis_repo,
            bot=app_context.bot,
            analytics_emitter=analytics_emitter,
            settings=settings,
        ),
        analytics_emitter=analytics_emitter,
    )

    app = FastAPI(title="Who Is The Spy MiniApp API", version="1.0.0")
    app.state.miniapp = api_context
    app.add_exception_handler(MiniAppError, _miniapp_error_handler)

    router = APIRouter(prefix="/api/v1/miniapp")

    @router.post("/auth", response_model=MiniAppAuthResponse, responses={401: {"model": MiniAppErrorResponse}})
    async def auth(payload: MiniAppAuthRequest, request: Request) -> MiniAppAuthResponse:
        context = _get_context(request)
        try:
            user = context.auth_validator.validate(payload.init_data)
        except MiniAppError as exc:
            context.analytics_emitter.emit(
                AnalyticsEvent(
                    event_name=AnalyticsEventName.MINIAPP_AUTH_FAIL,
                    chat_id=payload.chat_id,
                    payload={"code": exc.code},
                )
            )
            raise
        token, expires_at = context.session_manager.issue_token(
            user_id=user.user_id,
            chat_id=payload.chat_id,
            name=user.full_name,
        )
        context.analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.MINIAPP_AUTH_SUCCESS,
                chat_id=payload.chat_id,
                user_id=user.user_id,
                game_id=str(payload.chat_id),
                payload={"expires_at": expires_at},
            )
        )
        return MiniAppAuthResponse(
            session_token=token,
            expires_at=expires_at,
            user=MiniAppUserDTO(user_id=user.user_id, name=user.full_name),
        )

    @router.get("/game", response_model=MiniAppSnapshotResponse, responses={404: {"model": MiniAppErrorResponse}})
    async def game_snapshot(
        request: Request,
        chat_id: int = Query(...),
        since_version: int | None = Query(default=None, ge=0),
        claims: MiniAppSessionClaims = Depends(_auth_dependency),
    ) -> MiniAppSnapshotResponse:
        _ensure_chat_access(chat_id=chat_id, claims=claims)
        context = _get_context(request)
        snapshot = await context.game_service.get_snapshot(
            chat_id=chat_id,
            user_id=claims.user_id,
            user_name=claims.name,
            since_version=since_version,
        )
        game = snapshot.game
        if game is None:
            raise MiniAppError(code="game_not_found", message="Игра не найдена.", status_code=404)
        if snapshot.no_change:
            return MiniAppSnapshotResponse(
                no_change=True,
                version=game.version,
                updated_at_ts=game.updated_at_ts,
                snapshot=None,
            )
        return MiniAppSnapshotResponse(
            no_change=False,
            version=game.version,
            updated_at_ts=game.updated_at_ts,
            snapshot=_build_snapshot(game=game, user_id=claims.user_id),
        )

    @router.post("/join", response_model=MiniAppActionResponse, responses={403: {"model": MiniAppErrorResponse}})
    async def join(
        request: Request,
        payload: MiniAppBaseActionRequest,
        claims: MiniAppSessionClaims = Depends(_auth_dependency),
    ) -> MiniAppActionResponse:
        _ensure_chat_access(chat_id=payload.chat_id, claims=claims)
        context = _get_context(request)
        result = await _run_action(
            context=context,
            action_name="join",
            chat_id=payload.chat_id,
            user_id=claims.user_id,
            executor=lambda: context.game_service.join(
                chat_id=payload.chat_id,
                user_id=claims.user_id,
                name=claims.name,
            ),
        )
        return _build_action_response(result)

    @router.post("/leave", response_model=MiniAppActionResponse)
    async def leave(
        request: Request,
        payload: MiniAppBaseActionRequest,
        claims: MiniAppSessionClaims = Depends(_auth_dependency),
    ) -> MiniAppActionResponse:
        _ensure_chat_access(chat_id=payload.chat_id, claims=claims)
        context = _get_context(request)
        result = await _run_action(
            context=context,
            action_name="leave",
            chat_id=payload.chat_id,
            user_id=claims.user_id,
            executor=lambda: context.game_service.leave(
                chat_id=payload.chat_id,
                user_id=claims.user_id,
            ),
        )
        return _build_action_response(result)

    @router.post("/categories/toggle", response_model=MiniAppActionResponse)
    async def toggle_category(
        payload: MiniAppToggleCategoryRequest,
        request: Request,
        claims: MiniAppSessionClaims = Depends(_auth_dependency),
    ) -> MiniAppActionResponse:
        _ensure_chat_access(chat_id=payload.chat_id, claims=claims)
        context = _get_context(request)
        result = await _run_action(
            context=context,
            action_name="categories/toggle",
            chat_id=payload.chat_id,
            user_id=claims.user_id,
            executor=lambda: context.game_service.toggle_category(
                chat_id=payload.chat_id,
                user_id=claims.user_id,
                category=payload.category.strip().lower(),
            ),
        )
        return _build_action_response(result)

    @router.post("/start", response_model=MiniAppActionResponse)
    async def start(
        payload: MiniAppBaseActionRequest,
        request: Request,
        claims: MiniAppSessionClaims = Depends(_auth_dependency),
    ) -> MiniAppActionResponse:
        _ensure_chat_access(chat_id=payload.chat_id, claims=claims)
        context = _get_context(request)
        result = await _run_action(
            context=context,
            action_name="start",
            chat_id=payload.chat_id,
            user_id=claims.user_id,
            executor=lambda: context.game_service.start(chat_id=payload.chat_id, user_id=claims.user_id),
        )
        return _build_action_response(result)

    @router.post("/voting/open", response_model=MiniAppActionResponse)
    async def voting_open(
        payload: MiniAppBaseActionRequest,
        request: Request,
        claims: MiniAppSessionClaims = Depends(_auth_dependency),
    ) -> MiniAppActionResponse:
        _ensure_chat_access(chat_id=payload.chat_id, claims=claims)
        context = _get_context(request)
        result = await _run_action(
            context=context,
            action_name="voting/open",
            chat_id=payload.chat_id,
            user_id=claims.user_id,
            executor=lambda: context.game_service.open_voting(chat_id=payload.chat_id, user_id=claims.user_id),
        )
        return _build_action_response(result)

    @router.post("/votes", response_model=MiniAppActionResponse)
    async def votes(
        payload: MiniAppVoteRequest,
        request: Request,
        claims: MiniAppSessionClaims = Depends(_auth_dependency),
    ) -> MiniAppActionResponse:
        _ensure_chat_access(chat_id=payload.chat_id, claims=claims)
        context = _get_context(request)
        result = await _run_action(
            context=context,
            action_name="votes",
            chat_id=payload.chat_id,
            user_id=claims.user_id,
            executor=lambda: context.game_service.cast_vote(
                chat_id=payload.chat_id,
                user_id=claims.user_id,
                target_id=payload.target_id,
            ),
        )
        return _build_action_response(result)

    @router.post("/voting/close", response_model=MiniAppActionResponse)
    async def voting_close(
        payload: MiniAppBaseActionRequest,
        request: Request,
        claims: MiniAppSessionClaims = Depends(_auth_dependency),
    ) -> MiniAppActionResponse:
        _ensure_chat_access(chat_id=payload.chat_id, claims=claims)
        context = _get_context(request)
        result = await _run_action(
            context=context,
            action_name="voting/close",
            chat_id=payload.chat_id,
            user_id=claims.user_id,
            executor=lambda: context.game_service.close_voting(chat_id=payload.chat_id, user_id=claims.user_id),
        )
        return _build_action_response(result)

    @router.post("/cancel", response_model=MiniAppActionResponse)
    async def cancel(
        payload: MiniAppBaseActionRequest,
        request: Request,
        claims: MiniAppSessionClaims = Depends(_auth_dependency),
    ) -> MiniAppActionResponse:
        _ensure_chat_access(chat_id=payload.chat_id, claims=claims)
        context = _get_context(request)
        result = await _run_action(
            context=context,
            action_name="cancel",
            chat_id=payload.chat_id,
            user_id=claims.user_id,
            executor=lambda: context.game_service.cancel(chat_id=payload.chat_id, user_id=claims.user_id),
        )
        return _build_action_response(result)

    @router.get("/me/role", response_model=MiniAppRoleResponse)
    async def me_role(
        request: Request,
        chat_id: int = Query(...),
        claims: MiniAppSessionClaims = Depends(_auth_dependency),
    ) -> MiniAppRoleResponse:
        _ensure_chat_access(chat_id=chat_id, claims=claims)
        context = _get_context(request)
        payload = await _run_action(
            context=context,
            action_name="me/role",
            chat_id=chat_id,
            user_id=claims.user_id,
            executor=lambda: context.game_service.get_my_role(chat_id=chat_id, user_id=claims.user_id),
        )
        return MiniAppRoleResponse(**payload)

    @router.get("/round/roles", response_model=MiniAppRoundRolesResponse)
    async def round_roles(
        request: Request,
        chat_id: int = Query(...),
        claims: MiniAppSessionClaims = Depends(_auth_dependency),
    ) -> MiniAppRoundRolesResponse:
        _ensure_chat_access(chat_id=chat_id, claims=claims)
        context = _get_context(request)
        payload = await _run_action(
            context=context,
            action_name="round/roles",
            chat_id=chat_id,
            user_id=claims.user_id,
            executor=lambda: context.game_service.get_round_roles(chat_id=chat_id, user_id=claims.user_id),
        )
        return MiniAppRoundRolesResponse(
            theme=payload["theme"],
            civilian=MiniAppRoundRoleCardDTO(**payload["civilian"]),
            spy=MiniAppRoundRoleCardDTO(**payload["spy"]),
        )

    @router.get("/testpair", response_model=MiniAppTestPairResponse)
    async def testpair(
        request: Request,
        categories: list[str] | None = Query(default=None),
        claims: MiniAppSessionClaims = Depends(_auth_dependency),
    ) -> MiniAppTestPairResponse:
        if claims.chat_id != claims.user_id:
            raise MiniAppError(
                code="private_mode_only",
                message="Этот endpoint доступен только в личном режиме Mini App.",
                status_code=403,
            )
        context = _get_context(request)
        payload = await _run_action(
            context=context,
            action_name="testpair",
            chat_id=claims.chat_id,
            user_id=claims.user_id,
            executor=lambda: context.game_service.generate_test_pair(
                user_id=claims.user_id,
                categories=categories,
            ),
        )
        return MiniAppTestPairResponse(
            theme=payload["theme"],
            available_categories=payload["available_categories"],
            selected_categories=payload["selected_categories"],
            civilian=MiniAppTestPairCardDTO(
                card_id=payload["civilian_id"],
                name=payload["civilian_name"],
                image_url=payload["civilian_image_url"],
                wiki_url=payload["civilian_wiki_url"],
                search_url=payload["civilian_search_url"],
            ),
            spy=MiniAppTestPairCardDTO(
                card_id=payload["spy_id"],
                name=payload["spy_name"],
                image_url=payload["spy_image_url"],
                wiki_url=payload["spy_wiki_url"],
                search_url=payload["spy_search_url"],
            ),
        )

    @router.get("/cards/{card_id}/image")
    async def card_image(card_id: str, request: Request) -> Response:
        context = _get_context(request)
        image_bytes = context.game_service.get_card_image(card_id)
        return Response(content=image_bytes, media_type="image/jpeg")

    app.include_router(router)
    return app


def _get_context(request: Request) -> MiniAppApiContext:
    context = getattr(request.app.state, "miniapp", None)
    if context is None:
        raise HTTPException(status_code=500, detail="MiniApp context is not configured.")
    return context


async def _auth_dependency(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> MiniAppSessionClaims:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise MiniAppError(code="session_required", message="Требуется Bearer session token.", status_code=401)
    context = _get_context(request)
    return context.session_manager.verify_token(credentials.credentials)


def _ensure_chat_access(*, chat_id: int, claims: MiniAppSessionClaims) -> None:
    if claims.chat_id != chat_id:
        raise MiniAppError(
            code="chat_scope_violation",
            message="Сессия не принадлежит этому чату.",
            status_code=403,
        )


async def _miniapp_error_handler(_: Request, exc: MiniAppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=MiniAppErrorResponse(error=MiniAppErrorBody(code=exc.code, message=exc.message)).model_dump(),
    )


async def _run_action(
    *,
    context: MiniAppApiContext,
    action_name: str,
    chat_id: int,
    user_id: int,
    executor: Callable[[], Awaitable[_T]],
) -> _T:
    try:
        return await executor()
    except MiniAppError as exc:
        context.analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.MINIAPP_ACTION_FAILED,
                chat_id=chat_id,
                user_id=user_id,
                game_id=str(chat_id),
                payload={"action": action_name, "code": exc.code},
            )
        )
        raise


def _build_snapshot(*, game: Game, user_id: int) -> MiniAppSnapshotDataDTO:
    players = [MiniAppPlayerDTO(user_id=player.user_id, name=player.name) for player in game.players]
    round_player_ids = list(game.round_player_ids) if game.round_player_ids else [player.user_id for player in game.players]
    return MiniAppSnapshotDataDTO(
        chat_id=game.chat_id,
        state=game.state,
        admin_id=game.admin_id,
        players=players,
        round_player_ids=round_player_ids,
        selected_categories=list(game.selected_categories),
        available_categories=list(game.available_categories),
        votes_count=len(game.votes),
        version=game.version,
        updated_at_ts=game.updated_at_ts,
        is_admin=user_id == game.admin_id,
        is_member=user_id in {player.user_id for player in game.players},
        is_in_current_round=user_id in set(round_player_ids),
    )


def _build_action_response(result: MiniAppActionResult) -> MiniAppActionResponse:
    return MiniAppActionResponse(
        version=result.version,
        updated_at_ts=result.updated_at_ts,
        note_code=result.note_code,
        note_message=result.note_message,
    )


