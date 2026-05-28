from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from aiogram import Bot

from src.analytics import AnalyticsEmitter, AnalyticsEvent, AnalyticsEventName
from src.config import Settings, get_settings
from src.game.engine import build_google_search_url
from src.game.lifecycle import is_lobby_expired, reset_to_fresh_lobby, touch_activity
from src.game.models import Game, GameMode, GameState, Player
from src.game.provider_factory import build_content_provider
from src.handlers.admin_actions import cancel_game, close_voting, open_voting, start_round
from src.labeling.storage import LabelingStorage
from src.miniapp.errors import MiniAppError
from src.utils.category_labels import category_label


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
        self._labeling_storage = LabelingStorage(self._settings.labeling_db_path)
        self._labeling_storage.init_db()

    async def get_snapshot(
        self,
        *,
        chat_id: int,
        user_id: int,
        user_name: str,
        since_version: int | None,
    ) -> MiniAppSnapshotResult:
        started_at = monotonic()
        game = await self._resolve_snapshot_game(chat_id=chat_id, user_id=user_id, user_name=user_name)
        # Version can reset when a game is cancelled/recreated.
        # Treat only exact equality as "no change" so clients receive fresh snapshot after reset.
        no_change = since_version is not None and game.version == since_version
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

    async def leave(self, *, chat_id: int, user_id: int) -> MiniAppActionResult:
        async with self._repo.chat_lock(chat_id):
            game = await self._require_game(chat_id)
            self._require_state(
                game,
                {GameState.LOBBY, GameState.FINISHED},
                "leave_forbidden_state",
                "Покинуть лобби можно только вне активного раунда.",
            )
            if user_id == game.admin_id:
                raise MiniAppError(
                    code="admin_cannot_leave_lobby",
                    message="Админ не может покинуть лобби. Передайте роль админа или отмените игру.",
                    status_code=409,
                )
            if user_id not in self._player_ids(game):
                return MiniAppActionResult(
                    version=game.version,
                    updated_at_ts=game.updated_at_ts,
                    note_code="already_left_lobby",
                    note_message="Вы уже не в составе лобби.",
                )

            game.players = [player for player in game.players if player.user_id != user_id]
            game.round_player_ids = [value for value in game.round_player_ids if value != user_id]
            game.votes = {
                voter_id: target_id
                for voter_id, target_id in game.votes.items()
                if voter_id != user_id and target_id != user_id
            }
            touch_activity(game)
            await self._repo.save_game(game)
            return MiniAppActionResult(
                version=game.version,
                updated_at_ts=game.updated_at_ts,
                note_code="left_lobby",
                note_message="Вы покинули лобби.",
            )

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
                deliver_private_roles=False,
            )
            return MiniAppActionResult(version=game.version, updated_at_ts=game.updated_at_ts)

    async def repeat_round(self, *, chat_id: int, user_id: int) -> MiniAppActionResult:
        async with self._repo.chat_lock(chat_id):
            game = await self._require_game(chat_id)
            self._require_admin(game, user_id)
            self._require_state(
                game,
                {GameState.FINISHED},
                "repeat_forbidden_state",
                "Новый раунд можно запустить только после завершения текущего.",
            )
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
                started_from_post_round=True,
                deliver_private_roles=False,
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
            return {
                "has_role": False,
                "is_spy": None,
                "role_name": None,
                "payload_type": None,
                "payload": None,
                "image_url": None,
                "wiki_url": None,
                "search_url": None,
                "category": None,
                "category_label": None,
            }
        is_spy = user_id == game.spy_id
        payload = game.spy_payload if is_spy else game.civilian_payload
        role_name = game.spy_name if is_spy else game.civilian_name
        wiki_url = game.spy_wiki_url if is_spy else game.civilian_wiki_url
        category = self._resolve_role_category(payload=payload, selected_categories=game.selected_categories)
        search_url = self._build_role_search_url(role_name=role_name, category=category)
        image_url = f"/api/v1/miniapp/cards/{payload}/image" if payload else None
        return {
            "has_role": payload is not None,
            "is_spy": is_spy,
            "role_name": role_name,
            "payload_type": game.payload_type.value,
            "payload": payload,
            "image_url": image_url,
            "wiki_url": wiki_url,
            "search_url": search_url,
            "category": category,
            "category_label": category_label(category) if category else None,
        }

    async def get_round_roles(self, *, chat_id: int, user_id: int) -> dict[str, object]:
        game = await self._require_game(chat_id)
        if user_id not in self._player_ids(game):
            raise MiniAppError(
                code="member_required",
                message="Ты не участник этой игры.",
                status_code=403,
            )
        if game.state != GameState.FINISHED:
            raise MiniAppError(
                code="round_roles_unavailable",
                message="Роли можно показать только после завершения голосования.",
                status_code=409,
            )
        return {
            "theme": game.theme,
            "civilian": self._build_round_role_card(
                payload=game.civilian_payload,
                role_name=game.civilian_name,
                wiki_url=game.civilian_wiki_url,
                selected_categories=game.selected_categories,
            ),
            "spy": self._build_round_role_card(
                payload=game.spy_payload,
                role_name=game.spy_name,
                wiki_url=game.spy_wiki_url,
                selected_categories=game.selected_categories,
            ),
        }

    def _resolve_role_category(self, *, payload: str | None, selected_categories: list[str]) -> str | None:
        if not payload:
            return None
        card = self._labeling_storage.get_card(payload)
        if card is None:
            return None
        card_categories = [value.strip().lower() for value in card.dataset_categories if value.strip()]
        if not card_categories:
            return None
        selected = {value.strip().lower() for value in selected_categories if value.strip()}
        if selected:
            for value in card_categories:
                if value in selected:
                    return value
        return card_categories[0]

    @staticmethod
    def _build_role_search_query(*, role_name: str | None, category: str | None) -> str:
        if not role_name:
            return ""
        role = role_name.strip()
        if not role:
            return ""
        if not category:
            return role
        return f"{role} {category_label(category)}"

    def _build_role_search_url(self, *, role_name: str | None, category: str | None) -> str | None:
        search_query = self._build_role_search_query(role_name=role_name, category=category)
        return build_google_search_url(search_query) if search_query else None

    def _build_round_role_card(
        self,
        *,
        payload: str | None,
        role_name: str | None,
        wiki_url: str | None,
        selected_categories: list[str],
    ) -> dict[str, str | None]:
        category = self._resolve_role_category(payload=payload, selected_categories=selected_categories)
        return {
            "card_id": payload,
            "name": role_name,
            "image_url": f"/api/v1/miniapp/cards/{payload}/image" if payload else None,
            "wiki_url": wiki_url,
            "search_url": self._build_role_search_url(role_name=role_name, category=category),
            "category": category,
            "category_label": category_label(category) if category else None,
        }

    async def generate_test_pair(
        self,
        *,
        user_id: int,
        categories: list[str] | None = None,
    ) -> dict[str, object]:
        if not await self._repo.has_user_started(user_id):
            raise MiniAppError(
                code="private_start_required",
                message="Сначала напиши боту в личку: /start.",
                status_code=403,
            )
        provider = build_content_provider(self._settings)
        available_categories = provider.get_available_categories()
        normalized_categories = self._normalize_categories(categories, available_categories)
        try:
            pair = provider.get_random_image_pair(normalized_categories or None)
        except ValueError as exc:
            raise MiniAppError(code="testpair_unavailable", message=str(exc), status_code=409) from exc
        return {
            "theme": pair.theme,
            "available_categories": available_categories,
            "selected_categories": normalized_categories,
            "civilian_id": pair.civilian,
            "civilian_name": pair.civilian_name,
            "civilian_image_url": f"/api/v1/miniapp/cards/{pair.civilian}/image",
            "civilian_wiki_url": pair.civilian_wiki_url,
            "civilian_search_url": build_google_search_url(pair.civilian_name),
            "spy_id": pair.spy,
            "spy_name": pair.spy_name,
            "spy_image_url": f"/api/v1/miniapp/cards/{pair.spy}/image",
            "spy_wiki_url": pair.spy_wiki_url,
            "spy_search_url": build_google_search_url(pair.spy_name),
        }

    def get_card_image(self, card_id: str) -> bytes:
        provider = build_content_provider(self._settings)
        image_bytes = provider.get_image_bytes(card_id)
        if image_bytes is None:
            raise MiniAppError(code="card_image_not_found", message="Изображение карточки не найдено.", status_code=404)
        return image_bytes

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

    async def _resolve_snapshot_game(self, *, chat_id: int, user_id: int, user_name: str) -> Game:
        if chat_id == user_id:
            return await self._require_game(chat_id)

        async with self._repo.chat_lock(chat_id):
            game = await self._repo.get_game(chat_id)
            if game is None:
                provider = build_content_provider(self._settings)
                admin_id = await self._resolve_group_admin_id(chat_id=chat_id, fallback_user_id=user_id)
                players: list[Player] = []
                if await self._repo.has_user_started(user_id):
                    players.append(Player(user_id=user_id, name=user_name))
                game = Game(
                    chat_id=chat_id,
                    admin_id=admin_id,
                    state=GameState.LOBBY,
                    mode=GameMode.IMAGE_DB,
                    players=players,
                    available_categories=provider.get_available_categories(),
                )
                touch_activity(game)
                await self._repo.save_game(game)
                self._analytics_emitter.emit(
                    AnalyticsEvent(
                        event_name=AnalyticsEventName.GAME_CREATED,
                        chat_id=chat_id,
                        user_id=user_id,
                        game_id=str(chat_id),
                        payload={"source": "miniapp_auto_create", "players_count": len(players)},
                    )
                )
                return game

            changed = False
            resolved_admin_id = await self._resolve_group_admin_id(chat_id=chat_id, fallback_user_id=game.admin_id)
            if resolved_admin_id != game.admin_id:
                game.admin_id = resolved_admin_id
                changed = True

            if self._is_broken_round_state(game):
                game.state = GameState.LOBBY
                game.spy_id = None
                game.round_player_ids = []
                game.votes = {}
                game.last_voted_out_id = None
                game.last_is_spy_caught = None
                game.last_round_duration_seconds = None
                game.round_started_at_ts = None
                changed = True

            if game.state in {GameState.LOBBY, GameState.FINISHED} and is_lobby_expired(
                game, idle_seconds=self._settings.lobby_idle_reset_seconds
            ):
                provider = build_content_provider(self._settings)
                reset_to_fresh_lobby(game, available_categories=provider.get_available_categories())
                changed = True

            if changed:
                await self._repo.save_game(game)

            return game

    async def _resolve_group_admin_id(self, *, chat_id: int, fallback_user_id: int) -> int:
        try:
            requester = await self._bot.get_chat_member(chat_id, fallback_user_id)
            if requester.status in {"creator", "administrator"}:
                return fallback_user_id
        except Exception:
            pass

        try:
            admins = await self._bot.get_chat_administrators(chat_id)
            for member in admins:
                user = getattr(member, "user", None)
                status = getattr(member, "status", None)
                user_id = getattr(user, "id", None)
                if user_id is None:
                    continue
                if status == "creator":
                    return int(user_id)
            for member in admins:
                user = getattr(member, "user", None)
                status = getattr(member, "status", None)
                user_id = getattr(user, "id", None)
                if user_id is None:
                    continue
                if status == "administrator":
                    return int(user_id)
        except Exception:
            pass

        return fallback_user_id

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

    @staticmethod
    def _normalize_categories(categories: list[str] | None, available_categories: list[str]) -> list[str]:
        if not categories:
            return []
        available = {value.lower() for value in available_categories}
        normalized: list[str] = []
        seen: set[str] = set()
        for value in categories:
            cleaned = value.strip().lower()
            if not cleaned or cleaned in seen or cleaned not in available:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

    @staticmethod
    def _is_broken_round_state(game: Game) -> bool:
        if game.state not in {GameState.PLAYING, GameState.VOTING}:
            return False
        return (
            game.spy_id is None
            or game.civilian_payload is None
            or game.spy_payload is None
            or game.round_started_at_ts is None
        )
