import discord
from discord.ext import commands
import os
import logging
from logging.handlers import RotatingFileHandler
import time
import asyncio
from dotenv import load_dotenv
import json
import requests
import base64
from datetime import timezone, datetime # Tambahkan datetime
from typing import Dict # Import Dict jika belum ada

from utils.database import init_database
# Impor fungsi helper HANYA untuk Config class, cog akan mengimpornya sendiri
from cogs.token import get_github_file, update_github_file, parse_repo_slug 

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
# KELAS KONFIGURASI (VERSI LENGKAP)
# ============================
class Config:
    """Kelas untuk menampung semua variabel konfigurasi dari environment."""
    def __init__(self):
        # Variabel Inti & API Keys
        self.BOT_TOKEN = os.getenv("BOT_TOKEN")
        
        # --- [PERUBAHAN] Load SEMUA AI Keys sebagai LISTS (Daftar) ---
        # Ini untuk support multi-key (Req #2)
        self.OPENAI_API_KEYS = [k.strip() for k in os.getenv("OPENAI_API_KEYS", "").split(',') if k.strip()]
        self.GEMINI_API_KEYS = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(',') if k.strip()]
        self.DEEPSEEK_API_KEYS = [k.strip() for k in os.getenv("DEEPSEEK_API_KEYS", "").split(',') if k.strip()]
        self.OPENROUTER_API_KEYS = [k.strip() for k in os.getenv("OPENROUTER_API_KEY", "").split(',') if k.strip()]
        self.AGENTROUTER_API_KEYS = [k.strip() for k in os.getenv("AGENTROUTER_API_KEY", "").split(',') if k.strip()]
        # --- [AKHIR PERUBAHAN] ---
        
        # Header Opsional untuk OpenRouter
        self.OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "http://localhost") 
        self.OPENROUTER_SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "MBOT")
        
        # Variabel untuk Fitur Scanner
        self.ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID")) if os.getenv("ALERT_CHANNEL_ID") else None
        self.ALLOWED_CHANNEL_IDS = [int(cid.strip()) for cid in os.getenv("ALLOWED_CHANNEL_IDS", "").split(',') if cid.strip()]
        self.ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID")) if os.getenv("ADMIN_CHANNEL_ID") else None
        self.ALLOWED_EXTENSIONS = ['.lua', '.txt', '.zip', '.7z', '.rar', '.py', '.js', '.php']
        self.TEMP_DIR = "temp_scan"
        self.MAX_FILE_SIZE_MB = 3
        self.MAX_ARCHIVE_FILES = 5
        self.COMMAND_COOLDOWN_SECONDS = 60
        
        # --- [DIHAPUS] Limit ini akan diganti oleh sistem Pangkat (Rank) ---
        # self.DAILY_LIMIT_PER_USER = 10 
        # --- [AKHIR PENGHAPUSAN] ---
        
        self.QUEUE_MAX_SIZE = 3
        self.CACHE_EXPIRE_HOURS = 24

        # =================================================
        # VARIABEL BARU UNTUK FITUR TOKEN & ROLE
        # =================================================
        self.GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
        PRIMARY_REPO_INPUT = os.getenv('PRIMARY_REPO', '')
        self.PRIMARY_REPO = parse_repo_slug(PRIMARY_REPO_INPUT)
        ALLOWED_GUILD_IDS_STR = os.getenv('ALLOWED_GUILD_IDS', '')
        self.ALLOWED_GUILD_IDS = {int(gid.strip()) for gid in ALLOWED_GUILD_IDS_STR.split(',') if gid.strip()}
        
        # Untuk cogs/token.py
        self.CLAIM_CHANNEL_ID = int(os.getenv('CLAIM_CHANNEL_ID', 0))
        TOKEN_SOURCES_STR = os.getenv('TOKEN_SOURCES', '')
        self.TOKEN_SOURCES: Dict[str, Dict[str, str]] = {}
        if TOKEN_SOURCES_STR:
            try:
                for item in TOKEN_SOURCES_STR.split(','):
                    alias, full_path = item.split(':', 1)
                    alias = alias.strip().lower()
                    parts = full_path.strip().split('/')
                    raw_slug = '/'.join(parts[:-1])
                    path = parts[-1]
                    cleaned_slug = parse_repo_slug(raw_slug)
                    self.TOKEN_SOURCES[alias] = {"slug": cleaned_slug, "path": path}
            except Exception as e:
                logger.fatal(f"FATAL ERROR: Format TOKEN_SOURCES tidak valid. Error: {e}")

        # Untuk cogs/role_assigner.py
        self.ROLE_REQUEST_CHANNEL_ID = int(os.getenv('ROLE_REQUEST_CHANNEL_ID', 0))
        
        # Admin IDs (digunakan oleh kedua cog)
        self.ADMIN_USER_IDS = {int(uid.strip()) for uid in os.getenv('ADMIN_USER_IDS', '').split(',') if uid.strip()}
        
        # --- PATH FILE DI REPOSITORY GITHUB ---
        self.CLAIMS_FILE_PATH = 'claims.json'
        self.TOKEN_STATE_FILE_PATH = 'token_state.json'

        # --- KONFIGURASI ROLE (TETAP) ---
        self.ROLE_DURATIONS = {"vip": "30d", "supporter": "10d", "inner circle": "7d", "subscriber": "5d", "followers": "5d", "beginner": "3d"}
        self.ROLE_PRIORITY = ["vip", "supporter", "inner circle", "subscriber", "followers", "beginner"]
        self.SUBSCRIBER_ROLE_NAME = "Subscriber"
        self.FOLLOWER_ROLE_NAME = "Followers"
        self.FORGE_VERIFIED_ROLE_NAME = "Inner Circle"
        
        if not all([self.GITHUB_TOKEN, self.PRIMARY_REPO, self.ALLOWED_GUILD_IDS, self.TOKEN_SOURCES]):
            logger.warning("WARNING: Variabel fitur Token (GITHUB_TOKEN, PRIMARY_REPO, ALLOWED_GUILD_IDS, TOKEN_SOURCES) belum diatur lengkap.")
        if not self.PRIMARY_REPO and PRIMARY_REPO_INPUT:
             logger.error(f"FATAL ERROR: PRIMARY_REPO ('{PRIMARY_REPO_INPUT}') tidak dapat di-parse.")


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
        
        # Atribut baru untuk fitur Token
        self.admin_ids = self.config.ADMIN_USER_IDS
        self.owner_id = None # Akan di-set di on_ready
        self.github_lock = asyncio.Lock()
        self.current_claim_source_alias = None
        self.open_claim_message = None
        self.close_claim_message = None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True # Dibutuhkan untuk on_message dan cek role
