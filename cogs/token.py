# -*- coding: utf-8 -*-
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import os
import requests
import base64
import json
from datetime import datetime, timedelta, timezone
import secrets
import string
import asyncio
from typing import List, Dict, Optional
import logging
import io # Ditambahkan untuk 'baca_file'

logger = logging.getLogger(__name__)

# =================================================================================
# FUNGSI HELPER
# =================================================================================

def parse_repo_slug(repo_input: str) -> str:
    """Membersihkan input URL repo menjadi format 'owner/repo' yang valid untuk API."""
    if not repo_input: return ""
    for prefix in ["https://github.com/", "http://github.com/"]:
        if repo_input.startswith(prefix): repo_input = repo_input[len(prefix):]
    if repo_input.endswith(".git"): repo_input = repo_input[:-4]
    if repo_input.endswith("/"): repo_input = repo_input[:-1]
    parts = repo_input.split('/')
    return f"{parts[-2]}/{parts[-1]}" if len(parts) >= 2 else repo_input

def get_github_file(repo_slug: str, file_path: str, github_token: str) -> (Optional[str], Optional[str]):
    url = f"https://api.github.com/repos/{repo_slug}/contents/{file_path}"
    headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return base64.b64decode(data['content']).decode('utf-8'), data['sha']
        elif response.status_code == 404:
            return None, None
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error saat get file '{file_path}' (Repo: {repo_slug}): {e}") # Log lebih detail
    return None, None

def update_github_file(repo_slug: str, file_path: str, new_content: str, sha: Optional[str], commit_message: str, github_token: str) -> bool:
    url = f"https://api.github.com/repos/{repo_slug}/contents/{file_path}"
    headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}
    encoded_content = base64.b64encode(new_content.encode('utf-8')).decode('utf-8')
    data = {"message": commit_message, "content": encoded_content}
    if sha: data["sha"] = sha
    try:
        response = requests.put(url, headers=headers, json=data, timeout=10)
        response.raise_for_status()
        logger.info(f"File '{file_path}' (Repo: {repo_slug}) berhasil diupdate: {commit_message}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error saat update file '{file_path}' (Repo: {repo_slug}): {e}") # Log lebih detail
        return False

def parse_duration(duration_str: str) -> timedelta:
    try:
        unit = duration_str[-1].lower(); value = int(duration_str[:-1])
        if unit == 'd': return timedelta(days=value)
        if unit == 'h': return timedelta(hours=value)
        if unit == 'm': return timedelta(minutes=value)
        if unit == 's': return timedelta(seconds=value)
    except (ValueError, IndexError): raise ValueError("Format durasi tidak valid.")
    raise ValueError(f"Unit durasi tidak dikenal: {unit}")

def generate_random_token(role_name: str) -> str:
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    date_part = datetime.now(timezone.utc).strftime('%Y%m%d')
    return f"{role_name.upper().replace(' ', '')}-{random_part}-{date_part}"

# =================================================================================
# FUNGSI CHECK ADMIN (UNTUK PREFIX COMMANDS)
# =================================================================================
async def is_admin_check_prefix(ctx: commands.Context) -> bool:
    """Pemeriksaan internal apakah pengguna adalah admin untuk prefix commands."""
    if not ctx.cog or not hasattr(ctx.cog.bot, 'admin_ids'):
        logger.warning("Pengecekan admin prefix gagal: tidak dapat mengakses cog.bot.admin_ids.")
        return False
    is_admin = ctx.author.id in ctx.cog.bot.admin_ids
    if not is_admin:
        logger.warning(f"Pengecekan admin prefix gagal: {ctx.author.id} tidak ada di {ctx.cog.bot.admin_ids}")
    return is_admin

# =================================================================================
# KELAS PANEL INTERAKTIF (USER-FACING)
# =================================================================================

