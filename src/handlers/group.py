from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from src.analytics import AnalyticsEmitter, AnalyticsEvent, AnalyticsEventName
from src.config import Settings
from src.game.lifecycle import is_lobby_expired, reset_to_fresh_lobby, touch_activity
from src.handlers.admin_actions import cancel_game as cancel_game_action
from src.handlers.admin_actions import close_voting, open_voting, start_round
from src.game.models import Game, GameMode, GameState, Player
from src.game.provider_factory import build_content_provider
from src.handlers.callbacks import render_lobby_text
from src.utils.keyboards import lobby_keyboard, miniapp_open_keyboard_with_mode
from src.utils.miniapp_links import build_miniapp_chat_url, build_telegram_miniapp_deeplink

if TYPE_CHECKING:
    from src.game.repo import GameRepo

router = Router(name="group")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message(Command("newgame"))
async def new_game(
    message: Message,
    repo: GameRepo,
    settings: Settings,
    analytics_emitter: AnalyticsEmitter,
) -> None:
    if message.from_user is None:
        return
    existing = await repo.get_game(message.chat.id)
    if existing is not None:
        await message.answer("В этом чате уже есть активная игра. Используй /cancel для сброса.")
        return

    provider = build_content_provider()

    players: list[Player] = []
    if await repo.has_user_started(message.from_user.id):
        players.append(Player(user_id=message.from_user.id, name=message.from_user.full_name))

    game = Game(
        chat_id=message.chat.id,
        admin_id=message.from_user.id,
        state=GameState.LOBBY,
        mode=GameMode.IMAGE_DB,
        players=players,
        available_categories=provider.get_available_categories(),
    )
    touch_activity(game)

    miniapp_url = _build_group_miniapp_url(settings=settings, bot_username=message.bot.username, chat_id=game.chat_id)
    lobby_message = await message.answer(
        render_lobby_text(game.chat_id, game.players, game.selected_categories),
        reply_markup=lobby_keyboard(
            game.chat_id,
            game.available_categories,
            game.selected_categories,
            miniapp_url=miniapp_url,
        ),
    )
    game.lobby_message_id = lobby_message.message_id
    await repo.save_game(game)
    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.GAME_CREATED,
            chat_id=game.chat_id,
            user_id=message.from_user.id,
            game_id=str(game.chat_id),
            payload={
                "admin_id": game.admin_id,
                "players_count": len(game.players),
                "available_categories_count": len(game.available_categories),
            },
        )
    )


@router.message(Command("startgame"))
async def start_game(
    message: Message,
    repo: GameRepo,
    settings: Settings,
    bot: Bot,
    analytics_emitter: AnalyticsEmitter,
) -> None:
    if message.from_user is None:
        return
    game = await repo.get_game(message.chat.id)
    if game is None:
        await message.answer("Нет активной игры. Запусти /newgame.")
        return
    if message.from_user.id != game.admin_id:
        await message.answer("Только админ может запускать игру.")
        return
    if await _reset_lobby_if_idle(game=game, repo=repo, settings=settings):
        await message.answer(
            "Лобби было неактивно более часа и сброшено. Игрокам нужно присоединиться заново."
        )
        return
    if len(game.players) < 3:
        await message.answer("Нужно минимум 3 игрока.")
        return

    try:
        result = await start_round(
            game=game,
            actor_id=message.from_user.id,
            repo=repo,
            bot=bot,
            analytics_emitter=analytics_emitter,
            responder=message,
        )
    except ValueError as exc:
        await message.answer(f"Не удалось начать игру: {exc}")
        return
    if not result.delivered:
        await message.answer("Не удалось отправить роли никому. Проверь, что игроки написали боту в личку.")
        return

    if result.failed:
        await message.answer(
            "Не всем удалось отправить роли. Проверь личку бота у игроков: "
            + ", ".join(str(user_id) for user_id in result.failed)
        )


@router.message(Command("vote"))
async def start_vote(message: Message, repo: GameRepo, analytics_emitter: AnalyticsEmitter) -> None:
    if message.from_user is None:
        return
    game = await repo.get_game(message.chat.id)
    if game is None:
        await message.answer("Нет активной игры.")
        return
    if message.from_user.id != game.admin_id:
        await message.answer("Только админ может открыть голосование.")
        return
    if game.state != GameState.PLAYING:
        await message.answer("Голосование можно начать только во время раунда.")
        return

    await open_voting(
        game=game,
        actor_id=message.from_user.id,
        repo=repo,
        analytics_emitter=analytics_emitter,
        responder=message,
    )


@router.message(Command("endvote"))
async def end_vote(message: Message, repo: GameRepo, analytics_emitter: AnalyticsEmitter) -> None:
    if message.from_user is None:
        return
    game = await repo.get_game(message.chat.id)
    if game is None:
        await message.answer("Нет активной игры.")
        return
    if message.from_user.id != game.admin_id:
        await message.answer("Только админ может завершить голосование.")
        return
    if game.state != GameState.VOTING:
        await message.answer("Сейчас нет активного голосования.")
        return

    await close_voting(
        game=game,
        actor_id=message.from_user.id,
        repo=repo,
        analytics_emitter=analytics_emitter,
        responder=message,
        auto_finished=False,
    )


@router.message(Command("cancel"))
async def cancel_game(message: Message, repo: GameRepo, analytics_emitter: AnalyticsEmitter) -> None:
    if message.from_user is None:
        return
    game = await repo.get_game(message.chat.id)
    if game is None:
        await message.answer("Активной игры нет.")
        return
    if message.from_user.id != game.admin_id:
        await message.answer("Только админ может отменить игру.")
        return

    await cancel_game_action(
        game=game,
        actor_id=message.from_user.id,
        repo=repo,
        analytics_emitter=analytics_emitter,
        responder=message,
    )


@router.message(Command("app"))
async def open_group_miniapp(message: Message, settings: Settings) -> None:
    miniapp_url = _build_group_miniapp_url(settings=settings, bot_username=message.bot.username, chat_id=message.chat.id)
    if not miniapp_url:
        await message.answer("Mini App URL не настроен. Заполните MINIAPP_PUBLIC_URL в .env.")
        return
    await message.answer(
        "Открыть игру в Mini App для этого чата:",
        reply_markup=miniapp_open_keyboard_with_mode(url=miniapp_url, use_web_app=False),
    )


async def _reset_lobby_if_idle(*, game: Game, repo: GameRepo, settings: Settings) -> bool:
    if not is_lobby_expired(game, idle_seconds=settings.lobby_idle_reset_seconds):
        return False
    provider = build_content_provider(settings)
    reset_to_fresh_lobby(game, available_categories=provider.get_available_categories())
    await repo.save_game(game)
    return True


def _build_group_miniapp_url(*, settings: Settings, bot_username: str | None, chat_id: int) -> str | None:
    return build_telegram_miniapp_deeplink(
        bot_username=bot_username,
        short_name=settings.miniapp_short_name,
        chat_id=chat_id,
    ) or build_miniapp_chat_url(settings.miniapp_public_url, chat_id)
