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
Expert SAMP RP script writer. Tema: "{theme}". Detail: {details}

ATURAN WAJIB:
1. /me = mendeskripsikan TINDAKAN karakter (present tense), detail tapi singkat. Contoh: /me mengambil pulpen dari meja dengan tangan kanan.
2. /do = mendeskripsikan KEADAAN/HASIL/SITUASI di sekitar karakter atau kondisi karakter itu sendiri. TIDAK untuk bertanya 'bisa?'. Contoh: /do Terlihat pulpen di atas meja., /do Cuaca terlihat cerah.
3. Buat 3-7 langkah RP yang logis dan berurutan.
4. Sertakan delay antara 2-4 detik per langkah (bisa lebih jika aksi memang butuh waktu lama). Sesuaikan delay dengan logisnya aksi.
5. Jangan gunakan: emoji, force RP (memaksa hasil pada pemain lain), undetailed RP (RP terlalu singkat/kurang jelas).
6. Maksimal 100 karakter per langkah/command.
7. Gunakan Bahasa Indonesia yang natural dan baku.

LARANGAN:
- Force RP: "/me memukuli John Doe sampai mati" ❌ (Tidak boleh menentukan hasil akhir pada orang lain)
- Undetailed RP: "/me kaget" ❌ (Harus lebih detail: "/me kaget melihat mobil melaju kencang")
- Bohong di /do (OOC lie): "/do dompetnya kosong padahal ada uang" ❌
- Menggunakan /do untuk bertanya izin seperti "bisa?" ❌

Contoh BENAR:
/me mengulurkan tangan kanan mencoba meraih gagang pintu
/do Tangan kanan berhasil menggenggam gagang pintu.
/me memutar gagang pintu dan mendorongnya perlahan

JSON only (WAJIB format ini, tanpa teks lain di luar JSON):
{{
  "steps": [
    {{"command": "/me ...", "delay": 2}},
    {{"command": "/do ...", "delay": 3}}
    // ... langkah selanjutnya
  ]
}}
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
class MacroTypeSelectView(discord.ui.View):
    """View untuk memilih tipe macro"""
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.macro_type = None
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Tombol ini bukan untuk Anda!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⌨️ Auto RP Macro", style=discord.ButtonStyle.primary, emoji="⌨️")
    async def auto_rp_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.macro_type = "auto_rp"
        await interaction.response.send_message("✅ **Tipe dipilih:** Auto RP Macro (aktivasi dengan hotkey/button)", ephemeral=True)
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
            ][:25]
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
        
        self.clear_items()
        self.add_action_buttons()
        
        await interaction.response.edit_message(
            content=f"🔫 **Langkah 2/3:** Senjata dipilih: **{weapon_name}**. Sekarang pilih aksinya:",
            view=self
        )

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


# ============================
# MODAL KONFIGURASI
# ============================

