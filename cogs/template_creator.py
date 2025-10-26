# -*- coding: utf-8 -*-
import discord
from discord import ui
from discord.ext import commands
import logging
import io
import time
import json
import asyncio # <-- Pastikan asyncio diimpor
from typing import Dict, List, Optional, Tuple
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ============================================
# DATA KONSTANTA (Sama seperti sebelumnya)
# ============================================
KHP_MODIFIERS = ["Tidak Ada", "ALT", "SHIFT", "CTRL"]
KHP_KEYS = (
    [f"F{i}" for i in range(1, 13)] +
    [chr(ord('A') + i) for i in range(26)] +
    [str(i) for i in range(10)] +
    [f"NUM{i}" for i in range(10)]
)
WEAPON_NAMES = {
    22: "Pistol", 23: "Silenced Pistol", 24: "Desert Eagle",
    25: "Shotgun", 26: "Sawn-Off", 27: "Combat Shotgun",
    28: "Uzi", 29: "MP5", 30: "AK-47", 31: "M4", 32: "Tec-9",
    33: "Rifle", 34: "Sniper Rifle"
}
WEAPON_NAME_TO_ID = {v: k for k, v in WEAPON_NAMES.items()}

# ============================================
# PROMPT AI (Sama seperti sebelumnya)
# ============================================
AI_RP_GENERATION_PROMPT = """
Peran: Anda adalah penulis RP (Roleplay) SAMP (San Andreas Multiplayer) yang kreatif dan berpengalaman.

Tugas: Buat urutan langkah RP yang realistis dan imersif berdasarkan detail yang diberikan. Gunakan hanya perintah `/me` untuk tindakan fisik dan `/do` untuk deskripsi lingkungan atau hasil tindakan.

Detail Masukan:
- Platform Target: {platform} (KHP PC atau KHMobile)
- Tipe Macro: {macro_type} (Auto RP via Hotkey, CMD via Perintah Chat, atau Gun RP Otomatis)
- Detail Spesifik Macro: {details_str} (Contoh: Hotkey F5, Perintah /mancing, Senjata AK-47 aksi 'draw')
- Konteks RP yang Diminta Pengguna: {rp_context}

Instruksi Spesifik:
1.  Hasilkan antara 3 hingga 6 langkah RP. Gunakan kombinasi `/me` dan `/do` yang logis.
2.  Berikan jeda (delay) yang masuk akal SETELAH setiap langkah, dalam satuan DETIK (angka bulat antara 1 hingga 5). Jeda Gun RP biasanya lebih singkat (1-2 detik). Jeda CMD/AutoRP bisa lebih bervariasi (1-5 detik).
3.  Jaga teks RP tetap singkat, jelas, dan sesuai konteks SAMP.
4.  Output HARUS berupa JSON list yang valid, tanpa teks tambahan di luar JSON. Formatnya:
    ```json
    [
      {{"command": "/me mengambil peralatan dari bagasi", "delay_sec": 2}},
      {{"command": "/do Terlihat kunci inggris dan dongkrak.", "delay_sec": 3}},
      {{"command": "/me mulai mengganti ban.", "delay_sec": 5}}
    ]
    ```

Contoh Konteks Pengguna -> Hasil Langkah RP yang Baik:
- Konteks: "Mekanik mengganti ban mobil pelanggan"
  -> /me membuka bagasi, mengambil alat. -> /do Alat terlihat. -> /me mendongkrak mobil. -> /me melepas ban. -> /me memasang ban baru.
- Konteks: "Polisi menilang pengendara motor"
  -> /me memberhentikan pengendara motor ke tepi. -> /me meminta surat-surat kendaraan. -> /do Pengendara memberikan STNK dan SIM. -> /me menulis surat tilang.
- Konteks: "Mengeluarkan AK-47" (Gun RP Draw)
  -> /me melepas selempang AK-47 dari bahu. -> /do Senjata siap digunakan.

Sekarang, buat langkah-langkah RP berdasarkan detail masukan di atas.
"""

# ============================================
# UI COMPONENTS (Sama seperti sebelumnya)
# ============================================
class AIContextModal(ui.Modal, title="Deskripsi RP untuk AI"):
    rp_context = ui.TextInput(label="Jelaskan Aksi RP yang Diinginkan", placeholder="Contoh: Mekanik mengganti oli...", style=discord.TextStyle.paragraph, required=True, max_length=300)
    async def on_submit(self, interaction: discord.Interaction):
        # Simpan data dan interaction object
        self.interaction = interaction # Simpan interaction object
        interaction.data['rp_context'] = self.rp_context.value
        await interaction.response.defer()
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"Error di AIContextModal: {error}", exc_info=True)
        # Cek jika sudah direspons
        if not interaction.response.is_done():
            await interaction.response.send_message("Terjadi error pada modal.", ephemeral=True)
        else:
             await interaction.followup.send("Terjadi error pada modal.", ephemeral=True)


