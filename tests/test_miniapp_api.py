from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from time import time
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest import TestCase
from unittest.mock import Mock

from fastapi.testclient import TestClient

from src.config import Settings
from src.game.models import Game, GameMode, GameState, PayloadType, Player
from src.miniapp.api import build_miniapp_api


class _InMemoryRepo:
    def __init__(self, game: Game) -> None:
        self.game = game
        self._version = game.version
        self._started_users: set[int] = set()

    async def get_game(self, chat_id: int) -> Game | None:
        if self.game is None:
            return None
        return self.game if self.game.chat_id == chat_id else None

    async def save_game(self, game: Game, *, bump_version: bool = True) -> None:
        if bump_version:
            self._version += 1
            game.version = self._version
            game.updated_at_ts = float(self._version)
        self.game = game

    async def delete_game(self, chat_id: int) -> None:
        if self.game is not None and self.game.chat_id == chat_id:
            self.game = None

    async def has_user_started(self, user_id: int) -> bool:
        return user_id in self._started_users

    @asynccontextmanager
    async def chat_lock(self, chat_id: int):
        yield


def _build_init_data(*, bot_token: str, user_id: int, first_name: str, auth_date: int | None = None) -> str:
    payload = {
        "auth_date": str(auth_date if auth_date is not None else int(time())),
        "query_id": "query-1",
        "user": json.dumps({"id": user_id, "first_name": first_name}, separators=(",", ":"), ensure_ascii=False),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(payload.items(), key=lambda item: item[0]))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(payload)


class MiniAppApiIntegrationTest(TestCase):
    def _build_client(self, game: Game) -> tuple[TestClient, _InMemoryRepo]:
        repo = _InMemoryRepo(game)
        settings = Settings(
            BOT_TOKEN="bot-token",
            REDIS_URL="redis://localhost:6379/0",
            MINIAPP_ENABLED=True,
            MINIAPP_SESSION_SECRET="miniapp-secret",
            MINIAPP_INIT_DATA_TTL_SECONDS=300,
            MINIAPP_SESSION_TTL_SECONDS=900,
        )
        app_context = SimpleNamespace(bot=Mock(), redis_repo=repo)
        app = build_miniapp_api(settings=settings, app_context=app_context, analytics_emitter=Mock())
        return TestClient(app), repo

    def _auth_headers(self, client: TestClient, *, user_id: int, chat_id: int, name: str) -> dict[str, str]:
        response = client.post(
            "/api/v1/miniapp/auth",
            json={
                "chat_id": chat_id,
                "init_data": _build_init_data(bot_token="bot-token", user_id=user_id, first_name=name),
            },
        )
        self.assertEqual(response.status_code, 200)
        token = response.json()["session_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_snapshot_supports_no_change_protocol(self) -> None:
        game = Game(
            chat_id=500,
            admin_id=1,
            state=GameState.LOBBY,
            mode=GameMode.IMAGE_DB,
            players=[Player(user_id=1, name="Admin"), Player(user_id=2, name="User2")],
            available_categories=["anime"],
            selected_categories=[],
            version=3,
            updated_at_ts=3.0,
        )
        client, repo = self._build_client(game)
        repo._started_users.update({1, 2})

        headers = self._auth_headers(client, user_id=2, chat_id=500, name="User2")
        first = client.get("/api/v1/miniapp/game", params={"chat_id": 500}, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()["no_change"])
        version = first.json()["version"]

        second = client.get(
            "/api/v1/miniapp/game",
            params={"chat_id": 500, "since_version": version},
            headers=headers,
        )
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["no_change"])
        self.assertIsNone(second.json()["snapshot"])

    def test_join_and_role_secrecy(self) -> None:
        game = Game(
            chat_id=600,
            admin_id=1,
            state=GameState.PLAYING,
            mode=GameMode.IMAGE_DB,
            players=[Player(user_id=1, name="Admin"), Player(user_id=2, name="User2")],
            spy_id=2,
            payload_type=PayloadType.PHOTO,
            civilian_payload="civilian-card",
            spy_payload="spy-card",
            civilian_name="Civilian",
            spy_name="Spy",
            version=10,
            updated_at_ts=10.0,
        )
        client, repo = self._build_client(game)
        repo._started_users.update({1, 2, 3})

        headers_user2 = self._auth_headers(client, user_id=2, chat_id=600, name="User2")
        snapshot = client.get("/api/v1/miniapp/game", params={"chat_id": 600}, headers=headers_user2)
        self.assertEqual(snapshot.status_code, 200)
        snapshot_payload = snapshot.json()["snapshot"]
        self.assertNotIn("payload", snapshot_payload)
        self.assertNotIn("spy_payload", snapshot_payload)

        role = client.get("/api/v1/miniapp/me/role", params={"chat_id": 600}, headers=headers_user2)
        self.assertEqual(role.status_code, 200)
        self.assertTrue(role.json()["has_role"])
        self.assertTrue(role.json()["is_spy"])
        self.assertEqual(role.json()["payload"], "spy-card")

        headers_user3 = self._auth_headers(client, user_id=3, chat_id=600, name="User3")
        no_member_role = client.get("/api/v1/miniapp/me/role", params={"chat_id": 600}, headers=headers_user3)
        self.assertEqual(no_member_role.status_code, 403)
        self.assertEqual(no_member_role.json()["error"]["code"], "member_required")

    def test_join_and_admin_permission_checks(self) -> None:
        game = Game(
            chat_id=700,
            admin_id=1,
            state=GameState.LOBBY,
            mode=GameMode.IMAGE_DB,
            players=[Player(user_id=1, name="Admin")],
            available_categories=["anime"],
            selected_categories=[],
            version=1,
            updated_at_ts=1.0,
        )
        client, repo = self._build_client(game)
        repo._started_users.update({1, 4})

        headers_user4 = self._auth_headers(client, user_id=4, chat_id=700, name="User4")
        joined = client.post("/api/v1/miniapp/join", json={"chat_id": 700}, headers=headers_user4)
        self.assertEqual(joined.status_code, 200)
        self.assertEqual(len(repo.game.players), 2)
        self.assertGreater(joined.json()["version"], 1)

        forbidden_toggle = client.post(
            "/api/v1/miniapp/categories/toggle",
            json={"chat_id": 700, "category": "anime"},
            headers=headers_user4,
        )
        self.assertEqual(forbidden_toggle.status_code, 403)
        self.assertEqual(forbidden_toggle.json()["error"]["code"], "admin_required")
