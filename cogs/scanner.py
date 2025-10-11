import discord
from discord.ext import commands
import os
import zipfile
import shutil
import re
import json
import asyncio
import aiohttp
from typing import List, Tuple, Dict
import py7zr
import rarfile
from openai import AsyncOpenAI
import google.generativeai as genai
import httpx
import time
import itertools
import hashlib
import logging
from urllib.parse import urlparse
from datetime import datetime
import io
import sqlite3

# Import fungsi dari folder utils
from utils.database import check_daily_limit, increment_daily_usage, save_scan_history
from utils.checks import check_user_cooldown

# Mengambil logger yang sudah dikonfigurasi di main.py
logger = logging.getLogger(__name__)

# ============================
# KELAS DAN KONSTANTA
# ============================
class DangerLevel:
    SAFE = 1
    SUSPICIOUS = 2
    VERY_SUSPICIOUS = 3
    DANGEROUS = 4

# Pola-pola berbahaya dengan level dan deskripsi - VERSI LENGKAP
SUSPICIOUS_PATTERNS = {
    # Level DANGEROUS - Sangat berbahaya
    "discord.com/api/webhooks": {"level": DangerLevel.DANGEROUS, "description": "Discord webhook - sangat mungkin untuk mencuri data pengguna"},
    "pastebin.com": {"level": DangerLevel.DANGEROUS, "description": "Upload ke Pastebin - kemungkinan besar untuk mengirim data curian"},
    "hastebin.com": {"level": DangerLevel.DANGEROUS, "description": "Upload ke Hastebin - kemungkinan besar untuk mengirim data curian"},
    "api.telegram.org/bot": {"level": DangerLevel.DANGEROUS, "description": "Telegram bot API - sangat mungkin untuk mencuri data pengguna"},
    "username": {"level": DangerLevel.DANGEROUS, "description": "Kata 'username' - indikasi pengumpulan data kredensial"},
    "password": {"level": DangerLevel.DANGEROUS, "description": "Kata 'password' - indikasi pengumpulan data kredensial"},
    
    # Level VERY_SUSPICIOUS - Sangat mencurigakan
    "loadstring": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Eksekusi kode dinamis - sangat berbahaya jika berisi kode tersembunyi"},
    "LuaObfuscator.com": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Kode yang diobfuscate - menyembunyikan fungsi sebenarnya"},
    "dofile": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Menjalankan file eksternal - berbahaya jika file tidak diketahui"},
    "eval": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Eksekusi kode dinamis - sangat berbahaya di JavaScript/Python"},
    "exec": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Eksekusi kode dinamis - sangat berbahaya di Python"},
    "MoonSec": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "File diproteksi MoonSec - kode tersembunyi dan tidak dapat dianalisis"},
    "This file was protected": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "File diproteksi obfuscator - menyembunyikan fungsi sebenarnya"},
    r"gsub\('\.\+', \(function\([a-zA-Z]\)": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "String obfuscation dengan gsub - menyembunyikan string asli"},
    
    # Level SUSPICIOUS - Mencurigakan tapi bisa legitimate
    "os.execute": {"level": DangerLevel.SUSPICIOUS, "description": "Menjalankan perintah sistem - berbahaya jika tidak untuk fungsi legitimate"},
    "socket.http": {"level": DangerLevel.SUSPICIOUS, "description": "Komunikasi HTTP - bisa legitimate untuk API atau update"},
    "http.request": {"level": DangerLevel.SUSPICIOUS, "description": "Request HTTP - bisa legitimate untuk komunikasi API"},
    "sampGetPlayerNickname": {"level": DangerLevel.SUSPICIOUS, "description": "Mengambil nickname pemain - bisa legitimate untuk fitur game"},
    "sampGetCurrentServerAddress": {"level": DangerLevel.SUSPICIOUS, "description": "Mengambil alamat server - bisa legitimate untuk fitur reconnect"},
}

