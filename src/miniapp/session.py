from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from time import time

from src.miniapp.errors import MiniAppError


@dataclass(slots=True, frozen=True)
class MiniAppSessionClaims:
    user_id: int
    chat_id: int
    name: str
    exp: int


class MiniAppSessionManager:
    def __init__(self, *, secret: str, ttl_seconds: int) -> None:
        self._secret = secret.encode("utf-8")
        self._ttl_seconds = ttl_seconds

    def issue_token(self, *, user_id: int, chat_id: int, name: str) -> tuple[str, int]:
        now = int(time())
        exp = now + self._ttl_seconds
        payload = {"user_id": user_id, "chat_id": chat_id, "name": name, "iat": now, "exp": exp}
        payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        signature = hmac.new(self._secret, payload_bytes, hashlib.sha256).digest()
        token = (
            f"{_urlsafe_b64encode(payload_bytes)}"
            f".{_urlsafe_b64encode(signature)}"
        )
        return token, exp

    def verify_token(self, token: str) -> MiniAppSessionClaims:
        try:
            payload_part, signature_part = token.split(".", maxsplit=1)
            payload_bytes = _urlsafe_b64decode(payload_part)
            signature = _urlsafe_b64decode(signature_part)
        except ValueError as exc:
            raise MiniAppError(
                code="session_invalid",
                message="Некорректный формат сессии.",
                status_code=401,
            ) from exc

        expected_signature = hmac.new(self._secret, payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_signature, signature):
            raise MiniAppError(
                code="session_invalid",
                message="Подпись сессии не прошла проверку.",
                status_code=401,
            )

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
            exp = int(payload["exp"])
            user_id = int(payload["user_id"])
            chat_id = int(payload["chat_id"])
            name = str(payload["name"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MiniAppError(
                code="session_invalid",
                message="Поврежден payload сессии.",
                status_code=401,
            ) from exc

        if int(time()) >= exp:
            raise MiniAppError(
                code="session_expired",
                message="Сессия истекла.",
                status_code=401,
            )
        return MiniAppSessionClaims(user_id=user_id, chat_id=chat_id, name=name, exp=exp)


def _urlsafe_b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _urlsafe_b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}".encode("ascii"))
