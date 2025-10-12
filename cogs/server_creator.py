import discord
from discord.ext import commands
from discord import ui
import json
from openai import AsyncOpenAI
import logging

# Mengambil logger
logger = logging.getLogger(__name__)

# --- PROMPT ENGINEERING UNTUK AI ---
SYSTEM_PROMPT = """
Anda adalah seorang "Discord Architect AI", seorang asisten ahli dalam merancang struktur server Discord yang efisien.
Tugas Anda adalah membaca deskripsi proyek dari pengguna dan mengubahnya menjadi proposal struktur kategori dan channel dalam format JSON yang ketat.

ATURAN KETAT:
1.  Output HARUS HANYA berupa JSON yang valid, tanpa teks penjelasan tambahan di luar blok JSON.
2.  Struktur JSON harus mengikuti format ini:
    {
      "category_name": "NAMA_KATEGORI_YANG_DISARANKAN",
      "channels": [
        { "type": "text", "name": "nama-channel-teks-1" },
        { "type": "voice", "name": "Nama Channel Suara 1" },
        { "type": "forum", "name": "nama-forum-diskusi" }
      ]
    }
3.  Nama kategori harus singkat, deskriptif, dan bisa menyertakan emoji yang relevan.
4.  Nama channel TEKS dan FORUM harus ditulis dengan huruf kecil dan menggunakan tanda hubung (-).
5.  Nama channel SUARA bisa menggunakan huruf besar dan spasi.
6.  Setiap proyek harus memiliki satu channel teks umum dan satu channel suara.
7.  Analisis deskripsi pengguna untuk membuat channel yang relevan dengan tim atau tugas.
"""

# --- VIEW UNTUK TOMBOL KONFIRMASI ---
class ConfirmationView(ui.View):
    def __init__(self, author: discord.User, proposal_data: dict):
        super().__init__(timeout=300)  # Tombol akan nonaktif setelah 5 menit
        self.author = author
        self.proposal_data = proposal_data

    # Cek interaksi hanya dari pengguna asli
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Hanya pengguna yang meminta yang dapat menekan tombol ini.", ephemeral=True)
            return False
        return True

    @ui.button(label="Setuju & Buat", style=discord.ButtonStyle.green)
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        # Nonaktifkan semua tombol setelah ditekan
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ Disetujui! Membangun struktur server...", view=self)

        guild = interaction.guild
        try:
            # 1. Buat Kategori
            category_name = self.proposal_data.get("category_name", "Proyek Baru")
            new_category = await guild.create_category(name=category_name)

            # 2. Buat semua channel di dalam kategori tersebut
            for channel in self.proposal_data.get("channels", []):
                ch_type = channel.get("type")
                ch_name = channel.get("name")
                if ch_type == "text":
                    await new_category.create_text_channel(name=ch_name)
                elif ch_type == "voice":
                    await new_category.create_voice_channel(name=ch_name)
                elif ch_type == "forum":
                    await new_category.create_forum(name=ch_name)
            
            await interaction.followup.send(f"Struktur untuk **{category_name}** berhasil dibuat!")

        except Exception as e:
            await interaction.followup.send(f"Gagal membuat struktur server. Kesalahan: {e}")

    @ui.button(label="Batal", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        # Nonaktifkan semua tombol setelah ditekan
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Dibatalkan. Tidak ada perubahan yang dibuat.", view=self)


# --- KELAS COG UTAMA ---
class ServerCreatorCog(commands.Cog, name="ServerCreator"):
    def __init__(self, bot):
        self.bot = bot
        self.client = None
        if self.bot.config.OPENAI_API_KEYS:
            try:
                # Menggunakan API key dari config bot
                self.client = AsyncOpenAI(api_key=self.bot.config.OPENAI_API_KEYS[0])
                logger.info("✅ Model OpenAI untuk Server Creator berhasil diinisialisasi.")
            except Exception as e:
                logger.error(f"❌ Gagal mengkonfigurasi OpenAI: {e}")
        else:
            logger.warning("⚠️ OPENAI_API_KEYS tidak ditemukan di .env, fitur Server Creator tidak akan berfungsi.")

    @commands.command(name="createserver")
    @commands.has_permissions(manage_channels=True)
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def create_server_command(self, ctx, *, deskripsi_proyek: str):
        """Rancang dan buat struktur kategori & channel baru menggunakan AI."""
        if not self.client:
            return await ctx.send("❌ Fitur ini tidak aktif karena API Key OpenAI tidak dikonfigurasi.")
        
        msg = await ctx.send(f"🤖 AI sedang merancang struktur untuk proyek: *\"{deskripsi_proyek}\"*... mohon tunggu.")

        try:
            # Mengirim permintaan ke OpenAI API
            full_prompt = f"{SYSTEM_PROMPT}\n\nDeskripsi Proyek Pengguna:\n\"{deskripsi_proyek}\""
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": full_prompt}],
                response_format={"type": "json_object"},
                temperature=0.5
            )
            
            clean_response = response.choices[0].message.content.strip()
            proposal_data = json.loads(clean_response)

            # Memformat proposal menjadi pesan Embed
            embed = discord.Embed(
                title="🤖 Proposal Struktur Server dari AI",
                description=f"Berikut adalah rancangan berdasarkan deskripsi Anda. Tekan tombol di bawah untuk konfirmasi.",
                color=discord.Color.blue()
            )
            category_name = proposal_data.get("category_name", "Nama Kategori Tidak Ditemukan")
            embed.add_field(name="Nama Kategori", value=f"**{category_name}**", inline=False)
            text_channels = [ch['name'] for ch in proposal_data.get('channels', []) if ch['type'] == 'text']
            voice_channels = [ch['name'] for ch in proposal_data.get('channels', []) if ch['type'] == 'voice']
            forum_channels = [ch['name'] for ch in proposal_data.get('channels', []) if ch['type'] == 'forum']

            if text_channels:
                embed.add_field(name="Text Channels", value="\n".join([f"`#{name}`" for name in text_channels]), inline=True)
            if voice_channels:
                embed.add_field(name="Voice Channels", value="\n".join([f"`{name}`" for name in voice_channels]), inline=True)
            if forum_channels:
                embed.add_field(name="Forum Channels", value="\n".join([f"`#{name}`" for name in forum_channels]), inline=True)
            
            # Kirim proposal dengan tombol konfirmasi
            view = ConfirmationView(author=ctx.author, proposal_data=proposal_data)
            await msg.edit(content="", embed=embed, view=view)

        except json.JSONDecodeError:
            await msg.edit(content="Maaf, AI memberikan respons dengan format yang tidak valid. Coba deskripsi yang berbeda.")
        except Exception as e:
            await msg.edit(content=f"Terjadi kesalahan: {e}")
            logger.error(f"Error pada perintah createserver: {e}", exc_info=True)

    @create_server_command.error
    async def create_server_error(self, ctx, error):
        """Handler untuk error pada perintah createserver."""
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("Maaf, Anda tidak memiliki izin `Manage Channels` untuk menggunakan perintah ini.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Harap berikan deskripsi proyek. Contoh: `!createserver sebuah server untuk tim gaming Valorant`")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Perintah ini sedang dalam cooldown, coba lagi dalam {error.retry_after:.2f} detik.")
        else:
            logger.error(f"Error tidak dikenal pada perintah createserver: {error}", exc_info=True)
            await ctx.send(f"Terjadi kesalahan tak terduga: {error}")

async def setup(bot):
    await bot.add_cog(ServerCreatorCog(bot))

