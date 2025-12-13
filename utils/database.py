import os
import psycopg2
import logging
from datetime import date, datetime 

logger = logging.getLogger(__name__)

# --- Objek Koneksi Global ---
db_connection = None

# =================================================================
# Definisikan Batas Pangkat (Rank) - UNTUK FITUR AI / SCANNER
# =================================================================
RANK_LIMITS = {
    "beginner": 5,
    "low vip": 10,
    "middle vip": 20,
    "upper vip": 30,
    "admin": -1
}
VALID_RANKS = list(RANK_LIMITS.keys())

def get_db_connection():
    """Membuat atau mengembalikan koneksi database PostgreSQL."""
    global db_connection
    if db_connection is None or db_connection.closed != 0:
        try:
            DATABASE_URL = os.getenv("DATABASE_URL")
            if not DATABASE_URL:
                logger.error("FATAL: DATABASE_URL tidak ditemukan.")
                return None
            db_connection = psycopg2.connect(DATABASE_URL)
        except Exception as e:
            logger.error("Gagal koneksi database.", exc_info=e)
            db_connection = None
    return db_connection

def init_database():
    """Menginisialisasi SEMUA tabel (Lama & Baru)."""
    conn = get_db_connection()
    if not conn: return

    try:
        with conn.cursor() as cursor:
            # --- 1. Tabel Fitur Lama (Scanner, Converter, AI) ---
            cursor.execute('''CREATE TABLE IF NOT EXISTS scan_history (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, filename TEXT NOT NULL, file_hash TEXT, danger_level INTEGER NOT NULL, analyst TEXT, timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, channel_id BIGINT);''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS daily_usage (user_id BIGINT NOT NULL, date DATE NOT NULL, count INTEGER DEFAULT 0, PRIMARY KEY (user_id, date));''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS char_story_cooldown (user_id BIGINT PRIMARY KEY, last_used_date DATE NOT NULL);''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS server_settings (guild_id BIGINT PRIMARY KEY, upload_channel_id BIGINT);''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS user_permissions (user_id BIGINT PRIMARY KEY, rank TEXT NOT NULL DEFAULT 'beginner');''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS ai_daily_usage (user_id BIGINT NOT NULL, date DATE NOT NULL, count INTEGER DEFAULT 0, PRIMARY KEY (user_id, date));''')

            # --- 2. Tabel Fitur Baru (Rating & Support) ---
            # Config Log Channel
            cursor.execute('''CREATE TABLE IF NOT EXISTS rating_config (guild_id BIGINT PRIMARY KEY, log_channel_id BIGINT);''')
            
            # Data Rating (Update: Support Comment & Update Ulang)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ratings (
                    user_id BIGINT NOT NULL,
                    topic TEXT NOT NULL,
                    stars INTEGER NOT NULL,
                    comment TEXT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, topic)
                );
            ''')
            
            # Rules Text (Optional, buat jaga-jaga)
            cursor.execute('''CREATE TABLE IF NOT EXISTS server_rules_text (guild_id BIGINT PRIMARY KEY, rules_content TEXT);''')

        conn.commit()
        logger.info("Database lengkap berhasil diinisialisasi.")
    except Exception as e:
        logger.error("Gagal init database.", exc_info=e)
        conn.rollback()

# =================================================================
# FUNGSI FITUR LAMA (Scanner, MP3, AI)
# =================================================================

def set_upload_channel(guild_id, channel_id):
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO server_settings (guild_id, upload_channel_id) VALUES (%s, %s) ON CONFLICT (guild_id) DO UPDATE SET upload_channel_id = EXCLUDED.upload_channel_id", (guild_id, channel_id))
        conn.commit(); return True
    except: return False

def get_upload_channel(guild_id):
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT upload_channel_id FROM server_settings WHERE guild_id = %s', (guild_id,))
            res = cur.fetchone()
        return res[0] if res else None
    except: return None

def check_daily_limit(user_id, limit):
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT count FROM daily_usage WHERE user_id = %s AND date = %s', (user_id, date.today()))
            res = cur.fetchone()
        return not (res and res[0] >= limit)
    except: return False

def increment_daily_usage(user_id):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO daily_usage (user_id, date, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, date) DO UPDATE SET count = daily_usage.count + 1", (user_id, date.today()))
        conn.commit()
    except: conn.rollback()

def save_scan_history(user_id, filename, file_hash, danger_level, analyst, channel_id):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO scan_history (user_id, filename, file_hash, danger_level, analyst, channel_id) VALUES (%s, %s, %s, %s, %s, %s)", (user_id, filename, file_hash, danger_level, analyst, channel_id))
        conn.commit()
    except: conn.rollback()

def get_user_rank(user_id):
    conn = get_db_connection()
    if not conn: return 'beginner'
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT rank FROM user_permissions WHERE user_id = %s', (user_id,))
            res = cur.fetchone()
        if not res: 
            set_user_rank(user_id, 'beginner'); return 'beginner'
        return res[0].lower()
    except: return 'beginner'

def set_user_rank(user_id, rank):
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO user_permissions (user_id, rank) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET rank = EXCLUDED.rank", (user_id, rank.lower()))
        conn.commit(); return True
    except: return False

def check_ai_limit(user_id):
    conn = get_db_connection()
    if not conn: return (False, 0, 0)
    try:
        rank = get_user_rank(user_id)
        limit = RANK_LIMITS.get(rank, 5)
        if limit == -1: return (True, 999, -1)
        with conn.cursor() as cur:
            cur.execute('SELECT count FROM ai_daily_usage WHERE user_id = %s AND date = %s', (user_id, date.today()))
            res = cur.fetchone()
        curr = res[0] if res else 0
        return (curr < limit, limit - curr, limit)
    except: return (False, 0, 0)

def increment_ai_usage(user_id):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO ai_daily_usage (user_id, date, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, date) DO UPDATE SET count = ai_daily_usage.count + 1", (user_id, date.today()))
        conn.commit()
    except: conn.rollback()

# =================================================================
# FUNGSI FITUR BARU (Rating & Dynamic Support)
# =================================================================

def set_rating_log_channel(guild_id, channel_id):
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO rating_config (guild_id, log_channel_id) VALUES (%s, %s) ON CONFLICT (guild_id) DO UPDATE SET log_channel_id = EXCLUDED.log_channel_id", (guild_id, channel_id))
        conn.commit(); return True
    except: return False

def get_rating_log_channel(guild_id):
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT log_channel_id FROM rating_config WHERE guild_id = %s", (guild_id,))
            res = cur.fetchone()
        return res[0] if res else None
    except: return None

def add_rating(user_id, topic, stars, comment):
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            # UPSERT Logic (Insert or Update)
            cur.execute("""
                INSERT INTO ratings (user_id, topic, stars, comment, created_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, topic) 
                DO UPDATE SET stars = EXCLUDED.stars, comment = EXCLUDED.comment, created_at = CURRENT_TIMESTAMP;
            """, (user_id, topic, stars, comment))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Gagal add rating: {e}")
        conn.rollback()
        return False

def get_rating_stats(topic):
    conn = get_db_connection()
    if not conn: return 0.0, 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT AVG(stars), COUNT(*) FROM ratings WHERE topic = %s", (topic,))
            res = cur.fetchone()
            if res and res[0] is not None:
                return round(float(res[0]), 2), res[1]
            return 0.0, 0
    except: return 0.0, 0

def set_server_rules(guild_id, content):
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO server_rules_text (guild_id, rules_content) VALUES (%s, %s) ON CONFLICT (guild_id) DO UPDATE SET rules_content = EXCLUDED.rules_content", (guild_id, content))
        conn.commit(); return True
    except: return False

def get_server_rules(guild_id):
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT rules_content FROM server_rules_text WHERE guild_id = %s", (guild_id,))
            res = cur.fetchone()
        return res[0] if res else None
    except: return None
