import discord
from discord.ext import commands
import yt_dlp
import os
import asyncio
import logging
import aiohttp
from typing import Optional

from utils.database import get_upload_channel

logger = logging.getLogger(__name__)

class ConverterCog(commands.Cog, name="Converter"):
    def __init__(self, bot):
        self.bot = bot

    async def upload_to_catbox(self, file_path: str) -> Optional[str]:
        """Upload file ke Catbox.moe dan return direct link."""
        try:
            async with aiohttp.ClientSession() as session:
                with open(file_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('reqtype', 'fileupload')
                    data.add_field('fileToUpload', f, filename=os.path.basename(file_path))
                    
                    async with session.post('https://catbox.moe/user/api.php', data=data) as resp:
                        if resp.status == 200:
                            url = await resp.text()
                            return url.strip()
                        else:
                            logger.error(f"Catbox upload failed: {resp.status}")
                            return None
        except Exception as e:
            logger.error(f"Error uploading to Catbox: {e}")
            return None

    async def upload_to_gofile(self, file_path: str) -> Optional[str]:
        """Upload file ke GoFile.io dan return direct link."""
        try:
            async with aiohttp.ClientSession() as session:
                # Get best server
                async with session.get('https://api.gofile.io/getServer') as resp:
                    if resp.status != 200:
                        return None
                    server_data = await resp.json()
                    server = server_data['data']['server']
                
                # Upload file
                with open(file_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('file', f, filename=os.path.basename(file_path))
                    
                    async with session.post(f'https://{server}.gofile.io/uploadFile', data=data) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            if result['status'] == 'ok':
                                return result['data']['downloadPage']
                        return None
        except Exception as e:
            logger.error(f"Error uploading to GoFile: {e}")
            return None

    async def upload_to_top4top(self, file_path: str) -> Optional[str]:
        """Upload file ke Top4Top dan return direct link."""
        try:
            async with aiohttp.ClientSession() as session:
                with open(file_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('file_1_', f, filename=os.path.basename(file_path))
                    data.add_field('submitr', '[ رفع الملفات ]')
                    
                    async with session.post('https://top4top.io/uploadfile', data=data) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            # Parse response untuk mendapatkan direct link
                            # Top4Top mengembalikan HTML, kita perlu extract URL
                            import re
                            match = re.search(r'https://[a-z0-9-]+\.top4top\.io/[^\s"\'<>]+', text)
                            if match:
                                return match.group(0)
                        return None
        except Exception as e:
            logger.error(f"Error uploading to Top4Top: {e}")
            return None

    async def try_upload_to_hosts(self, file_path: str, status_msg: discord.Message):
        """Mencoba upload ke berbagai hosting secara berurutan."""
        hosts = [
            ("Catbox.moe", self.upload_to_catbox),
            ("GoFile.io", self.upload_to_gofile),
            ("Top4Top", self.upload_to_top4top)
        ]
        
        for host_name, upload_func in hosts:
            await status_msg.edit(content=f"⬆️ Mengupload ke {host_name}...")
            link = await upload_func(file_path)
            if link:
                return link, host_name
        
        return None, None

    @commands.command(name="setuploadchannel")
    @commands.has_permissions(administrator=True)
    async def setup_upload_channel(self, ctx, channel: discord.TextChannel):
        """Mengatur channel untuk mengirim link streaming musik."""
        from utils.database import set_upload_channel
        
        success = set_upload_channel(ctx.guild.id, channel.id)
        if success:
            await ctx.send(f"✅ **Channel streaming berhasil diatur!**\nLink musik akan dikirim ke {channel.mention}")
        else:
            await ctx.send("❌ Gagal menyimpan pengaturan channel. Cek log bot untuk detail.")

    @commands.command(name="convert")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def convert_command(self, ctx, *, url: str):
        """Mengonversi link YouTube/Spotify menjadi link streaming untuk Boombox GTA SAMP."""
        # 1. Cek channel
        upload_channel_id = get_upload_channel(ctx.guild.id)
        if not upload_channel_id:
            return await ctx.send("❌ Channel belum diatur. Admin perlu menjalankan `!setuploadchannel #channel` terlebih dahulu.")

        upload_channel = self.bot.get_channel(upload_channel_id)
        if not upload_channel:
            return await ctx.send(f"❌ Channel (ID: {upload_channel_id}) tidak ditemukan. Harap atur ulang.")

        processing_msg = await ctx.send(f"📥 **Memproses:** `{url[:70]}`...")

        loop = asyncio.get_event_loop()
        
        # Opsi yt-dlp
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',  # Kualitas lebih rendah untuk upload lebih cepat
            }],
            'outtmpl': f'temp/{ctx.message.id}',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch',
            'extractor_args': {
                'youtube': {
                    'skip': ['hls', 'dash'],
                }
            },
        }
        
        filename = None
        try:
            # 2. Download dari YouTube
            await processing_msg.edit(content="⏬ **Mengunduh audio...**")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                filename = f"temp/{ctx.message.id}.mp3"

            if not os.path.exists(filename):
                raise FileNotFoundError("File MP3 tidak ditemukan setelah proses unduh.")

            file_title = info.get('title', 'Unknown')
            file_size = os.path.getsize(filename) / (1024 * 1024)  # MB
            
            # Cek ukuran file (max 25MB untuk kebanyakan host gratis)
            if file_size > 25:
                await processing_msg.edit(content=f"❌ File terlalu besar ({file_size:.1f}MB). Maksimal 25MB.")
                return

            # 3. Upload ke hosting
            stream_link, host_used = await self.try_upload_to_hosts(filename, processing_msg)
            
            if not stream_link:
                await processing_msg.edit(content="❌ Gagal mengupload ke semua hosting. Coba lagi nanti.")
                return

            # 4. Kirim hasil ke channel
            embed = discord.Embed(
                title="🎵 Link Streaming Berhasil Dibuat!",
                description=f"**{file_title}**",
                color=0x1DB954  # Spotify green
            )
            embed.add_field(name="📊 Info", value=f"Ukuran: {file_size:.2f}MB\nHost: {host_used}", inline=False)
            embed.add_field(name="🔗 Link Streaming", value=f"```{stream_link}```", inline=False)
            embed.add_field(
                name="📝 Cara Pakai di GTA SAMP",
                value="1. Ambil Boombox/Ghettoblaster\n2. Ketik `/playurl` atau `/radio`\n3. Paste link di atas",
                inline=False
            )
            embed.set_footer(text=f"Diminta oleh {ctx.author.display_name}")
            
            await upload_channel.send(content=f"{ctx.author.mention}", embed=embed)
            await processing_msg.edit(content=f"✅ **Selesai!** Link streaming telah dikirim ke {upload_channel.mention}")

        except yt_dlp.utils.DownloadError as e:
            logger.error(f"yt-dlp error: {e}")
            await processing_msg.edit(content="❌ Gagal mengunduh. Video mungkin privat atau tidak tersedia di wilayah Anda.")
        except Exception as e:
            logger.error(f"Converter error: {e}", exc_info=True)
            await processing_msg.edit(content=f"❌ Terjadi kesalahan: `{str(e)[:100]}`")
        finally:
            # Hapus file temp
            if filename and os.path.exists(filename):
                try:
                    os.remove(filename)
                except Exception as e:
                    logger.error(f"Failed to delete temp file: {e}")

async def setup(bot):
    if not os.path.exists('temp'):
        os.makedirs('temp')
    await bot.add_cog(ConverterCog(bot))
