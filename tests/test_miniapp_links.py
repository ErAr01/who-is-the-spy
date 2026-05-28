from unittest import TestCase

from src.utils.miniapp_links import build_miniapp_chat_url, build_telegram_miniapp_deeplink


class MiniAppLinksTest(TestCase):
    def test_returns_none_when_base_url_missing(self) -> None:
        self.assertIsNone(build_miniapp_chat_url(None, 123))
        self.assertIsNone(build_miniapp_chat_url("   ", 123))

    def test_appends_chat_id_when_no_query(self) -> None:
        self.assertEqual(
            build_miniapp_chat_url("https://example.sslip.io", 777),
            "https://example.sslip.io?chat_id=777",
        )

    def test_replaces_existing_chat_id_and_preserves_other_params(self) -> None:
        self.assertEqual(
            build_miniapp_chat_url("https://example.sslip.io/path?foo=1&chat_id=5", 777),
            "https://example.sslip.io/path?foo=1&chat_id=777",
        )

    def test_supports_private_mode_param(self) -> None:
        self.assertEqual(
            build_miniapp_chat_url("https://example.sslip.io/path?foo=1", 321, mode="testpair"),
            "https://example.sslip.io/path?foo=1&chat_id=321&mode=testpair",
        )

    def test_builds_telegram_miniapp_deeplink(self) -> None:
        self.assertEqual(
            build_telegram_miniapp_deeplink(
                bot_username="@who_is_spy_game_bot",
                short_name="app",
                chat_id=-5196715372,
            ),
            "https://t.me/who_is_spy_game_bot/app?startapp=chat_-5196715372",
        )
