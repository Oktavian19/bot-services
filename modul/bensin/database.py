import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'bensin.db')

def setup_database():
    """Membuat tabel motor dan riwayat bensin jika belum ada."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
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
    conn.commit()
    conn.close()

def register_motor(chat_id, nama_motor, odometer_awal):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO motor (chat_id, nama_motor, odometer_awal, odometer_terakhir)
        VALUES (?, ?, ?, ?)
    ''', (chat_id, nama_motor, odometer_awal, odometer_awal))
    conn.commit()
    conn.close()

def get_motor(chat_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT nama_motor, odometer_awal, odometer_terakhir FROM motor WHERE chat_id = ?', (chat_id,))
    res = cursor.fetchone()
    conn.close()
    return res

def add_log_bensin(chat_id, odometer_sekarang, rupiah, liter):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT odometer_terakhir FROM motor WHERE chat_id = ?', (chat_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
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
    conn.close()
    
    return {
        "jarak": jarak_tempuh,
        "liter": round(liter, 2),
        "kml": konsumsi_kml
    }

def get_statistik_bensin(chat_id):
    conn = sqlite3.connect(DB_PATH)
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
    
    conn.close()
    
    total_jarak = row_sum[0] if row_sum and row_sum[0] else 0
    total_liter = row_sum[1] if row_sum and row_sum[1] else 0
    
    rata_rata_kml = round(total_jarak / total_liter, 2) if total_liter > 0 else 0.0
    terakhir_kml = row_last[0] if row_last else 0.0
    
    return {
        "rata_rata": rata_rata_kml,
        "terakhir": terakhir_kml
    }