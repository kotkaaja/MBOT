import os
import psycopg2
import logging
from datetime import date

logger = logging.getLogger(__name__)

# --- Objek Koneksi Global ---
db_connection = None

def get_db_connection():
    """Membuat atau mengembalikan koneksi database PostgreSQL yang sudah ada."""
    global db_connection
    # Cek jika koneksi belum ada atau sudah tertutup
    if db_connection is None or db_connection.closed != 0:
        try:
            DATABASE_URL = os.getenv("DATABASE_URL")
            if not DATABASE_URL:
                logger.error("FATAL: DATABASE_URL tidak ditemukan di environment variables.")
                return None
            db_connection = psycopg2.connect(DATABASE_URL)
            logger.info("Koneksi database PostgreSQL berhasil dibuat atau dibuka kembali.")
        except Exception as e:
            logger.error("Gagal membuat koneksi database persisten.", exc_info=e)
            db_connection = None # Set ke None jika gagal
    return db_connection

def init_database():
    """Menginisialisasi database dan membuat semua tabel yang diperlukan."""
    conn = get_db_connection()
    if not conn:
        logger.error("Tidak bisa inisialisasi database karena koneksi gagal.")
        return
        
    try:
        # Menggunakan 'with' memastikan cursor tertutup secara otomatis
        with conn.cursor() as cursor:
            # Tabel untuk fitur Scanner
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scan_history (
                    id SERIAL PRIMARY KEY, 
                    user_id BIGINT NOT NULL, 
                    filename TEXT NOT NULL,
                    file_hash TEXT, 
                    danger_level INTEGER NOT NULL, 
                    analyst TEXT,
                    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, 
                    channel_id BIGINT
                );
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_usage (
                    user_id BIGINT NOT NULL, 
                    date DATE NOT NULL, 
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, date)
                );
            ''')
            # Tabel untuk fitur Character Story
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS char_story_cooldown (
                    user_id BIGINT PRIMARY KEY, 
                    last_used_date DATE NOT NULL
                );
            ''')
            # Tabel untuk fitur MP3 Converter
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS server_settings (
                    guild_id BIGINT PRIMARY KEY,
                    upload_channel_id BIGINT
                );
            ''')
        # Commit perubahan ke database
        conn.commit()
        logger.info("Semua tabel berhasil diinisialisasi di database PostgreSQL.")
    except Exception as e:
        logger.error("Gagal menginisialisasi tabel database.", exc_info=e)
        # Rollback jika terjadi kesalahan
        conn.rollback()

# --- Fungsi untuk MP3 Converter ---
def set_upload_channel(guild_id: int, channel_id: int) -> bool:
    """Menyimpan atau memperbarui channel unggah dan mengembalikan status keberhasilan."""
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cursor:
            # Query UPSERT (UPDATE or INSERT) untuk PostgreSQL
            query = """
                INSERT INTO server_settings (guild_id, upload_channel_id)
                VALUES (%s, %s)
                ON CONFLICT (guild_id)
                DO UPDATE SET upload_channel_id = EXCLUDED.upload_channel_id;
            """
            cursor.execute(query, (guild_id, channel_id))
        conn.commit()
        logger.info(f"Berhasil mengatur upload channel untuk guild {guild_id} ke {channel_id}.")
        return True
    except Exception as e:
        logger.error(f"Gagal menjalankan query set_upload_channel untuk guild {guild_id}", exc_info=e)
        conn.rollback()
        return False

def get_upload_channel(guild_id: int) -> int or None:
    """Mengambil channel unggah yang tersimpan untuk sebuah server."""
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

# --- Fungsi untuk Scanner ---
def check_daily_limit(user_id: int, limit: int) -> bool:
    """Memeriksa batas scan harian pengguna."""
    conn = get_db_connection()
    if not conn: return False # Anggap limit tercapai jika DB tidak terhubung
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT count FROM daily_usage WHERE user_id = %s AND date = %s', (user_id, date.today()))
            result = cursor.fetchone()
        return not (result and result[0] >= limit)
    except Exception as e:
        logger.error(f"Gagal memeriksa daily limit untuk user {user_id}", exc_info=e)
        return False

def increment_daily_usage(user_id: int):
    """Menambah hitungan scan harian pengguna."""
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cursor:
            query = """
                INSERT INTO daily_usage (user_id, date, count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, date)
                DO UPDATE SET count = daily_usage.count + 1;
            """
            cursor.execute(query, (user_id, date.today()))
        conn.commit()
    except Exception as e:
        logger.error(f"Gagal menambah daily usage untuk user {user_id}", exc_info=e)
        conn.rollback()

def save_scan_history(user_id: int, filename: str, file_hash: str, danger_level: int, analyst: str, channel_id: int):
    """Menyimpan riwayat scan."""
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO scan_history (user_id, filename, file_hash, danger_level, analyst, channel_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, filename, file_hash, danger_level, analyst, channel_id)
            )
        conn.commit()
    except Exception as e:
        logger.error(f"Gagal menyimpan riwayat scan untuk file {filename}", exc_info=e)
        conn.rollback()

# --- Fungsi untuk Character Story ---
def check_char_story_cooldown(user_id: int) -> bool:
    """Memeriksa cooldown harian untuk Character Story."""
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT last_used_date FROM char_story_cooldown WHERE user_id = %s', (user_id,))
            result = cursor.fetchone()
        return not (result and result[0] == date.today())
    except Exception as e:
        logger.error(f"Gagal memeriksa cooldown char_story untuk user {user_id}", exc_info=e)
        return False

def set_char_story_cooldown(user_id: int):
    """Mengatur cooldown harian untuk Character Story."""
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cursor:
            query = """
                INSERT INTO char_story_cooldown (user_id, last_used_date)
                VALUES (%s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET last_used_date = EXCLUDED.last_used_date;
            """
            cursor.execute(query, (user_id, date.today()))
        conn.commit()
    except Exception as e:
        logger.error(f"Gagal mengatur cooldown char_story untuk user {user_id}", exc_info=e)
        conn.rollback()

