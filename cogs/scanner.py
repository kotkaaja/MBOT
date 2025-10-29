import discord
from discord.ext import commands, tasks
import os
import zipfile
import shutil
import re
import json
import asyncio
import aiohttp
from typing import List, Tuple, Dict, Set, Union # Tambahkan Union
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
from datetime import datetime, timedelta
import io
import sqlite3

# Import fungsi dari folder utils
from utils.database import check_daily_limit, increment_daily_usage, save_scan_history
from utils.checks import check_user_cooldown

# Mengambil logger yang sudah dikonfigurasi di main.py
logger = logging.getLogger(__name__)
DB_FILE = 'scanner.db'

# ============================
# KONSTANTA & DEFINISI POLA
# ============================
class DangerLevel:
    SAFE = 1
    SUSPICIOUS = 2
    VERY_SUSPICIOUS = 3
    DANGEROUS = 4

# Pola-pola berbahaya (tetap sama)
SUSPICIOUS_PATTERNS = {
    # Level DANGEROUS - Sangat berbahaya
    "discord.com/api/webhooks": {"level": DangerLevel.DANGEROUS, "description": "Discord webhook - sangat mungkin untuk mencuri data pengguna"},
    "pastebin.com": {"level": DangerLevel.DANGEROUS, "description": "Upload ke Pastebin - kemungkinan besar untuk mengirim data curian"},
    "hastebin.com": {"level": DangerLevel.DANGEROUS, "description": "Upload ke Hastebin - kemungkinan besar untuk mengirim data curian"},
    "api.telegram.org/bot": {"level": DangerLevel.DANGEROUS, "description": "Telegram bot API - sangat mungkin untuk mencuri data pengguna"},
    "username": {"level": DangerLevel.DANGEROUS, "description": "Kata 'username' - indikasi pengumpulan data kredensial"},
    "password": {"level": DangerLevel.DANGEROUS, "description": "Kata 'password' - indikasi pengumpulan data kredensial"},
    "api.telegram.org/": {"level": DangerLevel.DANGEROUS, "description": "Telegram API - sangat mungkin untuk mencuri data pengguna"},
    "discordapp.com/api/webhooks": {"level": DangerLevel.DANGEROUS, "description": "Discord webhook (legacy) - sangat mungkin untuk mencuri data pengguna"},
    "discordapp.com/api/": {"level": DangerLevel.DANGEROUS, "description": "Discord API (legacy) - sangat mungkin untuk mencuri data pengguna"},
    "telegram.org/bot": {"level": DangerLevel.DANGEROUS, "description": "Telegram bot API (legacy) - sangat mungkin untuk mencuri data pengguna"},
    "api.telegram.org": {"level": DangerLevel.DANGEROUS, "description": "Telegram API (legacy) - sangat mungkin untuk mencuri data pengguna"},
    
    # Level VERY_SUSPICIOUS - Sangat mencurigakan
    "loadstring": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Eksekusi kode dinamis - sangat berbahaya jika berisi kode tersembunyi"},
    "LuaObfuscator.com": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Kode yang diobfuscate - menyembunyikan fungsi sebenarnya"},
    "dofile": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Menjalankan file eksternal - berbahaya jika file tidak diketahui"},
    "eval": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Eksekusi kode dinamis - sangat berbahaya di JavaScript/Python"},
    "exec": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Eksekusi kode dinamis - sangat berbahaya di Python"},
    "MoonSec": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "File diproteksi MoonSec - kode tersembunyi dan tidak dapat dianalisis"},
    "protected with MoonSec": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "File diproteksi MoonSec - menyembunyikan kode asli dari analisis"},
    "This file was protected": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "File diproteksi obfuscator - menyembunyikan fungsi sebenarnya"},
    r"0x[a-fA-F0-9]{4,8}.*0x[a-fA-F0-9]{4,8}.*0x[a-fA-F0-9]{4,8}": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Pattern obfuscation dengan hex values - kode disembunyikan"},
    r"local [a-zA-Z_][a-zA-Z0-9_]*=[a-zA-Z_][a-zA-Z0-9_]*\+[0-9]{4,6}": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Pattern obfuscation matematika - kemungkinan kode tersembunyi"},
    r"while.*<0x[a-fA-F0-9]+.*and.*%0x[a-fA-F0-9]+": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Loop obfuscation dengan hex - pattern kode yang disembunyikan"},
    r"gsub\('\.\+', \(function\([a-zA-Z]\)": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "String obfuscation dengan gsub - menyembunyikan string asli"},
    r"return\(function\([a-zA-Z],\.\.\.\)": {"level": DangerLevel.VERY_SUSPICIOUS, "description": "Function wrapping obfuscation - menyembunyikan fungsi utama"},
    
    # Level SUSPICIOUS - Mencurigakan tapi bisa legitimate
    "os.execute": {"level": DangerLevel.SUSPICIOUS, "description": "Menjalankan perintah sistem - berbahaya jika tidak untuk fungsi legitimate"},
    "socket.http": {"level": DangerLevel.SUSPICIOUS, "description": "Komunikasi HTTP - bisa legitimate untuk API atau update"},
    "http.request": {"level": DangerLevel.SUSPICIOUS, "description": "Request HTTP - bisa legitimate untuk komunikasi API"},
    "subprocess": {"level": DangerLevel.SUSPICIOUS, "description": "Menjalankan subprocess - bisa berbahaya di Python"},
    "shell_exec": {"level": DangerLevel.SUSPICIOUS, "description": "Eksekusi shell command - berbahaya di PHP"},
    "sampGetPlayerNickname": {"level": DangerLevel.SUSPICIOUS, "description": "Mengambil nickname pemain - bisa legitimate untuk fitur game"},
    "sampGetCurrentServerAddress": {"level": DangerLevel.SUSPICIOUS, "description": "Mengambil alamat server - bisa legitimate untuk fitur reconnect"},
    r"[a-zA-Z_][a-zA-Z0-9_]*\s*=\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\+\s*[0-9]{3,5}": {"level": DangerLevel.SUSPICIOUS, "description": "Variable obfuscation dengan angka - kemungkinan kode disembunyikan"},
    r"local [a-zA-Z_][a-zA-Z0-9_]*={};while": {"level": DangerLevel.SUSPICIOUS, "description": "Table initialization dengan loop - pattern obfuscation sederhana"},
    r"if not s\[[a-zA-Z_][a-zA-Z0-9_]*\]then s\[[a-zA-Z_][a-zA-Z0-9_]*\]=0x1": {"level": DangerLevel.SUSPICIOUS, "description": "Conditional table assignment - pattern obfuscation ringan"}
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
    def __init__(self, filename: str, all_issues: List, ai_summaries: List, analysts: Set, scanned_files: List, ai_results: List):
        super().__init__(timeout=300)
        self.filename = filename
        self.all_issues = all_issues
        self.ai_summaries = ai_summaries
        self.analysts = analysts
        self.scanned_files = scanned_files
        self.ai_results = ai_results

    async def _create_scan_report(self) -> str:
        report = f"=== LUA SECURITY SCANNER REPORT ===\n"
        report += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        report += f"File: {self.filename}\n"
        report += f"Total Files Scanned: {len(self.scanned_files)}\n"
        report += f"Analysts Used: {', '.join(sorted(self.analysts))}\n\n=== SCAN RESULTS ===\n"
        
        if self.ai_summaries:
            best_summary = max(self.ai_summaries, key=lambda x: x.get('danger_level', 0), default={})
            level_names = {1: "SAFE", 2: "SUSPICIOUS", 3: "VERY_SUSPICIOUS", 4: "DANGEROUS"}
            report += f"Danger Level: {level_names.get(best_summary.get('danger_level', 1), 'UNKNOWN')}\n"
            report += f"Script Purpose: {best_summary.get('script_purpose', 'N/A')}\n"
            report += f"Analysis Summary: {best_summary.get('analysis_summary', 'N/A')}\n"
            report += f"Confidence Score: {best_summary.get('confidence_score', 'N/A')}%\n"
        
        if self.all_issues:
            report += f"\n=== DETECTED PATTERNS ({len(self.all_issues)}) ===\n"
            for i, (filepath, issue) in enumerate(self.all_issues, 1):
                report += f"{i}. File: {filepath}\n   Pattern: {issue['pattern']} (Line: {issue['line']})\n   Description: {issue['description']}\n\n"
        
        report += "\n=== SCANNED FILES ===\n"
        for i, file in enumerate(self.scanned_files, 1):
            report += f"{i}. {file}\n"
        report += "\n=== END OF REPORT ===\n"
        return report

    @discord.ui.button(label='📄 Export Report', style=discord.ButtonStyle.secondary, emoji='📄')
    async def export_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            report_content = await self._create_scan_report()
            report_file = discord.File(io.StringIO(report_content), filename=f"scan_report_{self.filename}.txt")
            await interaction.followup.send("Ini laporan lengkap hasil scan:", file=report_file, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error membuat laporan: {e}", ephemeral=True)

    @discord.ui.button(label='🔍 Detail Analysis', style=discord.ButtonStyle.primary, emoji='🔍')
    async def detail_analysis(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title=f"🔍 Detail Analysis: {self.filename}", color=0x3498db)
        if self.ai_results:
            ai_detail = "".join([f"**{i+1}. {res.get('ai_type', 'AI')}** (Confidence: {res.get('confidence_score', 'N/A')}%)\nPurpose: {res.get('script_purpose', 'N/A')[:100]}\n\n" for i, res in enumerate(self.ai_results[:3])])
            embed.add_field(name="🤖 AI Analysis Details", value=ai_detail.strip(), inline=False)
        if self.all_issues:
            pattern_detail = "".join([f"**{i+1}.** `{issue['pattern']}` di `{fp}` L:{issue['line']}\n" for i, (fp, issue) in enumerate(self.all_issues[:10])])
            if len(self.all_issues) > 10:
                pattern_detail += f"... dan {len(self.all_issues) - 10} lainnya."
            embed.add_field(name=f"📋 Pattern Details ({len(self.all_issues)})", value=pattern_detail.strip()[:1024], inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label='📊 JSON Export', style=discord.ButtonStyle.success, emoji='📊')
    async def json_export(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            json_data = {
                "scan_info": {"filename": self.filename, "timestamp": datetime.now().isoformat()},
                "results": {"ai_summaries": self.ai_summaries, "detected_issues": [{"file": fp, **issue} for fp, issue in self.all_issues]},
                "scanned_files": self.scanned_files
            }
            json_str = json.dumps(json_data, indent=2, ensure_ascii=False)
            json_file = discord.File(io.StringIO(json_str), filename=f"scan_data_{self.filename}.json")
            await interaction.followup.send("📊 **JSON Data Export**", file=json_file, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error membuat JSON: {e}", ephemeral=True)


# ============================
# KELAS COG UTAMA
# ============================
class ScannerCog(commands.Cog, name="Scanner"):
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        self.processing_queue = asyncio.Queue(maxsize=self.config.QUEUE_MAX_SIZE)
        self.file_cache = {}
        self.scan_stats = {"total_scans": 0, "dangerous_files": 0, "safe_files": 0}
        
        self.deepseek_key_cycler = itertools.cycle(self.config.DEEPSEEK_API_KEYS) if self.config.DEEPSEEK_API_KEYS else None
        self.gemini_key_cycler = itertools.cycle(self.config.GEMINI_API_KEYS) if self.config.GEMINI_API_KEYS else None
        self.openai_key_cycler = itertools.cycle(self.config.OPENAI_API_KEYS) if self.config.OPENAI_API_KEYS else None

        # --- [PERUBAHAN 1: Multiple Keys] ---
        # Memuat OpenRouter dan AgentRouter keys sebagai list
        self.openrouter_keys = [k.strip() for k in os.getenv("OPENROUTER_API_KEY", "").split(',') if k.strip()]
        self.agentrouter_keys = [k.strip() for k in os.getenv("AGENTROUTER_API_KEY", "").split(',') if k.strip()]

        self.openrouter_key_cycler = itertools.cycle(self.openrouter_keys) if self.openrouter_keys else None
        self.agentrouter_key_cycler = itertools.cycle(self.agentrouter_keys) if self.agentrouter_keys else None

        if self.openrouter_keys:
            self.openrouter_headers = {
                "HTTP-Referer": getattr(self.config, 'OPENROUTER_SITE_URL', 'http://localhost'),
                "X-Title": getattr(self.config, 'OPENROUTER_SITE_NAME', 'MBOT'),
            }
            logger.info(f"✅ OpenRouter keys ({len(self.openrouter_keys)}) dimuat untuk Scanner.")
        else:
            logger.warning("⚠️ OpenRouter API keys (OPENROUTER_API_KEY) tidak ditemukan di config.")
            
        if self.agentrouter_keys:
            logger.info(f"✅ AgentRouter keys ({len(self.agentrouter_keys)}) dimuat untuk Scanner.")
        else:
            logger.warning("⚠️ AgentRouter API keys (AGENTROUTER_API_KEY) tidak ditemukan di config.")
        # --- [AKHIR PERUBAHAN 1] ---

        self.cleanup_task.start()
        logger.info("✅ Scanner Cog loaded, cleanup task started.")
    
    def cog_unload(self):
        self.cleanup_task.cancel()
        logger.info("🛑 Scanner Cog unloaded, cleanup task stopped.")

    # ============================
    # FUNGSI-FUNGSI HELPER
    # ============================
    def _get_file_hash(self, content: bytes) -> str: 
        return hashlib.sha256(content).hexdigest()

    def _is_cache_valid(self, timestamp: float) -> bool: 
        return time.time() - timestamp < (self.config.CACHE_EXPIRE_HOURS * 3600)

    def _get_level_emoji_color(self, level: int) -> Tuple[str, int]:
        if level == DangerLevel.SAFE: return "🟢", 0x00FF00
        if level == DangerLevel.SUSPICIOUS: return "🟡", 0xFFFF00
        if level == DangerLevel.VERY_SUSPICIOUS: return "🟠", 0xFF8C00
        return "🔴", 0xFF0000

    def _create_progress_bar(self, current: int, total: int, length: int = 15) -> str:
        if total == 0: return "█" * length
        filled = int(length * current / total)
        percentage = int(100 * current / total)
        return f"[{'█' * filled}{'▒' * (length - filled)}] {percentage}%"
    
    def _get_file_metadata(self, file_path: str) -> Dict:
        try:
            stats = os.stat(file_path)
            return {
                "size": stats.st_size,
                "modified": datetime.fromtimestamp(stats.st_mtime).isoformat(),
                "extension": os.path.splitext(file_path)[1].lower()
            }
        except Exception as e:
            logger.error(f"Error getting file metadata: {e}")
            return {}

    async def _download_from_url(self, url: str) -> Tuple[bytes, str]:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200: raise Exception(f"HTTP {response.status}")
                if int(response.headers.get('content-length', 0)) > self.config.MAX_FILE_SIZE_MB * 1024 * 1024:
                    raise Exception(f"File terlalu besar (>{self.config.MAX_FILE_SIZE_MB}MB)")
                
                content = await response.read()
                if len(content) > self.config.MAX_FILE_SIZE_MB * 1024 * 1024:
                    raise Exception(f"File terlalu besar (>{self.config.MAX_FILE_SIZE_MB}MB)")
                
                filename = os.path.basename(urlparse(url).path) or "downloaded_file"
                return content, filename

    def _extract_archive(self, file_path: str, extract_to: str) -> bool:
        file_count = 0
        allowed_ext = tuple(self.config.ALLOWED_EXTENSIONS)
        try:
            if file_path.endswith('.zip'):
                with zipfile.ZipFile(file_path, 'r') as zf:
                    members = [m for m in zf.namelist() if m.endswith(allowed_ext) and not m.startswith('__MACOSX/')][:self.config.MAX_ARCHIVE_FILES]
                    for member in members: zf.extract(member, extract_to); file_count += 1
            elif file_path.endswith('.7z'):
                with py7zr.SevenZipFile(file_path, mode='r') as szf:
                    members = [m.filename for m in szf.files if m.filename.endswith(allowed_ext)][:self.config.MAX_ARCHIVE_FILES]
                    for member in members: szf.extract(targets=member, path=extract_to); file_count += 1
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

    # Fungsi analisis OpenRouter dan AgentRouter (tetap sama)
    async def _analyze_with_openrouter(self, code_snippet: str, api_key: str) -> Dict:
        """Menganalisis kode dengan OpenRouter."""
        async with httpx.AsyncClient(timeout=45.0) as client:
            payload = {
                "model": "mistralai/mistral-7b-instruct:free", # Model Teks Gratis
                "messages": [{"role": "user", "content": AI_PROMPT.format(code_snippet=code_snippet[:3000])}],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
                "max_tokens": 2048
            }
            headers = {"Authorization": f"Bearer {api_key}"}
            if hasattr(self, 'openrouter_headers'):
                headers.update(self.openrouter_headers)

            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            response_json = response.json()
            response_content = response_json["choices"][0]["message"]["content"]
            cleaned_response = re.sub(r'```json\s*|\s*```', '', response_content.strip(), flags=re.DOTALL)
            return json.loads(cleaned_response)

    async def _analyze_with_agentrouter(self, code_snippet: str, api_key: str) -> Dict:
        """Menganalisis kode dengan AgentRouter."""
        client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://agentrouter.org/v1",
            timeout=45.0
        )
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": AI_PROMPT.format(code_snippet=code_snippet[:3000])}],
            response_format={"type": "json_object"}, 
            temperature=0.0
        )
        response_content = response.choices[0].message.content
        cleaned_response = re.sub(r'```json\s*|\s*```', '', response_content.strip(), flags=re.DOTALL)
        return json.loads(cleaned_response)

    # Fungsi analisis DeepSeek, OpenAI, Gemini (tetap sama)
    async def _analyze_with_deepseek(self, code_snippet: str, api_key: str) -> Dict:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": AI_PROMPT.format(code_snippet=code_snippet[:3000])}], "response_format": {"type": "json_object"}, "temperature": 0.0},
                headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            return json.loads(response.json()["choices"][0]["message"]["content"])

    async def _analyze_with_openai(self, code_snippet: str, api_key: str) -> Dict:
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": AI_PROMPT.format(code_snippet=code_snippet[:3000])}],
            response_format={"type": "json_object"}, temperature=0.0
        )
        return json.loads(response.choices[0].message.content)

    async def _analyze_with_gemini(self, code_snippet: str, api_key: str) -> Dict:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = await model.generate_content_async(
            AI_PROMPT.format(code_snippet=code_snippet[:3000]),
             generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.0
             )
        )
        cleaned_response = re.sub(r'```json\s*|\s*```', '', response.text.strip(), flags=re.DOTALL)
        return json.loads(cleaned_response)

    def _analyze_manually(self, detected_issues: List[Dict]) -> Dict:
        if not detected_issues: return {"script_purpose": "Tidak ada pola mencurigakan", "analysis_summary": "Analisis manual tidak menemukan pola berbahaya.", "confidence_score": 85}
        summary = f"Ditemukan {len(detected_issues)} pola mencurigakan. Pola paling berbahaya memiliki level {max(i['level'] for i in detected_issues)}."
        return {"script_purpose": "Analisis manual berbasis pola", "analysis_summary": summary, "confidence_score": 75}


    # --- [PERUBAHAN 3: Fallback & Ephemeral Error] ---
    async def _get_ai_analysis_with_fallback(
        self,
        code_snippet: str,
        detected_issues: List[Dict],
        choice: str,
        loading_msg: discord.Message,
        ctx_or_msg: Union[commands.Context, discord.Message] # Tambahkan parameter ini
    ) -> Tuple[Dict, str, List[Dict]]:
        """Mendapatkan analisis AI menggunakan fallback chain, atau hanya manual."""
        
        # Jika 'manual', langsung gunakan manual
        if choice == 'manual':
            manual_result = self._analyze_manually(detected_issues)
            manual_result['ai_type'] = "Manual"
            return manual_result, "Manual", [manual_result]
        
        # Tentukan urutan AI berdasarkan 'choice'
        analysts_to_try = []
        is_command = isinstance(ctx_or_msg, commands.Context) # Cek apakah ini dari command

        if choice == 'auto':
            if self.openrouter_key_cycler: analysts_to_try.append(("OpenRouter", self.openrouter_key_cycler, self._analyze_with_openrouter))
            if self.agentrouter_key_cycler: analysts_to_try.append(("AgentRouter", self.agentrouter_key_cycler, self._analyze_with_agentrouter))
            if self.openai_key_cycler: analysts_to_try.append(("OpenAI", self.openai_key_cycler, self._analyze_with_openai))
            if self.gemini_key_cycler: analysts_to_try.append(("Gemini", self.gemini_key_cycler, self._analyze_with_gemini))
            if self.deepseek_key_cycler: analysts_to_try.append(("DeepSeek", self.deepseek_key_cycler, self._analyze_with_deepseek))
        elif choice == 'openrouter' and self.openrouter_key_cycler: analysts_to_try.append(("OpenRouter", self.openrouter_key_cycler, self._analyze_with_openrouter))
        elif choice == 'agentrouter' and self.agentrouter_key_cycler: analysts_to_try.append(("AgentRouter", self.agentrouter_key_cycler, self._analyze_with_agentrouter))
        elif choice == 'openai' and self.openai_key_cycler: analysts_to_try.append(("OpenAI", self.openai_key_cycler, self._analyze_with_openai))
        elif choice == 'gemini' and self.gemini_key_cycler: analysts_to_try.append(("Gemini", self.gemini_key_cycler, self._analyze_with_gemini))
        elif choice == 'deepseek' and self.deepseek_key_cycler: analysts_to_try.append(("DeepSeek", self.deepseek_key_cycler, self._analyze_with_deepseek))

        if not analysts_to_try:
            logger.warning(f"Tidak ada analis AI yang tersedia untuk pilihan '{choice}', menggunakan manual.")
            manual_result = self._analyze_manually(detected_issues)
            manual_result['ai_type'] = "Manual"
            return manual_result, "Manual", [manual_result]
        
        # Loop fallback chain
        for name, keys, analyzer_func in analysts_to_try:
            try:
                # Jaga pesan loading tetap generik
                await loading_msg.edit(content=f"🧠 Menganalisis dengan {name}...")
                key = next(keys)
                result = await analyzer_func(code_snippet, key)
                result['ai_type'] = name
                logger.info(f"Analisis AI ({name}) berhasil.")
                return result, name, [result] # Sukses
            except Exception as e:
                logger.warning(f"====== SCANNER: {name} GAGAL: {e} ======")
                # Kirim notifikasi kegagalan secara EPHEMERAL jika ini dari command
                if is_command:
                    try:
                        # Coba kirim ephemeral, jika gagal (misal interaksi lama), abaikan
                        await ctx_or_msg.send(f"⚠️ {name} gagal, mencoba fallback berikutnya...", ephemeral=True, delete_after=10)
                    except Exception as send_error:
                         logger.warning(f"Gagal mengirim notifikasi fallback ephemeral: {send_error}")
                         pass # Lanjutkan fallback tanpa notifikasi ephemeral
                # JANGAN edit loading_msg publik dengan error spesifik
                await asyncio.sleep(1) # Jeda singkat

        # Jika semua AI gagal
        logger.error("Semua API AI gagal untuk Scanner setelah fallback.")
        try:
            await loading_msg.edit(content="⚠️ Semua AI gagal dihubungi. Menggunakan analisis manual...")
        except discord.NotFound:
            pass
        
        manual_result = self._analyze_manually(detected_issues)
        manual_result['ai_type'] = "Manual"
        return manual_result, "Manual", [manual_result]
    # --- [AKHIR PERUBAHAN 3] ---


    # ============================
    # PROSES INTI SCAN
    # ============================
    async def _scan_file_content(
        self,
        file_path: str,
        file_content: bytes,
        choice: str,
        loading_msg: discord.Message,
        ctx_or_msg: Union[commands.Context, discord.Message] # Tambahkan parameter ini
    ) -> Tuple[List[Dict], Dict, str, List[Dict]]:
        
        file_hash = self._get_file_hash(file_content)
        cache_key = f"{file_hash}_{choice}"
        
        if cache_key in self.file_cache and self._is_cache_valid(self.file_cache[cache_key]['timestamp']):
            cached = self.file_cache[cache_key]
            logger.info(f"Menggunakan cache untuk {os.path.basename(file_path)}")
            return cached['issues'], cached['summary'], cached['analyst'], cached['results']

        content_str = file_content.decode('utf-8', errors='ignore')
        issues = []
        for pattern, info in SUSPICIOUS_PATTERNS.items():
            try:
                matches = re.finditer(pattern, content_str, re.IGNORECASE)
                for match in matches:
                    line_num = content_str[:match.start()].count('\n') + 1
                    issues.append({'pattern': pattern, 'line': line_num, **info})
            except re.error as e:
                logger.error(f"Regex error pada pattern '{pattern}': {e}")

        # --- [PERUBAHAN 5: Pass ctx_or_msg] ---
        summary, analyst, results = await self._get_ai_analysis_with_fallback(
            content_str,
            issues,
            choice,
            loading_msg,
            ctx_or_msg # <-- Diteruskan
        )
        # --- [AKHIR PERUBAHAN 5] ---
        
        detected_max_level = max([i['level'] for i in issues], default=DangerLevel.SAFE)
        summary['danger_level'] = detected_max_level

        self.file_cache[cache_key] = {'issues': issues, 'summary': summary, 'analyst': analyst, 'results': results, 'timestamp': time.time()}
        return issues, summary, analyst, results

    async def _process_analysis(self, ctx_or_msg, attachment: discord.Attachment = None, choice: str = "auto", url: str = None):
        
        is_command = isinstance(ctx_or_msg, commands.Context)
        author_id = ctx_or_msg.author.id
        channel = ctx_or_msg.channel
        
        if not self._check_limits(author_id, channel.id, "scan", is_command): 
            return
        
        await self.processing_queue.put(author_id)
        loading_msg = None
        download_path = None
        
        msg_id = ctx_or_msg.id if not is_command else ctx_or_msg.message.id
        extract_folder = os.path.join(self.config.TEMP_DIR, f"extracted_{msg_id}")

        try:
            file_content, filename = await self._get_file_source(ctx_or_msg, attachment, url, is_command)
            if not filename: return

            loading_msg = await channel.send(f"⚙️ Menganalisis `{filename}`...")
            
            if is_command:
                increment_daily_usage(author_id)
                self.scan_stats["total_scans"] += 1
            
            download_path = os.path.join(self.config.TEMP_DIR, filename)
            with open(download_path, 'wb') as f: f.write(file_content)

            all_issues, all_summaries, all_results, analysts, scanned_files = [], [], [], set(), []
            scan_paths = self._prepare_scan_paths(download_path, filename, extract_folder)
            total_files = len(scan_paths)
            
            for i, (file_path, display_name) in enumerate(scan_paths):
                if total_files > 1: await loading_msg.edit(content=f"🔍 Scanning {self._create_progress_bar(i, total_files)} `{display_name}`")
                with open(file_path, 'rb') as f_content:
                    # --- [PERUBAHAN 6: Pass ctx_or_msg] ---
                    issues, summary, analyst, results = await self._scan_file_content(
                        file_path,
                        f_content.read(),
                        choice,
                        loading_msg,
                        ctx_or_msg # <-- Diteruskan
                    )
                    # --- [AKHIR PERUBAHAN 6] ---
                
                scanned_files.append(display_name); analysts.add(analyst)
                if issues: all_issues.extend([(display_name, issue) for issue in issues])
                if summary: all_summaries.append(summary); all_results.extend(results)

            await self._finalize_and_send_report(ctx_or_msg, loading_msg, filename, all_summaries, all_issues, scanned_files, analysts, all_results, download_path, is_command)
        
        except Exception as e:
            logger.error(f"Gagal proses analisis: {e}", exc_info=True)
            error_msg = f"❌ Error: {str(e)[:500]}"
            if loading_msg: await loading_msg.edit(content=error_msg, embed=None, view=None)
            else: await channel.send(error_msg)
        finally:
            if not self.processing_queue.empty(): self.processing_queue.get_nowait()
            if download_path and os.path.exists(download_path): os.remove(download_path)
            if os.path.exists(extract_folder): shutil.rmtree(extract_folder)

    def _check_limits(self, author_id: int, channel_id: int, command_name: str, is_command: bool) -> bool:
        can_proceed, cooldown = check_user_cooldown(author_id, command_name, self.config.COMMAND_COOLDOWN_SECONDS)
        if not can_proceed:
            if is_command:
                asyncio.create_task(self.bot.get_channel(channel_id).send(f"⏳ Cooldown, tunggu {cooldown} detik lagi."))
            return False
        
        if is_command and command_name == "scan" and not check_daily_limit(author_id, self.config.DAILY_LIMIT_PER_USER):
            asyncio.create_task(self.bot.get_channel(channel_id).send(f"❌ Batas harian ({self.config.DAILY_LIMIT_PER_USER}) tercapai."))
            return False
        
        if self.config.ALLOWED_CHANNEL_IDS and channel_id not in self.config.ALLOWED_CHANNEL_IDS:
            if is_command:
                asyncio.create_task(self.bot.get_channel(channel_id).send("❌ Perintah ini tidak diizinkan di channel ini.", delete_after=10))
            return False

        if self.processing_queue.full():
            if is_command:
                asyncio.create_task(self.bot.get_channel(channel_id).send("⏳ Server sibuk, coba lagi nanti."))
            return False
        return True

    async def _get_file_source(self, ctx_or_msg, attachment, url, is_command) -> Tuple[bytes, str]:
        if url: return await self._download_from_url(url)
        
        target_attachment = attachment
        if not is_command:
             target_attachment = ctx_or_msg.message.attachments[0] if ctx_or_msg.message.attachments else None
        
        if target_attachment:
            if target_attachment.size > self.config.MAX_FILE_SIZE_MB * 1024 * 1024: raise Exception(f"File >{self.config.MAX_FILE_SIZE_MB}MB")
            if not any(target_attachment.filename.lower().endswith(ext) for ext in self.config.ALLOWED_EXTENSIONS): raise Exception("Format file tidak didukung")
            return await target_attachment.read(), target_attachment.filename
        
        raise Exception("Tidak ada file atau URL diberikan")

    def _prepare_scan_paths(self, download_path: str, filename: str, extract_folder: str) -> List[Tuple[str, str]]:
        scan_paths = []
        if filename.lower().endswith(('.zip', '.7z', '.rar')):
            if self._extract_archive(download_path, extract_folder):
                for root, _, files in os.walk(extract_folder):
                    for file in files:
                        full_path = os.path.join(root, file)
                        relative_path = os.path.relpath(full_path, extract_folder)
                        scan_paths.append((full_path, relative_path))
        else:
            scan_paths.append((download_path, filename))
        return scan_paths[:self.config.MAX_ARCHIVE_FILES]
    
    async def _finalize_and_send_report(self, ctx_or_msg, msg, filename, summaries, issues, scanned_files, analysts, results, download_path, is_command):
        best_summary = max(summaries, key=lambda x: x.get('danger_level', 0), default={})
        max_level = best_summary.get('danger_level', DangerLevel.SAFE)
        
        if is_command:
            if max_level >= DangerLevel.DANGEROUS: self.scan_stats["dangerous_files"] += 1
            elif max_level == DangerLevel.SAFE: self.scan_stats["safe_files"] += 1

        emoji, color = self._get_level_emoji_color(max_level)
        embed = self._create_result_embed(filename, best_summary, max_level, emoji, color, issues, scanned_files, analysts, download_path)
        view = ScanResultView(filename, issues, summaries, analysts, scanned_files, results)
        await msg.edit(content=None, embed=embed, view=view)
        
        with open(download_path, 'rb') as f:
            file_hash = self._get_file_hash(f.read())
        
        save_scan_history(ctx_or_msg.author.id, filename, file_hash, max_level, ", ".join(sorted(analysts)), ctx_or_msg.channel.id)

        if (is_command or max_level >= DangerLevel.DANGEROUS) and self.config.ALERT_CHANNEL_ID:
            alert_channel = self.bot.get_channel(self.config.ALERT_CHANNEL_ID)
            if alert_channel: 
                await alert_channel.send(f"🚨 **PERINGATAN** oleh {ctx_or_msg.author.mention} di {ctx_or_msg.channel.mention}", embed=embed)

    def _create_result_embed(self, filename, best_summary, max_level, emoji, color, all_issues, scanned_files, analysts, download_path):
        level_titles = {1: "✅ AMAN", 2: "🤔 MENCURIGAKAN", 3: "⚠️ SANGAT MENCURIGAKAN", 4: "🚨 BAHAYA TINGGI"}
        embed = discord.Embed(color=color, title=f"{emoji} **{level_titles.get(max_level, 'HASIL SCAN')}**")
        embed.description = (f"**File:** `{filename}`\n"
                             f"**Tujuan Script:** {best_summary.get('script_purpose', 'N/A')}\n"
                             f"**Analisis:** {best_summary.get('analysis_summary', 'N/A')[:500]}")
        
        if best_summary.get('confidence_score'):
            embed.add_field(name="🎯 Confidence", value=f"{best_summary['confidence_score']}%", inline=True)
        
        metadata = self._get_file_metadata(download_path)
        if metadata:
            embed.add_field(name="📊 File Info", value=f"Size: {metadata.get('size', 0):,} bytes\nType: {metadata.get('extension', 'N/A')}", inline=True)

        if all_issues:
            value = "".join([f"- `{i['pattern']}` di `{fp}` (L{i['line']})\n" for fp, i in all_issues[:5]])
            if len(all_issues) > 5: value += f"... dan {len(all_issues) - 5} lainnya."
            embed.add_field(name=f"📝 Pola Terdeteksi ({len(all_issues)})", value=value, inline=False)
        
        embed.set_footer(text=f"Dianalisis oleh: {', '.join(sorted(analysts))} • {len(scanned_files)} file diperiksa")
        return embed

    # ============================
    # PERINTAH-PERINTAH BOT
    # ============================
    @commands.command(name="scan")
    async def scan_command(self, ctx, analyst: str = "auto", *, url: str = None):
        """Memindai file atau URL dengan analis pilihan."""
        
        # --- [PERUBAHAN 7: Update valid_analysts] ---
        valid_analysts = ["auto", "deepseek", "gemini", "openai", "manual", "openrouter", "agentrouter"]
        # --- [AKHIR PERUBAHAN 7] ---

        if urlparse(analyst).scheme in ['http', 'https']:
            url = f"{analyst} {url}" if url else analyst
            analyst = "auto"
        
        if analyst.lower() not in valid_analysts:
            return await ctx.send(f"❌ Analis tidak valid. Pilihan: `{', '.join(valid_analysts)}`")

        if not ctx.message.attachments and not url:
            embed = discord.Embed(title="📎 Butuh File atau URL", description="Upload file bersamaan dengan perintah ini atau berikan URL untuk dipindai.", color=0x3498db)
            return await ctx.send(embed=embed)

        attachment_to_scan = ctx.message.attachments[0] if ctx.message.attachments else None
        await self._process_analysis(ctx, attachment_to_scan, analyst.lower(), url)

    @commands.command(name="history")
    async def history_command(self, ctx, limit: int = 5):
        """Melihat riwayat scan Anda."""
        if not self._check_limits(ctx.author.id, ctx.channel.id, "history", is_command=True): return
        limit = min(max(1, limit), 20)
        
        try:
            conn = self.bot.get_cog("Scanner").bot.db_connection
            if not conn or conn.closed != 0:
                logger.error("Koneksi DB (history) tidak tersedia.")
                conn = self.bot.get_cog("Scanner").bot.get_db_connection()
                if not conn:
                     return await ctx.send("❌ Gagal terhubung ke database riwayat.")

            cursor = conn.cursor()
            cursor.execute("SELECT filename, danger_level, timestamp FROM scan_history WHERE user_id = %s ORDER BY timestamp DESC LIMIT %s", (ctx.author.id, limit))
            results = cursor.fetchall()
            cursor.close()
        except Exception as e:
            logger.error(f"Gagal mengambil history: {e}")
            return await ctx.send("❌ Gagal mengambil data riwayat dari database.")

        if not results: return await ctx.send("📋 Tidak ada riwayat scan ditemukan.")
        
        embed = discord.Embed(title=f"📋 Riwayat Scan - {ctx.author.display_name}", color=0x3498db)
        desc = "".join([f"{self._get_level_emoji_color(level)[0]} `{fn[:30]}` - <t:{int(ts.timestamp())}:R>\n" for fn, level, ts in results])
        embed.description = desc
        await ctx.send(embed=embed)

    @commands.command(name="stats")
    async def stats_command(self, ctx):
        """Melihat statistik bot dan penggunaan Anda."""
        if not self._check_limits(ctx.author.id, ctx.channel.id, "stats", is_command=True): return
        
        embed = discord.Embed(title="📊 Statistik Bot Scanner", color=0x3498db)
        
        # User Stats from DB
        try:
            conn = self.bot.get_cog("Scanner").bot.db_connection
            if not conn or conn.closed != 0:
                logger.error("Koneksi DB (stats) tidak tersedia.")
                conn = self.bot.get_cog("Scanner").bot.get_db_connection()
                if not conn:
                     return await ctx.send("❌ Gagal terhubung ke database statistik.")

            cursor = conn.cursor()
            cursor.execute("SELECT count FROM daily_usage WHERE user_id = %s AND date = %s", (ctx.author.id, datetime.now().strftime('%Y-%m-%d')))
            user_daily = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM scan_history WHERE user_id = %s", (ctx.author.id,))
            user_total = cursor.fetchone()
            cursor.close()
            
            user_daily_count = user_daily[0] if user_daily else 0
            user_total_count = user_total[0] if user_total else 0
        except Exception as e:
            logger.error(f"Gagal mengambil stats: {e}")
            return await ctx.send("❌ Gagal mengambil data statistik dari database.")

        embed.add_field(name="👤 Statistik Anda", value=f"Scan hari ini: {user_daily_count}/{self.config.DAILY_LIMIT_PER_USER}\nTotal scan: {user_total_count}", inline=True)
        
        # Global Stats
        uptime_seconds = time.time() - self.bot.start_time
        uptime = str(timedelta(seconds=int(uptime_seconds)))
        embed.add_field(name="🌍 Statistik Global", value=f"Total scan (sejak restart): {self.scan_stats['total_scans']}\nFile berbahaya (sejak restart): {self.scan_stats['dangerous_files']}\nUptime: {uptime}", inline=True)
        
        # API Status
        api_status = ""
        # --- [PERUBAHAN 8: Tampilkan jumlah keys] ---
        if self.openrouter_keys: api_status += f"🌀 OpenRouter: {len(self.openrouter_keys)} keys\n"
        if self.agentrouter_keys: api_status += f"🚀 AgentRouter: {len(self.agentrouter_keys)} keys\n"
        # --- [AKHIR PERUBAHAN 8] ---
        if self.config.OPENAI_API_KEYS: api_status += f"🤖 OpenAI: {len(self.config.OPENAI_API_KEYS)} keys\n"
        if self.config.GEMINI_API_KEYS: api_status += f"🧠 Gemini: {len(self.config.GEMINI_API_KEYS)} keys\n"
        if self.config.DEEPSEEK_API_KEYS: api_status += f"🌊 DeepSeek: {len(self.config.DEEPSEEK_API_KEYS)} keys\n"
        embed.add_field(name="🔑 API Status", value=api_status or "Manual only", inline=False)
        
        await ctx.send(embed=embed)
        
    @commands.command(name="clearcache", hidden=True)
    @commands.is_owner()
    async def clearcache_command(self, ctx):
        """Membersihkan cache bot (owner only)."""
        cache_count = len(self.file_cache)
        self.file_cache.clear()
        await ctx.send(f"🧹 Cache dibersihkan. {cache_count} entri dihapus.", delete_after=10)

    # ============================
    # BACKGROUND TASK & LISTENERS
    # ============================
    @tasks.loop(hours=1)
    async def cleanup_task(self):
        # Clean expired cache
        expired_keys = [k for k, v in self.file_cache.items() if not self._is_cache_valid(v.get('timestamp', 0))]
        for key in expired_keys: del self.file_cache[key]
        if expired_keys: logger.info(f"🧹 Membersihkan {len(expired_keys)} cache yang kedaluwarsa.")
        
        # Clean old temp files
        cleaned_files = 0
        for item in os.listdir(self.config.TEMP_DIR):
            item_path = os.path.join(self.config.TEMP_DIR, item)
            try:
                if os.path.getmtime(item_path) < time.time() - 3600:
                    if os.path.isfile(item_path): os.remove(item_path)
                    elif os.path.isdir(item_path): shutil.rmtree(item_path)
                    cleaned_files += 1
            except Exception as e:
                logger.error(f"Gagal membersihkan file temp {item_path}: {e}")
        if cleaned_files > 0: logger.info(f"🧹 Membersihkan {cleaned_files} file/folder temp.")

    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.attachments or message.content.startswith(self.bot.command_prefix): 
            return
        
        # Wrapper context untuk auto-scan
        class FakeContext:
            def __init__(self, msg, bot_instance): 
                self.message = msg
                self.author = msg.author
                self.channel = msg.channel
                self.bot = bot_instance
                self.id = msg.id 
            async def send(self, *args, **kwargs): return await self.channel.send(*args, **kwargs)

        # --- [PERUBAHAN 9: Auto-scan selalu 'manual'] ---
        await self._process_analysis(FakeContext(message, self.bot), choice='manual')
        # --- [AKHIR PERUBAHAN 9] ---

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if ctx.cog is not self: return
            
        if isinstance(error, commands.CommandNotFound): return
        if isinstance(error, (commands.MissingPermissions, commands.NotOwner)):
            await ctx.send("❌ Anda tidak punya izin untuk menggunakan perintah ini.", ephemeral=True) # Ephemeral
        elif isinstance(error, commands.CommandInvokeError):
            logger.error(f"Error pada perintah {ctx.command}: {error.original}", exc_info=True)
            await ctx.send(f"❌ Terjadi kesalahan saat menjalankan perintah: `{str(error.original)[:500]}`", ephemeral=True) # Ephemeral
        elif isinstance(error, commands.CommandOnCooldown):
             await ctx.send(f"⏳ Cooldown. Coba lagi dalam **{error.retry_after:.1f} detik**.", ephemeral=True, delete_after=10) # Ephemeral
        else:
            logger.error(f"Error tidak dikenal pada perintah {ctx.command}: {error}", exc_info=True)
            await ctx.send("❌ Terjadi kesalahan internal.", ephemeral=True) # Ephemeral

async def setup(bot):
    if not os.path.exists(bot.config.TEMP_DIR):
        os.makedirs(bot.config.TEMP_DIR)
        
    # --- [PERUBAHAN 10: Koneksi DB] --- (Tidak berubah, hanya memastikan ada)
    if not hasattr(bot, 'db_connection') or not hasattr(bot, 'get_db_connection'):
        try:
            from utils.database import get_db_connection
            bot.get_db_connection = get_db_connection
            bot.db_connection = get_db_connection()
            if bot.db_connection:
                 logger.info("Koneksi DB berhasil dilampirkan ke bot dari Scanner.")
            else:
                 logger.error("Gagal melampirkan koneksi DB ke bot dari Scanner.")
        except ImportError:
             logger.error("Gagal impor 'get_db_connection' di scanner setup.")
    # --- [AKHIR PERUBAHAN 10] ---

    await bot.add_cog(ScannerCog(bot))