class BaseDetailsModal(ui.Modal):
    title_input = ui.TextInput(label="Judul/Nama Macro", placeholder="Contoh: RP Mancing Ikan", style=discord.TextStyle.short, required=True, max_length=128)
    def __init__(self, title: str): super().__init__(title=title)
    # [PERBAIKAN] Tambahkan on_error
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"Error di BaseDetailsModal ({self.title}): {error}", exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("Terjadi error pada modal detail.", ephemeral=True)
        else:
            await interaction.followup.send("Terjadi error pada modal detail.", ephemeral=True)


class AutoRP_KHP_Modal(BaseDetailsModal):
    modifier = ui.Select(placeholder="Pilih Tombol Modifier...", options=[discord.SelectOption(label=m) for m in KHP_MODIFIERS])
    primary_key = ui.Select(placeholder="Pilih Tombol Utama...", options=[discord.SelectOption(label=k) for k in KHP_KEYS[:25]])
    def __init__(self):
        super().__init__(title="Detail Auto RP Macro (KHP)")
        self.add_item(ui.Select(placeholder="Pilih Tombol Utama (Lanjutan)...", options=[discord.SelectOption(label=k) for k in KHP_KEYS[25:50]]))
        self.add_item(ui.Select(placeholder="Pilih Tombol Utama (Lanjutan 2)...", options=[discord.SelectOption(label=k) for k in KHP_KEYS[50:]]))
    async def on_submit(self, interaction: discord.Interaction):
        self.interaction = interaction # Simpan interaction
        selected_key = None
        for item in self.children:
            if isinstance(item, ui.Select) and item.placeholder.startswith("Pilih Tombol Utama"):
                if item.values: selected_key = item.values[0]; break
        if not selected_key: await interaction.response.send_message("Anda harus memilih Tombol Utama.", ephemeral=True); return
        interaction.data['details'] = {"title": self.title_input.value, "modifier": self.modifier.values[0], "primary_key": selected_key}
        await interaction.response.defer()

class CMD_Modal(BaseDetailsModal):
    command_trigger = ui.TextInput(label="Command Pemicu", placeholder="Contoh: /perbaiki", style=discord.TextStyle.short, required=True, max_length=128)
    def __init__(self, platform: str): super().__init__(title=f"Detail CMD Macro ({platform})")
    async def on_submit(self, interaction: discord.Interaction):
        self.interaction = interaction # Simpan interaction
        trigger = self.command_trigger.value
        if not trigger.startswith('/'): await interaction.response.send_message("Command Pemicu harus diawali dengan '/'.", ephemeral=True); return
        interaction.data['details'] = {"title": self.title_input.value, "command": trigger}
        await interaction.response.defer()

class GunRP_Modal(BaseDetailsModal):
    weapon = ui.Select(placeholder="Pilih Senjata...", options=[discord.SelectOption(label=name) for name in list(WEAPON_NAMES.values())[:25]])
    action = ui.Select(placeholder="Pilih Aksi...", options=[discord.SelectOption(label="Keluarkan Senjata", value="draw", emoji="▶️"), discord.SelectOption(label="Simpan Senjata", value="holster", emoji="◀️")])
    def __init__(self, platform: str):
        super().__init__(title=f"Detail Gun RP Macro ({platform})")
        if len(WEAPON_NAMES) > 25: self.add_item(ui.Select(placeholder="Pilih Senjata (Lanjutan)...", options=[discord.SelectOption(label=name) for name in list(WEAPON_NAMES.values())[25:]]))
    async def on_submit(self, interaction: discord.Interaction):
        self.interaction = interaction # Simpan interaction
        selected_weapon_name = None
        for item in self.children:
             if isinstance(item, ui.Select) and item.placeholder.startswith("Pilih Senjata"):
                 if item.values: selected_weapon_name = item.values[0]; break
        if not selected_weapon_name: await interaction.response.send_message("Anda harus memilih Senjata.", ephemeral=True); return
        weapon_id = WEAPON_NAME_TO_ID.get(selected_weapon_name)
        if not weapon_id: await interaction.response.send_message("Senjata tidak valid.", ephemeral=True); return
        interaction.data['details'] = {"title": self.title_input.value, "weapon_id": weapon_id, "weapon_name": selected_weapon_name, "action": self.action.values[0]}
        await interaction.response.defer()

