from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from src.analytics import AnalyticsEmitter, AnalyticsEvent, AnalyticsEventName
from src.game.engine import (
    VotingResult,
    all_players_voted,
    build_voting_result_text,
    finish_voting,
    prepare_game_round,
    send_roles,
    speaking_order_lines,
)
from src.game.models import Game, GameState, Player
from src.game.provider_factory import build_content_provider
from src.utils.category_labels import format_categories
from src.utils.keyboards import lobby_keyboard, post_round_keyboard

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


def _round_rules_text() -> str:
    return (
        "Каждому игроку показывается картинка с персонажем. У большинства игроков будет один и тот же персонаж, "
        "но у одного игрока — другой. Этот игрок и есть шпион.\n\n"
        "По очереди игроки называют факты о своём персонаже: как он выглядит, где мог появляться, какие у него "
        "особенности, характер или ассоциации. При этом важно говорить так, чтобы не раскрыть слишком много, "
        "но и не вызвать подозрений.\n\n"
        "Ваша задача — понять, кто вы: мирный житель или шпион. Слушайте ответы других игроков, сравнивайте их со "
        "своей картинкой и пытайтесь определить, кто говорит не о том персонаже.\n\n"
        "Если вы поняли, что шпион — это вы, старайтесь подстраиваться под ответы остальных игроков, говорить "
        "осторожно и не выдавать себя.\n\n"
        "В конце раунда все игроки голосуют за того, кого считают шпионом. Побеждают мирные жители, если правильно "
        "находят шпиона. Шпион побеждает, если ему удаётся остаться незамеченным."
    )


async def complete_round(
    *,
    game: Game,
    result: VotingResult,
    repo: GameRepo,
    analytics_emitter: AnalyticsEmitter,
    user_id: int,
    responder: Message | None,
    auto_finished: bool,
) -> None:
    if responder is not None:
        await responder.answer(build_voting_result_text(game, result), reply_markup=post_round_keyboard(game.chat_id))

    payload: dict[str, int | bool | None] = {
        "votes_count": len(game.votes),
        "voted_out_id": result.voted_out_id,
        "is_spy_caught": result.is_spy_caught,
        "round_duration_seconds": result.round_duration_seconds,
    }
    if auto_finished:
        payload["auto_finished"] = True

    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.ROUND_FINISHED,
            chat_id=game.chat_id,
            user_id=user_id,
            game_id=str(game.chat_id),
            round_id=f"{game.chat_id}:1",
            payload=payload,
        )
    )
    await repo.save_game(game)


@router.callback_query(F.data.startswith("join:"))
async def join_game(callback: CallbackQuery, repo: GameRepo, analytics_emitter: AnalyticsEmitter) -> None:
    if callback.from_user is None or callback.data is None:
        return

    _, chat_id_raw = callback.data.split(":")
    chat_id = int(chat_id_raw)
    game = await repo.get_game(chat_id)
    if game is None:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    if game.state != GameState.LOBBY:
        await callback.answer("Игра уже началась.", show_alert=True)
        return
    if not await repo.has_user_started(callback.from_user.id):
        await callback.answer("Сначала напиши боту в личку: /start", show_alert=True)
        return

    if all(player.user_id != callback.from_user.id for player in game.players):
        display_name = callback.from_user.full_name or str(callback.from_user.id)
        game.players.append(Player(user_id=callback.from_user.id, name=display_name))
        await repo.save_game(game)
        analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.PLAYER_JOINED,
                chat_id=game.chat_id,
                user_id=callback.from_user.id,
                game_id=str(game.chat_id),
                payload={"players_count": len(game.players)},
            )
        )

    if callback.message:
        await callback.message.edit_text(
            render_lobby_text(game.chat_id, game.players, game.selected_categories),
            reply_markup=lobby_keyboard(game.chat_id, game.available_categories, game.selected_categories),
        )
    await callback.answer("Ты в игре.")


@router.callback_query(F.data.startswith("category:"))
async def toggle_category(callback: CallbackQuery, repo: GameRepo, analytics_emitter: AnalyticsEmitter) -> None:
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
    if callback.message:
        await callback.message.edit_text(
            render_lobby_text(game.chat_id, game.players, game.selected_categories),
            reply_markup=lobby_keyboard(game.chat_id, game.available_categories, game.selected_categories),
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

    player_ids = {player.user_id for player in game.players}
    if callback.from_user.id not in player_ids:
        await callback.answer("Ты не участник этой игры.", show_alert=True)
        return
    if target_id not in player_ids:
        await callback.answer("Неверная цель голоса.", show_alert=True)
        return

    game.votes[callback.from_user.id] = target_id
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
        result = finish_voting(game)
        await complete_round(
            game=game,
            result=result,
            repo=repo,
            analytics_emitter=analytics_emitter,
            user_id=callback.from_user.id,
            responder=callback.message,
            auto_finished=True,
        )


@router.callback_query(F.data.startswith("postround:repeat:"))
async def repeat_round(
    callback: CallbackQuery,
    repo: GameRepo,
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
    if game.state != GameState.FINISHED:
        await callback.answer("Раунд еще не завершен.", show_alert=True)
        return

    provider = build_content_provider()
    game.available_categories = provider.get_available_categories()
    try:
        game = prepare_game_round(game, provider)
    except ValueError as exc:
        await callback.answer(f"Не удалось начать раунд: {exc}", show_alert=True)
        return

    await repo.save_game(game)
    delivered, failed = await send_roles(bot, game, provider)
    if not delivered:
        await callback.answer("Не удалось отправить роли. Проверь личку бота у игроков.", show_alert=True)
        return
    if failed and callback.message:
        await callback.message.answer(
            "Не всем удалось отправить роли. Проверь личку бота у игроков: "
            + ", ".join(str(user_id) for user_id in failed)
        )

    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.GAME_STARTED,
            chat_id=game.chat_id,
            user_id=callback.from_user.id,
            game_id=str(game.chat_id),
            round_id=f"{game.chat_id}:1",
            payload={
                "players_count": len(game.players),
                "delivered_count": len(delivered),
                "failed_count": len(failed),
                "selected_categories": list(game.selected_categories),
                "started_from_post_round": True,
            },
        )
    )
    if callback.message:
        await callback.message.answer(_round_rules_text())
        order = "\n".join(speaking_order_lines(game))
        await callback.message.answer(f"Порядок выступлений:\n{order}\n\nКогда закончите, запустите /vote.")
    await callback.answer("Новый раунд запущен.")


@router.callback_query(F.data.startswith("postround:newcats:"))
async def choose_new_categories(callback: CallbackQuery, repo: GameRepo) -> None:
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
    game.speaking_order = []
    game.round_started_at_ts = None
    game.selected_categories = []
    game.available_categories = build_content_provider().get_available_categories()
    await repo.save_game(game)

    if callback.message:
        await callback.message.answer(
            render_lobby_text(game.chat_id, game.players, game.selected_categories),
            reply_markup=lobby_keyboard(game.chat_id, game.available_categories, game.selected_categories),
        )
    await callback.answer("Категории сброшены.")
