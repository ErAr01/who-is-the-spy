from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import patch
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock

from src.game.models import Game, GameMode, GameState, Player
from src.miniapp.errors import MiniAppError
from src.miniapp.service import GameService


class _InMemoryRepo:
    def __init__(self, game: Game) -> None:
        self._game = game
        self._version = game.version
        self._started_users: set[int] = set()

    async def get_game(self, chat_id: int) -> Game | None:
        return self._game if self._game.chat_id == chat_id else None

    async def save_game(self, game: Game, *, bump_version: bool = True) -> None:
        if bump_version:
            self._version += 1
            game.version = self._version
            game.updated_at_ts = float(self._version)
        self._game = game

    async def delete_game(self, chat_id: int) -> None:
        if self._game.chat_id == chat_id:
            self._game = None

    async def has_user_started(self, user_id: int) -> bool:
        return user_id in self._started_users

    @asynccontextmanager
    async def chat_lock(self, chat_id: int):
        yield


class GameServiceValidationTest(IsolatedAsyncioTestCase):
    def _build_game(self, *, state: GameState = GameState.LOBBY) -> Game:
        return Game(
            chat_id=100,
            admin_id=1,
            state=state,
            mode=GameMode.IMAGE_DB,
            players=[Player(user_id=1, name="Admin"), Player(user_id=2, name="P2"), Player(user_id=3, name="P3")],
            available_categories=["anime"],
            selected_categories=[],
            version=1,
            updated_at_ts=1.0,
        )

    async def test_toggle_category_requires_admin(self) -> None:
        repo = _InMemoryRepo(self._build_game())
        service = GameService(repo=repo, bot=Mock(), analytics_emitter=Mock())

        with self.assertRaises(MiniAppError) as exc:
            await service.toggle_category(chat_id=100, user_id=2, category="anime")
        self.assertEqual(exc.exception.code, "admin_required")

    async def test_vote_requires_voting_state(self) -> None:
        game = self._build_game(state=GameState.PLAYING)
        repo = _InMemoryRepo(game)
        service = GameService(repo=repo, bot=Mock(), analytics_emitter=Mock())

        with self.assertRaises(MiniAppError) as exc:
            await service.cast_vote(chat_id=100, user_id=2, target_id=1)
        self.assertEqual(exc.exception.code, "vote_forbidden_state")

    async def test_late_join_returns_note_and_does_not_enter_current_round(self) -> None:
        game = self._build_game(state=GameState.PLAYING)
        game.round_player_ids = [1, 2, 3]
        repo = _InMemoryRepo(game)
        repo._started_users.update({1, 2, 3, 4})
        service = GameService(repo=repo, bot=Mock(), analytics_emitter=Mock())

        result = await service.join(chat_id=100, user_id=4, name="P4")

        self.assertEqual(result.note_code, "queued_for_next_round")
        self.assertIn("следующего раунда", result.note_message or "")
        self.assertIn(4, {player.user_id for player in game.players})
        self.assertNotIn(4, set(game.round_player_ids))

    async def test_vote_rejects_late_join_player_during_round(self) -> None:
        game = self._build_game(state=GameState.VOTING)
        game.round_player_ids = [1, 2, 3]
        game.players.append(Player(user_id=4, name="P4"))
        repo = _InMemoryRepo(game)
        service = GameService(repo=repo, bot=Mock(), analytics_emitter=Mock())

        with self.assertRaises(MiniAppError) as exc:
            await service.cast_vote(chat_id=100, user_id=4, target_id=1)
        self.assertEqual(exc.exception.code, "member_required")

    async def test_start_resets_lobby_after_idle_timeout(self) -> None:
        game = self._build_game(state=GameState.LOBBY)
        game.last_activity_ts = 10.0
        settings = Mock(lobby_idle_reset_seconds=3600)
        provider = Mock()
        provider.get_available_categories.return_value = ["anime", "rock"]
        repo = _InMemoryRepo(game)
        service = GameService(repo=repo, bot=Mock(), analytics_emitter=Mock(), settings=settings)

        with (
            patch("src.game.lifecycle.time", return_value=4000.5),
            patch("src.miniapp.service.build_content_provider", return_value=provider),
        ):
            with self.assertRaises(MiniAppError) as exc:
                await service.start(chat_id=100, user_id=1)

        self.assertEqual(exc.exception.code, "lobby_reset_due_inactivity")
        self.assertEqual(game.players, [])
        self.assertEqual(game.round_player_ids, [])
        self.assertEqual(game.state, GameState.LOBBY)