class ConfigInputModal(discord.ui.Modal):
    """Modal gabungan untuk input Konfigurasi (Hotkey/CMD) dan Tema."""
    
    theme = discord.ui.TextInput(
        label="Tema/Aktivitas RP",
        placeholder="Contoh: Mancing di dermaga, Masuk mobil",
        max_length=100,
        required=True,
        row=2
    )
    details = discord.ui.TextInput(
        label="Detail Tambahan (opsional)",
        placeholder="Contoh: Suasana malam hari, cuaca hujan",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=False,
        row=3
    )

    def __init__(self, macro_type: str, title: str):
        super().__init__(title=title)
        self.macro_type = macro_type
        
        self.theme_value = None
        self.details_value = None
        self.config_value = None

        if macro_type == "auto_rp":
            self.config_modifier = discord.ui.TextInput(
                label="Modifier Key (ALT/SHIFT/CTRL atau -)",
                placeholder="Contoh: ALT (atau - jika tidak ada)",
                max_length=10,
                required=True,
                row=0
            )
            self.config_primary_key = discord.ui.TextInput(
                label="Primary Key (F1-F12, A-Z, 0-9, NUM0-9)",
                placeholder="Contoh: F5",
                max_length=5,
                required=True,
                row=1
            )
            self.add_item(self.config_modifier)
            self.add_item(self.config_primary_key)
        
        elif macro_type == "cmd":
            self.config_command = discord.ui.TextInput(
                label="Command Pemicu (harus dimulai /)",
                placeholder="Contoh: /mancing",
                max_length=50,
                required=True,
                row=0
            )
            self.add_item(self.config_command)

    async def on_submit(self, interaction: discord.Interaction):
        self.theme_value = self.theme.value.strip()
        self.details_value = self.details.value.strip() or "Tidak ada detail tambahan"
        
        try:
            if self.macro_type == "auto_rp":
                mod = self.config_modifier.value.strip().upper()
                if mod == "-": mod_val = "Tidak Ada"
                elif mod in ["ALT", "SHIFT", "CTRL"]: mod_val = mod
                else: raise ValueError("Modifier tidak valid! Gunakan: ALT, SHIFT, CTRL, atau -")
                
                key = self.config_primary_key.value.strip().upper()
                valid_keys = (
                    [f"F{i}" for i in range(1, 13)] + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") +
                    [str(i) for i in range(10)] + [f"NUM{i}" for i in range(10)]
                )
                if key not in valid_keys:
                    raise ValueError("Key tidak valid! Gunakan: F1-F12, A-Z, 0-9, atau NUM0-NUM9")
                
                self.config_value = {"modifier": mod_val, "primary_key": key}
                config_info = f"Hotkey: `{mod_val if mod_val != 'Tidak Ada' else ''}{'+' if mod_val != 'Tidak Ada' else ''}{key}`"

            elif self.macro_type == "cmd":
                cmd = self.config_command.value.strip()
                if not cmd.startswith("/"): raise ValueError("Command harus dimulai dengan `/`")
                if len(cmd) < 2: raise ValueError("Command terlalu pendek!")
                
                self.config_value = cmd
                config_info = f"Command: `{cmd}`"
            
            else:
                config_info = "Tipe: Tidak Dikenali (Error)"

            await interaction.response.send_message(
                f"✅ **Konfigurasi Diterima**\n"
                f"**Tema:** {self.theme_value}\n"
                f"**Detail:** {self.details_value[:50]}...\n"
                f"**Info:** {config_info}",
                ephemeral=True
            )
        except ValueError as e:
            self.theme_value = None
            await interaction.response.send_message(f"❌ **Validasi Gagal!**\n{e}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error pada ConfigInputModal: {e}")
            await interaction.response.send_message("❌ Terjadi error tak terduga.", ephemeral=True)


class WeaponConfigModal(discord.ui.Modal, title="Konfigurasi Gun RP (Aksi Tunggal)"):
    """Modal untuk Gun RP (hanya tema & detail) untuk aksi 'draw' ATAU 'holster'."""
    theme = discord.ui.TextInput(
        label="Tema/Aktivitas RP (Wajib)",
        placeholder="Contoh: Mengeluarkan Deagle dari pinggang",
        max_length=100,
        required=True
    )
    details = discord.ui.TextInput(
        label="Detail Tambahan (opsional)",
        placeholder="Contoh: Sambil mengawasi sekitar",
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
            f"✅ **Tema Gun RP Diterima**\n"
            f"**Tema:** {self.theme_value}\n"
            f"**Detail:** {self.details_value[:50]}...",
            ephemeral=True
        )

# --- PERUBAHAN BARU: Modal untuk 'Keduanya' ---
class WeaponConfigModalBoth(discord.ui.Modal, title="Konfigurasi Gun RP (Keduanya)"):
    """Modal khusus untuk Gun RP 'Keduanya'."""
    theme_draw = discord.ui.TextInput(
        label="Tema Mengeluarkan Senjata (Wajib)",
        placeholder="Contoh: Mengambil Deagle dari holster pinggang",
        max_length=100,
        required=True,
        row=0
    )
    details_draw = discord.ui.TextInput(
        label="Detail Tambahan (Keluarkan)",
        placeholder="Contoh: Dengan tangan kanan, sambil awas",
        max_length=300,
        required=False,
        row=1
    )
    theme_holster = discord.ui.TextInput(
        label="Tema Menyimpan Senjata (Wajib)",
        placeholder="Contoh: Memasukkan kembali Deagle ke holster",
        max_length=100,
        required=True,
        row=2
    )
    details_holster = discord.ui.TextInput(
        label="Detail Tambahan (Simpan)",
        placeholder="Contoh: Setelah memastikan situasi aman",
        max_length=300,
        required=False,
        row=3
    )
    
    def __init__(self):
        super().__init__()
        self.theme_draw_value = None
        self.details_draw_value = None
        self.theme_holster_value = None
        self.details_holster_value = None

    async def on_submit(self, interaction: discord.Interaction):
        self.theme_draw_value = self.theme_draw.value.strip()
        self.details_draw_value = self.details_draw.value.strip() or "Tidak ada detail tambahan"
        self.theme_holster_value = self.theme_holster.value.strip()
        self.details_holster_value = self.details_holster.value.strip() or "Tidak ada detail tambahan"
        
        await interaction.response.send_message(
            f"✅ **Tema Gun RP Diterima**\n"
            f"**Tema Keluarkan:** {self.theme_draw_value}\n"
            f"**Tema Simpan:** {self.theme_holster_value}",
            ephemeral=True
        )