bot = MyBot(command_prefix='!', intents=intents, help_command=None)

# ============================
# EVENT & ERROR HANDLING
# ============================
@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Error handler global untuk semua perintah (prefix)."""
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Anda harus menjadi **Administrator** untuk menggunakan perintah ini.", delete_after=15)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Cooldown. Coba lagi dalam **{error.retry_after:.1f} detik**.", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argumen kurang. Contoh: `!{ctx.command.name} server untuk komunitas Valorant`", delete_after=15)
    elif isinstance(error, commands.CommandInvokeError):
        logger.error(f"Error pada perintah '{ctx.command.qualified_name}': {error.original}", exc_info=True)
        await ctx.send("❌ Terjadi kesalahan internal saat menjalankan perintah.", delete_after=10)
    else:
        logger.error(f"Error tidak dikenal: {error}", exc_info=True)

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    """Error handler untuk Slash Commands."""
    if isinstance(error, discord.app_commands.CheckFailure):
        await interaction.response.send_message("❌ **Akses Ditolak!** Perintah ini hanya untuk admin bot.", ephemeral=True)
    else:
        logger.error(f"Error tidak terduga pada slash command '{interaction.command.name if interaction.command else 'N/A'}': {error}", exc_info=True)
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("Terjadi error internal saat menjalankan perintah.", ephemeral=True)
            except discord.InteractionResponded:
                await interaction.followup.send("Terjadi error internal saat menjalankan perintah.", ephemeral=True)

@bot.event
async def on_guild_join(guild):
    """Keluar dari server yang tidak diizinkan."""
    if guild.id not in bot.config.ALLOWED_GUILD_IDS:
        logger.warning(f"Bot otomatis keluar dari server tidak sah: {guild.name} ({guild.id})")
        await guild.leave()

# ============================
# FUNGSI UTAMA
# ============================
async def load_cogs():
    """Memuat semua fitur (Cogs) dari direktori cogs."""
    cogs_to_load = ['scanner', 'char_story', 'general', 'server_creator', 'converter', 'token', 'role_assigner', 'template_creator', 'ssrp_chatlog', 'rating', 'role_catalog', 'massage_sender']
    for cog_name in cogs_to_load:
        try:
            await bot.load_extension(f'cogs.{cog_name}')
            logger.info(f"✅ Berhasil memuat fitur: {cog_name}.py")
        except Exception as e:
            logger.error(f"❌ Gagal memuat fitur: {cog_name}.py", exc_info=True)

async def main():
    """Fungsi utama untuk menjalankan bot."""
    init_database()
    
    @bot.event
    async def on_ready():
        logger.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
        
        # 1. Setup Admin & Owner (Global)
        app_info = await bot.application_info()
        bot.owner_id = app_info.owner.id
        bot.admin_ids.add(bot.owner_id) # Tambahkan owner sebagai admin
        logger.info(f'Owner ID: {bot.owner_id}')
        logger.info(f'Daftar Admin ID: {bot.admin_ids}')

        # 2. Cek kesehatan claims.json (Dibutuhkan oleh cogs/token.py)
        async with bot.github_lock:
            logger.info("Mengecek kesehatan claims.json di GitHub...")
            claims_content, claims_sha = get_github_file(
                bot.config.PRIMARY_REPO, 
                bot.config.CLAIMS_FILE_PATH, 
                bot.config.GITHUB_TOKEN
            )
            if claims_content is None:
                logger.warning("claims.json tidak ditemukan, membuat file baru...")
                update_github_file(
                    bot.config.PRIMARY_REPO, 
                    bot.config.CLAIMS_FILE_PATH, 
                    "{}", 
                    None, 
                    "Bot: Initialize claims.json",
                    bot.config.GITHUB_TOKEN
                )
            else:
                try:
                    if not claims_content.strip(): raise json.JSONDecodeError("File is empty", claims_content, 0)
                    json.loads(claims_content)
                except json.JSONDecodeError:
                    logger.error("claims.json rusak atau kosong, menginisialisasi ulang file...")
                    update_github_file(
                        bot.config.PRIMARY_REPO, 
                        bot.config.CLAIMS_FILE_PATH, 
                        "{}", 
                        claims_sha, 
                        "Bot: Re-initialize corrupted claims.json",
                        bot.config.GITHUB_TOKEN
                    )
            logger.info("Health check claims.json selesai, siap digunakan.")

        # 3. Cek kesehatan token_state.json
        async with bot.github_lock:
            logger.info("Mengecek status token_state.json di GitHub...")
            state_content, state_sha = get_github_file(
                bot.config.PRIMARY_REPO,
                bot.config.TOKEN_STATE_FILE_PATH,
                bot.config.GITHUB_TOKEN
            )

            # Tentukan default alias
            default_alias = "bassic" 
            if default_alias not in bot.config.TOKEN_SOURCES:
                default_alias = next(iter(bot.config.TOKEN_SOURCES.keys()), None)
                if default_alias:
                    logger.warning(f"'bassic' tidak ditemukan di TOKEN_SOURCES, menggunakan fallback alias: {default_alias}")
                else:
                    logger.error("FATAL: Tidak ada TOKEN_SOURCES yang dikonfigurasi. Klaim tidak akan berfungsi.")
                    default_alias = None

            if state_content is None:
                logger.warning(f"token_state.json tidak ditemukan, membuat file baru dengan default alias: {default_alias}")
                default_state_data = {"current_claim_alias": default_alias}
                update_github_file(
                    bot.config.PRIMARY_REPO,
                    bot.config.TOKEN_STATE_FILE_PATH,
                    json.dumps(default_state_data, indent=4),
                    None,
                    "Bot: Initialize token_state.json",
                    bot.config.GITHUB_TOKEN
                )
                bot.current_claim_source_alias = default_alias
            else:
                try:
                    if not state_content.strip(): raise json.JSONDecodeError("File is empty", state_content, 0)
                    state_data = json.loads(state_content)
                    bot.current_claim_source_alias = state_data.get("current_claim_alias")
                    
                    if bot.current_claim_source_alias and bot.current_claim_source_alias not in bot.config.TOKEN_SOURCES:
                         logger.warning(f"Alias '{bot.current_claim_source_alias}' di token_state.json tidak valid lagi. Mereset ke default ({default_alias}).")
                         bot.current_claim_source_alias = default_alias
                         default_state_data = {"current_claim_alias": default_alias}
                         update_github_file(
                            bot.config.PRIMARY_REPO,
                            bot.config.TOKEN_STATE_FILE_PATH,
                            json.dumps(default_state_data, indent=4),
                            state_sha,
                            "Bot: Reset token_state.json (alias tidak valid)",
                            bot.config.GITHUB_TOKEN
                         )
                except json.JSONDecodeError:
                    logger.error(f"token_state.json rusak, menginisialisasi ulang file dengan default ({default_alias})...")
                    default_state_data = {"current_claim_alias": default_alias}
                    update_github_file(
                        bot.config.PRIMARY_REPO,
                        bot.config.TOKEN_STATE_FILE_PATH,
                        json.dumps(default_state_data, indent=4),
                        state_sha,
                        "Bot: Re-initialize corrupted token_state.json",
                        bot.config.GITHUB_TOKEN
                    )
                    bot.current_claim_source_alias = default_alias

            logger.info(f"Health check token_state.json selesai. Status klaim saat ini: {bot.current_claim_source_alias}")
        
        # 4. Sinkronisasi Slash Commands
        try:
            synced = await bot.tree.sync()
            logger.info(f"Berhasil sinkronisasi {len(synced)} slash command(s).")
        except Exception as e:
            logger.error(f"Gagal sinkronisasi slash commands: {e}")
        
        logger.info('------')

    if not os.path.exists(bot.config.TEMP_DIR):
        os.makedirs(bot.config.TEMP_DIR)
        
    async with bot:
        await load_cogs()
        if not bot.config.BOT_TOKEN:
            logger.error("❌ FATAL ERROR: BOT_TOKEN tidak ditemukan.")
            return
        try:
            await bot.start(bot.config.BOT_TOKEN)
        except discord.errors.LoginFailure:
            logger.error("❌ FATAL ERROR: Gagal login. Token tidak valid.")
        except Exception as e:
            logger.error(f"❌ FATAL ERROR saat startup: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot dihentikan.")
