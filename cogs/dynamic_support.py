import discord
from discord.ext import commands
from discord import ui
import logging
# Import fungsi database baru
from utils.database import (
    set_rating_log_channel, get_rating_log_channel, 
    add_rating, get_rating_stats,
    set_server_rules, get_server_rules
)

logger = logging.getLogger(__name__)

# ====================================================
# 1. VIEW COMPONENTS (PERSISTENT)
# ====================================================

class RulesView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Baca Rules", style=discord.ButtonStyle.danger, emoji="📜", custom_id="rules:read")
    async def read_rules(self, interaction: discord.Interaction, button: ui.Button):
        # AMBIL DATA RULES DARI DATABASE
        rules_text = get_server_rules(interaction.guild_id)
        
        # Jika belum ada di database, tampilkan default
        if not rules_text:
            rules_text = (
                "⚠️ **Rules Belum Diatur**\n\n"
                "Admin belum mengatur isi peraturan server ini.\n"
                "Silakan gunakan command `!set_rules [isi peraturan]` untuk mengaturnya."
            )
        
        embed = discord.Embed(title="📜 Peraturan Komunitas", color=discord.Color.red())
        embed.description = rules_text
        embed.set_footer(text="Harap patuhi peraturan demi kenyamanan bersama.")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

class DynamicRoleSelect(ui.Select):
    def __init__(self, placeholder="Pilih Role...", options=None):
        safe_options = options if options else [discord.SelectOption(label="Loading...", value="dummy")]
        super().__init__(
            placeholder=placeholder,
            min_values=0, 
            max_values=1,
            options=safe_options,
            custom_id="dynamic_role_select"
        )

    async def callback(self, interaction: discord.Interaction):
        selected_role_ids = []
        for val in self.values:
            if val.isdigit(): selected_role_ids.append(int(val))
        
        original_view = ui.View.from_message(interaction.message)
        original_select = None
        for child in original_view.children:
            if isinstance(child, ui.Select) and child.custom_id == "dynamic_role_select":
                original_select = child; break
        
        if not original_select:
            return await interaction.response.send_message("❌ Error: Menu tidak ditemukan.", ephemeral=True)

        all_option_ids = [int(opt.value) for opt in original_select.options if opt.value.isdigit()]
        assigned, removed = [], []

        for role_id in all_option_ids:
            role = interaction.guild.get_role(role_id)
            if not role: continue
            
            if role_id in selected_role_ids:
                if role not in interaction.user.roles:
                    await interaction.user.add_roles(role)
                    assigned.append(role.name)
            else:
                if role in interaction.user.roles:
                    await interaction.user.remove_roles(role)
                    removed.append(role.name)
        
        msg = ""
        if assigned: msg += f"✅ Ditambahkan: {', '.join(assigned)}\n"
        if removed: msg += f"❌ Dihapus: {', '.join(removed)}"
        if not msg: msg = "Tidak ada perubahan role."
        await interaction.response.send_message(msg, ephemeral=True)

class RatingView(ui.View):
    def __init__(self, topic_name):
        super().__init__(timeout=None)
        for i in range(1, 6):
            self.add_item(ui.Button(label=str(i), emoji="⭐", custom_id=f"rate:{topic_name}:{i}", style=discord.ButtonStyle.secondary))

# ====================================================
# 2. MAIN COG
# ====================================================

