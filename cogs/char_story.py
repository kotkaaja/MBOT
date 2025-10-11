import discord
from discord.ext import commands
from discord import ui
import google.generativeai as genai
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
# UI COMPONENTS (MODAL & VIEW)
# ============================

# Modal untuk mengumpulkan data karakter dari pengguna
class CSInputModal(ui.Modal, title="Formulir Data Character Story"):
    nama_char = ui.TextInput(label="Nama Lengkap Karakter (IC)", placeholder="Contoh: John Doe", style=discord.TextStyle.short, required=True)
    tanggal_lahir = ui.TextInput(label="Tanggal Lahir", placeholder="Contoh: 17 Agustus 1995", style=discord.TextStyle.short, required=True)
    kota_asal = ui.TextInput(label="Kota Asal", placeholder="Contoh: Jakarta", style=discord.TextStyle.short, required=True)

    def __init__(self, server: str, bot_instance):
        super().__init__()
        self.server = server
        self.bot = bot_instance

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("⏳ Sedang memproses ceritamu dengan AI, mohon tunggu sebentar...", ephemeral=True)
        
        try:
            # Panggil fungsi untuk generate story
            story_text = await self.bot.get_cog("CharacterStoryCog").generate_story_from_ai(
                self.server,
                self.nama_char.value,
                self.tanggal_lahir.value,
                self.kota_asal.value
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
                title=f"✅ Character Story untuk {self.nama_char.value} Berhasil Dibuat!",
                description="Berikut adalah draf Character Story kamu. Salin teks di bawah ini dan lengkapi bagian `(Isi manual)`.",
                color=discord.Color.green()
            )
            embed.add_field(name="Server", value=SERVER_CONFIG[self.server]['name'], inline=False)
            
            # Kirim hasil dalam beberapa bagian jika terlalu panjang
            if len(final_cs) > 4000: # Batas Discord
                await interaction.followup.send(embed=embed, content=final_cs[:1990] + "...", ephemeral=True)
                await interaction.followup.send(content="..." + final_cs[1990:], ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, content=f"```\n{final_cs}\n```", ephemeral=True)

        except Exception as e:
            logger.error(f"Gagal membuat CS: {e}", exc_info=True)
            await interaction.followup.send("❌ Terjadi kesalahan saat menghubungi AI. Coba lagi nanti.", ephemeral=True)

# View yang berisi tombol untuk memulai proses pembuatan CS
class CSPanelView(ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None) # Timeout None agar view permanen
        self.bot = bot_instance

    @ui.button(label="Buat Character Story", style=discord.ButtonStyle.primary, emoji="📝", custom_id="create_cs_button")
    async def create_cs(self, interaction: discord.Interaction, button: ui.Button):
        # Tampilkan dropdown untuk memilih server
        await interaction.response.send_message(view=ServerSelectionView(self.bot), ephemeral=True)

# View untuk dropdown pemilihan server
class ServerSelectionView(ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=180) # Timeout 3 menit
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
        # Tampilkan modal input setelah server dipilih
        await interaction.response.send_modal(CSInputModal(server=server_choice, bot_instance=self.bot))

# ============================
# KELAS COG UTAMA
# ============================
class CharacterStoryCog(commands.Cog, name="CharacterStory"):
    def __init__(self, bot):
        self.bot = bot
        # Pastikan view persisten didaftarkan
        if not hasattr(bot, 'persistent_views_added'):
            bot.add_view(CSPanelView(bot))
            bot.persistent_views_added = True

    async def generate_story_from_ai(self, server: str, nama_char: str, tanggal_lahir: str, kota_asal: str) -> str:
        """Menghasilkan story dari AI berdasarkan input dan aturan server."""
        
        if not self.bot.config.GEMINI_API_KEYS:
            raise Exception("API Key Gemini tidak dikonfigurasi.")
            
        api_key = self.bot.config.GEMINI_API_KEYS[0] # Ambil key pertama
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')

        server_rules = SERVER_CONFIG[server]["rules"]
        
        prompt = f"""
        Peran: Anda adalah seorang penulis cerita kreatif yang sangat berpengalaman dalam dunia roleplay GTA San Andreas Multiplayer (SAMP) di Indonesia.

        Tugas: Buatlah sebuah Character Story (CS) yang unik, mendalam, dan logis berdasarkan informasi berikut:
        - Nama Karakter: {nama_char}
        - Tanggal Lahir: {tanggal_lahir}
        - Kota Asal: {kota_asal}

        Cerita harus mengikuti alur naratif yang umum:
        1. Latar belakang dan kehidupan awal di kota asalnya.
        2. Sebuah peristiwa penting atau titik balik yang mendorong karakter untuk pindah ke kota Los Santos.
        3. Perjuangan atau adaptasi awal setelah tiba di Los Santos.
        4. Kondisi karakter saat ini dan tujuannya di masa depan.

        ATURAN WAJIB UNTUK SERVER {SERVER_CONFIG[server]["name"]}:
        {server_rules}

        Hasil akhir harus berupa cerita saja, tanpa judul atau format tambahan. Pastikan cerita yang dihasilkan menarik dan konsisten.
        """
        
        logger.info(f"Mengirim prompt ke Gemini untuk karakter {nama_char}...")
        response = await model.generate_content_async(prompt)
        
        # Membersihkan jika ada markdown
        cleaned_story = response.text.strip().replace("```", "")
        
        return cleaned_story

    @commands.command(name="setupcs")
    @commands.has_permissions(administrator=True)
    async def setup_cs_panel(self, ctx):
        """Mengirim panel untuk membuat Character Story (Admin only)."""
        embed = discord.Embed(
            title="📝 Panel Pembuatan Character Story",
            description="Gunakan tombol di bawah ini untuk memulai proses pembuatan **Character Story (CS)** berbasis AI.",
            color=0x5865F2 # Warna Discord Blurple
        )
        embed.add_field(
            name="Ringkasan Aturan Umum",
            value="• Minimal 4 paragraf & 200+ kata.\n"
                  "• Bahasa Indonesia baku, tanpa plagiarisme.\n"
                  "• Usia karakter minimal 17 tahun.\n\n"
                  "*Bot akan secara otomatis menyesuaikan cerita dengan aturan spesifik dari server yang kamu pilih.*"
        )
        embed.set_footer(text="Tekan tombol di bawah untuk memulai.")

        await ctx.send(embed=embed, view=CSPanelView(self.bot))

async def setup(bot):
    await bot.add_cog(CharacterStoryCog(bot))

