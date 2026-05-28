from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from time import time
from urllib.parse import parse_qsl

from src.miniapp.errors import MiniAppError


@dataclass(slots=True, frozen=True)
class TelegramInitDataUser:
    user_id: int
    full_name: str


class TelegramInitDataValidator:
    def __init__(self, *, bot_token: str, auth_ttl_seconds: int) -> None:
        self._bot_token = bot_token
        self._auth_ttl_seconds = auth_ttl_seconds

    def validate(self, init_data: str) -> TelegramInitDataUser:
        try:
            values = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        except ValueError as exc:
            raise MiniAppError(
                code="init_data_invalid",
                message="Некорректный формат initData.",
                status_code=401,
            ) from exc
        provided_hash = values.pop("hash", "")
        if not provided_hash:
            raise MiniAppError(
                code="init_data_invalid",
                message="Отсутствует hash в initData.",
                status_code=401,
            )

        auth_date_raw = values.get("auth_date")
        if auth_date_raw is None:
            raise MiniAppError(
                code="init_data_invalid",
                message="Отсутствует auth_date в initData.",
                status_code=401,
            )
        try:
            auth_date = int(auth_date_raw)
        except ValueError as exc:
            raise MiniAppError(
                code="init_data_invalid",
                message="auth_date должен быть integer.",
                status_code=401,
            ) from exc

        if time() - auth_date > self._auth_ttl_seconds:
            raise MiniAppError(
                code="init_data_expired",
                message="Срок действия initData истек.",
                status_code=401,
            )

        data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items(), key=lambda item: item[0]))
        secret_key = hmac.new(b"WebAppData", self._bot_token.encode("utf-8"), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash, provided_hash):
            raise MiniAppError(
                code="init_data_invalid",
                message="Подпись initData не прошла проверку.",
                status_code=401,
            )

        user_raw = values.get("user")
        if not user_raw:
            raise MiniAppError(
                code="init_data_invalid",
                message="Отсутствуют данные пользователя.",
                status_code=401,
            )
        try:
            user_data = json.loads(user_raw)
            user_id = int(user_data["id"])
            first_name = str(user_data.get("first_name", "")).strip()
            last_name = str(user_data.get("last_name", "")).strip()
            full_name = " ".join(item for item in (first_name, last_name) if item).strip() or str(user_id)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MiniAppError(
                code="init_data_invalid",
                message="Некорректный user в initData.",
                status_code=401,
            ) from exc
        return TelegramInitDataUser(user_id=user_id, full_name=full_name)