# --- AKHIR PERUBAHAN BARU ---

# ============================
# COG UTAMA
# ============================
class TemplateCreatorCog(commands.Cog, name="TemplateCreator"):
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        self.active_sessions = {}
    
    async def _get_ai_analysis(self, theme: str, details: str) -> Optional[List[Dict]]:
        """Menggunakan AI untuk generate langkah-langkah RP"""
        prompt = AI_TEMPLATE_PROMPT.format(theme=theme, details=details)
        
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

    @commands.command(name="createtemplate")
    async def create_template_command(self, ctx):
        """Membuat template Auto RP untuk KotkaHelper (PC/Mobile)"""
        if ctx.author.id in self.active_sessions:
            return await ctx.send("❌ Anda sudah memiliki sesi aktif. Selesaikan dulu atau tunggu timeout.", delete_after=10)
        
        self.active_sessions[ctx.author.id] = {}

        # Langkah 1: Pilih Tipe Macro
        embed2 = discord.Embed(
            title="🎨 KotkaHelper Template Creator",
            description=f"**Langkah 1/3:** Pilih tipe macro (Format KHP untuk PC/Mobile)",
            color=0x5865F2
        )
        embed2.add_field(name="⌨️ Auto RP Macro", value="Aktivasi: Hotkey (PC) / Button (Mobile)", inline=False)
        embed2.add_field(name="💬 CMD Macro", value="Aktivasi: Command chat (misal /mancing)", inline=False)
        embed2.add_field(name="🔫 Gun RP Macro", value="Aktivasi: Otomatis saat ganti senjata", inline=False)
        
        type_view = MacroTypeSelectView(ctx.author.id)
        type_msg = await ctx.send(embed=embed2, view=type_view)
        
        await type_view.wait()
        if not type_view.macro_type:
            del self.active_sessions[ctx.author.id]
            return await type_msg.edit(content="⏱️ Timeout. Silakan jalankan perintah lagi.", embed=None, view=None)
        
        macro_type = type_view.macro_type
        self.active_sessions[ctx.author.id]["macro_type"] = macro_type
        
        # Hapus pesan lama
        await type_msg.delete() 
        modal_msg = None
        
        try:
            # --- PERUBAHAN BARU: Alur bercabang untuk Gun RP ---
            if macro_type == "gun":
                weapon_view = WeaponSelectView(ctx.author.id)
                weapon_msg = await ctx.send("🔫 **Langkah 2/3:** Pilih senjata:", view=weapon_view)
                
                await weapon_view.wait()
                if not weapon_view.weapon_id or not weapon_view.action:
                    del self.active_sessions[ctx.author.id]
                    return await weapon_msg.edit(content="⏱️ Timeout. Silakan jalankan perintah lagi.", view=None)
                
                self.active_sessions[ctx.author.id]["weapon_id"] = weapon_view.weapon_id
                self.active_sessions[ctx.author.id]["action"] = weapon_view.action
                await weapon_msg.delete()
                
                # Tentukan modal mana yang akan digunakan
                if weapon_view.action == "both":
                    modal = WeaponConfigModalBoth()
                    modal_button_label = "📝 Isi Tema Keluarkan & Simpan (Langkah 3/3)"
                else:
                    modal = WeaponConfigModal()
                    modal_button_label = f"📝 Isi Tema '{weapon_view.action}' (Langkah 3/3)"

                # Kirim tombol untuk buka modal
                class OpenModalView(discord.ui.View):
                    def __init__(self, author_id, button_label):
                        super().__init__(timeout=180)
                        self.author_id = author_id
                        self.interaction = None
                        # Tambahkan tombol secara dinamis
                        btn = discord.ui.Button(label=button_label, style=discord.ButtonStyle.primary)
                        btn.callback = self.open_modal_btn
                        self.add_item(btn)

                    async def interaction_check(self, interaction: discord.Interaction) -> bool:
                        return interaction.user.id == self.author_id
                    
                    async def open_modal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
                        self.interaction = interaction
                        self.stop()

                view = OpenModalView(ctx.author.id, modal_button_label)
                modal_msg = await ctx.send(f"{ctx.author.mention}, klik tombol untuk mengisi detail Gun RP.", view=view)
                await view.wait()
                
                if not view.interaction:
                    del self.active_sessions[ctx.author.id]
                    return await modal_msg.edit(content="⏱️ Timeout. Anda tidak menekan tombol.", view=None)

                await view.interaction.response.send_modal(modal)
                await modal.wait()
                
                # Simpan hasil modal
                if weapon_view.action == "both":
                    if modal.theme_draw_value: # Cek salah satu value
                        self.active_sessions[ctx.author.id]["theme_draw"] = modal.theme_draw_value
                        self.active_sessions[ctx.author.id]["details_draw"] = modal.details_draw_value
                        self.active_sessions[ctx.author.id]["theme_holster"] = modal.theme_holster_value
                        self.active_sessions[ctx.author.id]["details_holster"] = modal.details_holster_value
                    else:
                        del self.active_sessions[ctx.author.id]; return
                else:
                    if modal.theme_value:
                        self.active_sessions[ctx.author.id]["theme"] = modal.theme_value
                        self.active_sessions[ctx.author.id]["details"] = modal.details_value
                    else:
                        del self.active_sessions[ctx.author.id]; return
                
            else: # (macro_type == "auto_rp" or "cmd")
                modal_title = "Konfigurasi Auto RP Macro" if macro_type == "auto_rp" else "Konfigurasi CMD Macro"
                modal = ConfigInputModal(macro_type, modal_title)
                
                class OpenModalView(discord.ui.View):
                    def __init__(self, author_id):
                        super().__init__(timeout=180)
                        self.author_id = author_id
                        self.interaction = None
                    async def interaction_check(self, interaction: discord.Interaction) -> bool:
                        return interaction.user.id == self.author_id
                    @discord.ui.button(label="📝 Isi Konfigurasi & Tema (Langkah 2&3/3)", style=discord.ButtonStyle.primary)
                    async def open_modal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
                        self.interaction = interaction; self.stop()

                view = OpenModalView(ctx.author.id)
                modal_msg = await ctx.send(f"{ctx.author.mention}, klik tombol untuk mengisi konfigurasi.", view=view)
                await view.wait()

                if not view.interaction:
                    del self.active_sessions[ctx.author.id]
                    return await modal_msg.edit(content="⏱️ Timeout. Anda tidak menekan tombol.", view=None)
                
                await view.interaction.response.send_modal(modal)
                await modal.wait()

                if modal.theme_value:
                    self.active_sessions[ctx.author.id]["theme"] = modal.theme_value
                    self.active_sessions[ctx.author.id]["details"] = modal.details_value
                    if macro_type == "auto_rp":
                        self.active_sessions[ctx.author.id]["modifier"] = modal.config_value["modifier"]
                        self.active_sessions[ctx.author.id]["primary_key"] = modal.config_value["primary_key"]
                    elif macro_type == "cmd":
                        self.active_sessions[ctx.author.id]["command"] = modal.config_value
                else:
                    del self.active_sessions[ctx.author.id]; return

        except Exception as e:
            logger.error(f"Error saat alur konfigurasi: {e}", exc_info=True)
            if ctx.author.id in self.active_sessions: del self.active_sessions[ctx.author.id]
            if modal_msg: await modal_msg.edit(content=f"❌ Terjadi kesalahan: {e}", view=None)
            else: await ctx.send(f"❌ Terjadi kesalahan: {e}")
            return
        
        if modal_msg: await modal_msg.delete()

        # --- PERUBAHAN BARU: Logika Panggilan AI ---
        session = self.active_sessions.get(ctx.author.id)
        if not session:
            return await ctx.send("❌ Sesi dibatalkan karena data tidak lengkap.")
        
        loading_msg = await ctx.send("🤖 **Generating template dengan AI...** (tunggu 10-20 detik)")
        
        steps_draw = None
        steps_holster = None
        steps_single = None

        if session.get("macro_type") == "gun" and session.get("action") == "both":
            # Panggil AI dua kali
            theme_d = session.get("theme_draw", "mengeluarkan senjata")
            details_d = session.get("details_draw", "")
            theme_h = session.get("theme_holster", "menyimpan senjata")
            details_h = session.get("details_holster", "")
            
            await loading_msg.edit(content=f"🤖 **Generating RP 'Keluarkan':** {theme_d}...")
            steps_draw = await self._get_ai_analysis(theme_d, details_d)
            
            await loading_msg.edit(content=f"🤖 **Generating RP 'Simpan':** {theme_h}...")
            steps_holster = await self._get_ai_analysis(theme_h, details_h)
            
            if not steps_draw or not steps_holster:
                del self.active_sessions[ctx.author.id]
                return await loading_msg.edit(content="❌ Salah satu panggilan AI gagal. Silakan coba lagi nanti.")
            
        else:
            # Panggil AI sekali
            theme = session.get("theme", "melakukan rp")
            details = session.get("details", "")
            await loading_msg.edit(content=f"🤖 **Generating RP:** {theme}...")
            steps_single = await self._get_ai_analysis(theme, details)
            
            if not steps_single:
                del self.active_sessions[ctx.author.id]
                return await loading_msg.edit(content="❌ Semua layanan AI gagal. Silakan coba lagi nanti.")
        
        # --- PERUBAHAN BARU: Logika Format Output ---
        session = self.active_sessions[ctx.author.id] # Refresh session data (meskipun tidak perlu)
        
        if macro_type == "auto_rp":
            title = f"RP {session['theme'][:30]}"
            output = self._format_pc_auto_rp(
                title,
                session.get("modifier", "Tidak Ada"),
                session.get("primary_key", "F5"),
                steps_single # steps_single
            )
            filename = "KotkaHelper_Macros.txt"
        elif macro_type == "cmd":
            title = f"RP {session['theme'][:30]}"
            output = self._format_pc_cmd_macro(
                title,
                session.get("command", "/rp"),
                steps_single # steps_single
            )
            filename = "KotkaHelper_CmdMacros.txt"
        else:  # gun
            action = session.get("action", "draw")
            if action == "both":
                title_draw = f"RP {session['theme_draw'][:25]} (K)"
                title_holster = f"RP {session['theme_holster'][:25]} (S)"
                output_draw = self._format_pc_gun_rp(title_draw, session["weapon_id"], "draw", steps_draw)
                output_holster = self._format_pc_gun_rp(title_holster, session["weapon_id"], "holster", steps_holster)
                output = output_draw + "\n" + output_holster
                theme_display = f"Keluarkan: {session['theme_draw']}\nSimpan: {session['theme_holster']}"
            else:
                title = f"RP {session['theme'][:30]}"
                output = self._format_pc_gun_rp(title, session["weapon_id"], action, steps_single) # steps_single
                theme_display = session['theme']
            filename = "KotkaHelper_GunRP.txt"
        
        # Kirim hasil
        embed_result = discord.Embed(
            title="✅ Template Berhasil Dibuat!",
            description=f"**Platform:** PC / Mobile (Format KHP)\n**Tipe:** {macro_type.replace('_', ' ').title()}\n**Tema:** {theme_display if 'theme_display' in locals() else session.get('theme', 'N/A')}",
            color=0x00FF00
        )
        
        if macro_type == "gun" and session.get("action") == "both":
             embed_result.add_field(
                name="📋 Cara Pakai (PC/Mobile)",
                value=(
                    f"1. Buka file `{filename}`.\n"
                    "2. File ini berisi 2 template (Keluarkan & Simpan).\n"
                    "3. Copy-paste *kedua* template ke file GunRP Anda (di PC/Mobile)."
                ),
                inline=False
            )
             embed_result.set_footer(text=f"Generated by AI • {len(steps_draw)} + {len(steps_holster)} langkah")
        else:
            embed_result.add_field(
                name="📋 Cara Pakai (PC/Mobile)",
                value=(
                    f"1. Buka file `{filename}` di folder `KotkaHelper` (PC) atau `KotkaHelperMobile` (Android).\n"
                    "2. Copy isi file di bawah.\n"
                    "3. Paste ke *akhir* file Anda.\n"
                    "4. Simpan dan restart script."
                ),
                inline=False
            )
            embed_result.set_footer(text=f"Generated by AI • {len(steps_single)} langkah")
        
        try:
            import io
            file_content = output.encode('utf-8')
            file_buffer = io.BytesIO(file_content)
            file_buffer.seek(0)
            file = discord.File(fp=file_buffer, filename=filename)
            
            await loading_msg.delete()
            await ctx.send(embed=embed_result, file=file)
        except Exception as file_error:
            logger.error(f"Error saat membuat file: {file_error}", exc_info=True)
            await loading_msg.edit(content=f"⚠️ Gagal membuat file, berikut isi template:\n```\n{output[:1900]}\n```")
            if len(output) > 1900:
                await ctx.send(f"```\n{output[1900:][:1900]}\n```")
        
        del self.active_sessions[ctx.author.id]
        logger.info(f"Template created by {ctx.author.id}: {macro_type}")

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
                "2. Pilih tipe macro (Auto RP, CMD, Gun)\n"
                "3. Klik tombol untuk isi konfigurasi via form\n"
                "4. AI generate template otomatis"
            ),
            inline=False
        )
        embed.add_field(
            name="📝 Aturan RP yang Diterapkan AI",
            value=(
                "✅ **/me** = Tindakan detail (present tense)\n"
                "✅ **/do** = Hasil/situasi (Bukan untuk tanya 'bisa?')\n" 
                "✅ 3-7 langkah logis, delay 2-4s (disesuaikan AI)\n\n"
                "❌ **Larangan:** Force RP, Undetailed RP, bohong di /do"
            ),
            inline=False
        )
        embed.add_field(
            name="💡 Tips Tema yang Bagus",
            value=(
                "✅ **Spesifik:** *'Mancing di dermaga malam hari'*\n"
                "✅ **Dengan konteks:** *'Masuk mobil sport cuaca hujan'*\n"
                "✅ **(Gun RP Both):** Tema 'Keluarkan' dan 'Simpan' harus diisi keduanya."
            ),
            inline=False
        )
        embed.add_field(
            name="⌨️ Tipe Macro",
            value=(
                "**Auto RP:** Hotkey (PC: ALT+F5)\n"
                "**CMD Macro:** Command chat (/mancing, /masak)\n"
                "**Gun RP:** Otomatis saat ganti senjata"
            ),
            inline=False
        )
        embed.add_field(
            name="📂 Format Output",
            value=(
                "**`.txt` (KHP Format):** Format ini kompatibel untuk PC (KotkaHelper) dan Android (KotkaHelperMobile)."
            ),
            inline=False
        )
        embed.set_footer(text="Dibuat oleh Kotkaaja • AI mengikuti aturan SAMP RP")
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Error handler untuk Template Creator"""
        if ctx.command and ctx.command.name not in ['createtemplate', 'templatehelp']:
            return
        if isinstance(error, commands.CommandNotFound): return
        if ctx.author.id in self.active_sessions:
            del self.active_sessions[ctx.author.id]
        
        if isinstance(error, commands.CommandInvokeError):
            logger.error(f"Error di Template Creator: {error.original}", exc_info=True)
            await ctx.send(f"❌ Terjadi kesalahan saat membuat template: `{str(error.original)[:200]}`\nSilakan coba lagi atau hubungi admin.")
        else:
            logger.error(f"Unexpected error di Template Creator: {error}", exc_info=True)
            await ctx.send("❌ Terjadi kesalahan tidak terduga. Silakan coba lagi.")

    def cog_unload(self):
        self.active_sessions.clear()
        logger.info("Template Creator Cog unloaded.")

async def setup(bot):
    await bot.add_cog(TemplateCreatorCog(bot))
