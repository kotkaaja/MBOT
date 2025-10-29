import discord
from discord.ext import commands
from discord import ui
from openai import AsyncOpenAI
import google.generativeai as genai # Import Gemini
import httpx # Import httpx untuk Deepseek
import logging
from typing import Dict, Optional, List # Tambahkan Optional, List
import io
import re # Import re untuk membersihkan output JSON
import json # Import json
import itertools # Import itertools

# Import fungsi database untuk cooldown
from utils.database import check_ai_limit, increment_ai_usage, get_user_rank

# Mengambil logger
logger = logging.getLogger(__name__)

# ============================
# DICTIONARY UNTUK PROMPT DAN FORMAT (Tetap sama)
# ============================
SERVER_CONFIG = {
    "ssrp": {
        "name": "SSRP",
        "rules": """- Cerita harus memiliki minimal 4 paragraf dan 3 kalimat di setiap paragraf.
- Gunakan 5 spasi di awal setiap paragraf Di paragraft pertama juga wajib.
- Tulis tanggal lahir dalam format 'DD Bulan YYYY'.
- Gunakan huruf kapital hanya pada nama orang, nama tempat, dan awal kalimat.
- Gunakan Bahasa Indonesia yang baku dan sesuai KBBI.
- Jangan gunakan garis bawah (_) pada nama karakter dalam cerita. Contoh salah: Muriel_Bagge, contoh benar: Muriel Bagge.
- Pastikan penggunaan tanda baca (titik dan koma) tepat.""",
        "format": """**__FORMAT REQUEST CS | SSRP__**
- Nama karakter : {nama_char}
- Level karakter : {level}
- Jenis kelamin karakter : {jenis_kelamin}
- Tempat, tanggal lahir karakter : {kota_asal}, {tanggal_lahir}
- Screenshot /stats : (Lampirkan manual)
STORY :

{story}"""
    },
    "virtual_rp": {
        "name": "Virtual RP",
        "rules": """- Cerita harus memiliki minimal 250 suku kata.
- Beri jarak antar paragraf.
- Gunakan 5 spasi di awal setiap paragraf Di paragraft pertama juga wajib.
- Cerita minimal 4 paragraf, dan 1 paragraf minimal 4 baris.
- Gunakan Bahasa Indonesia yang baku dan sesuai KBBI.
- Perhatikan penggunaan huruf kapital dan tanda baca (beri spasi setelah titik/koma).
- Jangan menyalin story orang lain.
- Jangan gunakan garis bawah (_) pada nama karakter dalam cerita. Contoh salah: Muriel_Bagge, contoh benar: Muriel Bagge.
- Tulis tanggal lahir dalam format 'DD Bulan YYYY'.""",
        "format": """**__FORMAT CHARACTER STORY__**
> NAMA UCP : (Isi manual)
> NAMA IC : {nama_char}
> UMUR SESUAI KTP IC : (Isi manual)
> TEMPAT & TANGGAL LAHIR IC : {kota_asal}, {tanggal_lahir}
> CHARACTER SLOT : (Isi manual)
> SS KTP IC : (Lampirkan manual)

STORY :

{story}"""
    },
    "aarp": {
        "name": "AARP",
        "rules": """- Gunakan Bahasa Indonesia yang baku.
- Jangan gunakan garis bawah (_) pada nama karakter dalam cerita. Contoh salah: Muriel_Bagge, contoh benar: Muriel Bagge.
- Cerita minimal 1 paragraf atau lebih, singkat dan jelas.
- Beri jarak antar paragraf.""",
        "format": """**__[Format Character Story]__**
- Nama [ IC ] : {nama_char}
- JENIS KELAMIN : {jenis_kelamin}
- KOTA KELAHIRAN : {kota_asal}
- TANGGAL LAHIR : {tanggal_lahir}
- SS STATS PLAYER : (Lampirkan manual)

Story :

{story}"""
    },
    "gcrp": {
        "name": "GCRP",
        "rules": """- Minimal 4 paragraf dan setiap paragraf minimal memiliki 4 baris.
- Menggunakan bahasa Indonesia yang baku.
- Alur cerita yang jelas dan tidak berbelit-belit.
- Dilarang keras menjiplak/copy paste cerita orang lain.
- Penulisan nama karakter tidak menggunakan garis bawah (_). Contoh salah: Muriel_Bagge, contoh benar: Muriel Bagge.""",
        "format": """**[GCRP] FORMAT CHARACTER STORY**
* Nama UCP: (Isi Manual)
* Nama Character: {nama_char}
* Umur: (Isi Manual)
* Latar Belakang Cerita:

{story}"""
    },
    "tenrp": {
        "name": "TEN ROLEPLAY",
        "rules": """- CS di larang menggabungkan unsur OOC kedalam IC. Semua full dengan IC dari awal Charakter kalian masuk ke dalam kota.
- Ketika pembuatan di perhatikan tanda (,) (.) Dan berparagraf.
- Sertakan nama orang tua ayah dan ibu
- Cs menggunakan bahasa Indonesia baku.
- Character story minimal 4 paragraf.
- Dalam penulisan tempat tanggal lahir dilarang menggunakan spasi , / atau - (Contoh benar: Los Santos , 03 Juni 2004)
- Mudah dipahami dan dimengerti
- Nama lengkap tulis kembali dalam cerita gausah lagi pakai tanda ( _ )
- Tulis kembali tanggal, bulan, tahun dan umur dalam cerita
- Setiap pergantian paragraf baru harus enter / melangkah
- Membuat paragraf agar terlihat rapih dan kelihatan paragraf nya jangan lupa pakai spasi . Jangan  rata kek jalan aspal
- Menggunakan format yang telah disediakan
- Setiap akhir paragraf dikasi tanda titik
- Perhatikan penggunaan huruf setelah tanda koma dan titik dengan benar
- Yang huruf awalan memakai huruf kapital setelah tanda koma hanya boleh nama "Contoh :  Max Escobar""",
       "format": """**FORMAT CHARACTER STORY TEN ROLEPLAY**
* Nama Character: {nama_char}
* Usia Character: (Isi Manual)
* Tempat Tanggal Lahir: ( Isi Manual Sesuai CS)
* STORY CHARACTER :

{story}"""
    },
    "cprp": {
        "name": "CPRP",
        "rules": """1. Sesuaikan antara umur dan tanggal lahir karakter yang anda buat di In Game (/stats) dengan umur dan tanggal lahir didalam ceritanya. Batas minimal umur dalam pembuatan CS dari 17 Tahun.
2. Perhatikan penulisan huruf besar/kapital dan huruf kecil dalam pembuatan Story yang kalian buat, contohnya di awal paragraf/kalimat. Huruf besar/kapital juga bisa digunakan saat penulisan contoh :
a.Nama orang = Grace Jhonatan
b. Nama negara = Amerika Serikat atau negara Amerika Serikat
c. Nama kota = Kota Los Santos
d. Nama hari = Senin
e. Nama bulan = November
f. Nama profesi = seorang Mekanik
g. Hubungan kekerabatan = Ayah, Ibu, Kakak, Adik. Namun, apabila terdapat tambahan imbuhan (nya) pada hubungan kekerabatan, tidak perlu ditulis menggunakan huruf kapital seperti ayahnya, ibunya, kakaknya, adiknya
3. Perhatikan penulisan tanda baca pada saat pembuatan Story seperti tanda (,) dan (.). Seperti diakhir setiap kalimat harus ada tanda titik (.) Contohnya: " Worick adalah seorang anak dari keluarga yang kaya, ayahnya merupakan saudagar terkenal di Kota Los Santos."
4. Penulisan tanggal lahir tidak boleh menggunakan symbol ( / ) dan ( - ). Contohnya 17 Februari 1998
5. Character story wajib memiliki 4 paragraf (minimal) dan minimal 4 baris setiap paragraf, setiap akhir paragraf beri tanda ( .)
6. Penulisan Nama Karakter dalam Story harus sesuai didalam cerita, tidak usah menggunakan tanda ( _ ). Contohnya: Grace Jhonatan atau Worick Arcangelo.
7. Batas minimal level dalam pembuatan CS level 8 keatas
8. Dilarang keras melakukan plagiarisme
9. Setiap awal paragraf beri 3 spasi di paragraft pertama wajib jug""",
        "format": """**__FORMAT CHARACTER STORY CPRP__**

**Nama [IC]** : {nama_char}
**Umur [IC]** : (Isi manual, min 17)
**Tanggal lahir [IC sesuai Id card]** : {tanggal_lahir}
**Ss stats & Id card [Wajib]** : (Lampirkan manual)
**Ss Tab Level in Game [Wajib]**: (Lampirkan manual, min Lvl 8)
**Story** :

{story}

**Tag** : <@&1212085960418791464>"""
    },
    "relativerp": {
        "name": "Relative RP",
        "rules": """- Pembuatan character story tidak dibatasi level, kalian bisa membuat cs walaupun masih level 1.
- Untuk umur character diwajibkan minimal 17 tahun ke atas.
- Pemberian jarak antar paragraf satu dengan yang lainnya.
- Pemberian 5x spasi ke samping di awal kalimat saat memulai paragraf.
- Character story minimal 4 paragraf, dan 1 paragrafnya minimal 4 baris.
- Penggunaan titik dan koma yang tepat.
- Alur cerita harus sesuai / tidak boleh ngawur.
- Menggunakan bahasa Indonesia yang baku atau sesuai dengan KBBI.
- Penggunaan huruf kapital harus diperhatikan seperti nama orang, nama daerah, dan lain-lain.
- Perhatikan penggunaan tanda baca, setelah penggunaan koma dan titik diharuskan memeberikan 1 jarak / spasi.
- Dilarang menyalin story milik orang lain.
- Perhatikan penulisan nama, pada character story penulisan nama tidak perlu menggunakan garis bawah (_).
- Perhatian penulisan tanggal lahir, penulisan tanggal lahir yang tepat yaitu '27 November 2001'.
- Nama charactermu harus sesuai dengan roleplay name dan tidak mengandung dual culture.""",
        "format": """FORMAT CHARACTER STORY

Nama Character : {nama_char}
Usia Character     : (Isi manual, sesuai cs di atas)
Asal Character     : {kota_asal}
Gender                   : {jenis_kelamin}

Story Character :

{story}"""
    },
    "jgrp": {
        "name": "JGRP",
        "rules": """- Pastikan character kamu sudah minimal berlevel 3.
- Menggunakan formulir untuk character story.
- Menggunakan font yang mudah dibaca (Arial, Calibri, atau Tahoma),Font size: 14, dan jangan diberikan atribut berlebihan (Bold, Italic, atau Underline)
- Tidak boleh ada plagiarisme (silahkan cari di internet untuk plagiarism checker, contoh: http://smallseotools.com/plagiarism-checker/ )
- Ejaan, tanda baca, dan grammar harus sesuai dengan standard bahasa yang dipilih (Bahasa Indonesia atau English).
- Gunakan 5 spasi di awal setiap paragraf Di paragraft pertama juga wajib.
- Character story minimal harus memiliki 300 kata yang dipecah menjadi minimal 3 paragraph.""",
        "format": """**__FORMAT SEMENTARA REQUEST CS | JGRP__**
- Nama karakter : {nama_char}
- Level karakter : {level}
- Jenis kelamin karakter : {jenis_kelamin}
- Tempat, tanggal lahir karakter : {kota_asal}, {tanggal_lahir}
- Screenshot /stats : (Lampirkan manual)
- NOTE : INI FORMAT SEMENTARA SILAHKAN COPY STORYNYA DAN ISI ULANG DI FORUM JGRP
STORY :

{story}"""
    },
    "fmrp": {
        "name": "FMRP",
        "rules": """[•] Diawal story wajib memiliki tanggal lahir karakter anda.
[•] Menggunakan Bahasa Indonesia/Inggris yang baik dan benar sesuai dengan kaidah kepenulisan.
[•] Menggunakan sudut pandang pihak ketiga, namun tidak boleh memakai kata "ia" dan "dia". Wajib menggunakan nama karakter.
[•] Menggunakan tanda baca yang tepat serta menggunakan kalimat yang dapat dimengerti.
[•] Menggunakan penulisan huruf kapital yang benar.
[•] Character Story minimal memiliki 4 paragraf dan masing-masing memiliki 4 kalimat.
[•] Minimal mempunyai 230-300 kata
[•] Beri satu baris kosong untuk memisahkan paragraf satu dengan lainnya.
[•] Tidak memasukkan dialog dalam cerita karakter.
[•] Penulisan Nama di dalam cerita tidak boleh menggunakan tanda (_), agar terlihat rapih.
[•] Akhiri setiap paragraf dengan tanda baca (.), Karna banyaknya baris per paragraf dihitung dari kalimat yang diakhiri tanda baca (.).
[•] Alur cerita tidak boleh terlalu cepat, ceritakan karakter kalian dari kecil hingga menjadi seperti sekarang.""",
        "format": """**__FORMAT SEMENTARA REQUEST CS | FMRP__**
- Nama karakter : {nama_char}
- Level karakter : {level}
- Jenis kelamin karakter : {jenis_kelamin}
- Tempat, tanggal lahir karakter : {kota_asal}, {tanggal_lahir}
- Screenshot /stats : (Lampirkan manual)
- NOTE : INI FORMAT SEMENTARA SILAHKAN COPY STORYNYA DAN ISI ULANG DI DISCORD FMRP
STORY :

{story}"""
    }
}

