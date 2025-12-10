import discord
from discord.ext import commands
from discord import ui
import logging
from utils.database import set_rating_log_channel, get_rating_log_channel, add_rating, get_rating_stats

logger = logging.getLogger(__name__)

# ====================================================
# 1. VIEW HANDLERS (PERSISTENT)
# ====================================================

class DynamicVerifyView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # Handler dinamis untuk tombol verifikasi apapun
    # Custom ID format: "verify:ROLE_ID"
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id", "")
        if custom_id.startswith("verify:"):
            try:
                role_id = int(custom_id.split(":")[1])
                role = interaction.guild.get_role(role_id)
                if role:
                    if role in interaction.user.roles:
                        await interaction.response.send_message(f"✅ Kamu sudah memiliki role {role.mention}!", ephemeral=True)
                    else:
                        await interaction.user.add_roles(role)
                        await interaction.response.send_message(f"✅ Verifikasi berhasil! Kamu mendapatkan role {role.mention}.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Role tidak ditemukan (mungkin sudah dihapus).", ephemeral=True)
            except Exception as e:
                logger.error(f"Verify error: {e}")
                await interaction.response.send_message("❌ Terjadi kesalahan sistem.", ephemeral=True)
            return False # Stop propagation karena sudah dihandle manual
        return True

class RulesView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Baca Rules", style=discord.ButtonStyle.danger, emoji="📜", custom_id="rules:read")
    async def read_rules(self, interaction: discord.Interaction, button: ui.Button):
        # Kita ambil konten rules dari embed pesan aslinya jika ada, atau teks statis
        # Untuk fleksibilitas penuh, user biasanya ingin setup teks rules di sini.
        # Karena keterbatasan button interaction (tidak bisa simpan teks panjang di button), 
        # kita tampilkan rules umum atau instruksi.
        
        embed = discord.Embed(title="📜 Server Rules", color=discord.Color.red())
        # Teks ini statis di sini, tapi di tutorial lanjutan bisa disimpan di footer embed pesan asli
        embed.description = """
        1. Dilarang Spam & Toxic.
        2. Hargai sesama member.
        3. No SARA / NSFW.
        4. Ikuti arahan Staff.
        """
        await interaction.response.send_message(embed=embed, ephemeral=True)

class DynamicRoleSelect(ui.Select):
    def __init__(self, placeholder="Pilih Role...", options=[]):
        super().__init__(
            placeholder=placeholder,
            min_values=0, # Bisa deselect semua
            max_values=len(options) if options else 1, # Bisa pilih banyak
            options=options if options else [discord.SelectOption(label="Default")],
            custom_id="dynamic_role_select" # ID statis, kita baca valuesnya nanti
        )

    async def callback(self, interaction: discord.Interaction):
        # Logic: Role ID disimpan di 'value' opsi select menu
        selected_role_ids = [int(val) for val in self.values]
        
        # Ambil semua role ID yang ada di opsi menu ini (untuk remove yang tidak dipilih)
        all_option_ids = [int(opt.value) for opt in self.options]
        
        assigned = []
        removed = []

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
        # Tambahkan 5 tombol bintang
        for i in range(1, 6):
            self.add_item(ui.Button(label=str(i), emoji="⭐", custom_id=f"rate:{topic_name}:{i}", style=discord.ButtonStyle.secondary))

    # Handler global rating ada di listener Cog karena tombol dibuat dinamis

# ====================================================
# 2. MAIN COG
# ====================================================

