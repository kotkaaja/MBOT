import discord
from discord.ext import commands
import os
import logging
from logging.handlers import RotatingFileHandler
import time
import asyncio
from dotenv import load_dotenv

# Import database utility
from utils.database import init_database

# Muat variabel dari .env
load_dotenv()

# ============================
# SETUP LOGGING
# ============================
def setup_logging():
    if not os.path.exists("logs"):
        os.makedirs("logs")
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler = RotatingFileHandler('logs/bot.log', maxBytes=5*1024*1024, backupCount=3)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger

logger = setup_logging()

# ============================
# KELAS KONFIGURASI
# ============================
class Config:
    """Kelas untuk menampung semua variabel konfigurasi dari environment."""
    def __init__(self):
        self.BOT_TOKEN = os.getenv("BOT_TOKEN")
        self.OPENAI_API_KEYS = [k.strip() for k in os.getenv("OPENAI_API_KEYS", "").split(',') if k.strip()]
        self.GEMINI_API_KEYS = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(',') if k.strip()]
        self.DEEPSEEK_API_KEYS = [k.strip() for k in os.getenv("DEEPSEEK_API_KEYS", "").split(',') if k.strip()]
        self.ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID")) if os.getenv("ALERT_CHANNEL_ID") else None
        self.ALLOWED_CHANNEL_IDS = [int(cid.strip()) for cid in os.getenv("ALLOWED_CHANNEL_IDS", "").split(',') if cid.strip()]
        self.ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID")) if os.getenv("ADMIN_CHANNEL_ID") else None
        self.ADMIN_USER_IDS = [int(uid.strip()) for uid in os.getenv("ADMIN_USER_IDS", "").split(',') if uid.strip()]
        self.ALLOWED_EXTENSIONS = ['.lua', '.txt', '.zip', '.7z', '.rar', '.py', '.js', '.php']
        self.TEMP_DIR = "temp_scan"
        self.MAX_FILE_SIZE_MB = 3
        self.MAX_ARCHIVE_FILES = 5
        self.COMMAND_COOLDOWN_SECONDS = 60
        self.DAILY_LIMIT_PER_USER = 10
        self.QUEUE_MAX_SIZE = 3
        self.CACHE_EXPIRE_HOURS = 24

# ============================
# KELAS BOT KUSTOM
# ============================
class MyBot(commands.Bot):
    """Subclass dari commands.Bot untuk menambahkan atribut kustom."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = Config()
        self.start_time = time.time()
        self.persistent_views_added = False

intents = discord.Intents.default()
intents.message_content = True
bot = MyBot(command_prefix='!', intents=intents, help_command=None)

# ============================
# EVENT & ERROR HANDLING
# ============================
@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Error handler global untuk semua perintah."""
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Anda harus menjadi **Administrator** untuk menggunakan perintah ini.", ephemeral=True, delete_after=15)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Cooldown. Coba lagi dalam **{error.retry_after:.1f} detik**.", ephemeral=True, delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argumen kurang. Contoh: `!{ctx.command.name} server untuk komunitas Valorant`", ephemeral=True, delete_after=15)
    elif isinstance(error, commands.CommandInvokeError):
        logger.error(f"Error pada perintah '{ctx.command.qualified_name}': {error.original}", exc_info=True)
        await ctx.send("❌ Terjadi kesalahan internal saat menjalankan perintah.", ephemeral=True, delete_after=10)
    else:
        logger.error(f"Error tidak dikenal: {error}", exc_info=True)
        # Jangan kirim pesan untuk setiap error aneh untuk menghindari spam
        
# ============================
# FUNGSI UTAMA
# ============================
async def load_cogs():
    """Memuat semua fitur (Cogs) dari direktori cogs."""
    cogs_to_load = ['scanner', 'char_story', 'general', 'server_creator', 'converter']
    for cog_name in cogs_to_load:
        try:
            await bot.load_extension(f'cogs.{cog_name}')
            logger.info(f"✅ Berhasil memuat fitur: {cog_name}.py")
        except Exception as e:
            logger.error(f"❌ Gagal memuat fitur: {cog_name}.py", exc_info=True)

async def main():
    """Fungsi utama untuk menjalankan bot."""
    init_database()
    if not os.path.exists(bot.config.TEMP_DIR):
        os.makedirs(bot.config.TEMP_DIR)
        logger.info(f"✅ Direktori '{bot.config.TEMP_DIR}' berhasil dibuat.")
        
    async with bot:
        await load_cogs()
        if not bot.config.BOT_TOKEN:
            logger.error("❌ FATAL ERROR: BOT_TOKEN tidak ditemukan.")
            return
        try:
            await bot.start(bot.config.BOT_TOKEN)
        except discord.errors.LoginFailure:
            logger.error("❌ FATAL ERROR: Gagal login. Token tidak valid.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot dihentikan.")

