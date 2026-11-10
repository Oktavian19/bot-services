"""
Unit tests untuk memvalidasi arsitektur baru asinkron (repositories, services, dan config).
"""

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock
from app.core.config import Settings, set_settings
from app.database import fuel_repo, logbook_repo, reminder_repo
from app.services.crypto import decrypt_text, encrypt_text
from app.services.fuel_service import render_fuel_hub_text
from app.services.logbook_service import format_draft_message, parse_coordinates_input
from app.services.reminder_service import format_reminders_list_text


class TestAsyncCore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_dir = Path(self.temp_dir.name)

        # Mock settings dengan isolated databases
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

    async def asyncTearDown(self):
        set_settings(None)
        self.temp_dir.cleanup()

    # --- TEST CRYPTO ---
    def test_crypto_fernet(self):
        secret = "Rahasia123!"
        cipher = encrypt_text(secret, self.settings.LOGBOOK_SECRET_KEY)
        self.assertNotEqual(secret, cipher)
        decrypted = decrypt_text(cipher, self.settings.LOGBOOK_SECRET_KEY)
        self.assertEqual(secret, decrypted)

    # --- TEST REMINDER REPO ---
    async def test_reminder_crud(self):
        await reminder_repo.init_reminder_db()
        chat_id = 1001

        # Insert
        r_id = await reminder_repo.insert_reminder(chat_id, "Ujian Magang", "2026-12-01", "08:00", 3)
        self.assertGreater(r_id, 0)

        # Get active
        active = await reminder_repo.get_active_reminders_by_chat(chat_id)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["message"], "Ujian Magang")

        # Due reminders
        due = await reminder_repo.get_due_reminders("08:00")
        self.assertEqual(len(due), 1)

        # Mark completed
        await reminder_repo.mark_reminder_completed(r_id)
        active_after = await reminder_repo.get_active_reminders_by_chat(chat_id)
        self.assertEqual(len(active_after), 0)

        # Delete
        deleted = await reminder_repo.delete_reminder(r_id)
        self.assertTrue(deleted)

    # --- TEST FUEL REPO ---
    async def test_fuel_crud_and_recalc(self):
        await fuel_repo.init_fuel_db()
        chat_id = 2002

        # Register motor
        await fuel_repo.register_motor(chat_id, "Honda Beat", 10000.0, 10000.0)
        motor = await fuel_repo.get_motor(chat_id)
        self.assertIsNotNone(motor)
        self.assertEqual(motor["nama_motor"], "Honda Beat")

        # Refill 1 (tanpa odo)
        res1 = await fuel_repo.add_log_bensin(chat_id, None, 20000, 2.0)
        self.assertTrue(res1["tanpa_odo"])

        # Refill 2 (dengan odo 10100 -> jarak 100km, total liter 2 + 2 = 4L -> 25 km/L)
        res2 = await fuel_repo.add_log_bensin(chat_id, 10100.0, 20000, 2.0)
        self.assertFalse(res2["tanpa_odo"])
        self.assertEqual(res2["jarak"], 100.0)
        self.assertEqual(res2["kml"], 25.0)

        # Stats
        stats = await fuel_repo.get_statistik_bensin(chat_id)
        self.assertEqual(stats["rata_rata"], 25.0)

        # Oil status
        status_oli = await fuel_repo.get_status_oli(chat_id)
        self.assertEqual(status_oli["status"], "aman")
        self.assertEqual(status_oli["sisa_km"], 2900.0)

        # History list
        logs = await fuel_repo.get_logs_bensin(chat_id)
        self.assertEqual(len(logs), 2)

    # --- TEST LOGBOOK REPO ---
    async def test_logbook_crud(self):
        await logbook_repo.init_logbook_db()
        chat_id = 3003

        # Register user
        token = await logbook_repo.register_user_credential(chat_id, "2341720000", "myPass123")
        self.assertIsNotNone(token)

        # Verify get by token
        user = await logbook_repo.get_user_by_token(token)
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "2341720000")

        # Location profiles
        profiles = await logbook_repo.get_user_location_profiles(chat_id)
        self.assertGreaterEqual(len(profiles), 1)

        # Save profile home
        await logbook_repo.save_location_profile(chat_id, "home", "-7.9000", "112.6000", "10")
        lat, lng, acc = await logbook_repo.get_user_location(chat_id, "home")
        self.assertEqual(lat, "-7.9000")
        self.assertEqual(lng, "112.6000")

        # Drafts
        draft, is_new = await logbook_repo.create_or_get_draft(
            chat_id=chat_id,
            idempotency_key="idemp_1",
            date="2026-11-10",
            projects=["Test Proj"],
            commits_summary="Selesai refactor",
        )
        self.assertTrue(is_new)
        self.assertEqual(draft["summary"], "Selesai refactor")

        # Idempotency
        draft_dup, is_new_dup = await logbook_repo.create_or_get_draft(
            chat_id=chat_id,
            idempotency_key="idemp_1",
            date="2026-11-10",
            projects=["Test Proj"],
            commits_summary="Duplicate call",
        )
        self.assertFalse(is_new_dup)
        self.assertEqual(draft_dup["id"], draft["id"])

    # --- TEST SERVICE HELPERS ---
    def test_services_helpers(self):
        # Geo parser
        coords = parse_coordinates_input("-7.9467, 112.6156")
        self.assertIsNotNone(coords)
        self.assertAlmostEqual(coords[0], -7.9467, places=4)
        self.assertAlmostEqual(coords[1], 112.6156, places=4)

        # URL parser
        url_coords = parse_coordinates_input("https://maps.google.com/?q=-7.946711,112.615622")
        self.assertIsNotNone(url_coords)
        self.assertAlmostEqual(url_coords[0], -7.946711, places=4)

        # Reminder text formatter
        rem_text = format_reminders_list_text([
            {"message": "Sidang", "target_date": "2026-11-15", "notify_time": "09:00", "prep_days": 2}
        ])
        self.assertIn("Sidang", rem_text)
        self.assertIn("15-11-2026", rem_text)

    async def test_setup_bot_commands(self):
        from main import setup_bot_commands
        mock_bot = AsyncMock()
        await setup_bot_commands(mock_bot)
        self.assertEqual(mock_bot.set_my_commands.await_count, 2)
        # Check call 1: user default scope (17 commands)
        user_call = mock_bot.set_my_commands.await_args_list[0]
        user_cmds = user_call[0][0]
        self.assertEqual(len(user_cmds), 17)
        # Check call 2: admin chat scope (19 commands)
        admin_call = mock_bot.set_my_commands.await_args_list[1]
        admin_cmds = admin_call[0][0]
        self.assertEqual(len(admin_cmds), 19)

    def test_apply_gps_jitter_and_feedback(self):
        from app.services.logbook_service import apply_gps_jitter, extract_feedback_message
        j_lat, j_lng, j_acc, drift = apply_gps_jitter("-7.9467", "112.6156")
        self.assertNotEqual(j_lat, "-7.9467")
        self.assertTrue(2.0 <= drift <= 5.0)
        self.assertTrue(8 <= int(j_acc) <= 15)

        # Test feedback extractor
        html_success = "<script>notify('success', 'Data logbook tersimpan');</script>"
        ok, msg = extract_feedback_message(html_success)
        self.assertTrue(ok)
        self.assertIn("tersimpan", msg)

        html_err = "<div class='alert alert-danger'>Peringatan: jam masuk tidak valid</div>"
        ok_err, msg_err = extract_feedback_message(html_err)
        self.assertFalse(ok_err)
        self.assertIn("tidak valid", msg_err)

    async def test_parse_weekly_cards_and_weekly_reminders(self):
        from app.services.logbook_service import parse_weekly_cards_from_html
        from app.database.logbook_repo import (
            init_logbook_db,
            get_weekly_reminder_state,
            set_weekly_reminder_status,
            stop_weekly_reminder,
        )

        sample_html = """
        <div class="card minggu-card" data-awal="2026-11-02">
            <div class="minggu-label">November-1</div>
            <div class="text-muted">2 - 8 November 2026</div>
            <div>5 hari terisi</div>
            <span class="badge text-bg-warning">Menunggu verifikasi</span>
        </div>
        <div class="card minggu-card minggu-berjalan" data-awal="2026-11-09">
            <div class="minggu-label">November-2</div>
            <span class="badge text-bg-warning">Minggu ini</span>
            <div class="text-muted">9 - 15 November 2026</div>
            <div>1 hari terisi</div>
            <span class="badge text-bg-secondary">Belum diajukan</span>
        </div>
        """
        cards = parse_weekly_cards_from_html(sample_html)
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["label"], "November-1")
        self.assertEqual(cards[0]["status"], "Menunggu verifikasi")
        self.assertEqual(cards[1]["label"], "November-2")
        self.assertEqual(cards[1]["status"], "Belum diajukan")
        self.assertEqual(cards[1]["hari_terisi"], 1)

        # Test weekly repo state
        await init_logbook_db()
        test_chat_id = 991122
        from app.database.logbook_repo import register_user_credential
        await register_user_credential(test_chat_id, "user99", "pass123")
        await set_weekly_reminder_status(test_chat_id, "2026-11-09", status="reminded", week_label="November-2")
        state = await get_weekly_reminder_state(test_chat_id, "2026-11-09")
        self.assertIsNotNone(state)
        self.assertEqual(state["status"], "reminded")
        self.assertEqual(state["week_label"], "November-2")

        await stop_weekly_reminder(test_chat_id, "2026-11-09")
        state_stopped = await get_weekly_reminder_state(test_chat_id, "2026-11-09")
        self.assertEqual(state_stopped["status"], "stopped")

    def test_parse_weeks_and_parties_and_link_verif(self):
        from app.services.logbook_service import parse_weeks_and_parties_from_html
        from app.bot.handlers.logbook import render_verification_weeks_text, render_verification_detail_text
        from app.bot.keyboards.logbook import get_verification_weeks_keyboard, get_verification_detail_keyboard

        sample_html = """
        <script>
        const WEEKS = {
            "2026-10-26": {
                "awal": "2026-10-26",
                "label": "Oktober-4",
                "rentang": "26 Oktober - 1 November 2026",
                "mendatang": false,
                "logbook": [],
                "verif": {
                    "mahasiswa": "3 November 2026, 07:45 WIB",
                    "supervisor": "4 November 2026, 09:32 WIB",
                    "dosen": "3 November 2026, 09:14 WIB",
                    "link_supervisor": null,
                    "link_dosen": null,
                    "pdf": "https://jti.polinema.ac.id/dermaga/mahasiswa/monitoring/pdf/7046"
                }
            },
            "2026-11-02": {
                "awal": "2026-11-02",
                "label": "November-1",
                "rentang": "2 - 8 November 2026",
                "mendatang": false,
                "logbook": [],
                "verif": {
                    "mahasiswa": "10 November 2026, 09:55 WIB",
                    "supervisor": null,
                    "dosen": null,
                    "link_supervisor": "https://jti.polinema.ac.id/dermaga/verifikasi/logbook/sup12345",
                    "link_dosen": "https://jti.polinema.ac.id/dermaga/verifikasi/logbook/dos67890",
                    "pdf": null
                }
            }
        };
        const NAMA_PIHAK = {
            supervisor: "Pembimbing Lapangan (Tahta Alfina)",
            dosen: "Dosen Pembimbing (Sofyan Noor Arief, S.ST., M.Kom.)"
        };
        </script>
        """

        weeks, parties = parse_weeks_and_parties_from_html(sample_html)
        self.assertEqual(len(weeks), 2)
        self.assertEqual(parties["supervisor"], "Pembimbing Lapangan (Tahta Alfina)")
        self.assertEqual(parties["dosen"], "Dosen Pembimbing (Sofyan Noor Arief, S.ST., M.Kom.)")

        nov1 = weeks["2026-11-02"]
        self.assertEqual(nov1["verif"]["link_supervisor"], "https://jti.polinema.ac.id/dermaga/verifikasi/logbook/sup12345")
        self.assertEqual(nov1["verif"]["link_dosen"], "https://jti.polinema.ac.id/dermaga/verifikasi/logbook/dos67890")

        # Test render list
        list_text = render_verification_weeks_text(weeks)
        self.assertIn("November-1", list_text)
        self.assertIn("1 Minggu Menunggu Verifikasi", list_text)

        # Test render detail
        detail_text = render_verification_detail_text(nov1, parties)
        self.assertIn("Tahta Alfina", detail_text)
        self.assertIn("sup12345", detail_text)
        self.assertIn("dos67890", detail_text)

        # Test keyboards
        kb_weeks = get_verification_weeks_keyboard(weeks)
        self.assertTrue(any("log_verif_2026-11-02" in btn.callback_data for row in kb_weeks.inline_keyboard for btn in row if btn.callback_data))

        kb_detail = get_verification_detail_keyboard(nov1, parties)
        urls = [btn.url for row in kb_detail.inline_keyboard for btn in row if btn.url]
        self.assertIn("https://jti.polinema.ac.id/dermaga/verifikasi/logbook/sup12345", urls)
        self.assertIn("https://jti.polinema.ac.id/dermaga/verifikasi/logbook/dos67890", urls)


if __name__ == "__main__":
    unittest.main()
