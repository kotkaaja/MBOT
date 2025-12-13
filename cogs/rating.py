import discord
from discord import app_commands
from discord.ext import commands
from discord import ui
import logging
from utils.database import set_rating_log_channel, get_rating_log_channel, add_rating, get_rating_stats

logger = logging.getLogger(__name__)

# --- 1. MODAL (Popup Input Komentar) ---
class RatingModal(ui.Modal):
    def __init__(self, topic, stars, bot):
        super().__init__(title=f"⭐ Ulasan: {topic}")
        self.topic = topic
        self.stars = stars
        self.bot = bot

        self.comment = ui.TextInput(
            label=f"Berikan Komentar ({stars}/5)",
            style=discord.TextStyle.paragraph,
            placeholder="Tulis ulasan Anda di sini...",
            required=True,
            max_length=1000
        )
        self.add_item(self.comment)

    async def on_submit(self, interaction: discord.Interaction):
        # Simpan Database
        if add_rating(interaction.user.id, self.topic, self.stars, self.comment.value):
            
            # Kirim Log ke Channel Admin (Tampilan Webhook)
            log_id = get_rating_log_channel(interaction.guild.id)
            if log_id:
                channel = self.bot.get_channel(log_id)
                if channel:
                    avg, count = get_rating_stats(self.topic)
                    
                    # Warna indikator
                    color = discord.Color.green() if self.stars >= 4 else discord.Color.red()
                    
                    embed = discord.Embed(title=f"📝 Ulasan Baru: {self.topic}", color=color, timestamp=discord.utils.utcnow())
                    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
                    embed.set_thumbnail(url=interaction.user.display_avatar.url)
                    
                    embed.add_field(name="Nilai", value=f"{'⭐' * self.stars} **({self.stars}/5)**", inline=False)
                    embed.add_field(name="Komentar", value=f"```\n{self.comment.value}\n```", inline=False)
                    embed.set_footer(text=f"Total: {count} Ulasan | Rata-rata: {avg}")
                    
                    await channel.send(embed=embed)

            await interaction.response.send_message("✅ Ulasan Anda telah terkirim!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Gagal menyimpan ulasan (DB Error).", ephemeral=True)

# --- 2. MAIN COG ---
class RatingSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Listener Tombol (Agar tidak mati saat restart)
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component: return
        cid = interaction.data.get("custom_id", "")

        # Format ID: rate:TOPIK:BINTANG
        if cid.startswith("rate:"):
            try:
                parts = cid.split(":")
                topic = parts[1]
                stars = int(parts[2])
                await interaction.response.send_modal(RatingModal(topic, stars, self.bot))
            except:
                await interaction.response.send_message("❌ Terjadi kesalahan pada tombol.", ephemeral=True)

    # Command 1: Setup Log
    @app_commands.command(name="config_rating_log", description="Atur channel untuk laporan rating masuk.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_rating_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if set_rating_log_channel(interaction.guild.id, channel.id):
            await interaction.response.send_message(f"✅ Laporan rating akan dikirim ke {channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Gagal menyimpan konfigurasi.", ephemeral=True)

    # Command 2: Buat Panel Rating
    @app_commands.command(name="create_rating_panel", description="Buat panel rating dengan statistik dan tombol.")
    @app_commands.describe(
        topik="Topik (cth: Admin, Server)",
        judul="Judul Embed",
        deskripsi="Isi pesan",
        gambar="Banner (Opsional)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def create_rating_panel(self, interaction: discord.Interaction, topik: str, judul: str, deskripsi: str, gambar: discord.Attachment = None):
        avg, count = get_rating_stats(topik)

        embed = discord.Embed(title=judul, description=deskripsi, color=0xf1c40f)
        if gambar: embed.set_image(url=gambar.url)
        
        embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
        embed.set_footer(text=f"Topik: {topik}")

        view = ui.View(timeout=None)
        for i in range(1, 6):
            view.add_item(ui.Button(label=str(i), emoji="⭐", custom_id=f"rate:{topik}:{i}", style=discord.ButtonStyle.secondary))

        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Panel Rating **{topik}** berhasil dibuat!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(RatingSystem(bot))
