import discord
from discord import app_commands
from discord.ext import commands
from discord import ui
import logging
from typing import List
from utils.database import (
    set_rating_log_channel, get_rating_log_channel, 
    add_rating, get_rating_stats
)

logger = logging.getLogger(__name__)

# ====================================================
# 1. UI COMPONENTS (MODAL & VIEW)
# ====================================================

class RatingModal(ui.Modal):
    def __init__(self, topic, stars, bot):
        super().__init__(title=f"⭐ Ulasan: {topic} ({stars}/5)")
        self.topic = topic
        self.stars = stars
        self.bot = bot

        self.comment = ui.TextInput(
            label="Tulis pengalaman Anda",
            style=discord.TextStyle.paragraph,
            placeholder="Pelayanan cepat, admin ramah...",
            required=True,
            max_length=1000
        )
        self.add_item(self.comment)

    async def on_submit(self, interaction: discord.Interaction):
        if add_rating(interaction.user.id, self.topic, self.stars, self.comment.value):
            # Kirim Log (Webhook Style)
            log_id = get_rating_log_channel(interaction.guild.id)
            if log_id:
                channel = self.bot.get_channel(log_id)
                if channel:
                    avg, count = get_rating_stats(self.topic)
                    embed = discord.Embed(
                        title=f"New Review: {self.topic}",
                        color=discord.Color.gold() if self.stars >= 4 else discord.Color.red(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
                    embed.set_thumbnail(url=interaction.user.display_avatar.url)
                    embed.add_field(name="Rating", value=f"{'⭐' * self.stars} **({self.stars}/5)**", inline=False)
                    embed.add_field(name="Review", value=f"```\n{self.comment.value}\n```", inline=False)
                    embed.set_footer(text=f"Total: {count} Reviews | Avg: {avg}/5.0")
                    await channel.send(embed=embed)

            await interaction.response.send_message("✅ Ulasan berhasil dikirim!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Database error.", ephemeral=True)

class DynamicRoleSelect(ui.Select):
    def __init__(self, placeholder="Pilih Role...", options=None):
        safe_options = options if options else [discord.SelectOption(label="Loading...", value="dummy")]
        super().__init__(placeholder=placeholder, min_values=0, max_values=1, options=safe_options, custom_id="dynamic_role_select")

    async def callback(self, interaction: discord.Interaction):
        valid_opts = [opt for opt in self.options if opt.value.isdigit()]
        selected_ids = self.values
        added, removed = [], []

        for opt in valid_opts:
            role_id = int(opt.value)
            role = interaction.guild.get_role(role_id)
            if not role: continue

            if opt.value in selected_ids:
                if role not in interaction.user.roles:
                    await interaction.user.add_roles(role); added.append(role.name)
            else:
                if role in interaction.user.roles:
                    await interaction.user.remove_roles(role); removed.append(role.name)
        
        if added: await interaction.response.send_message(f"✅ Role **{', '.join(added)}** diambil.", ephemeral=True)
        elif removed: await interaction.response.send_message(f"❌ Role **{', '.join(removed)}** dilepas.", ephemeral=True)
        else: await interaction.response.send_message("Tidak ada perubahan.", ephemeral=True)

# ====================================================
# 2. MAIN LOGIC (COMMANDS)
# ====================================================

class DynamicSupportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- AUTOCOMPLETE FUNCTION (FITUR "AUTO KEDEK") ---
    async def embed_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Otomatis mendeteksi pesan bot yang memiliki embed di channel ini."""
        options = []
        # Scan 25 pesan terakhir di channel
        async for msg in interaction.channel.history(limit=25):
            if msg.author == interaction.guild.me and msg.embeds:
                # Ambil judul embed, atau fallback ke "Tanpa Judul"
                title = msg.embeds[0].title or f"Pesan ID: {msg.id}"
                
                # Filter berdasarkan ketikan user (current)
                if current.lower() in title.lower():
                    # Tampilkan Judul (ID di background)
                    display_name = f"{title[:80]}..." if len(title) > 80 else title
                    options.append(app_commands.Choice(name=display_name, value=str(msg.id)))
        
        return options[:25] # Limit max 25 pilihan Discord

    # --- LISTENER GLOBAL ---
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component: return
        cid = interaction.data.get("custom_id", "")

        if cid.startswith("verify:"):
            try:
                role = interaction.guild.get_role(int(cid.split(":")[1]))
                if role:
                    if role in interaction.user.roles: await interaction.response.send_message("✅ Sudah punya role.", ephemeral=True)
                    else: await interaction.user.add_roles(role); await interaction.response.send_message(f"✅ Sukses! +{role.name}", ephemeral=True)
                else: await interaction.response.send_message("❌ Role hilang.", ephemeral=True)
            except: await interaction.response.send_message("❌ Error.", ephemeral=True)

        elif cid.startswith("rate:"):
            try:
                parts = cid.split(":"); await interaction.response.send_modal(RatingModal(parts[1], int(parts[2]), self.bot))
            except: await interaction.response.send_message("❌ Error rating.", ephemeral=True)

    # --- SLASH COMMANDS ---

    @app_commands.command(name="setup_verify", description="Buat panel verifikasi baru (Standalone).")
    @app_commands.describe(role="Role yang didapat", judul="Judul Embed", deskripsi="Isi pesan", label_tombol="Teks Tombol", gambar="Banner")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_verify(self, interaction: discord.Interaction, role: discord.Role, judul: str, deskripsi: str, label_tombol: str = "Verifikasi", gambar: discord.Attachment = None):
        embed = discord.Embed(title=judul, description=deskripsi, color=0x2ecc71)
        if gambar: embed.set_image(url=gambar.url)
        embed.set_footer(text="Sistem Verifikasi Otomatis")

        view = ui.View(timeout=None)
        view.add_item(ui.Button(label=label_tombol, style=discord.ButtonStyle.success, emoji="✅", custom_id=f"verify:{role.id}"))

        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Panel Verifikasi dibuat!", ephemeral=True)

    @app_commands.command(name="setup_rating", description="Buat panel rating baru (Standalone).")
    @app_commands.describe(topik="Topik (cth: Admin)", judul="Judul Embed", deskripsi="Isi pesan", gambar="Banner")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_rating(self, interaction: discord.Interaction, topik: str, judul: str, deskripsi: str, gambar: discord.Attachment = None):
        avg, count = get_rating_stats(topik)
        embed = discord.Embed(title=judul, description=deskripsi, color=0xf1c40f)
        if gambar: embed.set_image(url=gambar.url)
        embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
        embed.set_footer(text=f"Topik: {topik}")

        view = ui.View(timeout=None)
        for i in range(1, 6):
            view.add_item(ui.Button(label=str(i), emoji="⭐", custom_id=f"rate:{topik}:{i}", style=discord.ButtonStyle.secondary))

        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Panel Rating dibuat!", ephemeral=True)

    @app_commands.command(name="setup_role_menu", description="Buat panel menu role (Dropdown) baru.")
    @app_commands.describe(judul="Judul Embed", deskripsi="Isi pesan", gambar="Banner")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_role_menu(self, interaction: discord.Interaction, judul: str, deskripsi: str, gambar: discord.Attachment = None):
        embed = discord.Embed(title=judul, description=deskripsi, color=0x3498db)
        if gambar: embed.set_image(url=gambar.url)

        view = ui.View(timeout=None)
        view.add_item(DynamicRoleSelect(options=[discord.SelectOption(label="Belum ada role...", value="dummy")]))

        msg = await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Menu Role dibuat!", ephemeral=True)

    @app_commands.command(name="add_role_to_menu", description="Tambah role ke menu dropdown yang sudah ada.")
    @app_commands.describe(
        target_pesan="Pilih panel role yang mau diedit (Auto-Detect)",
        role="Role yang dimasukkan",
        label="Nama di menu",
        emoji="Emoji ikon"
    )
    @app_commands.autocomplete(target_pesan=embed_autocomplete) # <--- INI FITUR AUTO KEDEK
    @app_commands.checks.has_permissions(administrator=True)
    async def add_role_to_menu(self, interaction: discord.Interaction, target_pesan: str, role: discord.Role, label: str, emoji: str = "🔹"):
        try:
            msg = await interaction.channel.fetch_message(int(target_pesan))
        except:
            return await interaction.response.send_message("❌ Pesan tidak ditemukan (Mungkin sudah dihapus/terlalu lama).", ephemeral=True)

        view = ui.View.from_message(msg)
        view.timeout = None
        
        select = None
        for child in view.children:
            if isinstance(child, ui.Select) and child.custom_id == "dynamic_role_select":
                select = child; break
        
        if not select:
            select = DynamicRoleSelect(options=[]); view.add_item(select)

        current_opts = [o for o in select.options if o.value != "dummy"]
        if len(current_opts) >= 25: return await interaction.response.send_message("❌ Menu penuh (Max 25).", ephemeral=True)
        if any(o.value == str(role.id) for o in current_opts): return await interaction.response.send_message("❌ Role sudah ada.", ephemeral=True)

        current_opts.append(discord.SelectOption(label=label, value=str(role.id), emoji=emoji, description=f"Role: {role.name}"))
        
        # Replace select lama dengan yang baru
        new_select = DynamicRoleSelect(options=current_opts)
        new_select.max_values = len(current_opts)
        
        for i, item in enumerate(view.children):
            if item.custom_id == "dynamic_role_select":
                view.children[i] = new_select; break
        else: view.add_item(new_select)

        await msg.edit(view=view)
        await interaction.response.send_message(f"✅ Role **{label}** berhasil ditambahkan!", ephemeral=True)

    @app_commands.command(name="config_rating_log", description="Set channel log rating.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_rating_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if set_rating_log_channel(interaction.guild.id, channel.id):
            await interaction.response.send_message(f"✅ Log rating ke {channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Database error.", ephemeral=True)

    async def cog_load(self):
        v = ui.View(timeout=None); v.add_item(DynamicRoleSelect()); self.bot.add_view(v)

async def setup(bot):
    await bot.add_cog(DynamicSupportCog(bot))
