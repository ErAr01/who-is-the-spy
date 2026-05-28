from __future__ import annotations

from time import time

from src.game.models import Game, GameState


def touch_activity(game: Game) -> None:
    game.last_activity_ts = time()


def is_lobby_expired(game: Game, *, idle_seconds: int) -> bool:
    if idle_seconds <= 0:
        return False
    if game.last_activity_ts is None:
        return False
    return (time() - game.last_activity_ts) > idle_seconds


def reset_to_fresh_lobby(game: Game, *, available_categories: list[str]) -> None:
    game.state = GameState.LOBBY
    game.players = []
    game.round_player_ids = []
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
    game.last_voted_out_id = None
    game.last_is_spy_caught = None
    game.last_round_duration_seconds = None
    game.round_started_at_ts = None
    game.selected_categories = []
    game.available_categories = available_categories
    touch_activity(game)
