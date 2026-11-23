"""
Unit tests untuk fitur Auto-Fill Darurat 23:50 dan Pengecekan Berkala Acak (40-60 Menit) Entri '-' di DERMAGA.
"""

import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import Settings, set_settings
from app.database import logbook_repo
from app.services.logbook_service import find_placeholder_entries
from app.services.scheduler import process_emergency_autofill, process_placeholder_checks


class TestPlaceholderAndAutoFill(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_dir = Path(self.temp_dir.name)

        self.settings = Settings(
            TELEGRAM_TOKEN="123456:FAKE_TOKEN_FOR_TESTING",
            ADMIN_CHAT_ID=999888777,
            MAGANG_SECRET_KEY="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            LOGBOOK_SECRET_KEY="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            REMINDER_DB_PATH=self.db_dir / "reminders_test.db",
            BENSIN_DB_PATH=self.db_dir / "bensin_test.db",
            LOGBOOK_DB_PATH=self.db_dir / "logbook_test.db",
            MAGANG_DB_PATH=self.db_dir / "magang_test.db",
        )
        set_settings(self.settings)

        # Inisialisasi DB
        await logbook_repo.init_logbook_db()

        self.test_chat_id = 99887711
        await logbook_repo.register_user_credential(
            self.test_chat_id, "tester_nim", "SecretPass123"
        )

    async def asyncTearDown(self):
        set_settings(None)
        self.temp_dir.cleanup()

    # --- 1. TEST REPOSITORY HELPER FUNCTIONS ---
    async def test_placeholder_repo_crud(self):
        # Initial: state should be None
        state = await logbook_repo.get_placeholder_reminder_state(self.test_chat_id)
        self.assertIsNone(state)

        # Update schedule with pending dates
        next_check = "2026-11-23 10:45:00"
        await logbook_repo.update_placeholder_check_schedule(
            self.test_chat_id,
            next_check_at=next_check,
            pending_dates=["2026-11-22"],
            notified=True,
        )

        state = await logbook_repo.get_placeholder_reminder_state(self.test_chat_id)
        self.assertIsNotNone(state)
        self.assertEqual(state["next_check_at"], next_check)
        self.assertEqual(state["pending_dates"], ["2026-11-22"])
        self.assertIsNotNone(state["last_notified_at"])

        # Set snooze 2 hours
        snooze_time = "2026-11-23 12:45:00"
        await logbook_repo.set_placeholder_snooze(self.test_chat_id, snooze_time)
        state = await logbook_repo.get_placeholder_reminder_state(self.test_chat_id)
        self.assertEqual(state["snooze_until"], snooze_time)

        # Clear state
        await logbook_repo.clear_placeholder_state(self.test_chat_id)
        state = await logbook_repo.get_placeholder_reminder_state(self.test_chat_id)
        self.assertEqual(state["pending_dates"], [])
        self.assertIsNone(state["snooze_until"])

    # --- 2. TEST FIND_PLACEHOLDER_ENTRIES HELPER ---
    def test_find_placeholder_entries(self):
        entries = [
            {
                "web_id": "5001",
                "tanggal_iso": "2026-11-20",
                "pekerjaan": "Mengerjakan fitur login",
                "has_btn_edit": True,
            },
            {
                "web_id": "5002",
                "tanggal_iso": "2026-11-21",
                "pekerjaan": "-",
                "has_btn_edit": True,
            },
            {
                "web_id": "5003",
                "tanggal_iso": "2026-11-22",
                "pekerjaan": " -- ",
                "has_btn_edit": True,
            },
            {
                "web_id": "5004",
                "tanggal_iso": "2026-11-23",
                "pekerjaan": "-",
                "has_btn_edit": False,  # locked / tidak ada btn-edit
            },
        ]

        found = find_placeholder_entries(entries)
        self.assertEqual(len(found), 2)
        web_ids = [e["web_id"] for e in found]
        self.assertIn("5002", web_ids)
        self.assertIn("5003", web_ids)
        self.assertNotIn("5001", web_ids)
        self.assertNotIn("5004", web_ids)

    # --- 3. TEST EMERGENCY AUTO-FILL 23:50 ---
    async def test_emergency_autofill_active_day_success(self):
        bot = AsyncMock()
        # Mock waktu: Senin 23:50 WIB (weekday 0)
        mock_now = datetime(2026, 11, 23, 23, 50, 0)

        with patch("app.services.scheduler.get_local_now", return_value=mock_now), \
             patch("app.services.scheduler.check_monitoring_today", new_callable=AsyncMock) as mock_check, \
             patch("app.services.scheduler.submit_dermaga_entry", new_callable=AsyncMock) as mock_submit:

            mock_check.return_value = {"exists": False}
            mock_submit.return_value = (True, "Logbook berhasil disimpan.")

            await process_emergency_autofill(bot)

            # Verifikasi submit dipanggil dengan summary '-'
            mock_submit.assert_awaited_once()
            args, kwargs = mock_submit.call_args
            self.assertEqual(kwargs.get("chat_id"), self.test_chat_id)
            self.assertEqual(kwargs.get("date"), "2026-11-23")
            self.assertEqual(kwargs.get("summary"), "-")
            self.assertEqual(kwargs.get("jam_masuk"), "07:10")
            self.assertEqual(kwargs.get("jam_pulang"), "16:25")

            # Verifikasi pesan alert darurat dikirim ke bot
            bot.send_message.assert_awaited_once()
            send_args, send_kwargs = bot.send_message.call_args
            self.assertIn("Logbook Darurat Terisi Otomatis", send_kwargs.get("text", ""))

    async def test_emergency_autofill_skips_off_day(self):
        bot = AsyncMock()
        # Mock waktu: Minggu 23:50 WIB (weekday 6) sedangkan reminder_days user adalah Senin-Jumat (0,1,2,3,4)
        mock_now = datetime(2026, 11, 29, 23, 50, 0)
        self.assertEqual(mock_now.weekday(), 6)

        with patch("app.services.scheduler.get_local_now", return_value=mock_now), \
             patch("app.services.scheduler.submit_dermaga_entry", new_callable=AsyncMock) as mock_submit:

            await process_emergency_autofill(bot)
            mock_submit.assert_not_awaited()
            bot.send_message.assert_not_awaited()

    async def test_emergency_autofill_skips_if_already_filled(self):
        bot = AsyncMock()
        mock_now = datetime(2026, 11, 23, 23, 50, 0)

        with patch("app.services.scheduler.get_local_now", return_value=mock_now), \
             patch("app.services.scheduler.check_monitoring_today", new_callable=AsyncMock) as mock_check, \
             patch("app.services.scheduler.submit_dermaga_entry", new_callable=AsyncMock) as mock_submit:

            mock_check.return_value = {"exists": True, "entry": {"web_id": "999"}}

            await process_emergency_autofill(bot)
            mock_submit.assert_not_awaited()
            bot.send_message.assert_not_awaited()

    # --- 4. TEST PERIODIC PLACEHOLDER CHECKS (40-60 MENIT) ---
    async def test_placeholder_check_skips_outside_hours(self):
        bot = AsyncMock()
        # Mock waktu: 02:00 WIB (di luar 07:00 - 22:00 WIB)
        mock_now = datetime(2026, 11, 23, 2, 30, 0)

        with patch("app.services.scheduler.get_local_now", return_value=mock_now), \
             patch("app.services.scheduler.fetch_dermaga_table", new_callable=AsyncMock) as mock_fetch:

            await process_placeholder_checks(bot)
            mock_fetch.assert_not_awaited()

    async def test_placeholder_check_detects_dash_and_notifies(self):
        bot = AsyncMock()
        # Mock waktu: 10:00 WIB
        mock_now = datetime(2026, 11, 23, 10, 0, 0)

        mock_entries = [
            {
                "web_id": "7788",
                "tanggal_iso": "2026-11-22",
                "pekerjaan": "-",
                "has_btn_edit": True,
            }
        ]

        with patch("app.services.scheduler.get_local_now", return_value=mock_now), \
             patch("app.services.scheduler.fetch_dermaga_table", new_callable=AsyncMock) as mock_fetch:

            mock_fetch.return_value = mock_entries

            await process_placeholder_checks(bot)

            # Notifikasi harus terkirim
            bot.send_message.assert_awaited_once()
            call_kwargs = bot.send_message.call_args[1]
            self.assertIn("Deskripsi '-' Terdeteksi", call_kwargs["text"])
            self.assertIn("2026-11-22", call_kwargs["text"])

            # Cek bahwa state DB tersimpan dengan next_check_at (antara 40 s/d 60 menit)
            state = await logbook_repo.get_placeholder_reminder_state(self.test_chat_id)
            self.assertIsNotNone(state)
            self.assertIsNotNone(state["next_check_at"])
            self.assertEqual(state["pending_dates"], ["2026-11-22"])

    async def test_placeholder_check_respects_snooze(self):
        bot = AsyncMock()
        mock_now = datetime(2026, 11, 23, 10, 0, 0)

        # Set snooze sampai jam 11:30
        snooze_until = "2026-11-23 11:30:00"
        await logbook_repo.set_placeholder_snooze(self.test_chat_id, snooze_until)

        with patch("app.services.scheduler.get_local_now", return_value=mock_now), \
             patch("app.services.scheduler.fetch_dermaga_table", new_callable=AsyncMock) as mock_fetch:

            await process_placeholder_checks(bot)
            # Karena masih dalam snooze, tidak boleh fetch atau kirim notif
            mock_fetch.assert_not_awaited()
            bot.send_message.assert_not_awaited()

    # --- 5. TEST CALLBACK DIRECT EDIT & SNOOZE ---
    async def test_snooze_callback(self):
        from app.bot.handlers.logbook_modules.calendar_nav import cb_snooze_placeholder

        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.from_user.id = self.test_chat_id
        callback.message = AsyncMock()

        await cb_snooze_placeholder(callback)

        state = await logbook_repo.get_placeholder_reminder_state(self.test_chat_id)
        self.assertIsNotNone(state)
        self.assertIsNotNone(state["snooze_until"])
        callback.message.edit_text.assert_awaited_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("Pengingat Ditunda", text)
        self.assertIn("2 jam", text)

    async def test_direct_edit_callback(self):
        from app.bot.handlers.logbook_modules.calendar_nav import (
            _calendar_edit_sessions,
            cb_calendar_direct_edit,
        )

        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.from_user.id = self.test_chat_id
        callback.data = "log_eddirect_5055"
        callback.message = AsyncMock()

        mock_entries = [
            {
                "web_id": "5055",
                "tanggal_iso": "2026-11-22",
                "tanggal_text": "22 Nov 2026",
                "jam_masuk": "07:10",
                "jam_pulang": "16:25",
                "pekerjaan": "-",
                "keterangan": "hadir",
                "has_btn_edit": True,
            }
        ]

        with patch("app.bot.handlers.logbook_modules.calendar_nav.fetch_dermaga_table", new_callable=AsyncMock) as mock_fetch, \
             patch("app.bot.handlers.logbook_modules.calendar_nav._send_edit_detail_view", new_callable=AsyncMock) as mock_send_detail:

            mock_fetch.return_value = mock_entries

            await cb_calendar_direct_edit(callback)

            mock_send_detail.assert_awaited_once_with(self.test_chat_id, callback.message)
            session = _calendar_edit_sessions.get(self.test_chat_id)
            self.assertIsNotNone(session)
            self.assertEqual(session["web_id"], "5055")
            self.assertEqual(session["tanggal"], "2026-11-22")
            self.assertEqual(session["deskripsi"], "-")


if __name__ == "__main__":
    unittest.main()
