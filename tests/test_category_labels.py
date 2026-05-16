from unittest import TestCase

from src.handlers.callbacks import render_lobby_text
from src.game.models import Player
from src.utils.category_labels import category_label, format_categories
from src.utils.keyboards import lobby_keyboard


class CategoryLabelsTest(TestCase):
    def test_category_label_maps_known_categories(self) -> None:
        self.assertEqual(category_label("adult"), "Актрисы (18+)")
        self.assertEqual(category_label("anime"), "Аниме")
        self.assertEqual(category_label("cartoons"), "Мультфильмы")
        self.assertEqual(category_label("movies_series"), "Кино / Сериалы")

    def test_format_categories_uses_mapped_labels(self) -> None:
        self.assertEqual(
            format_categories(["adult", "anime", "unknown"]),
            "Актрисы (18+), Аниме, unknown",
        )

    def test_render_lobby_text_shows_readable_labels(self) -> None:
        text = render_lobby_text(
            game_chat_id=77,
            players=[Player(user_id=1, name="Admin")],
            selected_categories=["movies_series", "cartoons"],
        )
        self.assertIn("Кино / Сериалы", text)
        self.assertIn("Мультфильмы", text)

    def test_lobby_keyboard_uses_readable_labels(self) -> None:
        keyboard = lobby_keyboard(
            chat_id=77,
            available_categories=["adult", "anime"],
            selected_categories=["anime"],
        )
        button_texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("⚪️ Актрисы (18+)", button_texts)
        self.assertIn("🟢 Аниме", button_texts)