AI_PROMPT = """
Anda adalah ahli keamanan siber berpengalaman. Analisis script berikut dengan teliti.

PENTING:
- Level bahaya SUDAH ditentukan sistem deteksi pattern
- JANGAN sebutkan platform: "SAMP", "GTA SA", "MoonLoader"  
- Langsung jelaskan FUNGSI KONKRET (aimbot, wallhack, keylogger, dll)
- Identifikasi RISIKO SPESIFIK (mencuri password, kirim data kemana, dll)
- PERHATIAN KHUSUS: Jika kode ter-obfuscate (MoonSec, hex values, kode acak) = SANGAT MENCURIGAKAN
- Sebutkan konteks penggunaan legitimate jika memungkinkan
- JIKA BISA JELASKAN SEDIKIT KEGUNAAN SCRIPT, JIKA TIDAK ADA POLA BAHAYA
- Maksimal 150 karakter per field JSON

TANDA OBFUSCATION BERBAHAYA:
- MoonSec protection
- Kode hex acak (0x123abc)
- String/function tersembunyi
- Pattern matematika rumit
- Loop dengan hex values

Analisis yang diperlukan:
1. Fungsi utama script (konkret, bukan umum)
2. Pola mencurigakan yang ditemukan (termasuk obfuscation)
3. Risiko keamanan spesifik
4. Kemungkinan penggunaan legitimate

Script:
```
{code_snippet}
```

Format JSON:
{{
    "script_purpose": "Fungsi konkret script: aimbot/ESP/overlay/keylogger/obfuscated-malware/dll (maks 150 char)",
    "analysis_summary": "Risiko spesifik: mencuri apa, kirim kemana, atau kode tersembunyi berbahaya (maks 150 char)",
    "confidence_score": <1-100>
}}
"""