class ClaimPanelView(ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance
        self.ROLE_DURATIONS = bot_instance.config.ROLE_DURATIONS
        self.ROLE_PRIORITY = bot_instance.config.ROLE_PRIORITY
        self.TOKEN_SOURCES = bot_instance.config.TOKEN_SOURCES
        self.PRIMARY_REPO = bot_instance.config.PRIMARY_REPO
        self.CLAIMS_FILE_PATH = bot_instance.config.CLAIMS_FILE_PATH
        self.GITHUB_TOKEN = bot_instance.config.GITHUB_TOKEN

    @ui.button(label="Claim Token", style=discord.ButtonStyle.success, custom_id="claim_token_button")
    async def claim_button_callback(self, interaction: discord.Interaction, button: ui.Button):
        if not self.bot.current_claim_source_alias:
            await interaction.response.send_message("❌ Sesi klaim saat ini sedang ditutup oleh admin.", ephemeral=True); return

        await interaction.response.defer(ephemeral=True, thinking=True)
        user, user_id, current_time = interaction.user, str(interaction.user.id), datetime.now(timezone.utc)
        
        async with self.bot.github_lock:
            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            if claims_content is None: # Cek jika file tidak ada/gagal fetch
                 await interaction.followup.send("❌ Error: Gagal membaca database klaim (claims.json). Pastikan `PRIMARY_REPO` di .env sudah benar.", ephemeral=True); return
            claims_data = json.loads(claims_content if claims_content else '{}')

            if user_id in claims_data:
                user_claim_info = claims_data[user_id]
                # Cek Cooldown
                if 'last_claim_timestamp' in user_claim_info:
                    try:
                        last_claim_time = datetime.fromisoformat(user_claim_info['last_claim_timestamp'])
                        if current_time < last_claim_time + timedelta(days=7):
                            next_claim_time = last_claim_time + timedelta(days=7)
                            await interaction.followup.send(f"❌ **Cooldown!** Anda baru bisa klaim lagi <t:{int(next_claim_time.timestamp())}:R>.", ephemeral=True); return
                    except ValueError:
                        logger.warning(f"Format timestamp tidak valid untuk user {user_id}. Mengabaikan cooldown check.")
                
                # Cek Token Aktif
                if 'current_token' in user_claim_info and 'token_expiry_timestamp' in user_claim_info:
                     try:
                         expiry_time = datetime.fromisoformat(user_claim_info['token_expiry_timestamp'])
                         if expiry_time > current_time:
                             await interaction.followup.send(f"❌ Token Anda saat ini masih aktif hingga <t:{int(expiry_time.timestamp())}:R>.", ephemeral=True); return
                     except ValueError:
                         logger.warning(f"Format expiry timestamp tidak valid untuk user {user_id}. Mengizinkan klaim.")


            user_role_names = [role.name.lower() for role in user.roles]
            claim_role = next((role for role in self.ROLE_PRIORITY if role in user_role_names), None)
            if not claim_role:
                await interaction.followup.send("❌ Anda tidak memiliki peran (`VIP`, `Supporter`, dll.) yang valid untuk klaim token.", ephemeral=True); return
            
            source_alias = self.bot.current_claim_source_alias
            token_source_info = self.TOKEN_SOURCES.get(source_alias)
            if not token_source_info: # Cek jika alias tidak ada di config
                 await interaction.followup.send(f"❌ Error: Konfigurasi sumber token `{source_alias}` tidak ditemukan. Hubungi admin.", ephemeral=True); return
            
            target_repo_slug, target_file_path = token_source_info["slug"], token_source_info["path"]
            duration_str = self.ROLE_DURATIONS[claim_role]
            
            try: duration_delta = parse_duration(duration_str)
            except ValueError:
                await interaction.followup.send("❌ Kesalahan konfigurasi durasi role. Hubungi admin.", ephemeral=True); return

            new_token = generate_random_token(claim_role)
            expiry_timestamp = current_time + duration_delta
            
            tokens_content, tokens_sha = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
            if tokens_content is None: # Cek jika file token tidak ada
                 await interaction.followup.send(f"❌ Error: Gagal membaca file token dari sumber `{source_alias}`. Pastikan `TOKEN_SOURCES` di .env sudah benar.", ephemeral=True); return
            
            new_tokens_content = (tokens_content or "").strip() + f"\n\n{new_token}\n\n"
            token_add_success = update_github_file(target_repo_slug, target_file_path, new_tokens_content, tokens_sha, f"Bot: Add token for {user.name}", self.GITHUB_TOKEN)
            
            if not token_add_success:
                await interaction.followup.send("❌ Gagal membuat token di file sumber. Silakan coba lagi nanti.", ephemeral=True); return

            # Simpan data klaim baru
            claims_data[user_id] = {
                "last_claim_timestamp": current_time.isoformat(), 
                "current_token": new_token, 
                "token_expiry_timestamp": expiry_timestamp.isoformat(), 
                "source_alias": source_alias
            }
            claim_db_update_success = update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, f"Bot: Update claim for {user.name}", self.GITHUB_TOKEN)

            # Rollback jika gagal simpan data klaim
            if not claim_db_update_success:
                logger.critical(f"KRITIS: Gagal menyimpan claim untuk {user.name}. Melakukan rollback token.")
                # Coba ambil lagi konten file token TERBARU
                current_tokens_content_rb, current_tokens_sha_rb = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
                if current_tokens_content_rb and new_token in current_tokens_content_rb:
                    lines = [line for line in current_tokens_content_rb.split('\n\n') if line.strip() and line.strip() != new_token]
                    content_after_removal = "\n\n".join(lines) + ("\n\n" if lines else "")
                    # Gunakan SHA terbaru untuk rollback
                    rollback_success = update_github_file(target_repo_slug, target_file_path, content_after_removal, current_tokens_sha_rb, f"Bot: ROLLBACK token for {user.name}", self.GITHUB_TOKEN)
                    logger.info(f"Status Rollback: {'Berhasil' if rollback_success else 'Gagal'}")
                await interaction.followup.send("❌ **Klaim Gagal!** Terjadi kesalahan saat menyimpan data klaim Anda. Token tidak dapat diberikan. Silakan hubungi admin.", ephemeral=True); return

        # Kirim DM ke pengguna
        try:
            await user.send(
                f"🎉 **Token Anda Berhasil Diklaim!**\n\n"
                f"**Sumber:** `{source_alias.title()}`\n"
                f"**Token Anda:** ```{new_token}```\n"
                f"**Role:** `{claim_role.title()}`\n"
                f"Aktif hingga: <t:{int(expiry_timestamp.timestamp())}:F> (<t:{int(expiry_timestamp.timestamp())}:R>)"
            )
            await interaction.followup.send("✅ **Berhasil!** Token Anda telah dikirim melalui DM.", ephemeral=True)
        except discord.Forbidden:
            logger.warning(f"Gagal mengirim DM ke {user.name} ({user_id}).")
            await interaction.followup.send("⚠️ Gagal mengirim DM (mungkin DM Anda tertutup?). Token Anda tetap berhasil dibuat.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error tidak dikenal saat mengirim DM klaim: {e}")
            await interaction.followup.send("✅ Token berhasil dibuat, namun gagal mengirim notifikasi DM.", ephemeral=True)


    @ui.button(label="Cek Token Saya", style=discord.ButtonStyle.secondary, custom_id="check_token_button")
    async def check_button_callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        user_id = str(interaction.user.id)
        current_time = datetime.now(timezone.utc)
        
        claims_content, _ = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
        if claims_content is None:
             await interaction.followup.send("❌ Error: Gagal membaca database klaim (claims.json). Pastikan `PRIMARY_REPO` di .env sudah benar.", ephemeral=True); return
        claims_data = json.loads(claims_content if claims_content else '{}')

        if user_id not in claims_data or not claims_data[user_id]: # Juga cek jika data user kosong
            await interaction.followup.send("Anda belum pernah melakukan klaim token atau data Anda kosong.", ephemeral=True); return
        
        user_data = claims_data[user_id]
        embed = discord.Embed(title="📄 Detail Token Anda", color=discord.Color.blue())
        
        # Cek Token Aktif
        token_aktif = False
        if 'current_token' in user_data and 'token_expiry_timestamp' in user_data:
            try:
                expiry_time = datetime.fromisoformat(user_data["token_expiry_timestamp"])
                if expiry_time > current_time:
                    embed.add_field(name="Token Aktif", value=f"```{user_data['current_token']}```", inline=False)
                    embed.add_field(name="Sumber", value=f"`{user_data.get('source_alias', 'N/A').title()}`", inline=True)
                    embed.add_field(name="Kedaluwarsa Pada", value=f"<t:{int(expiry_time.timestamp())}:F> (<t:{int(expiry_time.timestamp())}:R>)", inline=True)
                    token_aktif = True
            except ValueError:
                embed.add_field(name="Token Aktif", value="Error: Format data kedaluwarsa tidak valid.", inline=False)

        if not token_aktif:
             embed.description = "Anda tidak memiliki token yang aktif saat ini."

        # Cek Cooldown
        if 'last_claim_timestamp' in user_data:
            try:
                last_claim_time = datetime.fromisoformat(user_data["last_claim_timestamp"])
                next_claim_time = last_claim_time + timedelta(days=7)
                if current_time < next_claim_time:
                     embed.add_field(name="Cooldown Klaim", value=f"Bisa klaim lagi <t:{int(next_claim_time.timestamp())}:R>", inline=False)
                else:
                     embed.add_field(name="Cooldown Klaim", value="✅ Anda sudah bisa klaim token baru.", inline=False)
            except ValueError:
                embed.add_field(name="Cooldown Klaim", value="Error: Format data klaim terakhir tidak valid.", inline=False)
        else:
            embed.add_field(name="Cooldown Klaim", value="✅ Anda bisa klaim token sekarang.", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


# =================================================================================
# KELAS COG UTAMA (TOKEN)
# =================================================================================
class TokenCog(commands.Cog, name="Token"):
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        
        self.GITHUB_TOKEN = self.config.GITHUB_TOKEN
        self.PRIMARY_REPO = self.config.PRIMARY_REPO
        self.CLAIMS_FILE_PATH = self.config.CLAIMS_FILE_PATH
        self.TOKEN_SOURCES = self.config.TOKEN_SOURCES
        self.ROLE_DURATIONS = self.config.ROLE_DURATIONS
        self.ROLE_PRIORITY = self.config.ROLE_PRIORITY
        self.CLAIM_CHANNEL_ID = self.config.CLAIM_CHANNEL_ID
        
        # Set untuk melacak user yang sudah dinotifikasi cooldown berakhir
        self.cooldown_notified_users = set()

        self.cleanup_expired_tokens.start()
        logger.info("✅ Token Cog loaded, cleanup task started.")

    def cog_unload(self):
        self.cleanup_expired_tokens.cancel()
        logger.info("🛑 Token Cog unloaded, cleanup task stopped.")

    # --- BACKGROUND TASK ---
    @tasks.loop(hours=1) # Cek setiap jam
    async def cleanup_expired_tokens(self):
        logger.info(f"[{datetime.now()}] Menjalankan tugas pembersihan token kedaluwarsa...")
        current_time = datetime.now(timezone.utc)
        
        async with self.bot.github_lock:
            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            if not claims_content:
                logger.warning("Pembersihan token dibatalkan: Gagal membaca claims.json."); return
            try:
                claims_data = json.loads(claims_content)
            except json.JSONDecodeError:
                logger.error("Pembersihan token dibatalkan: claims.json rusak."); return

            keys_to_process = list(claims_data.keys())
            tokens_to_remove_by_source = {}
            claims_updated = False
            # users_to_notify_cooldown_end = [] # DIHAPUS SESUAI REQUEST

            for key in keys_to_process:
                # Hanya proses user IDs untuk token expired (non-shared)
                if key.isdigit():
                    user_id_int = int(key)
                    data = claims_data.get(key)
                    if not data: continue

                    # 1. Cek Token Kedaluwarsa & Notifikasi (HANYA NOTIFIKASI SAAT EXPIRED)
                    if "token_expiry_timestamp" in data and "current_token" in data:
                        try:
                            expiry_time = datetime.fromisoformat(data["token_expiry_timestamp"])
                            if expiry_time < current_time:
                                claims_updated = True
                                token = data.get("current_token")
                                alias = data.get("source_alias")
                                logger.info(f"Token {token} untuk user {key} telah kedaluwarsa.")

                                # Tambahkan ke daftar hapus dari source
                                if token and alias and alias in self.TOKEN_SOURCES:
                                    if alias not in tokens_to_remove_by_source:
                                        tokens_to_remove_by_source[alias] = {"slug": self.TOKEN_SOURCES[alias]["slug"], "path": self.TOKEN_SOURCES[alias]["path"], "tokens": set()}
                                    tokens_to_remove_by_source[alias]["tokens"].add(token)

                                # Cek apakah cooldown masih aktif untuk notifikasi
                                next_claim_time_str = "N/A"
                                if 'last_claim_timestamp' in data:
                                    try:
                                        last_claim_time = datetime.fromisoformat(data['last_claim_timestamp'])
                                        next_claim_time = last_claim_time + timedelta(days=7)
                                        if current_time < next_claim_time:
                                            next_claim_time_str = f"Bisa klaim lagi <t:{int(next_claim_time.timestamp())}:R>."
                                        else:
                                            next_claim_time_str = "Anda sudah bisa klaim lagi."
                                    except ValueError: pass

                                # Kirim notifikasi kedaluwarsa DENGAN status cooldown
                                member = self.bot.get_user(user_id_int)
                                if member:
                                    try:
                                        await member.send(
                                            f"⏳ Token Anda (`{token}`) telah kedaluwarsa.\n"
                                            f"Status cooldown: {next_claim_time_str}"
                                        )
                                        logger.info(f"Mengirim notifikasi token expired ke user {key}.")
                                    except discord.Forbidden:
                                        logger.warning(f"Gagal kirim DM expired ke user {key}.")
                                
                                # Hapus data token dari claims_data
                                data.pop("current_token", None)
                                data.pop("token_expiry_timestamp", None)
                                data.pop("source_alias", None)
                                data.pop("assigned_by_admin", None) # Hapus juga jika ada
                                
                        except ValueError:
                             logger.warning(f"Format expiry timestamp tidak valid untuk user {key}. Melewati cek expired.")
                
                # Proses "shared" tokens
                elif key.startswith("shared_"):
                    data = claims_data.get(key)
                    if not data: continue
                    if "token_expiry_timestamp" in data and "current_token" in data:
                        try:
                            expiry_time = datetime.fromisoformat(data["token_expiry_timestamp"])
                            if expiry_time < current_time:
                                claims_updated = True
                                token = data.get("current_token")
                                alias = data.get("source_alias")
                                logger.info(f"Token SHARED {token} telah kedaluwarsa.")
                                
                                if token and alias and alias in self.TOKEN_SOURCES:
                                    if alias not in tokens_to_remove_by_source:
                                        tokens_to_remove_by_source[alias] = {"slug": self.TOKEN_SOURCES[alias]["slug"], "path": self.TOKEN_SOURCES[alias]["path"], "tokens": set()}
                                    tokens_to_remove_by_source[alias]["tokens"].add(token)
                                
                                # Hapus data token shared dari claims_data
                                claims_data.pop(key, None) 
                        except ValueError:
                            logger.warning(f"Format expiry timestamp tidak valid untuk shared token {key}.")

                # 2. Cek Cooldown Selesai & Notifikasi (DIHAPUS SESUAI REQUEST)

            # Proses Penghapusan Token dari File Sumber
            if claims_updated:
                for alias, info in tokens_to_remove_by_source.items():
                    content, sha = get_github_file(info["slug"], info["path"], self.GITHUB_TOKEN)
                    if content:
                        lines = content.split('\n\n')
                        initial_count = len([l for l in lines if l.strip()])
                        new_lines = [line for line in lines if line.strip() and line.strip() not in info["tokens"]]
                        final_count = len(new_lines)
                        
                        if initial_count != final_count: # Hanya update jika ada perubahan
                            new_content = "\n\n".join(new_lines) + ("\n\n" if new_lines else "")
                            if update_github_file(info["slug"], info["path"], new_content, sha, f"Bot: Hapus {initial_count - final_count} token kedaluwarsa otomatis", self.GITHUB_TOKEN):
                                logger.info(f"{initial_count - final_count} token kedaluwarsa dihapus dari sumber: {alias}")
                            else:
                                 logger.error(f"Gagal menghapus token kedaluwarsa dari sumber: {alias}")

                # Update claims.json HANYA jika ada perubahan (token dihapus)
                if update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, "Bot: Bersihkan data klaim token kedaluwarsa", self.GITHUB_TOKEN):
                    logger.info("Pembersihan data token kedaluwarsa di claims.json selesai.")
                else:
                    logger.error("Gagal update claims.json setelah membersihkan token kedaluwarsa.")
            else:
                 logger.info("Tidak ada token kedaluwarsa yang perlu dibersihkan.")

        # Kirim Notifikasi Cooldown Selesai (DIHAPUS SESUAI REQUEST)


    @cleanup_expired_tokens.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()
        logger.info("Background task 'cleanup_expired_tokens' siap.")

    # --- PERINTAH PREFIX (ADMIN) ---

    @commands.command(name="open_claim", help="ADMIN: Membuka sesi klaim untuk sumber token tertentu. Usage: !open_claim [alias]")
    @commands.check(is_admin_check_prefix)
    async def open_claim(self, ctx: commands.Context, alias: str = None):
        if not alias:
            await ctx.send("❌ Usage: `!open_claim [alias_sumber]`", delete_after=15); return

        alias_lower = alias.lower()
        if alias_lower not in self.TOKEN_SOURCES:
            await ctx.send(f"❌ Alias `{alias}` tidak valid. Cek .env `TOKEN_SOURCES`.", delete_after=15); return
        if not self.CLAIM_CHANNEL_ID or not (claim_channel := self.bot.get_channel(self.CLAIM_CHANNEL_ID)):
            await ctx.send(f"❌ `CLAIM_CHANNEL_ID` tidak valid atau channel tidak ditemukan.", delete_after=15); return

        if self.bot.close_claim_message:
            try: await self.bot.close_claim_message.delete()
            except discord.HTTPException: pass
            finally: self.bot.close_claim_message = None

        self.bot.current_claim_source_alias = alias_lower
        embed = discord.Embed(title=f"📝 Sesi Klaim Dibuka: {alias.title()}", description=f"Sesi klaim untuk sumber `{alias.title()}` telah dibuka oleh {ctx.author.mention}.", color=discord.Color.green())
        try:
            self.bot.open_claim_message = await claim_channel.send(embed=embed, view=ClaimPanelView(self.bot))
            await ctx.send(f"✅ Panel klaim untuk `{alias.title()}` dikirim ke {claim_channel.mention}.", delete_after=10)
        except discord.Forbidden:
             await ctx.send(f"❌ Bot tidak punya izin mengirim pesan/view di {claim_channel.mention}.", delete_after=15)
        except Exception as e:
             logger.error(f"Error saat mengirim panel klaim: {e}")
             await ctx.send(f"❌ Terjadi error saat mengirim panel: {e}", delete_after=15)

    @commands.command(name="close_claim", help="ADMIN: Menutup sesi klaim dan mengirim notifikasi. Usage: !close_claim")
    @commands.check(is_admin_check_prefix)
    async def close_claim(self, ctx: commands.Context):
        if not self.bot.current_claim_source_alias:
            await ctx.send("ℹ️ Tidak ada sesi klaim yang sedang aktif.", delete_after=10); return
            
        if self.bot.open_claim_message:
            try:
                embed = discord.Embed(title="Sesi Klaim Ditutup", description=f"Sesi klaim untuk `{self.bot.current_claim_source_alias.title()}` telah ditutup.", color=discord.Color.orange())
                await self.bot.open_claim_message.edit(embed=embed, view=None)
                logger.info(f"View klaim dihapus dari pesan {self.bot.open_claim_message.id}")
            except discord.HTTPException as e:
                 logger.warning(f"Gagal mengedit pesan panel klaim saat menutup: {e}")
            finally:
                 self.bot.open_claim_message = None
                 
        closed_alias = self.bot.current_claim_source_alias
        self.bot.current_claim_source_alias = None
        
        if self.CLAIM_CHANNEL_ID and (claim_channel := self.bot.get_channel(self.CLAIM_CHANNEL_ID)):
            try:
                embed_closed = discord.Embed(title="🔴 Sesi Klaim Ditutup", description=f"Admin ({ctx.author.mention}) telah menutup sesi klaim untuk `{closed_alias.title()}`.", color=discord.Color.red())
                self.bot.close_claim_message = await claim_channel.send(embed=embed_closed)
            except discord.Forbidden:
                 logger.warning(f"Gagal mengirim pesan notifikasi penutupan ke channel {self.CLAIM_CHANNEL_ID}.")
        
        await ctx.send(f"🔴 Sesi klaim untuk `{closed_alias.title()}` telah ditutup.", delete_after=10)

    @commands.command(name="admin_add_token", help="ADMIN: Menambahkan token custom ke sumber file. Usage: !admin_add_token [alias] [token]")
    @commands.check(is_admin_check_prefix)
    async def admin_add_token(self, ctx: commands.Context, alias: str = None, token: str = None):
        if not alias or not token:
            await ctx.send("❌ Usage: `!admin_add_token [alias_sumber] [token]`", delete_after=15); return
        
        alias_lower = alias.lower()
        source_info = self.TOKEN_SOURCES.get(alias_lower)
        if not source_info:
            await ctx.send(f"❌ Alias `{alias}` tidak valid.", delete_after=15); return

        await ctx.message.add_reaction('⏳')
        async with self.bot.github_lock:
            content, sha = get_github_file(source_info["slug"], source_info["path"], self.GITHUB_TOKEN)
            if content is None:
                 await ctx.send(f"❌ Gagal membaca file token dari `{alias}`. Cek .env `TOKEN_SOURCES`.", delete_after=15); return
            if token in (content or ""):
                await ctx.send(f"⚠️ Token `{token}` sudah ada di `{alias}`.", delete_after=15); return
            
            new_content = (content or "").strip() + f"\n\n{token}\n\n"
            if update_github_file(source_info["slug"], source_info["path"], new_content, sha, f"Admin {ctx.author.name}: Add custom token {token}", self.GITHUB_TOKEN):
                await ctx.send(f"✅ Token `{token}` ditambahkan ke `{alias}`.", delete_after=15)
            else:
                await ctx.send(f"❌ Gagal menambahkan token ke `{alias}` di GitHub.", delete_after=15)

    @commands.command(name="admin_remove_token", help="ADMIN: Menghapus token dari sumber file. Usage: !admin_remove_token [alias] [token]")
    @commands.check(is_admin_check_prefix)
    async def admin_remove_token(self, ctx: commands.Context, alias: str = None, token: str = None):
        if not alias or not token:
            await ctx.send("❌ Usage: `!admin_remove_token [alias_sumber] [token]`", delete_after=15); return
            
        alias_lower = alias.lower()
        source_info = self.TOKEN_SOURCES.get(alias_lower)
        if not source_info:
            await ctx.send(f"❌ Alias `{alias}` tidak valid.", delete_after=15); return
            
        await ctx.message.add_reaction('⏳')
        async with self.bot.github_lock:
            content, sha = get_github_file(source_info["slug"], source_info["path"], self.GITHUB_TOKEN)
            if content is None:
                 await ctx.send(f"❌ Gagal membaca file token dari `{alias}`.", delete_after=15); return
            if not content or token not in content:
                await ctx.send(f"❌ Token `{token}` tidak ditemukan di `{alias}`.", delete_after=15); return
                
            lines = [line for line in content.split('\n\n') if line.strip() and line.strip() != token]
            new_content = "\n\n".join(lines) + ("\n\n" if lines else "")

            if new_content != content:
                if update_github_file(source_info["slug"], source_info["path"], new_content, sha, f"Admin {ctx.author.name}: Remove token {token}", self.GITHUB_TOKEN):
                    await ctx.send(f"✅ Token `{token}` dihapus dari `{alias}`.", delete_after=15)
                else:
                    await ctx.send(f"❌ Gagal menghapus token dari `{alias}` di GitHub.", delete_after=15)
            else:
                 await ctx.send(f"ℹ️ Token `{token}` tidak ditemukan (mungkin sudah dihapus).", delete_after=15)

    @commands.command(name="admin_add_shared", help="ADMIN: Menambah token umum dg durasi. Usage: !admin_add_shared [alias] [token] [durasi]")
    @commands.check(is_admin_check_prefix)
    async def admin_add_shared_token(self, ctx: commands.Context, alias: str = None, token: str = None, durasi: str = None):
        if not alias or not token or not durasi:
            await ctx.send("❌ Usage: `!admin_add_shared [alias_sumber] [token] [durasi]` (cth: 7d, 24h, 30m)", delete_after=15); return

        alias_lower = alias.lower()
        source_info = self.TOKEN_SOURCES.get(alias_lower)
        if not source_info:
            await ctx.send(f"❌ Alias `{alias}` tidak valid.", delete_after=15); return
        try:
            duration_delta = parse_duration(durasi)
            if duration_delta <= timedelta(0):
                 await ctx.send(f"❌ Durasi harus positif.", delete_after=15); return
        except ValueError as e:
            await ctx.send(f"❌ Format durasi tidak valid: {e}", delete_after=15); return

        await ctx.message.add_reaction('⏳')
        async with self.bot.github_lock:
            target_repo_slug, target_file_path = source_info["slug"], source_info["path"]
            
            # 1. Tambah token ke file sumber
            tokens_content, tokens_sha = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
            if tokens_content is None:
                 await ctx.send(f"❌ Gagal membaca file token dari `{alias}`.", delete_after=15); return
            if token in (tokens_content or ""):
                await ctx.send(f"⚠️ Token `{token}` sudah ada di file sumber `{alias}`. Tidak ditambahkan ulang.", delete_after=15); return
                
            new_tokens_content = (tokens_content or "").strip() + f"\n\n{token}\n\n"
            token_add_success = update_github_file(target_repo_slug, target_file_path, new_tokens_content, tokens_sha, f"Admin {ctx.author.name}: Add shared token {token}", self.GITHUB_TOKEN)
            if not token_add_success:
                await ctx.send("❌ Gagal menambahkan token ke file sumber GitHub. Operasi dibatalkan.", delete_after=15); return

            _, tokens_sha_after_add = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)

            # 2. Tambah data ke claims.json
            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            if claims_content is None:
                 await ctx.send("❌ Gagal membaca database klaim (claims.json).", delete_after=15); return
            claims_data = json.loads(claims_content if claims_content else '{}')
            claim_key = f"shared_{alias_lower}_{token}"

            if claim_key in claims_data:
                logger.warning(f"Data untuk token shared '{token}' di '{alias}' sudah ada di claims.json.")
                await ctx.send(f"⚠️ Data untuk token `{token}` sudah ada di database klaim. Token tetap ada di file sumber.", delete_after=15)
                return
                
            current_time = datetime.now(timezone.utc); expiry_time = current_time + duration_delta
            claims_data[claim_key] = {
                "current_token": token, 
                "token_expiry_timestamp": expiry_time.isoformat(), 
                "source_alias": alias_lower, 
                "is_shared": True
            }
            claim_db_update_success = update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, f"Admin {ctx.author.name}: Add data for shared token {token}", self.GITHUB_TOKEN)
            
            # 3. Rollback jika gagal simpan ke claims.json
            if not claim_db_update_success:
                logger.critical(f"KRITIS: Gagal menyimpan data klaim untuk token shared '{token}'. Melakukan rollback dari file sumber.")
                current_tokens_content_rb, current_tokens_sha_rb = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
                if current_tokens_content_rb and token in current_tokens_content_rb:
                    lines = [line for line in current_tokens_content_rb.split('\n\n') if line.strip() and line.strip() != token]
                    content_after_removal = "\n\n".join(lines) + ("\n\n" if lines else "")
                    rollback_success = update_github_file(target_repo_slug, target_file_path, content_after_removal, tokens_sha_after_add, f"Admin {ctx.author.name}: ROLLBACK shared token {token}", self.GITHUB_TOKEN)
                    logger.info(f"Status Rollback shared token '{token}': {'Berhasil' if rollback_success else 'Gagal'}")
                await ctx.send("❌ Gagal menyimpan data token ke database klaim. Token di file sumber telah dihapus kembali (rollback).", delete_after=15)
                return

        await ctx.send(f"✅ Token `{token}` ditambahkan ke `{alias}`. Akan aktif hingga <t:{int(expiry_time.timestamp())}:F> (<t:{int(expiry_time.timestamp())}:R>).", delete_after=15)

    @commands.command(name="admin_give_token", help="ADMIN: Berikan token ke user. Usage: !admin_give_token [user] [alias] [token] [durasi]")
    @commands.check(is_admin_check_prefix)
    async def admin_give_token(self, ctx: commands.Context, user: discord.Member = None, alias: str = None, token: str = None, durasi: str = None):
        if not user or not alias or not token or not durasi:
            await ctx.send("❌ Usage: `!admin_give_token [@user] [alias_sumber] [token] [durasi]`", delete_after=15); return
            
        admin = ctx.author
        alias_lower = alias.lower()

        source_info = self.TOKEN_SOURCES.get(alias_lower)
        if not source_info:
            await ctx.send(f"❌ Alias `{alias}` tidak valid.", delete_after=15); return
        try:
            duration_delta = parse_duration(durasi)
            if duration_delta <= timedelta(0):
                 await ctx.send(f"❌ Durasi harus positif.", delete_after=15); return
        except ValueError as e:
            await ctx.send(f"❌ Format durasi tidak valid: {e}", delete_after=15); return

        await ctx.message.add_reaction('⏳')
        async with self.bot.github_lock:
            target_repo_slug, target_file_path = source_info["slug"], source_info["path"]
            
            # 1. Pastikan token ADA di file sumber
            tokens_content, _ = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
            if tokens_content is None:
                 await ctx.send(f"❌ Gagal membaca file token dari `{alias}`.", delete_after=15); return
            if not tokens_content or token not in tokens_content.split():
                await ctx.send(f"❌ Token `{token}` tidak ditemukan di file sumber `{alias}`. Tambahkan dulu jika perlu.", delete_after=15); return

            # 2. Update claims.json untuk user
            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            if claims_content is None:
                 await ctx.send("❌ Gagal membaca database klaim (claims.json).", delete_after=15); return
            claims_data = json.loads(claims_content if claims_content else '{}')
            user_id_str = str(user.id)
            
            if user_id_str in claims_data and 'current_token' in claims_data[user_id_str]:
                 try:
                     expiry_time_existing = datetime.fromisoformat(claims_data[user_id_str]['token_expiry_timestamp'])
                     if expiry_time_existing > datetime.now(timezone.utc):
                          logger.warning(f"Admin {admin.name} menimpa token aktif milik {user.name}.")
                 except ValueError: pass

            current_time = datetime.now(timezone.utc)
            expiry_time = current_time + duration_delta
            
            claims_data[user_id_str] = {
                **claims_data.get(user_id_str, {}),
                "current_token": token, 
                "token_expiry_timestamp": expiry_time.isoformat(), 
                "source_alias": alias_lower,
                "assigned_by_admin": admin.id
            }
            
            claim_db_update_success = update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, f"Admin {admin.name}: Assign token {token} to {user.name}", self.GITHUB_TOKEN)
            
            if not claim_db_update_success:
                await ctx.send(f"❌ Gagal menyimpan data pemberian token untuk {user.mention} ke database klaim.", delete_after=15)
                return

        # 3. Kirim DM ke User (di luar lock)
        try:
            await user.send(
                f"🎁 Anda telah diberikan token oleh admin!\n\n"
                f"**Token:** ```{token}```\n"
                f"**Sumber:** `{alias.title()}`\n"
                f"**Diberikan oleh:** {admin.mention}\n"
                f"**Aktif hingga:** <t:{int(expiry_time.timestamp())}:F> (<t:{int(expiry_time.timestamp())}:R>)\n\n"
                f"*Catatan: Pemberian token ini tidak memengaruhi cooldown klaim normal Anda.*"
            )
            logger.info(f"Admin {admin.name} berhasil memberikan token {token} ke {user.name}. DM terkirim.")
            await ctx.send(f"✅ Token `{token}` berhasil diberikan kepada {user.mention} selama `{durasi}`. Notifikasi DM telah dikirim.", delete_after=15)
        except discord.Forbidden:
            logger.warning(f"Gagal mengirim DM pemberian token ke {user.name} ({user.id}). Token tetap diberikan.")
            await ctx.send(f"✅ Token `{token}` berhasil diberikan kepada {user.mention}, namun gagal mengirim notifikasi DM.", delete_after=15)
        except Exception as e:
            logger.error(f"Error tidak dikenal saat kirim DM pemberian token: {e}")
            await ctx.send(f"✅ Token `{token}` berhasil diberikan kepada {user.mention}, namun gagal mengirim notifikasi DM karena error.", delete_after=15)

    @commands.command(name="list_sources", help="ADMIN: Menampilkan semua sumber token. Usage: !list_sources")
    @commands.check(is_admin_check_prefix)
    async def list_sources(self, ctx: commands.Context):
        embed = discord.Embed(title="🔧 Konfigurasi Sumber Token", color=discord.Color.purple())
        if not self.TOKEN_SOURCES:
            embed.description = "Variabel `TOKEN_SOURCES` belum diatur."
        else:
            desc = []
            for alias, info in self.TOKEN_SOURCES.items():
                 desc.append(f"**Alias:** `{alias.title()}`\n**Repo:** `{info['slug']}`\n**File:** `{info['path']}`")
            embed.description = "\n\n".join(desc)
        await ctx.send(embed=embed)

    @commands.command(name="baca_file", help="ADMIN: Membaca konten file dari sumber token. Usage: !baca_file [alias]")
    @commands.check(is_admin_check_prefix)
    async def baca_file(self, ctx: commands.Context, alias: str = None):
        if not alias:
            await ctx.send("❌ Usage: `!baca_file [alias_sumber]`", delete_after=15); return

        alias_lower = alias.lower()
        source_info = self.TOKEN_SOURCES.get(alias_lower)
        if not source_info:
            await ctx.send(f"❌ Alias `{alias}` tidak valid.", delete_after=15); return
            
        await ctx.message.add_reaction('⏳')
        content, _ = get_github_file(source_info["slug"], source_info["path"], self.GITHUB_TOKEN)
        if content is None:
            await ctx.send(f"❌ File `{source_info['path']}` tidak ditemukan di repo `{source_info['slug']}`.", delete_after=15); return
        if not content.strip():
             await ctx.send(f"ℹ️ File `{alias}` kosong.", delete_after=15); return
            
        if len(content) > 1900:
            try:
                file = discord.File(io.StringIO(content), filename=f"{alias_lower}_content.txt")
                await ctx.send(f"📄 Konten dari `{alias}` (terlalu panjang, dikirim sebagai file):", file=file)
            except Exception as e:
                 await ctx.send(f"❌ Gagal mengirim file: {e}", delete_after=15)
        else:
            embed = discord.Embed(title=f"📄 Konten dari `{alias}`", description=f"```\n{content}\n```", color=discord.Color.blue())
            embed.set_footer(text=f"Repo: {source_info['slug']}, File: {source_info['path']}")
            await ctx.send(embed=embed)

    @commands.command(name="admin_reset_user", help="ADMIN: Mereset cooldown & token aktif user. Usage: !admin_reset_user [user]")
    @commands.check(is_admin_check_prefix)
    async def admin_reset_cooldown(self, ctx: commands.Context, user: discord.Member = None):
        if not user:
            await ctx.send("❌ Usage: `!admin_reset_user [@user]`", delete_after=15); return
            
        user_id_str = str(user.id)
        admin = ctx.author
        
        await ctx.message.add_reaction('⏳')
        async with self.bot.github_lock:
            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            if claims_content is None:
                 await ctx.send("❌ Gagal membaca database klaim (claims.json).", delete_after=15); return
            claims_data = json.loads(claims_content if claims_content else '{}')
            
            if user_id_str not in claims_data or not claims_data[user_id_str]:
                await ctx.send(f"ℹ️ {user.mention} tidak memiliki data klaim.", delete_after=15); return
            
            claims_data[user_id_str] = {}
                
            if update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, f"Admin {admin.name}: Reset data for {user.name}", self.GITHUB_TOKEN):
                logger.info(f"Admin {admin.name} mereset data klaim untuk {user.name} ({user_id_str}).")
                
                try:
                    await user.send(f"⚙️ Data klaim token Anda telah direset oleh admin {admin.mention}.")
                    await ctx.send(f"✅ Data klaim untuk {user.mention} berhasil direset. Notifikasi DM terkirim.", delete_after=15)
                except discord.Forbidden:
                     await ctx.send(f"✅ Data klaim untuk {user.mention} berhasil direset, namun gagal mengirim notifikasi DM.", delete_after=15)

                if user.id in self.cooldown_notified_users:
                    self.cooldown_notified_users.remove(user.id)
            else:
                await ctx.send(f"❌ Gagal mereset data untuk {user.mention} di GitHub.", delete_after=15)

    @commands.command(name="admin_cek_user", help="ADMIN: Memeriksa status token/cooldown user. Usage: !admin_cek_user [user]")
    @commands.check(is_admin_check_prefix)
    async def admin_cek_user(self, ctx: commands.Context, user: discord.Member = None):
        if not user:
            await ctx.send("❌ Usage: `!admin_cek_user [@user]`", delete_after=15); return
            
        claims_content, _ = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
        if claims_content is None:
             await ctx.send("❌ Gagal membaca database klaim (claims.json).", delete_after=15); return
        claims_data = json.loads(claims_content if claims_content else '{}')
        user_id_str = str(user.id)
        current_time = datetime.now(timezone.utc)

        if user_id_str not in claims_data or not claims_data[user_id_str]:
            await ctx.send(f"**{user.display_name}** tidak memiliki data klaim.", delete_after=15); return
        
        user_data = claims_data[user_id_str]
        embed = discord.Embed(title=f"🔍 Status Token - {user.display_name}", color=discord.Color.orange())
        embed.set_thumbnail(url=user.display_avatar.url)
        
        token_aktif = False
        if 'current_token' in user_data and 'token_expiry_timestamp' in user_data:
            try:
                expiry_time = datetime.fromisoformat(user_data["token_expiry_timestamp"])
                if expiry_time > current_time:
                    embed.add_field(name="Token Aktif", value=f"`{user_data['current_token']}`", inline=False)
                    embed.add_field(name="Sumber", value=f"`{user_data.get('source_alias', 'N/A').title()}`", inline=True)
                    embed.add_field(name="Kedaluwarsa", value=f"<t:{int(expiry_time.timestamp())}:R>", inline=True)
                    if user_data.get("assigned_by_admin"):
                         admin_assign = self.bot.get_user(user_data["assigned_by_admin"])
                         admin_name = str(admin_assign) if admin_assign else f"ID: {user_data['assigned_by_admin']}"
                         embed.add_field(name="Diberikan Oleh", value=f"Admin ({admin_name})", inline=False)
                    token_aktif = True
            except ValueError:
                 embed.add_field(name="Token Aktif", value="Error: Format data kedaluwarsa tidak valid.", inline=False)

        if not token_aktif:
            embed.description = "Pengguna tidak memiliki token aktif saat ini."

        if 'last_claim_timestamp' in user_data:
            try:
                last_claim_time = datetime.fromisoformat(user_data["last_claim_timestamp"])
                next_claim_time = last_claim_time + timedelta(days=7)
                embed.add_field(name="Klaim Terakhir", value=f"<t:{int(last_claim_time.timestamp())}:F>", inline=False)
                if current_time < next_claim_time:
                    embed.add_field(name="Cooldown Klaim", value=f"Berakhir <t:{int(next_claim_time.timestamp())}:R>", inline=False)
                else:
                    embed.add_field(name="Cooldown Klaim", value="✅ Sudah bisa klaim lagi", inline=False)
            except ValueError:
                 embed.add_field(name="Cooldown Klaim", value="Error: Format data klaim terakhir tidak valid.", inline=False)
        else:
             if not token_aktif:
                 embed.add_field(name="Cooldown Klaim", value="✅ Bisa klaim (belum pernah klaim normal / sudah direset)", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="list_tokens", help="ADMIN: Menampilkan semua token aktif. Usage: !list_tokens")
    @commands.check(is_admin_check_prefix)
    async def list_tokens(self, ctx: commands.Context):
        guild = ctx.guild
        if not guild:
            await ctx.send("Perintah ini harus dijalankan di dalam server.", delete_after=15); return

        await ctx.message.add_reaction('⏳')
        claims_content, _ = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
        if claims_content is None:
             await ctx.send("❌ Gagal membaca database klaim (claims.json).", delete_after=15); return
        claims_data = json.loads(claims_content if claims_content else '{}')
        if not claims_data:
            await ctx.send("Database klaim kosong.", delete_after=15); return

        active_tokens_list = []
        current_time = datetime.now(timezone.utc)

        for key, data in claims_data.items():
            if 'current_token' in data and 'token_expiry_timestamp' in data:
                 try:
                     expiry_time = datetime.fromisoformat(data["token_expiry_timestamp"])
                     if expiry_time > current_time:
                         token_info = f"- `{data['current_token']}` (Sumber: {data.get('source_alias', 'N/A').title()})"
                         if key.isdigit():
                             member = guild.get_member(int(key))
                             user_display = f"**{member}**" if member else f"User ID: `{key}`"
                             active_tokens_list.append(f"{user_display}: {token_info}")
                         elif key.startswith("shared_"):
                              active_tokens_list.append(f"**(Shared)** {token_info}")
                 except ValueError: continue

        if not active_tokens_list:
             await ctx.send("Tidak ada token yang sedang aktif.", delete_after=15); return

        embed = discord.Embed(title="🔑 Daftar Token Aktif", color=discord.Color.blue())
        description_part = ""
        for item in active_tokens_list:
            if len(description_part) + len(item) + 2 > 4000:
                embed.description = description_part
                await ctx.send(embed=embed)
                embed = discord.Embed(title="🔑 Daftar Token Aktif (Lanjutan)", color=discord.Color.blue())
                description_part = item + "\n"
            else:
                description_part += item + "\n"
        
        embed.description = description_part
        await ctx.send(embed=embed)

    @commands.command(name="show_config", help="ADMIN: Menampilkan channel & repo. Usage: !show_config")
    @commands.check(is_admin_check_prefix)
    async def show_config(self, ctx: commands.Context):
        embed = discord.Embed(title="🔧 Konfigurasi Bot (Token & Role)", color=discord.Color.teal())
        embed.add_field(name="Repo Utama (claims.json)", value=f"`{self.PRIMARY_REPO}`" if self.PRIMARY_REPO else "Belum diatur", inline=False)
        embed.add_field(name="Channel Klaim Token", value=f"<#{self.CLAIM_CHANNEL_ID}> (`{self.CLAIM_CHANNEL_ID}`)" if self.CLAIM_CHANNEL_ID else "Belum diatur", inline=False)
        
        role_req_ch_id = self.bot.config.ROLE_REQUEST_CHANNEL_ID
        embed.add_field(name="Channel Request Role", value=f"<#{role_req_ch_id}> (`{role_req_ch_id}`)" if role_req_ch_id else "Belum diatur", inline=False)
        
        guild_ids = ", ".join(f"`{gid}`" for gid in self.bot.config.ALLOWED_GUILD_IDS)
        embed.add_field(name="Server ID yang Diizinkan", value=guild_ids if guild_ids else "Belum diatur", inline=False)
        
        admin_ids = ", ".join(f"`{uid}`" for uid in self.bot.admin_ids)
        embed.add_field(name="Admin Bot IDs", value=admin_ids if admin_ids else "Hanya Owner", inline=False)

        embed.set_footer(text="Diatur melalui Environment Variables.")
        await ctx.send(embed=embed)

    @commands.command(name="serverlist", help="ADMIN: Menampilkan daftar server bot. Usage: !serverlist")
    @commands.check(is_admin_check_prefix)
    async def serverlist(self, ctx: commands.Context):
        server_list = [f"- **{guild.name}** (ID: `{guild.id}` | Members: {guild.member_count})" 
                       for guild in self.bot.guilds]
        allowed_status = {guild.id: ("✅ Diizinkan" if guild.id in self.bot.config.ALLOWED_GUILD_IDS else "❌ Tidak Diizinkan") 
                          for guild in self.bot.guilds}
        
        description = "\n".join(f"{s} - {allowed_status.get(int(s.split('`')[1]), 'N/A')}" for s in server_list)

        embed = discord.Embed(title=f"Bot Aktif di {len(self.bot.guilds)} Server", 
                              description=description, 
                              color=0x3498db)
        await ctx.send(embed=embed)

    # --- [PERINTAH BARU] ---
    @commands.command(name="notifycooldowns", help="ADMIN: Kirim notifikasi DM ke user yg cooldownnya selesai. Usage: !notifycooldowns")
    @commands.check(is_admin_check_prefix)
    async def notify_cooldowns(self, ctx: commands.Context):
        await ctx.message.add_reaction('⏳')
        current_time = datetime.now(timezone.utc)
        
        claims_content, _ = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
        if not claims_content:
            await ctx.send("❌ Gagal membaca claims.json.", delete_after=15); return
        try:
            claims_data = json.loads(claims_content)
        except json.JSONDecodeError:
            await ctx.send("❌ Gagal membaca claims.json (file rusak).", delete_after=15); return

        users_to_notify = []
        for key, data in claims_data.items():
            if not key.isdigit(): continue
            user_id_int = int(key)
            
            # Hanya kirim jika user BELUM pernah dinotifikasi
            if 'last_claim_timestamp' in data and user_id_int not in self.cooldown_notified_users:
                try:
                    last_claim_time = datetime.fromisoformat(data['last_claim_timestamp'])
                    next_claim_time = last_claim_time + timedelta(days=7)
                    
                    # Cek jika cooldown sudah berakhir
                    if current_time >= next_claim_time:
                        users_to_notify.append(user_id_int)
                except ValueError:
                     logger.warning(f"Format last_claim_timestamp tidak valid untuk user {key} saat manual notify.")

        if not users_to_notify:
            await ctx.send("ℹ️ Tidak ada pengguna baru yang cooldown-nya berakhir untuk dinotifikasi.", delete_after=15)
            await ctx.message.remove_reaction('⏳', self.bot.user)
            await ctx.message.add_reaction('✅')
            return

        sent_count = 0
        failed_count = 0
        msg = await ctx.send(f"Mengirim notifikasi ke {len(users_to_notify)} pengguna...")
        for user_id in users_to_notify:
             member = self.bot.get_user(user_id)
             if member:
                 try:
                     await member.send("🎉 Cooldown klaim token Anda telah berakhir! Anda sudah bisa melakukan klaim lagi.")
                     self.cooldown_notified_users.add(user_id) # Tandai sudah dinotifikasi
                     sent_count += 1
                     await asyncio.sleep(0.5) # Hindari rate limit DM
                 except discord.Forbidden:
                     logger.warning(f"Gagal kirim DM cooldown berakhir ke user {user_id} (DM ditutup).")
                     failed_count += 1
                 except Exception as e:
                     logger.error(f"Error tidak dikenal saat kirim DM cooldown end ke {user_id}: {e}")
                     failed_count += 1
             else:
                 logger.warning(f"User {user_id} tidak ditemukan untuk notifikasi cooldown.")
        
        await msg.edit(content=f"✅ Selesai. Notifikasi cooldown terkirim ke **{sent_count} pengguna**. Gagal mengirim ke **{failed_count} pengguna**.")
        await ctx.message.remove_reaction('⏳', self.bot.user)
        await ctx.message.add_reaction('✅')


async def setup(bot):
    # Hanya tambahkan view jika belum ada
    if not hasattr(bot, 'claim_view_added') or not bot.claim_view_added:
         bot.add_view(ClaimPanelView(bot))
         bot.claim_view_added = True
         logger.info("ClaimPanelView ditambahkan sebagai persistent view.")
    
    await bot.add_cog(TokenCog(bot))
