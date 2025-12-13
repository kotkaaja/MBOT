import discord
from discord import app_commands
from discord.ext import commands
from discord import ui
import logging
from utils.database import (
    set_rating_log_channel, get_rating_log_channel, 
    add_rating, get_rating_stats
)

logger = logging.getLogger(__name__)

# ====================================================
# 1. UI COMPONENTS
# ====================================================

class RatingModal(ui.Modal):
    def __init__(self, topic, stars, bot):
        super().__init__(title=f"⭐ Berikan Ulasan ({stars}/5)")
        self.topic = topic
        self.stars = stars
        self.bot = bot

        self.comment = ui.TextInput(
            label="Komentar / Pesan",
            style=discord.TextStyle.paragraph,
            placeholder="Tulis ulasanmu di sini...",
            required=True,
            max_length=1000
        )
        self.add_item(self.comment)

    async def on_submit(self, interaction: discord.Interaction):
        # Simpan ke DB
        if add_rating(interaction.user.id, self.topic, self.stars, self.comment.value):
            # 1. Kirim Log ke Channel (GAYA DISCOOHOOK / WEBHOOK)
            log_id = get_rating_log_channel(interaction.guild.id)
            if log_id:
                channel = self.bot.get_channel(log_id)
                if channel:
                    # Hitung stats baru
                    avg, count = get_rating_stats(self.topic)
                    
                    # Bikin Embed Log yang Cantik
                    embed = discord.Embed(
                        title=f"New Review: {self.topic}",
                        color=discord.Color.gold() if self.stars >= 4 else discord.Color.red(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
                    embed.set_thumbnail(url=interaction.user.display_avatar.url)
                    
                    stars_str = "⭐" * self.stars
                    embed.add_field(name="Rating", value=f"{stars_str} **({self.stars}/5)**", inline=False)
                    embed.add_field(name="Review", value=f"```\n{self.comment.value}\n```", inline=False)
                    embed.set_footer(text=f"Total: {count} Reviews | Avg: {avg}/5.0")
                    
                    await channel.send(embed=embed)

            # 2. Respon ke User (Ephemeral)
            await interaction.response.send_message("✅ Ulasan kamu berhasil dikirim! Terima kasih.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Database error. Coba lagi nanti.", ephemeral=True)

class DynamicRoleSelect(ui.Select):
    def __init__(self, placeholder="Pilih Role...", options=None):
        safe_options = options if options else [discord.SelectOption(label="Loading...", value="dummy")]
        super().__init__(placeholder=placeholder, min_values=0, max_values=1, options=safe_options, custom_id="dynamic_role_select")

    async def callback(self, interaction: discord.Interaction):
        # Ambil opsi yang valid (bukan dummy)
        valid_options = [opt for opt in self.options if opt.value.isdigit()]
        selected_ids = self.values
        
        added, removed = [], []

        for opt in valid_options:
            role_id = int(opt.value)
            role = interaction.guild.get_role(role_id)
            if not role: continue

            if opt.value in selected_ids:
                if role not in interaction.user.roles:
                    await interaction.user.add_roles(role); added.append(role.name)
            else:
                if role in interaction.user.roles:
                    await interaction.user.remove_roles(role); removed.append(role.name)
        
        if added: await interaction.response.send_message(f"✅ Role **{', '.join(added)}** ditambahkan.", ephemeral=True)
        elif removed: await interaction.response.send_message(f"❌ Role **{', '.join(removed)}** dilepas.", ephemeral=True)
        else: await interaction.response.send_message("Tidak ada perubahan.", ephemeral=True)

# ====================================================
# 2. MAIN LOGIC
# ====================================================

class DynamicSupportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def find_message(self, interaction, target: str):
        # Cari pesan berdasarkan Judul Embed di channel ini
        async for msg in interaction.channel.history(limit=50):
            if msg.author == interaction.guild.me and msg.embeds:
                if msg.embeds[0].title and msg.embeds[0].title.lower() == target.lower():
                    return msg
        return None

    # --- LISTENER TOMBOL (GLOBAL) ---
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component: return
        cid = interaction.data.get("custom_id", "")

        # Handler Verify
        if cid.startswith("verify:"):
            try:
                role = interaction.guild.get_role(int(cid.split(":")[1]))
                if role:
                    if role in interaction.user.roles:
                        await interaction.response.send_message("✅ Kamu sudah terverifikasi.", ephemeral=True)
                    else:
                        await interaction.user.add_roles(role)
                        await interaction.response.send_message(f"✅ Berhasil! Role **{role.name}** diberikan.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Role tidak ditemukan.", ephemeral=True)
            except:
                await interaction.response.send_message("❌ Error sistem verifikasi.", ephemeral=True)

        # Handler Rating (Buka Modal)
        elif cid.startswith("rate:"):
            try:
                parts = cid.split(":") # rate:Topik:Stars
                topic = parts[1]
                stars = int(parts[2])
                await interaction.response.send_modal(RatingModal(topic, stars, self.bot))
            except:
                await interaction.response.send_message("❌ Error membuka rating.", ephemeral=True)

    # --- COMMANDS ---

    @app_commands.command(name="create_embed", description="Buat embed ala Webhook/Discohook.")
    @app_commands.describe(
        judul="Judul utama (dipakai untuk target setup)",
        deskripsi="Isi pesan utama",
        warna="Warna HEX (cth: FF0000)",
        gambar="Gambar besar di bawah (Opsional)",
        thumbnail="Gambar kecil di pojok kanan (Opsional)",
        footer="Tulisan kecil di bawah (Opsional)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def create_embed(self, interaction: discord.Interaction, judul: str, deskripsi: str, warna: str = "2b2d31", gambar: discord.Attachment = None, thumbnail: discord.Attachment = None, footer: str = None):
        try: color = int(warna.replace("#", ""), 16)
        except: color = 0x2b2d31

        embed = discord.Embed(title=judul, description=deskripsi, color=color)
        if gambar: embed.set_image(url=gambar.url)
        if thumbnail: embed.set_thumbnail(url=thumbnail.url)
        if footer: embed.set_footer(text=footer)

        await interaction.channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Embed **{judul}** dibuat! Gunakan `/setup_...` untuk pasang tombol.", ephemeral=True)

    @app_commands.command(name="setup_verify", description="Pasang tombol Verify.")
    @app_commands.describe(target="Judul Embed yang mau dipasang", role="Role yang didapat", label="Tulisan tombol", emoji="Emoji")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_verify(self, interaction: discord.Interaction, target: str, role: discord.Role, label: str = "Verifikasi", emoji: str = "✅"):
        await interaction.response.defer(ephemeral=True)
        msg = await self.find_message(interaction, target)
        if not msg: return await interaction.followup.send(f"❌ Embed dengan judul **{target}** tidak ketemu.", ephemeral=True)

        view = ui.View.from_message(msg); view.timeout = None
        view.add_item(ui.Button(label=label, style=discord.ButtonStyle.success, emoji=emoji, custom_id=f"verify:{role.id}"))
        
        await msg.edit(view=view)
        await interaction.followup.send("✅ Tombol Verify dipasang.", ephemeral=True)

    @app_commands.command(name="setup_role", description="Pasang dropdown Select Role.")
    @app_commands.describe(target="Judul Embed", role="Role pilihan", label="Nama di menu", emoji="Emoji")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_role(self, interaction: discord.Interaction, target: str, role: discord.Role, label: str, emoji: str = "🔹"):
        await interaction.response.defer(ephemeral=True)
        msg = await self.find_message(interaction, target)
        if not msg: return await interaction.followup.send(f"❌ Embed **{target}** tidak ketemu.", ephemeral=True)

        view = ui.View.from_message(msg); view.timeout = None
        select = None
        for child in view.children:
            if isinstance(child, ui.Select) and child.custom_id == "dynamic_role_select":
                select = child; break
        
        if not select:
            select = DynamicRoleSelect(options=[]); view.add_item(select)

        # Update opsi
        opts = [o for o in select.options if o.value != "dummy"]
        if len(opts) >= 25: return await interaction.followup.send("❌ Menu penuh (max 25).", ephemeral=True)
        
        opts.append(discord.SelectOption(label=label, value=str(role.id), emoji=emoji))
        
        # Replace select lama dengan yang baru
        new_select = DynamicRoleSelect(options=opts); new_select.max_values = len(opts)
        for i, item in enumerate(view.children):
            if item.custom_id == "dynamic_role_select":
                view.children[i] = new_select; break
        else: view.add_item(new_select)

        await msg.edit(view=view)
        await interaction.followup.send(f"✅ Role **{label}** dimasukkan ke menu.", ephemeral=True)

    @app_commands.command(name="setup_rating", description="Pasang tombol Rating Bintang.")
    @app_commands.describe(target="Judul Embed", topik="Topik (cth: Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_rating(self, interaction: discord.Interaction, target: str, topik: str):
        await interaction.response.defer(ephemeral=True)
        msg = await self.find_message(interaction, target)
        if not msg: return await interaction.followup.send(f"❌ Embed **{target}** tidak ketemu.", ephemeral=True)

        view = ui.View.from_message(msg); view.timeout = None
        # Tambah 5 tombol bintang
        for i in range(1, 6):
            view.add_item(ui.Button(label=str(i), emoji="⭐", custom_id=f"rate:{topik}:{i}", style=discord.ButtonStyle.secondary))
        
        # Update tampilan embed dengan statistik
        avg, count = get_rating_stats(topik)
        embed = msg.embeds[0]
        stat_text = f"⭐ **{avg}/5.0**\n👤 {count} Ulasan"
        
        # Cek field statistik
        found = False
        for i, f in enumerate(embed.fields):
            if "Statistik" in f.name:
                embed.set_field_at(i, name="📊 Statistik", value=stat_text, inline=False)
                found = True; break
        if not found: embed.add_field(name="📊 Statistik", value=stat_text, inline=False)

        await msg.edit(embed=embed, view=view)
        await interaction.followup.send(f"✅ Rating **{topik}** dipasang.", ephemeral=True)

    @app_commands.command(name="config_log", description="Set channel untuk laporan rating.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if set_rating_log_channel(interaction.guild.id, channel.id):
            await interaction.response.send_message(f"✅ Log rating diset ke {channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Error DB.", ephemeral=True)

    async def cog_load(self):
        # Load persistent view
        v = ui.View(timeout=None)
        v.add_item(DynamicRoleSelect())
        self.bot.add_view(v)

async def setup(bot):
    await bot.add_cog(DynamicSupportCog(bot))
