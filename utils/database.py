import sqlite3
from datetime import datetime
import logging

# Mengambil logger yang sudah dikonfigurasi di main.py
logger = logging.getLogger(__name__)
DB_FILE = 'scanner.db'

def init_database():
    """
    Menginisialisasi database SQLite dan membuat semua tabel yang diperlukan.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Tabel untuk fitur Scanner
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                filename TEXT NOT NULL, file_hash TEXT, danger_level INTEGER NOT NULL,
                analyst TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, channel_id INTEGER
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_usage (
                user_id INTEGER NOT NULL, date TEXT NOT NULL, count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, date)
            )
        ''')

        # Tabel untuk fitur Character Story
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS char_story_cooldown (
                user_id INTEGER PRIMARY KEY, last_used_date TEXT NOT NULL
            )
        ''')
        
        # Tabel untuk fitur MP3 Converter
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS server_settings (
                guild_id INTEGER PRIMARY KEY,
                upload_channel_id INTEGER
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"Database '{DB_FILE}' berhasil diinisialisasi dengan semua tabel.")
    except Exception as e:
        logger.error("Gagal menginisialisasi database.", exc_info=e)

# --- Fungsi untuk MP3 Converter ---
def set_upload_channel(guild_id: int, channel_id: int):
    """Menyimpan atau memperbarui channel unggah untuk sebuah server."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO server_settings (guild_id, upload_channel_id) VALUES (?, ?)', (guild_id, channel_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Gagal mengatur upload channel untuk guild {guild_id}", exc_info=e)


def get_upload_channel(guild_id: int) -> int or None:
    """Mengambil channel unggah yang tersimpan untuk sebuah server."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT upload_channel_id FROM server_settings WHERE guild_id = ?', (guild_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Gagal mengambil upload channel untuk guild {guild_id}", exc_info=e)
        return None

# --- Fungsi untuk Scanner ---
async def check_daily_limit(user_id: int, limit: int) -> bool:
    """Memeriksa batas scan harian pengguna."""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT count FROM daily_usage WHERE user_id = ? AND date = ?', (user_id, today))
        result = cursor.fetchone()
        conn.close()
        if result and result[0] >= limit:
            return False
        return True
    except Exception as e:
        logger.error(f"Gagal memeriksa daily limit untuk user {user_id}", exc_info=e)
        return False


def increment_daily_usage(user_id: int):
    """Menambah hitungan scan harian pengguna."""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO daily_usage (user_id, date, count) VALUES (?, ?, 0)', (user_id, today))
        cursor.execute('UPDATE daily_usage SET count = count + 1 WHERE user_id = ? AND date = ?', (user_id, today))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Gagal menambah daily usage untuk user {user_id}", exc_info=e)


def save_scan_history(user_id: int, filename: str, file_hash: str, danger_level: int, analyst: str, channel_id: int):
    """Menyimpan riwayat scan."""
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


# --- Fungsi untuk Character Story ---
def check_char_story_cooldown(user_id: int) -> bool:
    """Memeriksa cooldown harian untuk Character Story."""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT last_used_date FROM char_story_cooldown WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        if result and result[0] == today:
            return False
        return True
    except Exception as e:
        logger.error(f"Gagal memeriksa cooldown char_story untuk user {user_id}", exc_info=e)
        return False


def set_char_story_cooldown(user_id: int):
    """Mengatur cooldown harian untuk Character Story."""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO char_story_cooldown (user_id, last_used_date) VALUES (?, ?)', (user_id, today))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Gagal mengatur cooldown char_story untuk user {user_id}", exc_info=e)

