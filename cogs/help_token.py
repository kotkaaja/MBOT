# cogs/help_token.py
import discord
from discord.ext import commands
import logging

# Import check admin dari token.py
try:
    from .token import is_admin_check_prefix
except ImportError:
    # Fallback jika struktur file berubah atau untuk testing
    async def is_admin_check_prefix(ctx: commands.Context) -> bool:
        # Implementasi fallback sederhana, Anda mungkin perlu menyesuaikannya
        return await ctx.bot.is_owner(ctx.author)
    logger.warning("Gagal mengimpor is_admin_check_prefix dari cogs.token. Menggunakan fallback.")


logger = logging.getLogger(__name__)

# Batas karakter per field embed Discord
FIELD_VALUE_LIMIT = 1024

class HelpTokenCog(commands.Cog, name="HelpToken"):
    def __init__(self, bot):
        self.bot = bot
        # Ambil CLAIM_CHANNEL_ID dari config bot untuk ditampilkan di help
        self.claim_channel_id = bot.config.CLAIM_CHANNEL_ID if hasattr(bot, 'config') else 'CHANNEL_ID_TIDAK_DISET'

    @commands.command(name="helptoken")
    async def help_token_command(self, ctx: commands.Context):
        """Menampilkan bantuan perintah khusus untuk fitur Token."""

        claim_channel_mention = f"<#{self.claim_channel_id}>" if isinstance(self.claim_channel_id, int) else "`CHANNEL_ID_TIDAK_DISET`"

        embed = discord.Embed(
            title="💎 Bantuan Perintah Fitur Token (GitHub)",
            description=f"Berikut adalah daftar perintah dan cara menggunakan fitur klaim token.\nPanel klaim akan muncul di {claim_channel_mention} saat sesi dibuka.",
            color=0x1ABC9C # Warna Teal
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url if self.bot.user else None)

        # --- Perintah Pengguna (Tombol Interaktif) ---
        user_commands_value = (
            f"Tombol-tombol ini muncul di {claim_channel_mention} saat admin membuka sesi klaim (`!open_claim`):\n\n"
            "• **`Claim Token`** (Tombol Hijau):\n"
            "  - Klaim token berdasarkan *role* tertinggi Anda (VIP > Supporter > Inner Circle > ... > Beginner).\n"
            "  - Cooldown: **7 hari**.\n"
            "  - Token dikirim via DM.\n"
            "  - Gagal jika masih ada token aktif atau dalam cooldown.\n\n"
            "• **`Cek Token Saya`** (Tombol Abu-abu):\n"
            "  - Lihat status token aktif Anda, masa berlaku, dan sisa waktu cooldown klaim."
        )
        # Pastikan field pertama tidak melebihi batas (meskipun kecil kemungkinannya)
        if len(user_commands_value) <= FIELD_VALUE_LIMIT:
             embed.add_field(
                 name="👤 Perintah Pengguna (Tombol)",
                 value=user_commands_value,
                 inline=False
             )
        else:
             logger.error("Nilai field Perintah Pengguna melebihi batas!") # Seharusnya tidak terjadi
             embed.add_field(
                 name="👤 Perintah Pengguna (Tombol)",
                 value="Deskripsi terlalu panjang untuk ditampilkan.",
                 inline=False
            )

        # --- Perintah Admin (Prefix !) ---
        is_admin = await is_admin_check_prefix(ctx)
        if is_admin:
            admin_commands_full_text = (
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
            )

            # --- Logika Pemisahan Field ---
            parts = []
            current_part = ""
            for line in admin_commands_full_text.split('\n'):
                # Cek jika menambahkan baris berikutnya akan melebihi batas
                if len(current_part) + len(line) + 1 > FIELD_VALUE_LIMIT:
                    # Jika ya, simpan bagian saat ini dan mulai bagian baru
                    parts.append(current_part.strip())
                    current_part = line + "\n"
                else:
                    # Jika tidak, tambahkan baris ke bagian saat ini
                    current_part += line + "\n"
            # Tambahkan bagian terakhir yang tersisa
            if current_part:
                parts.append(current_part.strip())

            # Tambahkan bagian-bagian sebagai field terpisah
            for i, part in enumerate(parts):
                field_name = "⚙️ Perintah Admin (Prefix `!`) (Lanjutan)" if i > 0 else "⚙️ Perintah Admin (Prefix `!`) "
                embed.add_field(name=field_name, value=part, inline=False)

        else:
            embed.set_footer(text="Beberapa perintah hanya terlihat oleh Admin Bot.")


        await ctx.send(embed=embed)

# Fungsi setup diperlukan agar cog bisa di-load
async def setup(bot):
    await bot.add_cog(HelpTokenCog(bot))
