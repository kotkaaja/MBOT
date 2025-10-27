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
# KONSTANTA & PROMPT AI (DIPERBARUI DENGAN BAHASA)
# ============================

# --- [PROMPT LAMA DIHAPUS DAN DIGANTI DENGAN YANG BARU INI] ---
AI_TEMPLATE_PROMPT = """
PERAN: Anda adalah penulis skrip Roleplay (RP) ahli untuk server GTA SAMP (San Andreas Multiplayer).

BAHASA UTAMA: Anda HARUS menulis semua output HANYA dalam bahasa/aksen berikut: "{language}".
Jika "{language}" BUKAN "Bahasa Indonesia baku", JANGAN gunakan Bahasa Indonesia sama sekali.

TEMA: "{theme}"
DETAIL: {details}

KONTEKS SPESIFIK GTA SAMP (SANGAT PENTING):
- Ini adalah game, aksi harus masuk akal di dalam game.
- RP harus mendetail dan logis.
- RP interaktif sangat diutamakan. Beri kesempatan pemain lain merespon, terutama saat menggunakan /do untuk bertanya (e.g., /do ada perlawanan?, /do terlihat senjata di dashboard?).
- RP Senjata (Gun RP) sangat penting dan harus detail (e.g., /me mengambil Deagle dari holster, /me melepas kunci pengaman, /do siap menembak.)
- Singkatan Umum: 'Deagle' (Desert Eagle), 'SG' (Shotgun), 'SOS' (Sawn-Off Shotgun), 'AK' (AK-47), 'M4', 'HP' (Handphone).
- Lokasi Umum: Holster (sarung pistol), dashboard (mobil), glove box (mobil), saku.

ATURAN WAJIB (Gunakan Bahasa: "{language}"):
1.  /me = Mendeskripsikan TINDAKAN fisik, ekspresi, atau apa yang dilakukan karakter (present tense). Detail tapi singkat (maks 100 karakter).
    Contoh (Indo): /me meraih HP dari saku celananya.
    Contoh (Inggris): /me reaches into his pocket for his phone.

2.  /do = Mendeskripsikan KEADAAN/HASIL/SITUASI ATAU BERTANYA. Ini adalah fakta lingkungan atau hasil dari /me.
    Contoh (Indo): /do Terlihat HP di tangannya.
    Contoh (Inggris): /do A phone is visible in his hand.
    Contoh BERTANYA (Indo): /do Ada perlawanan dari target? ((Nama_Karakter))
    Contoh BERTANYA (Inggris): /do Is there any resistance from the target? ((Character_Name))

3.  Buat 3-7 langkah RP yang logis, interaktif (jika relevan), dan berurutan sesuai tema.
4.  Sertakan delay antara 2-4 detik per langkah (sesuaikan logisnya aksi).
5.  JANGAN gunakan: emoji, force RP (memaksa hasil pada pemain lain), undetailed RP (terlalu singkat).
6.  JANGAN berbohong di /do (OOC lie).

LARANGAN (JANGAN DILAKUKAN):
- Force RP: "/me memukul John hingga pingsan" ❌
- Undetailed RP: "/me kaget" ❌
- Bohong di /do: "/do sakunya kosong (padahal ada uang)" ❌

Output HARUS HANYA JSON (WAJIB format ini, tanpa teks lain di luar JSON):
{{
  "steps": [
    {{"command": "/me ... (dalam bahasa '{language}')", "delay": 2}},
    {{"command": "/do ... (dalam bahasa '{language}')", "delay": 3}}
    // ... langkah selanjutnya
  ]
}}
"""
# --- [AKHIR DARI PROMPT BARU] ---


# Mapping ID senjata untuk Gun RP
WEAPON_LIST = {
    22: "Pistol", 23: "Silenced Pistol", 24: "Desert Eagle",
    25: "Shotgun", 26: "Sawn-Off", 27: "Combat Shotgun",
    28: "Uzi", 29: "MP5", 30: "AK-47", 31: "M4", 32: "Tec-9",
    33: "Rifle", 34: "Sniper Rifle"
}

