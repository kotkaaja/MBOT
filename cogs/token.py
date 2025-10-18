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

logger = logging.getLogger(__name__)

# =================================================================================
# FUNGSI HELPER (DARI SCRIPT ASLI)
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
        logger.error(f"Error saat get file '{file_path}': {e}")
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
        logger.info(f"File '{file_path}' berhasil diupdate: {commit_message}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error saat update file '{file_path}': {e}")
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
# KELAS PANEL INTERAKTIF
# =================================================================================

class ClaimPanelView(ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance
        # Mengambil konstanta dari config bot
        self.ROLE_DURATIONS = bot_instance.config.ROLE_DURATIONS
        self.ROLE_PRIORITY = bot_instance.config.ROLE_PRIORITY
        self.TOKEN_SOURCES = bot_instance.config.TOKEN_SOURCES
        self.PRIMARY_REPO = bot_instance.config.PRIMARY_REPO
        self.CLAIMS_FILE_PATH = bot_instance.config.CLAIMS_FILE_PATH
        self.GITHUB_TOKEN = bot_instance.config.GITHUB_TOKEN

    @ui.button(label="Claim Token", style=discord.ButtonStyle.success, custom_id="claim_token_button")
    async def claim_button_callback(self, interaction: discord.Interaction, button: ui.Button):
        if not self.bot.current_claim_source_alias:
            await interaction.response.send_message("❌ Sesi klaim saat ini sedang ditutup oleh admin.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        user, user_id, current_time = interaction.user, str(interaction.user.id), datetime.now(timezone.utc)
        
        async with self.bot.github_lock:
            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            claims_data = json.loads(claims_content if claims_content else '{}')

            if user_id in claims_data:
                user_claim_info = claims_data[user_id]
                if 'last_claim_timestamp' in user_claim_info:
                    last_claim_time = datetime.fromisoformat(user_claim_info['last_claim_timestamp'])
                    if current_time < last_claim_time + timedelta(days=7):
                        next_claim_time = last_claim_time + timedelta(days=7)
                        await interaction.followup.send(f"❌ **Cooldown!** Anda baru bisa klaim lagi pada {next_claim_time.strftime('%d %B %Y, %H:%M')} UTC.", ephemeral=True); return
                
                if 'current_token' in user_claim_info and 'token_expiry_timestamp' in user_claim_info and datetime.fromisoformat(user_claim_info['token_expiry_timestamp']) > current_time:
                    await interaction.followup.send(f"❌ Token Anda saat ini masih aktif.", ephemeral=True); return

            user_role_names = [role.name.lower() for role in user.roles]
            claim_role = next((role for role in self.ROLE_PRIORITY if role in user_role_names), None)
            if not claim_role:
                await interaction.followup.send("❌ Anda tidak memiliki peran yang valid untuk klaim token.", ephemeral=True); return
            
            source_alias = self.bot.current_claim_source_alias
            token_source_info = self.TOKEN_SOURCES[source_alias]
            target_repo_slug, target_file_path = token_source_info["slug"], token_source_info["path"]
            duration_str = self.ROLE_DURATIONS[claim_role]
            duration_delta = parse_duration(duration_str)
            new_token = generate_random_token(claim_role)
            
            tokens_content, tokens_sha = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
            new_tokens_content = (tokens_content or "").strip() + f"\n\n{new_token}\n\n"
            token_add_success = update_github_file(target_repo_slug, target_file_path, new_tokens_content, tokens_sha, f"Bot: Add token for {user.name}", self.GITHUB_TOKEN)
            
            if not token_add_success:
                await interaction.followup.send("❌ Gagal membuat token di file sumber. Silakan coba lagi.", ephemeral=True)
                return

            claims_data[user_id] = {
                "last_claim_timestamp": current_time.isoformat(), 
                "current_token": new_token, 
                "token_expiry_timestamp": (current_time + duration_delta).isoformat(), 
                "source_alias": source_alias
            }
            claim_db_update_success = update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, f"Bot: Update claim for {user.name}", self.GITHUB_TOKEN)

            if not claim_db_update_success:
                logger.critical(f"KRITIS: Gagal menyimpan claim untuk {user.name}. Melakukan rollback token.")
                current_tokens_content, current_tokens_sha = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
                if current_tokens_content and new_token in current_tokens_content:
                    lines = [line for line in current_tokens_content.split('\n\n') if line.strip() and line.strip() != new_token]
                    content_after_removal = "\n\n".join(lines) + ("\n\n" if lines else "")
                    rollback_success = update_github_file(target_repo_slug, target_file_path, content_after_removal, current_tokens_sha, f"Bot: ROLLBACK token for {user.name}", self.GITHUB_TOKEN)
                    logger.info(f"Status Rollback: {'Berhasil' if rollback_success else 'Gagal'}")
                await interaction.followup.send("❌ **Klaim Gagal!** Terjadi kesalahan saat menyimpan data klaim Anda. Token tidak dapat diberikan. Silakan hubungi admin.", ephemeral=True)
                return

        try:
            await user.send(f"🎉 **Token Anda Berhasil Diklaim!**\n\n**Sumber:** `{source_alias.title()}`\n**Token Anda:** ```{new_token}```\n**Role:** `{claim_role.title()}`\nAktif selama **{duration_str.replace('d', ' hari')}**.")
            await interaction.followup.send("✅ **Berhasil!** Token Anda telah dikirim melalui DM.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("⚠️ Gagal mengirim DM. Token Anda tetap dibuat dan tersimpan.", ephemeral=True)

    @ui.button(label="Cek Token Saya", style=discord.ButtonStyle.secondary, custom_id="check_token_button")
    async def check_button_callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        user_id = str(interaction.user.id)
        
        claims_content, _ = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
        claims_data = json.loads(claims_content if claims_content else '{}')

        if user_id not in claims_data:
            await interaction.followup.send("Anda belum pernah melakukan klaim token.", ephemeral=True); return
        
        user_data = claims_data[user_id]
        embed = discord.Embed(title="📄 Detail Token Anda", color=discord.Color.blue())
        
        if 'current_token' in user_data and 'token_expiry_timestamp' in user_data and datetime.fromisoformat(user_data["token_expiry_timestamp"]) > datetime.now(timezone.utc):
            embed.add_field(name="Token Aktif", value=f"```{user_data['current_token']}```", inline=False)
            embed.add_field(name="Sumber", value=f"`{user_data.get('source_alias', 'N/A').title()}`", inline=True)
            expiry_time = datetime.fromisoformat(user_data["token_expiry_timestamp"])
            embed.add_field(name="Kedaluwarsa Pada", value=f"{expiry_time.strftime('%d %B %Y, %H:%M')} UTC", inline=True)
        else:
            embed.description = "Anda tidak memiliki token yang aktif saat ini."

        if 'last_claim_timestamp' in user_data:
            last_claim_time = datetime.fromisoformat(user_data["last_claim_timestamp"])
            next_claim_time = last_claim_time + timedelta(days=7)
            if datetime.now(timezone.utc) < next_claim_time:
                 embed.add_field(name="Cooldown Klaim", value=f"Bisa klaim lagi pada {next_claim_time.strftime('%d %B %Y, %H:%M')} UTC", inline=False)
            else:
                 embed.add_field(name="Cooldown Klaim", value="Anda sudah bisa klaim token baru.", inline=False)
        else:
            embed.add_field(name="Cooldown Klaim", value="Anda bisa klaim token sekarang.", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


# =================================================================================
# KELAS COG UTAMA (TOKEN)
# =================================================================================
class TokenCog(commands.Cog, name="Token"):
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        
        # Mengambil variabel dari config bot
        self.GITHUB_TOKEN = self.config.GITHUB_TOKEN
        self.PRIMARY_REPO = self.config.PRIMARY_REPO
        self.CLAIMS_FILE_PATH = self.config.CLAIMS_FILE_PATH
        self.TOKEN_SOURCES = self.config.TOKEN_SOURCES
        self.ROLE_DURATIONS = self.config.ROLE_DURATIONS
        self.ROLE_PRIORITY = self.config.ROLE_PRIORITY
        self.CLAIM_CHANNEL_ID = self.config.CLAIM_CHANNEL_ID

        # Memulai background task
        self.cleanup_expired_tokens.start()
        logger.info("✅ Token Cog loaded, cleanup task started.")

    def cog_unload(self):
        self.cleanup_expired_tokens.cancel()
        logger.info("🛑 Token Cog unloaded, cleanup task stopped.")

    # --- DECORATOR UNTUK ADMIN CHECK ---
    async def is_admin_check(self, interaction: discord.Interaction) -> bool:
        """Pemeriksaan internal apakah pengguna adalah admin."""
        if not hasattr(self.bot, 'admin_ids'): 
            logger.warning("Pengecekan admin gagal: bot.admin_ids belum di-set.")
            return False
        is_admin = interaction.user.id in self.bot.admin_ids
        if not is_admin:
            logger.warning(f"Pengecekan admin gagal: {interaction.user.id} tidak ada di {self.bot.admin_ids}")
        return is_admin

    # --- AUTOCOMPLETE ---
    async def source_alias_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return [app_commands.Choice(name=alias, value=alias) for alias in self.TOKEN_SOURCES.keys() if current.lower() in alias.lower()]

    # --- BACKGROUND TASK ---
    @tasks.loop(hours=1)
    async def cleanup_expired_tokens(self):
        logger.info(f"[{datetime.now()}] Menjalankan tugas pembersihan token kedaluwarsa...")
        async with self.bot.github_lock:
            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            if not claims_content:
                logger.warning("Pembersihan dibatalkan: Gagal membaca claims.json.")
                return

            try:
                claims_data = json.loads(claims_content)
            except json.JSONDecodeError:
                logger.error("Pembersihan dibatalkan: claims.json rusak atau kosong.")
                return

            current_time = datetime.now(timezone.utc)
            keys_to_process = list(claims_data.keys())
            tokens_to_remove_by_source = {}
            claims_updated = False

            for key in keys_to_process:
                data = claims_data.get(key)
                if data and "token_expiry_timestamp" in data:
                    try: expiry_time = datetime.fromisoformat(data["token_expiry_timestamp"])
                    except ValueError: continue
                    
                    if current_time > expiry_time:
                        claims_updated = True
                        token = data.get("current_token")
                        alias = data.get("source_alias")

                        if token and alias and alias in self.TOKEN_SOURCES:
                            if alias not in tokens_to_remove_by_source:
                                tokens_to_remove_by_source[alias] = {"slug": self.TOKEN_SOURCES[alias]["slug"], "path": self.TOKEN_SOURCES[alias]["path"], "tokens": set()}
                            # --- [INI ADALAH PERBAIKANNYA] ---
                            tokens_to_remove_by_source[alias]["tokens"].add(token)
                            # ----------------------------------

                        if key.startswith("shared_"): del claims_data[key]
                        else:
                            data.pop("current_token", None); data.pop("token_expiry_timestamp", None); data.pop("source_alias", None)
            
            if not claims_updated:
                logger.info("Tidak ada token kedaluwarsa yang ditemukan.")
                return

            for alias, info in tokens_to_remove_by_source.items():
                content, sha = get_github_file(info["slug"], info["path"], self.GITHUB_TOKEN)
                if content:
                    lines = content.split('\n\n')
                    new_lines = [line for line in lines if line.strip() and line.strip() not in info["tokens"]]
                    new_content = "\n\n".join(new_lines) + ("\n\n" if new_lines else "")
                    if new_content != content:
                        update_github_file(info["slug"], info["path"], new_content, sha, f"Bot: Hapus token kedaluwarsa otomatis", self.GITHUB_TOKEN)
                        logger.info(f"{len(info['tokens'])} token kedaluwarsa dihapus dari sumber: {alias}")

            update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, "Bot: Bersihkan data klaim token kedaluwarsa", self.GITHUB_TOKEN)
            logger.info("Pembersihan data di claims.json selesai.")

    @cleanup_expired_tokens.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # --- PERINTAH SLASH COMMAND (ADMIN) ---

    @app_commands.command(name="open_claim", description="ADMIN: Membuka sesi klaim untuk sumber token tertentu.")
    @app_commands.check(is_admin_check)
    @app_commands.autocomplete(alias=source_alias_autocomplete)
    async def open_claim(self, interaction: discord.Interaction, alias: str):
        await interaction.response.defer(ephemeral=True)
        if alias.lower() not in self.TOKEN_SOURCES:
            await interaction.followup.send(f"❌ Alias `{alias}` tidak valid.", ephemeral=True); return
        if not self.CLAIM_CHANNEL_ID or not (claim_channel := self.bot.get_channel(self.CLAIM_CHANNEL_ID)):
            await interaction.followup.send("❌ `CLAIM_CHANNEL_ID` tidak valid.", ephemeral=True); return

        if self.bot.close_claim_message:
            try: await self.bot.close_claim_message.delete()
            except discord.HTTPException: pass
            finally: self.bot.close_claim_message = None

        self.bot.current_claim_source_alias = alias.lower()
        embed = discord.Embed(title=f"📝 Sesi Klaim Dibuka: {alias.title()}", description=f"Sesi klaim untuk sumber `{alias.title()}` telah dibuka.", color=discord.Color.green())
        self.bot.open_claim_message = await claim_channel.send(embed=embed, view=ClaimPanelView(self.bot))
        await interaction.followup.send(f"✅ Panel klaim untuk `{alias.title()}` dikirim ke {claim_channel.mention}.", ephemeral=True)

    @app_commands.command(name="close_claim", description="ADMIN: Menutup sesi klaim dan mengirim notifikasi.")
    @app_commands.check(is_admin_check)
    async def close_claim(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.bot.current_claim_source_alias:
            await interaction.followup.send("ℹ️ Tidak ada sesi klaim yang aktif.", ephemeral=True); return
            
        if self.bot.open_claim_message:
            try: await self.bot.open_claim_message.delete()
            except discord.HTTPException: pass
            finally: self.bot.open_claim_message = None
                
        closed_alias = self.bot.current_claim_source_alias
        self.bot.current_claim_source_alias = None
        
        if self.CLAIM_CHANNEL_ID and (claim_channel := self.bot.get_channel(self.CLAIM_CHANNEL_ID)):
            embed = discord.Embed(title="🔴 Sesi Klaim Ditutup", description=f"Admin telah menutup sesi klaim untuk `{closed_alias.title()}`.", color=discord.Color.red())
            self.bot.close_claim_message = await claim_channel.send(embed=embed)
        await interaction.followup.send(f"🔴 Sesi klaim untuk `{closed_alias.title()}` telah ditutup.", ephemeral=True)

    @app_commands.command(name="admin_add_token", description="ADMIN: Menambahkan token custom ke sumber file tertentu.")
    @app_commands.check(is_admin_check)
    @app_commands.autocomplete(alias=source_alias_autocomplete)
    async def admin_add_token(self, interaction: discord.Interaction, alias: str, token: str):
        await interaction.response.defer(ephemeral=True)
        source_info = self.TOKEN_SOURCES.get(alias.lower())
        if not source_info:
            await interaction.followup.send(f"❌ Alias `{alias}` tidak valid.", ephemeral=True); return

        async with self.bot.github_lock:
            content, sha = get_github_file(source_info["slug"], source_info["path"], self.GITHUB_TOKEN)
            if token in (content or ""):
                await interaction.followup.send(f"❌ Token `{token}` sudah ada di `{alias}`.", ephemeral=True); return
            
            new_content = (content or "").strip() + f"\n\n{token}\n\n"
            if update_github_file(source_info["slug"], source_info["path"], new_content, sha, f"Admin: Add custom token {token}", self.GITHUB_TOKEN):
                await interaction.followup.send(f"✅ Token custom `{token}` ditambahkan ke `{alias}`.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Gagal menambahkan token ke `{alias}`.", ephemeral=True)

    @app_commands.command(name="admin_remove_token", description="ADMIN: Menghapus token dari sumber file tertentu.")
    @app_commands.check(is_admin_check)
    @app_commands.autocomplete(alias=source_alias_autocomplete)
    async def admin_remove_token(self, interaction: discord.Interaction, alias: str, token: str):
        await interaction.response.defer(ephemeral=True)
        source_info = self.TOKEN_SOURCES.get(alias.lower())
        if not source_info:
            await interaction.followup.send(f"❌ Alias `{alias}` tidak valid.", ephemeral=True); return
            
        async with self.bot.github_lock:
            content, sha = get_github_file(source_info["slug"], source_info["path"], self.GITHUB_TOKEN)
            if not content or token not in content:
                await interaction.followup.send(f"❌ Token `{token}` tidak ditemukan di `{alias}`.", ephemeral=True); return
                
            lines = [line for line in content.split('\n\n') if line.strip() and line.strip() != token]
            new_content = "\n\n".join(lines) + ("\n\n" if lines else "")
            if update_github_file(source_info["slug"], source_info["path"], new_content, sha, f"Admin: Remove token {token}", self.GITHUB_TOKEN):
                await interaction.followup.send(f"✅ Token `{token}` dihapus dari `{alias}`.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Gagal menghapus token dari `{alias}`.", ephemeral=True)

    @app_commands.command(name="admin_add_shared_token", description="ADMIN: Menambahkan token yang bisa dibagikan dengan durasi custom.")
    @app_commands.check(is_admin_check)
    @app_commands.describe(alias="Alias sumber token.", token="Token yang akan ditambahkan.", durasi="Durasi token (misal: 7d, 24h, 30m).")
    @app_commands.autocomplete(alias=source_alias_autocomplete)
    async def admin_add_shared_token(self, interaction: discord.Interaction, alias: str, token: str, durasi: str):
        await interaction.response.defer(ephemeral=True)
        source_info = self.TOKEN_SOURCES.get(alias.lower())
        if not source_info:
            await interaction.followup.send(f"❌ Alias `{alias}` tidak valid.", ephemeral=True); return
        try:
            duration_delta = parse_duration(durasi)
        except ValueError as e:
            await interaction.followup.send(f"❌ Format durasi tidak valid: {e}", ephemeral=True); return

        async with self.bot.github_lock:
            target_repo_slug, target_file_path = source_info["slug"], source_info["path"]
            tokens_content, tokens_sha = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
            if token in (tokens_content or ""):
                await interaction.followup.send(f"❌ Token `{token}` sudah ada di file sumber `{alias}`.", ephemeral=True); return
                
            new_tokens_content = (tokens_content or "").strip() + f"\n\n{token}\n\n"
            token_add_success = update_github_file(target_repo_slug, target_file_path, new_tokens_content, tokens_sha, f"Admin: Add shared token {token}", self.GITHUB_TOKEN)
            if not token_add_success:
                await interaction.followup.send("❌ Gagal menambahkan token ke file sumber. Operasi dibatalkan.", ephemeral=True); return

            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            claims_data = json.loads(claims_content if claims_content else '{}')
            claim_key = f"shared_{alias.lower()}_{token}" 
            if claim_key in claims_data:
                await interaction.followup.send(f"❌ Data untuk token `{token}` sudah ada di database klaim.", ephemeral=True)
                # Rollback
                lines = [line for line in new_tokens_content.split('\\n\\n') if line.strip() and line.strip() != token]
                content_after_removal = "\\n\\n".join(lines) + ("\\n\\n" if lines else "")
                update_github_file(target_repo_slug, target_file_path, content_after_removal, tokens_sha, f"Admin: ROLLBACK shared token {token}", self.GITHUB_TOKEN)
                return
                
            current_time = datetime.now(timezone.utc); expiry_time = current_time + duration_delta
            claims_data[claim_key] = {"last_claim_timestamp": current_time.isoformat(), "current_token": token, "token_expiry_timestamp": expiry_time.isoformat(), "source_alias": alias.lower(), "is_shared": True}
            claim_db_update_success = update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, f"Admin: Add data for shared token {token}", self.GITHUB_TOKEN)
            
            if not claim_db_update_success:
                logger.critical(f"KRITIS: Gagal menyimpan data klaim untuk token shared '{token}'. Melakukan rollback.")
                current_tokens_content_rb, current_tokens_sha_rb = get_github_file(target_repo_slug, target_file_path, self.GITHUB_TOKEN)
                if current_tokens_content_rb and token in current_tokens_content_rb:
                    lines = [line for line in current_tokens_content_rb.split('\\n\\n') if line.strip() and line.strip() != token]
                    content_after_removal = "\\n\\n".join(lines) + ("\\n\\n" if lines else "")
                    update_github_file(target_repo_slug, target_file_path, content_after_removal, current_tokens_sha_rb, f"Admin: ROLLBACK shared token {token}", self.GITHUB_TOKEN)
                await interaction.followup.send("❌ Gagal menyimpan data token ke database. Token di file sumber telah dihapus kembali.", ephemeral=True)
                return

        await interaction.followup.send(f"✅ Token `{token}` berhasil ditambahkan ke `{alias}` dan akan aktif selama `{durasi}`.", ephemeral=True)

    @app_commands.command(name="list_sources", description="ADMIN: Menampilkan semua sumber token yang terkonfigurasi.")
    @app_commands.check(is_admin_check)
    async def list_sources(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🔧 Konfigurasi Sumber Token", color=discord.Color.purple())
        if not self.TOKEN_SOURCES:
            embed.description = "Variabel `TOKEN_SOURCES` belum diatur."
        else:
            for alias, info in self.TOKEN_SOURCES.items():
                embed.add_field(name=f"Alias: `{alias.title()}`", value=f"**Repo:** `{info['slug']}`\n**File:** `{info['path']}`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="baca_file", description="ADMIN: Membaca konten file dari sumber token.")
    @app_commands.check(is_admin_check)
    @app_commands.autocomplete(alias=source_alias_autocomplete)
    async def baca_file(self, interaction: discord.Interaction, alias: str):
        await interaction.response.defer(ephemeral=True)
        source_info = self.TOKEN_SOURCES.get(alias.lower())
        if not source_info:
            await interaction.followup.send(f"❌ Alias `{alias}` tidak valid.", ephemeral=True); return
            
        content, _ = get_github_file(source_info["slug"], source_info["path"], self.GITHUB_TOKEN)
        if content is None:
            await interaction.followup.send(f"❌ File tidak ditemukan di `{alias}`.", ephemeral=True); return
            
        content_to_show = content[:1900] + "\n... (dipotong)" if len(content) > 1900 else content
        embed = discord.Embed(title=f"📄 Konten dari `{alias}`", description=f"```\n{content_to_show or '[File Kosong]'}\n```", color=discord.Color.blue())
        embed.set_footer(text=f"Repo: {source_info['slug']}, File: {source_info['path']}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="admin_reset_cooldown", description="ADMIN: Mereset seluruh data klaim untuk pengguna.")
    @app_commands.check(is_admin_check)
    async def admin_reset_cooldown(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        user_id = str(user.id)
        async with self.bot.github_lock:
            claims_content, claims_sha = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
            claims_data = json.loads(claims_content if claims_content else '{}')
            if user_id not in claims_data:
                await interaction.followup.send(f"ℹ️ {user.mention} belum pernah klaim.", ephemeral=True); return
            
            del claims_data[user_id]
                
            if update_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, json.dumps(claims_data, indent=4), claims_sha, f"Admin: Reset data for {user.name}", self.GITHUB_TOKEN):
                await interaction.followup.send(f"✅ Seluruh data klaim untuk {user.mention} berhasil direset.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Gagal mereset data untuk {user.mention}.", ephemeral=True)

    @app_commands.command(name="admin_cek_user", description="ADMIN: Memeriksa status token dan cooldown pengguna.")
    @app_commands.check(is_admin_check)
    async def admin_cek_user(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        claims_content, _ = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
        claims_data = json.loads(claims_content if claims_content else '{}')

        if str(user.id) not in claims_data:
            await interaction.followup.send(f"**{user.display_name}** belum pernah klaim.", ephemeral=True); return
        
        user_data = claims_data[str(user.id)]
        embed = discord.Embed(title=f"🔍 Status Token - {user.display_name}", color=discord.Color.orange())
        
        if 'current_token' in user_data and 'token_expiry_timestamp' in user_data and datetime.fromisoformat(user_data["token_expiry_timestamp"]) > datetime.now(timezone.utc):
            embed.add_field(name="Token Aktif", value=f"`{user_data['current_token']}`", inline=False)
            embed.add_field(name="Sumber", value=f"`{user_data.get('source_alias', 'N/A').title()}`", inline=True)
            expiry_time = datetime.fromisoformat(user_data["token_expiry_timestamp"])
            embed.add_field(name="Kedaluwarsa", value=f"{expiry_time.strftime('%d %b %Y, %H:%M')} UTC", inline=True)
        else:
            embed.description = "Pengguna tidak memiliki token aktif."

        if 'last_claim_timestamp' in user_data:
            last_claim_time = datetime.fromisoformat(user_data["last_claim_timestamp"])
            next_claim_time = last_claim_time + timedelta(days=7)
            embed.add_field(name="Klaim Terakhir", value=last_claim_time.strftime('%d %b %Y, %H:%M UTC'), inline=False)
            if datetime.now(timezone.utc) < next_claim_time:
                embed.add_field(name="Bisa Klaim Lagi", value=next_claim_time.strftime('%d %b %Y, %H:%M UTC'), inline=False)
            else:
                embed.add_field(name="Bisa Klaim Lagi", value="Sekarang", inline=False)
        else:
            embed.add_field(name="Cooldown Klaim", value="Pengguna tidak dalam masa cooldown.", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="list_tokens", description="ADMIN: Menampilkan daftar semua token aktif dari database.")
    @app_commands.check(is_admin_check)
    async def list_tokens(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Perintah ini harus dijalankan di dalam server.", ephemeral=True); return

        claims_content, _ = get_github_file(self.PRIMARY_REPO, self.CLAIMS_FILE_PATH, self.GITHUB_TOKEN)
        claims_data = json.loads(claims_content if claims_content else '{}')
        if not claims_data:
            await interaction.followup.send("Tidak ada data klaim.", ephemeral=True); return

        embed = discord.Embed(title="Daftar Token Aktif", color=discord.Color.blue())
        active_tokens = []
        current_time = datetime.now(timezone.utc)

        for key, data in claims_data.items():
            if 'current_token' in data and 'token_expiry_timestamp' in data and datetime.fromisoformat(data["token_expiry_timestamp"]) > current_time:
                username = f"Shared Key: {key}"
                if key.isdigit():
                    member = guild.get_member(int(key))
                    username = str(member) if member else f"User ID: {key} (Not in server)"
                active_tokens.append(f"**{username}**: `{data['current_token']}` (Sumber: {data.get('source_alias', 'N/A').title()})")

        embed.description = "\n".join(active_tokens) if active_tokens else "Tidak ada token yang sedang aktif."
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="show_config", description="ADMIN: Menampilkan channel yang terkonfigurasi.")
    @app_commands.check(is_admin_check)
    async def show_config(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🔧 Konfigurasi Channel Bot", color=discord.Color.teal())
        embed.add_field(name="Channel Klaim", value=f"<#{self.CLAIM_CHANNEL_ID}>" if self.CLAIM_CHANNEL_ID else "Belum diatur", inline=False)
        # Ambil config role dari self.bot.config, BUKAN self.config
        role_req_ch_id = self.bot.config.ROLE_REQUEST_CHANNEL_ID
        embed.add_field(name="Channel Role", value=f"<#{role_req_ch_id}>" if role_req_ch_id else "Belum diatur", inline=False)
        embed.set_footer(text="Diatur melalui Environment Variables.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="serverlist", description="ADMIN: Menampilkan daftar semua server tempat bot ini berada.")
    @app_commands.check(is_admin_check)
    async def serverlist(self, interaction: discord.Interaction):
        server_list = [f"- **{guild.name}** (ID: `{guild.id}`)" for guild in self.bot.guilds]
        embed = discord.Embed(title=f"Bot Aktif di {len(self.bot.guilds)} Server", description="\n".join(server_list), color=0x3498db)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    token_cog = TokenCog(bot)
    await bot.add_cog(token_cog)
    # Menambahkan view persistent
    # Pastikan view hanya ditambahkan sekali
    if not hasattr(bot, 'claim_view_added'):
        bot.add_view(ClaimPanelView(bot))
        bot.claim_view_added = True
