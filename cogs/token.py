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
import io

logger = logging.getLogger(__name__)

# =================================================================================
# FUNGSI HELPER (Tetap sama)
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
        logger.error(f"Error saat get file '{file_path}' (Repo: {repo_slug}): {e}")
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
        logger.error(f"Error saat update file '{file_path}' (Repo: {repo_slug}): {e}")
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
# FUNGSI CHECK ADMIN (UNTUK SLASH COMMANDS)
# =================================================================================
async def is_admin_check_slash(interaction: discord.Interaction) -> bool:
    """Pemeriksaan apakah pengguna adalah admin untuk slash commands."""
    bot = interaction.client
    if not hasattr(bot, 'admin_ids'):
        logger.warning("Pengecekan admin slash gagal: tidak dapat mengakses bot.admin_ids.")
        return False
    return interaction.user.id in bot.admin_ids

# =================================================================================
# KELAS PANEL INTERAKTIF (USER-FACING) - Tetap sama
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
            if claims_content is None:
                 await interaction.followup.send("❌ Error: Gagal membaca database klaim (claims.json). Pastikan `PRIMARY_REPO` di .env sudah benar.", ephemeral=True); return
            claims_data = json.loads(claims_content if claims_content else '{}')

            if user_id in claims_data:
                user_claim_info = claims_data[user_id]
                if 'last_claim_timestamp' in user_claim_info:
                    try:
                        last_claim_time = datetime.fromisoformat(user_claim_info['last_claim_timestamp'])
                        if current_time < last_claim_time + timedelta(days=7):
                            next_claim_time = last_claim_time + timedelta(days=7)
                            await interaction.followup.send(f"❌ **Cooldown!** Anda baru bisa klaim lagi <t:{int(next_claim_time.timestamp())}:R>.", ephemeral=True); return
                    except ValueError:
                        logger.warning(f"Format timestamp tidak valid untuk user {user_id}. Mengabaikan cooldown check.")
                
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
            if not token_source_info:
                 await interaction.followup.send(f"❌ Error: Konfigurasi sumber token `{source_alias}` tidak ditemukan. Hubungi admin.", ephemeral=True); return
            
            target_repo_slug, target_file_path = token_source_info["slug"], token_source_info["path"]
            duration_str = self.ROLE_DURATIONS[claim_role]
            
            try: duration_delta = parse_duration(duration_str)
            except ValueError:
                await interaction.followup.send("❌ Kesalahan konfigurasi durasi role. Hubungi admin.", ephemeral=True); return

            new_token = generate_random_token(claim_role)
            expiry_timestamp = current_time + duration_delta
            
            tokens_content, tokens_sha = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
            if tokens_content is None:
                 await interaction.followup.send(f"❌ Error: Gagal membaca file token dari sumber `{source_alias}`. Pastikan `TOKEN_SOURCES` di .env sudah benar.", ephemeral=True); return
            
            new_tokens_content = (tokens_content or "").strip() + f"\n\n{new_token}\n\n"
            token_add_success = update_github_file(target_repo_slug, target_file_path, new_tokens_content, tokens_sha, f"Bot: Add token for {user.name}", self.GITHUB_TOKEN)
            
            if not token_add_success:
                await interaction.followup.send("❌ Gagal membuat token di file sumber. Silakan coba lagi nanti.", ephemeral=True); return

            claims_data[user_id] = {
                "last_claim_timestamp": current_time.isoformat(), 
                "current_token": new_token, 
                "token_expiry_timestamp": expiry_timestamp.isoformat(), 
                "source_alias": source_alias
            }
            claim_db_update_success = update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, f"Bot: Update claim for {user.name}", self.GITHUB_TOKEN)

            if not claim_db_update_success:
                logger.critical(f"KRITIS: Gagal menyimpan claim untuk {user.name}. Melakukan rollback token.")
                current_tokens_content_rb, current_tokens_sha_rb = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
                if current_tokens_content_rb and new_token in current_tokens_content_rb:
                    lines = [line for line in current_tokens_content_rb.split('\n\n') if line.strip() and line.strip() != new_token]
                    content_after_removal = "\n\n".join(lines) + ("\n\n" if lines else "")
                    rollback_success = update_github_file(target_repo_slug, target_file_path, content_after_removal, current_tokens_sha_rb, f"Bot: ROLLBACK token for {user.name}", self.GITHUB_TOKEN)
                    logger.info(f"Status Rollback: {'Berhasil' if rollback_success else 'Gagal'}")
                await interaction.followup.send("❌ **Klaim Gagal!** Terjadi kesalahan saat menyimpan data klaim Anda. Token tidak dapat diberikan. Silakan hubungi admin.", ephemeral=True); return

        # Kirim DM ke pengguna
        try:
            # =================================================================
            # PERUBAHAN DI SINI: Mengganti teks biasa dengan Embed
            # =================================================================
            embed = discord.Embed(
                title="🎉 Token Anda Berhasil Diklaim!",
                description=f"Token Anda untuk role **{claim_role.title()}** telah berhasil dibuat.",
                color=discord.Color.brand_green() # Warna hijau
            )
            embed.add_field(name="Token Anda", value=f"```{new_token}```", inline=False)
            embed.add_field(name="Sumber", value=f"`{source_alias.title()}`", inline=True)
            embed.add_field(name="Aktif Hingga", value=f"<t:{int(expiry_timestamp.timestamp())}:F> (<t:{int(expiry_timestamp.timestamp())}:R>)", inline=True)
            
            # Menambahkan promosi VIP
            embed.add_field(
                name="✨ Mau Token VIP Permanen?",
                value="malas nunggu cooldown dan token vip gratis ga karuan?? langsung <#1413805462129741874> aja.",
                inline=False
            )
            
            embed.set_footer(text="Gunakan token ini untuk mengakses file.")
            embed.timestamp = datetime.now(timezone.utc)
            
            await user.send(embed=embed)
            # =================================================================
            # AKHIR PERUBAHAN
            # =================================================================
            
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
            await interaction.followup.send("❌ Error: Gagal membaca database klaim (claims.json).", ephemeral=True); return
        claims_data = json.loads(claims_content if claims_content else '{}')

        if user_id not in claims_data or not claims_data[user_id]:
            await interaction.followup.send("Anda belum pernah melakukan klaim token atau data Anda kosong.", ephemeral=True); return
        
        user_data = claims_data[user_id]
        embed = discord.Embed(title="📄 Detail Token Anda", color=discord.Color.blue())
        embed.set_thumbnail(url=interaction.user.display_avatar.url) 
        
        # === UPDATE: Tampilkan semua token ===
        active_tokens = []
        if 'tokens' in user_data:
            for idx, token_info in enumerate(user_data['tokens'], 1):
                try:
                    expiry_time = datetime.fromisoformat(token_info["expiry_timestamp"])
                    if expiry_time > current_time:
                        active_tokens.append(
                            f"**Token {idx}:** ```{token_info['token']}```\n"
                            f"Sumber: `{token_info.get('source_alias', 'N/A').title()}`\n"
                            f"Kadaluarsa: <t:{int(expiry_time.timestamp())}:F> (<t:{int(expiry_time.timestamp())}:R>)"
                        )
                except (ValueError, KeyError):
                    continue

        if active_tokens:
            for token_text in active_tokens:
                embed.add_field(name="\u200b", value=token_text, inline=False)
        else:
            embed.description = "Anda tidak memiliki token yang aktif saat ini."

        # Cooldown
        if 'last_claim_timestamp' in user_data:
            try:
                last_claim_time = datetime.fromisoformat(user_data["last_claim_timestamp"])
                next_claim_time = last_claim_time + timedelta(days=7)
                if current_time < next_claim_time:
                    embed.add_field(name="⏳ Cooldown Klaim", value=f"Bisa klaim lagi <t:{int(next_claim_time.timestamp())}:R>", inline=False)
                else:
                    embed.add_field(name="✅ Cooldown Klaim", value="Anda sudah bisa klaim token baru.", inline=False)
            except ValueError:
                embed.add_field(name="Cooldown Klaim", value="Error: Format data tidak valid.", inline=False)
        else:
            embed.add_field(name="✅ Cooldown Klaim", value="Anda bisa klaim token sekarang.", inline=False)

        embed.add_field(
            name="✨ Mau Token VIP Permanen?",
            value="malas nunggu cooldown dan token vip gratis ga karuan?? langsung <#1413805462129741874> aja.",
            inline=False
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

# =================================================================================
# KELAS COG UTAMA (TOKEN) - DIUBAH KE SLASH COMMANDS
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
        
        self.cooldown_notified_users = set()

        self.cleanup_expired_tokens.start()
        logger.info("✅ Token Cog loaded, cleanup task started.")

    def cog_unload(self):
        self.cleanup_expired_tokens.cancel()
        logger.info("🛑 Token Cog unloaded, cleanup task stopped.")

    # --- BACKGROUND TASK ---
    @tasks.loop(hours=1)
    async def cleanup_expired_tokens(self):
        """Tugas otomatis yang berjalan setiap 1 jam."""
        await self._perform_cleanup()

    async def _perform_cleanup(self):
        """Logika inti pembersihan token kedaluwarsa."""
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

            for key in keys_to_process:
                if key.isdigit():
                    user_id_int = int(key)
                    data = claims_data.get(key)
                    if not data: continue

                    if "token_expiry_timestamp" in data and "current_token" in data:
                        try:
                            expiry_time = datetime.fromisoformat(data["token_expiry_timestamp"])
                            if expiry_time < current_time:
                                claims_updated = True
                                token = data.get("current_token")
                                alias = data.get("source_alias")
                                logger.info(f"Token {token} untuk user {key} telah kedaluwarsa.")

                                if token and alias and alias in self.TOKEN_SOURCES:
                                    if alias not in tokens_to_remove_by_source:
                                        tokens_to_remove_by_source[alias] = {"slug": self.TOKEN_SOURCES[alias]["slug"], "path": self.TOKEN_SOURCES[alias]["path"], "tokens": set()}
                                    tokens_to_remove_by_source[alias]["tokens"].add(token)

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

                                member = self.bot.get_user(user_id_int)
                                if member:
                                    try:
                                        embed = discord.Embed(
                                            title="⏳ Token Anda Telah Kedaluwarsa",
                                            description=f"Token Anda (`{token}`) sudah tidak aktif lagi.",
                                            color=discord.Color.orange() # Warna oranye/kuning
                                        )
                                        embed.add_field(
                                            name="Status Cooldown",
                                            value=next_claim_time_str,
                                            inline=False
                                        )
                                        embed.add_field(
                                            name="✨ Mau Lewati Cooldown?",
                                            value="malas nunggu cooldown dan token vip gratis ga karuan?? langsung <#1413805462129741874> aja.",
                                            inline=False
                                        )
                                        embed.set_footer(text="Notifikasi ini dikirim otomatis.")
                                        embed.timestamp = datetime.now(timezone.utc)
                                        
                                        await member.send(embed=embed)
                                        # =================================================================
                                        # AKHIR PERUBAHAN
                                        # =================================================================
                                        
                                        logger.info(f"Mengirim notifikasi token expired ke user {key}.")
                                    except discord.Forbidden:
                                        logger.warning(f"Gagal kirim DM expired ke user {key}.")
                                
                                # Hapus data token dari claims_data
                                data.pop("current_token", None)
                                data.pop("token_expiry_timestamp", None)
                                data.pop("source_alias", None)
                                data.pop("assigned_by_admin", None) # Hapus juga jika ada
                            # Bersihkan token kedaluwarsa dari array tokens[]
                            if 'tokens' in data:
                                data['tokens'] = [
                                    t for t in data['tokens'] 
                                    if datetime.fromisoformat(t['expiry_timestamp']) > current_time
                                ]
                                # Jika array kosong, hapus key
                                if not data['tokens']:
                                    data.pop('tokens', None)
                        except ValueError:
                             logger.warning(f"Format expiry timestamp tidak valid untuk user {key}. Melewati cek expired.")
                
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
                                
                                claims_data.pop(key, None) 
                        except ValueError:
                            logger.warning(f"Format expiry timestamp tidak valid untuk shared token {key}.")

            if claims_updated:
                for alias, info in tokens_to_remove_by_source.items():
                    content, sha = get_github_file(info["slug"], info["path"], self.GITHUB_TOKEN)
                    if content:
                        lines = content.split('\n\n')
                        initial_count = len([l for l in lines if l.strip()])
                        new_lines = [line for line in lines if line.strip() and line.strip() not in info["tokens"]]
                        final_count = len(new_lines)
                        
                        if initial_count != final_count:
                            new_content = "\n\n".join(new_lines) + ("\n\n" if new_lines else "")
                            if update_github_file(info["slug"], info["path"], new_content, sha, f"Bot: Hapus {initial_count - final_count} token kedaluwarsa otomatis", self.GITHUB_TOKEN):
                                logger.info(f"{initial_count - final_count} token kedaluwarsa dihapus dari sumber: {alias}")
                            else:
                                 logger.error(f"Gagal menghapus token kedaluwarsa dari sumber: {alias}")

                if update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, "Bot: Bersihkan data klaim token kedaluwarsa", self.GITHUB_TOKEN):
                    logger.info("Pembersihan data token kedaluwarsa di claims.json selesai.")
                else:
                    logger.error("Gagal update claims.json setelah membersihkan token kedaluwarsa.")
            else:
                 logger.info("Tidak ada token kedaluwarsa yang perlu dibersihkan.")

    @cleanup_expired_tokens.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()
        logger.info("Background task 'cleanup_expired_tokens' siap.")
        

    # --- SLASH COMMANDS (ADMIN) ---

    @app_commands.command(name="open_claim", description="[ADMIN] Membuka sesi klaim untuk sumber token tertentu")
    @app_commands.describe(alias="Alias sumber token (contoh: github, vip, premium)")
    @app_commands.check(is_admin_check_slash)
    async def open_claim_slash(self, interaction: discord.Interaction, alias: str):
        alias_lower = alias.lower()
        if alias_lower not in self.TOKEN_SOURCES:
            await interaction.response.send_message(f"❌ Alias `{alias}` tidak valid. Cek .env `TOKEN_SOURCES`.", ephemeral=True)
            return
        if not self.CLAIM_CHANNEL_ID or not (claim_channel := self.bot.get_channel(self.CLAIM_CHANNEL_ID)):
            await interaction.response.send_message(f"❌ `CLAIM_CHANNEL_ID` tidak valid atau channel tidak ditemukan.", ephemeral=True)
            return

        if self.bot.close_claim_message:
            try: await self.bot.close_claim_message.delete()
            except discord.HTTPException: pass
            finally: self.bot.close_claim_message = None

        self.bot.current_claim_source_alias = alias_lower
        embed = discord.Embed(title=f"📝 Sesi Klaim Dibuka: {alias.title()}", description=f"Sesi klaim untuk sumber `{alias.title()}` telah dibuka oleh {interaction.user.mention}.", color=discord.Color.green())
        try:
            self.bot.open_claim_message = await claim_channel.send(embed=embed, view=ClaimPanelView(self.bot))
            await interaction.response.send_message(f"✅ Panel klaim untuk `{alias.title()}` dikirim ke {claim_channel.mention}.", ephemeral=True)
        except discord.Forbidden:
             await interaction.response.send_message(f"❌ Bot tidak punya izin mengirim pesan/view di {claim_channel.mention}.", ephemeral=True)
        except Exception as e:
             logger.error(f"Error saat mengirim panel klaim: {e}")
             await interaction.response.send_message(f"❌ Terjadi error saat mengirim panel: {e}", ephemeral=True)

    @app_commands.command(name="close_claim", description="[ADMIN] Menutup sesi klaim dan mengirim notifikasi")
    @app_commands.check(is_admin_check_slash)
    async def close_claim_slash(self, interaction: discord.Interaction):
        if not self.bot.current_claim_source_alias:
            await interaction.response.send_message("ℹ️ Tidak ada sesi klaim yang sedang aktif.", ephemeral=True)
            return
            
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
                embed_closed = discord.Embed(title="🔴 Sesi Klaim Ditutup", description=f"Admin ({interaction.user.mention}) telah menutup sesi klaim untuk `{closed_alias.title()}`.", color=discord.Color.red())
                self.bot.close_claim_message = await claim_channel.send(embed=embed_closed)
            except discord.Forbidden:
                 logger.warning(f"Gagal mengirim pesan notifikasi penutupan ke channel {self.CLAIM_CHANNEL_ID}.")
        
        await interaction.response.send_message(f"🔴 Sesi klaim untuk `{closed_alias.title()}` telah ditutup.", ephemeral=True)

    @app_commands.command(name="cleanup_expired", description="[ADMIN] Hapus semua token kedaluwarsa SEKARANG (tanpa menunggu 1 jam)")
    @app_commands.check(is_admin_check_slash)
    async def cleanup_expired_manual(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self._perform_cleanup()
        await interaction.followup.send("✅ Pembersihan token kedaluwarsa selesai dilakukan secara manual.", ephemeral=True)

    @app_commands.command(name="add_token", description="[ADMIN] Menambahkan token custom ke sumber file")
    @app_commands.describe(alias="Alias sumber token", token="Token yang akan ditambahkan")
    @app_commands.check(is_admin_check_slash)
    async def add_token_slash(self, interaction: discord.Interaction, alias: str, token: str):
        alias_lower = alias.lower()
        source_info = self.TOKEN_SOURCES.get(alias_lower)
        if not source_info:
            await interaction.response.send_message(f"❌ Alias `{alias}` tidak valid.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.github_lock:
            content, sha = get_github_file(source_info["slug"], source_info["path"], self.GITHUB_TOKEN)
            if content is None:
                 await interaction.followup.send(f"❌ Gagal membaca file token dari `{alias}`. Cek .env `TOKEN_SOURCES`.", ephemeral=True)
                 return
            if token in (content or ""):
                await interaction.followup.send(f"⚠️ Token `{token}` sudah ada di `{alias}`.", ephemeral=True)
                return
            
            new_content = (content or "").strip() + f"\n\n{token}\n\n"
            if update_github_file(source_info["slug"], source_info["path"], new_content, sha, f"Admin {interaction.user.name}: Add custom token {token}", self.GITHUB_TOKEN):
                await interaction.followup.send(f"✅ Token `{token}` ditambahkan ke `{alias}`.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Gagal menambahkan token ke `{alias}` di GitHub.", ephemeral=True)

    @app_commands.command(name="remove_token", description="[ADMIN] Menghapus token dari sumber file")
    @app_commands.describe(alias="Alias sumber token", token="Token yang akan dihapus")
    @app_commands.check(is_admin_check_slash)
    async def remove_token_slash(self, interaction: discord.Interaction, alias: str, token: str):
        alias_lower = alias.lower()
        source_info = self.TOKEN_SOURCES.get(alias_lower)
        if not source_info:
            await interaction.response.send_message(f"❌ Alias `{alias}` tidak valid.", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.github_lock:
            content, sha = get_github_file(source_info["slug"], source_info["path"], self.GITHUB_TOKEN)
            if content is None:
                 await interaction.followup.send(f"❌ Gagal membaca file token dari `{alias}`.", ephemeral=True)
                 return
            if not content or token not in content:
                await interaction.followup.send(f"❌ Token `{token}` tidak ditemukan di `{alias}`.", ephemeral=True)
                return
                
            lines = [line for line in content.split('\n\n') if line.strip() and line.strip() != token]
            new_content = "\n\n".join(lines) + ("\n\n" if lines else "")

            if new_content != content:
                if update_github_file(source_info["slug"], source_info["path"], new_content, sha, f"Admin {interaction.user.name}: Remove token {token}", self.GITHUB_TOKEN):
                    await interaction.followup.send(f"✅ Token `{token}` dihapus dari `{alias}`.", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Gagal menghapus token dari `{alias}` di GitHub.", ephemeral=True)
            else:
                 await interaction.followup.send(f"ℹ️ Token `{token}` tidak ditemukan (mungkin sudah dihapus).", ephemeral=True)

    @app_commands.command(name="add_shared", description="[ADMIN] Menambah token umum dengan durasi")
    @app_commands.describe(alias="Alias sumber token", token="Token yang akan ditambahkan", durasi="Durasi aktif (contoh: 7d, 24h, 30m)")
    @app_commands.check(is_admin_check_slash)
    async def add_shared_token_slash(self, interaction: discord.Interaction, alias: str, token: str, durasi: str):
        alias_lower = alias.lower()
        source_info = self.TOKEN_SOURCES.get(alias_lower)
        if not source_info:
            await interaction.response.send_message(f"❌ Alias `{alias}` tidak valid.", ephemeral=True)
            return
        try:
            duration_delta = parse_duration(durasi)
            if duration_delta <= timedelta(0):
                 await interaction.response.send_message(f"❌ Durasi harus positif.", ephemeral=True)
                 return
        except ValueError as e:
            await interaction.response.send_message(f"❌ Format durasi tidak valid: {e}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.github_lock:
            target_repo_slug, target_file_path = source_info["slug"], source_info["path"]
            
            tokens_content, tokens_sha = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
            if tokens_content is None:
                 await interaction.followup.send(f"❌ Gagal membaca file token dari `{alias}`.", ephemeral=True)
                 return
            if token in (tokens_content or ""):
                await interaction.followup.send(f"⚠️ Token `{token}` sudah ada di file sumber `{alias}`. Tidak ditambahkan ulang.", ephemeral=True)
                return
                
            new_tokens_content = (tokens_content or "").strip() + f"\n\n{token}\n\n"
            token_add_success = update_github_file(target_repo_slug, target_file_path, new_tokens_content, tokens_sha, f"Admin {interaction.user.name}: Add shared token {token}", self.GITHUB_TOKEN)
            if not token_add_success:
                await interaction.followup.send("❌ Gagal menambahkan token ke file sumber GitHub. Operasi dibatalkan.", ephemeral=True)
                return

            _, tokens_sha_after_add = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)

            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            if claims_content is None:
                 await interaction.followup.send("❌ Gagal membaca database klaim (claims.json).", ephemeral=True)
                 return
            claims_data = json.loads(claims_content if claims_content else '{}')
            claim_key = f"shared_{alias_lower}_{token}"

            if claim_key in claims_data:
                logger.warning(f"Data untuk token shared '{token}' di '{alias}' sudah ada di claims.json.")
                await interaction.followup.send(f"⚠️ Data untuk token `{token}` sudah ada di database klaim. Token tetap ada di file sumber.", ephemeral=True)
                return
                
            current_time = datetime.now(timezone.utc)
            expiry_time = current_time + duration_delta
            claims_data[claim_key] = {
                "current_token": token, 
                "token_expiry_timestamp": expiry_time.isoformat(), 
                "source_alias": alias_lower, 
                "is_shared": True
            }
            claim_db_update_success = update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, f"Admin {interaction.user.name}: Add data for shared token {token}", self.GITHUB_TOKEN)
            
            if not claim_db_update_success:
                logger.critical(f"KRITIS: Gagal menyimpan data klaim untuk token shared '{token}'. Melakukan rollback dari file sumber.")
                current_tokens_content_rb, current_tokens_sha_rb = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
                if current_tokens_content_rb and token in current_tokens_content_rb:
                    lines = [line for line in current_tokens_content_rb.split('\n\n') if line.strip() and line.strip() != token]
                    content_after_removal = "\n\n".join(lines) + ("\n\n" if lines else "")
                    rollback_success = update_github_file(target_repo_slug, target_file_path, content_after_removal, tokens_sha_after_add, f"Admin {interaction.user.name}: ROLLBACK shared token {token}", self.GITHUB_TOKEN)
                    logger.info(f"Status Rollback shared token '{token}': {'Berhasil' if rollback_success else 'Gagal'}")
                await interaction.followup.send("❌ Gagal menyimpan data token ke database klaim. Token di file sumber telah dihapus kembali (rollback).", ephemeral=True)
                return

        await interaction.followup.send(f"✅ Token `{token}` ditambahkan ke `{alias}`. Akan aktif hingga <t:{int(expiry_time.timestamp())}:F> (<t:{int(expiry_time.timestamp())}:R>).", ephemeral=True)

    @app_commands.command(name="give_token", description="[ADMIN] Berikan token ke user (bisa lebih dari 1)")
    @app_commands.describe(user="User yang akan menerima token", alias="Alias sumber token", token="Token yang diberikan", durasi="Durasi aktif (contoh: 7d, 24h)")
    @app_commands.check(is_admin_check_slash)
    async def give_token_slash(self, interaction: discord.Interaction, user: discord.Member, alias: str, token: str, durasi: str):
        admin = interaction.user
        alias_lower = alias.lower()

        source_info = self.TOKEN_SOURCES.get(alias_lower)
        if not source_info:
            await interaction.response.send_message(f"❌ Alias `{alias}` tidak valid.", ephemeral=True)
            return
        try:
            duration_delta = parse_duration(durasi)
            if duration_delta <= timedelta(0):
                await interaction.response.send_message(f"❌ Durasi harus positif.", ephemeral=True)
                return
        except ValueError as e:
            await interaction.response.send_message(f"❌ Format durasi tidak valid: {e}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.github_lock:
            target_repo_slug, target_file_path = source_info["slug"], source_info["path"]
            
            tokens_content, tokens_sha = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
            if tokens_content is None:
                await interaction.followup.send(f"❌ Gagal membaca file token dari `{alias}`.", ephemeral=True)
                return

            token_add_success = True
            token_was_added_now = False

            if token not in (tokens_content or ""):
                logger.info(f"Admin {admin.name} menambahkan token baru '{token}' ke source '{alias}' via give_token.")
                new_tokens_content = (tokens_content or "").strip() + f"\n\n{token}\n\n"
                token_add_success = update_github_file(target_repo_slug, target_file_path, new_tokens_content, tokens_sha, f"Admin {admin.name}: Add token {token} via give_token", self.GITHUB_TOKEN)
                token_was_added_now = token_add_success
            
            if not token_add_success:
                await interaction.followup.send("❌ Gagal menambahkan token ke file sumber GitHub. Operasi dibatalkan.", ephemeral=True)
                return

            tokens_sha_after_add = tokens_sha
            if token_was_added_now:
                _, tokens_sha_after_add = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)

            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            if claims_content is None:
                await interaction.followup.send("❌ Gagal membaca database klaim (claims.json).", ephemeral=True)
                return
            claims_data = json.loads(claims_content if claims_content else '{}')
            user_id_str = str(user.id)
            
            current_time = datetime.now(timezone.utc)
            expiry_time = current_time + duration_delta
            
            # === PERUBAHAN: Support Multi-Token ===
            if user_id_str not in claims_data:
                claims_data[user_id_str] = {}
            
            # Inisialisasi list tokens jika belum ada
            if 'tokens' not in claims_data[user_id_str]:
                claims_data[user_id_str]['tokens'] = []
            
            # Tambahkan token baru ke list
            claims_data[user_id_str]['tokens'].append({
                "token": token,
                "expiry_timestamp": expiry_time.isoformat(),
                "source_alias": alias_lower,
                "assigned_by_admin": admin.id
            })
            
            # Tetap simpan info untuk kompatibilitas backward (token terakhir)
            claims_data[user_id_str].update({
                "current_token": token,
                "token_expiry_timestamp": expiry_time.isoformat(),
                "source_alias": alias_lower,
                "assigned_by_admin": admin.id
            })
            # === AKHIR PERUBAHAN ===
            
            claim_db_update_success = update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, f"Admin {admin.name}: Assign token {token} to {user.name}", self.GITHUB_TOKEN)
            
            if not claim_db_update_success:
                await interaction.followup.send(f"❌ Gagal menyimpan data pemberian token untuk {user.mention} ke database klaim. Memulai rollback...", ephemeral=True)
                
                if token_was_added_now:
                    logger.critical(f"KRITIS: Gagal menyimpan data klaim untuk admin_give_token {user.name}. Melakukan rollback dari file sumber.")
                    current_tokens_content_rb, current_tokens_sha_rb = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
                    
                    sha_for_rollback = current_tokens_sha_rb if current_tokens_sha_rb else tokens_sha_after_add

                    if current_tokens_content_rb and token in current_tokens_content_rb:
                        lines = [line for line in current_tokens_content_rb.split('\n\n') if line.strip() and line.strip() != token]
                        content_after_removal = "\n\n".join(lines) + ("\n\n" if lines else "")
                        rollback_success = update_github_file(target_repo_slug, target_file_path, content_after_removal, sha_for_rollback, f"Admin {admin.name}: ROLLBACK admin_give_token {token}", self.GITHUB_TOKEN)
                        logger.info(f"Status Rollback admin_give_token '{token}': {'Berhasil' if rollback_success else 'Gagal'}")
                        await interaction.followup.send(f"ℹ️ Rollback token `{token}` dari file sumber: {'Berhasil' if rollback_success else 'Gagal'}.", ephemeral=True)
                    else:
                        logger.error(f"Gagal rollback admin_give_token: Token '{token}' tidak ditemukan di konten terbaru.")
                        await interaction.followup.send(f"ℹ️ Gagal rollback, token `{token}` tidak ditemukan di file sumber.", ephemeral=True)
                else:
                    logger.warning(f"Gagal menyimpan data klaim untuk admin_give_token {user.name}, tapi token sudah ada di file sumber sebelumnya (tidak ada rollback).")
                    await interaction.followup.send(f"ℹ️ Token sudah ada di file sumber sebelumnya (tidak ada rollback).", ephemeral=True)
                return

        # === PERBAIKAN ERROR: Ganti ctx dengan interaction.followup ===
        try:
            # Hitung total token aktif user
            total_tokens = len(claims_data[user_id_str].get('tokens', []))
            
            embed = discord.Embed(
                title="🎁 Token Diberikan oleh Admin!",
                description=f"Anda telah diberikan token oleh {admin.mention}.",
                color=discord.Color.brand_green()
            )
            embed.add_field(name="Token Anda", value=f"```{token}```", inline=False)
            embed.add_field(name="Sumber", value=f"`{alias.title()}`", inline=True)
            embed.add_field(name="Aktif Hingga", value=f"<t:{int(expiry_time.timestamp())}:F> (<t:{int(expiry_time.timestamp())}:R>)", inline=True)
            embed.add_field(name="Total Token Aktif", value=f"🔑 **{total_tokens} token**", inline=False)
            embed.add_field(
                name="✨ Mau Token VIP Permanen?",
                value="malas nunggu cooldown dan token vip gratis ga karuan?? langsung <#1413805462129741874> aja.",
                inline=False
            )
            embed.set_footer(text="Catatan: Pemberian token ini tidak memengaruhi cooldown klaim normal Anda.")
            embed.timestamp = datetime.now(timezone.utc)

            await user.send(embed=embed)
            logger.info(f"Admin {admin.name} berhasil memberikan token {token} ke {user.name}. DM terkirim.")
            await interaction.followup.send(f"✅ Token `{token}` berhasil diberikan kepada {user.mention} selama `{durasi}`. Total token aktif: **{total_tokens}**. Notifikasi DM telah dikirim.", ephemeral=True)
        except discord.Forbidden:
            logger.warning(f"Gagal mengirim DM pemberian token ke {user.name} ({user.id}). Token tetap diberikan.")
            await interaction.followup.send(f"✅ Token `{token}` berhasil diberikan kepada {user.mention}, namun gagal mengirim notifikasi DM.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error tidak dikenal saat kirim DM pemberian token: {e}")
            await interaction.followup.send(f"✅ Token `{token}` berhasil diberikan kepada {user.mention}, namun gagal mengirim notifikasi DM karena error.", ephemeral=True)

    @app_commands.command(name="read_file", description="[ADMIN] Membaca konten file dari sumber token (kirim via DM)")
    @app_commands.describe(alias="Alias sumber token")
    @app_commands.check(is_admin_check_slash)
    async def read_file_slash(self, interaction: discord.Interaction, alias: str):
        alias_lower = alias.lower()
        source_info = self.TOKEN_SOURCES.get(alias_lower)
        if not source_info:
            await interaction.response.send_message(f"❌ Alias `{alias}` tidak valid.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        content, _ = get_github_file(source_info["slug"], source_info["path"], self.GITHUB_TOKEN)
        
        if content is None:
            await interaction.followup.send(f"❌ File `{source_info['path']}` tidak ditemukan di repo `{source_info['slug']}`.", ephemeral=True)
            return
        if not content.strip():
             await interaction.followup.send(f"ℹ️ File `{alias}` kosong.", ephemeral=True)
             return
            
        try:
            if len(content) > 1900:
                file = discord.File(io.StringIO(content), filename=f"{alias_lower}_content.txt")
                await interaction.user.send(f"📄 Konten dari `{alias}` (terlalu panjang, dikirim sebagai file):", file=file)
            else:
                embed = discord.Embed(title=f"📄 Konten dari `{alias}`", description=f"```\n{content}\n```", color=discord.Color.blue())
                embed.set_footer(text=f"Repo: {source_info['slug']}, File: {source_info['path']}")
                await interaction.user.send(embed=embed)
            
            await interaction.followup.send(f"✅ Hasil konten file `{alias}` telah dikirim ke DM Anda.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Gagal mengirim DM. Pastikan DM Anda terbuka.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Gagal mengirim file: {e}", ephemeral=True)

    @app_commands.command(name="reset_user", description="[ADMIN] Mereset cooldown & token aktif user")
    @app_commands.describe(user="User yang akan direset")
    @app_commands.check(is_admin_check_slash)
    async def reset_user_slash(self, interaction: discord.Interaction, user: discord.Member):
        user_id_str = str(user.id)
        admin = interaction.user
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.bot.github_lock:
            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            if claims_content is None:
                 await interaction.followup.send("❌ Gagal membaca database klaim (claims.json).", ephemeral=True)
                 return
            claims_data = json.loads(claims_content if claims_content else '{}')
            
            if user_id_str not in claims_data or not claims_data[user_id_str]:
                await interaction.followup.send(f"ℹ️ {user.mention} tidak memiliki data klaim.", ephemeral=True)
                return
            
            claims_data[user_id_str] = {}
                
            if update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, f"Admin {admin.name}: Reset data for {user.name}", self.GITHUB_TOKEN):
                logger.info(f"Admin {admin.name} mereset data klaim untuk {user.name} ({user_id_str}).")
                
                try:
                    embed = discord.Embed(
                        title="⚙️ Data Klaim Telah Direset",
                        description=f"Data klaim token Anda telah direset oleh admin {admin.mention}.",
                        color=discord.Color.orange() # Warna oranye/kuning
                    )
                    embed.add_field(
                        name="Status",
                        value="Token aktif (jika ada) dan cooldown klaim Anda telah dihapus."
                    )
                    embed.add_field(
                        name="✨ Mau Token VIP Permanen?",
                        value="malas nunggu cooldown dan token vip gratis ga karuan?? langsung <#1413805462129741874> aja.",
                        inline=False
                    )
                    embed.set_footer(text="Anda sekarang dapat melakukan klaim token baru.")
                    embed.timestamp = datetime.now(timezone.utc)

                    await user.send(embed=embed)
                    
                    await ctx.send(f"✅ Data klaim untuk {user.mention} berhasil direset. Notifikasi DM terkirim.", delete_after=15)
                except discord.Forbidden:
                     await ctx.send(f"✅ Data klaim untuk {user.mention} berhasil direset, namun gagal mengirim notifikasi DM.", delete_after=15)
                if user.id in self.cooldown_notified_users:
                    self.cooldown_notified_users.remove(user.id)
            else:
                await interaction.followup.send(f"❌ Gagal mereset data untuk {user.mention} di GitHub.", ephemeral=True)

    @app_commands.command(name="check_user", description="[ADMIN] Memeriksa status token/cooldown user")
    @app_commands.describe(user="User yang akan diperiksa")
    @app_commands.check(is_admin_check_slash)
    async def check_user_slash(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        claims_content, _ = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
        if claims_content is None:
            await interaction.followup.send("❌ Gagal membaca database klaim (claims.json).", ephemeral=True)
            return
        claims_data = json.loads(claims_content if claims_content else '{}')
        user_id_str = str(user.id)
        current_time = datetime.now(timezone.utc)

        if user_id_str not in claims_data or not claims_data[user_id_str]:
            await interaction.followup.send(f"**{user.display_name}** tidak memiliki data klaim.", ephemeral=True)
            return
        
        user_data = claims_data[user_id_str]
        embed = discord.Embed(title=f"🔍 Status Token - {user.display_name}", color=discord.Color.orange())
        embed.set_thumbnail(url=user.display_avatar.url)
        
        # === UPDATE: Tampilkan semua token aktif ===
        active_tokens = []
        if 'tokens' in user_data:
            for idx, token_info in enumerate(user_data['tokens'], 1):
                try:
                    expiry_time = datetime.fromisoformat(token_info["expiry_timestamp"])
                    if expiry_time > current_time:
                        active_tokens.append(
                            f"**{idx}.** `{token_info['token']}`\n"
                            f"   └ Sumber: `{token_info.get('source_alias', 'N/A').title()}`\n"
                            f"   └ Kadaluarsa: <t:{int(expiry_time.timestamp())}:R>"
                        )
                except (ValueError, KeyError):
                    continue
        
        if active_tokens:
            tokens_text = "\n\n".join(active_tokens)
            embed.add_field(name=f"🔑 Token Aktif ({len(active_tokens)})", value=tokens_text, inline=False)
        else:
            embed.description = "Pengguna tidak memiliki token aktif saat ini."
        
        # Cooldown info
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
            if not active_tokens:
                embed.add_field(name="Cooldown Klaim", value="✅ Bisa klaim (belum pernah klaim normal / sudah direset)", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="revoke_token", description="[ADMIN] Cabut token spesifik dari user")
    @app_commands.describe(user="User target", token="Token yang akan dicabut")
    @app_commands.check(is_admin_check_slash)
    async def revoke_token_slash(self, interaction: discord.Interaction, user: discord.Member, token: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        admin = interaction.user
        user_id_str = str(user.id)
        
        async with self.bot.github_lock:
            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            if claims_content is None:
                await interaction.followup.send("❌ Gagal membaca claims.json.", ephemeral=True); return
            claims_data = json.loads(claims_content if claims_content else '{}')
            
            if user_id_str not in claims_data or 'tokens' not in claims_data[user_id_str]:
                await interaction.followup.send(f"❌ {user.mention} tidak memiliki token.", ephemeral=True); return
            
            # Cari dan hapus token
            original_count = len(claims_data[user_id_str]['tokens'])
            claims_data[user_id_str]['tokens'] = [
                t for t in claims_data[user_id_str]['tokens'] 
                if t['token'] != token
            ]
            new_count = len(claims_data[user_id_str]['tokens'])
            
            if original_count == new_count:
                await interaction.followup.send(f"❌ Token `{token}` tidak ditemukan pada {user.mention}.", ephemeral=True); return
            
            # Update current_token jika yang dicabut adalah current
            if claims_data[user_id_str].get('current_token') == token:
                if claims_data[user_id_str]['tokens']:
                    latest = claims_data[user_id_str]['tokens'][-1]
                    claims_data[user_id_str]['current_token'] = latest['token']
                    claims_data[user_id_str]['token_expiry_timestamp'] = latest['expiry_timestamp']
                    claims_data[user_id_str]['source_alias'] = latest['source_alias']
                else:
                    claims_data[user_id_str].pop('current_token', None)
                    claims_data[user_id_str].pop('token_expiry_timestamp', None)
            
            if not claims_data[user_id_str]['tokens']:
                claims_data[user_id_str].pop('tokens', None)
            
            if update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, f"Admin {admin.name}: Revoke token {token} from {user.name}", self.GITHUB_TOKEN):
                await interaction.followup.send(f"✅ Token `{token}` berhasil dicabut dari {user.mention}. Sisa: {new_count} token.", ephemeral=True)
                try:
                    await user.send(f"⚠️ Token `{token}` Anda telah dicabut oleh admin {admin.mention}.")
                except: pass
            else:
                await interaction.followup.send("❌ Gagal update claims.json.", ephemeral=True)

    @app_commands.command(name="token_stats", description="[ADMIN] Statistik token sistem")
    @app_commands.check(is_admin_check_slash)
    async def token_stats_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        claims_content, _ = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
        if not claims_content:
            await interaction.followup.send("❌ Gagal membaca claims.json.", ephemeral=True); return
        claims_data = json.loads(claims_content)
        current_time = datetime.now(timezone.utc)
        
        total_users = len([k for k in claims_data.keys() if k.isdigit()])
        total_active_tokens = 0
        total_expired_tokens = 0
        tokens_by_source = {}
        
        for key, data in claims_data.items():
            if key.isdigit() and 'tokens' in data:
                for token_info in data['tokens']:
                    try:
                        expiry = datetime.fromisoformat(token_info['expiry_timestamp'])
                        source = token_info.get('source_alias', 'unknown')
                        
                        if expiry > current_time:
                            total_active_tokens += 1
                            tokens_by_source[source] = tokens_by_source.get(source, 0) + 1
                        else:
                            total_expired_tokens += 1
                    except: pass
        
        embed = discord.Embed(title="📊 Statistik Token Sistem", color=discord.Color.gold())
        embed.add_field(name="👥 Total User Terdaftar", value=f"`{total_users}` user", inline=True)
        embed.add_field(name="🔑 Token Aktif", value=f"`{total_active_tokens}` token", inline=True)
        embed.add_field(name="⏳ Token Kedaluwarsa", value=f"`{total_expired_tokens}` token", inline=True)
        
        if tokens_by_source:
            source_text = "\n".join([f"• **{src.title()}**: {count} token" for src, count in tokens_by_source.items()])
            embed.add_field(name="📂 Token per Sumber", value=source_text, inline=False)
        
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="list_tokens", description="[ADMIN] Menampilkan semua token aktif")
    @app_commands.check(is_admin_check_slash)
    async def list_tokens_slash(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Perintah ini harus dijalankan di dalam server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        claims_content, _ = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
        if claims_content is None:
             await interaction.followup.send("❌ Gagal membaca database klaim (claims.json).", ephemeral=True)
             return
        claims_data = json.loads(claims_content if claims_content else '{}')
        if not claims_data:
            await interaction.followup.send("Database klaim kosong.", ephemeral=True)
            return

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
             await interaction.followup.send("Tidak ada token yang sedang aktif.", ephemeral=True)
             return

        embed = discord.Embed(title="🔑 Daftar Token Aktif", color=discord.Color.blue())
        description_part = ""
        for item in active_tokens_list:
            if len(description_part) + len(item) + 2 > 4000:
                embed.description = description_part
                await interaction.followup.send(embed=embed, ephemeral=True)
                embed = discord.Embed(title="🔑 Daftar Token Aktif (Lanjutan)", color=discord.Color.blue())
                description_part = item + "\n"
            else:
                description_part += item + "\n"
        
        embed.description = description_part
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="show_config", description="[ADMIN] Menampilkan konfigurasi channel & repo")
    @app_commands.check(is_admin_check_slash)
    async def show_config_slash(self, interaction: discord.Interaction):
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
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="serverlist", description="[ADMIN] Menampilkan daftar server bot")
    @app_commands.check(is_admin_check_slash)
    async def serverlist_slash(self, interaction: discord.Interaction):
        server_list = [f"- **{guild.name}** (ID: `{guild.id}` | Members: {guild.member_count})" 
                       for guild in self.bot.guilds]
        allowed_status = {guild.id: ("✅ Diizinkan" if guild.id in self.bot.config.ALLOWED_GUILD_IDS else "❌ Tidak Diizinkan") 
                          for guild in self.bot.guilds}
        
        description = "\n".join(f"{s} - {allowed_status.get(int(s.split('`')[1]), 'N/A')}" for s in server_list)

        embed = discord.Embed(title=f"Bot Aktif di {len(self.bot.guilds)} Server", 
                              description=description, 
                              color=0x3498db)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="notify_cooldowns", description="[ADMIN] Kirim notifikasi DM ke user yang cooldownnya selesai")
    @app_commands.check(is_admin_check_slash)
    async def notify_cooldowns_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        current_time = datetime.now(timezone.utc)
        
        claims_content, _ = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
        if not claims_content:
            await interaction.followup.send("❌ Gagal membaca claims.json.", ephemeral=True)
            return
        try:
            claims_data = json.loads(claims_content)
        except json.JSONDecodeError:
            await interaction.followup.send("❌ Gagal membaca claims.json (file rusak).", ephemeral=True)
            return

        users_to_notify = []
        for key, data in claims_data.items():
            if not key.isdigit(): continue
            user_id_int = int(key)
            
            if 'last_claim_timestamp' in data and user_id_int not in self.cooldown_notified_users:
                try:
                    last_claim_time = datetime.fromisoformat(data['last_claim_timestamp'])
                    next_claim_time = last_claim_time + timedelta(days=7)
                    
                    if current_time >= next_claim_time:
                        users_to_notify.append(user_id_int)
                except ValueError:
                     logger.warning(f"Format last_claim_timestamp tidak valid untuk user {key} saat manual notify.")

        if not users_to_notify:
            await interaction.followup.send("ℹ️ Tidak ada pengguna baru yang cooldown-nya berakhir untuk dinotifikasi.", ephemeral=True)
            return

        sent_count = 0
        failed_count = 0
        # Menggunakan interaction.edit_original_response nanti, jadi followup.send tidak perlu disimpan
        await interaction.followup.send(f"Mengirim notifikasi ke {len(users_to_notify)} pengguna...", ephemeral=True)
        
        for user_id in users_to_notify:
             member = self.bot.get_user(user_id)
             if member:
                 try:
                    embed = discord.Embed(
                        title="🎉 Cooldown Klaim Selesai",
                        description="Cooldown klaim token Anda telah berakhir! Anda sudah bisa melakukan klaim lagi.",
                        color=discord.Color.green()
                    )
                    embed.add_field(
                        name="Mau Lewati Cooldown?",
                        value="malas nunggu cooldown dan token vip gratis ga karuan?? langsung <#1413805462129741874> aja."
                    )
                    embed.set_footer(text="Notifikasi ini dikirim otomatis.")
                    
                    await member.send(embed=embed)
                    self.cooldown_notified_users.add(user_id)
                    sent_count += 1
                    await asyncio.sleep(0.5)
                 except discord.Forbidden:
                     logger.warning(f"Gagal kirim DM cooldown berakhir ke user {user_id} (DM ditutup).")
                     failed_count += 1
                 except Exception as e:
                     logger.error(f"Error tidak dikenal saat kirim DM cooldown end ke {user_id}: {e}")
                     failed_count += 1
             else:
                 logger.warning(f"User {user_id} tidak ditemukan untuk notifikasi cooldown.")
        await interaction.edit_original_response(content=f"✅ Selesai. Notifikasi cooldown terkirim ke **{sent_count} pengguna**. Gagal mengirim ke **{failed_count} pengguna**.")

    @app_commands.command(name="list_sources", description="[ADMIN] Lihat semua sumber token terkonfigurasi")
    @app_commands.check(is_admin_check_slash)
    async def list_sources_slash(self, interaction: discord.Interaction):
        if not self.TOKEN_SOURCES:
            await interaction.response.send_message("❌ Tidak ada sumber token yang dikonfigurasi.", ephemeral=True)
            return
        
        embed = discord.Embed(title="📂 Daftar Sumber Token", color=discord.Color.green())
        for alias, info in self.TOKEN_SOURCES.items():
            embed.add_field(
                name=f"🔹 {alias.upper()}", 
                value=f"**Repo:** `{info['slug']}`\n**File:** `{info['path']}`", 
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    if not hasattr(bot, 'claim_view_added') or not bot.claim_view_added:
         bot.add_view(ClaimPanelView(bot))
         bot.claim_view_added = True
         logger.info("ClaimPanelView ditambahkan sebagai persistent view.")
    
    await bot.add_cog(TokenCog(bot))
