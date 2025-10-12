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
        """Upload ke Top4Top."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                with open(file_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('file_1_', f, filename=os.path.basename(file_path))
                    data.add_field('submitr', '[ رفع الملفات ]')
                    
                    async with session.post('https://top4top.io/uploadfile', data=data) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            import re
                            patterns = [
                                r'https://[a-z0-9-]+\.top4top\.io/mp3_[^\s"\'<>]+\.mp3',
                                r'https://[a-z0-9-]+\.top4top\.io/m_[^\s"\'<>]+\.mp3',
                                r'https://[a-z0-9-]+\.top4top\.io/[^\s"\'<>]+\.mp3'
                            ]
                            for pattern in patterns:
                                match = re.search(pattern, text)
                                if match:
                                    return match.group(0)
        except Exception as e:
            logger.error(f"Top4Top error: {e}")
        return None

    async def upload_to_0x0(self, file_path: str) -> Optional[str]:
        """Upload ke 0x0.st."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                with open(file_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('file', f, filename=os.path.basename(file_path))
                    
                    async with session.post('https://0x0.st', data=data) as resp:
                        if resp.status == 200:
                            return (await resp.text()).strip()
        except Exception as e:
            logger.error(f"0x0.st error: {e}")
        return None

    async def upload_to_fileio(self, file_path: str) -> Optional[str]:
        """Upload ke File.io."""
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
        except Exception as e:
            logger.error(f"File.io error: {e}")
        return None

    @commands.command(name="setuploadchannel")
    @commands.has_permissions(administrator=True)
    async def setup_upload_channel(self, ctx, channel: discord.TextChannel):
        """Atur channel untuk link streaming."""
        from utils.database import set_upload_channel
        
        if set_upload_channel(ctx.guild.id, channel.id):
            await ctx.send(f"✅ Channel diatur ke {channel.mention}")
        else:
            await ctx.send("❌ Gagal menyimpan ke database.")

    @commands.command(name="convert")
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def convert_command(self, ctx, *, url: str):
        """Convert YouTube jadi link streaming."""
        # Cek channel
        upload_channel_id = get_upload_channel(ctx.guild.id)
        if not upload_channel_id:
            return await ctx.send("❌ Channel belum diatur. Admin ketik `!setuploadchannel #channel`")

        upload_channel = self.bot.get_channel(upload_channel_id)
        if not upload_channel:
            return await ctx.send(f"❌ Channel tidak ditemukan.")

        msg = await ctx.send(f"⏬ Downloading...")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
            'outtmpl': f'temp/{ctx.message.id}',
            'quiet': True,
            'no_warnings': True,
        }
        
        filename = None
        try:
            loop = asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            
            filename = f"temp/{ctx.message.id}.mp3"
            if not os.path.exists(filename):
                return await msg.edit(content="❌ File tidak ditemukan.")

            title = info.get('title', 'Unknown')
            size_mb = os.path.getsize(filename) / (1024 * 1024)
            
            if size_mb > 50:
                return await msg.edit(content=f"❌ File terlalu besar ({size_mb:.1f}MB). Max 50MB.")

            # Upload
            await msg.edit(content="⬆️ Uploading...")
            
            link = await self.upload_to_top4top(filename)
            host = "Top4Top"
            
            if not link:
                link = await self.upload_to_0x0(filename)
                host = "0x0.st"
            
            if not link:
                link = await self.upload_to_fileio(filename)
                host = "File.io"
            
            if not link:
                return await msg.edit(content="❌ Semua hosting gagal.")

            # Kirim hasil
            await upload_channel.send(f"🎵 **{title}**\n{link}\n\nDiminta: {ctx.author.mention} | Host: {host}")
            await msg.edit(content=f"✅ Link dikirim ke {upload_channel.mention}")

        except Exception as e:
            logger.error(f"Convert error: {e}")
            await msg.edit(content=f"❌ Error: {str(e)[:100]}")
        finally:
            if filename and os.path.exists(filename):
                try:
                    os.remove(filename)
                except:
                    pass

async def setup(bot):
    if not os.path.exists('temp'):
        os.makedirs('temp')
    await bot.add_cog(ConverterCog(bot))
