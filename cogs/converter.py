import discord
from discord.ext import commands
import yt_dlp
import os
import asyncio
import logging

from utils.database import get_upload_channel

# Ambil logger
logger = logging.getLogger(__name__)

class ConverterCog(commands.Cog, name="Converter"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="setuploadchannel")
    @commands.has_permissions(administrator=True)
    async def setup_upload_channel(self, ctx, channel: discord.TextChannel):
        """Mengatur channel untuk mengupload hasil konversi MP3."""
        from utils.database import set_upload_channel
        
        success = set_upload_channel(ctx.guild.id, channel.id)
        if success:
            await ctx.send(f"✅ **Channel upload berhasil diatur!**\nHasil konversi MP3 akan dikirim ke {channel.mention}")
        else:
            await ctx.send("❌ Gagal menyimpan pengaturan channel. Cek log bot untuk detail.")

    @commands.command(name="convert")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def convert_command(self, ctx, *, url: str):
        """Mengonversi link dari YouTube/TikTok/Spotify menjadi file MP3."""
        # 1. Cek channel unggah dari database
        upload_channel_id = get_upload_channel(ctx.guild.id)
        if not upload_channel_id:
            return await ctx.send("❌ Channel unggah MP3 belum diatur. Admin perlu menjalankan `!setuploadchannel #channel` terlebih dahulu.")

        upload_channel = self.bot.get_channel(upload_channel_id)
        if not upload_channel:
            return await ctx.send(f"❌ Channel unggah (ID: {upload_channel_id}) tidak ditemukan atau saya tidak memiliki akses. Harap atur ulang.")

        processing_msg = await ctx.send(f"📥 Memproses link Anda... `{url[:70]}`")

        loop = asyncio.get_event_loop()
        
        # Opsi untuk yt-dlp
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            'outtmpl': f'temp/{ctx.message.id}',
            'noplaylist': True,
            'quiet': True,
            'default_search': 'ytsearch',
            'extractor_args': {
                'youtube': {
                    'skip': ['hls', 'dash'],
                }
            },
        }
        
        filename = None
        try:
            # 2. Proses Unduhan di thread terpisah
            await processing_msg.edit(content="Downloading... ⏳ (Proses ini bisa memakan waktu beberapa saat)")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                filename = f"temp/{ctx.message.id}.mp3"

            if not os.path.exists(filename):
                raise FileNotFoundError("File MP3 tidak ditemukan setelah proses unduh.")

            # 3. Kirim file ke channel yang sudah diatur
            file_title = info.get('title', 'audio')
            await processing_msg.edit(content=f"📤 Mengunggah `{file_title}`...")
            
            with open(filename, 'rb') as fp:
                clean_filename = f"{file_title}.mp3".replace("/", "_").replace("\\", "_")
                
                await upload_channel.send(
                    content=f"🎵 Konversi berhasil untuk **{file_title}**\nDiminta oleh: {ctx.author.mention}",
                    file=discord.File(fp, filename=clean_filename)
                )
            
            await processing_msg.edit(content=f"✅ **Berhasil!** File MP3 telah diunggah ke {upload_channel.mention}.")

        except yt_dlp.utils.DownloadError as e:
            logger.error(f"yt-dlp DownloadError: {e}")
            await processing_msg.edit(content=f"❌ **Gagal mengunduh.** Video ini mungkin privat, dibatasi umur, atau tidak tersedia di wilayah Anda.")
        except Exception as e:
            logger.error(f"Gagal mengonversi link: {url}", exc_info=e)
            await processing_msg.edit(content=f"❌ **Terjadi kesalahan internal.** Cek log bot untuk detail.")
        
        finally:
            # 4. Hapus file sementara dengan aman
            if filename and os.path.exists(filename):
                try:
                    os.remove(filename)
                except Exception as e:
                    logger.error(f"Gagal menghapus file sementara {filename}", exc_info=e)

async def setup(bot):
    # Buat direktori 'temp' jika belum ada
    if not os.path.exists('temp'):
        os.makedirs('temp')
    await bot.add_cog(ConverterCog(bot))