# ============================
# UI COMPONENTS (MODAL & VIEWS) - Tetap sama
# ============================

class CSInputModal_Part2(ui.Modal):
    bakat_dominan = ui.TextInput(label="Bakat/Keahlian Dominan Karakter", placeholder="Contoh: Penembak jitu, negosiator ulung, pembalap liar", style=discord.TextStyle.short, required=True)
    culture = ui.TextInput(label="Kultur/Etnis (Opsional)", placeholder="Contoh: African-American, Hispanic, Italian-American", style=discord.TextStyle.short, required=False)
    detail_tambahan = ui.TextInput(label="Detail Tambahan (Opsional)", placeholder="Contoh: Punya hutang, dikhianati geng lama, dll.", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, server: str, story_type: str, bot_instance, part1_data: Dict):
        super().__init__(title=f"Detail Cerita ({story_type.replace('_',' ').title()}) (2/2)")
        self.server = server
        self.story_type = story_type
        self.bot = bot_instance
        self.part1_data = part1_data

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        processing_msg = await interaction.followup.send(f"⏳ Character Story untuk **{self.part1_data['nama_char']}** sedang diproses oleh AI...")

        try:
            all_data = self.part1_data.copy()
            all_data.update({
                "bakat": self.bakat_dominan.value,
                "culture": self.culture.value,
                "detail": self.detail_tambahan.value,
                "server": self.server,
                "story_type": self.story_type,
            })

            story_text = await self.bot.get_cog("CharacterStory").generate_story_from_ai(**all_data)
            # --- [BARU] Periksa jika AI gagal ---
            if story_text is None:
                raise Exception("Semua layanan AI gagal dihubungi atau error.")
            # --- [AKHIR PERBAIKAN] ---

            server_format = SERVER_CONFIG[self.server]["format"]
            final_cs = server_format.format(
                nama_char=all_data['nama_char'],
                tanggal_lahir=all_data['tanggal_lahir'],
                kota_asal=all_data['kota_asal'],
                story=story_text,
                level=all_data['level'],
                jenis_kelamin=all_data['jenis_kelamin']
            )

            embed = discord.Embed(
                title=f"✅ Character Story Selesai: {all_data['nama_char']}",
                description="Cerita Anda telah berhasil dibuat. Silakan unduh file `.txt` di bawah ini dan lengkapi bagian yang diperlukan.",
                color=discord.Color.green()
            )
            embed.add_field(name="Server", value=SERVER_CONFIG[self.server]['name'], inline=True)
            embed.add_field(name="Sisi Cerita", value=self.story_type.replace("_", " ").title(), inline=True)
            embed.set_footer(text=f"Diminta oleh: {interaction.user.display_name}")

            story_file = discord.File(
                io.StringIO(final_cs),
                filename=f"CS_{all_data['nama_char'].replace(' ', '_')}.txt"
            )

            await processing_msg.edit(
                content=f"Character Story untuk **{all_data['nama_char']}**, diminta oleh {interaction.user.mention}:",
                embed=embed,
                attachments=[story_file]
            )

            increment_ai_usage(interaction.user.id)

        except Exception as e:
            logger.error(f"Gagal membuat CS: {e}", exc_info=True)
            # --- [PERBAIKAN] Pesan error lebih informatif ---
            error_msg = f"❌ Terjadi kesalahan: {e}"
            if "Semua layanan AI gagal" in str(e):
                error_msg = "❌ Semua layanan AI sedang bermasalah atau gagal dihubungi. Coba lagi nanti."
            # --- [AKHIR PERBAIKAN] ---
            await processing_msg.edit(content=error_msg, embed=None, view=None, attachments=[])

