from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.analytics import AnalyticsEmitter, AnalyticsEvent, AnalyticsEventName
from src.fsm.states import CustomSetup, TestRoundSetup
from src.game.content import ContentProvider
from src.game.engine import build_google_search_url
from src.game.models import PayloadType
from src.game.provider_factory import build_content_provider
from src.game.repo import GameRepo

router = Router(name="private")
router.message.filter(F.chat.type == "private")


def _parse_optional_wiki_url(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if value in {"", "-"}:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return None


def _build_content_provider() -> ContentProvider:
    return build_content_provider()


def _parse_categories_from_command_text(raw: str | None) -> list[str]:
    if raw is None:
        return []
    parts = raw.strip().split(maxsplit=1)
    if len(parts) < 2:
        return []
    values = [item.strip().lower() for item in parts[1].split(",")]
    return [item for item in values if item]


def _test_round_text(selected_categories: list[str]) -> str:
    categories_text = ", ".join(selected_categories) if selected_categories else "все доступные"
    return (
        "Тестовый режим: симуляция раунда в личке.\n"
        "Выбери категории и нажми «Сгенерировать раунд».\n"
        "Бот отправит две карточки: мирный и шпион.\n\n"
        f"Категории: <b>{categories_text}</b>"
    )


def _test_round_keyboard(available_categories: list[str], selected_categories: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if available_categories:
        category_buttons = [
            InlineKeyboardButton(
                text=f"{'🟢' if category in selected_categories else '⚪️'} {category}",
                callback_data=f"testround:category:{category}",
            )
            for category in available_categories
        ]
        for idx in range(0, len(category_buttons), 2):
            rows.append(category_buttons[idx : idx + 2])
    else:
        rows.append([InlineKeyboardButton(text="⚠️ Нет категорий в БД", callback_data="testround:noop")])

    rows.append([InlineKeyboardButton(text="🎲 Сгенерировать раунд", callback_data="testround:roll")])
    rows.append([InlineKeyboardButton(text="♻️ Сбросить категории", callback_data="testround:reset")])
    rows.append([InlineKeyboardButton(text="✅ Завершить тест", callback_data="testround:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _role_caption(role: str, theme: str, name: str, wiki_url: str | None) -> str:
    caption = f"Роль: <b>{role}</b>\nТема: <b>{escape(theme)}</b>\nПерсонаж: <b>{escape(name)}</b>"
    if wiki_url:
        safe_wiki = escape(wiki_url, quote=True)
        caption += f"\nWikipedia: <a href=\"{safe_wiki}\">ссылка</a>"
    search_url = escape(build_google_search_url(name), quote=True)
    caption += f"\nGoogle: <a href=\"{search_url}\">поиск</a>"
    return caption


@router.message(CommandStart())
async def start_private(message: Message, repo: GameRepo, analytics_emitter: AnalyticsEmitter) -> None:
    if message.from_user is None:
        return
    await repo.set_user_started(message.from_user.id)
    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.USER_STARTED_PRIVATE,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            payload={"command": "/start"},
        )
    )
    await message.answer(
        "Привет! Я бот игры «Кто шпион».\n"
        "Добавь меня в группу, затем админ сможет запустить /newgame.\n"
        "Команды: /help."
    )


@router.message(Command("help"))
async def help_private(message: Message) -> None:
    await message.answer(
        "Как играть:\n"
        "1) В группе админ запускает /newgame.\n"
        "2) Игроки нажимают Join.\n"
        "3) Админ выбирает категории персонажей в лобби.\n"
        "4) Админ запускает /startgame.\n\n"
        "Для теста контента в личке: /testpair.\n"
        "Откроется тест-лобби с выбором категорий и симуляцией раунда."
    )


@router.message(Command("testpair"))
async def test_pair(message: Message, state: FSMContext) -> None:
    provider = _build_content_provider()
    available_categories = provider.get_available_categories()
    requested_categories = _parse_categories_from_command_text(message.text)
    selected_categories = [c for c in requested_categories if c in available_categories]

    await state.set_state(TestRoundSetup.selecting_categories)
    await state.update_data(
        test_round_selected_categories=selected_categories,
        test_round_available_categories=available_categories,
    )
    await message.answer(
        _test_round_text(selected_categories),
        reply_markup=_test_round_keyboard(available_categories, selected_categories),
    )


@router.callback_query(F.data == "testround:noop")
async def noop_test_round(callback: CallbackQuery) -> None:
    await callback.answer("Сначала добавьте карточки в БД.", show_alert=True)


@router.callback_query(F.data.startswith("testround:category:"))
async def toggle_test_round_category(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data is None or callback.message is None:
        return
    if callback.message.chat.type != "private":
        return
    data = await state.get_data()
    available_categories = data.get("test_round_available_categories")
    selected_categories = data.get("test_round_selected_categories")
    if not isinstance(available_categories, list) or not isinstance(selected_categories, list):
        await callback.answer("Сессия теста не активна. Запусти /testpair снова.", show_alert=True)
        return

    category = callback.data.removeprefix("testround:category:")
    if category not in available_categories:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    selected_set = set(str(item) for item in selected_categories)
    if category in selected_set:
        selected_set.remove(category)
    else:
        selected_set.add(category)
    updated_selected = sorted(selected_set)
    await state.update_data(test_round_selected_categories=updated_selected)
    await callback.message.edit_text(
        _test_round_text(updated_selected),
        reply_markup=_test_round_keyboard(available_categories, updated_selected),
    )
    await callback.answer("Категории обновлены.")


@router.callback_query(F.data == "testround:reset")
async def reset_test_round_categories(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        return
    data = await state.get_data()
    available_categories = data.get("test_round_available_categories")
    if not isinstance(available_categories, list):
        await callback.answer("Сессия теста не активна. Запусти /testpair снова.", show_alert=True)
        return
    await state.update_data(test_round_selected_categories=[])
    await callback.message.edit_text(
        _test_round_text([]),
        reply_markup=_test_round_keyboard(available_categories, []),
    )
    await callback.answer("Категории сброшены.")


@router.callback_query(F.data == "testround:roll")
async def roll_test_round(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        return
    data = await state.get_data()
    selected_categories = data.get("test_round_selected_categories")
    if not isinstance(selected_categories, list):
        await callback.answer("Сессия теста не активна. Запусти /testpair снова.", show_alert=True)
        return

    provider = _build_content_provider()
    try:
        pair = provider.get_random_image_pair(selected_categories or None)
    except ValueError as exc:
        await callback.answer(f"Ошибка: {exc}", show_alert=True)
        return

    civilian_bytes = provider.get_image_bytes(pair.civilian)
    spy_bytes = provider.get_image_bytes(pair.spy)
    if civilian_bytes is None or spy_bytes is None:
        await callback.answer("Не удалось загрузить картинки пары из БД.", show_alert=True)
        return

    categories_text = ", ".join(selected_categories) if selected_categories else "все доступные"
    await callback.message.answer(
        f"Тестовый раунд готов.\nКатегории: <b>{categories_text}</b>\nТема: <b>{escape(pair.theme)}</b>"
    )
    await callback.message.answer_photo(
        photo=BufferedInputFile(civilian_bytes, filename=f"{pair.civilian}.jpg"),
        caption=_role_caption(
            role="Мирный",
            theme=pair.theme,
            name=pair.civilian_name,
            wiki_url=pair.civilian_wiki_url,
        ),
    )
    await callback.message.answer_photo(
        photo=BufferedInputFile(spy_bytes, filename=f"{pair.spy}.jpg"),
        caption=_role_caption(
            role="Шпион",
            theme=pair.theme,
            name=pair.spy_name,
            wiki_url=pair.spy_wiki_url,
        ),
    )
    await callback.answer("Раунд сгенерирован.")


@router.callback_query(F.data == "testround:close")
async def close_test_round(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.edit_text("Тестовый режим завершён. Чтобы начать снова, отправь /testpair.")
    await callback.answer("Готово.")


@router.message(CustomSetup.waiting_civilian_payload)
async def receive_civilian_payload(message: Message, state: FSMContext, repo: GameRepo) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    chat_id = data.get("chat_id")
    if not isinstance(chat_id, int):
        await message.answer("Не нашёл активную игру для кастомного режима.")
        await state.clear()
        return

    game = await repo.get_game(chat_id)
    if game is None:
        await message.answer("Игра уже не активна.")
        await state.clear()
        return

    if message.photo:
        payload = message.photo[-1].file_id
        payload_type = PayloadType.PHOTO
    elif message.text:
        payload = message.text.strip()
        payload_type = PayloadType.TEXT
    else:
        await message.answer("Отправь текст или фото для мирных игроков.")
        return

    game.payload_type = payload_type
    game.civilian_payload = payload
    game.civilian_wiki_url = None
    await repo.save_game(game)
    if payload_type == PayloadType.PHOTO:
        await state.set_state(CustomSetup.waiting_civilian_wiki_url)
        await message.answer(
            "Добавь ссылку на Wikipedia для картинки мирных "
            "(или отправь '-' для пропуска)."
        )
    else:
        await state.set_state(CustomSetup.waiting_spy_payload)
        await message.answer("Принято. Теперь пришли слово/картинку для шпиона.")


@router.message(CustomSetup.waiting_civilian_wiki_url)
async def receive_civilian_wiki(message: Message, state: FSMContext, repo: GameRepo) -> None:
    data = await state.get_data()
    chat_id = data.get("chat_id")
    if not isinstance(chat_id, int):
        await message.answer("Не нашёл активную игру для кастомного режима.")
        await state.clear()
        return

    if not message.text:
        await message.answer("Отправь ссылку текстом или '-' для пропуска.")
        return

    wiki_url = _parse_optional_wiki_url(message.text)
    if message.text.strip() != "-" and wiki_url is None:
        await message.answer("Ссылка должна начинаться с http:// или https://")
        return

    game = await repo.get_game(chat_id)
    if game is None:
        await message.answer("Игра уже не активна.")
        await state.clear()
        return

    game.civilian_wiki_url = wiki_url
    await repo.save_game(game)
    await state.set_state(CustomSetup.waiting_spy_payload)
    await message.answer("Принято. Теперь пришли слово/картинку для шпиона.")


@router.message(CustomSetup.waiting_spy_payload)
async def receive_spy_payload(message: Message, state: FSMContext, repo: GameRepo) -> None:
    data = await state.get_data()
    chat_id = data.get("chat_id")
    if not isinstance(chat_id, int):
        await message.answer("Не нашёл активную игру для кастомного режима.")
        await state.clear()
        return

    game = await repo.get_game(chat_id)
    if game is None:
        await message.answer("Игра уже не активна.")
        await state.clear()
        return

    if message.photo:
        payload = message.photo[-1].file_id
        payload_type = PayloadType.PHOTO
    elif message.text:
        payload = message.text.strip()
        payload_type = PayloadType.TEXT
    else:
        await message.answer("Отправь текст или фото для шпиона.")
        return

    if payload_type != game.payload_type:
        await message.answer("Тип должен совпадать с первым шагом: оба текста или оба фото.")
        return

    game.spy_payload = payload
    game.spy_wiki_url = None
    await repo.save_game(game)
    if payload_type == PayloadType.PHOTO:
        await state.set_state(CustomSetup.waiting_spy_wiki_url)
        await message.answer(
            "Добавь ссылку на Wikipedia для картинки шпиона "
            "(или отправь '-' для пропуска)."
        )
    else:
        await state.clear()
        await message.answer(
            "Кастомные значения сохранены.\n"
            "Возвращайся в группу и снова запусти /startgame."
        )


@router.message(CustomSetup.waiting_spy_wiki_url)
async def receive_spy_wiki(message: Message, state: FSMContext, repo: GameRepo) -> None:
    data = await state.get_data()
    chat_id = data.get("chat_id")
    if not isinstance(chat_id, int):
        await message.answer("Не нашёл активную игру для кастомного режима.")
        await state.clear()
        return

    if not message.text:
        await message.answer("Отправь ссылку текстом или '-' для пропуска.")
        return

    wiki_url = _parse_optional_wiki_url(message.text)
    if message.text.strip() != "-" and wiki_url is None:
        await message.answer("Ссылка должна начинаться с http:// или https://")
        return

    game = await repo.get_game(chat_id)
    if game is None:
        await message.answer("Игра уже не активна.")
        await state.clear()
        return

    game.spy_wiki_url = wiki_url
    await repo.save_game(game)
    await state.clear()
    await message.answer(
        "Кастомные значения сохранены.\n"
        "Возвращайся в группу и снова запусти /startgame."
    )
