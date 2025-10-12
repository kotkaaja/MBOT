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

    async def upload_to_top4top(self, file_path: str) -> Optional[str]:
        """Upload file ke Top4Top (Priority #1 - Paling stabil untuk SAMP)."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                with open(file_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('file_1_', f, filename=os.path.basename(file_path))
                    data.add_field('submitr', '[ رفع الملفات ]')
                    
                    async with session.post('https://top4top.io/uploadfile', data=data) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            # Extract direct link dari response HTML
                            import re
                            # Pattern untuk direct link top4top
                            patterns = [
                                r'https://[a-z0-9-]+\.top4top\.io/mp3_[^\s"\'<>]+\.mp3',
                                r'https://[a-z0-9-]+\.top4top\.io/m_[^\s"\'<>]+\.mp3',
                                r'https://[a-z0-9-]+\.top4top\.io/[^\s"\'<>]+\.mp3'
                            ]
                            for pattern in patterns:
                                match = re.search(pattern, text)
                                if match:
                                    return match.group(0)
                        return None
        except Exception as e:
            logger.error(f"Top4Top error: {e}")
            return None

    async def upload_to_fileio(self, file_path: str) -> Optional[str]:
        """Upload ke File.io (14 hari expire, tapi reliable)."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                with open(file_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('file', f, filename=os.path.basename(file_path))
                    
                    async with session.post('https://file.io', data=data) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            if result.get('success'):
                                return result['link']
                        return None
        except Exception as e:
            logger.error(f"File.io error: {e}")
            return None

    async def upload_to_0x0(self, file_path: str) -> Optional[str]:
        """Upload ke 0x0.st (365 hari expire)."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                with open(file_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('file', f, filename=os.path.basename(file_path))
                    
                    async with session.post('https://0x0.st', data=data) as resp:
                        if resp.status == 200:
                            url = await resp.text()
                            return url.strip()
                        return None
        except Exception as e:
            logger.error(f"0x0.st error: {e}")
            return None

    async def upload_to_tmpfiles(self, file_path: str) -> Optional[str]:
        """Upload ke tmpfiles.org (1 jam expire, tapi sangat cepat)."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                with open(file_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('file', f, filename=os.path.basename(file_path))
                    
                    async with session.post('https://tmpfiles.org/api/v1/upload', data=data) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            if result.get('status') == 'success':
                                # Convert URL ke direct link
                                url = result['data']['url']
                                # https://tmpfiles.org/123/file.mp3 -> https://tmpfiles.org/dl/123/file.mp3
                                direct_url = url.replace('tmpfiles.org/', 'tmpfiles.org/dl/')
                                return direct_url
                        return None
        except Exception as e:
            logger.error(f"tmpfiles.org error: {e}")
            return None

    async def try_upload_to_hosts(self, file_path: str, status_msg: discord.Message):
        """Mencoba upload ke berbagai hosting. Prioritas: Top4Top > 0x0.st > File.io > tmpfiles."""
        hosts = [
            ("Top4Top.io", self.upload_to_top4top, "✅ Paling stabil untuk SAMP"),
            ("0x0.st", self.upload_to_0x0, "⏰ Expire: 365 hari"),
            ("File.io", self.upload_to_fileio, "⏰ Expire: 14 hari"),
            ("tmpfiles.org", self.upload_to_tmpfiles, "⚠️ Expire: 1 jam (cepat tapi sementara)")
        ]
        
        for host_name, upload_func, note in hosts:
            try:
                await status_msg.edit(content=f"⬆️ Mengupload ke **{host_name}**... {note}")
                link = await upload_func(file_path)
                if link:
                    return link, host_name
            except Exception as e:
                logger.error(f"Failed to upload to {host_name}: {e}")
                continue
        
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

    def get_spotify_track_info(self, url: str) -> Optional[dict]:
        """Mengambil info track dari Spotify untuk search di YouTube."""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,  # Tidak download, hanya ambil metadata
                'skip_download': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    # Spotify bisa return format berbeda
                    artist = info.get('artist') or info.get('uploader') or info.get('channel', '')
                    title = info.get('track') or info.get('title', '')
                    
                    # Jika masih kosong, coba parse dari entries (playlist)
                    if not title and 'entries' in info and info['entries']:
                        first_track = info['entries'][0]
                        artist = first_track.get('artist') or first_track.get('uploader', '')
                        title = first_track.get('track') or first_track.get('title', '')
                    
                    if title:
                        search_query = f"{artist} {title}".strip() if artist else title
                        return {
                            'search_query': search_query,
                            'title': title,
                            'artist': artist
                        }
        except Exception as e:
            logger.error(f"Error getting Spotify info: {e}", exc_info=True)
        return None

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
        
        # Deteksi jika link Spotify
        is_spotify = 'spotify.com' in url.lower()
        search_query = None
        
        if is_spotify:
            await processing_msg.edit(content="🔍 **Mendeteksi lagu Spotify...**")
            spotify_info = await loop.run_in_executor(None, lambda: self.get_spotify_track_info(url))
            if spotify_info:
                search_query = f"ytsearch:{spotify_info['search_query']}"
                await processing_msg.edit(content=f"🔎 **Mencari di YouTube:** `{spotify_info['search_query']}`")
            else:
                return await processing_msg.edit(content="❌ Gagal mendapatkan info dari Spotify. Pastikan link valid.")
        
        # Jika Spotify, gunakan search query. Jika YouTube, gunakan URL langsung
        download_url = search_query if is_spotify else url
        
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
            if is_spotify:
                await processing_msg.edit(content="⏬ **Mengunduh dari YouTube...**")
            else:
                await processing_msg.edit(content="⏬ **Mengunduh audio...**")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(download_url, download=True))
                filename = f"temp/{ctx.message.id}.mp3"

            if not os.path.exists(filename):
                raise FileNotFoundError("File MP3 tidak ditemukan setelah proses unduh.")

            file_title = info.get('title', 'Unknown')
            file_size = os.path.getsize(filename) / (1024 * 1024)  # MB
            
            # Cek ukuran file 
            if file_size > 50:
                await processing_msg.edit(content=f"❌ **File terlalu besar** ({file_size:.1f}MB).\n📌 Maksimal **50MB** untuk hosting gratis.")
                return
            
            # Warning jika file besar
            size_warning = ""
            if file_size > 25:
                size_warning = "\n⚠️ File besar, upload mungkin lambat..."
                await processing_msg.edit(content=f"⏬ **Selesai download** ({file_size:.1f}MB){size_warning}")

            # 3. Upload ke hosting
            stream_link, host_used = await self.try_upload_to_hosts(filename, processing_msg)
            
            if not stream_link:
                await processing_msg.edit(content="❌ Gagal mengupload ke semua hosting. Coba lagi nanti.")
                return

            # 4. Kirim hasil ke channel
            source_text = "🎵 Spotify → YouTube" if is_spotify else "🎵 YouTube"
            
            # Emoji dan warna berdasarkan host
            host_emoji = {
                "Top4Top.io": "🟢",
                "0x0.st": "🔵", 
                "File.io": "🟡",
                "tmpfiles.org": "🟠"
            }
            
            embed = discord.Embed(
                title=f"{host_emoji.get(host_used, '✅')} Link Streaming Berhasil!",
                description=f"**{file_title}**",
                color=0x1DB954 if is_spotify else 0xFF0000
            )
            
            # Info tambahan berdasarkan host
            expire_info = ""
            if host_used == "tmpfiles.org":
                expire_info = "\n⚠️ **Link expire dalam 1 jam!**"
            elif host_used == "File.io":
                expire_info = "\n⏰ Link expire dalam 14 hari"
            elif host_used == "0x0.st":
                expire_info = "\n⏰ Link expire dalam 365 hari"
            elif host_used == "Top4Top.io":
                expire_info = "\n✅ Link permanent"
            
            embed.add_field(
                name="📊 Info File", 
                value=f"Ukuran: **{file_size:.2f} MB**\nHost: **{host_used}**{expire_info}", 
                inline=False
            )
            embed.add_field(name="🔗 Link Streaming", value=f"```{stream_link}```", inline=False)
            embed.add_field(
                name="📝 Cara Pakai di GTA SAMP",
                value=(
                    "**Ghettoblaster/Boombox:**\n"
                    "• Ambil boombox dari inventory\n"
                    "• Ketik: `/playurl` atau `/radio`\n"
                    "• Paste link di atas\n\n"
                    "**Vehicle Radio:**\n"
                    "• Masuk mobil\n"
                    "• Ketik: `/vradio` (tergantung server)\n"
                    "• Paste link"
                ),
                inline=False
            )
            embed.set_footer(text=f"Diminta oleh {ctx.author.display_name} | Source: {source_text}")
            
            await upload_channel.send(
                content=f"🎵 {ctx.author.mention} **Link siap!**\n{stream_link}",
                embed=embed
            )
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
