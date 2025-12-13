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

# Modal Rating (Sistem Shopee)
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
                # Kita cari embed di pesan original dan update field statistiknya
                # Asumsi statistik ada di field pertama (index 0) atau footer
                embed = self.message_to_update.embeds[0]
                
                # Update field statistik (cari field yang judulnya 'Statistik' atau update field ke-0)
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
        # Opsi dummy agar view bisa di-load, nanti akan di-override oleh opsi asli dari pesan
        safe_options = options if options else [discord.SelectOption(label="Loading...", value="dummy")]
        super().__init__(placeholder=placeholder, min_values=0, max_values=1, options=safe_options, custom_id="dynamic_role_select")

    async def callback(self, interaction: discord.Interaction):
        # Ambil opsi ASLI dari komponen yang diklik user
        # 'self.options' di sini sudah berisi opsi yang ada di pesan Discord saat itu
        selected_values = self.values
        all_options = self.options

        assigned, removed = [], []
        
        # Mapping Value (ID) ke Role Object
        # Kita perlu cek semua opsi yang ada di menu ini
        for option in all_options:
            if not option.value.isdigit(): continue # Skip dummy
            
            role_id = int(option.value)
            role = interaction.guild.get_role(role_id)
            
            if not role: continue

            if option.value in selected_values:
                # Jika dipilih, tambahkan role
                if role not in interaction.user.roles:
                    await interaction.user.add_roles(role)
                    assigned.append(role.name)
            else:
                # Jika tidak dipilih (ada di list tapi tidak di values), hapus role
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

    # --- LISTENER GLOBAL (PERSISTENCE HANDLER) ---
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component: return
        cid = interaction.data.get("custom_id", "")

        # A. Handler Verifikasi
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
            except Exception as e:
                logger.error(f"Verify failed: {e}")
                await interaction.response.send_message("❌ Gagal verifikasi.", ephemeral=True)

        # B. Handler Rating (Membuka Modal)
        elif cid.startswith("rate:"):
            # Format ID: "rate:TOPIK:BINTANG"
            try:
                parts = cid.split(":")
                topic = ":".join(parts[1:-1])
                stars = int(parts[-1])
                
                # Kirim Modal untuk input ulasan
                modal = RatingModal(topic, stars, self.bot, interaction.message)
                await interaction.response.send_modal(modal)
            except Exception as e:
                logger.error(f"Rating modal failed: {e}")
                await interaction.response.send_message("❌ Gagal membuka ulasan.", ephemeral=True)

    # --- COMMANDS: EMBED BUILDER MANUAL ---

    @commands.command(name="create_embed")
    @commands.has_permissions(administrator=True)
    async def create_embed(self, ctx, channel: discord.TextChannel, color_hex: str, title: str, *, description: str):
        """
        Buat embed dasar di channel tertentu.
        Format: !create_embed #channel #HEXWARNA "Judul" "Deskripsi Panjang"
        Contoh: !create_embed #info #FF0000 "Info Server" "Ini adalah deskripsi..."
        """
        try:
            # Konversi hex string ke int color
            if color_hex.startswith("#"): color_hex = color_hex[1:]
            color = int(color_hex, 16)
        except:
            color = 0x3498db # Default blue

        embed = discord.Embed(title=title, description=description, color=color)
        
        # Cek lampiran gambar
        if ctx.message.attachments:
            embed.set_image(url=ctx.message.attachments[0].url)

        msg = await channel.send(embed=embed)
        await ctx.send(f"✅ Embed dibuat di {channel.mention}.\nID Pesan: `{msg.id}`\n(Gunakan ID ini untuk command setup lainnya)", delete_after=20)

    # --- COMMANDS: ATTACHMENT / SETUP ---

    @commands.command(name="setuprole")
    @commands.has_permissions(administrator=True)
    async def setup_role(self, ctx, message_id: int, role: discord.Role, label: str, emoji: str = "🔹"):
        """
        Menambah menu role ke pesan embed yang sudah ada.
        Format: !setuprole [ID_Pesan] [@Role] [Label] [Emoji]
        """
        try:
            msg = await ctx.channel.fetch_message(message_id)
        except:
            return await ctx.send("❌ Pesan tidak ditemukan di channel ini. Pastikan command diketik di channel yang sama dengan pesan.")

        # Ambil view lama atau buat baru
        view = ui.View.from_message(msg)
        view.timeout = None # Persistent

        # Cari Select Menu Role
        select_menu = None
        for child in view.children:
            if isinstance(child, ui.Select) and child.custom_id == "dynamic_role_select":
                select_menu = child
                break
        
        # Jika belum ada, buat baru
        if not select_menu:
            select_menu = DynamicRoleSelect(options=[])
            # Hapus komponen lain jika perlu agar rapi, atau append
            # Untuk amannya kita taruh select menu di row baru atau paling atas
            view.add_item(select_menu)

        # Hapus dummy "Loading" jika ada
        current_options = [opt for opt in select_menu.options if opt.value != "dummy"]
        
        # Tambah Opsi Baru
        if len(current_options) >= 25: return await ctx.send("❌ Maksimal 25 role per menu.")
        
        # Cek duplikat role
        if any(opt.value == str(role.id) for opt in current_options):
            return await ctx.send("❌ Role ini sudah ada di menu.")

        current_options.append(discord.SelectOption(label=label, value=str(role.id), emoji=emoji, description=f"Role: {role.name}"))
        
        # Refresh komponen Select (karena options bersifat read-only di bbrp konteks)
        new_select = DynamicRoleSelect(options=current_options)
        new_select.max_values = len(current_options) # Agar bisa select multiple
        
        # Ganti select menu lama dengan yang baru
        # Kita harus cari indexnya
        for i, item in enumerate(view.children):
            if isinstance(item, ui.Select) and item.custom_id == "dynamic_role_select":
                view.children[i] = new_select
                break
        else:
            # Jika tadi baru dibuat dan belum di-add ke children list dgn benar
            view.add_item(new_select)

        await msg.edit(view=view)
        await ctx.message.delete()
        await ctx.send(f"✅ Opsi **{label}** ditambahkan ke menu.", delete_after=5)

    @commands.command(name="setuplink")
    @commands.has_permissions(administrator=True)
    async def setup_link(self, ctx, message_id: int, label: str, url: str, emoji: str = "🔗"):
        """Format: !setuplink [ID_Pesan] [Label] [URL] [Emoji]"""
        try: msg = await ctx.channel.fetch_message(message_id)
        except: return await ctx.send("❌ Pesan tidak ditemukan.")
        
        view = ui.View.from_message(msg)
        view.timeout = None
        view.add_item(ui.Button(label=label, url=url, emoji=emoji))
        
        await msg.edit(view=view)
        await ctx.message.delete()
        await ctx.send(f"✅ Link **{label}** ditambahkan.", delete_after=5)

    @commands.command(name="setupverify")
    @commands.has_permissions(administrator=True)
    async def setup_verify(self, ctx, message_id: int, role: discord.Role, label: str = "Verifikasi", emoji: str = "✅"):
        """Format: !setupverify [ID_Pesan] [@Role] [Label] [Emoji]"""
        try: msg = await ctx.channel.fetch_message(message_id)
        except: return await ctx.send("❌ Pesan tidak ditemukan.")
        
        view = ui.View.from_message(msg)
        view.timeout = None
        # Tambah tombol verify dengan ID dinamis
        view.add_item(ui.Button(label=label, style=discord.ButtonStyle.success, emoji=emoji, custom_id=f"verify:{role.id}"))
        
        await msg.edit(view=view)
        await ctx.message.delete()
        await ctx.send(f"✅ Tombol Verifikasi untuk **{role.name}** ditambahkan.", delete_after=5)

    @commands.command(name="setuprating")
    @commands.has_permissions(administrator=True)
    async def setup_rating(self, ctx, message_id: int, topic: str):
        """Format: !setuprating [ID_Pesan] [Topik Rating]"""
        try: msg = await ctx.channel.fetch_message(message_id)
        except: return await ctx.send("❌ Pesan tidak ditemukan.")
        
        # Ambil statistik awal
        avg, count = get_rating_stats(topic)
        
        # Update Embed dengan Info Statistik
        if msg.embeds:
            embed = msg.embeds[0]
            embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)
        else:
            embed = discord.Embed(description="Rating Panel")
            embed.add_field(name="📊 Statistik", value=f"⭐ **{avg}/5.0**\n👤 {count} Ulasan", inline=False)

        view = ui.View.from_message(msg)
        view.timeout = None
        
        # Tambahkan 5 tombol bintang
        for i in range(1, 6):
            view.add_item(ui.Button(label=str(i), emoji="⭐", custom_id=f"rate:{topic}:{i}", style=discord.ButtonStyle.secondary))
        
        await msg.edit(embed=embed, view=view)
        await ctx.message.delete()
        await ctx.send(f"✅ Sistem Rating **{topic}** ditambahkan.", delete_after=5)

    # --- RULES SYSTEM ---
    @commands.command(name="set_rules")
    @commands.has_permissions(administrator=True)
    async def set_rules(self, ctx, *, content: str):
        if set_server_rules(ctx.guild.id, content):
            await ctx.send("✅ Rules diperbarui.", delete_after=5)
        else:
            await ctx.send("❌ Gagal simpan rules.")

    @commands.command(name="setup_rating_log")
    @commands.has_permissions(administrator=True)
    async def setup_rating_log(self, ctx, channel: discord.TextChannel):
        if set_rating_log_channel(ctx.guild.id, channel.id):
            await ctx.send(f"✅ Log rating ke {channel.mention}")
        else:
            await ctx.send("❌ Gagal simpan config.")

    # --- COG LOAD ---
    async def cog_load(self):
        # Register Persistent Views
        self.bot.add_view(RulesView())
        
        # Register Role Select Handler (dummy)
        v = ui.View(timeout=None)
        v.add_item(DynamicRoleSelect())
        self.bot.add_view(v)

async def setup(bot):
    await bot.add_cog(DynamicSupportCog(bot))
