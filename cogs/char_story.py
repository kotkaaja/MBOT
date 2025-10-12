import discord
from discord.ext import commands
from discord import ui
from openai import AsyncOpenAI
import logging
from typing import Dict

# Mengambil logger
logger = logging.getLogger(__name__)

# ============================
# DICTIONARY UNTUK PROMPT DAN FORMAT
# ============================

# Menyimpan aturan spesifik dan format untuk setiap server
SERVER_CONFIG = {
    "ssrp": {
        "name": "SSRP",
        "rules": """- Cerita harus memiliki minimal 4 paragraf dan 3 kalimat di setiap paragraf.
- Gunakan 5 spasi di awal setiap paragraf.
- Tulis tanggal lahir dalam format 'DD Bulan YYYY'.
- Gunakan huruf kapital hanya pada nama orang, nama tempat, dan awal kalimat.
- Gunakan Bahasa Indonesia yang baku dan sesuai KBBI.
- Jangan gunakan garis bawah (_) pada nama karakter dalam cerita.
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
- Umur karakter minimal 17 tahun.
- Beri jarak antar paragraf.
- Cerita minimal 4 paragraf, dan 1 paragraf minimal 4 baris.
- Gunakan Bahasa Indonesia yang baku dan sesuai KBBI.
- Perhatikan penggunaan huruf kapital dan tanda baca (beri spasi setelah titik/koma).
- Jangan menyalin story orang lain.
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
- Cerita minimal 1 paragraf atau lebih, singkat dan jelas.""",
        "format": """**__[Format Character Story]__**
- Nama [ IC ] : {nama_char}
- JENIS KELAMIN : {jenis_kelamin}
- KOTA KELAHIRAN : {kota_asal}
- TANGGAL LAHIR : {tanggal_lahir}
- SS STATS PLAYER : (Lampirkan manual)

Story :

{story}"""
    },
    # ... (konfigurasi server lain)
    "gcrp": {
        "name": "GCRP",
        "rules": """- Minimal 4 paragraf dan setiap paragraf minimal memiliki 4 baris.
- Menggunakan bahasa Indonesia yang baku.
- Alur cerita yang jelas dan tidak berbelit-belit.
- Dilarang keras menjiplak/copy paste cerita orang lain.
- Penulisan nama karakter tidak menggunakan garis bawah (_).""",
        "format": """**[GCRP] FORMAT CHARACTER STORY**
* Nama UCP: (Isi Manual)
* Nama Character: {nama_char}
* Umur: (Isi Manual)
* Latar Belakang Cerita:

{story}"""
    }
}


# ============================
# UI COMPONENTS (MODAL & VIEWS)
# ============================

# Modal Bagian 2: Mengumpulkan detail cerita yang lebih dalam
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
        # Defer secara publik agar pengguna tahu bot sedang bekerja
        await interaction.response.defer()

        try:
            # Gabungkan data dari formulir bagian 1 dan 2
            all_data = self.part1_data.copy()
            all_data.update({
                "bakat": self.bakat_dominan.value,
                "culture": self.culture.value,
                "detail": self.detail_tambahan.value,
                "server": self.server,
                "story_type": self.story_type,
            })

            # Panggil AI untuk menghasilkan cerita
            story_text = await self.bot.get_cog("CharacterStory").generate_story_from_ai(**all_data)

            # Format output sesuai server
            server_format = SERVER_CONFIG[self.server]["format"]
            final_cs = server_format.format(
                nama_char=all_data['nama_char'],
                tanggal_lahir=all_data['tanggal_lahir'],
                kota_asal=all_data['kota_asal'],
                story=story_text,
                level=all_data['level'],
                jenis_kelamin=all_data['jenis_kelamin']
            )

            # Buat embed untuk hasil
            embed = discord.Embed(
                title=f"📝 Character Story untuk {all_data['nama_char']}",
                description="Berikut draf cerita yang dihasilkan AI. Salin dan lengkapi bagian yang diperlukan.",
                color=discord.Color.blue()
            )
            embed.add_field(name="Server", value=SERVER_CONFIG[self.server]['name'], inline=True)
            embed.add_field(name="Sisi Cerita", value=self.story_type.replace("_", " ").title(), inline=True)
            embed.set_footer(text=f"Diminta oleh: {interaction.user.display_name}")

            # Kirim hasil secara publik
            content_message = f"Character Story untuk **{all_data['nama_char']}**, diminta oleh {interaction.user.mention}:"
            
            if len(final_cs) > 1900:
                await interaction.followup.send(content=content_message, embed=embed)
                for i in range(0, len(final_cs), 1900):
                    chunk = final_cs[i:i+1900]
                    await interaction.followup.send(f"```\n{chunk}\n```")
            else:
                await interaction.followup.send(content=content_message, embed=embed)
                await interaction.followup.send(f"```\n{final_cs}\n```")

        except Exception as e:
            logger.error(f"Gagal membuat CS dengan OpenAI: {e}", exc_info=True)
            await interaction.followup.send("❌ Terjadi kesalahan saat menghubungi AI OpenAI. Pastikan API Key valid dan memiliki kuota.")

