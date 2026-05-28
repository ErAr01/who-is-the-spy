from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from src.analytics import AnalyticsEmitter, AnalyticsEvent, AnalyticsEventName
from src.config import Settings
from src.game.engine import all_players_voted, current_round_player_ids
from src.game.lifecycle import is_lobby_expired, reset_to_fresh_lobby, touch_activity
from src.game.models import Game, GameState, Player
from src.game.provider_factory import build_content_provider
from src.handlers.admin_actions import cancel_game, close_voting, open_voting, start_round
from src.utils.category_labels import format_categories
from src.utils.keyboards import lobby_keyboard
from src.utils.miniapp_links import build_miniapp_chat_url, build_telegram_miniapp_deeplink

if TYPE_CHECKING:
    from src.game.repo import GameRepo

router = Router(name="callbacks")


@router.callback_query(F.data.startswith("noop:"))
async def noop(callback: CallbackQuery) -> None:
    await callback.answer("Сначала добавьте карточки в категории через labeling.")


def render_lobby_text(game_chat_id: int, players: list[Player], selected_categories: list[str]) -> str:
    names = [f"- {p.name}" for p in players] or ["- Пока никого"]
    players_text = "\n".join(names)
    categories_text = format_categories(selected_categories) if selected_categories else "все доступные"
    return (
        f"Игра в чате <code>{game_chat_id}</code>\n"
        "Режим: <b>Картинки из БД</b>\n"
        f"Категории: <b>{categories_text}</b>\n"
        f"Игроки:\n{players_text}\n\n"
        "Нажми Join, чтобы участвовать."
    )


@router.callback_query(F.data.startswith("join:"))
async def join_game(
    callback: CallbackQuery,
    repo: GameRepo,
    settings: Settings,
    analytics_emitter: AnalyticsEmitter,
) -> None:
    if callback.from_user is None or callback.data is None:
        return

    _, chat_id_raw = callback.data.split(":")
    chat_id = int(chat_id_raw)
    game = await repo.get_game(chat_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if game.state == GameState.CUSTOM_SETUP:
        await callback.answer("Сейчас нельзя присоединиться к игре.", show_alert=True)
        return
    if not await repo.has_user_started(callback.from_user.id):
        await callback.answer("Сначала напиши боту в личку: /start", show_alert=True)
        return

    joined_now = False
    if all(player.user_id != callback.from_user.id for player in game.players):
        display_name = callback.from_user.full_name or str(callback.from_user.id)
        game.players.append(Player(user_id=callback.from_user.id, name=display_name))
        touch_activity(game)
        await repo.save_game(game)
        joined_now = True
        analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.PLAYER_JOINED,
                chat_id=game.chat_id,
                user_id=callback.from_user.id,
                game_id=str(game.chat_id),
                payload={"players_count": len(game.players)},
            )
        )

    miniapp_url = _build_group_miniapp_url(settings=settings, bot_username=callback.bot.username, chat_id=game.chat_id)
    if callback.message and game.state == GameState.LOBBY:
        await callback.message.edit_text(
            render_lobby_text(game.chat_id, game.players, game.selected_categories),
            reply_markup=lobby_keyboard(
                game.chat_id,
                game.available_categories,
                game.selected_categories,
                miniapp_url=miniapp_url,
            ),
        )
    if joined_now and game.state != GameState.LOBBY:
        await callback.answer("Ты добавлен в игру. Участие начнётся со следующего раунда.", show_alert=True)
        return
    await callback.answer("Ты в игре.")


@router.callback_query(F.data.startswith("category:"))
async def toggle_category(
    callback: CallbackQuery,
    repo: GameRepo,
    settings: Settings,
    analytics_emitter: AnalyticsEmitter,
) -> None:
    if callback.from_user is None or callback.data is None:
        return

    _, chat_id_raw, category = callback.data.split(":")
    chat_id = int(chat_id_raw)
    game = await repo.get_game(chat_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if callback.from_user.id != game.admin_id:
        await callback.answer("Категории может менять только админ.", show_alert=True)
        return
    if game.state != GameState.LOBBY:
        await callback.answer("Поздно менять категории.", show_alert=True)
        return

    if category in game.selected_categories:
        game.selected_categories = [item for item in game.selected_categories if item != category]
    else:
        game.selected_categories.append(category)
        game.selected_categories.sort()
    touch_activity(game)
    await repo.save_game(game)
    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.CATEGORY_TOGGLED,
            chat_id=game.chat_id,
            user_id=callback.from_user.id,
            game_id=str(game.chat_id),
            payload={"category": category, "selected_categories": list(game.selected_categories)},
        )
    )
    miniapp_url = _build_group_miniapp_url(settings=settings, bot_username=callback.bot.username, chat_id=game.chat_id)
    if callback.message:
        await callback.message.edit_text(
            render_lobby_text(game.chat_id, game.players, game.selected_categories),
            reply_markup=lobby_keyboard(
                game.chat_id,
                game.available_categories,
                game.selected_categories,
                miniapp_url=miniapp_url,
            ),
        )
    await callback.answer("Категории обновлены.")