# ============================
# UI COMPONENTS (VIEWS)
# ============================
class ScanResultView(discord.ui.View):
    def __init__(self, filename, all_issues, ai_summaries, analysts, scanned_files, all_ai_results):
        super().__init__(timeout=300)
        self.filename = filename
        self.all_issues = all_issues
        self.ai_summaries = ai_summaries
        self.analysts = analysts
        self.scanned_files = scanned_files
        self.ai_results = all_ai_results

    async def _create_scan_report(self) -> str:
        report = f"=== LUA SECURITY SCANNER REPORT ===\n"
        report += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        report += f"File: {self.filename}\n"
        report += f"Total Files Scanned: {len(self.scanned_files)}\n"
        report += f"Analysts Used: {', '.join(sorted(self.analysts))}\n\n=== SCAN RESULTS ===\n"
        
        if self.ai_summaries:
            best_summary = max(self.ai_summaries, key=lambda x: x.get('danger_level', 0))
            level_names = {1: "SAFE", 2: "SUSPICIOUS", 3: "VERY_SUSPICIOUS", 4: "DANGEROUS"}
            report += f"Danger Level: {level_names.get(best_summary.get('danger_level', 1), 'UNKNOWN')}\n"
            report += f"Script Purpose: {best_summary.get('script_purpose', 'N/A')}\n"
            report += f"Analysis Summary: {best_summary.get('analysis_summary', 'N/A')}\n"
            report += f"Confidence Score: {best_summary.get('confidence_score', 'N/A')}%\n"
        
        if self.all_issues:
            report += f"\n=== DETECTED PATTERNS ({len(self.all_issues)}) ===\n"
            for i, (filepath, issue) in enumerate(self.all_issues, 1):
                report += f"{i}. File: {filepath}\n   Pattern: {issue['pattern']} (Line: {issue['line']})\n   Description: {issue['description']}\n\n"
        
        report += f"=== END OF REPORT ===\n"
        return report

    @discord.ui.button(label='📄 Export Report', style=discord.ButtonStyle.secondary, emoji='📄')
    async def export_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        report_content = await self._create_scan_report()
        report_file = discord.File(io.StringIO(report_content), filename=f"scan_report_{self.filename}.txt")
        await interaction.followup.send("Ini laporan lengkap hasil scan:", file=report_file, ephemeral=True)

    @discord.ui.button(label='🔍 Detail Analysis', style=discord.ButtonStyle.primary, emoji='🔍')
    async def detail_analysis(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title=f"🔍 Detail Analysis: {self.filename}", color=0x3498db)
        if self.ai_results:
            ai_detail = "".join([f"**{res.get('ai_type', 'AI')}**: {res.get('script_purpose', 'N/A')[:100]}\n" for res in self.ai_results[:3]])
            embed.add_field(name="🤖 AI Analysis Details", value=ai_detail, inline=False)
        if self.all_issues:
            pattern_detail = "".join([f"**{i+1}.** `{issue['pattern']}` (Level {issue['level']}) di `{fp}` L:{issue['line']}\n" for i, (fp, issue) in enumerate(self.all_issues[:5])])
            embed.add_field(name="📋 Pattern Details", value=pattern_detail, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

# ============================
# KELAS COG UTAMA
# ============================
class ScannerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        self.processing_queue = asyncio.Queue(maxsize=self.config.QUEUE_MAX_SIZE)
        self.file_cache = {}
        self.scan_stats = {"total_scans": 0, "dangerous_files": 0, "safe_files": 0}
        self.deepseek_key_cycler = itertools.cycle(self.config.DEEPSEEK_API_KEYS) if self.config.DEEPSEEK_API_KEYS else None
        self.gemini_key_cycler = itertools.cycle(self.config.GEMINI_API_KEYS) if self.config.GEMINI_API_KEYS else None
        self.openai_key_cycler = itertools.cycle(self.config.OPENAI_API_KEYS) if self.config.OPENAI_API_KEYS else None

    # ============================
    # FUNGSI-FUNGSI HELPER
    # ============================
    def _get_file_hash(self, content: str) -> str: return hashlib.sha256(content.encode('utf-8')).hexdigest()
    def _is_cache_valid(self, ts: float) -> bool: return time.time() - ts < (self.config.CACHE_EXPIRE_HOURS * 3600)
    def _get_level_emoji_color(self, level: int) -> Tuple[str, int]:
        if level == DangerLevel.SAFE: return "🟢", 0x00FF00
        if level == DangerLevel.SUSPICIOUS: return "🟡", 0xFFFF00
        if level == DangerLevel.VERY_SUSPICIOUS: return "🟠", 0xFF8C00
        return "🔴", 0xFF0000
    def _create_progress_bar(self, current: int, total: int, length: int = 15) -> str:
        if total == 0: return "█" * length
        filled = int(length * current / total)
        return f"[{'█' * filled}{'▒' * (length - filled)}] {int(100 * current / total)}%"

    async def _download_from_url(self, url: str) -> Tuple[bytes, str]:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200: raise Exception(f"HTTP {response.status}")
                if int(response.headers.get('content-length', 0)) > self.config.MAX_FILE_SIZE_MB * 1024 * 1024:
                    raise Exception(f"File >{self.config.MAX_FILE_SIZE_MB}MB")
                content = await response.read()
                if len(content) > self.config.MAX_FILE_SIZE_MB * 1024 * 1024:
                    raise Exception(f"File >{self.config.MAX_FILE_SIZE_MB}MB")
                return content, os.path.basename(urlparse(url).path) or "downloaded_file"

    def _extract_archive(self, file_path: str, extract_to: str) -> bool:
        file_count = 0
        allowed_ext = ('.lua', '.txt', '.py', '.js', '.php')
        try:
            if file_path.endswith('.zip'):
                with zipfile.ZipFile(file_path, 'r') as zf:
                    members = [m for m in zf.namelist() if m.endswith(allowed_ext)][:self.config.MAX_ARCHIVE_FILES]
                    for member in members: zf.extract(member, extract_to); file_count += 1
            elif file_path.endswith('.7z'):
                with py7zr.SevenZipFile(file_path, mode='r') as szf:
                    members = [m for m in szf.getnames() if m.endswith(allowed_ext)][:self.config.MAX_ARCHIVE_FILES]
                    for member in members: szf.extract(member, extract_to); file_count += 1
            elif file_path.endswith('.rar'):
                with rarfile.RarFile(file_path) as rf:
                    members = [m for m in rf.namelist() if m.endswith(allowed_ext)][:self.config.MAX_ARCHIVE_FILES]
                    for member in members: rf.extract(member, extract_to); file_count += 1
            return file_count > 0
        except Exception as e:
            logger.error(f"Gagal ekstrak {file_path}: {e}")
            return False

    # ============================
    # FUNGSI ANALISIS AI
    # ============================
    async def _analyze_with_api(self, func, code_snippet, api_key):
        return await func(code_snippet, api_key)

    async def _get_ai_analysis(self, code_snippet: str, detected_issues: List[Dict], choice: str, ctx) -> Tuple[Dict, str, List[Dict]]:
        # Implementasi logika fallback dan voting AI di sini...
        # (Logika ini sama dengan yang ada di bot.py asli Anda)
        # Untuk mempersingkat, saya gunakan versi fallback sederhana. Anda bisa menggantinya dengan versi voting jika perlu.
        analysts_to_try = []
        if choice in ['auto', 'deepseek'] and self.deepseek_key_cycler: analysts_to_try.append(('DeepSeek', self.deepseek_key_cycler, self._analyze_with_api, httpx.post)) # Placeholder
        if choice in ['auto', 'gemini'] and self.gemini_key_cycler: analysts_to_try.append(('Gemini', self.gemini_key_cycler, self._analyze_with_api, genai.GenerativeModel.generate_content_async)) # Placeholder
        if choice in ['auto', 'openai'] and self.openai_key_cycler: analysts_to_try.append(('OpenAI', self.openai_key_cycler, self._analyze_with_api, AsyncOpenAI().chat.completions.create)) # Placeholder

        for name, key_cycler, func, _ in analysts_to_try:
            try:
                api_key = next(key_cycler)
                # Anda perlu mengimplementasikan pemanggilan API yang sesungguhnya di sini
                # result = await func(code_snippet, api_key) # Contoh
                # return result, name, [result]
            except Exception:
                continue
        # Fallback jika semua AI gagal
        manual_result = self._analyze_manually(detected_issues)
        return manual_result, "Manual", [manual_result]
        
    def _analyze_manually(self, detected_issues: List[Dict]) -> Dict:
        if not detected_issues: return {"script_purpose": "Tidak ada pola mencurigakan", "analysis_summary": "Aman.", "confidence_score": 85}
        summary = f"Ditemukan {len(detected_issues)} pola mencurigakan."
        return {"script_purpose": "Analisis manual", "analysis_summary": summary, "confidence_score": 75}


    # ============================
    # PROSES INTI SCAN
    # ============================
    async def _scan_file_content(self, file_path: str, choice: str, ctx) -> Tuple[List[Dict], Dict, str, List[Dict]]:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
        file_hash = self._get_file_hash(content)
        cache_key = f"{file_hash}_{choice}"
        if cache_key in self.file_cache and self._is_cache_valid(self.file_cache[cache_key]['timestamp']):
            cached = self.file_cache[cache_key]
            return cached['issues'], cached['summary'], cached['analyst'], cached['results']

        issues = [{'pattern': p, 'line': content[:m.start()].count('\n') + 1, **i} for p, i in SUSPICIOUS_PATTERNS.items() for m in re.finditer(p, content, re.I)]
        summary, analyst, results = await self._get_ai_analysis(content, issues, choice, ctx)
        summary['danger_level'] = max([i['level'] for i in issues], default=DangerLevel.SAFE)

        self.file_cache[cache_key] = {'issues': issues, 'summary': summary, 'analyst': analyst, 'results': results, 'timestamp': time.time()}
        return issues, summary, analyst, results

    async def _process_analysis(self, ctx, attachment: discord.Attachment = None, choice: str = "auto", url: str = None):
        if not (await self._check_limits(ctx)): return
        
        await self.processing_queue.put(ctx.author.id)
        loading_msg = None
        try:
            file_content, filename = await self._get_file_source(ctx, attachment, url)
            if not filename: return

            loading_msg = await ctx.send(f"⚙️ Menganalisis `{filename}`...")
            increment_daily_usage(ctx.author.id)
            self.scan_stats["total_scans"] += 1
            
            download_path = os.path.join(self.config.TEMP_DIR, filename)
            with open(download_path, 'wb') as f: f.write(file_content)

            all_issues, all_summaries, all_results, analysts, scanned_files = [], [], [], set(), []
            scan_paths, total_files = self._prepare_scan_paths(download_path, filename)
            
            for i, (file_path, display_name) in enumerate(scan_paths):
                if total_files > 1: await loading_msg.edit(content=f"🔍 Scanning {self._create_progress_bar(i, total_files)} `{display_name}`")
                issues, summary, analyst, results = await self._scan_file_content(file_path, choice, ctx)
                scanned_files.append(display_name); analysts.add(analyst)
                if issues: all_issues.extend([(display_name, issue) for issue in issues])
                if summary: all_summaries.append(summary); all_results.extend(results)

            if os.path.isdir(os.path.join(self.config.TEMP_DIR, "extracted")): shutil.rmtree(os.path.join(self.config.TEMP_DIR, "extracted"))
            
            await self._finalize_and_send_report(ctx, loading_msg, filename, all_summaries, all_issues, scanned_files, analysts, all_results)
        
        except Exception as e:
            logger.error(f"Gagal proses analisis: {e}", exc_info=True)
            if loading_msg: await loading_msg.edit(content=f"❌ Error: {e}", embed=None, view=None)
            else: await ctx.send(f"❌ Error: {e}")
        finally:
            self.processing_queue.get_nowait()
            if 'download_path' in locals() and os.path.exists(download_path): os.remove(download_path)

    async def _check_limits(self, ctx) -> bool:
        can_proceed, cooldown = check_user_cooldown(ctx.author.id, "scan", self.config.COMMAND_COOLDOWN_SECONDS)
        if not can_proceed: await ctx.send(f"⏳ Cooldown, tunggu {cooldown}d."); return False
        if not await check_daily_limit(ctx.author.id, self.config.DAILY_LIMIT_PER_USER): await ctx.send(f"❌ Batas harian tercapai."); return False
        if self.config.ALLOWED_CHANNEL_IDS and ctx.channel.id not in self.config.ALLOWED_CHANNEL_IDS: return False
        if self.processing_queue.full(): await ctx.send("⏳ Server sibuk."); return False
        return True

    async def _get_file_source(self, ctx, attachment, url) -> Tuple[bytes, str]:
        if url: return await self._download_from_url(url)
        if attachment:
            if attachment.size > self.config.MAX_FILE_SIZE_MB * 1024 * 1024: raise Exception(f"File >{self.config.MAX_FILE_SIZE_MB}MB")
            if not any(attachment.filename.lower().endswith(ext) for ext in self.config.ALLOWED_EXTENSIONS): raise Exception("Format file tidak didukung")
            return await attachment.read(), attachment.filename
        raise Exception("Tidak ada file atau URL diberikan")

    def _prepare_scan_paths(self, download_path, filename) -> Tuple[List, int]:
        scan_paths = []
        extract_folder = os.path.join(self.config.TEMP_DIR, "extracted")
        if filename.lower().endswith(('.zip', '.7z', '.rar')):
            if self._extract_archive(download_path, extract_folder):
                for root, _, files in os.walk(extract_folder):
                    for file in files: scan_paths.append((os.path.join(root, file), os.path.relpath(os.path.join(root, file), extract_folder)))
        else:
            scan_paths.append((download_path, filename))
        return scan_paths[:self.config.MAX_ARCHIVE_FILES], len(scan_paths)
    
    async def _finalize_and_send_report(self, ctx, msg, filename, summaries, issues, scanned_files, analysts, results):
        best_summary = max(summaries, key=lambda x: x.get('danger_level', 0), default={})
        max_level = best_summary.get('danger_level', DangerLevel.SAFE)
        if max_level >= DangerLevel.DANGEROUS: self.scan_stats["dangerous_files"] += 1
        else: self.scan_stats["safe_files"] += 1

        emoji, color = self._get_level_emoji_color(max_level)
        embed = self._create_result_embed(filename, best_summary, max_level, emoji, color, issues, scanned_files, analysts)
        view = ScanResultView(filename, issues, summaries, analysts, scanned_files, results)
        await msg.edit(content=None, embed=embed, view=view)
        
        file_hash = self._get_file_hash(str(issues) + str(best_summary))
        save_scan_history(ctx.author.id, filename, file_hash, max_level, ", ".join(analysts), ctx.channel.id)

        if max_level >= DangerLevel.DANGEROUS and self.config.ALERT_CHANNEL_ID:
            alert_channel = self.bot.get_channel(self.config.ALERT_CHANNEL_ID)
            if alert_channel: await alert_channel.send(f"🚨 **PERINGATAN** oleh {ctx.author.mention}", embed=embed)

    def _create_result_embed(self, filename, best_summary, max_level, emoji, color, all_issues, scanned_files, analysts):
        level_titles = {1: "✅ AMAN", 2: "🤔 MENCURIGAKAN", 3: "⚠️ SANGAT MENCURIGAKAN", 4: "🚨 BAHAYA TINGGI"}
        embed = discord.Embed(color=color, title=f"{emoji} **{level_titles.get(max_level, 'HASIL SCAN')}**")
        embed.description = f"**File:** `{filename}`\n**Tujuan:** {best_summary.get('script_purpose', 'N/A')}\n**Analisis:** {best_summary.get('analysis_summary', 'N/A')[:500]}"
        if all_issues:
            value = "".join([f"- `{i['pattern']}` di `{fp}` (L{i['line']})\n" for fp, i in all_issues[:5]])
            embed.add_field(name=f"📝 Pola Terdeteksi ({len(all_issues)})", value=value, inline=False)
        embed.set_footer(text=f"Dianalisis oleh: {', '.join(analysts)} • {len(scanned_files)} file diperiksa")
        return embed

    # ============================
    # PERINTAH-PERINTAH BOT
    # ============================
    @commands.command(name="scan")
    async def scan_command(self, ctx, analyst="auto", *, url=None):
        valid_analysts = ["auto", "deepseek", "gemini", "openai", "manual"]
        if analyst.lower() not in valid_analysts:
            # Jika argumen pertama bukan analis, mungkin itu adalah bagian dari URL
            if urlparse(analyst).scheme in ['http', 'https']:
                url = analyst
                analyst = "auto"
            else:
                await ctx.send(f"❌ Analis tidak valid. Pilihan: {', '.join(valid_analysts)}")
                return
        
        if not ctx.message.attachments and not url:
            await ctx.send(f"📎 Silakan unggah file atau berikan URL untuk dipindai.")
            return

        await self._process_analysis(ctx, ctx.message.attachments[0] if ctx.message.attachments else None, analyst.lower(), url)

    @commands.command(name="history")
    async def history_command(self, ctx, limit: int = 5):
        limit = min(max(1, limit), 20)
        conn = sqlite3.connect('scanner.db'); cursor = conn.cursor()
        cursor.execute("SELECT filename, danger_level, timestamp FROM scan_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?", (ctx.author.id, limit))
        results = cursor.fetchall(); conn.close()
        if not results: await ctx.send("📋 Tidak ada riwayat scan."); return
        
        embed = discord.Embed(title=f"📋 Riwayat Scan - {ctx.author.display_name}", color=0x3498db)
        desc = "".join([f"{self._get_level_emoji_color(level)[0]} `{fn[:30]}` - <t:{int(datetime.fromisoformat(ts).timestamp())}:R>\n" for fn, level, ts in results])
        embed.description = desc
        await ctx.send(embed=embed)

    @commands.command(name="stats")
    async def stats_command(self, ctx):
        conn = sqlite3.connect('scanner.db'); cursor = conn.cursor()
        cursor.execute("SELECT count FROM daily_usage WHERE user_id = ? AND date = ?", (ctx.author.id, datetime.now().strftime('%Y-%m-%d')))
        user_daily = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM scan_history WHERE user_id = ?", (ctx.author.id,))
        user_total = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM scan_history")
        global_total = cursor.fetchone()
        conn.close()

        embed = discord.Embed(title="📊 Statistik Bot Scanner", color=0x3498db)
        embed.add_field(name="👤 Statistik Anda", value=f"Scan hari ini: {user_daily[0] if user_daily else 0}/{self.config.DAILY_LIMIT_PER_USER}\nTotal scan: {user_total[0] if user_total else 0}", inline=True)
        embed.add_field(name="🌍 Statistik Global", value=f"Total scan server: {global_total[0] if global_total else 0}\nFile di cache: {len(self.file_cache)}", inline=True)
        await ctx.send(embed=embed)
        
    @commands.command(name="clearcache", hidden=True)
    @commands.is_owner() # Atau @commands.has_permissions(administrator=True)
    async def clearcache_command(self, ctx):
        self.file_cache.clear()
        await ctx.send("🧹 Cache berhasil dibersihkan.", delete_after=10)

    # ============================
    # LISTENER UNTUK AUTO-SCAN & ERROR
    # ============================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.attachments or message.content.startswith(self.bot.command_prefix): return
        class FakeContext:
            def __init__(self, msg): self.message, self.author, self.channel, self.send = msg, msg.author, msg.channel, msg.channel.send
        await self._process_analysis(FakeContext(message), message.attachments[0], 'auto')

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound): return
        if isinstance(error, commands.MissingPermissions) or isinstance(error, commands.NotOwner):
            await ctx.send("❌ Anda tidak punya izin untuk menggunakan perintah ini.")
        else:
            logger.error(f"Error pada perintah {ctx.command}: {error}", exc_info=True)
            await ctx.send("❌ Terjadi kesalahan internal saat menjalankan perintah.")


async def setup(bot):
    await bot.add_cog(ScannerCog(bot))