# --- Views (Sama) ---
class MacroTypeSelectView(ui.View):
    def __init__(self, author_id: int, platform: str): super().__init__(timeout=180); self.author_id = author_id; self.platform = platform; self.macro_type: Optional[str] = None; self.interaction: Optional[discord.Interaction] = None # Simpan interaksi
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id: await interaction.response.send_message("Hanya peminta...", ephemeral=True); return False
        return True
    async def _handle_selection(self, interaction: discord.Interaction, macro_type: str):
        self.interaction = interaction # Simpan interaksi
        self.macro_type = macro_type; self.stop(); await interaction.response.defer()
    @ui.button(label="Auto RP Macro", style=discord.ButtonStyle.primary, emoji="🔥")
    async def auto_rp(self, interaction: discord.Interaction, button: ui.Button): await self._handle_selection(interaction, "auto_rp")
    @ui.button(label="CMD Macro", style=discord.ButtonStyle.primary, emoji="⌨️")
    async def cmd_macro(self, interaction: discord.Interaction, button: ui.Button): await self._handle_selection(interaction, "cmd")
    @ui.button(label="Gun RP Macro", style=discord.ButtonStyle.primary, emoji="🔫")
    async def gun_rp(self, interaction: discord.Interaction, button: ui.Button): await self._handle_selection(interaction, "gun")

class PlatformSelectView(ui.View):
    def __init__(self, author_id: int): super().__init__(timeout=180); self.author_id = author_id; self.platform: Optional[str] = None; self.interaction: Optional[discord.Interaction] = None # Simpan interaksi
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id: await interaction.response.send_message("Hanya peminta...", ephemeral=True); return False
        return True
    async def _handle_selection(self, interaction: discord.Interaction, platform: str):
        self.interaction = interaction # Simpan interaksi
        self.platform = platform; self.stop(); await interaction.response.defer()
    @ui.button(label="PC (KHP)", style=discord.ButtonStyle.blurple, emoji="💻")
    async def pc(self, interaction: discord.Interaction, button: ui.Button): await self._handle_selection(interaction, "KHP")
    @ui.button(label="Mobile (KHMobile)", style=discord.ButtonStyle.green, emoji="📱")
    async def mobile(self, interaction: discord.Interaction, button: ui.Button): await self._handle_selection(interaction, "KHMobile")

# ============================================
# FUNGSI FORMATTING TEMPLATE (Sama)
# ============================================
def format_template(platform: str, macro_type: str, details: Dict, steps: List[Dict]) -> Tuple[str, str]:
    title = details.get("title", "Template_Generated")
    sanitized_title = "".join(c if c.isalnum() else "_" for c in title)
    filename = f"{platform}_{macro_type}_{sanitized_title}.txt"
    content = ""
    unique_id = str(int(time.time()))

    if platform == "KHP":
        if macro_type == "auto_rp":
            filename = "KotkaHelper_Macros.txt"
            content += f"TITLE:{title}\n"
            content += f"MODIFIER:{details.get('modifier', 'Tidak Ada')}\n"
            content += f"PRIMARY_KEY:{details.get('primary_key', 'F1')}\n"
            for step in steps:
                delay_ms = step.get('delay_sec', 1) * 1000
                content += f"STEP:{delay_ms}:{step.get('command', '/me error')}\n"
            content += "END_MACRO\n"
        elif macro_type == "cmd":
            filename = "KotkaHelper_CmdMacros.txt"
            content += f"TITLE:{title}\n"
            content += f"CMD:{details.get('command', '/defaultcmd')}\n"
            for step in steps:
                delay_s = step.get('delay_sec', 1)
                content += f"STEP:{delay_s}:{step.get('command', '/me error')}\n"
            content += "END_MACRO\n"
        elif macro_type == "gun":
            filename = "KotkaHelper_GunRP.txt"
            content += f"WEAPON_ID:{details.get('weapon_id', 22)}\n"
            content += f"ACTION:{details.get('action', 'draw')}\n"
            content += f"TITLE:{title}\n"
            for step in steps:
                delay_s = step.get('delay_sec', 1)
                content += f"STEP:{delay_s}:{step.get('command', '/me error')}\n"
            content += "END_GUN_MACRO\n"
    elif platform == "KHMobile":
        macro_data = {"name": title, "steps": [] }
        json_container = {}
        if macro_type == "auto_rp":
            for step in steps:
                delay_ms = step.get('delay_sec', 1) * 1000
                macro_data["steps"].append({"command": step.get('command', '/me error'), "delay": delay_ms})
            json_container = {"macros": {unique_id: macro_data}}
            content = f"// --- Auto RP Macro ---\n// ID: {unique_id}\n// Tambahkan ID '{unique_id}' ke `macro_id` pada tombol...\n"
        elif macro_type == "cmd":
            macro_data["command"] = details.get('command', '/defaultcmd')
            for step in steps:
                delay_s = step.get('delay_sec', 1)
                macro_data["steps"].append({"command": step.get('command', '/me error'), "delay": delay_s})
            json_container = {"cmdMacros": {unique_id: macro_data}}
            content = f"// --- CMD Macro ---\n// ID: {unique_id}\n"
        elif macro_type == "gun":
            macro_data["weaponId"] = details.get('weapon_id', 22)
            macro_data["action"] = details.get('action', 'draw')
            for step in steps:
                delay_s = step.get('delay_sec', 1)
                macro_data["steps"].append({"command": step.get('command', '/me error'), "delay": delay_s})
            json_container = {"gunMacros": {unique_id: macro_data}}
            content = f"// --- Gun RP Macro ---\n// ID: {unique_id}\n"

        content += json.dumps(json_container, indent=4)
        filename = f"{sanitized_title}.json"

    return content, filename

