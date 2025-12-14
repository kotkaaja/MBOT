import discord
from discord import app_commands
from discord.ext import commands
from discord import ui
import logging
import asyncio
from utils.database import (
    set_rating_log_channel, get_rating_log_channel, 
    add_rating, get_rating_stats, get_all_ratings, update_rating_image
)

logger = logging.getLogger(__name__)

# --- 1. MODAL (Popup Input) ---
class RatingModal(ui.Modal):
    def __init__(self, topic, stars, bot, panel_message: discord.Message):
        super().__init__(title=f"⭐ Ulasan: {topic}")
        self.topic = topic
        self.stars = stars
        self.bot = bot
        self.panel_message = panel_message

        self.comment = ui.TextInput(
            label=f"Berikan Komentar ({stars}/5)",
            style=discord.TextStyle.paragraph,
            placeholder="Tulis ulasan jujur Anda di sini...",
            required=True,
            max_length=1000
        )
        self.add_item(self.comment)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        
        # 1. Simpan Data Awal (Teks dulu)
        if add_rating(user_id, self.topic, self.stars, self.comment.value):
            
            # 2. Update Panel Real-time (Sementara)
            await self.update_panel_display()
            
            # 3. Minta Gambar (Flow Upload)
            await interaction.response.send_message(
                "✅ **Ulasan teks disimpan!**\n"
                "📸 Apakah Anda ingin melampirkan bukti gambar/screenshot?\n"
                "👉 **Kirim gambar sekarang di chat ini** (Anda punya waktu 60 detik).\n"
                "👉 Atau abaikan pesan ini jika tidak ingin mengirim gambar.",
                ephemeral=True
            )

            # 4. Tunggu User Mengirim Gambar
            def check(m):
                return m.author.id == user_id and m.channel.id == interaction.channel.id and m.attachments

            image_url = None
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=60.0)
                # Ambil attachment pertama
                if msg.attachments:
                    image_url = msg.attachments[0].url
                    # Update database dengan URL gambar
                    update_rating_image(user_id, self.topic, image_url)
                    
                    # Hapus pesan user agar chat bersih (opsional, butuh manage_messages)
                    try: await msg.delete()
                    except: pass
                    
                    await interaction.followup.send("✅ **Gambar berhasil ditambahkan!**", ephemeral=True)
            except asyncio.TimeoutError:
                pass # Tidak kirim gambar, lanjut saja

            # 5. Update Log Admin (Sekarang sudah final dengan atau tanpa gambar)
            await self.send_admin_log(interaction, image_url)
            
            # 6. Update Panel lagi (untuk memastikan sinkron jika ada delay)
            await self.update_panel_display()

        else:
            await interaction.response.send_message("❌ Gagal menyimpan ulasan (DB Error).", ephemeral=True)

    async def update_panel_display(self):
        """Helper untuk update tampilan panel rating."""
        if not self.panel_message: return
        avg, count = get_rating_stats(self.topic)
        try:
            embed = self.panel_message.embeds[0]
            field_found = False
            for i, field in enumerate(embed.fields):
                if "Statistik" in field.name:
                    embed.set_field_at(i, name=field.name, value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
                    field_found = True
                    break
            if not field_found:
                 embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
            await self.panel_message.edit(embed=embed)
        except Exception as e:
            logger.warning(f"Gagal update panel: {e}")

    async def send_admin_log(self, interaction, image_url):
        log_id = get_rating_log_channel(interaction.guild.id)
        if log_id:
            channel = self.bot.get_channel(log_id)
            if channel:
                avg, count = get_rating_stats(self.topic)
                color = discord.Color.green() if self.stars >= 4 else discord.Color.red()
                embed_log = discord.Embed(title=f"📝 Ulasan Baru: {self.topic}", color=color, timestamp=discord.utils.utcnow())
                embed_log.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
                embed_log.set_thumbnail(url=interaction.user.display_avatar.url)
                
                embed_log.add_field(name="Nilai", value=f"{'⭐' * self.stars} **({self.stars}/5)**", inline=False)
                embed_log.add_field(name="Komentar", value=f"```\n{self.comment.value}\n```", inline=False)
                
                if image_url:
                    embed_log.set_image(url=image_url)
                    embed_log.add_field(name="Lampiran", value="[Lihat Gambar](" + image_url + ")", inline=False)

                embed_log.set_footer(text=f"Total: {count} Ulasan | Rata-rata: {avg}")
                await channel.send(embed=embed_log)

# --- 2. MAIN COG ---
class RatingSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Listener Tombol
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component: return
        cid = interaction.data.get("custom_id", "")

        # A. Handler Tombol Bintang (rate:TOPIK:BINTANG:ROLE_ID)
        if cid.startswith("rate:"):
            try:
                parts = cid.split(":")
                topic = parts[1]
                stars = int(parts[2])
                # parts[3] adalah Role ID (atau "0" jika semua boleh)
                role_id_req = int(parts[3]) if len(parts) > 3 else 0

                # --- CEK PERMISSION ROLE ---
                if role_id_req != 0:
                    user_role_ids = [r.id for r in interaction.user.roles]
                    if role_id_req not in user_role_ids:
                        # Cek apakah user admin (opsional, tapi bagus untuk bypass)
                        if not interaction.user.guild_permissions.administrator:
                            required_role = interaction.guild.get_role(role_id_req)
                            role_name = required_role.name if required_role else "Unknown Role"
                            await interaction.response.send_message(f"❌ Maaf, Anda memerlukan role **{role_name}** untuk memberikan rating di sini.", ephemeral=True)
                            return
                # ---------------------------

                await interaction.response.send_modal(RatingModal(topic, stars, self.bot, interaction.message))
            except Exception as e:
                logger.error(f"Error tombol rating: {e}")
                await interaction.response.send_message("❌ Terjadi kesalahan.", ephemeral=True)

        # B. Handler Tombol Lihat Ulasan (see_reviews:TOPIK)
        elif cid.startswith("see_reviews:"):
            try:
                topic = cid.split(":")[1]
                await interaction.response.defer(ephemeral=True)

                ratings = get_all_ratings(topic)
                avg, count = get_rating_stats(topic)

                if not ratings:
                    await interaction.followup.send(f"📭 Belum ada ulasan untuk topik **{topic}**.", ephemeral=True)
                    return

                embed = discord.Embed(title=f"📋 Daftar Ulasan: {topic}", description=f"**Rata-rata:** ⭐ {avg}/5.0 | **Total:** {count} Ulasan", color=discord.Color.blue())
                
                limit = 8 # Limit agar tidak kepanjangan
                for r in ratings[:limit]:
                    user_id, stars, comment, created_at, image_url = r # Unpack image_url
                    user = interaction.guild.get_member(user_id)
                    name = user.display_name if user else f"User {user_id}"
                    date_str = created_at.strftime("%d/%m/%Y")
                    
                    text_val = f"{comment[:150]}"
                    if image_url:
                        text_val += f"\n🖼️ [Lihat Bukti]({image_url})"
                    
                    embed.add_field(
                        name=f"{'⭐' * stars} - {name} ({date_str})",
                        value=text_val,
                        inline=False
                    )
                
                if len(ratings) > limit:
                    embed.set_footer(text=f"Dan {len(ratings) - limit} ulasan lainnya...")
                
                await interaction.followup.send(embed=embed, ephemeral=True)

            except Exception as e:
                logger.error(f"Error tombol lihat ulasan: {e}")
                await interaction.followup.send("❌ Gagal memuat ulasan.", ephemeral=True)

    @app_commands.command(name="config_rating_log", description="Atur channel untuk laporan rating masuk.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_rating_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if set_rating_log_channel(interaction.guild.id, channel.id):
            await interaction.response.send_message(f"✅ Laporan rating akan dikirim ke {channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Gagal menyimpan konfigurasi.", ephemeral=True)

    # Command Updated: Tambah parameter 'required_role'
    @app_commands.command(name="create_rating_panel", description="Buat panel rating dengan statistik dan tombol ulasan.")
    @app_commands.describe(
        topik="Topik (cth: admin, server)",
        judul="Judul Embed",
        deskripsi="Isi pesan",
        gambar="Banner (Opsional)",
        required_role="Role khusus yang boleh memberi rating (Kosongkan jika semua boleh)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def create_rating_panel(self, interaction: discord.Interaction, topik: str, judul: str, deskripsi: str, gambar: discord.Attachment = None, required_role: discord.Role = None):
        avg, count = get_rating_stats(topik)

        embed = discord.Embed(title=judul, description=deskripsi, color=0xf1c40f)
        if gambar: embed.set_image(url=gambar.url)
        
        embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
        
        # Info Role Permission
        role_id_str = "0"
        footer_text = f"Topik: {topik}"
        if required_role:
            role_id_str = str(required_role.id)
            footer_text += f" | Khusus Role: {required_role.name}"
        
        embed.set_footer(text=footer_text)

        view = ui.View(timeout=None)
        
        # ID Button Format: rate:TOPIK:BINTANG:ROLE_ID
        for i in range(1, 6):
            view.add_item(ui.Button(label=str(i), emoji="⭐", custom_id=f"rate:{topik}:{i}:{role_id_str}", style=discord.ButtonStyle.secondary, row=0))
        
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
