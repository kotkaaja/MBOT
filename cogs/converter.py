import discord
from discord.ext import commands
import yt_dlp
import os
import asyncio
import logging
import aiohttp
from typing import Optional

from utils.database import get_upload_channel, set_upload_channel

logger = logging.getLogger(__name__)

class ConverterCog(commands.Cog, name="Converter"):
    def __init__(self, bot):
        self.bot = bot

    async def upload_to_0x0(self, file_path: str) -> Optional[str]:
        """Upload ke 0x0.st — mengembalikan URL file langsung."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session:
                with open(file_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('file', f, filename=os.path.basename(file_path))
                    
                    # Gunakan URL BERSIH, bukan markdown!
                    async with session.post('https://0x0.st', data=data) as resp:
                        if resp.status == 200:
                            url = (await resp.text()).strip()
                            # Pastikan URL valid dan berakhiran .mp3
                            if url.endswith('.mp3') or '/mp3/' in url or '0x0.st' in url:
                                return url
        except Exception as e:
            logger.error(f"0x0.st upload error: {e}")
        return None

    @commands.command(name="setuploadchannel")
    @commands.has_permissions(administrator=True)
    async def setup_upload_channel(self, ctx, channel: discord.TextChannel):
        """Atur channel untuk link streaming."""
        if set_upload_channel(ctx.guild.id, channel.id):
            await ctx.send(f"✅ Channel diatur ke {channel.mention}")
        else:
            await ctx.send("❌ Gagal menyimpan ke database.")

    @commands.command(name="convert")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def convert_command(self, ctx, *, url: str):
        """Convert YouTube/TikTok/Spotify jadi link MP3 streaming untuk SA-MP."""
        upload_channel_id = get_upload_channel(ctx.guild.id)
        if not upload_channel_id:
            return await ctx.send("❌ Channel belum diatur. Admin ketik `!setuploadchannel #channel`")

        upload_channel = self.bot.get_channel(upload_channel_id)
        if not upload_channel:
            return await ctx.send("❌ Channel tidak ditemukan.")

        msg = await ctx.send("⏬ Sedang mengunduh...")

        filename = f"temp/{ctx.message.id}.mp3"
        os.makedirs("temp", exist_ok=True)

        ydl_opts = {
            'format': 'bestaudio[ext=mp3]/bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
            'outtmpl': f'temp/{ctx.message.id}',
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            # Tambahkan user-agent untuk hindari blokir ringan
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        }

        try:
            loop = asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))

            if not os.path.exists(filename):
                return await msg.edit(content="❌ Gagal membuat file MP3.")

            title = info.get('title', 'Unknown').strip()
            size_mb = os.path.getsize(filename) / (1024 * 1024)

            if size_mb > 50:
                return await msg.edit(content=f"❌ File terlalu besar ({size_mb:.1f} MB). Maksimal 50 MB.")

            await msg.edit(content="⬆️ Mengupload ke 0x0.st...")

            link = await self.upload_to_0x0(filename)
            if not link:
                return await msg.edit(content="❌ Gagal upload ke 0x0.st. Coba lagi nanti.")

            # Pastikan link bisa diakses langsung sebagai file
            if not link.startswith("http"):
                return await msg.edit(content="❌ URL tidak valid dari 0x0.st.")

            await upload_channel.send(
                f"🎵 **{discord.utils.escape_markdown(title)}**\n"
                f"{link}\n\n"
                f"Diminta oleh: {ctx.author.mention} | Host: 0x0.st"
            )
            await msg.edit(content=f"✅ Link MP3 dikirim ke {upload_channel.mention}!")

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"Download error: {error_msg}")
            if "confirm you’re not a bot" in error_msg or "429" in error_msg:
                await msg.edit(content="❌ YouTube memblokir permintaan. Coba lagi nanti atau gunakan link lain.")
            elif "is not a valid URL" in error_msg:
                await msg.edit(content="❌ URL tidak valid. Pastikan link YouTube/TikTok/Spotify.")
            else:
                await msg.edit(content="❌ Gagal mengunduh audio. Coba link lain.")
        except Exception as e:
            logger.exception("Unexpected error in convert command")
            await msg.edit(content=f"❌ Error: {str(e)[:150]}")
        finally:
            # Hapus file sementara
            try:
                if os.path.exists(filename):
                    os.remove(filename)
            except Exception as e:
                logger.warning(f"Gagal hapus file {filename}: {e}")

async def setup(bot):
    os.makedirs("temp", exist_ok=True)
    await bot.add_cog(ConverterCog(bot))
