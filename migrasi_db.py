import sqlite3
import os
from cryptography.fernet import Fernet

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')

def main():
    # 1. Generate the Secret Key
    key = Fernet.generate_key()
    cipher = Fernet(key)
    
    print("\n" + "="*50)
    print("!!! SANGAT PENTING !!!")
    print("Copy kunci di bawah ini dan paste ke variabel SECRET_KEY di cek_magang.py:")
    print(f"SECRET_KEY = b'{key.decode()}'")
    print("="*50 + "\n")
    
    if not os.path.exists(DB_FILE):
        print("Database users.db tidak ditemukan. Tidak ada yang dimigrasi.")
        return

    # 2. Migrate the database
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute('SELECT chat_id, username, password FROM users')
        rows = cur.fetchall()
        
        if not rows:
            print("Database kosong. Tidak ada password yang perlu dienkripsi.")
            return
            
        for chat_id, username, plaintext_pass in rows:
            # Cegah enkripsi ganda jika ter-run 2 kali (Token Fernet biasanya diawali 'gAAAAA')
            if len(plaintext_pass) > 50 and plaintext_pass.startswith('gAAAAAB'):
                print(f"Password user {username} sepertinya sudah dienkripsi. Lewati.")
                continue
                
            encrypted_pass = cipher.encrypt(plaintext_pass.encode()).decode()
            cur.execute('UPDATE users SET password = ? WHERE chat_id = ?', (encrypted_pass, chat_id))
            print(f"[OK] Password milik {username} berhasil dienkripsi.")
            
        conn.commit()
        print("\nMigrasi Selesai! Semua password di SQLite kini terkunci aman.")

if __name__ == "__main__":
    main()