import discord
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
# 1. MODAL & VIEW COMPONENTS (PERSISTENT)
# ====================================================

# Modal Rating (Sistem Shopee/Ulasan)
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
            placeholder="Contoh: Pelayanan sangat cepat dan ramah!",
            required=True,
            max_length=500
        )
        self.add_item(self.comment)

    async def on_submit(self, interaction: discord.Interaction):
        # Simpan ke Database
        success = add_rating(self.topic, interaction.user.id, self.stars, self.comment.value)
        
        if success:
            # 1. Balas ke User (Ephemeral)
            await interaction.response.send_message(f"✅ Terima kasih! Rating **{self.stars}⭐** dan ulasan Anda telah dikirim.", ephemeral=True)
            
            # 2. Update Embed Statistik Realtime
            try:
                avg, count = get_rating_stats(self.topic)
                embed = self.message_to_update.embeds[0]
                
                # Update field statistik
                found = False
                for i, field in enumerate(embed.fields):
                    if "Statistik" in field.name:
                        embed.set_field_at(i, name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
                        found = True
                        break
                
                if not found:
                    embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)

                await self.message_to_update.edit(embed=embed)
            except Exception as e:
                logger.error(f"Gagal update embed statistik: {e}")

            # 3. Kirim Log ke Channel
            log_id = get_rating_log_channel(interaction.guild.id)
            if log_id:
                log_ch = self.bot.get_channel(log_id)
                if log_ch:
                    log_embed = discord.Embed(title="🌟 Ulasan Baru Diterima", color=discord.Color.gold())
                    log_embed.set_thumbnail(url=interaction.user.display_avatar.url)
                    log_embed.add_field(name="👤 User", value=interaction.user.mention, inline=True)
                    log_embed.add_field(name="🏷️ Topik", value=self.topic, inline=True)
                    log_embed.add_field(name="⭐ Rating", value=f"{'⭐' * self.stars} ({self.stars}/5)", inline=False)
                    log_embed.add_field(name="💬 Pesan", value=f"```{self.comment.value}```", inline=False)
                    log_embed.set_footer(text=f"Total: {count} Review | Avg: {avg}")
                    log_embed.timestamp = discord.utils.utcnow()
                    await log_ch.send(embed=log_embed)
        else:
            await interaction.response.send_message("❌ Gagal menyimpan ulasan ke database.", ephemeral=True)

