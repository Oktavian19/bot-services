import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'bensin.db')

def setup_database():
    """Membuat tabel motor dan riwayat bensin jika belum ada."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL;')
        cursor.execute('PRAGMA busy_timeout=5000;')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS motor (
                chat_id INTEGER PRIMARY KEY,
                nama_motor TEXT NOT NULL,
                odometer_awal INTEGER NOT NULL,
                odometer_terakhir INTEGER NOT NULL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS log_bensin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                odometer INTEGER NOT NULL,
                rupiah INTEGER NOT NULL,
                liter REAL NOT NULL,
                jarak_tempuh INTEGER NOT NULL,
                konsumsi_kml REAL NOT NULL,
                tanggal DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_log_bensin_chat 
            ON log_bensin(chat_id);
        ''')
        conn.commit()

def register_motor(chat_id, nama_motor, odometer_awal):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO motor (chat_id, nama_motor, odometer_awal, odometer_terakhir)
            VALUES (?, ?, ?, ?)
        ''', (chat_id, nama_motor, odometer_awal, odometer_awal))
        conn.commit()
    print(f"[DB-BENSIN] Data motor '{nama_motor}' (Odo: {odometer_awal}) berhasil di-commit ke SQLite untuk User {chat_id}.")

def get_motor(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT nama_motor, odometer_awal, odometer_terakhir FROM motor WHERE chat_id = ?', (chat_id,))
        res = cursor.fetchone()
    return res

def add_log_bensin(chat_id, odometer_sekarang, rupiah, liter):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT odometer_terakhir FROM motor WHERE chat_id = ?', (chat_id,))
        row = cursor.fetchone()
        
        if not row:
            print(f"[DB-BENSIN - WARNING] Penolakan sistem: User {chat_id} mencoba menambah log bensin tetapi belum mendaftarkan motor.")
            return None
            
        odometer_terakhir = row[0]
        jarak_tempuh = odometer_sekarang - odometer_terakhir
        
        konsumsi_kml = round(jarak_tempuh / liter, 2) if liter > 0 else 0.0
        
        cursor.execute('''
            INSERT INTO log_bensin (chat_id, odometer, rupiah, liter, jarak_tempuh, konsumsi_kml)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (chat_id, odometer_sekarang, rupiah, liter, jarak_tempuh, konsumsi_kml))
        
        cursor.execute('UPDATE motor SET odometer_terakhir = ? WHERE chat_id = ?', (odometer_sekarang, chat_id))
        conn.commit()
        
    print(f"[DB-BENSIN] Log transaksi (Rp{rupiah}, {liter}L) & Update Odo ({odometer_sekarang}km) berhasil di-commit untuk User {chat_id}.")
    
    return {
        "jarak": jarak_tempuh,
        "liter": round(liter, 2),
        "kml": konsumsi_kml
    }

def get_statistik_bensin(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT SUM(jarak_tempuh), SUM(liter) 
            FROM log_bensin 
            WHERE chat_id = ?
        ''', (chat_id,))
        row_sum = cursor.fetchone()
        
        cursor.execute('''
            SELECT konsumsi_kml 
            FROM log_bensin 
            WHERE chat_id = ? 
            ORDER BY id DESC LIMIT 1
        ''', (chat_id,))
        row_last = cursor.fetchone()
        
    total_jarak = row_sum[0] if row_sum and row_sum[0] else 0
    total_liter = row_sum[1] if row_sum and row_sum[1] else 0
    
    rata_rata_kml = round(total_jarak / total_liter, 2) if total_liter > 0 else 0.0
    terakhir_kml = row_last[0] if row_last else 0.0
    
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
        
        cursor.execute('''
            SELECT id, odometer, liter 
            FROM log_bensin 
            WHERE chat_id = ? 
            ORDER BY id ASC
        ''', (chat_id,))
        logs = cursor.fetchall()
        
        for log_id, odometer, liter in logs:
            jarak_tempuh = odometer - odometer_prev
            konsumsi_kml = round(jarak_tempuh / liter, 2) if liter > 0 else 0.0
            
            cursor.execute('''
                UPDATE log_bensin 
                SET jarak_tempuh = ?, konsumsi_kml = ? 
                WHERE id = ?
            ''', (jarak_tempuh, konsumsi_kml, log_id))
            
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