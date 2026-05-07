from __future__ import annotations

import hashlib
from time import monotonic
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from prometheus_client import Counter, Histogram, start_http_server

from src.analytics.emitter import AnalyticsEmitter
from src.analytics.events import AnalyticsEvent, AnalyticsEventName

_METRICS_SERVER_STARTED = False
_UNIQUE_BUCKETS = 1024

bot_updates_total = Counter(
    "bot_updates_total",
    "Total processed bot updates",
    labelnames=("update_type",),
)
bot_handler_exceptions_total = Counter(
    "bot_handler_exceptions_total",
    "Total unhandled bot handler exceptions",
    labelnames=("exception_type", "handler_name", "update_type"),
)
analytics_events_total = Counter(
    "analytics_events_total",
    "Total analytics events emitted",
    labelnames=("event_name",),
)
analytics_actor_bucket_touches_total = Counter(
    "analytics_actor_bucket_touches_total",
    "Bucket touches for approximate unique actors by day",
    labelnames=("actor_type", "bucket"),
)
round_duration_seconds = Histogram(
    "round_duration_seconds",
    "Duration of finished game rounds",
    buckets=(10, 20, 30, 45, 60, 90, 120, 180, 240, 300, 420, 600, 900, 1200, 1800),
)
bot_update_duration_seconds = Histogram(
    "bot_update_duration_seconds",
    "Bot update handler duration",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def start_metrics_http_server(host: str, port: int) -> None:
    global _METRICS_SERVER_STARTED
    if _METRICS_SERVER_STARTED:
        return
    start_http_server(port=port, addr=host)
    _METRICS_SERVER_STARTED = True


class PrometheusAnalyticsEmitter:
    """Prometheus bridge for app analytics events."""

    def emit(self, event: AnalyticsEvent) -> None:
        event_name = event.event_name.value if isinstance(event.event_name, AnalyticsEventName) else str(event.event_name)
        analytics_events_total.labels(event_name=event_name).inc()

        if event.user_id is not None:
            analytics_actor_bucket_touches_total.labels(
                actor_type="user",
                bucket=_bucket_for_identifier(event.user_id),
            ).inc()

        if event.chat_id is not None and event.game_id is not None:
            analytics_actor_bucket_touches_total.labels(
                actor_type="group_chat",
                bucket=_bucket_for_identifier(event.chat_id),
            ).inc()

        if event_name == AnalyticsEventName.ROUND_FINISHED.value:
            duration_seconds = event.payload.get("round_duration_seconds")
            if isinstance(duration_seconds, (int, float)) and duration_seconds >= 0:
                round_duration_seconds.observe(float(duration_seconds))

        if event_name == AnalyticsEventName.HANDLER_EXCEPTION.value:
            exception_type = str(event.payload.get("exception_type", "unknown"))
            handler_name = str(event.payload.get("handler_name", "unknown"))
            update_type = str(event.payload.get("update_type", "unknown"))
            bot_handler_exceptions_total.labels(
                exception_type=exception_type,
                handler_name=handler_name,
                update_type=update_type,
            ).inc()


class PrometheusUpdatesMiddleware(BaseMiddleware):
    """Collects update count and duration for every handled update."""

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        update_type = type(event).__name__.lower()
        started_at = monotonic()
        bot_updates_total.labels(update_type=update_type).inc()
        try:
            return await handler(event, data)
        finally:
            bot_update_duration_seconds.observe(monotonic() - started_at)


def _bucket_for_identifier(identifier: int) -> str:
    digest = hashlib.sha256(str(identifier).encode("utf-8")).hexdigest()
    return str(int(digest[:8], 16) % _UNIQUE_BUCKETS)