class RulesView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Baca Rules", style=discord.ButtonStyle.danger, emoji="📜", custom_id="rules:read")
    async def read_rules(self, interaction: discord.Interaction, button: ui.Button):
        rules_text = get_server_rules(interaction.guild_id)
        if not rules_text:
            rules_text = "⚠️ **Rules Belum Diatur**\nAdmin gunakan `!set_rules [teks]` untuk mengisi ini."
        
        embed = discord.Embed(title="📜 Peraturan Komunitas", description=rules_text, color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

class DynamicRoleSelect(ui.Select):
    def __init__(self, placeholder="Pilih Role...", options=None):
        safe_options = options if options else [discord.SelectOption(label="Loading...", value="dummy")]
        super().__init__(placeholder=placeholder, min_values=0, max_values=1, options=safe_options, custom_id="dynamic_role_select")

    async def callback(self, interaction: discord.Interaction):
        selected_values = self.values
        all_options = self.options # Opsi yang ada di menu saat ini

        assigned, removed = [], []
        
        for option in all_options:
            if not option.value.isdigit(): continue 
            
            role_id = int(option.value)
            role = interaction.guild.get_role(role_id)
            if not role: continue

            if option.value in selected_values:
                if role not in interaction.user.roles:
                    await interaction.user.add_roles(role)
                    assigned.append(role.name)
            else:
                if role in interaction.user.roles:
                    await interaction.user.remove_roles(role)
                    removed.append(role.name)

        msg = ""
        if assigned: msg += f"✅ **Ditambahkan:** {', '.join(assigned)}\n"
        if removed: msg += f"❌ **Dihapus:** {', '.join(removed)}"
        if not msg: msg = "Tidak ada perubahan role."
        
        await interaction.response.send_message(msg, ephemeral=True)

# ====================================================
# 2. MAIN COG
# ====================================================

class DynamicSupportCog(commands.Cog, name="DynamicSupport"):
    def __init__(self, bot):
        self.bot = bot

    # --- HELPER: FIND MESSAGE BY TITLE OR ID ---
    async def find_target_message(self, ctx, identifier: str):
        """Mencari pesan berdasarkan ID atau JUDUL EMBED di channel saat ini."""
        # 1. Coba cari berdasarkan ID (Angka)
        if identifier.isdigit():
            try:
                return await ctx.channel.fetch_message(int(identifier))
            except:
                pass # Lanjut cari by title jika gagal fetch ID

        # 2. Coba cari berdasarkan Judul Embed (Scan 50 pesan terakhir)
        # Kita cari yang paling BARU (terakhir dikirim)
        async for message in ctx.channel.history(limit=50):
            if message.author == ctx.guild.me and message.embeds:
                # Cek Title (Case insensitive)
                embed_title = message.embeds[0].title
                if embed_title and embed_title.lower() == identifier.lower():
                    return message
        
        return None

    # --- LISTENER ---
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component: return
        cid = interaction.data.get("custom_id", "")

        if cid.startswith("verify:"):
            try:
                role_id = int(cid.split(":")[1])
                role = interaction.guild.get_role(role_id)
                if role:
                    if role in interaction.user.roles:
                        await interaction.response.send_message(f"✅ Kamu sudah memiliki role {role.mention}!", ephemeral=True)
                    else:
                        await interaction.user.add_roles(role)
                        await interaction.response.send_message(f"✅ Verifikasi berhasil! Role {role.mention} diberikan.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Role tidak ditemukan.", ephemeral=True)
            except:
                await interaction.response.send_message("❌ Gagal verifikasi.", ephemeral=True)

        elif cid.startswith("rate:"):
            try:
                parts = cid.split(":")
                topic = ":".join(parts[1:-1])
                stars = int(parts[-1])
                modal = RatingModal(topic, stars, self.bot, interaction.message)
                await interaction.response.send_modal(modal)
            except:
                await interaction.response.send_message("❌ Gagal membuka ulasan.", ephemeral=True)

    # --- COMMANDS: SETUP ---

    @commands.command(name="create_embed")
    @commands.has_permissions(administrator=True)
    async def create_embed(self, ctx, channel: discord.TextChannel, color_hex: str, title: str, *, description: str):
        """
        Buat embed. Judul Embed ini nanti dipakai untuk target setup.
        Contoh: !create_embed #umum FF0000 "Info Server" "Isi deskripsi..."
        """
        try:
            if color_hex.startswith("#"): color_hex = color_hex[1:]
            color = int(color_hex, 16)
        except: color = 0x3498db

        embed = discord.Embed(title=title, description=description, color=color)
        if ctx.message.attachments:
            embed.set_image(url=ctx.message.attachments[0].url)

        await channel.send(embed=embed)
        await ctx.send(f"✅ Embed **{title}** berhasil dibuat di {channel.mention}.\nSekarang kamu bisa setup pakai: `!setuprole \"{title}\" ...`", delete_after=10)

    @commands.command(name="setuprole")
    @commands.has_permissions(administrator=True)
    async def setup_role(self, ctx, target: str, role: discord.Role, label: str, emoji: str = "🔹"):
        """
        Target: Bisa 'Judul Embed' atau 'ID Pesan'.
        Contoh: !setuprole "Info Server" @Warga "Ambil Warga" 🙋‍♂️
        """
        msg = await self.find_target_message(ctx, target)
        if not msg: return await ctx.send(f"❌ Pesan dengan judul/ID **'{target}'** tidak ditemukan di 50 pesan terakhir.")

        view = ui.View.from_message(msg); view.timeout = None
        
        select_menu = None
        for child in view.children:
            if isinstance(child, ui.Select) and child.custom_id == "dynamic_role_select":
                select_menu = child; break
        
        if not select_menu:
            select_menu = DynamicRoleSelect(options=[]); view.add_item(select_menu)

        current_options = [opt for opt in select_menu.options if opt.value != "dummy"]
        if len(current_options) >= 25: return await ctx.send("❌ Maksimal 25 role per menu.")
        if any(opt.value == str(role.id) for opt in current_options): return await ctx.send("❌ Role ini sudah ada di menu.")

        current_options.append(discord.SelectOption(label=label, value=str(role.id), emoji=emoji, description=f"Role: {role.name}"))
        
        # Re-create select to update options
        new_select = DynamicRoleSelect(options=current_options)
        new_select.max_values = len(current_options)
        
        # Replace old select
        for i, item in enumerate(view.children):
            if isinstance(item, ui.Select) and item.custom_id == "dynamic_role_select":
                view.children[i] = new_select; break
        else: view.add_item(new_select)

        await msg.edit(view=view)
        await ctx.message.delete()
        await ctx.send(f"✅ Role **{label}** ditambahkan ke embed **{target}**.", delete_after=3)

    @commands.command(name="setuplink")
    @commands.has_permissions(administrator=True)
    async def setup_link(self, ctx, target: str, label: str, url: str, emoji: str = "🔗"):
        """Contoh: !setuplink "Info Server" "Website" https://web.com 🌐"""
        msg = await self.find_target_message(ctx, target)
        if not msg: return await ctx.send(f"❌ Pesan **'{target}'** tidak ditemukan.")
        
        view = ui.View.from_message(msg); view.timeout = None
        view.add_item(ui.Button(label=label, url=url, emoji=emoji))
        
        await msg.edit(view=view)
        await ctx.message.delete()
        await ctx.send(f"✅ Link ditambahkan ke **{target}**.", delete_after=3)

    @commands.command(name="setupverify")
    @commands.has_permissions(administrator=True)
    async def setup_verify(self, ctx, target: str, role: discord.Role, label: str = "Verifikasi", emoji: str = "✅"):
        """Contoh: !setupverify "Verifikasi Disini" @Member "Klik Saya" ✅"""
        msg = await self.find_target_message(ctx, target)
        if not msg: return await ctx.send(f"❌ Pesan **'{target}'** tidak ditemukan.")
        
        view = ui.View.from_message(msg); view.timeout = None
        view.add_item(ui.Button(label=label, style=discord.ButtonStyle.success, emoji=emoji, custom_id=f"verify:{role.id}"))
        
        await msg.edit(view=view)
        await ctx.message.delete()
        await ctx.send(f"✅ Tombol verify ditambahkan ke **{target}**.", delete_after=3)

    @commands.command(name="setuprating")
    @commands.has_permissions(administrator=True)
    async def setup_rating(self, ctx, target: str, topic: str):
        """Contoh: !setuprating "Rating Admin" "Kinerja Admin" """
        msg = await self.find_target_message(ctx, target)
        if not msg: return await ctx.send(f"❌ Pesan **'{target}'** tidak ditemukan.")
        
        avg, count = get_rating_stats(topic)
        if msg.embeds:
            embed = msg.embeds[0]
            # Cek apakah field statistik sudah ada
            found = False
            for i, field in enumerate(embed.fields):
                if "Statistik" in field.name:
                    embed.set_field_at(i, name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
                    found = True; break
            if not found:
                embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
        else:
            embed = discord.Embed(description="Rating Panel") # Fallback jika pesan polos

        view = ui.View.from_message(msg); view.timeout = None
        for i in range(1, 6):
            view.add_item(ui.Button(label=str(i), emoji="⭐", custom_id=f"rate:{topic}:{i}", style=discord.ButtonStyle.secondary))
        
        await msg.edit(embed=embed, view=view)
        await ctx.message.delete()
        await ctx.send(f"✅ Rating **{topic}** dipasang di **{target}**.", delete_after=3)

    # --- RULES & CONFIG ---
    @commands.command(name="set_rules")
    @commands.has_permissions(administrator=True)
    async def set_rules(self, ctx, *, content: str):
        if set_server_rules(ctx.guild.id, content): await ctx.send("✅ Rules diupdate.", delete_after=3)
        else: await ctx.send("❌ DB Error.")

    @commands.command(name="setup_rating_log")
    @commands.has_permissions(administrator=True)
    async def setup_rating_log(self, ctx, channel: discord.TextChannel):
        if set_rating_log_channel(ctx.guild.id, channel.id): await ctx.send(f"✅ Log rating: {channel.mention}")
        else: await ctx.send("❌ DB Error.")

    async def cog_load(self):
        self.bot.add_view(RulesView())
        v = ui.View(timeout=None); v.add_item(DynamicRoleSelect()); self.bot.add_view(v)

async def setup(bot):
    await bot.add_cog(DynamicSupportCog(bot))
