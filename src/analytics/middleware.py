from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware

from src.analytics.emitter import AnalyticsEmitter
from src.analytics.events import AnalyticsEvent, AnalyticsEventName


class AnalyticsErrorsMiddleware(BaseMiddleware):
    """Логирует непойманные исключения как аналитическое событие."""

    def __init__(self, analytics_emitter: AnalyticsEmitter) -> None:
        self._analytics_emitter = analytics_emitter

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as exc:
            handler_name = getattr(handler, "__qualname__", getattr(handler, "__name__", "unknown"))
            self._analytics_emitter.emit(
                AnalyticsEvent(
                    event_name=AnalyticsEventName.HANDLER_EXCEPTION,
                    chat_id=_extract_chat_id(event),
                    user_id=_extract_user_id(event),
                    payload={
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                        "handler_name": str(handler_name),
                        "update_type": type(event).__name__.lower(),
                    },
                )
            )
            raise


def _extract_chat_id(event: Any) -> int | None:
    chat = getattr(event, "chat", None)
    if chat is None:
        message = getattr(event, "message", None)
        chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    return chat_id if isinstance(chat_id, int) else None


def _extract_user_id(event: Any) -> int | None:
    user = getattr(event, "from_user", None)
    if user is None:
        message = getattr(event, "message", None)
        user = getattr(message, "from_user", None)
    user_id = getattr(user, "id", None)
    return user_id if isinstance(user_id, int) else None
