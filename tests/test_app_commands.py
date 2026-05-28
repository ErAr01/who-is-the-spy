from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from src.handlers.group import open_group_miniapp
from src.handlers.private import open_private_miniapp


class AppCommandsTest(IsolatedAsyncioTestCase):
    async def test_group_app_command_sends_webapp_button(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-100555),
            answer=AsyncMock(),
        )
        settings = SimpleNamespace(miniapp_public_url="https://example.sslip.io")

        await open_group_miniapp(message, settings)

        message.answer.assert_awaited_once()
        kwargs = message.answer.await_args.kwargs
        self.assertIn("reply_markup", kwargs)
        keyboard = kwargs["reply_markup"]
        self.assertEqual(keyboard.inline_keyboard[0][0].web_app.url, "https://example.sslip.io?chat_id=-100555")

    async def test_private_app_command_uses_testpair_mode(self) -> None:
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=42),
            answer=AsyncMock(),
        )
        settings = SimpleNamespace(miniapp_public_url="https://example.sslip.io")

        await open_private_miniapp(message, settings)

        message.answer.assert_awaited_once()
        kwargs = message.answer.await_args.kwargs
        keyboard = kwargs["reply_markup"]
        self.assertEqual(
            keyboard.inline_keyboard[0][0].web_app.url,
            "https://example.sslip.io?chat_id=42&mode=testpair",
        )
