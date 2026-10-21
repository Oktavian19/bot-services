import unittest
import os
import sys
import tempfile
import shutil
import json
import subprocess
from datetime import datetime
from unittest.mock import MagicMock, patch

# Tambahkan path root agar modul dapat diimpor
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from modul.logbook import database, website, server
from tools.logbook_cli import logbook_cli

class TestGitLogbookAutomation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Setup temporary SQLite database untuk testing
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_file = os.path.join(cls.temp_dir, "test_logbook.db")
        database.DB_FILE = cls.db_file
        database.setup_database()
        cls.test_chat_id = 999001
        database.register_user_credential(cls.test_chat_id, "tester_nim", "TestPass123", api_token="TEST_TOKEN_API")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        # Setup git temp repo fixture
        self.git_repo1 = tempfile.mkdtemp()
        self.git_repo2 = tempfile.mkdtemp()
        
        # Inisialisasi repo 1
        subprocess.run(["git", "init"], cwd=self.git_repo1, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.git_repo1, check=True)
        subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=self.git_repo1, check=True)

        # Inisialisasi repo 2
        subprocess.run(["git", "init"], cwd=self.git_repo2, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=self.git_repo2, check=True)
        subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=self.git_repo2, check=True)

    def tearDown(self):
        shutil.rmtree(self.git_repo1, ignore_errors=True)
        shutil.rmtree(self.git_repo2, ignore_errors=True)

    def test_1_git_parsing_and_date_filtering(self):
        """1. Parsing output Git dan filter tanggal dengan fixture/temp repo."""
        test_file = os.path.join(self.git_repo1, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello world\n")
        subprocess.run(["git", "add", "."], cwd=self.git_repo1, check=True)
        subprocess.run(["git", "commit", "-m", "feat: initial commit"], cwd=self.git_repo1, check=True)

        today_str = datetime.now().strftime("%Y-%m-%d")
        commits = logbook_cli.get_commits_for_date("repo1", self.git_repo1, today_str)
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0]["project"], "repo1")
        self.assertEqual(commits[0]["subject"], "feat: initial commit")
        self.assertTrue(len(commits[0]["hash"]) >= 7)

        # Tanggal yang berbeda tidak mengembalikan commit
        old_commits = logbook_cli.get_commits_for_date("repo1", self.git_repo1, "2020-01-01")
        self.assertEqual(len(old_commits), 0)

    def test_2_multi_repo_daily_payload(self):
        """2. Beberapa repository/proyek membentuk satu payload harian."""
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Commit di repo 1
        with open(os.path.join(self.git_repo1, "file1.txt"), "w") as f:
            f.write("repo1")
        subprocess.run(["git", "add", "."], cwd=self.git_repo1, check=True)
        subprocess.run(["git", "commit", "-m", "feat: repo 1 task"], cwd=self.git_repo1, check=True)

        # Commit di repo 2
        with open(os.path.join(self.git_repo2, "file2.txt"), "w") as f:
            f.write("repo2")
        subprocess.run(["git", "add", "."], cwd=self.git_repo2, check=True)
        subprocess.run(["git", "commit", "-m", "fix: repo 2 bug"], cwd=self.git_repo2, check=True)

        repos = {"proj1": self.git_repo1, "proj2": self.git_repo2}
        all_commits = logbook_cli.collect_all_commits(repos, today_str)
        self.assertEqual(len(all_commits), 2)
        projects = {c["project"] for c in all_commits}
        self.assertEqual(projects, {"proj1", "proj2"})

    def test_3_no_commit_no_request(self):
        """3. Tanggal tanpa commit tidak membuat request."""
        repos = {"proj1": self.git_repo1}
        old_date = "2020-05-15"
        commits = logbook_cli.collect_all_commits(repos, old_date)
        self.assertEqual(len(commits), 0)

        # Mock urllib request untuk memastikan tidak terpanggil saat commits kosong
        with patch("urllib.request.urlopen") as mock_urlopen:
            args = MagicMock()
            args.date = old_date
            args.no_ai = True
            config = {"repositories": repos}
            logbook_cli.cmd_run(args, config)
            mock_urlopen.assert_not_called()

    def test_4_secrets_and_local_paths_not_in_payload(self):
        """4. Secret dan path lokal tidak muncul dalam payload/log."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        with open(os.path.join(self.git_repo1, "code.py"), "w") as f:
            f.write("pass")
        subprocess.run(["git", "add", "."], cwd=self.git_repo1, check=True)
        subprocess.run(["git", "commit", "-m", "clean: refactor parser"], cwd=self.git_repo1, check=True)

        repos = {"my-project": self.git_repo1}
        commits = logbook_cli.collect_all_commits(repos, today_str)
        config = {
            "vps_endpoint": "http://127.0.0.1:8088/api/logbook",
            "api_token": "SUPER_SECRET_TOKEN_XYZ",
            "openai_api_key": "sk-SECRET-OPENAI-KEY",
            "repositories": repos
        }
        summary = logbook_cli.generate_summary(commits, config, force_no_ai=True)
        idemp = logbook_cli.compute_idempotency_key(today_str, commits)
        payload = {
            "date": today_str,
            "projects": ["my-project"],
            "summary": summary,
            "idempotency_key": idemp,
            "commits": commits
        }

        payload_str = json.dumps(payload)
        # Pastikan path lokal komputer tidak bocor ke payload
        self.assertNotIn(self.git_repo1, payload_str)
        # Pastikan token/secret tidak bocor di dalam payload JSON
        self.assertNotIn("SUPER_SECRET_TOKEN_XYZ", payload_str)
        self.assertNotIn("sk-SECRET-OPENAI-KEY", payload_str)

    def test_5_idempotency_prevents_duplicate_drafts(self):
        """5. Request duplikat tidak menghasilkan approval/submission ganda."""
        idemp_key = "idemp_test_key_12345"
        d1, is_new1 = database.create_or_get_draft(
            idempotency_key=idemp_key,
            date="2026-10-20",
            projects=["bot-services"],
            commits_summary="Ringkasan test 1",
            raw_metadata=[]
        )
        self.assertTrue(is_new1)
        self.assertEqual(d1["status"], "pending")

        # Request kedua dengan idempotency_key yang sama
        d2, is_new2 = database.create_or_get_draft(
            idempotency_key=idemp_key,
            date="2026-10-20",
            projects=["bot-services"],
            commits_summary="Ringkasan test 2 (duplikat)",
            raw_metadata=[]
        )
        self.assertFalse(is_new2)
        self.assertEqual(d1["id"], d2["id"])

    def test_6_edit_requires_reapproval_and_cancel_does_not_submit(self):
        """6. Edit memerlukan persetujuan ulang; batal tidak submit."""
        d, _ = database.create_or_get_draft(
            idempotency_key="idemp_flow_test",
            date="2026-10-20",
            projects=["project-x"],
            commits_summary="Ringkasan awal",
            raw_metadata=[]
        )
        draft_id = d["id"]

        # Edit draft
        database.update_draft_summary(draft_id, "Ringkasan hasil revisi")
        edited = database.get_draft(draft_id)
        # Status harus kembali 'pending', BUKAN langsung submitted atau approved
        self.assertEqual(edited["commits_summary"], "Ringkasan hasil revisi")
        self.assertEqual(edited["status"], "pending")

        # Batalkan draft
        database.update_draft_status(draft_id, "cancelled")
        cancelled = database.get_draft(draft_id)
        self.assertEqual(cancelled["status"], "cancelled")

    def test_7_connection_failure_saves_to_pending_queue(self):
        """7. Koneksi gagal menyimpan payload pending untuk retry."""
        cli_queue_path = os.path.join(self.temp_dir, "test_queue.db")
        logbook_cli.QUEUE_DB_PATH = cli_queue_path

        payload = {
            "date": "2026-10-20",
            "projects": ["test-proj"],
            "summary": "Offline draft test",
            "idempotency_key": "offline_key_999",
            "commits": []
        }

        # Simpan ke pending
        logbook_cli.save_pending_payload("offline_key_999", payload, "Simulated Connection Refused")
        pending_list = logbook_cli.get_pending_payloads()
        self.assertEqual(len(pending_list), 1)
        self.assertEqual(pending_list[0][0], "offline_key_999")

        # Bersihkan setelah berhasil
        logbook_cli.remove_pending_payload("offline_key_999")
        self.assertEqual(len(logbook_cli.get_pending_payloads()), 0)

    def test_8_website_exists_check_prevents_accidental_double_submission(self):
        """8. Timeout/keberadaan website tidak menimbulkan retry berisiko duplikasi."""
        # Mock get_authenticated_session dan check_monitoring_page
        with patch("modul.logbook.website.get_authenticated_session") as mock_session, \
             patch("modul.logbook.website.check_monitoring_page") as mock_check:
            
            mock_check.return_value = {
                "exists": True,
                "existing_entry": {
                    "web_id": "777",
                    "tanggal": "2026-10-20",
                    "deskripsi": "Sudah terisi sebelumnya"
                },
                "csrf_token": "token_abc"
            }

            draft = {
                "date": "2026-10-20",
                "commits_summary": "Draf baru hari ini",
                "jam_masuk": "07:10",
                "jam_pulang": "16:25"
            }

            # Submit tanpa override_id -> Harus mengembalikan status EXISTS, tidak submit langsung
            res = website.submit_logbook_to_dermaga(draft, override_id=None)
            self.assertEqual(res["status"], "EXISTS")
            self.assertEqual(res["web_id"], "777")

            # Jika admin mengonfirmasi override_id -> Baru dieksekusi submit
            mock_post = MagicMock()
            mock_post.status_code = 200
            mock_post.text = "<script>notify('success', 'Logbook berhasil disimpan');</script>"
            mock_session.return_value.post.return_value = mock_post
            res_override = website.submit_logbook_to_dermaga(draft, override_id="777")
            self.assertEqual(res_override["status"], "SUCCESS")

    def test_9_admin_auth_verification(self):
        """9. Verifikasi admin mengizinkan pesan bot dengan chat.id admin & membersihkan quote."""
        from modul.logbook import main as logbook_main

        with patch.dict(os.environ, {"ADMIN_CHAT_ID": "'1186041989'"}):
            self.assertEqual(logbook_main.get_admin_chat_id(), "1186041989")
            self.assertTrue(logbook_main.is_admin("1186041989"))
            self.assertTrue(logbook_main.is_admin(1186041989))
            self.assertFalse(logbook_main.is_admin(99999999))

            # Simulasi pesan dari tombol menu callback (di mana from_user adalah bot, tapi chat.id adalah admin)
            mock_menu_msg = MagicMock()
            mock_menu_msg.chat.id = 1186041989
            mock_menu_msg.from_user.id = 8794413205  # Bot ID
            self.assertTrue(logbook_main.check_message_admin(mock_menu_msg))

            # Simulasi pesan dari non-admin
            mock_non_admin = MagicMock()
            mock_non_admin.chat.id = 22222222
            mock_non_admin.from_user.id = 22222222
            self.assertFalse(logbook_main.check_message_admin(mock_non_admin))

    def test_10_recursive_git_discovery(self):
        """10. Auto-discovery git repositori bertingkat dan penamaan proyek."""
        parent_dir = tempfile.mkdtemp()
        try:
            # 1. Nested repo di bawah folder proyek induk
            nested_repo = os.path.join(parent_dir, "PROJECT-A", "nested_core")
            os.makedirs(nested_repo, exist_ok=True)
            subprocess.run(["git", "init"], cwd=nested_repo, check=True, stdout=subprocess.DEVNULL)

            # 2. Direct repo di bawah parent
            direct_repo = os.path.join(parent_dir, "project-b")
            os.makedirs(direct_repo, exist_ok=True)
            subprocess.run(["git", "init"], cwd=direct_repo, check=True, stdout=subprocess.DEVNULL)

            # 3. Ignored directory
            ignored_repo = os.path.join(parent_dir, "node_modules", "some-pkg")
            os.makedirs(ignored_repo, exist_ok=True)
            subprocess.run(["git", "init"], cwd=ignored_repo, check=True, stdout=subprocess.DEVNULL)

            from pathlib import Path
            discovered = logbook_cli.discover_git_repos(Path(parent_dir))

            # Verifikasi penamaan proyek
            self.assertIn("PROJECT-A", discovered)
            self.assertEqual(discovered["PROJECT-A"], os.path.abspath(nested_repo))

            self.assertIn("project-b", discovered)
            self.assertEqual(discovered["project-b"], os.path.abspath(direct_repo))

            # Verifikasi node_modules diabaikan
            self.assertNotIn("node_modules", discovered)
            self.assertNotIn("some-pkg", discovered)

            # Verifikasi resolve_all_repositories
            resolved = logbook_cli.resolve_all_repositories({"sai_group": parent_dir})
            self.assertIn("PROJECT-A", resolved)
            self.assertIn("project-b", resolved)

        finally:
            shutil.rmtree(parent_dir, ignore_errors=True)

    def test_11_multiuser_registration_and_token_flow(self):
        """11. Pendaftaran kredensial multi-user, enkripsi Fernet, dan token API."""
        chat_user1 = 10001
        chat_user2 = 10002

        # User 1 daftar
        token1 = database.register_user_credential(chat_user1, "nim_user1", "Password123")
        self.assertTrue(len(token1) >= 32)

        # User 2 daftar
        token2 = database.register_user_credential(chat_user2, "nim_user2", "Password456")
        self.assertTrue(len(token2) >= 32)
        self.assertNotEqual(token1, token2)

        # Lookup by token
        u1 = database.get_user_by_token(token1)
        self.assertIsNotNone(u1)
        self.assertEqual(u1["chat_id"], chat_user1)
        self.assertEqual(u1["username"], "nim_user1")

        u2 = database.get_user_by_token(token2)
        self.assertIsNotNone(u2)
        self.assertEqual(u2["chat_id"], chat_user2)
        self.assertEqual(u2["username"], "nim_user2")

        # Decrypt credentials
        user_cred1 = database.get_user_credential(chat_user1)
        self.assertEqual(user_cred1, ("nim_user1", "Password123"))

        # Regenerate token
        new_token1 = database.regenerate_api_token(chat_user1)
        self.assertNotEqual(token1, new_token1)
        self.assertIsNone(database.get_user_by_token(token1))
        self.assertIsNotNone(database.get_user_by_token(new_token1))

        # Delete user
        database.delete_user_credential(chat_user2)
        self.assertIsNone(database.get_user_by_chat_id(chat_user2))
        self.assertIsNone(database.get_user_by_token(token2))

    def test_12_multiuser_draft_isolation(self):
        """12. Draf terisolasi per user sesuai chat_id."""
        chat_user1 = 20001
        chat_user2 = 20002
        database.register_user_credential(chat_user1, "u1", "p1")
        database.register_user_credential(chat_user2, "u2", "p2")

        d1, _ = database.create_or_get_draft(
            chat_id=chat_user1,
            idempotency_key="u1_key",
            date="2026-10-21",
            projects=["proj-u1"],
            commits_summary="Summary u1",
            raw_metadata=[]
        )
        d2, _ = database.create_or_get_draft(
            chat_id=chat_user2,
            idempotency_key="u2_key",
            date="2026-10-21",
            projects=["proj-u2"],
            commits_summary="Summary u2",
            raw_metadata=[]
        )

        user1_drafts = database.get_recent_drafts(chat_id=chat_user1)
        user2_drafts = database.get_recent_drafts(chat_id=chat_user2)

        user1_ids = [d["id"] for d in user1_drafts]
        user2_ids = [d["id"] for d in user2_drafts]

        self.assertIn(d1["id"], user1_ids)
        self.assertNotIn(d2["id"], user1_ids)

        self.assertIn(d2["id"], user2_ids)
        self.assertNotIn(d1["id"], user2_ids)

    def test_13_server_multiuser_bearer_token_auth(self):
        """13. Server HTTP API memvalidasi Bearer Token per-user dengan benar."""
        from io import BytesIO

        # Daftarkan user untuk tes HTTP API
        test_chat_id = 77701
        token = database.register_user_credential(test_chat_id, "test_api_user", "pass123")

        # 1. Request tanpa token -> 401
        handler = server.LogbookRequestHandler.__new__(server.LogbookRequestHandler)
        handler.headers = {}
        handler.path = "/api/logbook"
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = BytesIO()
        handler.do_POST()
        handler.send_response.assert_called_with(401)

        # 2. Request dengan token salah -> 401
        handler = server.LogbookRequestHandler.__new__(server.LogbookRequestHandler)
        handler.headers = {"Authorization": "Bearer TOKEN_SALAH_12345"}
        handler.path = "/api/logbook"
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = BytesIO()
        handler.do_POST()
        handler.send_response.assert_called_with(401)

        # 3. Request dengan token valid user -> 201
        payload = json.dumps({
            "date": "2026-10-21",
            "projects": ["api-proj"],
            "summary": "Fitur API Multiuser",
            "idempotency_key": "api_test_idemp_key_1",
            "commits": []
        }).encode("utf-8")

        handler = server.LogbookRequestHandler.__new__(server.LogbookRequestHandler)
        handler.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Length": str(len(payload))
        }
        handler.path = "/api/logbook"
        handler.rfile = BytesIO(payload)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = BytesIO()
        handler.do_POST()
        handler.send_response.assert_called_with(201)

        response_body = json.loads(handler.wfile.getvalue().decode('utf-8'))
        self.assertEqual(response_body['chat_id'], test_chat_id)
        self.assertEqual(response_body['status'], 'ok')

if __name__ == "__main__":
    unittest.main()


