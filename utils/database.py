import psycopg2
import os
from datetime import datetime
import logging

# Mengambil logger
logger = logging.getLogger(__name__)
# Mengambil URL database dari environment variable yang disediakan Railway
DATABASE_URL = os.getenv("DATABASE_URL")

db_connection = None

def get_db_connection():
    """Membuat atau mengembalikan koneksi database PostgreSQL."""
    global db_connection
    if db_connection is None or db_connection.closed != 0:
        try:
            if not DATABASE_URL:
                raise ValueError("DATABASE_URL environment variable not set.")
            db_connection = psycopg2.connect(DATABASE_URL)
            logger.info("Koneksi database PostgreSQL berhasil dibuat.")
        except Exception as e:
            logger.error("Gagal membuat koneksi database PostgreSQL.", exc_info=e)
            db_connection = None
    return db_connection

def init_database():
    """Menginisialisasi tabel-tabel di database PostgreSQL."""
    conn = get_db_connection()
    if not conn: return

    try:
        with conn.cursor() as cursor:
            # Tabel Scanner
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scan_history (
                    id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
                    filename TEXT NOT NULL, file_hash TEXT, danger_level INTEGER NOT NULL,
                    analyst TEXT, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    channel_id BIGINT
                )
            ''')
            # Tabel Daily Usage
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_usage (
                    user_id BIGINT NOT NULL, date DATE NOT NULL,
                    count INTEGER DEFAULT 0, PRIMARY KEY (user_id, date)
                )
            ''')
            # Tabel Character Story
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS char_story_cooldown (
                    user_id BIGINT PRIMARY KEY,
                    last_used_date DATE NOT NULL
                )
            ''')
            # Tabel Server Settings
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS server_settings (
                    guild_id BIGINT PRIMARY KEY,
                    upload_channel_id BIGINT
                )
            ''')
        conn.commit()
        logger.info("Database PostgreSQL berhasil diinisialisasi dengan semua tabel.")
    except Exception as e:
        logger.error("Gagal menginisialisasi tabel database.", exc_info=e)

# --- Fungsi untuk MP3 Converter ---
def set_upload_channel(guild_id: int, channel_id: int):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'INSERT INTO server_settings (guild_id, upload_channel_id) VALUES (%s, %s) '
                'ON CONFLICT (guild_id) DO UPDATE SET upload_channel_id = EXCLUDED.upload_channel_id',
                (guild_id, channel_id)
            )
        conn.commit()
    except Exception as e:
        logger.error(f"Gagal mengatur upload channel untuk guild {guild_id}", exc_info=e)

def get_upload_channel(guild_id: int) -> int or None:
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT upload_channel_id FROM server_settings WHERE guild_id = %s', (guild_id,))
            result = cursor.fetchone()
            return result[0] if result else None
    except Exception as e:
        logger.error(f"Gagal mengambil upload channel untuk guild {guild_id}", exc_info=e)
        return None

# --- Fungsi lainnya disesuaikan untuk PostgreSQL ---
async def check_daily_limit(user_id: int, limit: int) -> bool:
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cursor:
            today = datetime.now().date()
            cursor.execute('SELECT count FROM daily_usage WHERE user_id = %s AND date = %s', (user_id, today))
            result = cursor.fetchone()
            return not (result and result[0] >= limit)
    except Exception as e:
        logger.error(f"Gagal memeriksa daily limit untuk user {user_id}", exc_info=e)
        return False

def increment_daily_usage(user_id: int):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cursor:
            today = datetime.now().date()
            cursor.execute(
                'INSERT INTO daily_usage (user_id, date, count) VALUES (%s, %s, 1) '
                'ON CONFLICT (user_id, date) DO UPDATE SET count = daily_usage.count + 1',
                (user_id, today)
            )
        conn.commit()
    except Exception as e:
        logger.error(f"Gagal menambah daily usage untuk user {user_id}", exc_info=e)

def save_scan_history(user_id: int, filename: str, file_hash: str, danger_level: int, analyst: str, channel_id: int):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'INSERT INTO scan_history (user_id, filename, file_hash, danger_level, analyst, channel_id) '
                'VALUES (%s, %s, %s, %s, %s, %s)',
                (user_id, filename, file_hash, danger_level, analyst, channel_id)
            )
        conn.commit()
    except Exception as e:
        logger.error(f"Gagal menyimpan riwayat scan untuk file {filename}", exc_info=e)

def check_char_story_cooldown(user_id: int) -> bool:
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cursor:
            today = datetime.now().date()
            cursor.execute('SELECT last_used_date FROM char_story_cooldown WHERE user_id = %s', (user_id,))
            result = cursor.fetchone()
            return not (result and result[0] == today)
    except Exception as e:
        logger.error(f"Gagal memeriksa cooldown char_story untuk user {user_id}", exc_info=e)
        return False

def set_char_story_cooldown(user_id: int):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cursor:
            today = datetime.now().date()
            cursor.execute(
                'INSERT INTO char_story_cooldown (user_id, last_used_date) VALUES (%s, %s) '
                'ON CONFLICT (user_id) DO UPDATE SET last_used_date = EXCLUDED.last_used_date',
                (user_id, today)
            )
        conn.commit()
    except Exception as e:
        logger.error(f"Gagal mengatur cooldown char_story untuk user {user_id}", exc_info=e)