@router.callback_query(F.data.startswith("vote:"))
async def vote(callback: CallbackQuery, repo: GameRepo, analytics_emitter: AnalyticsEmitter) -> None:
    if callback.from_user is None or callback.data is None:
        return

    _, chat_id_raw, target_raw = callback.data.split(":")
    chat_id = int(chat_id_raw)
    target_id = int(target_raw)
    game = await repo.get_game(chat_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if game.state != GameState.VOTING:
        await callback.answer("Сейчас не этап голосования.", show_alert=True)
        return

    player_ids = set(current_round_player_ids(game))
    if callback.from_user.id not in player_ids:
        await callback.answer("Ты не участник этой игры.", show_alert=True)
        return
    if target_id not in player_ids:
        await callback.answer("Неверная цель голоса.", show_alert=True)
        return

    game.votes[callback.from_user.id] = target_id
    touch_activity(game)
    await repo.save_game(game)
    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.VOTE_CAST,
            chat_id=game.chat_id,
            user_id=callback.from_user.id,
            game_id=str(game.chat_id),
            round_id=f"{game.chat_id}:1",
            payload={"target_id": target_id, "votes_count": len(game.votes)},
        )
    )
    await callback.answer("Голос учтён.")

    if all_players_voted(game):
        await close_voting(
            game=game,
            actor_id=callback.from_user.id,
            repo=repo,
            analytics_emitter=analytics_emitter,
            responder=callback.message,
            auto_finished=True,
        )