class ContinueToPart2View(ui.View):
    def __init__(self, server: str, story_type: str, bot_instance, part1_data: Dict):
        super().__init__(timeout=300)
        self.server = server
        self.story_type = story_type
        self.bot = bot_instance
        self.part1_data = part1_data

    @ui.button(label="Lanjutkan ke Detail Cerita (2/2)", style=discord.ButtonStyle.primary, emoji="➡️")
    async def continue_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CSInputModal_Part2(
            server=self.server,
            story_type=self.story_type,
            bot_instance=self.bot,
            part1_data=self.part1_data
        ))
        await interaction.message.edit(view=None)
        self.stop()

class CSInputModal_Part1(ui.Modal):
    nama_char = ui.TextInput(label="Nama Lengkap Karakter (IC)", placeholder="Contoh: John Washington, Kenji Tanaka", style=discord.TextStyle.short, required=True)
    level = ui.TextInput(label="Level Karakter", placeholder="Contoh: 1", style=discord.TextStyle.short, required=True, max_length=3)
    jenis_kelamin = ui.TextInput(label="Jenis Kelamin", placeholder="Contoh: Laki-laki / Perempuan", style=discord.TextStyle.short, required=True)
    tanggal_lahir = ui.TextInput(label="Tanggal Lahir", placeholder="Contoh: 17 Agustus 1995", style=discord.TextStyle.short, required=True)
    kota_asal = ui.TextInput(label="Kota Asal", placeholder="Contoh: Chicago, Illinois", style=discord.TextStyle.short, required=True)

    def __init__(self, server: str, story_type: str, bot_instance):
        super().__init__(title=f"Detail Karakter ({story_type.replace('_',' ').title()}) (1/2)")
        self.server = server
        self.story_type = story_type
        self.bot = bot_instance

    async def on_submit(self, interaction: discord.Interaction):
        part1_data = {
            "nama_char": self.nama_char.value.replace('_', ' '),
            "level": self.level.value,
            "jenis_kelamin": self.jenis_kelamin.value,
            "tanggal_lahir": self.tanggal_lahir.value,
            "kota_asal": self.kota_asal.value,
        }
        view = ContinueToPart2View(
            server=self.server,
            story_type=self.story_type,
            bot_instance=self.bot,
            part1_data=part1_data
        )
        await interaction.response.send_message(
            "✅ Detail dasar berhasil disimpan. Tekan tombol di bawah untuk melanjutkan.",
            view=view,
            ephemeral=True
        )

