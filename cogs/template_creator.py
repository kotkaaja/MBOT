# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
import json
import re
from typing import Optional, Dict, List
import httpx
from openai import AsyncOpenAI
import google.generativeai as genai

logger = logging.getLogger(__name__)

# ============================
# KONSTANTA & PROMPT AI
# ============================
AI_TEMPLATE_PROMPT = """
Kamu adalah expert Lua script writer untuk game roleplay SAMP (San Andreas Multiplayer). 
Buatkan rangkaian Auto RP yang realistis dan detail sesuai dengan tema: "{theme}"

Detail tambahan: {details}

ATURAN PENTING:
1. Buat 3-7 langkah RP yang logis dan natural
2. Gunakan /me dan /do secara bergantian untuk variasi
3. Delay antar langkah 2-4 detik (logis sesuai aksi)
4. Jangan gunakan emoji atau karakter special
5. Maksimal 100 karakter per langkah
6. Gunakan bahasa Indonesia yang natural dan tidak kaku

Contoh format output JSON:
{{
  "steps": [
    {{"command": "/me membuka pintu mobil dengan perlahan", "delay": 2}},
    {{"command": "/do Pintu mobil terbuka dengan bunyi khas", "delay": 3}},
    {{"command": "/me masuk ke dalam mobil dan menutup pintunya", "delay": 2}}
  ]
}}

Output HANYA JSON tanpa penjelasan tambahan.
"""

# Mapping ID senjata untuk Gun RP
WEAPON_LIST = {
    22: "Pistol", 23: "Silenced Pistol", 24: "Desert Eagle",
    25: "Shotgun", 26: "Sawn-Off", 27: "Combat Shotgun",
    28: "Uzi", 29: "MP5", 30: "AK-47", 31: "M4", 32: "Tec-9",
    33: "Rifle", 34: "Sniper Rifle"
}

# ============================
# UI COMPONENTS
# ============================
class PlatformSelectView(discord.ui.View):
    """View untuk memilih platform (PC/Mobile)"""
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.platform = None
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Tombol ini bukan untuk Anda!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="💻 PC (KHP)", style=discord.ButtonStyle.primary, emoji="💻")
    async def pc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.platform = "pc"
        await interaction.response.send_message("✅ **Platform dipilih:** PC (KotkaHelper v1.3.2)", ephemeral=True)
        self.stop()

    @discord.ui.button(label="📱 Mobile (KHMobile)", style=discord.ButtonStyle.success, emoji="📱")
    async def mobile_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.platform = "mobile"
        await interaction.response.send_message("✅ **Platform dipilih:** Mobile (KotkaHelper Mobile)", ephemeral=True)
        self.stop()