@router.callback_query(F.data.startswith("admin:start:"))
async def admin_start_round(
    callback: CallbackQuery,
    repo: GameRepo,
    settings: Settings,
    bot: Bot,
    analytics_emitter: AnalyticsEmitter,
) -> None:
    if callback.from_user is None or callback.data is None:
        return

    _, _, chat_id_raw = callback.data.split(":")
    chat_id = int(chat_id_raw)
    game = await repo.get_game(chat_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if callback.from_user.id != game.admin_id:
        await callback.answer("Только админ может запускать игру.", show_alert=True)
        return
    if await _reset_lobby_if_idle(game=game, repo=repo, settings=settings):
        if callback.message:
            miniapp_url = _build_group_miniapp_url(
                settings=settings,
                bot_username=callback.bot.username,
                chat_id=game.chat_id,
            )
            await callback.message.answer(
                "Лобби было неактивно более часа и сброшено. Игрокам нужно присоединиться заново.",
                reply_markup=lobby_keyboard(
                    game.chat_id,
                    game.available_categories,
                    game.selected_categories,
                    miniapp_url=miniapp_url,
                ),
            )
        await callback.answer("Лобби сброшено по неактивности.", show_alert=True)
        return
    if game.state != GameState.LOBBY:
        await callback.answer("Игру можно запустить только из лобби.", show_alert=True)
        return
    if len(game.players) < 3:
        await callback.answer("Нужно минимум 3 игрока.", show_alert=True)
        return

    try:
        result = await start_round(
            game=game,
            actor_id=callback.from_user.id,
            repo=repo,
            bot=bot,
            analytics_emitter=analytics_emitter,
            responder=callback.message,
        )
    except ValueError as exc:
        await callback.answer(f"Не удалось начать игру: {exc}", show_alert=True)
        return

    if not result.delivered:
        await callback.answer("Не удалось отправить роли. Проверь личку бота у игроков.", show_alert=True)
        return
    if result.failed and callback.message:
        await callback.message.answer(
            "Не всем удалось отправить роли. Проверь личку бота у игроков: "
            + ", ".join(str(user_id) for user_id in result.failed)
        )
    await callback.answer("Раунд запущен.")


@router.callback_query(F.data.startswith("admin:vote:"))
async def admin_start_vote(
    callback: CallbackQuery,
    repo: GameRepo,
    analytics_emitter: AnalyticsEmitter,
) -> None:
    if callback.from_user is None or callback.data is None:
        return

    _, _, chat_id_raw = callback.data.split(":")
    chat_id = int(chat_id_raw)
    game = await repo.get_game(chat_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if callback.from_user.id != game.admin_id:
        await callback.answer("Только админ может открыть голосование.", show_alert=True)
        return
    if game.state != GameState.PLAYING:
        await callback.answer("Голосование можно начать только во время раунда.", show_alert=True)
        return

    await open_voting(
        game=game,
        actor_id=callback.from_user.id,
        repo=repo,
        analytics_emitter=analytics_emitter,
        responder=callback.message,
    )
    await callback.answer("Голосование открыто.")


@router.callback_query(F.data.startswith("admin:endvote:"))
async def admin_end_vote(
    callback: CallbackQuery,
    repo: GameRepo,
    analytics_emitter: AnalyticsEmitter,
) -> None:
    if callback.from_user is None or callback.data is None:
        return

    _, _, chat_id_raw = callback.data.split(":")
    chat_id = int(chat_id_raw)
    game = await repo.get_game(chat_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if callback.from_user.id != game.admin_id:
        await callback.answer("Только админ может завершить голосование.", show_alert=True)
        return
    if game.state != GameState.VOTING:
        await callback.answer("Сейчас нет активного голосования.", show_alert=True)
        return

    await close_voting(
        game=game,
        actor_id=callback.from_user.id,
        repo=repo,
        analytics_emitter=analytics_emitter,
        responder=callback.message,
        auto_finished=False,
    )
    await callback.answer("Голосование завершено.")


@router.callback_query(F.data.startswith("admin:cancel:"))
async def admin_cancel_game(
    callback: CallbackQuery,
    repo: GameRepo,
    analytics_emitter: AnalyticsEmitter,
) -> None:
    if callback.from_user is None or callback.data is None:
        return

    _, _, chat_id_raw = callback.data.split(":")
    chat_id = int(chat_id_raw)
    game = await repo.get_game(chat_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if callback.from_user.id != game.admin_id:
        await callback.answer("Только админ может отменить игру.", show_alert=True)
        return

    await cancel_game(
        game=game,
        actor_id=callback.from_user.id,
        repo=repo,
        analytics_emitter=analytics_emitter,
        responder=callback.message,
    )
    await callback.answer("Игра отменена.")


@router.callback_query(F.data.startswith("postround:repeat:"))
async def repeat_round(
    callback: CallbackQuery,
    repo: GameRepo,
    settings: Settings,
    bot: Bot,
    analytics_emitter: AnalyticsEmitter,
) -> None:
    if callback.from_user is None or callback.data is None:
        return

    _, _, chat_id_raw = callback.data.split(":")
    chat_id = int(chat_id_raw)
    game = await repo.get_game(chat_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if callback.from_user.id != game.admin_id:
        await callback.answer("Только админ может запускать новый раунд.", show_alert=True)
        return
    if await _reset_lobby_if_idle(game=game, repo=repo, settings=settings):
        if callback.message:
            miniapp_url = _build_group_miniapp_url(
                settings=settings,
                bot_username=callback.bot.username,
                chat_id=game.chat_id,
            )
            await callback.message.answer(
                "Лобби было неактивно более часа и сброшено. Игрокам нужно присоединиться заново.",
                reply_markup=lobby_keyboard(
                    game.chat_id,
                    game.available_categories,
                    game.selected_categories,
                    miniapp_url=miniapp_url,
                ),
            )
        await callback.answer("Лобби сброшено по неактивности.", show_alert=True)
        return
    if game.state != GameState.FINISHED:
        await callback.answer("Раунд еще не завершен.", show_alert=True)
        return

    try:
        result = await start_round(
            game=game,
            actor_id=callback.from_user.id,
            repo=repo,
            bot=bot,
            analytics_emitter=analytics_emitter,
            responder=callback.message,
            started_from_post_round=True,
        )
    except ValueError as exc:
        await callback.answer(f"Не удалось начать раунд: {exc}", show_alert=True)
        return

    if not result.delivered:
        await callback.answer("Не удалось отправить роли. Проверь личку бота у игроков.", show_alert=True)
        return
    if result.failed and callback.message:
        await callback.message.answer(
            "Не всем удалось отправить роли. Проверь личку бота у игроков: "
            + ", ".join(str(user_id) for user_id in result.failed)
        )
    await callback.answer("Новый раунд запущен.")


@router.callback_query(F.data.startswith("postround:newcats:"))
async def choose_new_categories(callback: CallbackQuery, repo: GameRepo, settings: Settings) -> None:
    if callback.from_user is None or callback.data is None:
        return

    _, _, chat_id_raw = callback.data.split(":")
    chat_id = int(chat_id_raw)
    game = await repo.get_game(chat_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if callback.from_user.id != game.admin_id:
        await callback.answer("Категории может менять только админ.", show_alert=True)
        return
    if game.state != GameState.FINISHED:
        await callback.answer("Эта опция доступна только после раунда.", show_alert=True)
        return

    game.state = GameState.LOBBY
    game.spy_id = None
    game.theme = None
    game.civilian_payload = None
    game.spy_payload = None
    game.civilian_name = None
    game.spy_name = None
    game.civilian_wiki_url = None
    game.spy_wiki_url = None
    game.civilian_search_url = None
    game.spy_search_url = None
    game.votes = {}
    game.round_player_ids = []
    game.round_started_at_ts = None
    game.selected_categories = []
    game.available_categories = build_content_provider(settings).get_available_categories()
    touch_activity(game)
    await repo.save_game(game)

    if callback.message:
        miniapp_url = _build_group_miniapp_url(settings=settings, bot_username=callback.bot.username, chat_id=game.chat_id)
        await callback.message.answer(
            render_lobby_text(game.chat_id, game.players, game.selected_categories),
            reply_markup=lobby_keyboard(
                game.chat_id,
                game.available_categories,
                game.selected_categories,
                miniapp_url=miniapp_url,
            ),
        )
    await callback.answer("Категории сброшены.")


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
