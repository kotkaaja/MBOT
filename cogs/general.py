import discord
from discord.ext import commands

class GeneralCog(commands.Cog, name="General"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help_command(self, ctx):
        """Menampilkan pesan bantuan untuk semua fitur bot."""
        embed = discord.Embed(
            title="Bantuan Perintah MBOT",
            description="Berikut adalah daftar semua fitur yang tersedia di bot ini.",
            color=0x0099ff
        )

        embed.add_field(
            name="🤖 Fitur Character Story (`!setupcs`)",
            value=(
                "Gunakan perintah `!setupcs` untuk mengirim panel interaktif pembuatan *character story* (CS) berbasis AI.\n\n"
                "**Alur Penggunaan:**\n"
                "1. Tekan tombol 'Buat Character Story'.\n"
                "2. Pilih server tujuan (SSRP, Virtual RP, AARP, GCRP).\n"
                "3. Pilih sisi cerita (Baik/Jahat).\n"
                "4. Isi formulir detail karakter dalam 2 tahap.\n"
                "5. Bot akan menghasilkan cerita dan mengirimnya ke channel."
            ),
            inline=False
        )

        embed.add_field(
            name="🛡️ Fitur Scanner File (`!scan`)",
            value=(
                "Fitur ini menganalisis file (`.lua`, `.txt`, `.zip`, dll.) untuk mendeteksi kode berbahaya.\n\n"
                "**Cara Penggunaan:**\n"
                "- **Scan Otomatis:** Cukup unggah file ke channel.\n"
                "- **Scan Manual:** Gunakan `!scan [url_file]` atau `!scan` lalu unggah file.\n"
                "- **Pilih Analyst:** `!scan [analyst] [url]`. Pilihan: `auto`, `gemini`, `openai`, `manual`."
            ),
            inline=False
        )
        
        embed.add_field(
            name="📊 Perintah Lainnya",
            value=(
                "- `!history [jumlah]`: Melihat riwayat scan Anda.\n"
                "- `!stats`: Melihat statistik penggunaan bot."
            ),
            inline=False
        )

        embed.set_footer(text="Dibuat oleh Kotkaaja")

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(GeneralCog(bot))
