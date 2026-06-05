from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import patch
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock

from src.game.models import Game, GameMode, GameState, Player
from src.miniapp.errors import MiniAppError
from src.miniapp.service import GameService


class GameSerializationTest(TestCase):
    def test_used_hint_indices_survive_json_roundtrip(self) -> None:
        # Redis хранит игру как JSON: ключи dict становятся строками,
        # from_dict обязан привести их обратно к int.
        game = Game(
            chat_id=-100,
            admin_id=1,
            state=GameState.PLAYING,
            mode=GameMode.IMAGE_DB,
            players=[Player(user_id=1, name="A"), Player(user_id=2, name="B")],
            used_hint_indices={1: [0, 3], 2: [7]},
        )

        restored = Game.from_dict(json.loads(json.dumps(game.to_dict())))

        self.assertEqual(restored.used_hint_indices, {1: [0, 3], 2: [7]})
        for key in restored.used_hint_indices:
            self.assertIsInstance(key, int)
        for index in restored.used_hint_indices[1]:
            self.assertIsInstance(index, int)


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


class _FakeCard:
    def __init__(self, *, description: str | None, facts: list[str]) -> None:
        self.description = description
        self.facts = facts
        self.dataset_categories: list[str] = []


class _FakeLabelingStorage:
    """Минимальный двойник LabelingStorage: card_id -> _FakeCard."""

    def __init__(self, cards: dict[str, _FakeCard]) -> None:
        self._cards = cards

    def get_card(self, card_id: str):
        return self._cards.get(card_id)


