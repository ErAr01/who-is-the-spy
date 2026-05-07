from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.analytics import AnalyticsEmitter, AnalyticsEvent, AnalyticsEventName
from src.game.engine import all_players_voted, build_voting_result_text, finish_voting
from src.game.models import GameState, Player
from src.game.repo import GameRepo
from src.utils.keyboards import lobby_keyboard

router = Router(name="callbacks")


@router.callback_query(F.data.startswith("noop:"))
async def noop(callback: CallbackQuery) -> None:
    await callback.answer("Сначала добавьте карточки в категории через labeling.")


def render_lobby_text(game_chat_id: int, players: list[Player], selected_categories: list[str]) -> str:
    names = [f"- {p.name}" for p in players] or ["- Пока никого"]
    players_text = "\n".join(names)
    categories_text = ", ".join(selected_categories) if selected_categories else "все доступные"
    return (
        f"Игра в чате <code>{game_chat_id}</code>\n"
        "Режим: <b>Картинки из БД</b>\n"
        f"Категории: <b>{categories_text}</b>\n"
        f"Игроки:\n{players_text}\n\n"
        "Нажми Join, чтобы участвовать."
    )


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
        if callback.message:
            await callback.message.answer(build_voting_result_text(game, result))
        analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.ROUND_FINISHED,
                chat_id=game.chat_id,
                user_id=callback.from_user.id,
                game_id=str(game.chat_id),
                round_id=f"{game.chat_id}:1",
                payload={
                    "votes_count": len(game.votes),
                    "voted_out_id": result.voted_out_id,
                    "is_spy_caught": result.is_spy_caught,
                    "auto_finished": True,
                    "round_duration_seconds": result.round_duration_seconds,
                },
            )
        )
        await repo.delete_game(game.chat_id)
