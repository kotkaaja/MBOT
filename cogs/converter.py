import discord
from discord.ext import commands
import asyncio
import yt_dlp
import os
import logging
import re
from utils.database import get_upload_channel # Import fungsi baru dari database

# Mengambil logger
logger = logging.getLogger(__name__)

class ConverterCog(commands.Cog, name="Converter"):
    def __init__(self, bot):
        self.bot = bot
        self.temp_dir = "temp_audio"
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)

    def _cleanup_file(self, path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.error(f"Gagal hapus file sementara {path}: {e}")

    async def _download_audio(self, url: str) -> dict:
        output_path = os.path.join(self.temp_dir, '%(id)s.%(ext)s')
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_path,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            'noplaylist': True,
            'quiet': True,
            'nocheckcertificate': True,
            'default_search': 'ytsearch', # Jika link spotify, cari di youtube
        }

        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                downloaded_file = ydl.prepare_filename(info)
                final_path = os.path.splitext(downloaded_file)[0] + '.mp3'
                
                if not os.path.exists(final_path):
                    return {"error": "Gagal mengonversi file ke MP3."}
                
                if os.path.getsize(final_path) > 8 * 1024 * 1024:
                    self._cleanup_file(final_path)
                    return {"error": "File audio terlalu besar (lebih dari 8MB)."}

                return {
                    "path": final_path,
                    "title": info.get('title', 'N/A'),
                    "uploader": info.get('uploader', 'N/A'),
                    "duration": info.get('duration', 0)
                }
            except Exception as e:
                logger.error(f"yt-dlp download error: {e}")
                return {"error": "Gagal mengunduh audio. Pastikan link valid dan tidak bersifat pribadi."}

    @commands.command(name="convert")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def convert_command(self, ctx, *, url: str):
        """Konversi link YouTube/TikTok/Spotify menjadi link MP3 langsung."""
        upload_channel_id = get_upload_channel(ctx.guild.id)
        if not upload_channel_id:
            return await ctx.send("❌ Channel unggah MP3 belum diatur. Admin perlu menjalankan `!setuploadchannel #channel` terlebih dahulu.")
            
        upload_channel = self.bot.get_channel(upload_channel_id)
        if not upload_channel:
            return await ctx.send(f"❌ Channel unggah yang diatur tidak dapat ditemukan. Mohon atur ulang.")

        url = url.strip('<>')
        if not re.match(r'https?://\S+', url):
            return await ctx.send("❌ URL yang Anda masukkan tidak valid.")

        processing_msg = await ctx.send(f"⏳ Memproses link Anda...")

        try:
            result = await self._download_audio(url)
            if "error" in result:
                return await processing_msg.edit(content=f"❌ {result['error']}")

            file_path = result.get("path")
            if not file_path:
                return await processing_msg.edit(content="❌ Terjadi kesalahan, file MP3 tidak ditemukan.")

            with open(file_path, 'rb') as f:
                uploaded_file = await upload_channel.send(file=discord.File(f, filename=f"{result['title']}.mp3"))
            
            mp3_url = uploaded_file.attachments[0].url
            duration_str = f"{int(result['duration'] // 60)}:{int(result['duration'] % 60):02d}"
            
            embed = discord.Embed(title="✅ Audio Berhasil Diproses!", color=discord.Color.green())
            embed.add_field(name="Judul", value=result['title'], inline=False)
            embed.add_field(name="Artis/Uploader", value=result['uploader'], inline=True)
            embed.add_field(name="Durasi", value=duration_str, inline=True)
            embed.add_field(name="Link MP3 (Boombox)", value=f"`{mp3_url}`", inline=False)
            embed.set_footer(text=f"Diminta oleh: {ctx.author.display_name}")
            
            await processing_msg.edit(content=None, embed=embed)
        finally:
            if 'result' in locals() and 'path' in result:
                self._cleanup_file(result['path'])

async def setup(bot):
    await bot.add_cog(ConverterCog(bot))