class DynamicSupportCog(commands.Cog, name="DynamicSupport"):
    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # A. SISTEM VERIFIKASI
    # ------------------------------------------------------------------
    @commands.command(name="setup_verify")
    @commands.has_permissions(administrator=True)
    async def setup_verify(self, ctx, role: discord.Role, image_url: str = None, *, description: str = "Klik tombol di bawah untuk verifikasi."):
        await ctx.message.delete()
        embed = discord.Embed(title="🔐 Verifikasi Server", description=description, color=discord.Color.green())
        if image_url and image_url.startswith("http"): embed.set_image(url=image_url)
        view = ui.View(timeout=None)
        view.add_item(ui.Button(label="Verifikasi Sekarang", style=discord.ButtonStyle.success, emoji="✅", custom_id=f"verify:{role.id}"))
        await ctx.send(embed=embed, view=view)

    # ------------------------------------------------------------------
    # B. SISTEM RULES (CUSTOMIZABLE)
    # ------------------------------------------------------------------
    
    @commands.command(name="set_rules")
    @commands.has_permissions(administrator=True)
    async def set_rules(self, ctx, *, content: str):
        """
        Mengatur isi teks peraturan server.
        Contoh: !set_rules 1. Dilarang Spam 2. Dilarang Toxic
        """
        if set_server_rules(ctx.guild.id, content):
            await ctx.send("✅ **Isi peraturan berhasil diperbarui!**\nCoba tekan tombol di panel rules untuk melihat perubahannya.", delete_after=10)
        else:
            await ctx.send("❌ Gagal menyimpan peraturan ke database.")

    @commands.command(name="create_rules")
    @commands.has_permissions(administrator=True)
    async def create_rules(self, ctx, image_url: str = None, *, description: str = "Silakan baca peraturan dengan seksama dengan menekan tombol di bawah."):
        """
        Membuat panel tombol rules.
        Contoh: !create_rules https://img.url "Klik tombol di bawah"
        """
        await ctx.message.delete()
        embed = discord.Embed(title="📜 Peraturan Komunitas", description=description, color=discord.Color.red())
        if image_url and image_url.startswith("http"): embed.set_image(url=image_url)
        await ctx.send(embed=embed, view=RulesView())

    # ------------------------------------------------------------------
    # C. SISTEM LINKS
    # ------------------------------------------------------------------
    @commands.command(name="create_links")
    @commands.has_permissions(administrator=True)
    async def create_links(self, ctx, image_url: str = None, *, description: str = "Daftar Link Resmi Komunitas"):
        await ctx.message.delete()
        embed = discord.Embed(title="🔗 Official Links", description=description, color=discord.Color.blue())
        if image_url and image_url.startswith("http"): embed.set_image(url=image_url)
        msg = await ctx.send(embed=embed, view=ui.View(timeout=None))
        await ctx.send(f"Panel Link dibuat! ID: `{msg.id}`.\nGunakan `!add_link {msg.id} [Label] [URL] [Emoji]`", delete_after=15)

    @commands.command(name="add_link")
    @commands.has_permissions(administrator=True)
    async def add_link(self, ctx, message_id: int, label: str, url: str, emoji: str = "🔗"):
        try: msg = await ctx.channel.fetch_message(message_id)
        except: return await ctx.send("❌ Pesan tidak ditemukan.")
        view = ui.View.from_message(msg); view.timeout = None
        view.add_item(ui.Button(label=label, url=url, emoji=emoji))
        await msg.edit(view=view); await ctx.message.delete()

    # ------------------------------------------------------------------
    # D. SISTEM SELECT ROLE
    # ------------------------------------------------------------------
    @commands.command(name="create_role_menu")
    @commands.has_permissions(administrator=True)
    async def create_role_menu(self, ctx, image_url: str = None, *, description: str = "Pilih role di bawah:"):
        await ctx.message.delete()
        embed = discord.Embed(title="🎭 Self Roles", description=description, color=discord.Color.gold())
        if image_url and image_url.startswith("http"): embed.set_image(url=image_url)
        view = ui.View(timeout=None)
        select = DynamicRoleSelect(options=[discord.SelectOption(label="Belum ada role", value="dummy")]); select.disabled = True
        view.add_item(select)
        msg = await ctx.send(embed=embed, view=view)
        await ctx.send(f"Panel Role dibuat! ID: `{msg.id}`.\nGunakan `!add_role_option {msg.id} @Role [Label] [Emoji]`", delete_after=15)

    @commands.command(name="add_role_option")
    @commands.has_permissions(administrator=True)
    async def add_role_option(self, ctx, message_id: int, role: discord.Role, label: str, emoji: str = "🔹"):
        try: msg = await ctx.channel.fetch_message(message_id)
        except: return await ctx.send("❌ Pesan tidak ditemukan.")
        old_view = ui.View.from_message(msg); old_view.timeout = None
        
        select_menu = None
        for item in old_view.children:
            if isinstance(item, ui.Select) and item.custom_id == "dynamic_role_select":
                select_menu = item; break
        if not select_menu:
            select_menu = DynamicRoleSelect(options=[]); old_view.clear_items(); old_view.add_item(select_menu)
        
        current_options = [opt for opt in select_menu.options if opt.value != "dummy"]
        if len(current_options) >= 25: return await ctx.send("❌ Maksimal 25 role.")
        
        current_options.append(discord.SelectOption(label=label, value=str(role.id), emoji=emoji, description=f"Role: {role.name}"))
        
        new_select = DynamicRoleSelect(options=current_options); new_select.max_values = len(current_options)
        old_view.clear_items(); old_view.add_item(new_select)
        await msg.edit(view=old_view); await ctx.message.delete()

    # ------------------------------------------------------------------
    # E. SISTEM RATING
    # ------------------------------------------------------------------
    @commands.command(name="setup_rating_log")
    @commands.has_permissions(administrator=True)
    async def setup_rating_log(self, ctx, channel: discord.TextChannel):
        if set_rating_log_channel(ctx.guild.id, channel.id): await ctx.send(f"✅ Channel log rating diatur ke {channel.mention}")
        else: await ctx.send("❌ Gagal menyimpan database.")

    @commands.command(name="create_rating")
    @commands.has_permissions(administrator=True)
    async def create_rating(self, ctx, image_url: str = None, *, topic: str):
        await ctx.message.delete()
        avg, count = get_rating_stats(topic)
        embed = discord.Embed(title=f"⭐ Rating: {topic}", description=f"Berikan penilaian Anda untuk **{topic}**!", color=discord.Color.yellow())
        embed.add_field(name="Statistik", value=f"Rata-rata: **{avg}/5.0** ({count} user)")
        if image_url and image_url.startswith("http"): embed.set_image(url=image_url)
        await ctx.send(embed=embed, view=RatingView(topic))

    # ------------------------------------------------------------------
    # LISTENER
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component: return
        cid = interaction.data.get("custom_id", "")

        if cid.startswith("verify:"):
            try:
                role = interaction.guild.get_role(int(cid.split(":")[1]))
                if role:
                    if role in interaction.user.roles: await interaction.response.send_message(f"✅ Sudah punya role {role.mention}!", ephemeral=True)
                    else: await interaction.user.add_roles(role); await interaction.response.send_message(f"✅ Verifikasi berhasil! +{role.mention}", ephemeral=True)
                else: await interaction.response.send_message("❌ Role hilang.", ephemeral=True)
            except: await interaction.response.send_message("❌ Gagal verifikasi.", ephemeral=True)

        elif cid.startswith("rate:"):
            try:
                parts = cid.split(":"); topic = ":".join(parts[1:-1]); stars = int(parts[-1])
                if add_rating(topic, interaction.user.id, stars):
                    avg, count = get_rating_stats(topic)
                    embed = interaction.message.embeds[0]
                    embed.set_field_at(0, name="Statistik", value=f"Rata-rata: **{avg}/5.0** ({count} user)")
                    await interaction.message.edit(embed=embed)
                    await interaction.response.send_message(f"✅ Rating **{stars} ⭐** diterima.", ephemeral=True)
                    
                    lid = get_rating_log_channel(interaction.guild.id)
                    if lid and (lch := self.bot.get_channel(lid)):
                        e = discord.Embed(title="🌟 Rating Masuk", color=discord.Color.gold())
                        e.description = f"**User:** {interaction.user.mention}\n**Topik:** {topic}\n**Nilai:** {'⭐'*stars} ({stars})"
                        e.set_footer(text=f"Total: {count} | Avg: {avg}")
                        await lch.send(embed=e)
            except: pass

    async def cog_load(self):
        self.bot.add_view(RulesView())
        v = ui.View(timeout=None); v.add_item(DynamicRoleSelect()); self.bot.add_view(v)

async def setup(bot):
    await bot.add_cog(DynamicSupportCog(bot))