class DynamicSupportCog(commands.Cog, name="DynamicSupport"):
    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # A. SISTEM VERIFIKASI (SETUP MANUAL)
    # ------------------------------------------------------------------
    @commands.command(name="setup_verify")
    @commands.has_permissions(administrator=True)
    async def setup_verify(self, ctx, role: discord.Role, image_url: str = None, *, description: str = "Klik tombol di bawah untuk verifikasi."):
        """
        !setup_verify @Role [ImageURL] [Deskripsi]
        Contoh: !setup_verify @Warga https://gambar.com/img.png Klik tombol hijau untuk akses server!
        """
        await ctx.message.delete()
        embed = discord.Embed(title="🔐 Verifikasi Server", description=description, color=discord.Color.green())
        if image_url and image_url.startswith("http"):
            embed.set_image(url=image_url)
        
        # Buat tombol dengan ID khusus berisi Role ID: "verify:123456789"
        view = ui.View(timeout=None)
        btn = ui.Button(label="Verifikasi Sekarang", style=discord.ButtonStyle.success, emoji="✅", custom_id=f"verify:{role.id}")
        view.add_item(btn)
        
        await ctx.send(embed=embed, view=view)

    # ------------------------------------------------------------------
    # B. SISTEM LINKS (SETUP MANUAL)
    # ------------------------------------------------------------------
    @commands.command(name="create_links")
    @commands.has_permissions(administrator=True)
    async def create_links(self, ctx, image_url: str = None, *, description: str = "Daftar Link Resmi Komunitas"):
        """Buat panel link kosong. Nanti tombol ditambah pakai !add_link"""
        await ctx.message.delete()
        embed = discord.Embed(title="🔗 Official Links", description=description, color=discord.Color.blue())
        if image_url and image_url.startswith("http"):
            embed.set_image(url=image_url)
        
        # Kirim pesan kosong view dulu
        msg = await ctx.send(embed=embed)
        await ctx.send(f"Panel Link dibuat! ID Pesan: `{msg.id}`.\nGunakan `!add_link {msg.id} [Label] [URL] [Emoji]` untuk menambah tombol.", delete_after=15)

    @commands.command(name="add_link")
    @commands.has_permissions(administrator=True)
    async def add_link(self, ctx, message_id: int, label: str, url: str, emoji: str = "🔗"):
        """Menambah tombol link ke panel yang sudah ada."""
        try:
            msg = await ctx.channel.fetch_message(message_id)
        except:
            return await ctx.send("❌ Pesan tidak ditemukan di channel ini.")

        # Ambil view lama atau buat baru
        view = ui.View.from_message(msg)
        
        # Tambah tombol URL (Link Button tidak butuh persistent handler)
        view.add_item(ui.Button(label=label, url=url, emoji=emoji))
        
        await msg.edit(view=view)
        await ctx.message.delete()
        await ctx.send(f"✅ Link **{label}** ditambahkan.", delete_after=3)

    # ------------------------------------------------------------------
    # C. SISTEM SELECT ROLE (SETUP MANUAL)
    # ------------------------------------------------------------------
    @commands.command(name="create_role_menu")
    @commands.has_permissions(administrator=True)
    async def create_role_menu(self, ctx, image_url: str = None, *, description: str = "Pilih role di bawah:"):
        """Buat panel select role kosong."""
        await ctx.message.delete()
        embed = discord.Embed(title="🎭 Self Roles", description=description, color=discord.Color.gold())
        if image_url and image_url.startswith("http"):
            embed.set_image(url=image_url)

        # View awal kosong
        msg = await ctx.send(embed=embed)
        await ctx.send(f"Panel Role dibuat! ID Pesan: `{msg.id}`.\nGunakan `!add_role_option {msg.id} @Role [Label] [Emoji]`", delete_after=15)

    @commands.command(name="add_role_option")
    @commands.has_permissions(administrator=True)
    async def add_role_option(self, ctx, message_id: int, role: discord.Role, label: str, emoji: str = "🔹"):
        """
        Menambah opsi role ke dropdown menu di pesan tertentu.
        Contoh: !add_role_option 123456789 @Jakarta "Warga Jakarta" 🏙️
        """
        try:
            msg = await ctx.channel.fetch_message(message_id)
        except:
            return await ctx.send("❌ Pesan tidak ditemukan.")

        # Ambil komponen Select lama jika ada
        old_view = ui.View.from_message(msg)
        select_menu = None
        
        # Cari apakah sudah ada Select Menu di view
        for item in old_view.children:
            if isinstance(item, ui.Select) and item.custom_id == "dynamic_role_select":
                select_menu = item
                break
        
        # Jika belum ada, buat baru
        if not select_menu:
            select_menu = DynamicRoleSelect(placeholder="Klik untuk memilih role...", options=[])
            # Kita harus clear items dulu agar urutan rapi jika ada tombol lain (jarang)
            old_view.clear_items()
            old_view.add_item(select_menu)
        
        # Hapus opsi default placeholder jika ada
        current_options = [opt for opt in select_menu.options if opt.label != "Default"]
        
        # Cek limit (Discord max 25 options)
        if len(current_options) >= 25:
            return await ctx.send("❌ Maksimal 25 role per menu.")

        # Tambah Opsi Baru (Value = Role ID)
        new_option = discord.SelectOption(label=label, value=str(role.id), emoji=emoji, description=f"Role: {role.name}")
        current_options.append(new_option)
        
        # Re-create select dengan opsi baru
        select_menu.options = current_options
        select_menu.max_values = len(current_options) # Update agar bisa select multiple
        
        await msg.edit(view=old_view)
        await ctx.message.delete()
        await ctx.send(f"✅ Opsi **{label}** ({role.name}) ditambahkan.", delete_after=3)

    # ------------------------------------------------------------------
    # D. SISTEM RATING & PENGUMUMAN (SETUP MANUAL)
    # ------------------------------------------------------------------
    @commands.command(name="setup_rating_log")
    @commands.has_permissions(administrator=True)
    async def setup_rating_log(self, ctx, channel: discord.TextChannel):
        """Set channel untuk log pengumuman rating."""
        if set_rating_log_channel(ctx.guild.id, channel.id):
            await ctx.send(f"✅ Channel log rating diatur ke {channel.mention}")
        else:
            await ctx.send("❌ Gagal menyimpan database.")

    @commands.command(name="create_rating")
    @commands.has_permissions(administrator=True)
    async def create_rating(self, ctx, image_url: str = None, *, topic: str):
        """
        Buat panel rating.
        Contoh: !create_rating https://img.url "Kinerja Admin"
        """
        await ctx.message.delete()
        
        # Ambil statistik awal
        avg, count = get_rating_stats(topic)
        
        embed = discord.Embed(title=f"⭐ Rating: {topic}", description=f"Berikan penilaian Anda untuk **{topic}**!", color=discord.Color.yellow())
        embed.add_field(name="Statistik", value=f"Rata-rata: **{avg}/5.0** ({count} user)")
        if image_url and image_url.startswith("http"):
            embed.set_image(url=image_url)
        
        await ctx.send(embed=embed, view=RatingView(topic))

    # --- LISTENER UNTUK TOMBOL RATING DINAMIS ---
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        # Handle tombol rating secara global karena custom_id-nya dinamis
        if interaction.type != discord.InteractionType.component: return
        
        custom_id = interaction.data.get("custom_id", "")
        
        # Format ID: "rate:TOPIK:BINTANG" -> "rate:Kinerja Admin:5"
        if custom_id.startswith("rate:"):
            try:
                parts = custom_id.split(":")
                # Gabungkan kembali bagian tengah jika topik mengandung titik dua
                topic = ":".join(parts[1:-1]) 
                stars = int(parts[-1])
                
                # Simpan ke DB
                success = add_rating(topic, interaction.user.id, stars)
                
                if success:
                    # Ambil stats baru
                    avg, count = get_rating_stats(topic)
                    
                    # Update pesan panel rating dengan statistik baru
                    embed = interaction.message.embeds[0]
                    # Update field statistik (biasanya field ke-0)
                    embed.set_field_at(0, name="Statistik", value=f"Rata-rata: **{avg}/5.0** ({count} user)")
                    await interaction.message.edit(embed=embed)
                    
                    await interaction.response.send_message(f"✅ Terima kasih! Anda memberi **{stars} ⭐** untuk **{topic}**.", ephemeral=True)
                    
                    # Kirim Log Pengumuman
                    log_channel_id = get_rating_log_channel(interaction.guild.id)
                    if log_channel_id:
                        log_channel = self.bot.get_channel(log_channel_id)
                        if log_channel:
                            log_embed = discord.Embed(title="🌟 Rating Masuk", color=discord.Color.gold())
                            log_embed.description = f"**User:** {interaction.user.mention}\n**Topik:** {topic}\n**Nilai:** {'⭐'*stars} ({stars})"
                            log_embed.set_footer(text=f"Akumulasi: {avg} rata-rata dari {count} user")
                            await log_channel.send(embed=log_embed)
                else:
                    await interaction.response.send_message("❌ Gagal menyimpan rating (Database error).", ephemeral=True)
            except Exception as e:
                logger.error(f"Rating interaction error: {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Error sistem rating.", ephemeral=True)

    # Listener untuk Persistent Views di-load saat bot nyala
    # Agar tombol Verify dan Role Select tetap jalan setelah restart
    async def cog_load(self):
        # Kita tambahkan handler Verify umum
        self.bot.add_view(DynamicVerifyView())
        # Kita tambahkan handler Role Select umum (kosong gpp, yg penting custom_id match)
        self.bot.add_view(ui.View().add_item(DynamicRoleSelect()))

async def setup(bot):
    await bot.add_cog(DynamicSupportCog(bot))
