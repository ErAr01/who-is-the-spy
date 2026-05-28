from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MiniAppError(Exception):
    code: str
    message: str
    status_code: int

    def __str__(self) -> str:
        return self.message
