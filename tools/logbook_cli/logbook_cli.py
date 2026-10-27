#!/usr/bin/env python3
import os
import sys
import json
import sqlite3
import argparse
import subprocess
import hashlib
import urllib.request
import urllib.error
import time
import socket
from pathlib import Path
from datetime import datetime

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"
QUEUE_DB_PATH = BASE_DIR / "pending_queue.db"

def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    config = {
        "vps_endpoint": os.environ.get("LOGBOOK_VPS_URL", "http://127.0.0.1:8088/api/logbook"),
        "api_token": os.environ.get("LOGBOOK_API_TOKEN", ""),
        "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
        "openai_base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "openai_model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "custom_prompt": os.environ.get("LOGBOOK_CUSTOM_PROMPT", ""),
        "jam_masuk": os.environ.get("LOGBOOK_JAM_MASUK", "07:10"),
        "jam_pulang": os.environ.get("LOGBOOK_JAM_PULANG", "16:25"),
        "repositories": {}
    }


    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
                for k, v in file_cfg.items():
                    if v:
                        config[k] = v
        except Exception as e:
            print(f"[WARN] Gagal membaca {config_path}: {e}", file=sys.stderr)

    return config

def init_queue_db():
    conn = sqlite3.connect(QUEUE_DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_payloads (
                idempotency_key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                retry_count INTEGER DEFAULT 0,
                last_error TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()

def save_pending_payload(idempotency_key: str, payload: dict, error_msg: str):
    init_queue_db()
    conn = sqlite3.connect(QUEUE_DB_PATH)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO pending_payloads 
            (idempotency_key, payload_json, created_at, retry_count, last_error)
            VALUES (?, ?, ?, COALESCE((SELECT retry_count + 1 FROM pending_payloads WHERE idempotency_key = ?), 0), ?)
        """, (idempotency_key, json.dumps(payload), datetime.now().isoformat(), idempotency_key, error_msg))
        conn.commit()
    finally:
        conn.close()

def remove_pending_payload(idempotency_key: str):
    init_queue_db()
    conn = sqlite3.connect(QUEUE_DB_PATH)
    try:
        conn.execute("DELETE FROM pending_payloads WHERE idempotency_key = ?", (idempotency_key,))
        conn.commit()
    finally:
        conn.close()

def get_pending_payloads() -> list:
    init_queue_db()
    conn = sqlite3.connect(QUEUE_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT idempotency_key, payload_json, retry_count FROM pending_payloads ORDER BY created_at ASC")
        return cur.fetchall()
    finally:
        conn.close()


SKIP_DIRS = {
    'node_modules', 'vendor', '.venv', 'venv', 'build', 'dist', 
    '.cache', '.dart_tool', '.cargo', 'target', '.pub-cache', '__pycache__'
}

def discover_git_repos(root_path: Path, max_depth: int = 5) -> dict:
    """
    Memindai root_path secara rekursif untuk menemukan seluruh direktori git.
    Mengembalikan dict {project_name: str(repo_path)}.
    Jika repo bersarang di bawah root_path, nama proyek diambil dari folder tingkat pertama
    di bawah root_path (misal: sai/SHIN-SEMUT/shin_semut -> SHIN-SEMUT).
    """
    found_repos = {}
    root_resolved = root_path.expanduser().resolve()
    if not root_resolved.exists() or not root_resolved.is_dir():
        return found_repos

    # Jika root_path sendiri adalah git repo langsung
    if (root_resolved / ".git").exists():
        return {root_resolved.name: str(root_resolved)}

    root_parts_len = len(root_resolved.parts)

    for current_dir, dirs, files in os.walk(root_resolved, topdown=True):
        cur_path = Path(current_dir)
        rel_depth = len(cur_path.parts) - root_parts_len

        # Batasi kedalaman traverse
        if rel_depth >= max_depth:
            dirs[:] = []
            continue

        # Prune folder blacklist / hidden
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]

        # Cek apakah direktori saat ini memiliki .git
        if (cur_path / ".git").exists() and cur_path != root_resolved:
            rel_parts = cur_path.relative_to(root_resolved).parts
            proj_name = rel_parts[0] if rel_parts else cur_path.name
            found_repos[proj_name] = str(cur_path)
            # Jangan traverse ke dalam repo yang sudah ditemukan
            dirs[:] = []

    return found_repos

def resolve_all_repositories(repositories_config: dict) -> dict:
    """
    Menyelesaikan mapping konfigurasi repositori:
    - Jika entri berupa git repository langsung, gunakan langsung.
    - Jika entri berupa folder biasa (seperti folder induk 'sai'), jalankan auto-discovery.
    """
    resolved = {}
    for alias, path_str in repositories_config.items():
        path_obj = Path(path_str).expanduser().resolve()
        if not path_obj.exists():
            print(f"[WARN] Path {path_str} ({alias}) tidak ditemukan.", file=sys.stderr)
            continue

        if (path_obj / ".git").exists():
            resolved[alias] = str(path_obj)
        elif path_obj.is_dir():
            discovered = discover_git_repos(path_obj)
            if not discovered:
                print(f"[WARN] Tidak ditemukan repositori Git di dalam {path_str}.", file=sys.stderr)
            for proj_name, repo_dir in discovered.items():
                resolved[proj_name] = repo_dir
    return resolved

def get_commits_for_date(repo_name: str, repo_path: str, date_str: str) -> list:
    """
    Membaca commit tanggal target dari repositori lokal secara read-only.
    Hanya membaca metadata (hash, author, date, subject) dari branch aktif (HEAD).
    """
    path_obj = Path(repo_path).expanduser().resolve()
    if not path_obj.exists() or not (path_obj / ".git").exists():
        print(f"[WARN] Repository {repo_name} pada {repo_path} tidak valid atau bukan git repo.", file=sys.stderr)
        return []

    # Filter rentang waktu hari tersebut: 00:00:00 s.d. 23:59:59
    since_arg = f"--since={date_str} 00:00:00"
    until_arg = f"--until={date_str} 23:59:59"
    cmd = [
        "git", "log",
        since_arg, until_arg,
        "--format=%h|%an|%ad|%s",
        "--date=iso-strict"
    ]

    try:
        res = subprocess.run(cmd, cwd=str(path_obj), capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Gagal membaca git log di {repo_name}: {e}", file=sys.stderr)
        return []

    commits = []
    for line in res.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "project": repo_name,
                "hash": parts[0],
                "author": parts[1],
                "date": parts[2],
                "subject": parts[3]
            })
    return commits

def collect_all_commits(repositories: dict, target_date: str) -> list:
    resolved_repos = resolve_all_repositories(repositories)
    all_commits = []
    for repo_name, repo_path in resolved_repos.items():
        commits = get_commits_for_date(repo_name, repo_path, target_date)
        all_commits.extend(commits)
    return all_commits


def generate_summary(commits: list, config: dict, force_no_ai: bool = False) -> str:
    """
    Menghasilkan ringkasan naratif Bahasa Indonesia.
    Menggunakan OpenAI jika API key tersedia dan tidak --no-ai,
    jika tidak menggunakan fallback non-AI terstruktur.
    """
    if not commits:
        return ""

    api_key = config.get("openai_api_key", "").strip()
    if not force_no_ai and api_key:
        try:
            # Format metadata untuk AI prompt (project dan subject)
            items = [f"- [{c['project']}] {c['subject']}" for c in commits]
            commit_text = "\n".join(items)

            default_system_prompt = (
                "Anda adalah asisten penyusun logbook kerja magang software engineer profesional. "
                "Tugas Anda adalah merangkum commit harian menjadi deskripsi kegiatan logbook yang sangat ringkas, padat, dan elegan.\n\n"
                "Aturan Penulisan:\n"
                "1. Panjang tepat 1 kalimat ringkas (maksimal 2 kalimat jika cakupan pekerjaan sangat luas dan beragam).\n"
                "2. WAJIB diawali langsung dengan kata kerja aktif formal berimbuhan Me- (seperti: Mengembangkan, Menyempurnakan, Menambahkan, Memperbaiki, Melanjutkan pengembangan).\n"
                "3. Dilarang menggunakan kata pengantar, pembuka basa-basi (seperti 'Hari ini...', 'Melakukan...', 'Aktivitas yang dilakukan...'), maupun bullet point.\n"
                "4. Penempatan nama proyek:\n"
                "   - Untuk 1 proyek: letakkan di akhir klausa kegiatan dengan pola '... pada proyek [NAMA_PROYEK].'\n"
                "   - Untuk lebih dari 1 proyek: gabungkan secara alami dengan konjungsi, seperti '... pada proyek [PROYEK_A], serta ... pada [PROYEK_B].' (atau '... pada proyek A dan B' jika pekerjaannya serupa).\n"
                "5. Gunakan istilah teknis utama secara padat dan wajar tanpa mencantumkan hash commit atau detail mikro kode."
            )
            system_prompt = config.get("system_prompt", default_system_prompt).strip()
            custom_prompt = config.get("custom_prompt", "").strip()
            if custom_prompt:
                system_prompt = f"{system_prompt}\n{custom_prompt}"

            user_prompt = f"Berikut daftar commit hari ini:\n{commit_text}\n\nBuat deskripsi kegiatan logbook:"

            req_body = json.dumps({
                "model": config.get("openai_model", "gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.2
            }).encode("utf-8")

            base_url = config.get("openai_base_url", "https://api.openai.com/v1").rstrip("/")
            endpoint_url = f"{base_url}/chat/completions"

            req = urllib.request.Request(
                endpoint_url,
                data=req_body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            )


            with urllib.request.urlopen(req, timeout=30) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                return res_data["choices"][0]["message"]["content"].strip()

        except Exception as e:
            print(f"[WARN] OpenAI summarization gagal ({e}). Beralih ke fallback non-AI.", file=sys.stderr)

    # Fallback Non-AI: Gabungkan subject commit per proyek
    grouped = {}
    for c in commits:
        grouped.setdefault(c["project"], []).append(c["subject"])

    lines = []
    for proj, subjs in grouped.items():
        subjs_str = "; ".join(subjs)
        lines.append(f"Mengerjakan pengembangan pada proyek {proj}: {subjs_str}.")
    return " ".join(lines)

def compute_idempotency_key(date_str: str, commits: list) -> str:
    sorted_signatures = sorted(f"{c['project']}:{c['hash']}" for c in commits)
    raw = f"{date_str}|" + "|".join(sorted_signatures)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def ensure_ssh_tunnel(config: dict) -> bool:
    """
    Jika vps_endpoint menggunakan localhost/127.0.0.1:8088 dan port belum aktif,
    otomatis nyalakan SSH tunnel ke bot-azure di background.
    """
    endpoint = config.get("vps_endpoint", "")
    if "8088" not in endpoint or ("127.0.0.1" not in endpoint and "localhost" not in endpoint):
        return True

    # Cek apakah port 8088 sudah listening lokal
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", 8088))
        s.close()
        return True
    except Exception:
        pass

    # Port belum aktif, coba nyalakan background tunnel otomatis
    ssh_host = config.get("ssh_host", "bot-azure")
    print(f"🔌 Port 8088 belum terbuka. Membuka SSH tunnel ke {ssh_host} otomatis...", file=sys.stderr)
    try:
        subprocess.run(["ssh", "-f", "-N", "-L", "8088:127.0.0.1:8088", ssh_host], check=True)
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"[WARN] Gagal membuka SSH tunnel otomatis: {e}", file=sys.stderr)
        return False

def send_payload_to_vps(payload: dict, config: dict) -> tuple:
    """Mengirim payload JSON ke endpoint VPS. Mengembalikan (success: bool, msg: str)."""
    endpoint = config.get("vps_endpoint")
    token = config.get("api_token")

    if not endpoint:
        return False, "vps_endpoint belum dikonfigurasi"

    # Pastikan SSH tunnel aktif jika mengarah ke port 8088 lokal
    ensure_ssh_tunnel(config)

    body_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body_bytes,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = json.loads(resp.read().decode("utf-8"))
            return True, resp_body.get("message", "OK")
    except urllib.error.HTTPError as he:
        err_content = he.read().decode("utf-8", errors="replace")
        return False, f"HTTP Error {he.code}: {err_content}"
    except Exception as e:
        err_hint = ""
        if "8088" in endpoint and ("127.0.0.1" in endpoint or "localhost" in endpoint):
            err_hint = " (Pastikan SSH tunnel aktif: 'ssh -f -N -L 8088:127.0.0.1:8088 bot-azure')"
        return False, f"Network Error: {str(e)}{err_hint}"

# --- CLI COMMANDS ---

def cmd_preview(args, config):
    target_date = args.date or datetime.now().strftime("%Y-%m-%d")
    repos = config.get("repositories", {})
    if not repos:
        print("Belum ada repositori yang dikonfigurasi di config.json.")
        return

    commits = collect_all_commits(repos, target_date)
    if not commits:
        print(f"Tidak ada commit pada tanggal {target_date}.")
        return

    summary = generate_summary(commits, config, force_no_ai=args.no_ai)
    idemp_key = compute_idempotency_key(target_date, commits)
    projects = sorted(list({c["project"] for c in commits}))

    print("=" * 60)
    print(f"PREVIEW LOGBOOK ({target_date})")
    print("=" * 60)
    print(f"Proyek      : {', '.join(projects)}")
    print(f"Jam Kerja   : {config.get('jam_masuk', '07:10')} - {config.get('jam_pulang', '16:25')}")
    print(f"Idempotency : {idemp_key[:16]}...")
    print(f"Total Commit: {len(commits)}")
    print("-" * 60)
    print("RINGKASAN NARATIF:")
    print(summary)
    print("-" * 60)
    print("DAFTAR COMMIT:")
    for c in commits:
        print(f"  • [{c['project']}] {c['hash']} - {c['subject']}")
    print("=" * 60)

def cmd_run(args, config):
    target_date = args.date or datetime.now().strftime("%Y-%m-%d")
    repos = config.get("repositories", {})
    if not repos:
        print("Belum ada repositori yang dikonfigurasi di config.json.")
        return

    commits = collect_all_commits(repos, target_date)
    if not commits:
        print(f"ℹ️ Tidak ada commit pada tanggal {target_date}. Tidak ada request yang dikirim.")
        return

    summary = generate_summary(commits, config, force_no_ai=args.no_ai)
    idemp_key = compute_idempotency_key(target_date, commits)
    projects = sorted(list({c["project"] for c in commits}))

    payload = {
        "date": target_date,
        "projects": projects,
        "summary": summary,
        "idempotency_key": idemp_key,
        "commits": commits,
        "jam_masuk": config.get("jam_masuk", "07:10"),
        "jam_pulang": config.get("jam_pulang", "16:25")
    }

    success, msg = send_payload_to_vps(payload, config)
    if success:
        print(f"✅ Draf logbook tanggal {target_date} berhasil dikirim ke bot VPS! ({msg})")
    else:
        print(f"⚠️ Gagal mengirim payload ke VPS: {msg}")
        save_pending_payload(idemp_key, payload, msg)
        print("💾 Payload telah disimpan ke antrean pending lokal untuk dicoba ulang berikutnya.")

def cmd_send_pending(args, config):
    pending = get_pending_payloads()
    if not pending:
        print("Tidak ada payload logbook yang tertunda.")
        return

    print(f"Ditemukan {len(pending)} payload tertunda. Mencoba mengirim ulang...")
    for idemp_key, payload_json, retries in pending:
        payload = json.loads(payload_json)
        date_str = payload.get("date", "-")
        success, msg = send_payload_to_vps(payload, config)
        if success:
            print(f"✅ Payload tanggal {date_str} ({idemp_key[:8]}...) berhasil terkirim!")
            remove_pending_payload(idemp_key)
        else:
            print(f"❌ Gagal mengirim ulang {date_str}: {msg}")
            save_pending_payload(idemp_key, payload, msg)

def cmd_scan(args, config):
    repos = config.get("repositories", {})
    if not repos:
        print("Belum ada repositori atau folder induk yang dikonfigurasi di config.json.")
        return

    resolved = resolve_all_repositories(repos)
    print("=" * 65)
    print(f"DAFTAR REPOSITORI GIT TERDETEKSI ({len(resolved)} Repositori)")
    print("=" * 65)
    if not resolved:
        print("Tidak ada repositori Git yang ditemukan.")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    for name, path in sorted(resolved.items()):
        commits_today = get_commits_for_date(name, path, today_str)
        status_commit = f"({len(commits_today)} commit hari ini)" if commits_today else "(0 commit hari ini)"
        print(f"• {name:<18} : {path} {status_commit}")
    print("=" * 65)

def main():
    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path ke file konfigurasi json")

    parser = argparse.ArgumentParser(description="Git Logbook Automation CLI", parents=[base_parser])
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    subparsers.add_parser("scan", parents=[base_parser], help="Pindai dan tampilkan daftar repositori Git yang terdeteksi")

    # preview
    p_prev = subparsers.add_parser("preview", parents=[base_parser], help="Lihat draf logbook tanpa kirim ke VPS")
    p_prev.add_argument("--date", help="Tanggal commit (format YYYY-MM-DD, default hari ini)")
    p_prev.add_argument("--no-ai", action="store_true", help="Pakai ringkasan manual non-AI")

    # run
    p_run = subparsers.add_parser("run", parents=[base_parser], help="Jalankan pembuatan dan pengiriman logbook")
    p_run.add_argument("--date", help="Tanggal commit (format YYYY-MM-DD, default hari ini)")
    p_run.add_argument("--no-ai", action="store_true", help="Pakai ringkasan manual non-AI")

    # send-pending
    subparsers.add_parser("send-pending", parents=[base_parser], help="Kirim ulang draf yang tertunda")

    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "scan":
        cmd_scan(args, config)
    elif args.command == "preview":
        cmd_preview(args, config)
    elif args.command == "run":
        cmd_run(args, config)
    elif args.command == "send-pending":
        cmd_send_pending(args, config)

if __name__ == "__main__":

    main()
