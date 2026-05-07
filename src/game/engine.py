import random
from dataclasses import dataclass
from html import escape
from time import time
from typing import Iterable
from urllib.parse import quote_plus

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import BufferedInputFile

from src.game.content import ContentProvider
from src.game.models import Game, GameState, PayloadType


@dataclass(slots=True)
class VotingResult:
    voted_out_id: int | None
    votes: dict[int, int]
    is_spy_caught: bool
    round_duration_seconds: int | None


def prepare_game_round(game: Game, content: ContentProvider) -> Game:
    if not game.players:
        raise ValueError("Game has no players")

    spy = random.choice(game.players)
    game.spy_id = spy.user_id
    game.speaking_order = [player.user_id for player in game.players]
    random.shuffle(game.speaking_order)

    pair = content.get_random_image_pair(game.selected_categories or None, chat_id=game.chat_id)
    game.theme = pair.theme
    game.payload_type = PayloadType.PHOTO
    game.civilian_payload = pair.civilian
    game.spy_payload = pair.spy
    game.civilian_name = pair.civilian_name
    game.spy_name = pair.spy_name
    game.civilian_wiki_url = pair.civilian_wiki_url
    game.spy_wiki_url = pair.spy_wiki_url
    game.civilian_search_url = build_google_search_url(pair.civilian_name)
    game.spy_search_url = build_google_search_url(pair.spy_name)

    game.state = GameState.PLAYING
    game.votes = {}
    game.round_started_at_ts = time()
    return game


async def send_roles(bot: Bot, game: Game, content: ContentProvider) -> tuple[list[int], list[int]]:
    delivered: list[int] = []
    failed: list[int] = []
    for player in game.players:
        payload = game.spy_payload if player.user_id == game.spy_id else game.civilian_payload
        if payload is None:
            failed.append(player.user_id)
            continue

        try:
            image_bytes = content.get_image_bytes(payload)
            if image_bytes is None:
                failed.append(player.user_id)
                continue

            caption = _build_role_caption(game, player.user_id)
            wiki_url = _wiki_url_for_player(game, player.user_id)
            search_url = _search_url_for_player(game, player.user_id)
            if wiki_url:
                safe_url = escape(wiki_url, quote=True)
                caption = f"{caption}\nWikipedia: <a href=\"{safe_url}\">ссылка</a>"
            if search_url:
                safe_url = escape(search_url, quote=True)
                caption = f"{caption}\nGoogle: <a href=\"{safe_url}\">поиск</a>"

            await bot.send_photo(
                player.user_id,
                photo=BufferedInputFile(image_bytes, filename=f"{payload}.jpg"),
                caption=caption,
            )
            delivered.append(player.user_id)
        except TelegramForbiddenError:
            failed.append(player.user_id)
    return delivered, failed


def finish_voting(game: Game) -> VotingResult:
    round_duration_seconds = _round_duration_seconds(game)
    if not game.votes:
        game.state = GameState.FINISHED
        game.round_started_at_ts = None
        return VotingResult(
            voted_out_id=None,
            votes={},
            is_spy_caught=False,
            round_duration_seconds=round_duration_seconds,
        )

    tally: dict[int, int] = {}
    for target in game.votes.values():
        tally[target] = tally.get(target, 0) + 1

    voted_out_id = sorted(tally.items(), key=lambda item: (-item[1], item[0]))[0][0]
    is_spy_caught = voted_out_id == game.spy_id
    game.state = GameState.FINISHED
    game.round_started_at_ts = None
    return VotingResult(
        voted_out_id=voted_out_id,
        votes=tally,
        is_spy_caught=is_spy_caught,
        round_duration_seconds=round_duration_seconds,
    )


def all_players_voted(game: Game) -> bool:
    player_ids = {player.user_id for player in game.players}
    return player_ids.issubset(set(game.votes))


def player_name_by_id(game: Game, user_id: int) -> str:
    for player in game.players:
        if player.user_id == user_id:
            return player.name
    return str(user_id)


def speaking_order_lines(game: Game) -> Iterable[str]:
    for index, user_id in enumerate(game.speaking_order, start=1):
        yield f"{index}. {player_name_by_id(game, user_id)}"


def _build_role_caption(game: Game, user_id: int) -> str:
    hero_name = game.spy_name if user_id == game.spy_id else game.civilian_name
    return f"<b>{escape(hero_name or 'Персонаж')}</b>"


def _wiki_url_for_player(game: Game, user_id: int) -> str | None:
    if user_id == game.spy_id:
        return game.spy_wiki_url
    return game.civilian_wiki_url


def _search_url_for_player(game: Game, user_id: int) -> str | None:
    if user_id == game.spy_id:
        return game.spy_search_url
    return game.civilian_search_url


def build_google_search_url(query: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(query)}"


def build_voting_result_text(game: Game, result: VotingResult) -> str:
    lines = ["Голосование завершено."]
    if result.voted_out_id is None:
        lines.append("Никто не проголосовал.")
    else:
        voted_name = player_name_by_id(game, result.voted_out_id)
        lines.append(f"Большинство выбрало: <b>{voted_name}</b>")

    if game.spy_id is not None:
        spy_name = player_name_by_id(game, game.spy_id)
        lines.append(f"Шпионом был: <b>{spy_name}</b>")

    if result.is_spy_caught:
        lines.append("Мирные победили.")
    else:
        lines.append("Шпион победил.")

    return "\n".join(lines)


def _round_duration_seconds(game: Game) -> int | None:
    if game.round_started_at_ts is None:
        return None
    duration = int(time() - game.round_started_at_ts)
    return max(0, duration)
