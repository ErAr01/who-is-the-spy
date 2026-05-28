from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from src.analytics import AnalyticsEmitter, AnalyticsEvent, AnalyticsEventName
from src.game.engine import (
    VotingResult,
    build_voting_result_text,
    finish_voting,
    prepare_game_round,
    send_roles,
)
from src.game.models import Game, GameState
from src.game.provider_factory import build_content_provider
from src.utils.keyboards import admin_controls_keyboard, post_round_keyboard, vote_keyboard

if TYPE_CHECKING:
    from src.game.repo import GameRepo


@dataclass(slots=True)
class StartRoundResult:
    delivered: list[int]
    failed: list[int]


def round_rules_text() -> str:
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


def commands_guide_text() -> str:
    return (
        "Команды игры:\n"
        "- <b>/newgame</b> — создать новое лобби.\n"
        "- <b>Join</b> — присоединиться к игре через кнопку в лобби.\n"
        "- <b>/startgame</b> — начать раунд и раздать роли.\n"
        "- <b>/vote</b> — открыть голосование.\n"
        "- <b>/endvote</b> — завершить голосование вручную.\n"
        "- <b>/cancel</b> — отменить текущую игру."
    )


async def start_round(
    *,
    game: Game,
    actor_id: int,
    repo: GameRepo,
    bot: Bot,
    analytics_emitter: AnalyticsEmitter,
    responder: Message | None,
    started_from_post_round: bool = False,
) -> StartRoundResult:
    provider = build_content_provider()
    try:
        game.available_categories = provider.get_available_categories()
        game = prepare_game_round(game, provider)
    except ValueError as exc:
        analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.CONTENT_SELECTION_FAILED,
                chat_id=game.chat_id,
                user_id=actor_id,
                game_id=str(game.chat_id),
                payload={"error": str(exc)},
            )
        )
        raise
    except Exception as exc:
        analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.CONTENT_SELECTION_FAILED,
                chat_id=game.chat_id,
                user_id=actor_id,
                game_id=str(game.chat_id),
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
                user_id=actor_id,
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
                user_id=actor_id,
                game_id=str(game.chat_id),
                round_id=f"{game.chat_id}:1",
                payload={"failed_user_ids": failed, "failed_count": len(failed), "delivered_count": 0},
            )
        )
    elif failed:
        analytics_emitter.emit(
            AnalyticsEvent(
                event_name=AnalyticsEventName.ROLE_DELIVERY_FAILED,
                chat_id=game.chat_id,
                user_id=actor_id,
                game_id=str(game.chat_id),
                payload={"failed_user_ids": failed, "failed_count": len(failed)},
            )
        )

    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.GAME_STARTED,
            chat_id=game.chat_id,
            user_id=actor_id,
            game_id=str(game.chat_id),
            round_id=f"{game.chat_id}:1",
            payload={
                "players_count": len(game.players),
                "delivered_count": len(delivered),
                "failed_count": len(failed),
                "selected_categories": list(game.selected_categories),
                "started_from_post_round": started_from_post_round,
            },
        )
    )

    if responder is not None:
        commands_message = await responder.answer(commands_guide_text())
        try:
            await bot.pin_chat_message(
                chat_id=game.chat_id,
                message_id=commands_message.message_id,
                disable_notification=True,
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
        await responder.answer(round_rules_text())
        await responder.answer(
            "Вы можете определить порядок хода самостоятельно, но если среди вас есть игрок по имени Даша, "
            "то она ходит первой",
            reply_markup=admin_controls_keyboard(game),
        )

    return StartRoundResult(delivered=delivered, failed=failed)


async def open_voting(
    *,
    game: Game,
    actor_id: int,
    repo: GameRepo,
    analytics_emitter: AnalyticsEmitter,
    responder: Message | None,
) -> None:
    game.state = GameState.VOTING
    game.votes = {}
    await repo.save_game(game)
    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.VOTING_STARTED,
            chat_id=game.chat_id,
            user_id=actor_id,
            game_id=str(game.chat_id),
            round_id=f"{game.chat_id}:1",
            payload={"players_count": len(game.players), "votes_count": 0},
        )
    )
    if responder is not None:
        await responder.answer(
            "Голосование открыто. Выберите подозреваемого:",
            reply_markup=vote_keyboard(game, include_admin_controls=True),
        )


async def close_voting(
    *,
    game: Game,
    actor_id: int,
    repo: GameRepo,
    analytics_emitter: AnalyticsEmitter,
    responder: Message | None,
    auto_finished: bool,
) -> None:
    result = finish_voting(game)
    await complete_round(
        game=game,
        result=result,
        repo=repo,
        analytics_emitter=analytics_emitter,
        user_id=actor_id,
        responder=responder,
        auto_finished=auto_finished,
    )


async def cancel_game(
    *,
    game: Game,
    actor_id: int,
    repo: GameRepo,
    analytics_emitter: AnalyticsEmitter,
    responder: Message | None,
) -> None:
    await repo.delete_game(game.chat_id)
    analytics_emitter.emit(
        AnalyticsEvent(
            event_name=AnalyticsEventName.GAME_CANCELLED,
            chat_id=game.chat_id,
            user_id=actor_id,
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
    if responder is not None:
        await responder.answer("Игра отменена.")


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
