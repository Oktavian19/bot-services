import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'bensin.db')

def setup_database():
    """Membuat tabel motor dan riwayat bensin jika belum ada, serta migrasi skema bila diperlukan."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL;')
        cursor.execute('PRAGMA busy_timeout=5000;')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS motor (
                chat_id INTEGER PRIMARY KEY,
                nama_motor TEXT NOT NULL,
                odometer_awal REAL NOT NULL,
                odometer_terakhir REAL NOT NULL,
                odometer_terakhir_oli REAL DEFAULT NULL
            )
        ''')
        
        # Cek dan jalankan migrasi jika kolom odometer_terakhir_oli pada motor belum ada
        cursor.execute("PRAGMA table_info(motor)")
        columns_motor = cursor.fetchall()
        col_names_motor = [c[1] for c in columns_motor]
        if 'odometer_terakhir_oli' not in col_names_motor:
            print("[DB-BENSIN] Menambahkan kolom odometer_terakhir_oli ke tabel motor...")
            cursor.execute('ALTER TABLE motor ADD COLUMN odometer_terakhir_oli REAL DEFAULT NULL')
            print("[DB-BENSIN] Kolom odometer_terakhir_oli berhasil ditambahkan!")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS log_bensin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                odometer REAL,
                rupiah INTEGER NOT NULL,
                liter REAL NOT NULL,
                jarak_tempuh REAL DEFAULT 0,
                konsumsi_kml REAL DEFAULT 0,
                tanggal DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Cek dan jalankan migrasi jika kolom odometer pada log_bensin masih berstatus NOT NULL
        cursor.execute("PRAGMA table_info(log_bensin)")
        columns = cursor.fetchall()
        odo_col = next((c for c in columns if c[1] == 'odometer'), None)
        if odo_col and odo_col[3] == 1:
            print("[DB-BENSIN] Menjalankan migrasi skema tabel log_bensin (nullable odometer)...")
            cursor.execute('''
                CREATE TABLE log_bensin_migration (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    odometer REAL,
                    rupiah INTEGER NOT NULL,
                    liter REAL NOT NULL,
                    jarak_tempuh REAL DEFAULT 0,
                    konsumsi_kml REAL DEFAULT 0,
                    tanggal DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                INSERT INTO log_bensin_migration (id, chat_id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml, tanggal)
                SELECT id, chat_id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml, tanggal FROM log_bensin
            ''')
            cursor.execute('DROP TABLE log_bensin')
            cursor.execute('ALTER TABLE log_bensin_migration RENAME TO log_bensin')
            print("[DB-BENSIN] Migrasi skema log_bensin selesai!")
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_log_bensin_chat 
            ON log_bensin(chat_id);
        ''')
        conn.commit()

def register_motor(chat_id, nama_motor, odometer_awal, odometer_terakhir_oli=None):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO motor (chat_id, nama_motor, odometer_awal, odometer_terakhir, odometer_terakhir_oli)
            VALUES (?, ?, ?, ?, ?)
        ''', (chat_id, nama_motor, odometer_awal, odometer_awal, odometer_terakhir_oli))
        conn.commit()
    print(f"[DB-BENSIN] Data motor '{nama_motor}' (Odo Awal: {odometer_awal}, Odo Oli: {odometer_terakhir_oli}) berhasil di-commit ke SQLite untuk User {chat_id}.")

def get_motor(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT nama_motor, odometer_awal, odometer_terakhir, odometer_terakhir_oli FROM motor WHERE chat_id = ?', (chat_id,))
        res = cursor.fetchone()
    return res

def update_odometer_oli(chat_id, odometer_oli):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE motor SET odometer_terakhir_oli = ? WHERE chat_id = ?', (odometer_oli, chat_id))
        updated = cursor.rowcount > 0
        conn.commit()
    if updated:
        print(f"[DB-BENSIN] Odometer ganti oli diperbarui menjadi {odometer_oli} km untuk User {chat_id}.")
    return updated

def get_status_oli(chat_id):
    motor = get_motor(chat_id)
    if not motor:
        return None
    nama_motor, odo_awal, odo_akhir, odo_oli = motor
    if odo_oli is None:
        return {
            "status": "belum_diatur",
            "terakhir_oli": None,
            "target_oli": None,
            "odo_sekarang": odo_akhir,
            "jarak_sejak_oli": 0.0,
            "sisa_km": 0.0
        }
    target_oli = odo_oli + 3000.0
    jarak_sejak_oli = odo_akhir - odo_oli
    sisa_km = target_oli - odo_akhir
    
    if sisa_km < 0:
        status = "terlewat"
    elif sisa_km <= 200:
        status = "mendekati"
    else:
        status = "aman"
        
    return {
        "status": status,
        "terakhir_oli": odo_oli,
        "target_oli": target_oli,
        "odo_sekarang": odo_akhir,
        "jarak_sejak_oli": jarak_sejak_oli,
        "sisa_km": sisa_km
    }

def add_log_bensin(chat_id, odometer_sekarang, rupiah, liter):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT odometer_terakhir FROM motor WHERE chat_id = ?', (chat_id,))
        row = cursor.fetchone()
        
        if not row:
            print(f"[DB-BENSIN - WARNING] Penolakan sistem: User {chat_id} mencoba menambah log bensin tetapi belum mendaftarkan motor.")
            return None
            
        odometer_terakhir = row[0]
        
        # Kasus 1: Pengisian tanpa odometer
        if odometer_sekarang is None:
            cursor.execute('''
                INSERT INTO log_bensin (chat_id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml)
                VALUES (?, NULL, ?, ?, 0, 0)
            ''', (chat_id, rupiah, liter))
            conn.commit()
            print(f"[DB-BENSIN] Log transaksi tanpa Odo (Rp{rupiah}, {liter}L) berhasil di-commit untuk User {chat_id}.")
            return {
                "tanpa_odo": True,
                "rupiah": rupiah,
                "liter": round(liter, 2),
                "jarak": 0.0,
                "kml": 0.0
            }
            
        # Kasus 2: Pengisian dengan odometer (Hitung jarak & akumulasi liter pending)
        odometer_sekarang = float(odometer_sekarang)
        
        # Cari ID log terakhir yang memiliki odometer
        cursor.execute('''
            SELECT id FROM log_bensin 
            WHERE chat_id = ? AND odometer IS NOT NULL 
            ORDER BY id DESC LIMIT 1
        ''', (chat_id,))
        last_odo_log = cursor.fetchone()
        
        if last_odo_log:
            last_id = last_odo_log[0]
            cursor.execute('''
                SELECT SUM(liter), COUNT(*) 
                FROM log_bensin 
                WHERE chat_id = ? AND id > ? AND odometer IS NULL
            ''', (chat_id, last_id))
        else:
            cursor.execute('''
                SELECT SUM(liter), COUNT(*) 
                FROM log_bensin 
                WHERE chat_id = ? AND odometer IS NULL
            ''', (chat_id,))
            
        row_pending = cursor.fetchone()
        pending_liters = row_pending[0] if (row_pending and row_pending[0]) else 0.0
        pending_count = row_pending[1] if (row_pending and row_pending[1]) else 0
        
        jarak_tempuh = odometer_sekarang - odometer_terakhir
        total_liter = pending_liters + liter
        konsumsi_kml = round(jarak_tempuh / total_liter, 2) if total_liter > 0 else 0.0
        
        cursor.execute('''
            INSERT INTO log_bensin (chat_id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (chat_id, odometer_sekarang, rupiah, liter, jarak_tempuh, konsumsi_kml))
        
        cursor.execute('UPDATE motor SET odometer_terakhir = ? WHERE chat_id = ?', (odometer_sekarang, chat_id))
        conn.commit()
        
    print(f"[DB-BENSIN] Log transaksi (Rp{rupiah}, {liter}L) & Update Odo ({odometer_sekarang}km, Total L: {total_liter:.2f}) berhasil di-commit untuk User {chat_id}.")
    
    return {
        "tanpa_odo": False,
        "jarak": jarak_tempuh,
        "liter": round(liter, 2),
        "kml": konsumsi_kml,
        "total_liter_akumulasi": round(total_liter, 2),
        "jumlah_log_tanpa_odo": pending_count
    }

def get_statistik_bensin(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT odometer_awal, odometer_terakhir FROM motor WHERE chat_id = ?', (chat_id,))
        motor = cursor.fetchone()
        if not motor:
            return {"rata_rata": 0.0, "terakhir": 0.0}
            
        odo_awal, odo_akhir = motor
        total_jarak = odo_akhir - odo_awal
        
        # Cari log ber-odometer terakhir
        cursor.execute('''
            SELECT id, konsumsi_kml 
            FROM log_bensin 
            WHERE chat_id = ? AND odometer IS NOT NULL 
            ORDER BY id DESC LIMIT 1
        ''', (chat_id,))
        last_odo_log = cursor.fetchone()
        
        if not last_odo_log or total_jarak <= 0:
            return {"rata_rata": 0.0, "terakhir": 0.0}
            
        last_id, terakhir_kml = last_odo_log
        
        # Hitung total liter hanya dari awal sampai log ber-odometer terakhir
        cursor.execute('''
            SELECT SUM(liter) 
            FROM log_bensin 
            WHERE chat_id = ? AND id <= ?
        ''', (chat_id, last_id))
        row_sum = cursor.fetchone()
        total_liter_verified = row_sum[0] if row_sum and row_sum[0] else 0.0
        
        rata_rata_kml = round(total_jarak / total_liter_verified, 2) if total_liter_verified > 0 else 0.0
        
    return {
        "rata_rata": rata_rata_kml,
        "terakhir": terakhir_kml
    }

def recalculate_bensin_logs(chat_id):
    """Menghitung ulang jarak tempuh, konsumsi km/L, dan odometer terakhir untuk semua log bensin milik user."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT odometer_awal FROM motor WHERE chat_id = ?', (chat_id,))
        row_motor = cursor.fetchone()
        if not row_motor:
            return
            
        odometer_prev = row_motor[0]
        pending_liters = 0.0
        
        cursor.execute('''
            SELECT id, odometer, liter 
            FROM log_bensin 
            WHERE chat_id = ? 
            ORDER BY id ASC
        ''', (chat_id,))
        logs = cursor.fetchall()
        
        for log_id, odometer, liter in logs:
            if odometer is None:
                pending_liters += liter
                cursor.execute('''
                    UPDATE log_bensin 
                    SET jarak_tempuh = 0, konsumsi_kml = 0 
                    WHERE id = ?
                ''', (log_id,))
            else:
                jarak_tempuh = odometer - odometer_prev
                total_liter = pending_liters + liter
                konsumsi_kml = round(jarak_tempuh / total_liter, 2) if total_liter > 0 else 0.0
                
                cursor.execute('''
                    UPDATE log_bensin 
                    SET jarak_tempuh = ?, konsumsi_kml = ? 
                    WHERE id = ?
                ''', (jarak_tempuh, konsumsi_kml, log_id))
                
                pending_liters = 0.0
                odometer_prev = odometer
                
        cursor.execute('UPDATE motor SET odometer_terakhir = ? WHERE chat_id = ?', (odometer_prev, chat_id))
        conn.commit()
    print(f"[DB-BENSIN] Recalculation selesai untuk User {chat_id}. Odo Terakhir: {odometer_prev}")

