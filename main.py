import discord
from discord.ext import commands
import os
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
import time

# Pastikan Anda memiliki file database.py di dalam folder utils/
from utils.database import init_database

# ============================
# KONFIGURASI & INISIALISASI
# ============================

# Memuat variabel environment dari file .env
load_dotenv()

# Fungsi untuk mengatur logging
def setup_logging():
    """Mengatur logging untuk merekam output ke file dan konsol."""
    if not os.path.exists("logs"):
        os.makedirs("logs")

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Handler untuk menulis log ke file dengan rotasi
    file_handler = RotatingFileHandler('logs/bot.log', maxBytes=5*1024*1024, backupCount=3)
    file_handler.setFormatter(formatter)

    # Handler untuk menampilkan log di konsol
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Mengatur logger utama
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

logger = setup_logging()

# Mengambil token bot dari environment
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("FATAL ERROR: BOT_TOKEN tidak ditemukan di file .env! Bot tidak bisa berjalan.")
    exit()

# Menginisialisasi database saat bot pertama kali dijalankan
init_database()

# Menyiapkan bot dengan intents yang diperlukan
intents = discord.Intents.default()
intents.message_content = True  # Diperlukan untuk membaca konten pesan
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ============================
# FUNGSI UTAMA BOT
# ============================

async def load_cogs():
    """Mencari dan memuat semua file fitur (cogs) dari direktori /cogs."""
    cogs_dir = './cogs'
    if not os.path.exists(cogs_dir):
        logger.warning(f"Direktori {cogs_dir} tidak ditemukan. Tidak ada fitur yang dimuat.")
        return
        
    for filename in os.listdir(cogs_dir):
        if filename.endswith('.py'):
            try:
                # Memuat ekstensi/cog
                await bot.load_extension(f'cogs.{filename[:-3]}')
                logger.info(f"✅ Berhasil memuat fitur: {filename}")
            except Exception as e:
                logger.error(f"❌ Gagal memuat fitur: {filename}", exc_info=e)

@bot.event
async def on_ready():
    """Event yang dijalankan ketika bot berhasil terhubung ke Discord."""
    logger.info(f'🤖 Bot siap! Login sebagai {bot.user} ({bot.user.id})')
    
    # Membuat direktori temporary jika belum ada
    if not os.path.exists("temp_scan"):
        os.makedirs("temp_scan")
    
    # Menyimpan waktu mulai untuk perhitungan uptime
    bot.start_time = time.time()
    
    logger.info("="*60)
    logger.info("🚀 Enhanced Lua Security Scanner Bot Dimulai...")

# ============================
# MENJALANKAN BOT
# ============================

async def main():
    """Fungsi utama untuk memuat cogs dan menjalankan bot."""
    async with bot:
        await load_cogs()
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    try:
        # Menjalankan loop event asyncio
        asyncio.run(main())
    except discord.errors.LoginFailure:
        logger.critical("❌ FATAL ERROR: Gagal login. Pastikan BOT_TOKEN Anda valid.")
    except KeyboardInterrupt:
        logger.info("🛑 Bot dihentikan secara manual.")
    except Exception as e:
        logger.critical(f"❌ FATAL ERROR: Terjadi kesalahan tak terduga saat menjalankan bot.", exc_info=True)

