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
- Level karakter : (Isi manual)
- Jenis kelamin karakter : (Isi manual)
- Tempat, tanggal lahir karakter : {kota_asal}, {tanggal_lahir}
- Screenshot /stats : (Lampirkan manual)
STORY :

{story}"""
    },
    "virtual_rp": {
        "name": "Virtual RP",
        "rules": """- Cerita harus memiliki minimal 250 suku kata.
- Cerita harus menggunakan nama karakter, bukan sudut pandang orang ketiga (ia, saya, aku).
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
- JENIS KELAMIN : (Isi manual)
- KOTA KELAHIRAN : {kota_asal}
- TANGGAL LAHIR : {tanggal_lahir}
- SS STATS PLAYER : (Lampirkan manual)

Story :

{story}"""
    }
}

# ============================
# UI COMPONENTS (MODAL & VIEWS)
# ============================

# Modal untuk mengumpulkan data karakter dari pengguna
class CSInputModal(ui.Modal, title="Formulir Detail Karakter"):
    nama_char = ui.TextInput(label="Nama Lengkap Karakter (IC)", placeholder="Contoh: John Doe", style=discord.TextStyle.short, required=True)
    tanggal_lahir = ui.TextInput(label="Tanggal Lahir", placeholder="Contoh: 17 Agustus 1995", style=discord.TextStyle.short, required=True)
    kota_asal = ui.TextInput(label="Kota Asal", placeholder="Contoh: Jakarta", style=discord.TextStyle.short, required=True)
    bakat_dominan = ui.TextInput(label="Bakat/Keahlian Dominan Karakter", placeholder="Contoh: Menembak, memimpin, negosiasi, balapan", style=discord.TextStyle.short, required=True)
    detail_tambahan = ui.TextInput(label="Detail Tambahan (Opsional)", placeholder="Contoh: Memiliki trauma masa kecil, punya hutang, dll.", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, server: str, story_type: str, bot_instance):
        super().__init__()
        self.server = server
        self.story_type = story_type
        self.bot = bot_instance

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("⏳ AI sedang meracik ceritamu, proses ini butuh waktu sejenak...", ephemeral=True)
        
        try:
            # Panggil fungsi untuk generate story dengan parameter baru
            story_text = await self.bot.get_cog("CharacterStory").generate_story_from_ai(
                server=self.server,
                nama_char=self.nama_char.value,
                tanggal_lahir=self.tanggal_lahir.value,
                kota_asal=self.kota_asal.value,
                story_type=self.story_type,
                bakat=self.bakat_dominan.value,
                detail=self.detail_tambahan.value
            )

            # Format output sesuai server yang dipilih
            server_format = SERVER_CONFIG[self.server]["format"]
            final_cs = server_format.format(
                nama_char=self.nama_char.value,
                tanggal_lahir=self.tanggal_lahir.value,
                kota_asal=self.kota_asal.value,
                story=story_text
            )

            # Buat embed untuk hasil
            embed = discord.Embed(
                title=f"✅ Cerita untuk {self.nama_char.value} Berhasil Dibuat!",
                description="Berikut draf Character Story kamu. **Salin teks di bawah ini** dan lengkapi bagian `(Isi manual)` sebelum dikirim.",
                color=discord.Color.green()
            )
            embed.add_field(name="Server", value=SERVER_CONFIG[self.server]['name'], inline=True)
            embed.add_field(name="Sisi Cerita", value=self.story_type.replace("_", " ").title(), inline=True)
            
            # Kirim hasil dalam beberapa bagian jika terlalu panjang
            if len(final_cs) > 1900: 
                await interaction.followup.send(embed=embed, ephemeral=True)
                # Split the story into chunks and send
                for i in range(0, len(final_cs), 1900):
                    chunk = final_cs[i:i+1900]
                    await interaction.followup.send(f"```{chunk}```", ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, content=f"```\n{final_cs}\n```", ephemeral=True)

        except Exception as e:
            logger.error(f"Gagal membuat CS dengan OpenAI: {e}", exc_info=True)
            await interaction.followup.send("❌ Terjadi kesalahan saat menghubungi AI OpenAI. Pastikan API Key valid dan memiliki kuota. Coba lagi nanti.", ephemeral=True)

# View untuk memilih tipe cerita (Goodside/Badside)
class StoryTypeView(ui.View):
    def __init__(self, server: str, bot_instance):
        super().__init__(timeout=180)
        self.server = server
        self.bot = bot_instance

    @ui.button(label="😇 Sisi Baik (Goodside)", style=discord.ButtonStyle.success, emoji="😇")
    async def good_side(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CSInputModal(server=self.server, story_type="good_side", bot_instance=self.bot))

    @ui.button(label="😈 Sisi Jahat (Badside)", style=discord.ButtonStyle.danger, emoji="😈")
    async def bad_side(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CSInputModal(server=self.server, story_type="bad_side", bot_instance=self.bot))

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
        ],
        custom_id="server_select"
    )
    async def select_server(self, interaction: discord.Interaction, select: ui.Select):
        server_choice = select.values[0]
        # Kirim view untuk memilih tipe cerita
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
        if not bot.persistent_views_added:
            bot.add_view(CSPanelView(bot))
            bot.persistent_views_added = True

    async def generate_story_from_ai(self, server: str, nama_char: str, tanggal_lahir: str, kota_asal: str, story_type: str, bakat: str, detail: str) -> str:
        """Menghasilkan story dari OpenAI berdasarkan input detail."""
        
        if not self.bot.config.OPENAI_API_KEYS:
            raise Exception("API Key OpenAI tidak dikonfigurasi.")
            
        api_key = self.bot.config.OPENAI_API_KEYS[0] # Ambil key pertama
        client = AsyncOpenAI(api_key=api_key)

        server_rules = SERVER_CONFIG[server]["rules"]
        
        story_direction = ""
        if story_type == "good_side":
            story_direction = "Cerita harus bernuansa 'goodside'. Fokus pada latar belakang karakter yang baik, normal, atau memiliki tujuan hidup yang positif. Alasan pindah ke Los Santos harus logis untuk mencari kehidupan lebih baik atau bergabung dengan faksi legal seperti kepolisian, medis, atau bisnis."
        else: # bad_side
            story_direction = "Cerita harus bernuansa 'badside'. Fokus pada latar belakang yang keras, tumbuh di lingkungan gangster, atau mengalami peristiwa tragis yang mendorongnya ke dunia kejahatan. Alasan pindah ke Los Santos adalah untuk melarikan diri dari masalah atau mencari peluang di dunia kriminal."

        prompt = f"""
        Peran: Anda adalah penulis cerita kreatif yang sangat berpengalaman dalam dunia roleplay GTA San Andreas Multiplayer (SAMP) di Indonesia.

        Tugas: Buat sebuah Character Story (CS) yang unik, mendalam, dan logis berdasarkan informasi detail berikut:
        - Nama Karakter: {nama_char}
        - Tanggal Lahir: {tanggal_lahir}
        - Kota Asal: {kota_asal}
        - Sisi Cerita: {story_type.replace('_', ' ')}
        - Bakat/Keahlian Utama: {bakat}
        - Detail Tambahan: {detail if detail else 'Tidak ada.'}

        Struktur Cerita (WAJIB DIIKUTI):
        1.  **Latar Belakang:** Ceritakan kehidupan awal karakter di {kota_asal}.
        2.  **Titik Balik:** Jelaskan satu peristiwa penting yang menjadi alasan utama karakter pindah ke Los Santos. Peristiwa ini harus mencerminkan bakat utamanya ({bakat}).
        3.  **Adaptasi di Los Santos:** Gambarkan perjuangan atau adaptasi awal setelah tiba di kota baru.
        4.  **Tujuan Masa Depan:** Jelaskan kondisi karakter saat ini dan apa tujuannya di Los Santos.

        Instruksi Spesifik:
        -   **{story_direction}**
        -   Integrasikan bakat '{bakat}' secara menonjol dalam alur cerita, terutama di bagian 'Titik Balik'.
        -   Gunakan 'Detail Tambahan' untuk memberi kedalaman pada karakter.

        ATURAN TEKNIS WAJIB UNTUK SERVER '{SERVER_CONFIG[server]["name"]}':
        {server_rules}

        Output akhir harus berupa teks cerita saja, tanpa judul atau format tambahan. Pastikan cerita yang dihasilkan menarik, konsisten, dan memenuhi semua aturan.
        """
        
        logger.info(f"Mengirim prompt ke OpenAI untuk karakter {nama_char}...")
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1000,
        )
        
        story_text = response.choices[0].message.content
        cleaned_story = story_text.strip().replace("```", "")
        
        return cleaned_story

    @commands.command(name="setupcs")
    @commands.has_permissions(administrator=True)
    async def setup_cs_panel(self, ctx):
        """Mengirim panel untuk membuat Character Story (Admin only)."""
        embed = discord.Embed(
            title="📝 Panel Pembuatan Character Story (AI)",
            description="Tekan tombol di bawah untuk memulai proses pembuatan **Character Story (CS)** yang lebih detail dan sesuai keinginanmu.",
            color=0x5865F2
        )
        embed.add_field(
            name="Alur Baru",
            value="1. Pilih Server\n2. Pilih Sisi Cerita (Baik/Jahat)\n3. Isi Detail Karakter (Nama, Bakat, dll.)",
            inline=False
        )
        embed.set_footer(text="Bot ini menggunakan OpenAI untuk menghasilkan cerita.")

        await ctx.send(embed=embed, view=CSPanelView(self.bot))

async def setup(bot):
    await bot.add_cog(CharacterStoryCog(bot))