class StoryTypeView(ui.View):
    def __init__(self, server: str, bot_instance):
        super().__init__(timeout=180)
        self.server = server
        self.bot = bot_instance

    @ui.button(label="😇 Sisi Baik (Goodside)", style=discord.ButtonStyle.success, emoji="😇")
    async def good_side(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CSInputModal_Part1(server=self.server, story_type="good_side", bot_instance=self.bot))

    @ui.button(label="😈 Sisi Jahat (Badside)", style=discord.ButtonStyle.danger, emoji="😈")
    async def bad_side(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CSInputModal_Part1(server=self.server, story_type="bad_side", bot_instance=self.bot))

class ServerSelectionView(ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=180)
        self.bot = bot_instance

    @ui.select(
        placeholder="Pilih server tujuan...",
       options=[
            discord.SelectOption(label="SSRP", value="ssrp", description="Buat CS untuk server State Side RP."),
            discord.SelectOption(label="Virtual RP", value="virtual_rp", description="Buat CS untuk server Virtual RP."),
            discord.SelectOption(label="AARP", value="aarp", description="Buat CS untuk server Air Asia RP."),
            discord.SelectOption(label="GCRP", value="gcrp", description="Buat CS untuk server Grand Country RP."),
            discord.SelectOption(label="TEN ROLEPLAY", value="tenrp", description="Buat CS untuk server 10RP."),
            discord.SelectOption(label="CPRP", value="cprp", description="Buat CS untuk server Cyristal Pride RP."),
            discord.SelectOption(label="Relative RP", value="relativerp", description="Buat CS untuk server Relative RP."),
            discord.SelectOption(label="JGRP", value="jgrp", description="Buat CS untuk server JGRP."),
            discord.SelectOption(label="FMRP", value="fmrp", description="Buat CS untuk server FAMERLONE RP.")
        ],
        custom_id="server_select"
    )
    async def select_server(self, interaction: discord.Interaction, select: ui.Select):
        server_choice = select.values[0]
        await interaction.response.send_message("Pilih alur cerita untuk karaktermu:", view=StoryTypeView(server=server_choice, bot_instance=self.bot), ephemeral=True)

