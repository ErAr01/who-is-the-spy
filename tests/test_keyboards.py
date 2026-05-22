from unittest import TestCase

from src.game.models import Game, GameMode, GameState, Player
from src.utils.keyboards import lobby_keyboard, post_round_keyboard, vote_keyboard


class AdminButtonsKeyboardTest(TestCase):
    def _game(self, state: GameState) -> Game:
        return Game(
            chat_id=777,
            admin_id=1,
            state=state,
            mode=GameMode.IMAGE_DB,
            players=[Player(user_id=1, name="Admin"), Player(user_id=2, name="P2")],
        )

    def test_lobby_keyboard_contains_start_and_cancel(self) -> None:
        keyboard = lobby_keyboard(chat_id=777, available_categories=["anime"], selected_categories=[])
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        self.assertIn("admin:start:777", callback_data)
        self.assertIn("admin:cancel:777", callback_data)

    def test_vote_keyboard_can_include_endvote_controls(self) -> None:
        keyboard = vote_keyboard(self._game(GameState.VOTING), include_admin_controls=True)
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        self.assertIn("admin:endvote:777", callback_data)
        self.assertIn("admin:cancel:777", callback_data)

    def test_post_round_keyboard_has_repeat_and_new_categories(self) -> None:
        keyboard = post_round_keyboard(777)
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        self.assertEqual(callback_data, ["postround:repeat:777", "postround:newcats:777"])
