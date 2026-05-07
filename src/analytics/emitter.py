from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from src.analytics.events import AnalyticsEvent


class AnalyticsEmitter(Protocol):
    """Интерфейс эмиттера аналитики."""

    def emit(self, event: AnalyticsEvent) -> None:
        """Публикует аналитическое событие."""


@dataclass(slots=True)
class StdoutJsonAnalyticsEmitter:
    """
    Базовая реализация эмиттера.

    Сейчас пишет line-delimited JSON в stdout.
    """

    def emit(self, event: AnalyticsEvent) -> None:
        print(json.dumps(event.to_dict(), ensure_ascii=False), flush=True)


@dataclass(slots=True)
class CompositeAnalyticsEmitter:
    """
    Централизованный emitter-агрегатор.

    Позволяет добавить несколько бекендов (например, stdout + PostHog).
    """

    emitters: list[AnalyticsEmitter] = field(default_factory=list)

    def emit(self, event: AnalyticsEvent) -> None:
        for emitter in self.emitters:
            emitter.emit(event)