# ============================================
# KELAS COG UTAMA (Dimodifikasi lagi)
# ============================================
class TemplateCreatorCog(commands.Cog, name="TemplateCreator"):
    def __init__(self, bot):
        self.bot = bot
        self.openai_client = None
        if bot.config.OPENAI_API_KEYS:
            try:
                self.openai_client = AsyncOpenAI(api_key=bot.config.OPENAI_API_KEYS[0])
                logger.info("✅ OpenAI client untuk Template Creator berhasil diinisialisasi.")
            except Exception as e:
                logger.error(f"❌ Gagal inisialisasi OpenAI client: {e}")
        else:
            logger.warning("⚠️ OPENAI_API_KEYS tidak ditemukan. Fitur AI Template Creator tidak akan berfungsi.")

    # --- Fungsi Panggil AI (Sama) ---
    async def _generate_rp_steps_with_ai(self, platform: str, macro_type: str, details: Dict, rp_context: str) -> List[Dict]:
        if not self.openai_client: raise ValueError("OpenAI client tidak diinisialisasi.")
        details_str = json.dumps(details, ensure_ascii=False)
        prompt = AI_RP_GENERATION_PROMPT.format(platform=platform, macro_type=macro_type.replace('_',' ').title(), details_str=details_str, rp_context=rp_context)
        try:
            logger.info(f"Mengirim prompt RP generation ke OpenAI...")
            response = await self.openai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}, temperature=0.6, max_tokens=400)
            content = response.choices[0].message.content
            logger.debug(f"Raw AI response: {content}")
            if content.strip().startswith("```json"): content = content.strip()[7:-3].strip()
            elif content.strip().startswith("```"): content = content.strip()[3:-3].strip()
            steps = json.loads(content)
            if not isinstance(steps, list): raise ValueError("Format JSON dari AI bukan list.")
            for step in steps:
                if not isinstance(step, dict) or "command" not in step or "delay_sec" not in step: raise ValueError("Format item JSON tidak sesuai.")
                if not isinstance(step["delay_sec"], int): step["delay_sec"] = int(step["delay_sec"])
            logger.info(f"AI berhasil menghasilkan {len(steps)} langkah RP.")
            return steps
        except json.JSONDecodeError as e:
            logger.error(f"Gagal parse JSON dari OpenAI: {e}\nRaw content: {content}")
            raise ValueError(f"Gagal memproses respons AI (JSON tidak valid). Respons:\n```\n{content[:500]}\n```")
        except Exception as e:
            logger.error(f"Error saat memanggil OpenAI: {e}", exc_info=True)
            raise ValueError(f"Gagal menghubungi AI: {e}")

    # --- Perintah Panel (Sama) ---
    @commands.command(name="createtemplatepanel", aliases=["ctp"])
    @commands.has_permissions(administrator=True)
    async def create_template_panel(self, ctx: commands.Context):
        embed = discord.Embed(title="🛠️ Pembuat Template KotkaHelper (AI)", description="Tekan tombol...", color=discord.Color.orange())
        embed.set_footer(text="Fitur ini menggunakan AI OpenAI.")
        class StartView(ui.View):
            def __init__(self, cog_instance): super().__init__(timeout=None); self.cog = cog_instance
            @ui.button(label="Buat Template (AI)", style=discord.ButtonStyle.success, emoji="✨", custom_id="start_template_creation_ai")
            async def start_button(self, interaction: discord.Interaction, button: ui.Button):
                if not self.cog.openai_client: await interaction.response.send_message("❌ Fitur AI tidak aktif...", ephemeral=True); return
                await self.cog.start_template_workflow(interaction)

        view_exists = any(v.custom_id == "start_template_creation_ai" for v in self.bot.persistent_views for item in v.children if hasattr(item, 'custom_id') and item.custom_id == "start_template_creation_ai")
        if not view_exists:
             if not hasattr(self.bot, 'persistent_template_view_added_ai'):
                 self.bot.add_view(StartView(self))
                 self.bot.persistent_template_view_added_ai = True
                 logger.info("Persistent view AI untuk Template Creator ditambahkan.")
        await ctx.send(embed=embed, view=StartView(self))


    # --- Alur Kerja Utama (Direvisi Lagi) ---
    async def start_template_workflow(self, interaction: discord.Interaction):
        author_id = interaction.user.id
        # Simpan interaksi awal untuk mengedit pesan status akhir
        initial_interaction = interaction

        try:
            # 1. Pilih Platform
            platform_view = PlatformSelectView(author_id)
            # Respons pertama HARUS menggunakan interaction.response
            await interaction.response.send_message("1️⃣ Pilih platform target:", view=platform_view, ephemeral=True)
            await platform_view.wait()
            if platform_view.platform is None: raise asyncio.TimeoutError("Pemilihan platform timeout.")
            platform = platform_view.platform
            # Dapatkan interaction dari view ini untuk langkah berikutnya
            platform_interaction = platform_view.interaction

            # 2. Pilih Tipe Macro
            type_view = MacroTypeSelectView(author_id, platform)
            # Gunakan interaction DARI LANGKAH SEBELUMNYA untuk edit pesan
            await platform_interaction.edit_original_response(content=f"Platform: **{platform}**. 2️⃣ Pilih jenis macro:", view=type_view)
            await type_view.wait()
            if type_view.macro_type is None: raise asyncio.TimeoutError("Pemilihan tipe macro timeout.")
            macro_type = type_view.macro_type
            # Dapatkan interaction dari view ini
            type_interaction = type_view.interaction

            # 3. Isi Detail Spesifik (Modal)
            details_modal: Optional[ui.Modal] = None
            # ... (logika pemilihan modal sama) ...
            if platform == "KHP":
                if macro_type == "auto_rp": details_modal = AutoRP_KHP_Modal()
                elif macro_type == "cmd": details_modal = CMD_Modal(platform)
                elif macro_type == "gun": details_modal = GunRP_Modal(platform)
            elif platform == "KHMobile":
                if macro_type == "auto_rp": details_modal = BaseDetailsModal("Detail Auto RP Macro (KHMobile)")
                elif macro_type == "cmd": details_modal = CMD_Modal(platform)
                elif macro_type == "gun": details_modal = GunRP_Modal(platform)
            if not details_modal: raise ValueError("Kombinasi platform & tipe macro tidak valid.")

            # Kirim modal menggunakan interaction DARI LANGKAH SEBELUMNYA
            await type_interaction.response.send_modal(details_modal)
            await details_modal.wait()
            # Ambil data dan interaction dari modal yang baru saja selesai
            if not hasattr(details_modal, 'interaction') or 'details' not in details_modal.interaction.data:
                 raise asyncio.TimeoutError("Pengisian detail dibatalkan atau modal error.")
            details = details_modal.interaction.data['details']
            details_interaction = details_modal.interaction # Simpan interaction dari modal ini

            # 4. Input Konteks RP (Modal AI Baru)
            ai_context_modal = AIContextModal()
            # Kirim modal AI menggunakan interaction DARI MODAL SEBELUMNYA
            await details_interaction.response.send_modal(ai_context_modal)
            await ai_context_modal.wait()
            if not hasattr(ai_context_modal, 'interaction') or 'rp_context' not in ai_context_modal.interaction.data:
                 raise asyncio.TimeoutError("Pengisian deskripsi RP dibatalkan atau modal error.")
            rp_context = ai_context_modal.interaction.data['rp_context']
            ai_interaction = ai_context_modal.interaction # Simpan interaction terakhir ini

            # 5. Panggil AI untuk Generate Steps
            # Edit pesan status menggunakan interaction terakhir
            await ai_interaction.response.edit_message(content="⏳ Meminta AI membuat langkah-langkah RP...", view=None)
            try:
                final_steps = await self._generate_rp_steps_with_ai(platform, macro_type, details, rp_context)
            except ValueError as ai_error:
                # Gunakan followup dari interaction terakhir jika edit_message gagal (sudah direspons)
                try: await ai_interaction.edit_original_response(content=f"❌ Gagal mendapatkan langkah RP dari AI:\n{ai_error}", view=None)
                except discord.InteractionResponded: await initial_interaction.followup.send(f"❌ Gagal mendapatkan langkah RP dari AI:\n{ai_error}", ephemeral=True)
                return
            except Exception as e:
                logger.error(f"Error tak terduga saat generate AI steps: {e}", exc_info=True)
                try: await ai_interaction.edit_original_response(content=f"❌ Terjadi error tak terduga saat menghubungi AI: {e}", view=None)
                except discord.InteractionResponded: await initial_interaction.followup.send(f"❌ Terjadi error tak terduga saat menghubungi AI: {e}", ephemeral=True)
                return

            # 6. Generate & Send Template
            template_content, template_filename = format_template(platform, macro_type, details, final_steps)
            template_file = discord.File(io.StringIO(template_content), filename=template_filename)
            steps_preview = "\n".join([f"- `{s.get('command', 'N/A')}` ({s.get('delay_sec', 'N/A')}s)" for s in final_steps])
            result_message = (
                f"✅ Template **{details.get('title', 'Tanpa Judul')}** untuk **{platform} ({macro_type.replace('_',' ').upper()})** berhasil dibuat oleh AI!\n\n"
                f"**Pratinjau Langkah RP:**\n{steps_preview}\n\n"
                f"Silakan unduh file `{template_filename}` di bawah dan salin isinya ke file KotkaHelper yang sesuai."
            )
            # Gunakan interaction terakhir untuk mengirim hasil
            # Coba edit dulu, kalau gagal (karena sudah direspons), pakai followup
            try:
                await ai_interaction.edit_original_response(
                    content=result_message,
                    attachments=[template_file],
                    view=None
                )
            except discord.InteractionResponded:
                # Jika edit gagal, gunakan followup dari interaksi AWAL
                await initial_interaction.followup.send(
                    content=result_message,
                    file=template_file,
                    ephemeral=True # Hasil akhir tetap ephemeral
                 )

            logger.info(f"User {interaction.user} berhasil membuat template AI: {template_filename}")

        except asyncio.TimeoutError as e:
            logger.warning(f"Workflow template dibatalkan atau timeout: {e}")
            try:
                # Coba edit pesan dari interaksi awal
                await initial_interaction.edit_original_response(content=f"❌ Pembuatan template dibatalkan karena waktu habis.", view=None, attachments=[])
            except (discord.NotFound, discord.InteractionResponded):
                # Jika gagal edit, coba kirim followup ephemeral
                try: await initial_interaction.followup.send(f"❌ Pembuatan template dibatalkan karena waktu habis.", ephemeral=True)
                except Exception as fe: logger.error(f"Gagal mengirim pesan timeout followup: {fe}")
            except Exception as inner_e: logger.error(f"Error saat edit pesan timeout: {inner_e}")
        except Exception as e:
            logger.error(f"Error selama workflow template: {e}", exc_info=True)
            try:
                # Coba edit pesan dari interaksi awal
                 await initial_interaction.edit_original_response(content=f"❌ Terjadi error: {e}", view=None, attachments=[])
            except (discord.NotFound, discord.InteractionResponded):
                 # Jika gagal edit, coba kirim followup ephemeral
                 try: await initial_interaction.followup.send(f"❌ Terjadi error: {e}", ephemeral=True)
                 except Exception as fe: logger.error(f"Gagal mengirim pesan error followup: {fe}")
            except Exception as inner_e: logger.error(f"Error saat edit pesan error: {inner_e}")


async def setup(bot):
    if not bot.config.OPENAI_API_KEYS:
        logger.warning("❌ Fitur AI Template Creator dinonaktifkan karena OPENAI_API_KEYS tidak ada.")
    await bot.add_cog(TemplateCreatorCog(bot))
    if not hasattr(bot, 'persistent_template_view_added_ai'):
        bot.persistent_template_view_added_ai = False
