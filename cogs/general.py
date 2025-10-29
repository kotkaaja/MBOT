import discord
from discord.ext import commands

class GeneralCog(commands.Cog, name="General"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help_command(self, ctx):
        """Menampilkan ringkasan fitur bot dan perintah bantuan detail."""
        embed = discord.Embed(
            title=" Bantuan Perintah KotkaHelper",
            description="Bot ini memiliki beberapa fitur utama. Gunakan perintah bantuan spesifik di bawah untuk detail lebih lanjut.",
            color=0x5865F2 # Warna biru Discord
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        embed.add_field(
            name=" Fitur Utama",
            value=(
                "• **Character Story (CS)**: Buat cerita karakter otomatis berbasis AI.\n"
                "  Gunakan `!cshelp` untuk info detail.\n\n"
                "• **Template RP (SAMP)**: Buat template macro RP (/me, /do) untuk SAMP.\n"
                "  Gunakan `!rphelp` untuk info detail.\n\n"
                "• **SSRP Chatlog**: Buat gambar chatlog SSRP dengan dialog AI.\n"
                "  Gunakan `!ssrphelp` untuk info detail.\n\n"
                "• **AI Server Builder (Admin)**: Rancang struktur server Discord dengan AI.\n"
                "  Gunakan `!serverhelp` untuk info detail.\n\n"
                "• **Scanner File**: Pindai file untuk kode berbahaya.\n"
                "  Gunakan `!scanhelp` untuk info detail.\n\n"
                "• **Token & Role**: Klaim token akses dan dapatkan role otomatis.\n"
                "  Gunakan `!tokenhelp` untuk info detail.\n\n"
                "• **MP3 Converter (Maintenance)**: Konversi link media ke MP3.\n"
                "  Gunakan `!converterhelp` untuk info detail."

            ),
            inline=False
        )

        embed.set_footer(text=f"Dijalankan oleh {self.bot.user.name} | Dibuat oleh Kotkaaja")
        await ctx.send(embed=embed)

    # --- Perintah Bantuan Spesifik ---

    @commands.command(name="cshelp")
    async def cs_help(self, ctx):
        """Bantuan detail untuk Fitur Character Story."""
        embed = discord.Embed(
            title=" Bantuan Character Story (CS)",
            description="Fitur ini membantu Anda membuat *Character Story* (CS) untuk berbagai server SAMP menggunakan AI.",
            color=0x1ABC9C # Teal
        )
        embed.add_field(
            name="Cara Pakai",
            value=(
                "1. Gunakan perintah `!setupcs`.\n"
                "2. Panel interaktif akan muncul.\n"
                "3. Pilih server tujuan (misal: SSRP, Virtual RP).\n"
                "4. Pilih sisi cerita (Goodside/Badside).\n"
                "5. Isi detail karakter Anda (Nama, Level, Kota Asal, dll.).\n"
                "6. Isi detail cerita (Bakat, Kultur, Detail Tambahan).\n"
                "7. AI akan membuat cerita berdasarkan input Anda.\n"
                "8. Hasilnya akan dikirim sebagai file `.txt` yang siap digunakan."
            ),
            inline=False
        )
        embed.add_field(
            name=" Penting",
            value="• Terdapat batas penggunaan AI harian berdasarkan rank Anda.\n• Pastikan mengisi semua detail dengan benar.",
            inline=False
        )
        await ctx.send(embed=embed)

    @commands.command(name="rphelp")
    async def rp_help(self, ctx):
        """Bantuan detail untuk Fitur Template RP."""
        # Menggunakan kembali fungsi dari template_creator.py jika memungkinkan,
        # atau salin embed bantuannya ke sini.
        # Untuk contoh ini, saya akan panggil command asli jika ada.
        template_cog = self.bot.get_cog("TemplateCreator")
        if template_cog and hasattr(template_cog, 'template_help_command'):
            await template_cog.template_help_command(ctx)
        else:
            # Fallback jika cog tidak ditemukan atau command tidak ada
            embed = discord.Embed(
                title=" Bantuan Template RP (SAMP)",
                description="Fitur membuat template Auto RP (`/me`, `/do`) untuk KotkaHelper (PC/Mobile) via AI.",
                color=0x3498db # Biru
            )
            embed.add_field(name="Perintah Utama", value="`!buatrp` - Memulai proses pembuatan template interaktif.", inline=False)
            embed.add_field(name="Fitur", value="- Membuat macro Auto RP (hotkey), CMD Macro (command), atau Gun RP (ganti senjata).\n- Mendukung berbagai bahasa/aksen.\n- AI mengikuti aturan RP SAMP.", inline=False)
            await ctx.send(embed=embed)

    @commands.command(name="ssrphelp")
    async def ssrp_help(self, ctx):
        """Bantuan detail untuk Fitur SSRP Chatlog."""
        embed = discord.Embed(
            title=" Bantuan SSRP Chatlog",
            description="Fitur ini membuat gambar chatlog SSRP (seperti Chatlog Magician) dengan dialog yang dihasilkan AI.",
            color=0x9B59B6 # Ungu
        )
        embed.add_field(
            name="Cara Pakai",
            value=(
                "1. Lampirkan 1-10 gambar (.png/.jpg/.jpeg) yang ingin dijadikan chatlog.\n"
                "2. Tulis `!buatssrp` di *caption* saat mengunggah gambar.\n"
                "3. Klik tombol 'Isi Informasi SSRP' yang muncul.\n"
                "4. Isi detail skenario, karakter, dan jumlah pemain di form.\n"
                "5. Atur jumlah baris, posisi teks, dan gaya background untuk setiap gambar.\n"
                "6. Klik 'Proses Semua Gambar'.\n"
                "7. AI akan membuat dialog dan menambahkannya ke gambar Anda."
            ),
            inline=False
        )
        embed.add_field(
            name=" Format Gambar",
            value="Gambar akan otomatis di-crop ke rasio **4:3 (800x600)** untuk hasil terbaik.",
            inline=False
        )
        embed.add_field(
            name=" Batasan",
            value="• Maksimal 10 gambar per perintah.\n• Terdapat batas penggunaan AI harian.",
            inline=False
        )
        await ctx.send(embed=embed)

    @commands.command(name="serverhelp")
    async def server_help(self, ctx):
        """Bantuan detail untuk Fitur AI Server Builder (Admin)."""
        embed = discord.Embed(
            title=" Bantuan AI Server Builder (Admin)",
            description="Fitur ini memungkinkan admin merancang struktur server atau kategori baru menggunakan AI.",
            color=0xE91E63 # Pink
        )
        embed.add_field(
            name="Perintah Utama",
            value=(
                "• `!createserver [deskripsi server]`\n"
                "  Meminta AI membuat proposal struktur server lengkap (kategori, channel, role) berdasarkan deskripsi Anda.\n\n"
                "• `!createcategory [deskripsi kategori]`\n"
                "  Meminta AI membuat proposal satu kategori beserta channel-channelnya.\n\n"
                "• `!deletecategory [nama kategori]`\n"
                "  Menghapus kategori yang ada beserta semua channel di dalamnya (hati-hati!)."
            ),
            inline=False
        )
        embed.add_field(
            name=" Alur Kerja",
            value=(
                "1. Gunakan `!createserver` atau `!createcategory`.\n"
                "2. AI akan memberikan proposal dalam bentuk panel interaktif.\n"
                "3. Pilih channel/role yang ingin dibuat menggunakan tombol.\n"
                "4. Klik 'Buat Pilihan' untuk membangun struktur, 'Proposal Baru' untuk meminta AI membuat proposal lain, atau 'Batal'."
            ),
            inline=False
        )
        await ctx.send(embed=embed)

    @commands.command(name="scanhelp")
    async def scan_help(self, ctx):
        """Bantuan detail untuk Fitur Scanner File."""
        embed = discord.Embed(
            title=" Bantuan Scanner File",
            description="Fitur ini menganalisis file (terutama `.lua`, `.zip`, `.rar`, `.7z`) untuk mendeteksi potensi kode berbahaya atau mencurigakan.",
            color=0xF1C40F # Kuning
        )
        embed.add_field(
            name=" Cara Kerja",
            value=(
                "• **Auto-Scan**: Cukup unggah file yang didukung ke channel mana saja (yang diizinkan), bot akan otomatis memindainya (menggunakan analisis pola manual, tanpa AI).\n"
                "• **Scan Manual (dengan AI)**: Gunakan perintah `!scan` untuk analisis yang lebih mendalam menggunakan AI."
            ),
            inline=False
        )
        embed.add_field(
            name=" Perintah",
            value=(
                "• `!scan [analis] [url]` atau lampirkan file\n"
                "  Memindai file terlampir atau dari URL. Anda bisa memilih analis AI (opsional):\n"
                "  `auto` (default), `openai`, `gemini`, `deepseek`, `openrouter`, `agentrouter`, `manual`.\n"
                "  Contoh: `!scan https://example.com/script.lua`\n"
                "  Contoh: `!scan openrouter` (sambil upload file)\n\n"
                "• `!history [jumlah]`\n"
                "  Melihat riwayat pemindaian Anda (default 5 terakhir).\n\n"
                "• `!stats`\n"
                "  Melihat statistik penggunaan bot, rank AI Anda, dan sisa limit harian.\n\n"
                "• `!setrank [user] [rank]` **(Admin)**\n"
                "  Mengatur rank AI pengguna.\n\n"
                "• `!checkrank [user]` **(Admin)**\n"
                "  Memeriksa rank dan limit AI pengguna."
            ),
            inline=False
        )
        embed.add_field(
            name=" Tingkat Bahaya",
            value=(
                "🟢 **Aman**: Tidak ditemukan pola berbahaya.\n"
                "🟡 **Mencurigakan**: Ditemukan pola yang bisa disalahgunakan.\n"
                "🟠 **Sangat Mencurigakan**: Pola berbahaya atau kode tersembunyi.\n"
                "🔴 **Bahaya Tinggi**: Sangat mungkin malware (misal: webhook discord, telegram bot)."
            ),
            inline=False
        )
        await ctx.send(embed=embed)

    @commands.command(name="tokenhelp", aliases=["help_token"])
    async def token_help(self, ctx):
        """Bantuan detail untuk Fitur Token & Role."""
        embed = discord.Embed(
            title=" Bantuan Token & Role",
            description="Fitur ini memungkinkan Anda mengklaim token akses berdasarkan role Discord Anda dan mendapatkan role otomatis.",
            color=0x7289DA # Biru keunguan
        )
        embed.add_field(
            name=" Klaim Token",
            value=(
                "1. Pergi ke channel klaim token yang ditentukan admin.\n"
                "2. Klik tombol **'Claim Token'** pada panel.\n"
                "3. Jika Anda memiliki role yang valid (VIP, Supporter, dll.) dan tidak sedang cooldown (7 hari), token akan dikirim via DM.\n"
                "4. Klik **'Cek Token Saya'** untuk melihat token aktif dan status cooldown."
            ),
            inline=False
        )
        embed.add_field(
            name=" Role Otomatis",
            value=(
                "1. Pergi ke channel request role yang ditentukan admin.\n"
                "2. Kirim bukti (screenshot) berlangganan YouTube atau mengikuti TikTok.\n"
                "3. Bot akan otomatis memberikan role `Subscriber` (untuk YouTube) atau `Follower` (untuk TikTok).\n"
                "4. Jika Anda memiliki kedua role tersebut, Anda akan otomatis mendapatkan role `Inner Circle`."
            ),
            inline=False
        )
        embed.add_field(
            name=" Perintah Admin (Slash Commands)",
            value=(
                "`/open_claim [alias]` - Membuka sesi klaim.\n"
                "`/close_claim` - Menutup sesi klaim.\n"
                "`/add_token [alias] [token]` - Menambah token manual.\n"
                "`/remove_token [alias] [token]` - Menghapus token manual.\n"
                "`/add_shared [alias] [token] [durasi]` - Menambah token umum.\n"
                "`/give_token [user] [alias] [token] [durasi]` - Memberi token ke user.\n"
                "`/revoke_token [user] [token]` - Mencabut token user.\n"
                "`/reset_user [user]` - Mereset data token & cooldown user.\n"
                "`/check_user [user]` - Memeriksa status token/cooldown user.\n"
                "`/cleanup_expired` - Membersihkan token kedaluwarsa sekarang.\n"
                "`/read_file [alias]` - Membaca isi file sumber token (via DM).\n"
                "`/list_tokens` - Menampilkan semua token aktif.\n"
                "`/token_stats` - Statistik sistem token.\n"
                "`/list_sources` - Menampilkan semua sumber token.\n"
                "`/show_config` - Menampilkan konfigurasi bot.\n"
                "`/serverlist` - Daftar server tempat bot berada.\n"
                "`/notify_cooldowns` - Kirim notifikasi DM cooldown selesai."
            ),
            inline=False
        )
        await ctx.send(embed=embed)

    @commands.command(name="converterhelp")
    async def converter_help(self, ctx):
        """Bantuan detail untuk Fitur MP3 Converter."""
        embed = discord.Embed(
            title=" Bantuan MP3 Converter (Maintenance)",
            description="Fitur ini mengkonversi link dari YouTube, TikTok, atau Spotify menjadi link streaming MP3 langsung.",
            color=0xFF0000 # Merah
        )
        embed.add_field(
            name=" Cara Pakai",
            value=(
                "1. Gunakan perintah `!convert [link media]`.\n"
                "   Contoh: `!convert https://www.youtube.com/watch?v=dQw4w9WgXcQ`\n"
                "2. Bot akan mengunduh audio, mengkonversinya ke MP3 (128kbps), dan mengunggahnya ke hosting file.\n"
                "3. Link MP3 akan dikirim ke channel yang telah diatur oleh admin."
            ),
            inline=False
        )
        embed.add_field(
            name=" Perintah Admin",
            value=(
                "`!setuploadchannel [#channel]`\n"
                "Mengatur channel tujuan untuk mengirim link MP3 yang sudah jadi."
            ),
            inline=False
        )
        embed.add_field(
            name=" Catatan",
            value=(
                "• Terdapat cooldown 60 detik per pengguna.\n"
                "• Ukuran file maksimal adalah 50MB.\n"
                "• Fitur ini mungkin sedang dalam perbaikan (maintenance)."
            ),
            inline=False
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(GeneralCog(bot))