class CSPanelView(ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance

    @ui.button(label="Buat Character Story", style=discord.ButtonStyle.primary, emoji="📝", custom_id="create_cs_button")
    async def create_cs(self, interaction: discord.Interaction, button: ui.Button):
        can_use, remaining, limit = check_ai_limit(interaction.user.id)
        if not can_use:
            rank = get_user_rank(interaction.user.id)
            limit_display = "Unlimited" if limit == -1 else limit
            usage_today = (limit - remaining) if limit > 0 else 0
            await interaction.response.send_message(
                f"❌ Batas harian AI Anda (Rank: **{rank.title()}**) untuk membuat CS telah tercapai ({usage_today}/{limit_display}). Coba lagi besok.",
                ephemeral=True
            )
            return

        await interaction.response.send_message("Pilih server di mana karaktermu akan bermain:", view=ServerSelectionView(self.bot), ephemeral=True)

# ============================
# KELAS COG UTAMA
# ============================
class CharacterStoryCog(commands.Cog, name="CharacterStory"):
    def __init__(self, bot):
        self.bot = bot
        # --- [BARU] Tambahkan key cyclers ---
        self.openai_key_cycler = itertools.cycle(self.bot.config.OPENAI_API_KEYS) if self.bot.config.OPENAI_API_KEYS else None
        self.gemini_key_cycler = itertools.cycle(self.bot.config.GEMINI_API_KEYS) if self.bot.config.GEMINI_API_KEYS else None
        self.deepseek_key_cycler = itertools.cycle(self.bot.config.DEEPSEEK_API_KEYS) if self.bot.config.DEEPSEEK_API_KEYS else None
        # --- [AKHIR PERBAIKAN] ---

        if not hasattr(bot, 'persistent_views_added') or not bot.persistent_views_added:
            bot.add_view(CSPanelView(bot))
            bot.persistent_views_added = True

    async def generate_story_from_ai(self, server: str, nama_char: str, tanggal_lahir: str, kota_asal: str, story_type: str, bakat: str, culture: str, detail: str, jenis_kelamin: str, level: str) -> Optional[str]:
        """Menghasilkan story dari AI dengan fallback."""

        server_rules = SERVER_CONFIG[server]["rules"]

        story_direction = ""
        if story_type == "good_side":
            story_direction = "Cerita harus bernuansa 'goodside'. Fokus pada latar belakang karakter yang baik, normal, atau memiliki tujuan hidup yang positif. Alasan pindah ke Los Santos harus logis untuk mencari kehidupan lebih baik atau bergabung dengan faksi legal seperti kepolisian, medis, atau bisnis."
        else: # bad_side
            story_direction = "Cerita harus bernuansa 'badside'. Fokus pada latar belakang yang keras, tumbuh di lingkungan gangster, atau mengalami peristiwa tragis yang mendorongnya ke dunia kejahatan. Alasan pindah ke Los Santos adalah untuk melarikan diri dari masalah atau mencari peluang di dunia kriminal."

        prompt = f"""
        Peran: Anda adalah penulis cerita kreatif yang sangat berpengalaman dalam dunia roleplay GTA San Andreas Multiplayer (SAMP) di Indonesia, dengan pemahaman mendalam tentang kultur Amerika.

        Tugas: Buat sebuah Character Story (CS) yang unik, mendalam, dan logis untuk server roleplay berbasis di Amerika, berdasarkan informasi detail berikut:
        - Nama Karakter: {nama_char}
        - Jenis Kelamin: {jenis_kelamin}
        - Tanggal Lahir: {tanggal_lahir}
        - Kota Asal: {kota_asal} (Asumsikan ini adalah kota di Amerika)
        - Latar Belakang Kultur/Etnis (jika ada): {culture if culture else 'Amerika umum'}
        - Sisi Cerita: {story_type.replace('_', ' ')}
        - Bakat/Keahlian Utama: {bakat}
        - Detail Tambahan: {detail if detail else 'Tidak ada.'}

        Struktur Cerita (WAJIB DIIKUTI):
        1.  **Latar Belakang:** Ceritakan kehidupan awal karakter di {kota_asal}.
        2.  **Titik Balik:** Jelaskan satu peristiwa penting yang menjadi alasan utama karakter pindah ke Los Santos. Peristiwa ini harus mencerminkan bakat utamanya ({bakat}).
        3.  **Adaptasi di Los Santos:** Gambarkan perjuangan atau adaptasi awal setelah tiba di kota baru.
        4.  **Tujuan Masa Depan:** Jelaskan kondisi karakter saat ini dan apa tujuannya di Los Santos.

        Instruksi Spesifik (SANGAT PENTING):
        -   **Gaya Penulisan:** Gunakan sudut pandang orang ketiga (third-person point of view). Sebut karakter dengan namanya ({nama_char}), hindari kata 'aku' atau 'saya'.
        -   **Penulisan Nama:** Jangan pernah gunakan garis bawah (_) pada nama karakter. Tulis nama seperti nama orang pada umumnya (contoh: Muriel Bagge).
        -   **Kultur:** Cerita harus terasa seperti berlatar di Amerika. Jika kultur/etnis spesifik diberikan, integrasikan secara halus (misalnya, melalui nama, tradisi, lingkungan). Jika tidak, gunakan nuansa kultur Amerika pada umumnya.
        -   **Arah Cerita:** {story_direction}
        -   **Integrasi Bakat:** Jadikan bakat '{bakat}' sebagai pilar utama dalam alur cerita.

        ATURAN TEKNIS WAJIB UNTUK SERVER '{SERVER_CONFIG[server]["name"]}':
        {server_rules}

        Output akhir harus berupa teks cerita saja dalam Bahasa Indonesia, tanpa judul atau format tambahan. Pastikan cerita yang dihasilkan menarik, konsisten, dan memenuhi semua aturan.
        """

        # --- [BARU] Fallback Logic ---
        story_text = None
        ai_used = "Tidak ada"

        # Coba Gemini
        if self.gemini_key_cycler:
            try:
                key = next(self.gemini_key_cycler)
                genai.configure(api_key=key)
                model = genai.GenerativeModel('gemini-1.5-flash')
                logger.info(f"Char Story: Mencoba Gemini...")
                response = await model.generate_content_async(
                    prompt,
                    generation_config=genai.types.GenerationConfig(temperature=0.75), # Minta output teks biasa
                    request_options={"timeout": 60}
                )
                if response.prompt_feedback.block_reason:
                    raise Exception(f"Gemini diblokir: {response.prompt_feedback.block_reason.name}")
                if response.candidates and response.candidates[0].finish_reason.name != "STOP":
                     raise Exception(f"Gemini finish reason: {response.candidates[0].finish_reason.name}")
                story_text = response.text
                if story_text:
                     ai_used = "Gemini"
                     logger.info("AI (Gemini) berhasil generate Char Story.")
            except Exception as e:
                logger.warning(f"Char Story: Gemini gagal: {e}")
                await asyncio.sleep(1)

        # Coba Deepseek jika Gemini gagal
        if not story_text and self.deepseek_key_cycler:
            try:
                key = next(self.deepseek_key_cycler)
                async with httpx.AsyncClient(timeout=40.0) as client:
                    logger.info(f"Char Story: Mencoba Deepseek...")
                    response = await client.post(
                        "https://api.deepseek.com/chat/completions",
                        json={
                            "model": "deepseek-chat",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.75,
                            "max_tokens": 1200,
                        },
                        headers={"Authorization": f"Bearer {key}"}
                    )
                    response.raise_for_status()
                    story_text = response.json()["choices"][0]["message"]["content"]
                    if story_text:
                        ai_used = "Deepseek"
                        logger.info("AI (Deepseek) berhasil generate Char Story.")
            except Exception as e:
                logger.warning(f"Char Story: Deepseek gagal: {e}")
                await asyncio.sleep(1)

        # Coba OpenAI jika semua gagal
        if not story_text and self.openai_key_cycler:
            try:
                key = next(self.openai_key_cycler)
                client = AsyncOpenAI(api_key=key, timeout=30.0)
                logger.info(f"Char Story: Mencoba OpenAI...")
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.75,
                    max_tokens=1200,
                )
                story_text = response.choices[0].message.content
                if story_text:
                    ai_used = "OpenAI"
                    logger.info("AI (OpenAI) berhasil generate Char Story.")
            except Exception as e:
                logger.error(f"Char Story: OpenAI GAGAL (fallback terakhir): {e}")
                # Jangan return None di sini, biarkan fungsi selesai dan return story_text (yang None)
        # --- [AKHIR PERBAIKAN] ---

        if story_text:
            cleaned_story = story_text.strip().replace("```", "")
            return cleaned_story
        else:
            logger.error(f"Semua AI gagal generate Char Story untuk {nama_char}.")
            return None # Return None jika semua AI gagal

    @commands.command(name="setupcs")
    async def setup_cs_panel(self, ctx):
        """Mengirim panel untuk membuat Character Story."""
        embed = discord.Embed(
            title="📝 Panel Pembuatan Character Story",
            description="Tekan tombol di bawah untuk memulai proses pembuatan **Character Story (CS)** yang lebih detail dan sesuai keinginanmu.",
            color=0x5865F2
        )
        embed.add_field(
            name="Alur Baru yang Lebih Detail",
            value="1. Pilih Server\n2. Pilih Sisi Cerita (Baik/Jahat)\n3. Isi Detail Lengkap Karakter (Nama, Kultur, Bakat, dll.)",
            inline=False
        )
        embed.set_footer(text="Created By Kotkaaja.")

        await ctx.send(embed=embed, view=CSPanelView(self.bot))

async def setup(bot):
    if not hasattr(bot, 'persistent_views_added'):
        bot.persistent_views_added = False
    await bot.add_cog(CharacterStoryCog(bot))

