from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from src.game.engine import prepare_game_round
from src.game.models import Game, GameMode, GameState, PayloadType, Player


class PrepareGameRoundBehaviorTest(TestCase):
    def _build_game(self) -> Game:
        return Game(
            chat_id=100,
            admin_id=1,
            state=GameState.LOBBY,
            mode=GameMode.IMAGE_DB,
            players=[
                Player(user_id=1, name="A"),
                Player(user_id=2, name="B"),
                Player(user_id=3, name="C"),
            ],
        )

    def _provider(self) -> SimpleNamespace:
        return SimpleNamespace(
            get_random_image_pair=lambda *_args, **_kwargs: SimpleNamespace(
                theme="test",
                civilian="civilian",
                spy="spy",
                civilian_name="Civilian",
                spy_name="Spy",
                civilian_wiki_url=None,
                spy_wiki_url=None,
            )
        )

    def test_spy_is_not_reused_when_other_players_available(self) -> None:
        game = self._build_game()
        game.spy_id = 1

        with patch("src.game.engine.random.choice", return_value=2) as choice_mock:
            prepared = prepare_game_round(game, self._provider())

        self.assertEqual(prepared.spy_id, 2)
        self.assertNotEqual(prepared.spy_id, 1)
        self.assertEqual(sorted(choice_mock.call_args.args[0]), [2, 3])

    def test_speaking_order_is_preserved_between_rounds(self) -> None:
        game = self._build_game()
        game.speaking_order = [2, 3, 1]

        with patch("src.game.engine.random.shuffle") as shuffle_mock:
            prepared = prepare_game_round(game, self._provider())

        self.assertEqual(prepared.speaking_order, [2, 3, 1])
        shuffle_mock.assert_not_called()

    def test_invalid_speaking_order_is_rebuilt_once(self) -> None:
        game = self._build_game()
        game.speaking_order = [1, 2]

        with patch("src.game.engine.random.shuffle") as shuffle_mock:
            prepared = prepare_game_round(game, self._provider())

        self.assertEqual(set(prepared.speaking_order), {1, 2, 3})
        self.assertEqual(prepared.payload_type, PayloadType.PHOTO)
        shuffle_mock.assert_called_once()
