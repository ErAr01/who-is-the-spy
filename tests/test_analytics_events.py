import json
from datetime import datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from src.analytics import (
    AnalyticsErrorsMiddleware,
    AnalyticsEvent,
    AnalyticsEventName,
    CompositeAnalyticsEmitter,
    StdoutJsonAnalyticsEmitter,
)
from src.game.engine import VotingResult, finish_voting
from src.game.models import Game, GameMode, GameState, Player
from src.handlers.callbacks import vote
from src.handlers.group import end_vote, start_vote
from src.observability.prometheus_metrics import (
    PrometheusAnalyticsEmitter,
    analytics_events_total,
    bot_handler_exceptions_total,
)


class AnalyticsEventSchemaTest(TestCase):
    def test_event_to_dict_contains_required_and_optional_fields(self) -> None:
        event = AnalyticsEvent(
            event_name=AnalyticsEventName.GAME_CREATED,
            chat_id=101,
            user_id=202,
            game_id="game-101",
            round_id="round-1",
            payload={"players_count": 3},
        )

        serialized = event.to_dict()

        self.assertEqual(serialized["event_name"], AnalyticsEventName.GAME_CREATED.value)
        self.assertEqual(serialized["chat_id"], 101)
        self.assertEqual(serialized["user_id"], 202)
        self.assertEqual(serialized["game_id"], "game-101")
        self.assertEqual(serialized["round_id"], "round-1")
        self.assertEqual(serialized["payload"], {"players_count": 3})
        self.assertIsInstance(datetime.fromisoformat(serialized["timestamp"]), datetime)

    def test_event_rejects_non_serializable_payload(self) -> None:
        with self.assertRaises(ValueError):
            AnalyticsEvent(
                event_name=AnalyticsEventName.GAME_STARTED,
                payload={"bad_value": {1, 2, 3}},
            )


class AnalyticsEmitterTest(TestCase):
    def test_stdout_emitter_outputs_json_line(self) -> None:
        emitter = StdoutJsonAnalyticsEmitter()
        event = AnalyticsEvent(
            event_name=AnalyticsEventName.VOTE_CAST,
            chat_id=10,
            user_id=20,
            payload={"target_id": 30},
        )

        with patch("builtins.print") as print_mock:
            emitter.emit(event)

        printed_payload = print_mock.call_args.args[0]
        self.assertEqual(json.loads(printed_payload)["event_name"], AnalyticsEventName.VOTE_CAST.value)

    def test_composite_emitter_sends_to_all_emitters(self) -> None:
        first = Mock()
        second = Mock()
        composite = CompositeAnalyticsEmitter(emitters=[first, second])
        event = AnalyticsEvent(event_name=AnalyticsEventName.GAME_CANCELLED, payload={"reason": "admin"})

        composite.emit(event)

        first.emit.assert_called_once_with(event)
        second.emit.assert_called_once_with(event)

    def test_prometheus_emitter_tracks_events_and_exceptions(self) -> None:
        emitter = PrometheusAnalyticsEmitter()
        event_counter = analytics_events_total.labels(event_name=AnalyticsEventName.HANDLER_EXCEPTION.value)
        exc_counter = bot_handler_exceptions_total.labels(
            exception_type="RuntimeError",
            handler_name="unknown",
            update_type="unknown",
        )
        before_event = event_counter._value.get()
        before_exc = exc_counter._value.get()

        emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.HANDLER_EXCEPTION,
                payload={"exception_type": "RuntimeError"},
            )
        )

        self.assertEqual(event_counter._value.get(), before_event + 1.0)
        self.assertEqual(exc_counter._value.get(), before_exc + 1.0)


class AnalyticsErrorsMiddlewareTest(IsolatedAsyncioTestCase):
    async def test_middleware_emits_handler_exception_and_reraises(self) -> None:
        analytics_emitter = Mock()
        middleware = AnalyticsErrorsMiddleware(analytics_emitter)

        async def broken_handler(_: object, __: dict[str, object]) -> None:
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            await middleware(
                broken_handler,
                object(),
                {},
            )

        emitted_event = analytics_emitter.emit.call_args.args[0]
        self.assertIsInstance(emitted_event, AnalyticsEvent)
        self.assertEqual(emitted_event.event_name, AnalyticsEventName.HANDLER_EXCEPTION)
        self.assertEqual(emitted_event.payload["exception_type"], "RuntimeError")


