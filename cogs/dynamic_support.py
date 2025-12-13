import discord
from discord import app_commands
from discord.ext import commands
from discord import ui
import logging
from utils.database import (
    set_rating_log_channel, get_rating_log_channel, 
    add_rating, get_rating_stats,
    set_server_rules, get_server_rules
)

logger = logging.getLogger(__name__)

# ====================================================
# 1. KOMPONEN UI (View & Modal) - Tidak Berubah
# ====================================================

class RatingModal(ui.Modal):
    def __init__(self, topic, stars, bot_instance, message_to_update):
        super().__init__(title=f"Ulasan: {topic} ({stars}⭐)")
        self.topic = topic
        self.stars = stars
        self.bot = bot_instance
        self.message_to_update = message_to_update

        self.comment = ui.TextInput(
            label="Tulis Ulasan / Pesan Anda",
            style=discord.TextStyle.paragraph,
            placeholder="Contoh: Pelayanan sangat cepat, mantap!",
            required=True,
            max_length=500
        )
        self.add_item(self.comment)

    async def on_submit(self, interaction: discord.Interaction):
        success = add_rating(self.topic, interaction.user.id, self.stars, self.comment.value)
        
        if success:
            await interaction.response.send_message(f"✅ Terima kasih! Rating **{self.stars}⭐** dan ulasan terkirim.", ephemeral=True)
            
            # Update Realtime Statistik di Embed
            try:
                avg, count = get_rating_stats(self.topic)
                embed = self.message_to_update.embeds[0]
                found = False
                for i, field in enumerate(embed.fields):
                    if "Statistik" in field.name:
                        embed.set_field_at(i, name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
                        found = True; break
                if not found:
                    embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
                await self.message_to_update.edit(embed=embed)
            except: pass

            # Kirim Log
            log_id = get_rating_log_channel(interaction.guild.id)
            if log_id:
                log_ch = self.bot.get_channel(log_id)
                if log_ch:
                    log_embed = discord.Embed(title="🌟 Ulasan Baru", color=discord.Color.gold())
                    log_embed.set_thumbnail(url=interaction.user.display_avatar.url)
                    log_embed.add_field(name="👤 User", value=interaction.user.mention, inline=True)
                    log_embed.add_field(name="🏷️ Topik", value=self.topic, inline=True)
                    log_embed.add_field(name="⭐ Rating", value=f"{'⭐' * self.stars} ({self.stars}/5)", inline=False)
                    log_embed.add_field(name="💬 Pesan", value=f"```{self.comment.value}```", inline=False)
                    log_embed.set_footer(text=f"Total: {count} | Avg: {avg}")
                    await log_ch.send(embed=log_embed)
        else:
            await interaction.response.send_message("❌ Database Error.", ephemeral=True)

class RulesView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Baca Rules", style=discord.ButtonStyle.danger, emoji="📜", custom_id="rules:read")
    async def read_rules(self, interaction: discord.Interaction, button: ui.Button):
        rules_text = get_server_rules(interaction.guild_id)
        if not rules_text: rules_text = "⚠️ Rules belum diatur oleh Admin."
        embed = discord.Embed(title="📜 Peraturan Komunitas", description=rules_text, color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

class DynamicRoleSelect(ui.Select):
    def __init__(self, placeholder="Pilih Role...", options=None):
        safe_options = options if options else [discord.SelectOption(label="Loading...", value="dummy")]
        super().__init__(placeholder=placeholder, min_values=0, max_values=1, options=safe_options, custom_id="dynamic_role_select")

    async def callback(self, interaction: discord.Interaction):
        selected_values = self.values; all_options = self.options
        assigned, removed = [], []
        
        for option in all_options:
            if not option.value.isdigit(): continue 
            role_id = int(option.value)
            role = interaction.guild.get_role(role_id)
            if not role: continue

            if option.value in selected_values:
                if role not in interaction.user.roles:
                    await interaction.user.add_roles(role); assigned.append(role.name)
            else:
                if role in interaction.user.roles:
                    await interaction.user.remove_roles(role); removed.append(role.name)

        msg = ""
        if assigned: msg += f"✅ **Ditambahkan:** {', '.join(assigned)}\n"
        if removed: msg += f"❌ **Dihapus:** {', '.join(removed)}"
        if not msg: msg = "Tidak ada perubahan role."
        await interaction.response.send_message(msg, ephemeral=True)

# ====================================================
# 2. MAIN COG (SLASH COMMANDS)
# ====================================================

class DynamicSupportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- Helper: Cari Pesan (ID atau Judul) ---
    async def find_message(self, interaction: discord.Interaction, target: str):
        # 1. Cek jika input adalah ID angka
        if target.isdigit():
            try: return await interaction.channel.fetch_message(int(target))
            except: pass
        
        # 2. Cari berdasarkan Judul Embed di 50 pesan terakhir channel ini
        async for message in interaction.channel.history(limit=50):
            if message.author == interaction.guild.me and message.embeds:
                if message.embeds[0].title and message.embeds[0].title.lower() == target.lower():
                    return message
        return None

    # --- LISTENER INTERAKSI (Tombol/Menu) ---
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component: return
        cid = interaction.data.get("custom_id", "")

        if cid.startswith("verify:"):
            try:
                role = interaction.guild.get_role(int(cid.split(":")[1]))
                if role:
                    if role in interaction.user.roles: await interaction.response.send_message(f"✅ Sudah punya {role.mention}!", ephemeral=True)
                    else: await interaction.user.add_roles(role); await interaction.response.send_message(f"✅ Verifikasi sukses! +{role.mention}", ephemeral=True)
                else: await interaction.response.send_message("❌ Role hilang.", ephemeral=True)
            except: await interaction.response.send_message("❌ Error.", ephemeral=True)

        elif cid.startswith("rate:"):
            try:
                parts = cid.split(":"); topic = ":".join(parts[1:-1]); stars = int(parts[-1])
                await interaction.response.send_modal(RatingModal(topic, stars, self.bot, interaction.message))
            except: await interaction.response.send_message("❌ Error modal.", ephemeral=True)

    # ====================================================
    # SLASH COMMANDS START HERE
    # ====================================================

    @app_commands.command(name="create_embed", description="Buat embed dasar untuk pengumuman atau panel.")
    @app_commands.describe(
        judul="Judul embed (Penting: Dipakai untuk target setup)",
        deskripsi="Isi pesan embed",
        warna="Kode warna HEX (contoh: FF0000 untuk merah)",
        gambar="Upload gambar untuk embed (Opsional)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def create_embed(self, interaction: discord.Interaction, judul: str, deskripsi: str, warna: str = "3498db", gambar: discord.Attachment = None):
        try:
            if warna.startswith("#"): warna = warna[1:]
            color_int = int(warna, 16)
        except: color_int = 0x3498db

        embed = discord.Embed(title=judul, description=deskripsi, color=color_int)
        if gambar:
            embed.set_image(url=gambar.url)

        await interaction.channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Embed **{judul}** berhasil dibuat! Gunakan judul ini untuk setup tombol.", ephemeral=True)

    @app_commands.command(name="setup_role", description="Tambah menu dropdown role ke embed.")
    @app_commands.describe(target="Judul Embed atau ID Pesan", role="Role yang akan diberikan", label="Nama di menu", emoji="Emoji ikon")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_role(self, interaction: discord.Interaction, target: str, role: discord.Role, label: str, emoji: str = "🔹"):
        await interaction.response.defer(ephemeral=True) # Defer karena cari pesan butuh waktu
        
        msg = await self.find_message(interaction, target)
        if not msg:
            return await interaction.followup.send(f"❌ Pesan **'{target}'** tidak ditemukan di channel ini.", ephemeral=True)

        view = ui.View.from_message(msg); view.timeout = None
        
        select_menu = None
        for child in view.children:
            if isinstance(child, ui.Select) and child.custom_id == "dynamic_role_select":
                select_menu = child; break
        
        if not select_menu:
            select_menu = DynamicRoleSelect(options=[]); view.add_item(select_menu)

        current_options = [opt for opt in select_menu.options if opt.value != "dummy"]
        if len(current_options) >= 25: return await interaction.followup.send("❌ Maksimal 25 role.", ephemeral=True)
        if any(opt.value == str(role.id) for opt in current_options): return await interaction.followup.send("❌ Role sudah ada.", ephemeral=True)

        current_options.append(discord.SelectOption(label=label, value=str(role.id), emoji=emoji, description=f"Role: {role.name}"))
        
        # Re-create select
        new_select = DynamicRoleSelect(options=current_options); new_select.max_values = len(current_options)
        
        for i, item in enumerate(view.children):
            if isinstance(item, ui.Select) and item.custom_id == "dynamic_role_select":
                view.children[i] = new_select; break
        else: view.add_item(new_select)

        await msg.edit(view=view)
        await interaction.followup.send(f"✅ Role **{label}** ditambahkan ke **{target}**.", ephemeral=True)

    @app_commands.command(name="setup_link", description="Tambah tombol link ke embed.")
    @app_commands.describe(target="Judul Embed atau ID Pesan", label="Tulisan tombol", url="Link tujuan", emoji="Ikon")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_link(self, interaction: discord.Interaction, target: str, label: str, url: str, emoji: str = "🔗"):
        await interaction.response.defer(ephemeral=True)
        
        msg = await self.find_message(interaction, target)
        if not msg: return await interaction.followup.send(f"❌ Pesan **'{target}'** tidak ditemukan.", ephemeral=True)

        view = ui.View.from_message(msg); view.timeout = None
        view.add_item(ui.Button(label=label, url=url, emoji=emoji))
        
        await msg.edit(view=view)
        await interaction.followup.send(f"✅ Link ditambahkan ke **{target}**.", ephemeral=True)

    @app_commands.command(name="setup_verify", description="Tambah tombol verifikasi role.")
    @app_commands.describe(target="Judul Embed atau ID Pesan", role="Role yang didapat", label="Tulisan tombol", emoji="Ikon")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_verify(self, interaction: discord.Interaction, target: str, role: discord.Role, label: str = "Verifikasi", emoji: str = "✅"):
        await interaction.response.defer(ephemeral=True)
        
        msg = await self.find_message(interaction, target)
        if not msg: return await interaction.followup.send(f"❌ Pesan **'{target}'** tidak ditemukan.", ephemeral=True)

        view = ui.View.from_message(msg); view.timeout = None
        view.add_item(ui.Button(label=label, style=discord.ButtonStyle.success, emoji=emoji, custom_id=f"verify:{role.id}"))
        
        await msg.edit(view=view)
        await interaction.followup.send(f"✅ Tombol verify ditambahkan ke **{target}**.", ephemeral=True)

    @app_commands.command(name="setup_rating", description="Tambah sistem rating bintang (Shopee style).")
    @app_commands.describe(target="Judul Embed atau ID Pesan", topik="Nama topik rating (misal: Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_rating(self, interaction: discord.Interaction, target: str, topik: str):
        await interaction.response.defer(ephemeral=True)
        
        msg = await self.find_message(interaction, target)
        if not msg: return await interaction.followup.send(f"❌ Pesan **'{target}'** tidak ditemukan.", ephemeral=True)

        avg, count = get_rating_stats(topik)
        if msg.embeds:
            embed = msg.embeds[0]
            found = False
            for i, field in enumerate(embed.fields):
                if "Statistik" in field.name:
                    embed.set_field_at(i, name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
                    found = True; break
            if not found: embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
        else:
            embed = discord.Embed(description="Rating Panel")
            embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)

        view = ui.View.from_message(msg); view.timeout = None
        # Tambah 5 bintang
        for i in range(1, 6):
            view.add_item(ui.Button(label=str(i), emoji="⭐", custom_id=f"rate:{topik}:{i}", style=discord.ButtonStyle.secondary))
        
        await msg.edit(embed=embed, view=view)
        await interaction.followup.send(f"✅ Sistem rating **{topik}** dipasang di **{target}**.", ephemeral=True)

    @app_commands.command(name="config_rules", description="Atur isi teks peraturan server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_rules(self, interaction: discord.Interaction, isi_peraturan: str):
        if set_server_rules(interaction.guild_id, isi_peraturan):
            await interaction.response.send_message("✅ Isi peraturan berhasil diperbarui.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Gagal menyimpan database.", ephemeral=True)

    @app_commands.command(name="config_rating_log", description="Atur channel log untuk rating.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_rating_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if set_rating_log_channel(interaction.guild.id, channel.id):
            await interaction.response.send_message(f"✅ Log rating akan dikirim ke {channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Gagal menyimpan database.", ephemeral=True)

    @app_commands.command(name="setup_rules_button", description="Pasang tombol 'Baca Rules' di embed.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_rules_button(self, interaction: discord.Interaction, target: str):
        await interaction.response.defer(ephemeral=True)
        msg = await self.find_message(interaction, target)
        if not msg: return await interaction.followup.send("❌ Pesan tidak ditemukan.", ephemeral=True)
        
        view = ui.View.from_message(msg); view.timeout = None
        view.add_item(ui.Button(label="Baca Rules", style=discord.ButtonStyle.danger, emoji="📜", custom_id="rules:read"))
        
        await msg.edit(view=view)
        await interaction.followup.send("✅ Tombol Rules dipasang.", ephemeral=True)

    async def cog_load(self):
        self.bot.add_view(RulesView())
        v = ui.View(timeout=None); v.add_item(DynamicRoleSelect()); self.bot.add_view(v)

async def setup(bot):
    await bot.add_cog(DynamicSupportCog(bot))
