import json

from redis.asyncio import Redis

from src.game.models import Game


class GameRepo:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def game_key(chat_id: int) -> str:
        return f"game:{chat_id}"

    @staticmethod
    def user_started_key(user_id: int) -> str:
        return f"user_started:{user_id}"

    async def get_game(self, chat_id: int) -> Game | None:
        payload = await self._redis.get(self.game_key(chat_id))
        if payload is None:
            return None
        return Game.from_dict(json.loads(payload))

    async def save_game(self, game: Game) -> None:
        await self._redis.set(self.game_key(game.chat_id), json.dumps(game.to_dict(), ensure_ascii=False))

    async def delete_game(self, chat_id: int) -> None:
        await self._redis.delete(self.game_key(chat_id))

    async def set_user_started(self, user_id: int) -> None:
        await self._redis.set(self.user_started_key(user_id), "1")

    async def has_user_started(self, user_id: int) -> bool:
        value = await self._redis.get(self.user_started_key(user_id))
        return value == "1"
