import discord
from discord import app_commands
from discord.ext import commands
import logging
import json

logger = logging.getLogger(__name__)

class MessageSenderCog(commands.Cog, name="MessageSender"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="create_message", description="Kirim pesan/embed ala Discohook. Paste JSON di 'json_input'.")
    @app_commands.describe(
        json_input="Paste teks JSON (Format Discohook) di sini",
        image="Upload gambar banner (Opsional, akan menimpa gambar di JSON)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def create_message(self, interaction: discord.Interaction, json_input: str, image: discord.Attachment = None):
        """
        Mengirim pesan berdasarkan input JSON. Support format Discohook.
        """
        await interaction.response.defer(ephemeral=True)

        try:
            # 1. Parsing JSON
            data = json.loads(json_input)
            
            # 2. Ambil Content (Teks biasa di luar embed)
            content = data.get('content', None)

            # 3. Ambil Data Embed
            # Discohook biasanya membungkus dalam list "embeds": [{...}]
            embed_data = None
            if 'embeds' in data and isinstance(data['embeds'], list) and len(data['embeds']) > 0:
                embed_data = data['embeds'][0] # Kita ambil embed pertama saja
            elif 'embed' in data:
                embed_data = data['embed'] # Support format single object juga

            embed = None
            if embed_data:
                # Warna: Support integer atau hex string (misal "#ffffff")
                color_val = embed_data.get('color', 0x2b2d31)
                if isinstance(color_val, str):
                    if color_val.startswith('#'): color_val = int(color_val[1:], 16)
                    else: color_val = int(color_val)

                embed = discord.Embed(
                    title=embed_data.get('title'),
                    description=embed_data.get('description'),
                    url=embed_data.get('url'),
                    color=color_val
                )

                # Author
                if 'author' in embed_data:
                    auth = embed_data['author']
                    embed.set_author(
                        name=auth.get('name'), 
                        url=auth.get('url'), 
                        icon_url=auth.get('icon_url')
                    )

                # Footer
                if 'footer' in embed_data:
                    foot = embed_data['footer']
                    embed.set_footer(
                        text=foot.get('text'), 
                        icon_url=foot.get('icon_url')
                    )

                # Thumbnail
                if 'thumbnail' in embed_data:
                    embed.set_thumbnail(url=embed_data['thumbnail'].get('url'))

                # Fields
                if 'fields' in embed_data:
                    for field in embed_data['fields']:
                        embed.add_field(
                            name=field.get('name', '\u200b'),
                            value=field.get('value', '\u200b'),
                            inline=field.get('inline', False)
                        )

                # Image (Banner)
                # Prioritas: Upload Manual di Discord > URL di JSON
                if image:
                    embed.set_image(url=image.url)
                elif 'image' in embed_data:
                    # Discohook format: "image": {"url": "..."}
                    img_url = embed_data['image'].get('url') if isinstance(embed_data['image'], dict) else embed_data['image']
                    embed.set_image(url=img_url)
            
            # Jika user cuma kirim gambar tanpa embed/text
            if not content and not embed and image:
                # Bikin embed kosong buat wadah gambar doang atau kirim sebagai attachment biasa?
                # Kita kirim sebagai file biasa kalau ga ada embed
                pass # Logic di bawah handle send

            # 4. Kirim Pesan
            if content or embed or image:
                # Jika ada embed, kirim embed. Jika gambar diupload tapi ga masuk embed, jadi attachment terpisah?
                # Skenario: User upload gambar buat banner embed -> sudah dihandle di atas (embed.set_image).
                
                # Skenario: User upload gambar TAPI json ga pake embed (cuma content text)
                if not embed and image:
                     await interaction.channel.send(content=content, file=await image.to_file())
                else:
                    await interaction.channel.send(content=content, embed=embed)
                
                await interaction.followup.send("✅ Pesan terkirim!", ephemeral=True)
            else:
                await interaction.followup.send("❌ JSON kosong? Minimal harus ada 'content' atau 'embeds'.", ephemeral=True)

        except json.JSONDecodeError:
            await interaction.followup.send("❌ Format JSON salah/rusak. Cek tanda kurung dan koma.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error create_message: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MessageSenderCog(bot))
