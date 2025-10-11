import sqlite3
from datetime import datetime
import logging

# Mengambil logger yang sudah dikonfigurasi di main.py
logger = logging.getLogger(__name__)
DB_FILE = 'scanner.db'

def init_database():
    """
    Menginisialisasi database SQLite dan membuat tabel-tabel yang diperlukan 
    jika belum ada. Fungsi ini dipanggil sekali saat bot pertama kali dijalankan.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Tabel untuk menyimpan riwayat semua file yang pernah di-scan
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                file_hash TEXT,
                danger_level INTEGER NOT NULL,
                analyst TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                channel_id INTEGER
            )
        ''')
        
        # Tabel untuk melacak berapa kali seorang pengguna melakukan scan per hari
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_usage (
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, date)
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"Database '{DB_FILE}' berhasil diinisialisasi dan tabel telah diverifikasi.")
    except Exception as e:
        logger.error("Gagal menginisialisasi database.", exc_info=e)

async def check_daily_limit(user_id: int, limit: int) -> bool:
    """
    Memeriksa apakah seorang pengguna telah mencapai batas scan harian mereka.
    Mengembalikan True jika pengguna masih bisa scan, False jika sudah mencapai limit.
    """
    today = datetime.now().strftime('%Y-%m-%d')
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT count FROM daily_usage WHERE user_id = ? AND date = ?', (user_id, today))
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] >= limit:
            return False # Limit tercapai
        return True # Masih bisa scan
    except Exception as e:
        logger.error(f"Gagal memeriksa daily limit untuk user {user_id}", exc_info=e)
        return False # Anggap limit tercapai jika terjadi error

def increment_daily_usage(user_id: int):
    """
    Menambahkan +1 pada hitungan scan harian untuk seorang pengguna.
    """
    today = datetime.now().strftime('%Y-%m-%d')
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Membuat baris baru jika pengguna belum pernah scan hari ini
        cursor.execute('INSERT OR IGNORE INTO daily_usage (user_id, date, count) VALUES (?, ?, 0)', (user_id, today))
        # Menambahkan hitungan
        cursor.execute('UPDATE daily_usage SET count = count + 1 WHERE user_id = ? AND date = ?', (user_id, today))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Gagal menambah daily usage untuk user {user_id}", exc_info=e)

def save_scan_history(user_id: int, filename: str, file_hash: str, danger_level: int, analyst: str, channel_id: int):
    """
    Menyimpan detail hasil scan ke dalam tabel scan_history.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO scan_history 
            (user_id, filename, file_hash, danger_level, analyst, channel_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, filename, file_hash, danger_level, analyst, channel_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Gagal menyimpan riwayat scan untuk file {filename}", exc_info=e)

