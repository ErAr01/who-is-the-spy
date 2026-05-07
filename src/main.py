import asyncio
import logging

from src.analytics import AnalyticsErrorsMiddleware, CompositeAnalyticsEmitter, StdoutJsonAnalyticsEmitter
from src.bot import build_app
from src.config import get_settings
from src.game.repo import GameRepo
from src.handlers.callbacks import router as callbacks_router
from src.handlers.group import router as group_router
from src.handlers.private import router as private_router
from src.observability import PrometheusAnalyticsEmitter, PrometheusUpdatesMiddleware, start_metrics_http_server


async def run() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if settings.metrics_enabled:
        start_metrics_http_server(settings.metrics_host, settings.metrics_port)

    app = build_app(settings)
    repo = GameRepo(app.redis)
    analytics_emitters = [StdoutJsonAnalyticsEmitter()]
    if settings.metrics_enabled:
        analytics_emitters.append(PrometheusAnalyticsEmitter())
    analytics_emitter = CompositeAnalyticsEmitter(emitters=analytics_emitters)
    app.dispatcher["repo"] = repo
    app.dispatcher["analytics_emitter"] = analytics_emitter
    app.dispatcher["dispatcher"] = app.dispatcher
    if settings.metrics_enabled:
        app.dispatcher.update.outer_middleware(PrometheusUpdatesMiddleware())
    app.dispatcher.update.outer_middleware(AnalyticsErrorsMiddleware(analytics_emitter))
    app.dispatcher.include_router(private_router)
    app.dispatcher.include_router(group_router)
    app.dispatcher.include_router(callbacks_router)

    try:
        await app.dispatcher.start_polling(app.bot)
    finally:
        await app.bot.session.close()
        await app.redis.aclose()
        await app.storage_redis.aclose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
