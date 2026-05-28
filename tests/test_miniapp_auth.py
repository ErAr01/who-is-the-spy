import hashlib
import hmac
import json
from time import time
from urllib.parse import urlencode
from unittest import TestCase

from src.miniapp.auth import TelegramInitDataValidator
from src.miniapp.errors import MiniAppError
from src.miniapp.session import MiniAppSessionManager


def _build_init_data(*, bot_token: str, user_id: int, first_name: str, auth_date: int) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "query-1",
        "user": json.dumps({"id": user_id, "first_name": first_name}, separators=(",", ":"), ensure_ascii=False),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items(), key=lambda item: item[0]))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(values)


class TelegramInitDataValidatorTest(TestCase):
    def test_valid_init_data(self) -> None:
        validator = TelegramInitDataValidator(bot_token="token-123", auth_ttl_seconds=300)
        init_data = _build_init_data(
            bot_token="token-123",
            user_id=42,
            first_name="Artem",
            auth_date=int(time()),
        )

        user = validator.validate(init_data)

        self.assertEqual(user.user_id, 42)
        self.assertEqual(user.full_name, "Artem")

    def test_rejects_expired_init_data(self) -> None:
        validator = TelegramInitDataValidator(bot_token="token-123", auth_ttl_seconds=1)
        init_data = _build_init_data(
            bot_token="token-123",
            user_id=42,
            first_name="Artem",
            auth_date=int(time()) - 10,
        )

        with self.assertRaises(MiniAppError) as exc:
            validator.validate(init_data)
        self.assertEqual(exc.exception.code, "init_data_expired")


class MiniAppSessionManagerTest(TestCase):
    def test_issue_and_verify(self) -> None:
        manager = MiniAppSessionManager(secret="test-secret", ttl_seconds=120)
        token, exp = manager.issue_token(user_id=11, chat_id=22, name="Alice")

        claims = manager.verify_token(token)

        self.assertEqual(claims.user_id, 11)
        self.assertEqual(claims.chat_id, 22)
        self.assertEqual(claims.name, "Alice")
        self.assertEqual(claims.exp, exp)

    def test_rejects_bad_signature(self) -> None:
        manager = MiniAppSessionManager(secret="test-secret", ttl_seconds=120)
        token, _ = manager.issue_token(user_id=11, chat_id=22, name="Alice")
        broken = f"{token}x"

        with self.assertRaises(MiniAppError) as exc:
            manager.verify_token(broken)
        self.assertEqual(exc.exception.code, "session_invalid")
