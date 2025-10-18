# cogs/help_token.py
import discord
from discord.ext import commands
import logging

# Import check admin dari token.py (atau definisikan ulang jika perlu, tapi impor lebih baik)
from .token import is_admin_check_prefix

logger = logging.getLogger(__name__)

class HelpTokenCog(commands.Cog, name="HelpToken"):
    def __init__(self, bot):
        self.bot = bot
        # Ambil CLAIM_CHANNEL_ID dari config bot untuk ditampilkan di help
        self.claim_channel_id = bot.config.CLAIM_CHANNEL_ID

    @commands.command(name="helptoken")
    async def help_token_command(self, ctx: commands.Context):
        """Menampilkan bantuan perintah khusus untuk fitur Token."""

        embed = discord.Embed(
            title="💎 Bantuan Perintah Fitur Token (GitHub)",
            description=f"Berikut adalah daftar perintah dan cara menggunakan fitur klaim token.\nPanel klaim akan muncul di <#{self.claim_channel_id}> saat sesi dibuka.",
            color=0x1ABC9C # Warna Teal
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url if self.bot.user else None)

        # --- Perintah Pengguna (Tombol Interaktif) ---
        embed.add_field(
            name="👤 Perintah Pengguna (Tombol)",
            value=(
                f"Tombol-tombol ini muncul di <#{self.claim_channel_id}> saat admin membuka sesi klaim (`!open_claim`):\n\n"
                "• **`Claim Token`** (Tombol Hijau):\n"
                "  - Klaim token berdasarkan *role* tertinggi Anda (VIP > Supporter > Inner Circle > ... > Beginner).\n"
                "  - Cooldown: **7 hari**.\n"
                "  - Token dikirim via DM.\n"
                "  - Gagal jika masih ada token aktif atau dalam cooldown.\n\n"
                "• **`Cek Token Saya`** (Tombol Abu-abu):\n"
                "  - Lihat status token aktif Anda, masa berlaku, dan sisa waktu cooldown klaim."
            ),
            inline=False
        )

        # --- Perintah Admin (Prefix !) ---
        # Cek apakah pengguna adalah admin sebelum menampilkan bagian ini
        is_admin = await is_admin_check_prefix(ctx)
        if is_admin:
            embed.add_field(
                name="⚙️ Perintah Admin (Prefix `!`)",
                value=(
                    "**Manajemen Sesi:**\n"
                    "• `!open_claim [alias]` - Membuka sesi klaim & mengirim panel.\n"
                    "• `!close_claim` - Menutup sesi klaim & menghapus panel.\n\n"
                    "**Manajemen Token Manual:**\n"
                    "• `!admin_add_token [alias] [token]` - Tambah token ke file (tanpa auto-expire).\n"
                    "• `!admin_remove_token [alias] [token]` - Hapus token dari file.\n"
                    "• `!admin_add_shared [alias] [token] [durasi]` - Tambah token umum (auto-expire).\n"
                    "• `!admin_give_token [@user] [alias] [token] [durasi]` - Beri token ke user (tidak reset cooldown).\n\n"
                    "**Manajemen Pengguna:**\n"
                    "• `!admin_reset_user [@user]` - Reset token aktif & cooldown user.\n"
                    "• `!admin_cek_user [@user]` - Cek status token & cooldown user.\n"
                    "• `!notifycooldowns` - Kirim notifikasi DM manual ke user yang cooldownnya selesai.\n\n"
                    "**Pemeriksaan & Konfigurasi:**\n"
                    "• `!list_sources` - Lihat semua sumber token terkonfigurasi.\n"
                    "• `!baca_file [alias]` - Tampilkan isi file token dari sumber.\n"
                    "• `!list_tokens` - Tampilkan semua token yang sedang aktif.\n"
                    "• `!show_config` - Tampilkan konfigurasi channel & repo.\n"
                    "• `!serverlist` - Tampilkan daftar server bot."
                ),
                inline=False
            )
        else:
             embed.set_footer(text="Beberapa perintah hanya terlihat oleh Admin Bot.")


        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(HelpTokenCog(bot))