# ============================
# UI COMPONENTS
# (Tidak ada perubahan di bagian ini)
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
# (Tidak ada perubahan di bagian ini)
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
    # --- Input Bahasa Baru ---
    language = discord.ui.TextInput(
        label="Bahasa/Aksen RP (Opsional)",
        placeholder="Contoh: English, Spanish (Mexico), Japanese",
        default="Bahasa Indonesia baku",
        max_length=50,
        required=False,
        row=4
    )
    # -----------------------

    def __init__(self, macro_type: str, title: str):
        super().__init__(title=title)
        self.macro_type = macro_type

        self.theme_value = None
        self.details_value = None
        self.language_value = None # Simpan bahasa
        self.config_value = None

        if macro_type == "auto_rp":
            self.config_modifier = discord.ui.TextInput(
                label="Modifier Key (ALT/SHIFT/CTRL atau -)",
                placeholder="Contoh: ALT (atau - jika tidak ada)",
                max_length=10, required=True, row=0
            )
            self.config_primary_key = discord.ui.TextInput(
                label="Primary Key (F1-F12, A-Z, 0-9, NUM0-9)",
                placeholder="Contoh: F5", max_length=5, required=True, row=1
            )
            self.add_item(self.config_modifier)
            self.add_item(self.config_primary_key)

        elif macro_type == "cmd":
            self.config_command = discord.ui.TextInput(
                label="Command Pemicu (harus dimulai /)",
                placeholder="Contoh: /mancing", max_length=50, required=True, row=0
            )
            self.add_item(self.config_command)

    async def on_submit(self, interaction: discord.Interaction):
        self.theme_value = self.theme.value.strip()
        self.details_value = self.details.value.strip() or "Tidak ada detail tambahan"
        self.language_value = self.language.value.strip() or "Bahasa Indonesia baku" # Ambil bahasa

        try:
            if self.macro_type == "auto_rp":
                mod = self.config_modifier.value.strip().upper()
                if mod == "-": mod_val = "Tidak Ada"
                elif mod in ["ALT", "SHIFT", "CTRL"]: mod_val = mod
                else: raise ValueError("Modifier tidak valid!")

                key = self.config_primary_key.value.strip().upper()
                valid_keys = (
                    [f"F{i}" for i in range(1, 13)] + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") +
                    [str(i) for i in range(10)] + [f"NUM{i}" for i in range(10)]
                )
                if key not in valid_keys: raise ValueError("Key tidak valid!")

                self.config_value = {"modifier": mod_val, "primary_key": key}
                config_info = f"Hotkey: `{mod_val if mod_val != 'Tidak Ada' else ''}{'+' if mod_val != 'Tidak Ada' else ''}{key}`"

            elif self.macro_type == "cmd":
                cmd = self.config_command.value.strip()
                if not cmd.startswith("/"): raise ValueError("Command harus dimulai /")
                if len(cmd) < 2: raise ValueError("Command terlalu pendek!")
                self.config_value = cmd
                config_info = f"Command: `{cmd}`"
            else:
                config_info = "Error Tipe"

            await interaction.response.send_message(
                f"✅ **Konfigurasi Diterima**\n"
                f"**Tema:** {self.theme_value}\n"
                f"**Bahasa:** {self.language_value}\n" # Tampilkan bahasa
                f"**Info:** {config_info}",
                ephemeral=True
            )
        except ValueError as e:
            self.theme_value = None # Reset jika gagal
            await interaction.response.send_message(f"❌ **Validasi Gagal!**\n{e}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error pada ConfigInputModal: {e}")
            await interaction.response.send_message("❌ Error tak terduga.", ephemeral=True)


