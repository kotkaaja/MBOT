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
                "  Meminta proposal struktur server lengkap dari AI.\n\n"
                "• `!createcategory [deskripsi]`\n"
                "  Meminta proposal satu kategori dari AI.\n\n"
                "• `!deletecategory [nama kategori]`\n"
                "  Menghapus kategori beserta semua channel di dalamnya."
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
        
        # --- Fitur Token (Dipisah) ---
        embed.add_field(
            name="💎 Fitur Token (GitHub)",
            value=(
                "Klaim token berbasis GitHub.\n\n"
                "**Perintah Pengguna (Slash Command):**\n"
                "Gunakan tombol di channel klaim untuk:\n"
                "• `Claim Token`: Mengklaim token berdasarkan role Anda (cooldown 7 hari).\n"
                "• `Cek Token Saya`: Melihat status token aktif dan cooldown Anda.\n\n"
                "**Perintah Admin (Slash Command):**\n"
                "• `/open_claim [alias]`: Membuka sesi klaim.\n"
                "• `/close_claim`: Menutup sesi klaim.\n"
                "• `/admin_add_token [alias] [token]`: Menambah token manual.\n"
                "• `/admin_reset_cooldown [user]`: Mereset cooldown klaim user.\n"
                "• `...dan banyak lagi (ketik / untuk melihat semua).`"
            ),
            inline=False
        )
        
        # --- Fitur Role (Dipisah) ---
        embed.add_field(
            name="👑 Fitur Role Otomatis",
            value=(
                "Dapatkan role otomatis dengan mengirim bukti (SS) di channel request role.\n"
                "• **Role Didukung**: `Subscriber`, `Follower`, dan `Inner Circle`."
            ),
            inline=False
        )
        
        embed.add_field(
            name="🎵 Fitur MP3 Converter (maintenance)",
            value=(
                "• `!convert [link]` - Konversi link YT/TikTok/Spotify.\n"
                "• `!setuploadchannel [#channel]` - **(Admin)** Atur channel unggah."
            ),
            inline=False
        )
        # Penjelasan Fitur Scanner
        embed.add_field(
            name="🛡️ Fitur Scanner File",
            value=(
                "Analisis file (`.lua`, `.zip`, dll.) untuk mendeteksi kode berbahaya.\n\n"
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