class MacroTypeSelectView(discord.ui.View):
    """View untuk memilih tipe macro"""
    def __init__(self, user_id: int, platform: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.platform = platform
        self.macro_type = None
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Tombol ini bukan untuk Anda!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⌨️ Auto RP Macro", style=discord.ButtonStyle.primary, emoji="⌨️")
    async def auto_rp_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.macro_type = "auto_rp"
        await interaction.response.send_message("✅ **Tipe dipilih:** Auto RP Macro (aktivasi dengan hotkey)", ephemeral=True)
        self.stop()

    @discord.ui.button(label="💬 CMD Macro", style=discord.ButtonStyle.success, emoji="💬")
    async def cmd_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.macro_type = "cmd"
        await interaction.response.send_message("✅ **Tipe dipilih:** CMD Macro (aktivasi dengan command)", ephemeral=True)
        self.stop()

    @discord.ui.button(label="🔫 Gun RP Macro", style=discord.ButtonStyle.danger, emoji="🔫")
    async def gun_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.macro_type = "gun"
        await interaction.response.send_message("✅ **Tipe dipilih:** Gun RP Macro (otomatis saat ganti senjata)", ephemeral=True)
        self.stop()


class HotkeyModal(discord.ui.Modal, title="Pengaturan Hotkey"):
    """Modal untuk input hotkey (Auto RP Macro - PC only)"""
    modifier = discord.ui.TextInput(
        label="Modifier Key (ketik: ALT/SHIFT/CTRL atau -)",
        placeholder="Contoh: ALT atau - (jika tidak pakai modifier)",
        max_length=10,
        required=True
    )
    primary_key = discord.ui.TextInput(
        label="Primary Key (F1-F12, A-Z, 0-9, NUM0-NUM9)",
        placeholder="Contoh: F5",
        max_length=5,
        required=True
    )

    def __init__(self):
        super().__init__()
        self.modifier_value = None
        self.primary_key_value = None

    async def on_submit(self, interaction: discord.Interaction):
        mod = self.modifier.value.strip().upper()
        if mod == "-":
            self.modifier_value = "Tidak Ada"
        elif mod in ["ALT", "SHIFT", "CTRL"]:
            self.modifier_value = mod
        else:
            await interaction.response.send_message("❌ Modifier tidak valid! Gunakan: ALT, SHIFT, CTRL, atau -", ephemeral=True)
            return
        
        key = self.primary_key.value.strip().upper()
        valid_keys = (
            [f"F{i}" for i in range(1, 13)] +
            list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") +
            [str(i) for i in range(10)] +
            [f"NUM{i}" for i in range(10)]
        )
        if key not in valid_keys:
            await interaction.response.send_message(f"❌ Key tidak valid! Gunakan: F1-F12, A-Z, 0-9, atau NUM0-NUM9", ephemeral=True)
            return
        
        self.primary_key_value = key
        combo = f"{self.modifier_value} + {key}" if self.modifier_value != "Tidak Ada" else key
        await interaction.response.send_message(f"✅ **Hotkey diatur:** `{combo}`", ephemeral=True)


class CommandModal(discord.ui.Modal, title="Pengaturan Command"):
    """Modal untuk input command (CMD Macro)"""
    command = discord.ui.TextInput(
        label="Command Pemicu (harus dimulai dengan /)",
        placeholder="Contoh: /mancing",
        max_length=50,
        required=True
    )

    def __init__(self):
        super().__init__()
        self.command_value = None

    async def on_submit(self, interaction: discord.Interaction):
        cmd = self.command.value.strip()
        if not cmd.startswith("/"):
            await interaction.response.send_message("❌ Command harus dimulai dengan `/`", ephemeral=True)
            return
        if len(cmd) < 2:
            await interaction.response.send_message("❌ Command terlalu pendek!", ephemeral=True)
            return
        self.command_value = cmd
        await interaction.response.send_message(f"✅ **Command diatur:** `{cmd}`", ephemeral=True)


class WeaponSelectView(discord.ui.View):
    """View untuk memilih senjata (Gun RP)"""
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.weapon_id = None
        self.action = None
        self.add_weapon_select()
    
    def add_weapon_select(self):
        select = discord.ui.Select(
            placeholder="Pilih jenis senjata...",
            options=[
                discord.SelectOption(label=f"{name} (ID: {wid})", value=str(wid))
                for wid, name in WEAPON_LIST.items()
            ][:25]  # Discord limit 25 options
        )
        select.callback = self.weapon_callback
        self.add_item(select)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Menu ini bukan untuk Anda!", ephemeral=True)
            return False
        return True

    async def weapon_callback(self, interaction: discord.Interaction):
        self.weapon_id = int(interaction.data['values'][0])
        weapon_name = WEAPON_LIST.get(self.weapon_id, "Unknown")
        await interaction.response.send_message(f"✅ **Senjata dipilih:** {weapon_name} (ID: {self.weapon_id})", ephemeral=True)
        # Hapus select dan tambahkan button aksi
        self.clear_items()
        self.add_action_buttons()

    def add_action_buttons(self):
        draw_btn = discord.ui.Button(label="📤 Keluarkan Senjata", style=discord.ButtonStyle.success)
        holster_btn = discord.ui.Button(label="📥 Simpan Senjata", style=discord.ButtonStyle.primary)
        both_btn = discord.ui.Button(label="🔄 Keduanya", style=discord.ButtonStyle.secondary)
        
        draw_btn.callback = lambda i: self.action_callback(i, "draw")
        holster_btn.callback = lambda i: self.action_callback(i, "holster")
        both_btn.callback = lambda i: self.action_callback(i, "both")
        
        self.add_item(draw_btn)
        self.add_item(holster_btn)
        self.add_item(both_btn)

    async def action_callback(self, interaction: discord.Interaction, action: str):
        self.action = action
        action_text = {"draw": "Keluarkan", "holster": "Simpan", "both": "Keluarkan & Simpan"}
        await interaction.response.send_message(f"✅ **Aksi dipilih:** {action_text[action]}", ephemeral=True)
        self.stop()


class ThemeModal(discord.ui.Modal, title="Detail Template RP"):
    """Modal untuk input tema dan detail RP"""
    theme = discord.ui.TextInput(
        label="Tema/Aktivitas RP",
        placeholder="Contoh: Mancing di dermaga, Masuk mobil, Makan di resto",
        max_length=100,
        required=True
    )
    details = discord.ui.TextInput(
        label="Detail Tambahan (opsional)",
        placeholder="Contoh: Suasana malam hari, cuaca hujan, mobil sport",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=False
    )

    def __init__(self):
        super().__init__()
        self.theme_value = None
        self.details_value = None

    async def on_submit(self, interaction: discord.Interaction):
        self.theme_value = self.theme.value.strip()
        self.details_value = self.details.value.strip() or "Tidak ada detail tambahan"
        await interaction.response.send_message(
            f"✅ **Tema diatur:** {self.theme_value}\n**Detail:** {self.details_value[:100]}...",
            ephemeral=True
        )


# ============================
# COG UTAMA
# ============================
class TemplateCreatorCog(commands.Cog, name="TemplateCreator"):
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        self.active_sessions = {}  # user_id -> session_data
    
    async def _get_ai_analysis(self, theme: str, details: str) -> Optional[List[Dict]]:
        """Menggunakan AI untuk generate langkah-langkah RP"""
        prompt = AI_TEMPLATE_PROMPT.format(theme=theme, details=details)
        
        # Coba Gemini dulu (lebih murah)
        if self.config.GEMINI_API_KEYS:
            try:
                genai.configure(api_key=self.config.GEMINI_API_KEYS[0])
                model = genai.GenerativeModel('gemini-1.5-flash')
                response = await model.generate_content_async(prompt)
                cleaned = re.sub(r'```json\s*|\s*```', '', response.text.strip(), flags=re.DOTALL)
                data = json.loads(cleaned)
                return data.get("steps", [])
            except Exception as e:
                logger.warning(f"Gemini gagal: {e}")
        
        # Fallback ke DeepSeek
        if self.config.DEEPSEEK_API_KEYS:
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.post(
                        "https://api.deepseek.com/chat/completions",
                        json={
                            "model": "deepseek-chat",
                            "messages": [{"role": "user", "content": prompt}],
                            "response_format": {"type": "json_object"},
                            "temperature": 0.7
                        },
                        headers={"Authorization": f"Bearer {self.config.DEEPSEEK_API_KEYS[0]}"}
                    )
                    response.raise_for_status()
                    data = json.loads(response.json()["choices"][0]["message"]["content"])
                    return data.get("steps", [])
            except Exception as e:
                logger.warning(f"DeepSeek gagal: {e}")
        
        # Fallback ke OpenAI
        if self.config.OPENAI_API_KEYS:
            try:
                client = AsyncOpenAI(api_key=self.config.OPENAI_API_KEYS[0])
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.7
                )
                data = json.loads(response.choices[0].message.content)
                return data.get("steps", [])
            except Exception as e:
                logger.error(f"OpenAI gagal: {e}")
        
        return None

    def _format_pc_auto_rp(self, title: str, modifier: str, primary_key: str, steps: List[Dict]) -> str:
        """Format untuk KHP Auto RP Macro"""
        output = f"TITLE:{title}\n"
        output += f"MODIFIER:{modifier}\n"
        output += f"PRIMARY_KEY:{primary_key}\n"
        for step in steps:
            delay_seconds = step.get("delay", 2)
            output += f"STEP:{delay_seconds}:{step['command']}\n"
        output += "END_MACRO\n"
        return output

    def _format_pc_cmd_macro(self, title: str, command: str, steps: List[Dict]) -> str:
        """Format untuk KHP CMD Macro"""
        output = f"TITLE:{title}\n"
        output += f"CMD:{command}\n"
        for step in steps:
            delay_seconds = step.get("delay", 1)
            output += f"STEP:{delay_seconds}:{step['command']}\n"
        output += "END_MACRO\n"
        return output

    def _format_pc_gun_rp(self, title: str, weapon_id: int, action: str, steps: List[Dict]) -> str:
        """Format untuk KHP Gun RP Macro"""
        output = f"WEAPON_ID:{weapon_id}\n"
        output += f"ACTION:{action}\n"
        output += f"TITLE:{title}\n"
        for step in steps:
            delay_seconds = step.get("delay", 1)
            output += f"STEP:{delay_seconds}:{step['command']}\n"
        output += "END_GUN_MACRO\n"
        return output

    def _format_mobile_macro(self, title: str, steps: List[Dict], weapon_id: Optional[int] = None, 
                            action: Optional[str] = None, command: Optional[str] = None) -> str:
        """Format untuk KHMobile (JSON format)"""
        macro_data = {
            "name": title,
            "steps": [{"command": s["command"], "delay": s.get("delay", 2) * 1000} for s in steps]
        }
        
        if weapon_id is not None and action:
            macro_data["weaponId"] = weapon_id
            macro_data["action"] = action
        
        if command:
            macro_data["command"] = command
        
        return json.dumps(macro_data, indent=2, ensure_ascii=False)

    @commands.command(name="createtemplate")
    async def create_template_command(self, ctx):
        """Membuat template Auto RP untuk KotkaHelper (PC/Mobile)"""
        if ctx.author.id in self.active_sessions:
            return await ctx.send("❌ Anda sudah memiliki sesi aktif. Selesaikan dulu atau tunggu timeout.", delete_after=10)
        
        # Langkah 1: Pilih Platform
        embed = discord.Embed(
            title="🎨 KotkaHelper Template Creator",
            description="**Langkah 1/4:** Pilih platform target template Anda",
            color=0x5865F2
        )
        embed.add_field(
            name="💻 PC (KHP v1.3.2)",
            value="• Simpan ke `KotkaHelper_Macros.txt`\n• Simpan ke `KotkaHelper_CmdMacros.txt`\n• Simpan ke `KotkaHelper_GunRP.txt`",
            inline=True
        )
        embed.add_field(
            name="📱 Mobile (KHMobile)",
            value="• Import ke menu Auto RP\n• Import ke menu CMD Macro\n• Import ke menu Gun RP",
            inline=True
        )
        
        platform_view = PlatformSelectView(ctx.author.id)
        platform_msg = await ctx.send(embed=embed, view=platform_view)
        
        await platform_view.wait()
        if not platform_view.platform:
            return await platform_msg.edit(content="⏱️ Timeout. Silakan jalankan perintah lagi.", embed=None, view=None)
        
        platform = platform_view.platform
        self.active_sessions[ctx.author.id] = {"platform": platform}
        
        # Langkah 2: Pilih Tipe Macro
        embed2 = discord.Embed(
            title="🎨 KotkaHelper Template Creator",
            description=f"**Langkah 2/4:** Pilih tipe macro\n**Platform:** {platform.upper()}",
            color=0x5865F2
        )
        embed2.add_field(
            name="⌨️ Auto RP Macro",
            value="Aktivasi: Hotkey (PC) / Button (Mobile)",
            inline=False
        )
        embed2.add_field(
            name="💬 CMD Macro",
            value="Aktivasi: Command chat (misal /mancing)",
            inline=False
        )
        embed2.add_field(
            name="🔫 Gun RP Macro",
            value="Aktivasi: Otomatis saat ganti senjata",
            inline=False
        )
        
        type_view = MacroTypeSelectView(ctx.author.id, platform)
        await platform_msg.edit(embed=embed2, view=type_view)
        
        await type_view.wait()
        if not type_view.macro_type:
            del self.active_sessions[ctx.author.id]
            return await platform_msg.edit(content="⏱️ Timeout. Silakan jalankan perintah lagi.", embed=None, view=None)
        
        macro_type = type_view.macro_type
        self.active_sessions[ctx.author.id]["macro_type"] = macro_type
        
        # Langkah 3: Konfigurasi spesifik
        await platform_msg.edit(
            content=f"⚙️ **Langkah 3/4:** Konfigurasi {macro_type.replace('_', ' ').title()}...",
            embed=None,
            view=None
        )
        
        try:
            if macro_type == "auto_rp" and platform == "pc":
                modal = HotkeyModal()
                await ctx.send(f"{ctx.author.mention} Klik tombol di bawah untuk mengatur hotkey:", view=discord.ui.View().add_item(
                    discord.ui.Button(label="⚙️ Set Hotkey", style=discord.ButtonStyle.primary, custom_id="hotkey_modal")
                ))
                # Tunggu modal submit (simplified, in production use proper modal handling)
                # Untuk production, gunakan interaction dari button yang memanggil modal
                # Di sini kita simplifikasi dengan menunggu user input
                await ctx.send("📝 Silakan input hotkey via DM bot atau lanjutkan dengan default (F5)", delete_after=10)
                self.active_sessions[ctx.author.id]["modifier"] = "Tidak Ada"
                self.active_sessions[ctx.author.id]["primary_key"] = "F5"
                
            elif macro_type == "cmd":
                modal = CommandModal()
                await ctx.send(f"{ctx.author.mention} Ketik command pemicu Anda (misal: /mancing)")
                
                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel and m.content.startswith("/")
                
                try:
                    cmd_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
                    command = cmd_msg.content.strip()
                    self.active_sessions[ctx.author.id]["command"] = command
                    await cmd_msg.add_reaction("✅")
                except asyncio.TimeoutError:
                    del self.active_sessions[ctx.author.id]
                    return await ctx.send("⏱️ Timeout. Silakan jalankan perintah lagi.")
                
            elif macro_type == "gun":
                weapon_view = WeaponSelectView(ctx.author.id)
                weapon_msg = await ctx.send("🔫 Pilih senjata dan aksi:", view=weapon_view)
                
                await weapon_view.wait()
                if not weapon_view.weapon_id or not weapon_view.action:
                    del self.active_sessions[ctx.author.id]
                    return await weapon_msg.edit(content="⏱️ Timeout. Silakan jalankan perintah lagi.", view=None)
                
                self.active_sessions[ctx.author.id]["weapon_id"] = weapon_view.weapon_id
                self.active_sessions[ctx.author.id]["action"] = weapon_view.action
        
        except Exception as e:
            logger.error(f"Error saat konfigurasi: {e}")
            del self.active_sessions[ctx.author.id]
            return await ctx.send(f"❌ Terjadi kesalahan: {e}")
        
        # Langkah 4: Input Tema dan Generate
        await ctx.send("📝 **Langkah 4/4:** Masukkan tema dan detail RP...")
        await ctx.send(f"{ctx.author.mention} Ketik tema RP Anda (misal: **mancing di dermaga**)")
        
        def check_theme(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            theme_msg = await self.bot.wait_for('message', timeout=120.0, check=check_theme)
            theme = theme_msg.content.strip()
            
            await ctx.send("📝 (Opsional) Ketik detail tambahan atau ketik **skip**")
            details_msg = await self.bot.wait_for('message', timeout=60.0, check=check_theme)
            details = details_msg.content.strip() if details_msg.content.lower() != "skip" else "Tidak ada detail"
            
        except asyncio.TimeoutError:
            del self.active_sessions[ctx.author.id]
            return await ctx.send("⏱️ Timeout. Silakan jalankan perintah lagi.")
        
        # Generate dengan AI
        loading_msg = await ctx.send("🤖 **Generating template dengan AI...** (tunggu 10-20 detik)")
        
        steps = await self._get_ai_analysis(theme, details)
        if not steps:
            del self.active_sessions[ctx.author.id]
            return await loading_msg.edit(content="❌ Semua layanan AI gagal. Silakan coba lagi nanti.")
        
        # Format output sesuai platform dan tipe
        session = self.active_sessions[ctx.author.id]
        title = f"RP {theme[:30]}"
        
        if platform == "pc":
            if macro_type == "auto_rp":
                output = self._format_pc_auto_rp(
                    title,
                    session.get("modifier", "Tidak Ada"),
                    session.get("primary_key", "F5"),
                    steps
                )
                filename = "KotkaHelper_Macros.txt"
            elif macro_type == "cmd":
                output = self._format_pc_cmd_macro(
                    title,
                    session.get("command", "/rp"),
                    steps
                )
                filename = "KotkaHelper_CmdMacros.txt"
            else:  # gun
                action = session.get("action", "draw")
                if action == "both":
                    # Buat 2 output: draw dan holster
                    output_draw = self._format_pc_gun_rp(title + " (Keluarkan)", session["weapon_id"], "draw", steps)
                    output_holster = self._format_pc_gun_rp(title + " (Simpan)", session["weapon_id"], "holster", steps)
                    output = output_draw + "\n" + output_holster
                else:
                    output = self._format_pc_gun_rp(title, session["weapon_id"], action, steps)
                filename = "KotkaHelper_GunRP.txt"
        else:  # mobile
            if macro_type == "gun":
                action = session.get("action", "draw")
                if action == "both":
                    output_draw = self._format_mobile_macro(
                        title + " (Keluarkan)",
                        steps,
                        weapon_id=session["weapon_id"],
                        action="draw"
                    )
                    output_holster = self._format_mobile_macro(
                        title + " (Simpan)",
                        steps,
                        weapon_id=session["weapon_id"],
                        action="holster"
                    )
                    output = f"// KELUARKAN SENJATA\n{output_draw}\n\n// SIMPAN SENJATA\n{output_holster}"
                else:
                    output = self._format_mobile_macro(
                        title,
                        steps,
                        weapon_id=session["weapon_id"],
                        action=action
                    )
            elif macro_type == "cmd":
                output = self._format_mobile_macro(title, steps, command=session.get("command", "/rp"))
            else:  # auto_rp
                output = self._format_mobile_macro(title, steps)
            
            filename = "KHMobile_import.json" if macro_type != "gun" else "KHMobile_GunRP.json"
        
        # Kirim hasil
        embed_result = discord.Embed(
            title="✅ Template Berhasil Dibuat!",
            description=f"**Platform:** {platform.upper()}\n**Tipe:** {macro_type.replace('_', ' ').title()}\n**Tema:** {theme}",
            color=0x00FF00
        )
        
        if platform == "pc":
            embed_result.add_field(
                name="📋 Cara Pakai",
                value=f"1. Buka file `{filename}` di folder KotkaHelper\n2. Copy isi file di bawah\n3. Paste ke akhir file (sebelum END jika ada)\n4. Simpan dan restart script",
                inline=False
            )
        else:
            embed_result.add_field(
                name="📋 Cara Pakai (Mobile)",
                value=f"1. Copy JSON di bawah\n2. Buka KHMobile → Menu sesuai tipe\n3. Paste atau manual input sesuai struktur JSON\n4. Simpan",
                inline=False
            )
        
        embed_result.set_footer(text=f"Generated by AI • {len(steps)} langkah")
        
        # Kirim file dengan BytesIO
        try:
            import io
            file_content = output.encode('utf-8')
            file_buffer = io.BytesIO(file_content)
            file_buffer.seek(0)  # Reset pointer ke awal
            file = discord.File(fp=file_buffer, filename=filename)
            
            await loading_msg.delete()
            await ctx.send(embed=embed_result, file=file)
        except Exception as file_error:
            logger.error(f"Error saat membuat file: {file_error}", exc_info=True)
            # Fallback: kirim sebagai code block jika file gagal
            await loading_msg.edit(content=f"⚠️ Gagal membuat file, berikut isi template:\n```\n{output[:1900]}\n```")
            if len(output) > 1900:
                await ctx.send(f"```\n{output[1900:][:1900]}\n```")
        
        # Preview steps
        preview = "**Preview Langkah-langkah:**\n"
        for i, step in enumerate(steps[:5], 1):
            preview += f"{i}. `{step['command']}` (delay: {step.get('delay', 2)}s)\n"
        if len(steps) > 5:
            preview += f"... dan {len(steps) - 5} langkah lainnya"
        
        await ctx.send(preview)
        
        # Cleanup session
        del self.active_sessions[ctx.author.id]
        
        logger.info(f"Template created by {ctx.author.id}: {macro_type} for {platform}")

    @commands.command(name="templatehelp")
    async def template_help_command(self, ctx):
        """Bantuan untuk fitur Template Creator"""
        embed = discord.Embed(
            title="📚 KotkaHelper Template Creator - Bantuan",
            description="Fitur untuk membuat template Auto RP yang kompatibel dengan KotkaHelper PC dan Mobile menggunakan AI.",
            color=0x3498db
        )
        
        embed.add_field(
            name="🎯 Cara Menggunakan",
            value=(
                "1. Ketik `!createtemplate`\n"
                "2. Pilih platform (PC/Mobile)\n"
                "3. Pilih tipe macro (Auto RP/CMD/Gun RP)\n"
                "4. Atur konfigurasi (hotkey/command/senjata)\n"
                "5. Input tema RP dan detail\n"
                "6. Bot akan generate template dengan AI"
            ),
            inline=False
        )
        
        embed.add_field(
            name="⌨️ Auto RP Macro",
            value=(
                "**PC:** Aktivasi dengan hotkey (misal ALT+F5)\n"
                "**Mobile:** Aktivasi dengan tombol apung\n"
                "**Contoh tema:** Mancing, Masuk mobil, Beli makan"
            ),
            inline=False
        )
        
        embed.add_field(
            name="💬 CMD Macro",
            value=(
                "**PC & Mobile:** Aktivasi dengan command chat\n"
                "**Contoh command:** /mancing, /masak, /cuci\n"
                "Bot akan tanya command yang Anda inginkan"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🔫 Gun RP Macro",
            value=(
                "**PC & Mobile:** Otomatis saat ganti senjata\n"
                "**Pilihan:** Keluarkan saja, Simpan saja, atau Keduanya\n"
                "Bot menyediakan list senjata ID 22-34"
            ),
            inline=False
        )
        
        embed.add_field(
            name="💡 Tips Tema yang Bagus",
            value=(
                "✅ Spesifik: *'Mancing di dermaga malam hari'*\n"
                "✅ Dengan konteks: *'Masuk mobil sport di cuaca hujan'*\n"
                "✅ Detail aktivitas: *'Beli burger di warung pinggir jalan'*\n\n"
                "❌ Terlalu umum: *'RP'*, *'Aktivitas'*\n"
                "❌ Tanpa konteks: *'Sesuatu'*"
            ),
            inline=False
        )
        
        embed.add_field(
            name="📂 Format File Output",
            value=(
                "**PC (KHP v1.3.2):**\n"
                "• `.txt` format (TITLE:..., STEP:...)\n"
                "• Langsung paste ke file yang sesuai\n\n"
                "**Mobile (KHMobile):**\n"
                "• `.json` format\n"
                "• Copy-paste atau manual input di app"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🤖 AI Engine",
            value=(
                "Menggunakan multiple AI (Gemini/DeepSeek/OpenAI)\n"
                "• Generate 3-7 langkah RP natural\n"
                "• Delay otomatis disesuaikan\n"
                "• Bahasa Indonesia yang natural"
            ),
            inline=False
        )
        
        embed.set_footer(text="Dibuat oleh Kotkaaja • Powered by AI")
        
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Error handler untuk Template Creator"""
        # Hanya handle error dari command template creator
        if ctx.command and ctx.command.name not in ['createtemplate', 'templatehelp']:
            return
            
        if isinstance(error, commands.CommandNotFound):
            return
        
        # Cleanup session jika ada error
        if ctx.author.id in self.active_sessions:
            del self.active_sessions[ctx.author.id]
        
        if isinstance(error, commands.CommandInvokeError):
            logger.error(f"Error di Template Creator: {error.original}", exc_info=True)
            await ctx.send(f"❌ Terjadi kesalahan saat membuat template: `{str(error.original)[:200]}`\nSilakan coba lagi atau hubungi admin.")
        else:
            logger.error(f"Unexpected error di Template Creator: {error}", exc_info=True)
            await ctx.send("❌ Terjadi kesalahan tidak terduga. Silakan coba lagi.")

    def cog_unload(self):
        """Cleanup saat cog di-unload"""
        self.active_sessions.clear()
        logger.info("Template Creator Cog unloaded.")


async def setup(bot):
    await bot.add_cog(TemplateCreatorCog(bot))