class RuntimeAnalyticsInstrumentationTest(IsolatedAsyncioTestCase):
    def _build_game(self, *, state: GameState = GameState.VOTING) -> Game:
        return Game(
            chat_id=101,
            admin_id=1,
            state=state,
            mode=GameMode.IMAGE_DB,
            players=[Player(user_id=1, name="Admin"), Player(user_id=2, name="Player2")],
            spy_id=2,
        )

    async def test_start_vote_emits_voting_started_event(self) -> None:
        game = self._build_game(state=GameState.PLAYING)
        repo = SimpleNamespace(get_game=AsyncMock(return_value=game), save_game=AsyncMock())
        emitter = Mock()
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=1),
            chat=SimpleNamespace(id=101),
            answer=AsyncMock(),
        )

        await start_vote(message, repo, emitter)

        emitted = emitter.emit.call_args.args[0]
        self.assertEqual(emitted.event_name, AnalyticsEventName.VOTING_STARTED)
        self.assertEqual(emitted.payload["votes_count"], 0)
        repo.save_game.assert_awaited_once()

    async def test_vote_auto_finish_emits_round_finished_without_callback_message(self) -> None:
        game = self._build_game()
        game.votes = {2: 1}
        repo = SimpleNamespace(
            get_game=AsyncMock(return_value=game),
            save_game=AsyncMock(),
            delete_game=AsyncMock(),
        )
        emitter = Mock()
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=1),
            data="vote:101:2",
            message=None,
            answer=AsyncMock(),
        )

        with patch(
            "src.handlers.callbacks.finish_voting",
            return_value=VotingResult(
                voted_out_id=2,
                votes={2: 2},
                is_spy_caught=True,
                round_duration_seconds=42,
            ),
        ):
            await vote(callback, repo, emitter)

        emitted = emitter.emit.call_args.args[0]
        self.assertEqual(emitted.event_name, AnalyticsEventName.ROUND_FINISHED)
        self.assertTrue(emitted.payload["auto_finished"])
        self.assertEqual(emitted.payload["round_duration_seconds"], 42)
        repo.delete_game.assert_awaited_once_with(101)

    async def test_end_vote_emits_round_duration(self) -> None:
        game = self._build_game()
        game.votes = {1: 2, 2: 2}
        repo = SimpleNamespace(get_game=AsyncMock(return_value=game), delete_game=AsyncMock())
        emitter = Mock()
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=1),
            chat=SimpleNamespace(id=101),
            answer=AsyncMock(),
        )

        with patch(
            "src.handlers.group.finish_voting",
            return_value=VotingResult(
                voted_out_id=2,
                votes={2: 2},
                is_spy_caught=True,
                round_duration_seconds=17,
            ),
        ):
            await end_vote(message, repo, emitter)

        emitted = emitter.emit.call_args.args[0]
        self.assertEqual(emitted.event_name, AnalyticsEventName.ROUND_FINISHED)
        self.assertEqual(emitted.payload["round_duration_seconds"], 17)
        repo.delete_game.assert_awaited_once_with(101)


class RoundDurationEngineTest(TestCase):
    def test_finish_voting_calculates_and_resets_round_duration(self) -> None:
        game = Game(
            chat_id=202,
            admin_id=1,
            state=GameState.VOTING,
            mode=GameMode.IMAGE_DB,
            players=[Player(user_id=1, name="A"), Player(user_id=2, name="B")],
            spy_id=2,
            votes={1: 2, 2: 2},
            round_started_at_ts=100.0,
        )

        with patch("src.game.engine.time", return_value=130.9):
            result = finish_voting(game)

        self.assertEqual(result.round_duration_seconds, 30)
        self.assertEqual(game.state, GameState.FINISHED)
        self.assertIsNone(game.round_started_at_ts)
