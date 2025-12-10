import os
import psycopg2
import logging
from datetime import date, datetime # Tambahkan datetime
from typing import Tuple # <--- TAMBAHKAN IMPORT INI

logger = logging.getLogger(__name__)

# --- Objek Koneksi Global ---
db_connection = None

# =================================================================
# [BARU] Definisikan Batas Pangkat (Rank)
# =================================================================
# -1 berarti tidak terbatas (unlimited)
RANK_LIMITS = {
    "beginner": 5,
    "low vip": 10,
    "middle vip": 20,
    "upper vip": 30,
    "admin": -1
}
VALID_RANKS = list(RANK_LIMITS.keys())

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

            # =================================================================
            # [BARU] Tabel untuk Pangkat (Rank) dan Limit AI
            # =================================================================
            # Menyimpan pangkat pengguna
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_permissions (
                    user_id BIGINT PRIMARY KEY,
                    rank TEXT NOT NULL DEFAULT 'beginner'
                );
            ''')
            # Menyimpan jejak penggunaan SEMUA FITUR AI
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ai_daily_usage (
                    user_id BIGINT NOT NULL,
                    date DATE NOT NULL,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, date)
                );
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ratings (
                    id SERIAL PRIMARY KEY,
                    target_name TEXT NOT NULL,
                    rater_id BIGINT NOT NULL,
                    stars INTEGER NOT NULL,
                    comment TEXT,
                    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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
    """Memeriksa batas scan harian pengguna (HANYA UNTUK SCANNER LAMA)."""
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
    """Menambah hitungan scan harian pengguna (HANYA UNTUK SCANNER LAMA)."""
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
    """Memeriksa cooldown harian untuk Character Story (SEKARANG DIKELOLA OLEH check_ai_limit)."""
    # Fungsi ini bisa dibiarkan atau dihapus, karena akan diganti
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
    """Mengatur cooldown harian untuk Character Story (SEKARANG DIKELOLA OLEH increment_ai_usage)."""
    # Fungsi ini bisa dibiarkan atau dihapus, karena akan diganti
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


# =================================================================
# [BARU] Fungsi untuk Pangkat (Rank) dan Limit AI Global
# =================================================================

def get_user_rank(user_id: int) -> str:
    """Mengambil pangkat (rank) pengguna dari database."""
    conn = get_db_connection()
    if not conn:
        return 'beginner' # Default jika DB gagal
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT rank FROM user_permissions WHERE user_id = %s', (user_id,))
            result = cursor.fetchone()

        # Jika pengguna tidak ada di tabel, tambahkan sebagai beginner
        if not result:
            set_user_rank(user_id, 'beginner') # Otomatis daftarkan
            return 'beginner'

        rank = result[0].lower()
        # Validasi jika rank di DB tidak valid lagi
        if rank not in VALID_RANKS:
            logger.warning(f"User {user_id} memiliki rank tidak valid '{rank}', direset ke 'beginner'.")
            set_user_rank(user_id, 'beginner')
            return 'beginner'

        return rank

    except Exception as e:
        logger.error(f"Gagal mengambil rank untuk user {user_id}", exc_info=e)
        return 'beginner'

def set_user_rank(user_id: int, rank: str) -> bool:
    """Mengatur atau memperbarui pangkat (rank) pengguna (untuk admin)."""
    rank_lower = rank.lower()
    if rank_lower not in VALID_RANKS:
        logger.warning(f"Upaya mengatur rank tidak valid '{rank}' untuk user {user_id}")
        return False

    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cursor:
            query = """
                INSERT INTO user_permissions (user_id, rank)
                VALUES (%s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET rank = EXCLUDED.rank;
            """
            cursor.execute(query, (user_id, rank_lower))
        conn.commit()
        logger.info(f"Berhasil mengatur rank user {user_id} ke {rank_lower}.")
        return True
    except Exception as e:
        logger.error(f"Gagal mengatur rank untuk user {user_id}", exc_info=e)
        conn.rollback()
        return False

def check_ai_limit(user_id: int) -> Tuple[bool, int, int]:
    """
    Memeriksa apakah pengguna telah mencapai batas penggunaan AI harian mereka.
    Mengembalikan (BolehPakai, SisaRequest, BatasMaksimal)
    """
    conn = get_db_connection()
    if not conn:
        return (False, 0, 0) # Gagalkan jika DB mati

    try:
        rank = get_user_rank(user_id)
        limit = RANK_LIMITS.get(rank, 5) # Default ke 5 jika rank aneh

        # Admin tidak terbatas
        if limit == -1:
            return (True, 999, -1) # BolehPakai, Sisa, BatasMaksimal

        current_usage = 0
        with conn.cursor() as cursor:
            cursor.execute('SELECT count FROM ai_daily_usage WHERE user_id = %s AND date = %s', (user_id, date.today()))
            result = cursor.fetchone()

        if result:
            current_usage = result[0]

        can_use = current_usage < limit
        remaining = limit - current_usage

        return (can_use, remaining, limit)

    except Exception as e:
        logger.error(f"Gagal memeriksa AI limit untuk user {user_id}", exc_info=e)
        return (False, 0, 0)

def increment_ai_usage(user_id: int):
    """Menambah hitungan penggunaan AI harian pengguna."""
    conn = get_db_connection()
    if not conn:
        return

    try:
        with conn.cursor() as cursor:
            query = """
                INSERT INTO ai_daily_usage (user_id, date, count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, date)
                DO UPDATE SET count = ai_daily_usage.count + 1;
            """
            cursor.execute(query, (user_id, date.today()))
        conn.commit()
        logger.info(f"Berhasil menambah AI usage untuk user {user_id}.")
    except Exception as e:
        logger.error(f"Gagal menambah AI usage untuk user {user_id}", exc_info=e)
        conn.rollback()
