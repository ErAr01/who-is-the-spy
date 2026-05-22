from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.game.models import Game, GameState
from src.utils.category_labels import category_label


def _admin_rows_for_state(state: GameState, chat_id: int) -> list[list[InlineKeyboardButton]]:
    if state == GameState.LOBBY:
        return [
            [
                InlineKeyboardButton(text="▶️ Start", callback_data=f"admin:start:{chat_id}"),
                InlineKeyboardButton(text="❌ Cancel", callback_data=f"admin:cancel:{chat_id}"),
            ]
        ]
    if state == GameState.PLAYING:
        return [
            [
                InlineKeyboardButton(text="🗳 Vote", callback_data=f"admin:vote:{chat_id}"),
                InlineKeyboardButton(text="❌ Cancel", callback_data=f"admin:cancel:{chat_id}"),
            ]
        ]
    if state == GameState.VOTING:
        return [
            [
                InlineKeyboardButton(text="✅ End Vote", callback_data=f"admin:endvote:{chat_id}"),
                InlineKeyboardButton(text="❌ Cancel", callback_data=f"admin:cancel:{chat_id}"),
            ]
        ]
    if state == GameState.FINISHED:
        return [
            [
                InlineKeyboardButton(
                    text="🔁 Еще раунд (те же категории)",
                    callback_data=f"postround:repeat:{chat_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗂 Выбрать новые категории",
                    callback_data=f"postround:newcats:{chat_id}",
                )
            ],
        ]
    return []


def admin_controls_keyboard(game: Game) -> InlineKeyboardMarkup | None:
    rows = _admin_rows_for_state(game.state, game.chat_id)
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lobby_keyboard(
    chat_id: int,
    available_categories: list[str],
    selected_categories: list[str],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[InlineKeyboardButton(text="✅ Join", callback_data=f"join:{chat_id}")]]
    if not available_categories:
        rows.append([InlineKeyboardButton(text="⚠️ Нет категорий в БД", callback_data=f"noop:{chat_id}")])
        rows.extend(_admin_rows_for_state(GameState.LOBBY, chat_id))
        return InlineKeyboardMarkup(inline_keyboard=rows)

    category_buttons = [
        InlineKeyboardButton(
            text=f"{'🟢' if category in selected_categories else '⚪️'} {category_label(category)}",
            callback_data=f"category:{chat_id}:{category}",
        )
        for category in available_categories
    ]
    for idx in range(0, len(category_buttons), 2):
        rows.append(category_buttons[idx : idx + 2])
    rows.extend(_admin_rows_for_state(GameState.LOBBY, chat_id))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def vote_keyboard(game: Game, *, include_admin_controls: bool = False) -> InlineKeyboardMarkup:
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
    if include_admin_controls:
        rows.extend(_admin_rows_for_state(GameState.VOTING, game.chat_id))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def post_round_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=_admin_rows_for_state(GameState.FINISHED, chat_id))