class WeaponConfigModal(discord.ui.Modal, title="Konfigurasi Gun RP (Aksi Tunggal)"):
    """Modal untuk Gun RP 'draw' ATAU 'holster'."""
    theme = discord.ui.TextInput(label="Tema/Aktivitas RP (Wajib)", placeholder="Contoh: Mengeluarkan Deagle", max_length=100, required=True, row=0)
    details = discord.ui.TextInput(label="Detail Tambahan (opsional)", placeholder="Contoh: Sambil awas", style=discord.TextStyle.paragraph, max_length=300, required=False, row=1)
    # --- Input Bahasa Baru ---
    language = discord.ui.TextInput(label="Bahasa/Aksen RP (Opsional)", placeholder="Default: Bahasa Indonesia baku", default="Bahasa Indonesia baku", max_length=50, required=False, row=2)
    # -----------------------

    def __init__(self):
        super().__init__()
        self.theme_value = None
        self.details_value = None
        self.language_value = None # Simpan bahasa

    async def on_submit(self, interaction: discord.Interaction):
        self.theme_value = self.theme.value.strip()
        self.details_value = self.details.value.strip() or "Tidak ada detail tambahan"
        self.language_value = self.language.value.strip() or "Bahasa Indonesia baku" # Ambil bahasa
        await interaction.response.send_message(
            f"✅ **Tema Gun RP Diterima**\n"
            f"**Tema:** {self.theme_value}\n"
            f"**Bahasa:** {self.language_value}", # Tampilkan bahasa
            ephemeral=True
        )


class WeaponConfigModalBoth(discord.ui.Modal, title="Konfigurasi Gun RP (Keduanya)"):
    """Modal khusus untuk Gun RP 'Keduanya'."""
    theme_draw = discord.ui.TextInput(label="Tema Keluarkan Senjata (Wajib)", placeholder="Contoh: Mengambil Deagle dari holster", max_length=100, required=True, row=0)
    details_draw = discord.ui.TextInput(label="Detail Tambahan (Keluarkan)", placeholder="Contoh: Sambil awas", max_length=300, required=False, row=1)
    theme_holster = discord.ui.TextInput(label="Tema Simpan Senjata (Wajib)", placeholder="Contoh: Memasukkan Deagle ke holster", max_length=100, required=True, row=2)
    details_holster = discord.ui.TextInput(label="Detail Tambahan (Simpan)", placeholder="Contoh: Setelah aman", max_length=300, required=False, row=3)
    # --- Input Bahasa Baru ---
    language = discord.ui.TextInput(label="Bahasa/Aksen RP (Opsional)", placeholder="Default: Bahasa Indonesia baku", default="Bahasa Indonesia baku", max_length=50, required=False, row=4)
    # -----------------------

    def __init__(self):
        super().__init__()
        self.theme_draw_value = None
        self.details_draw_value = None
        self.theme_holster_value = None
        self.details_holster_value = None
        self.language_value = None # Simpan bahasa

    async def on_submit(self, interaction: discord.Interaction):
        self.theme_draw_value = self.theme_draw.value.strip()
        self.details_draw_value = self.details_draw.value.strip() or "Tidak ada detail tambahan"
        self.theme_holster_value = self.theme_holster.value.strip()
        self.details_holster_value = self.details_holster.value.strip() or "Tidak ada detail tambahan"
        self.language_value = self.language.value.strip() or "Bahasa Indonesia baku" # Ambil bahasa

        await interaction.response.send_message(
            f"✅ **Tema Gun RP Diterima**\n"
            f"**Bahasa:** {self.language_value}\n" # Tampilkan bahasa
            f"**Tema Keluarkan:** {self.theme_draw_value}\n"
            f"**Tema Simpan:** {self.theme_holster_value}",
            ephemeral=True
        )