def get_logs_bensin(chat_id, limit=10):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml, tanggal 
            FROM log_bensin 
            WHERE chat_id = ? 
            ORDER BY id DESC 
            LIMIT ?
        ''', (chat_id, limit))
        rows = cursor.fetchall()
    return rows

def get_log_bensin_by_id(log_id, chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml, tanggal 
            FROM log_bensin 
            WHERE id = ? AND chat_id = ?
        ''', (log_id, chat_id))
        row = cursor.fetchone()
    return row

def delete_log_bensin(log_id, chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM log_bensin WHERE id = ? AND chat_id = ?', (log_id, chat_id))
        deleted = cursor.rowcount > 0
        conn.commit()
        
    if deleted:
        print(f"[DB-BENSIN] Log #{log_id} berhasil dihapus untuk User {chat_id}.")
        recalculate_bensin_logs(chat_id)
    return deleted

def update_log_bensin(log_id, chat_id, odometer, rupiah, liter):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        if odometer is None:
            cursor.execute('''
                UPDATE log_bensin 
                SET odometer = NULL, rupiah = ?, liter = ? 
                WHERE id = ? AND chat_id = ?
            ''', (rupiah, liter, log_id, chat_id))
        else:
            cursor.execute('''
                UPDATE log_bensin 
                SET odometer = ?, rupiah = ?, liter = ? 
                WHERE id = ? AND chat_id = ?
            ''', (odometer, rupiah, liter, log_id, chat_id))
        updated = cursor.rowcount > 0
        conn.commit()
        
    if updated:
        print(f"[DB-BENSIN] Log #{log_id} berhasil di-update untuk User {chat_id}.")
        recalculate_bensin_logs(chat_id)
    return updated