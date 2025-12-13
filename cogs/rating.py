import discord
from discord import app_commands
from discord.ext import commands
from discord import ui
import logging
from utils.database import (
    set_rating_log_channel, get_rating_log_channel, 
    add_rating, get_rating_stats, get_all_ratings
)

logger = logging.getLogger(__name__)

# --- 1. MODAL (Popup Input) ---
class RatingModal(ui.Modal):
    def __init__(self, topic, stars, bot, panel_message: discord.Message):
        super().__init__(title=f"⭐ Ulasan: {topic}")
        self.topic = topic
        self.stars = stars
        self.bot = bot
        self.panel_message = panel_message # Menyimpan pesan panel untuk di-edit

        self.comment = ui.TextInput(
            label=f"Berikan Komentar ({stars}/5)",
            style=discord.TextStyle.paragraph,
            placeholder="Tulis ulasan jujur Anda di sini...",
            required=True,
            max_length=1000
        )
        self.add_item(self.comment)

    async def on_submit(self, interaction: discord.Interaction):
        # 1. Simpan ke Database
        if add_rating(interaction.user.id, self.topic, self.stars, self.comment.value):
            
            # 2. Ambil Statistik Baru (Real-time update)
            avg, count = get_rating_stats(self.topic)

            # 3. UPDATE PANEL EMBED OTOMATIS
            if self.panel_message:
                try:
                    embed = self.panel_message.embeds[0]
                    # Update Field "Statistik"
                    field_found = False
                    for i, field in enumerate(embed.fields):
                        if "Statistik" in field.name: # Cari field statistik
                            embed.set_field_at(
                                i, 
                                name=field.name, 
                                value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", 
                                inline=False
                            )
                            field_found = True
                            break
                    
                    # Jika field statistik entah kenapa hilang, buat baru (fallback)
                    if not field_found:
                         embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)

                    await self.panel_message.edit(embed=embed)
                except Exception as e:
                    logger.warning(f"Gagal update panel real-time: {e}")

            # 4. Kirim Log ke Channel Admin (jika diatur)
            log_id = get_rating_log_channel(interaction.guild.id)
            if log_id:
                channel = self.bot.get_channel(log_id)
                if channel:
                    color = discord.Color.green() if self.stars >= 4 else discord.Color.red()
                    embed_log = discord.Embed(title=f"📝 Ulasan Baru: {self.topic}", color=color, timestamp=discord.utils.utcnow())
                    embed_log.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
                    embed_log.set_thumbnail(url=interaction.user.display_avatar.url)
                    
                    embed_log.add_field(name="Nilai", value=f"{'⭐' * self.stars} **({self.stars}/5)**", inline=False)
                    embed_log.add_field(name="Komentar", value=f"```\n{self.comment.value}\n```", inline=False)
                    embed_log.set_footer(text=f"Total: {count} Ulasan | Rata-rata: {avg}")
                    
                    await channel.send(embed=embed_log)

            await interaction.response.send_message(f"✅ Terima kasih! Panel rating telah diperbarui menjadi **{avg}/5.0**.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Gagal menyimpan ulasan (DB Error).", ephemeral=True)

# --- 2. MAIN COG ---
class RatingSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Listener Tombol (Menangani klik tombol tanpa perlu restart view)
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component: return
        cid = interaction.data.get("custom_id", "")

        # A. Handler Tombol Bintang (rate:TOPIK:BINTANG)
        if cid.startswith("rate:"):
            try:
                parts = cid.split(":")
                topic = parts[1]
                stars = int(parts[2])
                # Kirim pesan panel (interaction.message) ke modal agar bisa di-edit
                await interaction.response.send_modal(RatingModal(topic, stars, self.bot, interaction.message))
            except Exception as e:
                logger.error(f"Error tombol rating: {e}")
                await interaction.response.send_message("❌ Terjadi kesalahan.", ephemeral=True)

        # B. Handler Tombol Lihat Ulasan (see_reviews:TOPIK)
        elif cid.startswith("see_reviews:"):
            try:
                topic = cid.split(":")[1]
                await interaction.response.defer(ephemeral=True) # Loading sebentar

                ratings = get_all_ratings(topic)
                avg, count = get_rating_stats(topic)

                if not ratings:
                    await interaction.followup.send(f"📭 Belum ada ulasan untuk topik **{topic}**.", ephemeral=True)
                    return

                # Buat Embed Daftar Ulasan
                embed = discord.Embed(title=f"📋 Daftar Ulasan: {topic}", description=f"**Rata-rata:** ⭐ {avg}/5.0 | **Total:** {count} Ulasan", color=discord.Color.blue())
                
                # Limit tampilan (Discord limit 25 field), tampilkan 10 terbaru
                limit = 10
                for r in ratings[:limit]:
                    user_id, stars, comment, created_at = r
                    # Coba ambil nama user, kalau keluar server pakai ID
                    user = interaction.guild.get_member(user_id)
                    name = user.display_name if user else f"User ID: {user_id}"
                    
                    date_str = created_at.strftime("%d/%m/%Y")
                    embed.add_field(
                        name=f"{'⭐' * stars} - {name} ({date_str})",
                        value=f"{comment[:200]}", # Potong jika komentar terlalu panjang
                        inline=False
                    )
                
                if len(ratings) > limit:
                    embed.set_footer(text=f"Dan {len(ratings) - limit} ulasan lainnya...")
                
                await interaction.followup.send(embed=embed, ephemeral=True)

            except Exception as e:
                logger.error(f"Error tombol lihat ulasan: {e}")
                await interaction.followup.send("❌ Gagal memuat ulasan.", ephemeral=True)


    # Command 1: Setup Log Channel
    @app_commands.command(name="config_rating_log", description="Atur channel untuk laporan rating masuk.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_rating_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if set_rating_log_channel(interaction.guild.id, channel.id):
            await interaction.response.send_message(f"✅ Laporan rating akan dikirim ke {channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Gagal menyimpan konfigurasi.", ephemeral=True)

    # Command 2: Buat Panel Rating (Update Tombol)
    @app_commands.command(name="create_rating_panel", description="Buat panel rating dengan statistik dan tombol ulasan.")
    @app_commands.describe(
        topik="Topik (cth: admin, server)",
        judul="Judul Embed",
        deskripsi="Isi pesan",
        gambar="Banner (Opsional)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def create_rating_panel(self, interaction: discord.Interaction, topik: str, judul: str, deskripsi: str, gambar: discord.Attachment = None):
        avg, count = get_rating_stats(topik)

        embed = discord.Embed(title=judul, description=deskripsi, color=0xf1c40f)
        if gambar: embed.set_image(url=gambar.url)
        
        # Field Statistik (Penting: Format ini dibaca oleh Modal untuk update)
        embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
        embed.set_footer(text=f"Topik: {topik}")

        view = ui.View(timeout=None)
        
        # Baris 1: Tombol Bintang 1-5
        for i in range(1, 6):
            view.add_item(ui.Button(label=str(i), emoji="⭐", custom_id=f"rate:{topik}:{i}", style=discord.ButtonStyle.secondary, row=0))
        
        # Baris 2: Tombol Lihat Ulasan (NEW)
        view.add_item(ui.Button(
            label="Lihat Semua Ulasan", 
            emoji="📜", 
            custom_id=f"see_reviews:{topik}", 
            style=discord.ButtonStyle.primary, 
            row=1
        ))

        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Panel Rating **{topik}** berhasil dibuat!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(RatingSystem(bot))