# View untuk tombol Lanjutkan ke Bagian 2
class ContinueToPart2View(ui.View):
    def __init__(self, server: str, story_type: str, bot_instance, part1_data: Dict):
        super().__init__(timeout=300) # 5 menit timeout
        self.server = server
        self.story_type = story_type
        self.bot = bot_instance
        self.part1_data = part1_data

    @ui.button(label="Lanjutkan ke Detail Cerita (2/2)", style=discord.ButtonStyle.primary, emoji="➡️")
    async def continue_button(self, interaction: discord.Interaction, button: ui.Button):
        # Tombol ini membuat interaksi baru, jadi kita bisa mengirim modal
        await interaction.response.send_modal(CSInputModal_Part2(
            server=self.server,
            story_type=self.story_type,
            bot_instance=self.bot,
            part1_data=self.part1_data
        ))
        # Hapus view setelah diklik agar tidak bisa digunakan lagi
        await interaction.message.edit(view=None)
        self.stop()

# Modal Bagian 1: Mengumpulkan data dasar karakter
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
            "nama_char": self.nama_char.value,
            "level": self.level.value,
            "jenis_kelamin": self.jenis_kelamin.value,
            "tanggal_lahir": self.tanggal_lahir.value,
            "kota_asal": self.kota_asal.value,
        }
        # Kirim pesan dengan tombol untuk membuka modal kedua
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


# View untuk memilih tipe cerita (Goodside/Badside)
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

# View untuk dropdown pemilihan server
class ServerSelectionView(ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=180) 
        self.bot = bot_instance

    @ui.select(
        placeholder="Pilih server tujuan...",
        options=[
            discord.SelectOption(label="SSRP", value="ssrp", description="Buat CS untuk server SSRP."),
            discord.SelectOption(label="Virtual RP", value="virtual_rp", description="Buat CS untuk server Virtual RP."),
            discord.SelectOption(label="AARP", value="aarp", description="Buat CS untuk server AARP."),
            discord.SelectOption(label="GCRP", value="gcrp", description="Buat CS untuk server GCRP."),
        ],
        custom_id="server_select"
    )
    async def select_server(self, interaction: discord.Interaction, select: ui.Select):
        server_choice = select.values[0]
        await interaction.response.send_message("Pilih alur cerita untuk karaktermu:", view=StoryTypeView(server=server_choice, bot_instance=self.bot), ephemeral=True)

# View utama yang berisi tombol untuk memulai proses
class CSPanelView(ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None) 
        self.bot = bot_instance

    @ui.button(label="Buat Character Story", style=discord.ButtonStyle.primary, emoji="📝", custom_id="create_cs_button")
    async def create_cs(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Pilih server di mana karaktermu akan bermain:", view=ServerSelectionView(self.bot), ephemeral=True)

# ============================
# KELAS COG UTAMA
# ============================
class CharacterStoryCog(commands.Cog, name="CharacterStory"):
    def __init__(self, bot):
        self.bot = bot
        if not hasattr(bot, 'persistent_views_added') or not bot.persistent_views_added:
            bot.add_view(CSPanelView(bot))
            bot.persistent_views_added = True

    async def generate_story_from_ai(self, server: str, nama_char: str, tanggal_lahir: str, kota_asal: str, story_type: str, bakat: str, culture: str, detail: str, jenis_kelamin: str, level: str) -> str:
        """Menghasilkan story dari OpenAI berdasarkan input detail."""
        
        if not self.bot.config.OPENAI_API_KEYS:
            raise Exception("API Key OpenAI tidak dikonfigurasi.")
            
        api_key = self.bot.config.OPENAI_API_KEYS[0]
        client = AsyncOpenAI(api_key=api_key)

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
        -   **Kultur:** Cerita harus terasa seperti berlatar di Amerika. Jika kultur/etnis spesifik diberikan, integrasikan secara halus (misalnya, melalui nama, tradisi, lingkungan). Jika tidak, gunakan nuansa kultur Amerika pada umumnya.
        -   **Arah Cerita:** {story_direction}
        -   **Integrasi Bakat:** Jadikan bakat '{bakat}' sebagai pilar utama dalam alur cerita.

        ATURAN TEKNIS WAJIB UNTUK SERVER '{SERVER_CONFIG[server]["name"]}':
        {server_rules}

        Output akhir harus berupa teks cerita saja dalam Bahasa Indonesia, tanpa judul atau format tambahan. Pastikan cerita yang dihasilkan menarik, konsisten, dan memenuhi semua aturan.
        """
        
        logger.info(f"Mengirim prompt ke OpenAI untuk karakter {nama_char}...")
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.75,
            max_tokens=1200,
        )
        
        story_text = response.choices[0].message.content
        cleaned_story = story_text.strip().replace("```", "")
        
        return cleaned_story

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
    # Pastikan atribut 'persistent_views_added' ada di bot
    if not hasattr(bot, 'persistent_views_added'):
        bot.persistent_views_added = False
    await bot.add_cog(CharacterStoryCog(bot))

