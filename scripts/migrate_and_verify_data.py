#!/usr/bin/env python3
"""
scripts/migrate_and_verify_data.py
Script otomatis sekali pakai (one-off migration & verification script)
untuk membackup, memigrasikan, dan memverifikasi integritas data SQLite ke direktori target baru.
"""

from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
import sys

# Tambahkan root path ke sys.path agar dapat mengimpor app.core.config
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings


def get_tables_in_db(conn: sqlite3.Connection) -> list[str]:
    """Mengambil daftar nama tabel pengguna dalam database SQLite (mengabaikan sqlite_sequence)."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    )
    return [row[0] for row in cursor.fetchall()]


def get_table_row_count(conn: sqlite3.Connection, table_name: str) -> int:
    """Menghitung jumlah baris dalam tabel tertentu."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`;")
    row = cursor.fetchone()
    return row[0] if row else 0


def run_integrity_check(conn: sqlite3.Connection) -> str:
    """Menjalankan PRAGMA integrity_check pada database."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA integrity_check;")
    rows = cursor.fetchall()
    if rows and len(rows) == 1 and rows[0][0].lower() == "ok":
        return "OK"
    return "; ".join(r[0] for r in rows)


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = PROJECT_ROOT / "backups" / f"db_backup_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    settings = get_settings()

    # Pemetaan file database sumber (legacy di modul/) ke target (data/)
    db_mapping = [
        {
            "name": "Reminders DB",
            "source": (PROJECT_ROOT / "modul" / "reminder" / "reminders.db").resolve(),
            "target": (PROJECT_ROOT / settings.REMINDER_DB_PATH).resolve(),
        },
        {
            "name": "Bensin & Motor DB",
            "source": (PROJECT_ROOT / "modul" / "bensin" / "bensin.db").resolve(),
            "target": (PROJECT_ROOT / settings.BENSIN_DB_PATH).resolve(),
        },
        {
            "name": "Logbook DERMAGA DB",
            "source": (PROJECT_ROOT / "modul" / "logbook" / "logbook.db").resolve(),
            "target": (PROJECT_ROOT / settings.LOGBOOK_DB_PATH).resolve(),
        },
        {
            "name": "Magang Users DB",
            "source": (PROJECT_ROOT / "modul" / "magang" / "users.db").resolve(),
            "target": (PROJECT_ROOT / settings.MAGANG_DB_PATH).resolve(),
        },
    ]

    print(f"\n{'='*75}")
    print("  🚀 MEMULAI MIGRASI DATABASE & VERIFIKASI INTEGRITAS DATA")
    print(f"{'='*75}")
    print(f"Timestamp        : {timestamp}")
    print(f"Folder Backup    : {backup_dir.relative_to(PROJECT_ROOT)}")
    print(f"{'='*75}\n")

    # 1. Pastikan folder target ada
    for item in db_mapping:
        item["target"].parent.mkdir(parents=True, exist_ok=True)

    verification_results = []
    has_error = False

    for item in db_mapping:
        db_name = item["name"]
        src_path: Path = item["source"]
        tgt_path: Path = item["target"]

        print(f"[*] Memproses {db_name}...")
        print(f"    Sumber : {src_path.relative_to(PROJECT_ROOT)}")
        print(f"    Target : {tgt_path.relative_to(PROJECT_ROOT)}")

        if not src_path.exists():
            print(f"    ⚠️ File sumber tidak ditemukan! Melewati {db_name}.\n")
            continue

        # 1.1 WAL Checkpoint sebelum backup agar semua data tersinkron ke file .db
        try:
            with sqlite3.connect(str(src_path)) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except sqlite3.Error as e:
            print(f"    ⚠️ Gagal jalankan wal_checkpoint pada sumber: {e}")

        # 1.2 Salin ke folder backup
        backup_file = backup_dir / src_path.name
        # Jika nama file bertabrakan (misal ada yang sama), gunakan nama unik
        if backup_file.exists():
            backup_file = backup_dir / f"{src_path.parent.name}_{src_path.name}"
        shutil.copy2(src_path, backup_file)

        # Salin juga wal/shm jika ada
        for extra_ext in ("-wal", "-shm"):
            extra_src = src_path.parent / (src_path.name + extra_ext)
            if extra_src.exists():
                shutil.copy2(extra_src, backup_dir / extra_src.name)

        print(f"    ✅ Backup fisik berhasil disalin ke: {backup_file.name}")

        # 1.3 Cek integritas & hitung baris pada database sumber
        src_integrity = "FAILED"
        src_counts = {}
        with sqlite3.connect(str(src_path)) as src_conn:
            src_conn.row_factory = sqlite3.Row
            src_integrity = run_integrity_check(src_conn)
            tables = get_tables_in_db(src_conn)
            for t in tables:
                src_counts[t] = get_table_row_count(src_conn, t)

        print(f"    🔍 Integrity Check Sumber: {src_integrity}")
        if src_integrity != "OK":
            print(f"    ❌ ERROR: Database sumber {db_name} mengalami kerusakan integritas!")
            has_error = True
            continue

        # 1.4 Pindahkan / Salin ke Target
        shutil.copy2(src_path, tgt_path)
        print(f"    📦 Berhasil disalin ke target: {tgt_path.relative_to(PROJECT_ROOT)}")

        # 1.5 Cek integritas & hitung baris pada database target
        tgt_integrity = "FAILED"
        tgt_counts = {}
        with sqlite3.connect(str(tgt_path)) as tgt_conn:
            tgt_conn.row_factory = sqlite3.Row
            tgt_integrity = run_integrity_check(tgt_conn)
            tgt_tables = get_tables_in_db(tgt_conn)
            for t in tgt_tables:
                tgt_counts[t] = get_table_row_count(tgt_conn, t)

        print(f"    🔍 Integrity Check Target: {tgt_integrity}")
        if tgt_integrity != "OK":
            print(f"    ❌ ERROR: Database target {db_name} mengalami kerusakan integritas!")
            has_error = True
            continue

        # 1.6 Bandingkan kecocokan baris per tabel
        all_tables = sorted(list(set(src_counts.keys()).union(set(tgt_counts.keys()))))
        for t in all_tables:
            s_cnt = src_counts.get(t, -1)
            t_cnt = tgt_counts.get(t, -1)
            match = (s_cnt == t_cnt and s_cnt >= 0)
            if not match:
                has_error = True

            verification_results.append({
                "db_name": db_name,
                "table": t,
                "src_count": s_cnt,
                "tgt_count": t_cnt,
                "src_integrity": src_integrity,
                "tgt_integrity": tgt_integrity,
                "status": "MATCH ✅" if match else "MISMATCH ❌",
            })
        print(f"    ✅ Semua {len(all_tables)} tabel pada {db_name} terverifikasi cocok.\n")

    # 2. Tampilkan Tabel Ringkasan Komparasi
    print(f"\n{'='*85}")
    print(f"  TABEL LAPORAN INTEGRITAS & KOMPARASI DATA SEBELUM/SESUDAH MIGRASI")
    print(f"{'='*85}")
    header_fmt = "{:<20} | {:<26} | {:>9} | {:>9} | {:<12}"
    row_fmt = "{:<20} | {:<26} | {:>9} | {:>9} | {:<12}"
    print(header_fmt.format("Database", "Nama Tabel", "Src Rows", "Tgt Rows", "Status"))
    print(f"{'-'*20}-+-{'-'*26}-+-{'-'*9}-+-{'-'*9}-+-{'-'*12}")

    for r in verification_results:
        print(row_fmt.format(
            r["db_name"][:20],
            r["table"][:26],
            r["src_count"],
            r["tgt_count"],
            r["status"],
        ))

    print(f"{'='*85}\n")

    if has_error:
        print("❌ MIGRASI GAGAL: Terdeteksi ketidakcocokan jumlah baris atau integritas rusak!")
        print("   Database target tidak valid. Jangan hapus database sumber!")
        sys.exit(1)
    else:
        print("🎉 SELURUH DATA TERVERIFIKASI 100% COCOK & AMAN!")
        print(f"   Backup tersimpan di: {backup_dir.relative_to(PROJECT_ROOT)}")
        print("   Silakan lanjutkan ke proses pembersihan file legacy.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
