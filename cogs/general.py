import discord
from discord.ext import commands

class GeneralCog(commands.Cog, name="General"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help_command(self, ctx):
        """Menampilkan pesan bantuan untuk semua fitur bot."""
        embed = discord.Embed(
            title="Bantuan Perintah KotkaHelper",
            description="Berikut adalah daftar semua fitur yang tersedia di bot ini.",
            color=0x5865F2 # Warna biru Discord
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        # Penjelasan Fitur AI Server Builder
        embed.add_field(
            name="🤖 Fitur AI Server Builder (Admin Only)",
            value=(
                "Rancang struktur server atau kategori secara dinamis menggunakan AI dan UI yang interaktif.\n\n"
                "**Perintah Utama:**\n"
                "• `!createserver [deskripsi]`\n"
                "  Meminta proposal struktur server lengkap dari AI. Anda bisa memilih channel, mengaktifkan/menonaktifkan pembuatan role, dan meminta proposal baru jika tidak suka.\n\n"
                "• `!createcategory [deskripsi]`\n"
                "  Meminta proposal satu kategori dari AI, lengkap dengan pilihan channel interaktif dan opsi proposal baru.\n\n"
                "• `!deletecategory [nama kategori]`\n"
                "  Menghapus kategori beserta semua channel di dalamnya dengan konfirmasi."
            ),
            inline=False
        )
        
        # Penjelasan Fitur Character Story
        embed.add_field(
            name="📝 Fitur Character Story",
            value=(
                "Gunakan `!setupcs` untuk mengirim panel interaktif pembuatan *character story* (CS) berbasis AI. "
                "Terdapat cooldown 1 kali pembuatan per hari."
            ),
            inline=False
        )

        # Penjelasan Fitur Scanner
        embed.add_field(
            name="🛡️ Fitur Scanner File",
            value=(
                "Analisis file (`.lua`, `.zip`, dll.) untuk mendeteksi kode berbahaya secara otomatis saat diunggah atau dengan perintah.\n\n"
                "**Perintah Lainnya:**\n"
                "• `!scan [url]`: Scan file dari URL.\n"
                "• `!history`: Lihat riwayat scan Anda.\n"
                "• `!stats`: Lihat statistik penggunaan bot."
            ),
            inline=False
        )

        embed.set_footer(text=f"Dijalankan oleh {self.bot.user.name} | Dibuat oleh Kotkaaja")

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(GeneralCog(bot))

