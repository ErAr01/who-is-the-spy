from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from src.config import Settings


@dataclass(slots=True)
class AppContext:
    bot: Bot
    dispatcher: Dispatcher
    redis: Redis
    storage_redis: Redis


def build_app(settings: Settings) -> AppContext:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    storage_redis = Redis.from_url(settings.redis_url)
    storage = RedisStorage(redis=storage_redis)
    dispatcher = Dispatcher(storage=storage)
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    return AppContext(bot=bot, dispatcher=dispatcher, redis=redis, storage_redis=storage_redis)
