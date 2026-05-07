from time import time

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from src.analytics import AnalyticsEmitter, AnalyticsEvent, AnalyticsEventName
from src.game.content import ContentProvider
from src.game.engine import (
    build_voting_result_text,
    finish_voting,
    prepare_game_round,
    send_roles,
    speaking_order_lines,
)
from src.game.models import Game, GameMode, GameState, Player
from src.game.provider_factory import build_content_provider
from src.game.repo import GameRepo
from src.handlers.callbacks import render_lobby_text
from src.utils.keyboards import lobby_keyboard, vote_keyboard

router = Router(name="group")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


def _build_content_provider() -> ContentProvider:
    return build_content_provider()


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


@router.message(Command("newgame"))
async def new_game(message: Message, repo: GameRepo, analytics_emitter: AnalyticsEmitter) -> None:
    if message.from_user is None:
        return
    existing = await repo.get_game(message.chat.id)
    if existing is not None:
        await message.answer("В этом чате уже есть активная игра. Используй /cancel для сброса.")
        return

    provider = _build_content_provider()

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

    lobby_message = await message.answer(
        render_lobby_text(game.chat_id, game.players, game.selected_categories),
        reply_markup=lobby_keyboard(game.chat_id, game.available_categories, game.selected_categories),
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
    if len(game.players) < 3:
        await message.answer("Нужно минимум 3 игрока.")
        return

    provider = _build_content_provider()
    try:
        game.available_categories = provider.get_available_categories()
        game = prepare_game_round(game, provider)
    except ValueError as exc:
        analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.CONTENT_SELECTION_FAILED,
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                game_id=str(message.chat.id),
                payload={"error": str(exc)},
            )
        )
        await message.answer(f"Не удалось начать игру: {exc}")
        return
    except Exception as exc:
        analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.CONTENT_SELECTION_FAILED,
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                game_id=str(message.chat.id),
                payload={"error": str(exc), "exception_type": type(exc).__name__},
            )
        )
        raise

    await repo.save_game(game)
    try:
        delivered, failed = await send_roles(bot, game, provider)
    except Exception as exc:
        analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.ROLE_DELIVERY_FAILED,
                chat_id=game.chat_id,
                user_id=message.from_user.id,
                game_id=str(game.chat_id),
                round_id=f"{game.chat_id}:1",
                payload={"error": str(exc), "exception_type": type(exc).__name__},
            )
        )
        raise
    if not delivered:
        analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.ROLE_DELIVERY_FAILED,
                chat_id=game.chat_id,
                user_id=message.from_user.id,
                game_id=str(game.chat_id),
                round_id=f"{game.chat_id}:1",
                payload={"failed_user_ids": failed, "failed_count": len(failed), "delivered_count": 0},
            )
        )
        await message.answer("Не удалось отправить роли никому. Проверь, что игроки написали боту в личку.")
        return

    if failed:
        analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.ROLE_DELIVERY_FAILED,
                chat_id=game.chat_id,
                user_id=message.from_user.id,
                game_id=str(game.chat_id),
                payload={"failed_user_ids": failed, "failed_count": len(failed)},
            )
        )
        await message.answer(
            "Не всем удалось отправить роли. Проверь личку бота у игроков: "
            + ", ".join(str(user_id) for user_id in failed)
        )

    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.GAME_STARTED,
            chat_id=game.chat_id,
            user_id=message.from_user.id,
            game_id=str(game.chat_id),
            round_id=f"{game.chat_id}:1",
            payload={
                "players_count": len(game.players),
                "delivered_count": len(delivered),
                "failed_count": len(failed),
                "selected_categories": list(game.selected_categories),
            },
        )
    )
    await message.answer(_round_rules_text())
    order = "\n".join(speaking_order_lines(game))
    await message.answer(f"Порядок выступлений:\n{order}\n\nКогда закончите, запустите /vote.")


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

    game.state = GameState.VOTING
    game.votes = {}
    await repo.save_game(game)
    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.VOTING_STARTED,
            chat_id=game.chat_id,
            user_id=message.from_user.id,
            game_id=str(game.chat_id),
            round_id=f"{game.chat_id}:1",
            payload={"players_count": len(game.players), "votes_count": 0},
        )
    )
    await message.answer("Голосование открыто. Выберите подозреваемого:", reply_markup=vote_keyboard(game))


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

    result = finish_voting(game)
    await message.answer(build_voting_result_text(game, result))
    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.ROUND_FINISHED,
            chat_id=game.chat_id,
            user_id=message.from_user.id,
            game_id=str(game.chat_id),
            round_id=f"{game.chat_id}:1",
            payload={
                "votes_count": len(game.votes),
                "voted_out_id": result.voted_out_id,
                "is_spy_caught": result.is_spy_caught,
                "round_duration_seconds": result.round_duration_seconds,
            },
        )
    )
    await repo.delete_game(game.chat_id)


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

    await repo.delete_game(game.chat_id)
    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.GAME_CANCELLED,
            chat_id=game.chat_id,
            user_id=message.from_user.id,
            game_id=str(game.chat_id),
            payload={
                "state_before_cancel": game.state.value,
                "players_count": len(game.players),
                "round_duration_seconds": (
                    max(0, int(time() - game.round_started_at_ts))
                    if game.round_started_at_ts is not None
                    else None
                ),
            },
        )
    )
    await message.answer("Игра отменена.")
