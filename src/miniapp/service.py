from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from aiogram import Bot

from src.analytics import AnalyticsEmitter, AnalyticsEvent, AnalyticsEventName
from src.config import Settings, get_settings
from src.game.engine import build_google_search_url
from src.game.lifecycle import is_lobby_expired, reset_to_fresh_lobby, touch_activity
from src.game.models import Game, GameState, Player
from src.game.provider_factory import build_content_provider
from src.handlers.admin_actions import cancel_game, close_voting, open_voting, start_round
from src.miniapp.errors import MiniAppError


@dataclass(slots=True, frozen=True)
class MiniAppActionResult:
    version: int
    updated_at_ts: float | None
    note_code: str | None = None
    note_message: str | None = None


@dataclass(slots=True, frozen=True)
class MiniAppSnapshotResult:
    no_change: bool
    game: Game | None


class GameService:
    def __init__(
        self,
        *,
        repo: object,
        bot: Bot,
        analytics_emitter: AnalyticsEmitter,
        settings: Settings | None = None,
    ) -> None:
        self._repo = repo
        self._bot = bot
        self._analytics_emitter = analytics_emitter
        self._settings = settings or get_settings()

    async def get_snapshot(self, *, chat_id: int, user_id: int, since_version: int | None) -> MiniAppSnapshotResult:
        started_at = monotonic()
        game = await self._require_game(chat_id)
        no_change = since_version is not None and game.version <= since_version
        self._analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.MINIAPP_POLLING_LATENCY,
                chat_id=chat_id,
                user_id=user_id,
                game_id=str(chat_id),
                payload={
                    "latency_ms": int((monotonic() - started_at) * 1000),
                    "no_change": no_change,
                    "version": game.version,
                },
            )
        )
        if no_change:
            return MiniAppSnapshotResult(no_change=True, game=game)
        return MiniAppSnapshotResult(no_change=False, game=game)

    async def join(self, *, chat_id: int, user_id: int, name: str) -> MiniAppActionResult:
        async with self._repo.chat_lock(chat_id):
            game = await self._require_game(chat_id)
            self._require_state(
                game,
                {GameState.LOBBY, GameState.PLAYING, GameState.VOTING, GameState.FINISHED},
                "join_forbidden_state",
                "Сейчас нельзя присоединиться к игре.",
            )
            if not await self._repo.has_user_started(user_id):
                raise MiniAppError(
                    code="private_start_required",
                    message="Сначала напиши боту в личку: /start.",
                    status_code=403,
                )
            if user_id not in self._player_ids(game):
                game.players.append(Player(user_id=user_id, name=name))
                touch_activity(game)
                await self._repo.save_game(game)
                self._analytics_emitter.emit(
                    AnalyticsEvent(
                        event_name=AnalyticsEventName.PLAYER_JOINED,
                        chat_id=chat_id,
                        user_id=user_id,
                        game_id=str(chat_id),
                        payload={"players_count": len(game.players), "source": "miniapp"},
                    )
                )
            if game.state != GameState.LOBBY:
                return MiniAppActionResult(
                    version=game.version,
                    updated_at_ts=game.updated_at_ts,
                    note_code="queued_for_next_round",
                    note_message="Игрок добавлен. Участие начнётся со следующего раунда.",
                )
            return MiniAppActionResult(version=game.version, updated_at_ts=game.updated_at_ts)

    async def toggle_category(self, *, chat_id: int, user_id: int, category: str) -> MiniAppActionResult:
        async with self._repo.chat_lock(chat_id):
            game = await self._require_game(chat_id)
            self._require_admin(game, user_id)
            self._require_state(
                game,
                {GameState.LOBBY},
                "category_toggle_forbidden_state",
                "Категории можно менять только в лобби.",
            )
            if category not in game.available_categories:
                raise MiniAppError(
                    code="category_not_found",
                    message="Категория не найдена.",
                    status_code=404,
                )
            if category in game.selected_categories:
                game.selected_categories = [item for item in game.selected_categories if item != category]
            else:
                game.selected_categories.append(category)
                game.selected_categories.sort()
            touch_activity(game)
            await self._repo.save_game(game)
            self._analytics_emitter.emit(
                AnalyticsEvent(
                    event_name=AnalyticsEventName.CATEGORY_TOGGLED,
                    chat_id=chat_id,
                    user_id=user_id,
                    game_id=str(chat_id),
                    payload={
                        "category": category,
                        "selected_categories": list(game.selected_categories),
                        "source": "miniapp",
                    },
                )
            )
            return MiniAppActionResult(version=game.version, updated_at_ts=game.updated_at_ts)

    async def start(self, *, chat_id: int, user_id: int) -> MiniAppActionResult:
        async with self._repo.chat_lock(chat_id):
            game = await self._require_game(chat_id)
            self._require_admin(game, user_id)
            self._require_state(game, {GameState.LOBBY}, "start_forbidden_state", "Игру можно начать только из лобби.")
            if self._reset_lobby_if_idle(game):
                await self._repo.save_game(game)
                raise MiniAppError(
                    code="lobby_reset_due_inactivity",
                    message="Лобби было неактивно более часа и сброшено. Игрокам нужно присоединиться заново.",
                    status_code=409,
                )
            if len(game.players) < 3:
                raise MiniAppError(
                    code="not_enough_players",
                    message="Нужно минимум 3 игрока.",
                    status_code=409,
                )
            await start_round(
                game=game,
                actor_id=user_id,
                repo=self._repo,
                bot=self._bot,
                analytics_emitter=self._analytics_emitter,
                responder=None,
            )
            return MiniAppActionResult(version=game.version, updated_at_ts=game.updated_at_ts)

    async def open_voting(self, *, chat_id: int, user_id: int) -> MiniAppActionResult:
        async with self._repo.chat_lock(chat_id):
            game = await self._require_game(chat_id)
            self._require_admin(game, user_id)
            self._require_state(
                game,
                {GameState.PLAYING},
                "voting_open_forbidden_state",
                "Голосование можно открыть только во время раунда.",
            )
            await open_voting(
                game=game,
                actor_id=user_id,
                repo=self._repo,
                analytics_emitter=self._analytics_emitter,
                responder=None,
            )
            return MiniAppActionResult(version=game.version, updated_at_ts=game.updated_at_ts)

    async def cast_vote(self, *, chat_id: int, user_id: int, target_id: int) -> MiniAppActionResult:
        async with self._repo.chat_lock(chat_id):
            game = await self._require_game(chat_id)
            self._require_state(
                game,
                {GameState.VOTING},
                "vote_forbidden_state",
                "Сейчас не этап голосования.",
            )
            player_ids = self._round_player_ids(game)
            if user_id not in player_ids:
                raise MiniAppError(
                    code="member_required",
                    message="Ты не участник этой игры.",
                    status_code=403,
                )
            if target_id not in player_ids:
                raise MiniAppError(
                    code="vote_target_invalid",
                    message="Неверная цель голоса.",
                    status_code=400,
                )
            game.votes[user_id] = target_id
            touch_activity(game)
            await self._repo.save_game(game)
            self._analytics_emitter.emit(
                AnalyticsEvent(
                    event_name=AnalyticsEventName.VOTE_CAST,
                    chat_id=chat_id,
                    user_id=user_id,
                    game_id=str(chat_id),
                    round_id=f"{chat_id}:1",
                    payload={"target_id": target_id, "votes_count": len(game.votes), "source": "miniapp"},
                )
            )
            if player_ids.issubset(set(game.votes)):
                await close_voting(
                    game=game,
                    actor_id=user_id,
                    repo=self._repo,
                    analytics_emitter=self._analytics_emitter,
                    responder=None,
                    auto_finished=True,
                )
            return MiniAppActionResult(version=game.version, updated_at_ts=game.updated_at_ts)

    async def close_voting(self, *, chat_id: int, user_id: int) -> MiniAppActionResult:
        async with self._repo.chat_lock(chat_id):
            game = await self._require_game(chat_id)
            self._require_admin(game, user_id)
            self._require_state(
                game,
                {GameState.VOTING},
                "voting_close_forbidden_state",
                "Сейчас нет активного голосования.",
            )
            await close_voting(
                game=game,
                actor_id=user_id,
                repo=self._repo,
                analytics_emitter=self._analytics_emitter,
                responder=None,
                auto_finished=False,
            )
            return MiniAppActionResult(version=game.version, updated_at_ts=game.updated_at_ts)

    async def cancel(self, *, chat_id: int, user_id: int) -> MiniAppActionResult:
        async with self._repo.chat_lock(chat_id):
            game = await self._require_game(chat_id)
            self._require_admin(game, user_id)
            await cancel_game(
                game=game,
                actor_id=user_id,
                repo=self._repo,
                analytics_emitter=self._analytics_emitter,
                responder=None,
            )
            return MiniAppActionResult(version=0, updated_at_ts=None)

    async def get_my_role(self, *, chat_id: int, user_id: int) -> dict[str, str | bool | None]:
        game = await self._require_game(chat_id)
        player_ids = self._round_player_ids(game)
        if user_id not in player_ids:
            raise MiniAppError(
                code="member_required",
                message="Ты не участник этой игры.",
                status_code=403,
            )
        if game.state not in {GameState.PLAYING, GameState.VOTING, GameState.FINISHED}:
            return {"has_role": False, "is_spy": None, "role_name": None, "payload_type": None, "payload": None}
        is_spy = user_id == game.spy_id
        payload = game.spy_payload if is_spy else game.civilian_payload
        role_name = game.spy_name if is_spy else game.civilian_name
        return {
            "has_role": payload is not None,
            "is_spy": is_spy,
            "role_name": role_name,
            "payload_type": game.payload_type.value,
            "payload": payload,
        }

    async def generate_test_pair(
        self,
        *,
        user_id: int,
        categories: list[str] | None = None,
    ) -> dict[str, str | None]:
        if not await self._repo.has_user_started(user_id):
            raise MiniAppError(
                code="private_start_required",
                message="Сначала напиши боту в личку: /start.",
                status_code=403,
            )
        provider = build_content_provider(self._settings)
        try:
            pair = provider.get_random_image_pair(categories or None)
        except ValueError as exc:
            raise MiniAppError(code="testpair_unavailable", message=str(exc), status_code=409) from exc
        return {
            "theme": pair.theme,
            "civilian_id": pair.civilian,
            "civilian_name": pair.civilian_name,
            "civilian_wiki_url": pair.civilian_wiki_url,
            "civilian_search_url": build_google_search_url(pair.civilian_name),
            "spy_id": pair.spy,
            "spy_name": pair.spy_name,
            "spy_wiki_url": pair.spy_wiki_url,
            "spy_search_url": build_google_search_url(pair.spy_name),
        }

    @staticmethod
    def _player_ids(game: Game) -> set[int]:
        return {player.user_id for player in game.players}

    @staticmethod
    def _round_player_ids(game: Game) -> set[int]:
        if game.round_player_ids:
            return set(game.round_player_ids)
        return {player.user_id for player in game.players}

    def _reset_lobby_if_idle(self, game: Game) -> bool:
        if not is_lobby_expired(game, idle_seconds=self._settings.lobby_idle_reset_seconds):
            return False
        provider = build_content_provider(self._settings)
        reset_to_fresh_lobby(game, available_categories=provider.get_available_categories())
        return True

    async def _require_game(self, chat_id: int) -> Game:
        game = await self._repo.get_game(chat_id)
        if game is None:
            raise MiniAppError(
                code="game_not_found",
                message="Игра не найдена.",
                status_code=404,
            )
        return game

    @staticmethod
    def _require_admin(game: Game, user_id: int) -> None:
        if user_id != game.admin_id:
            raise MiniAppError(
                code="admin_required",
                message="Только админ может выполнять это действие.",
                status_code=403,
            )

    @staticmethod
    def _require_state(game: Game, allowed: set[GameState], code: str, message: str) -> None:
        if game.state not in allowed:
            raise MiniAppError(code=code, message=message, status_code=409)
