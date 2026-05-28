from contextlib import asynccontextmanager
import json
from time import time

from redis.asyncio import Redis
from redis.exceptions import LockError

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

    @staticmethod
    def game_version_key(chat_id: int) -> str:
        return f"game_version:{chat_id}"

    @staticmethod
    def game_lock_key(chat_id: int) -> str:
        return f"game_lock:{chat_id}"

    async def get_game(self, chat_id: int) -> Game | None:
        payload = await self._redis.get(self.game_key(chat_id))
        if payload is None:
            return None
        return Game.from_dict(json.loads(payload))

    async def save_game(self, game: Game, *, bump_version: bool = True) -> None:
        if bump_version:
            game.version = int(await self._redis.incr(self.game_version_key(game.chat_id)))
            game.updated_at_ts = time()
        await self._redis.set(self.game_key(game.chat_id), json.dumps(game.to_dict(), ensure_ascii=False))

    async def delete_game(self, chat_id: int) -> None:
        await self._redis.delete(self.game_key(chat_id))
        await self._redis.delete(self.game_version_key(chat_id))

    async def set_user_started(self, user_id: int) -> None:
        await self._redis.set(self.user_started_key(user_id), "1")

    async def has_user_started(self, user_id: int) -> bool:
        value = await self._redis.get(self.user_started_key(user_id))
        return value == "1"

    @asynccontextmanager
    async def chat_lock(
        self,
        chat_id: int,
        *,
        timeout_seconds: int = 10,
        blocking_timeout_seconds: int = 5,
    ):
        lock = self._redis.lock(
            self.game_lock_key(chat_id),
            timeout=timeout_seconds,
            blocking_timeout=blocking_timeout_seconds,
        )
        acquired = await lock.acquire()
        if not acquired:
            raise TimeoutError(f"Failed to acquire game lock for chat {chat_id}")
        try:
            yield
        finally:
            try:
                await lock.release()
            except LockError:
                pass