class GameServiceHintTest(IsolatedAsyncioTestCase):
    CIVILIAN_FACTS = [f"civilian-fact-{i}" for i in range(5)]
    SPY_FACTS = [f"spy-fact-{i}" for i in range(3)]

    def _build_playing_game(self, *, spy_id: int = 3) -> Game:
        return Game(
            chat_id=100,
            admin_id=1,
            state=GameState.PLAYING,
            mode=GameMode.IMAGE_DB,
            players=[Player(user_id=1, name="Admin"), Player(user_id=2, name="P2"), Player(user_id=3, name="P3")],
            round_player_ids=[1, 2, 3],
            spy_id=spy_id,
            civilian_payload="civ-card",
            spy_payload="spy-card",
            civilian_name="Civ",
            spy_name="Spy",
            available_categories=["anime"],
            selected_categories=[],
            version=5,
            updated_at_ts=5.0,
        )

    def _build_service(self, repo: _InMemoryRepo, cards: dict[str, _FakeCard]) -> GameService:
        service = GameService(repo=repo, bot=Mock(), analytics_emitter=Mock())
        service._labeling_storage = _FakeLabelingStorage(cards)
        return service

    def _cards(self) -> dict[str, _FakeCard]:
        return {
            "civ-card": _FakeCard(description="A civilian character", facts=list(self.CIVILIAN_FACTS)),
            "spy-card": _FakeCard(description="A spy character", facts=list(self.SPY_FACTS)),
        }

    async def test_role_response_includes_description_and_hint_counts(self) -> None:
        game = self._build_playing_game()
        repo = _InMemoryRepo(game)
        service = self._build_service(repo, self._cards())

        role = await service.get_my_role(chat_id=100, user_id=1)  # civilian

        self.assertEqual(role["description"], "A civilian character")
        self.assertEqual(role["hints_total"], len(self.CIVILIAN_FACTS))
        self.assertEqual(role["hints_used"], 0)

    async def test_hint_returns_a_fact(self) -> None:
        game = self._build_playing_game()
        repo = _InMemoryRepo(game)
        service = self._build_service(repo, self._cards())

        result = await service.get_hint(chat_id=100, user_id=2)  # civilian

        self.assertTrue(result["has_hint"])
        self.assertIn(result["hint"], self.CIVILIAN_FACTS)
        self.assertEqual(result["hints_used"], 1)
        self.assertEqual(result["hints_remaining"], len(self.CIVILIAN_FACTS) - 1)

    async def test_repeated_hints_never_repeat_within_round(self) -> None:
        game = self._build_playing_game()
        repo = _InMemoryRepo(game)
        service = self._build_service(repo, self._cards())

        seen: list[str] = []
        for _ in range(len(self.CIVILIAN_FACTS)):
            result = await service.get_hint(chat_id=100, user_id=2)
            self.assertTrue(result["has_hint"])
            seen.append(result["hint"])

        self.assertEqual(sorted(seen), sorted(self.CIVILIAN_FACTS))
        self.assertEqual(len(set(seen)), len(self.CIVILIAN_FACTS))

    async def test_hint_exhaustion_returns_no_more_hints(self) -> None:
        game = self._build_playing_game()
        repo = _InMemoryRepo(game)
        service = self._build_service(repo, self._cards())

        for _ in range(len(self.CIVILIAN_FACTS)):
            await service.get_hint(chat_id=100, user_id=2)

        result = await service.get_hint(chat_id=100, user_id=2)
        self.assertFalse(result["has_hint"])
        self.assertIsNone(result["hint"])
        self.assertEqual(result["hints_remaining"], 0)
        self.assertEqual(result["hints_used"], len(self.CIVILIAN_FACTS))

    async def test_hint_does_not_bump_version(self) -> None:
        game = self._build_playing_game()
        repo = _InMemoryRepo(game)
        service = self._build_service(repo, self._cards())
        version_before = game.version

        await service.get_hint(chat_id=100, user_id=2)

        self.assertEqual(game.version, version_before)

    async def test_hints_reset_on_new_round(self) -> None:
        from src.game.engine import prepare_game_round

        game = self._build_playing_game()
        repo = _InMemoryRepo(game)
        service = self._build_service(repo, self._cards())

        await service.get_hint(chat_id=100, user_id=2)
        self.assertEqual(len(game.used_hint_indices.get(2, [])), 1)

        content = Mock()
        content.get_random_image_pair.return_value = Mock(
            theme="t",
            civilian="civ-card",
            spy="spy-card",
            civilian_name="Civ",
            spy_name="Spy",
            civilian_wiki_url=None,
            spy_wiki_url=None,
        )
        prepare_game_round(game, content)

        self.assertEqual(game.used_hint_indices, {})

    async def test_card_without_facts_returns_no_hints(self) -> None:
        game = self._build_playing_game()
        repo = _InMemoryRepo(game)
        cards = {
            "civ-card": _FakeCard(description=None, facts=[]),
            "spy-card": _FakeCard(description=None, facts=[]),
        }
        service = self._build_service(repo, cards)

        result = await service.get_hint(chat_id=100, user_id=2)
        self.assertFalse(result["has_hint"])
        self.assertEqual(result["hints_total"], 0)

    async def test_spy_and_civilian_get_facts_of_their_own_card(self) -> None:
        game = self._build_playing_game(spy_id=3)
        repo = _InMemoryRepo(game)
        service = self._build_service(repo, self._cards())

        civ_result = await service.get_hint(chat_id=100, user_id=1)  # civilian
        spy_result = await service.get_hint(chat_id=100, user_id=3)  # spy

        self.assertIn(civ_result["hint"], self.CIVILIAN_FACTS)
        self.assertIn(spy_result["hint"], self.SPY_FACTS)

    async def test_hint_requires_round_participant(self) -> None:
        game = self._build_playing_game()
        game.round_player_ids = [1, 2]  # user 3 not in round
        repo = _InMemoryRepo(game)
        service = self._build_service(repo, self._cards())

        with self.assertRaises(MiniAppError) as exc:
            await service.get_hint(chat_id=100, user_id=3)
        self.assertEqual(exc.exception.code, "member_required")

    async def test_hint_forbidden_outside_round(self) -> None:
        game = self._build_playing_game()
        game.state = GameState.LOBBY
        repo = _InMemoryRepo(game)
        service = self._build_service(repo, self._cards())

        with self.assertRaises(MiniAppError) as exc:
            await service.get_hint(chat_id=100, user_id=2)
        self.assertEqual(exc.exception.code, "hint_forbidden_state")