# ============================
# COG UTAMA
# ============================
class TemplateCreatorCog(commands.Cog, name="TemplateCreator"):
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        self.active_sessions = {}

    # --- DIPERBARUI: Terima parameter bahasa ---
    async def _get_ai_analysis(self, theme: str, details: str, language: str) -> Optional[List[Dict]]:
        """Menggunakan AI untuk generate langkah-langkah RP dalam bahasa yang diminta."""
        # --- [INI BAGIAN KRUSIAL] ---
        # Prompt sekarang menggunakan AI_TEMPLATE_PROMPT yang baru
        prompt = AI_TEMPLATE_PROMPT.format(theme=theme, details=details, language=language) # Masukkan bahasa ke prompt
        logger.info(f"Mengirim prompt ke AI (Bahasa: {language})") # Log bahasa yang digunakan

        # (Logika pemilihan AI tetap sama)
        if self.config.GEMINI_API_KEYS:
            try:
                genai.configure(api_key=self.config.GEMINI_API_KEYS[0])
                model = genai.GenerativeModel('gemini-1.5-flash')
                # Perbarui cara memanggil Gemini untuk JSON output
                response = await model.generate_content_async(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        response_mime_type="application/json"
                    )
                )
                cleaned = re.sub(r'```json\s*|\s*```', '', response.text.strip(), flags=re.DOTALL)
                data = json.loads(cleaned)
                logger.info("AI (Gemini) berhasil generate.")
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
                    logger.info("AI (DeepSeek) berhasil generate.")
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
                logger.info("AI (OpenAI) berhasil generate.")
                return data.get("steps", [])
            except Exception as e:
                logger.error(f"OpenAI gagal: {e}")

        return None
    # ------------------------------------------

    # (Fungsi _format_* tetap sama)
    def _format_pc_auto_rp(self, title: str, modifier: str, primary_key: str, steps: List[Dict]) -> str:
        output = f"TITLE:{title}\nMODIFIER:{modifier}\nPRIMARY_KEY:{primary_key}\n"
        for step in steps: output += f"STEP:{step.get('delay', 2)}:{step['command']}\n"
        output += "END_MACRO\n"; return output

    def _format_pc_cmd_macro(self, title: str, command: str, steps: List[Dict]) -> str:
        output = f"TITLE:{title}\nCMD:{command}\n"
        for step in steps: output += f"STEP:{step.get('delay', 1)}:{step['command']}\n"
        output += "END_MACRO\n"; return output

    def _format_pc_gun_rp(self, title: str, weapon_id: int, action: str, steps: List[Dict]) -> str:
        output = f"WEAPON_ID:{weapon_id}\nACTION:{action}\nTITLE:{title}\n"
        for step in steps: output += f"STEP:{step.get('delay', 1)}:{step['command']}\n"
        output += "END_GUN_MACRO\n"; return output

    # --- PERUBAHAN NAMA PERINTAH ---
    @commands.command(name="buatrp")
    # -------------------------------
    async def create_template_command(self, ctx):
        """Membuat template Auto RP untuk KotkaHelper (PC/Mobile)"""
        if ctx.author.id in self.active_sessions:
            return await ctx.send("❌ Sesi aktif. Selesaikan/tunggu timeout.", delete_after=10)

        self.active_sessions[ctx.author.id] = {}

        # Langkah 1: Pilih Tipe Macro
        embed_type = discord.Embed(
            title="🎨 KotkaHelper Template Creator",
            description=f"**Langkah 1/3:** Pilih tipe macro (Format KHP)", color=0x5865F2
        )
        embed_type.add_field(name="⌨️ Auto RP Macro", value="Aktivasi: Hotkey/Button", inline=False)
        embed_type.add_field(name="💬 CMD Macro", value="Aktivasi: Command chat", inline=False)
        embed_type.add_field(name="🔫 Gun RP Macro", value="Aktivasi: Otomatis ganti senjata", inline=False)

        type_view = MacroTypeSelectView(ctx.author.id)
        type_msg = await ctx.send(embed=embed_type, view=type_view)

        await type_view.wait()
        if not type_view.macro_type:
            del self.active_sessions[ctx.author.id]
            return await type_msg.edit(content="⏱️ Timeout.", embed=None, view=None)

        macro_type = type_view.macro_type
        self.active_sessions[ctx.author.id]["macro_type"] = macro_type
        await type_msg.delete()
        modal_msg = None # Untuk pesan tombol buka modal

        try:
            # --- Alur Utama ---
            class OpenModalView(discord.ui.View): # Kelas view pembuka modal generik
                    def __init__(self, author_id, button_label):
                        super().__init__(timeout=180)
                        self.author_id = author_id
                        self.interaction = None
                        btn = discord.ui.Button(label=button_label, style=discord.ButtonStyle.primary)
                        # --- PERBAIKAN ERROR TypeError ---
                        btn.callback = self.open_modal_btn
                        # ---------------------------------
                        self.add_item(btn)

                    async def interaction_check(self, interaction: discord.Interaction) -> bool:
                        return interaction.user.id == self.author_id

                    # --- PERBAIKAN ERROR TypeError ---
                    async def open_modal_btn(self, interaction: discord.Interaction): # Hapus parameter 'button'
                    # ---------------------------------
                        self.interaction = interaction
                        self.stop()

            if macro_type == "gun":
                # Langkah 2 (Gun RP): Pilih Senjata
                weapon_view = WeaponSelectView(ctx.author.id)
                weapon_msg = await ctx.send("🔫 **Langkah 2/3:** Pilih senjata:", view=weapon_view)
                await weapon_view.wait()
                if not weapon_view.weapon_id or not weapon_view.action:
                    del self.active_sessions[ctx.author.id]
                    return await weapon_msg.edit(content="⏱️ Timeout.", view=None)
                self.active_sessions[ctx.author.id].update({
                    "weapon_id": weapon_view.weapon_id, "action": weapon_view.action
                })
                await weapon_msg.delete()

                # Tentukan modal & label tombol
                if weapon_view.action == "both":
                    modal = WeaponConfigModalBoth()
                    modal_button_label = "📝 Isi Tema Keluarkan & Simpan (Langkah 3/3)"
                else:
                    modal = WeaponConfigModal()
                    modal_button_label = f"📝 Isi Tema '{weapon_view.action}' (Langkah 3/3)"

            else: # Auto RP atau CMD Macro
                modal_title = "Konfigurasi Auto RP Macro" if macro_type == "auto_rp" else "Konfigurasi CMD Macro"
                modal = ConfigInputModal(macro_type, modal_title)
                modal_button_label = "📝 Isi Konfigurasi & Tema (Langkah 2&3/3)"

            # Langkah Terakhir (Semua Tipe): Buka Modal
            view = OpenModalView(ctx.author.id, modal_button_label)
            modal_msg = await ctx.send(f"{ctx.author.mention}, klik tombol:", view=view)
            await view.wait()

            if not view.interaction:
                del self.active_sessions[ctx.author.id]
                return await modal_msg.edit(content="⏱️ Timeout.", view=None)

            await view.interaction.response.send_modal(modal)
            await modal.wait() # Tunggu modal di-submit

            # Simpan hasil modal
            if macro_type == "gun":
                if modal.language_value: # Cek apakah modal berhasil disubmit
                    self.active_sessions[ctx.author.id]["language"] = modal.language_value
                    if self.active_sessions[ctx.author.id]["action"] == "both":
                        self.active_sessions[ctx.author.id].update({
                            "theme_draw": modal.theme_draw_value, "details_draw": modal.details_draw_value,
                            "theme_holster": modal.theme_holster_value, "details_holster": modal.details_holster_value
                        })
                    else:
                        self.active_sessions[ctx.author.id].update({
                            "theme": modal.theme_value, "details": modal.details_value
                        })
                else:
                     del self.active_sessions[ctx.author.id]; return # Modal dibatalkan
            else: # Auto RP / CMD
                if modal.theme_value: # Cek apakah modal berhasil disubmit
                    self.active_sessions[ctx.author.id].update({
                        "theme": modal.theme_value, "details": modal.details_value,
                        "language": modal.language_value
                    })
                    if macro_type == "auto_rp":
                         self.active_sessions[ctx.author.id].update({
                            "modifier": modal.config_value["modifier"], "primary_key": modal.config_value["primary_key"]
                         })
                    elif macro_type == "cmd":
                        self.active_sessions[ctx.author.id]["command"] = modal.config_value
                else:
                    del self.active_sessions[ctx.author.id]; return # Modal dibatalkan

        except Exception as e:
            logger.error(f"Error alur konfigurasi: {e}", exc_info=True)
            if ctx.author.id in self.active_sessions: del self.active_sessions[ctx.author.id]
            if modal_msg: await modal_msg.edit(content=f"❌ Error: {e}", view=None)
            else: await ctx.send(f"❌ Error: {e}")
            return

        if modal_msg: await modal_msg.delete()

        # --- Generate AI ---
        session = self.active_sessions.get(ctx.author.id)
        if not session: return await ctx.send("❌ Sesi Error.")

        loading_msg = await ctx.send("🤖 **Generating AI...**")
        steps_draw, steps_holster, steps_single = None, None, None
        language = session.get("language", "Bahasa Indonesia baku") # Ambil bahasa dari sesi

        try:
            if session.get("macro_type") == "gun" and session.get("action") == "both":
                theme_d = session.get("theme_draw", "mengeluarkan")
                details_d = session.get("details_draw", "")
                theme_h = session.get("theme_holster", "menyimpan")
                details_h = session.get("details_holster", "")
                await loading_msg.edit(content=f"🤖 Generating 'Keluarkan' ({language})...")
                steps_draw = await self._get_ai_analysis(theme_d, details_d, language)
                await loading_msg.edit(content=f"🤖 Generating 'Simpan' ({language})...")
                steps_holster = await self._get_ai_analysis(theme_h, details_h, language)
                if not steps_draw or not steps_holster: raise Exception("AI Gagal (Both)")
            else:
                theme = session.get("theme", "rp")
                details = session.get("details", "")
                await loading_msg.edit(content=f"🤖 Generating RP ({language})...")
                steps_single = await self._get_ai_analysis(theme, details, language)
                if not steps_single: raise Exception("AI Gagal (Single)")
        except Exception as ai_error:
             del self.active_sessions[ctx.author.id]
             return await loading_msg.edit(content=f"❌ Gagal generate AI: {ai_error}")

        # --- Format & Kirim Hasil ---
        session = self.active_sessions[ctx.author.id] # Refresh
        theme_display = "N/A" # Fallback

        if macro_type == "auto_rp":
            title = f"RP {session['theme'][:30]}"
            output = self._format_pc_auto_rp(title, session["modifier"], session["primary_key"], steps_single)
            filename = "KotkaHelper_Macros.txt"
            theme_display = session['theme']
            footer_text = f"AI ({language}) • {len(steps_single)} langkah"
        elif macro_type == "cmd":
            title = f"RP {session['theme'][:30]}"
            output = self._format_pc_cmd_macro(title, session["command"], steps_single)
            filename = "KotkaHelper_CmdMacros.txt"
            theme_display = session['theme']
            footer_text = f"AI ({language}) • {len(steps_single)} langkah"
        else: # gun
            action = session.get("action", "draw")
            if action == "both":
                title_draw = f"RP {session['theme_draw'][:25]} (K)"
                title_holster = f"RP {session['theme_holster'][:25]} (S)"
                output_draw = self._format_pc_gun_rp(title_draw, session["weapon_id"], "draw", steps_draw)
                output_holster = self._format_pc_gun_rp(title_holster, session["weapon_id"], "holster", steps_holster)
                output = output_draw + "\n" + output_holster
                theme_display = f"Keluarkan: {session['theme_draw']}\nSimpan: {session['theme_holster']}"
                footer_text = f"AI ({language}) • {len(steps_draw)} + {len(steps_holster)} langkah"
            else:
                title = f"RP {session['theme'][:30]}"
                output = self._format_pc_gun_rp(title, session["weapon_id"], action, steps_single)
                filename = "KotkaHelper_GunRP.txt"
                theme_display = session['theme']
                footer_text = f"AI ({language}) • {len(steps_single)} langkah"
            filename = "KotkaHelper_GunRP.txt" # filename selalu sama untuk Gun RP

        embed_result = discord.Embed(
            title="✅ Template Berhasil Dibuat!",
            description=f"**Tipe:** {macro_type.replace('_', ' ').title()}\n**Tema:** {theme_display}\n**Bahasa:** {language}",
            color=0x00FF00
        )
        embed_result.add_field(
            name="📋 Cara Pakai (PC/Mobile - KHP Format)",
            value=(
                f"1. Buka file `{filename}`.\n"
                + ("2. File ini berisi 2 template (Keluarkan & Simpan).\n3. Copy-paste *kedua* template." if macro_type=="gun" and action=="both"
                   else f"2. Copy isi file di bawah.\n3. Paste ke *akhir* file `{filename}` Anda.") + "\n4. Simpan & restart script."
            ),
            inline=False
        )
        embed_result.set_footer(text=footer_text)

        try:
            import io
            file_content = output.encode('utf-8')
            file_buffer = io.BytesIO(file_content)
            file_buffer.seek(0)
            file = discord.File(fp=file_buffer, filename=filename)
            await loading_msg.delete()
            await ctx.send(embed=embed_result, file=file)
        except Exception as file_error:
            logger.error(f"Error buat file: {file_error}", exc_info=True)
            await loading_msg.edit(content=f"⚠️ Gagal buat file:\n```\n{output[:1900]}\n```")
            if len(output) > 1900: await ctx.send(f"```\n{output[1900:][:1900]}\n```")

        del self.active_sessions[ctx.author.id] # Hapus sesi setelah selesai
        logger.info(f"Template '{macro_type}' by {ctx.author.id} ({language})")

    # --- PERUBAHAN NAMA PERINTAH BANTUAN ---
    @commands.command(name="templatehelp")
    # --------------------------------------
    async def template_help_command(self, ctx):
        """Bantuan untuk fitur Template Creator"""
        embed = discord.Embed(
            title="📚 KotkaHelper Template Creator - Bantuan",
            description="Fitur membuat template Auto RP (PC/Mobile) via AI.",
            color=0x3498db
        )
        embed.add_field(
            name="🎯 Cara Pakai",
            value=("1. Ketik `!buatrp`\n2. Pilih tipe macro\n3. Ikuti alur & isi form (termasuk Bahasa/Aksen)\n4. AI generate template"), inline=False
        )
        embed.add_field(
            name="🌐 Bahasa & Aksen",
            value=("Anda bisa input bahasa & aksen di form (opsional). Contoh: `English`, `Spanish (Mexico)`, `Russian accent`."), inline=False
        )
        embed.add_field(
            name="📝 Aturan AI (SAMP)",
            value=("✅ /me=Aksi, /do=Hasil/Tanya\n✅ 3-7 langkah, delay 2-4s\n✅ Konteks SAMP (SOS, Deagle, dll)\n❌ No Force RP, Undetailed, /do bohong"), inline=False
        )
        embed.add_field(
            name="💡 Tips Tema",
            value=("✅ Spesifik: 'Mancing malam hari'\n✅ Konteks: 'Masuk mobil hujan'\n✅ (Gun Both): Isi tema Keluarkan & Simpan"), inline=False
        )
        embed.add_field(
            name="⌨️ Tipe Macro",
            value=("**Auto RP:** Hotkey\n**CMD Macro:** Command chat\n**Gun RP:** Otomatis ganti senjata"), inline=False
        )
        embed.add_field(
            name="📂 Format Output",
            value=("**`.txt` (KHP Format):** Kompatibel PC & Android."), inline=False
        )
        embed.set_footer(text="Dibuat oleh Kotkaaja • AI mengikuti aturan SAMP RP")
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Error handler untuk Template Creator"""
        if ctx.command and ctx.command.name not in ['buatrp', 'templatehelp']: return # Sesuaikan nama
        if isinstance(error, commands.CommandNotFound): return
        if ctx.author.id in self.active_sessions: del self.active_sessions[ctx.author.id]

        if isinstance(error, commands.CommandInvokeError):
            if isinstance(error.original, discord.NotFound):
                logger.warning(f"Error NotFound (interaksi timeout?): {error.original}")
                await ctx.send("❌ Interaksi timeout/tidak valid. Coba lagi `!buatrp`.")
            else:
                logger.error(f"Error di {ctx.command.name}: {error.original}", exc_info=True)
                await ctx.send(f"❌ Error: `{str(error.original)[:200]}`")
        else:
            logger.error(f"Error tak terduga: {error}", exc_info=True)
            await ctx.send("❌ Error tak terduga.")


    def cog_unload(self):
        self.active_sessions.clear()
        logger.info("Template Creator Cog unloaded.")

async def setup(bot):
    await bot.add_cog(TemplateCreatorCog(bot))
