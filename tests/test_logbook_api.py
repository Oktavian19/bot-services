"""
Test untuk HTTP API Receiver Logbook (/api/health dan /api/logbook).
"""

from pathlib import Path
import tempfile
import unittest
from aiohttp.test_utils import AioHTTPTestCase
from app.core.config import Settings, set_settings
from app.database import logbook_repo
from app.services.logbook_api import create_api_app


class TestLogbookApi(AioHTTPTestCase):
    async def get_application(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_dir = Path(self.temp_dir.name)

        self.settings = Settings(
            TELEGRAM_TOKEN="123456:FAKE_TOKEN",
            ADMIN_CHAT_ID=999888777,
            MAGANG_SECRET_KEY="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            LOGBOOK_SECRET_KEY="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            LOGBOOK_DB_PATH=self.db_dir / "logbook_api_test.db",
            LOGBOOK_API_TOKEN="master_token_test",
        )
        set_settings(self.settings)

        # Inisialisasi DB
        await logbook_repo.init_logbook_db()

        # Mock Bot
        class DummyBot:
            async def send_message(self, *args, **kwargs):
                class DummyMsg:
                    message_id = 12345
                return DummyMsg()

        return create_api_app(DummyBot())

    def tearDown(self):
        super().tearDown()
        set_settings(None)
        self.temp_dir.cleanup()

    async def test_health_endpoint(self):
        resp = await self.client.get("/api/health")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertTrue(data["multi_user"])

    async def test_submit_draft_unauthorized(self):
        resp = await self.client.post("/api/logbook", json={"dummy": "data"})
        self.assertEqual(resp.status, 401)

    async def test_submit_draft_authorized(self):
        # Register user in DB first
        chat_id = 778899
        token = await logbook_repo.register_user_credential(chat_id, "testcli", "passcli")

        payload = {
            "date": "2026-11-10",
            "projects": ["CLI Test"],
            "summary": "Fitur logbook API telah ditest secara menyeluruh",
            "idempotency_key": "cli_test_idemp_1",
            "jam_masuk": "08:00",
            "jam_pulang": "17:00",
        }

        headers = {"Authorization": f"Bearer {token}"}
        resp = await self.client.post("/api/logbook", json=payload, headers=headers)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["is_new"])
        self.assertGreater(data["draft_id"], 0)


if __name__ == "__main__":
    unittest.main()

