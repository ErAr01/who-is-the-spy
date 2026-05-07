from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.game.models import Game


def lobby_keyboard(
    chat_id: int,
    available_categories: list[str],
    selected_categories: list[str],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[InlineKeyboardButton(text="✅ Join", callback_data=f"join:{chat_id}")]]
    if not available_categories:
        rows.append([InlineKeyboardButton(text="⚠️ Нет категорий в БД", callback_data=f"noop:{chat_id}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    category_buttons = [
        InlineKeyboardButton(
            text=f"{'🟢' if category in selected_categories else '⚪️'} {category}",
            callback_data=f"category:{chat_id}:{category}",
        )
        for category in available_categories
    ]
    for idx in range(0, len(category_buttons), 2):
        rows.append(category_buttons[idx : idx + 2])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def vote_keyboard(game: Game) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for player in game.players:
        rows.append(
            [
                InlineKeyboardButton(
                    text=player.name,
                    callback_data=f"vote:{game.chat_id}:{player.user_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
