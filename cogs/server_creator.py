import discord
from discord.ext import commands
from discord import ui, app_commands
import random
import asyncio
import logging
from typing import List, Dict, Any

# Mengambil logger
logger = logging.getLogger(__name__)

# =================================================================================
# TEMPLATE STRUKTUR SERVER UNTUK GTA/SAMP ROLEPLAY
# =================================================================================
# Anda bisa menambahkan lebih banyak template di sini dengan kunci yang berbeda.
# Contoh: "valorant", "minecraft-smp", dll.
SERVER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "gta-roleplay": {
        "name": "GTA V / SAMP Roleplay",
        "description": "Template server yang dioptimalkan untuk komunitas roleplay.",
        "categories": [
            {
                "name": "🏁║SELAMAT DATANG",
                "channels": [
                    {"type": "text", "name": "💬│obrolan-umum"},
                    {"type": "text", "name": "📜│peraturan"},
                    {"type": "text", "name": "📢│pengumuman"},
                ]
            },
            {
                "name": "📜║INFORMASI SERVER",
                "channels": [
                    {"type": "text", "name": "📚│panduan-roleplay"},
                    {"type": "text", "name": "🗺️│peta-server"},
                    {"type": "text", "name": "💼│lowongan-pekerjaan"},
                ]
            },
            {
                "name": "🎭║IC ZONE",
                "channels": [
                    {"type": "text", "name": "📱│social-media-ic"},
                    {"type": "text", "name": "📰│berita-los-santos"},
                    {"type": "voice", "name": "🎙️ Voice RP 1"},
                    {"type": "voice", "name": "🎙️ Voice RP 2"},
                ]
            },
            {
                "name": "🔧║MODDING & SCRIPT",
                "channels": [
                    {"type": "text", "name": "📦│share-mod"},
                    {"type": "text", "name": "💡│diskusi-script"},
                    {"type": "forum", "name": "bantuan-teknis"},
                ]
            },
            {
                "name": "🎮║OOC (Out of Character)",
                "channels": [
                    {"type": "text", "name": "😂│meme-zone"},
                    {"type": "text", "name": "📸│share-screenshot"},
                    {"type": "voice", "name": "🎧 Voice Santai"},
                ]
            }
        ],
        "roles": [
            {"name": "👑 Admin", "permissions": discord.Permissions(administrator=True), "color": discord.Color.red()},
            {"name": "🛡️ Moderator", "permissions": discord.Permissions(manage_messages=True, kick_members=True, ban_members=True), "color": discord.Color.blue()},
            {"name": "✅ Terverifikasi", "permissions": discord.Permissions.general(), "color": discord.Color.green()},
            {"name": "🤖 Bot", "permissions": discord.Permissions.none(), "color": discord.Color.dark_grey()}
        ]
    }
}

# =================================================================================
# UI COMPONENTS (VIEWS, SELECTS, MODALS)
# =================================================================================

class CategorySelect(ui.Select):
    """Dropdown untuk memilih kategori yang akan dibuat."""
    def __init__(self, categories: List[Dict[str, Any]]):
        self.category_options = categories
        options = [
            discord.SelectOption(label=cat['name'], value=str(i), description=f"{len(cat['channels'])} channel di dalamnya.")
            for i, cat in enumerate(categories)
        ]
        super().__init__(placeholder="Pilih kategori yang ingin dibuat...", min_values=1, max_values=len(options), options=options)

    async def callback(self, interaction: discord.Interaction):
        # Menyimpan pilihan di view untuk diakses nanti
        self.view.selected_indices = self.values
        await interaction.response.defer()

class ServerBuilderView(ui.View):
    """View utama yang menampilkan pilihan kategori dan tombol aksi."""
    def __init__(self, author: discord.User, template: Dict[str, Any]):
        super().__init__(timeout=300)
        self.author = author
        self.template = template
        self.selected_indices: List[str] = []

        self.category_select = CategorySelect(template['categories'])
        self.add_item(self.category_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Hanya pembuat permintaan yang dapat berinteraksi.", ephemeral=True)
            return False
        return True

    async def _disable_all_items(self):
        for item in self.children:
            item.disabled = True

    @ui.button(label="Bangun Server", style=discord.ButtonStyle.green, emoji="✅", row=1)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if not self.selected_indices:
            await interaction.response.send_message("Anda harus memilih setidaknya satu kategori.", ephemeral=True)
            return

        await self._disable_all_items()
        await interaction.response.edit_message(content="⏳ Membangun struktur server... Ini mungkin memakan waktu beberapa saat.", view=self)

        guild = interaction.guild
        log_messages = []

        # --- Proses Pembuatan Role ---
        if self.template.get("roles"):
            log_messages.append("**Membuat Roles...**")
            existing_roles = {role.name: role for role in guild.roles}
            for role_data in self.template["roles"]:
                role_name = role_data["name"]
                if role_name not in existing_roles:
                    try:
                        await guild.create_role(
                            name=role_name,
                            permissions=role_data.get("permissions", discord.Permissions.none()),
                            color=role_data.get("color", discord.Color.default())
                        )
                        log_messages.append(f"✅ Role `{role_name}` berhasil dibuat.")
                    except Exception as e:
                        log_messages.append(f"❌ Gagal membuat role `{role_name}`: {e}")
                else:
                    log_messages.append(f"🟡 Role `{role_name}` sudah ada, dilewati.")
            await asyncio.sleep(1) # Jeda untuk menghindari rate limit

        # --- Proses Pembuatan Kategori dan Channel ---
        log_messages.append("\n**Membangun Kategori & Channel...**")
        for index_str in self.selected_indices:
            index = int(index_str)
            cat_data = self.template['categories'][index]
            cat_name = cat_data['name']
            
            try:
                # Buat kategori
                new_category = await guild.create_category(name=cat_name)
                log_messages.append(f"✅ Kategori `{cat_name}` berhasil dibuat.")

                # Buat channel di dalamnya
                for channel_data in cat_data['channels']:
                    ch_name = channel_data['name']
                    ch_type = channel_data['type']
                    try:
                        if ch_type == 'text':
                            await new_category.create_text_channel(name=ch_name)
                        elif ch_type == 'voice':
                            await new_category.create_voice_channel(name=ch_name)
                        elif ch_type == 'forum':
                            await new_category.create_forum(name=ch_name)
                        log_messages.append(f"  - Channel `{ch_name}` (`{ch_type}`) dibuat.")
                    except Exception as e:
                        log_messages.append(f"  - ❌ Gagal membuat channel `{ch_name}`: {e}")
                    await asyncio.sleep(0.5) # Jeda kecil
            except Exception as e:
                log_messages.append(f"❌ Gagal membuat kategori `{cat_name}`: {e}")
        
        log_messages.append("\n**Pembangunan Selesai!** 🎉")
        
        # Kirim log ke channel
        log_content = "\n".join(log_messages)
        embed = discord.Embed(title="Laporan Pembangunan Server", description=log_content, color=discord.Color.green())
        await interaction.followup.send(embed=embed)


    @ui.button(label="Batal", style=discord.ButtonStyle.red, emoji="❌", row=1)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await self._disable_all_items()
        await interaction.response.edit_message(content="Pembangunan server dibatalkan.", embed=None, view=self)

    @ui.button(label="Refresh", style=discord.ButtonStyle.blurple, emoji="🔁", row=1)
    async def refresh(self, interaction: discord.Interaction, button: ui.Button):
        # Mengirim ulang view yang sama untuk mereset pilihan
        new_view = ServerBuilderView(self.author, self.template)
        embed = interaction.message.embeds[0]
        await interaction.response.edit_message(content=interaction.message.content, embed=embed, view=new_view)

# =================================================================================
# KELAS COG UTAMA (SERVER CREATOR)
# =================================================================================

class ServerCreatorCog(commands.Cog, name="ServerCreator"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="createserver", help="Membuat struktur server lengkap dari template.")
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 120, commands.BucketType.user)
    async def create_server(self, ctx: commands.Context, template_name: str = "gta-roleplay"):
        """
        Memulai proses pembuatan server interaktif berdasarkan template.
        Saat ini hanya template 'gta-roleplay' yang tersedia.
        """
        template = SERVER_TEMPLATES.get(template_name.lower())
        if not template:
            await ctx.send(f"❌ Template `{template_name}` tidak ditemukan. Template yang tersedia: `{', '.join(SERVER_TEMPLATES.keys())}`")
            return

        embed = discord.Embed(
            title=f"🤖 AI Server Builder - Template: {template['name']}",
            description=(
                f"{template['description']}\n\n"
                "**Langkah 1:** Pilih kategori yang ingin Anda buat dari menu dropdown di bawah.\n"
                "**Langkah 2:** Tekan tombol 'Bangun Server' untuk memulai proses."
            ),
            color=0x5865F2
        )
        embed.set_footer(text="Anda dapat me-refresh pilihan atau membatalkan kapan saja.")

        view = ServerBuilderView(ctx.author, template)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="createcategory", help="Membuat satu kategori dengan channel dasar.")
    @commands.has_permissions(manage_channels=True)
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def create_category(self, ctx: commands.Context, *, category_name: str):
        """
        Membuat sebuah kategori baru beserta channel teks dan suara dasar.
        Contoh: !createcategory  zona-event
        """
        msg = await ctx.send(f"⚙️ Membuat kategori `{category_name}`...")
        try:
            # Emoji acak untuk variasi
            emojis = ["📁", "📌", "✅", "💡", "⭐", "🔧", "🧩"]
            random_emoji = random.choice(emojis)
            
            new_category = await ctx.guild.create_category(name=f"{random_emoji}│{category_name.upper()}")
            await new_category.create_text_channel(name="💬│diskusi")
            await new_category.create_voice_channel(name="🎙️ Voice Chat")

            await msg.edit(content=f"✅ Kategori `{category_name}` berhasil dibuat dengan channel dasar.")
        except Exception as e:
            await msg.edit(content=f"❌ Gagal membuat kategori: {e}")

    @commands.command(name="deletechannel", help="Menghapus channel berdasarkan nama.")
    @commands.has_permissions(manage_channels=True)
    async def delete_channel(self, ctx: commands.Context, *, channel_name: str):
        """
        Menghapus sebuah channel teks atau suara berdasarkan namanya.
        Contoh: !deletechannel diskusi-lama
        """
        # Mencari channel dengan mencocokkan nama (case-insensitive)
        channel_to_delete = discord.utils.get(ctx.guild.channels, name=channel_name)
        
        if channel_to_delete:
            try:
                await channel_to_delete.delete(reason=f"Dihapus oleh {ctx.author}")
                await ctx.send(f"✅ Channel `{channel_name}` berhasil dihapus.")
            except Exception as e:
                await ctx.send(f"❌ Gagal menghapus channel: {e}")
        else:
            await ctx.send(f"⚠️ Channel dengan nama `{channel_name}` tidak ditemukan.")

    @commands.command(name="deletecategory", help="Menghapus kategori dan semua isinya.")
    @commands.has_permissions(manage_channels=True)
    async def delete_category(self, ctx: commands.Context, *, category_name: str):
        """
        Menghapus sebuah kategori dan SEMUA channel di dalamnya.
        PERHATIAN: Aksi ini tidak dapat diurungkan.
        Contoh: !deletecategory zona-event
        """
        category_to_delete = discord.utils.get(ctx.guild.categories, name=category_name)
        
        if not category_to_delete:
            await ctx.send(f"⚠️ Kategori `{category_name}` tidak ditemukan.")
            return

        # --- View Konfirmasi ---
        class ConfirmationView(ui.View):
            def __init__(self, author):
                super().__init__(timeout=60)
                self.author = author
                self.confirmed = False

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                return interaction.user.id == self.author.id

            @ui.button(label="Ya, Hapus Semua", style=discord.ButtonStyle.danger)
            async def confirm(self, interaction: discord.Interaction, button: ui.Button):
                self.confirmed = True
                self.stop()
                await interaction.response.defer()

            @ui.button(label="Batal", style=discord.ButtonStyle.secondary)
            async def cancel(self, interaction: discord.Interaction, button: ui.Button):
                self.stop()
                await interaction.response.defer()

        view = ConfirmationView(ctx.author)
        warning_msg = await ctx.send(
            f"🚨 **PERINGATAN!** Anda akan menghapus kategori `{category_name}` dan **semua channel di dalamnya**. Aksi ini permanen. Yakin ingin melanjutkan?",
            view=view
        )

        await view.wait()
        await warning_msg.delete()

        if view.confirmed:
            processing_msg = await ctx.send(f"⏳ Menghapus kategori `{category_name}`...")
            try:
                # Buat salinan daftar channel karena koleksi aslinya akan berubah saat iterasi
                channels_to_delete = list(category_to_delete.channels)
                for channel in channels_to_delete:
                    await channel.delete(reason=f"Bagian dari penghapusan kategori oleh {ctx.author}")
                    await asyncio.sleep(0.5)
                
                # Hapus kategori itu sendiri
                await category_to_delete.delete(reason=f"Dihapus oleh {ctx.author}")

                # Setelah selesai, edit pesan asli.
                await processing_msg.edit(content=f"✅ Kategori `{category_name}` dan semua isinya berhasil dihapus.")
            
            except discord.errors.NotFound:
                # Ini terjadi jika channel tempat pesan dikirim telah dihapus.
                # Kita tidak bisa mengedit pesan lagi, jadi kita log saja dan tidak melakukan apa-apa.
                logger.info(f"Berhasil menghapus kategori '{category_name}', tetapi tidak dapat mengirim konfirmasi karena channel asal sudah dihapus.")
                
            except Exception as e:
                logger.error(f"Terjadi kesalahan saat menghapus kategori {category_name}: {e}", exc_info=True)
                # Coba edit pesan asli dengan pesan error.
                try:
                    await processing_msg.edit(content=f"❌ Terjadi kesalahan saat menghapus: {e}")
                except discord.errors.NotFound:
                    # Jika channel asli sudah tidak ada, kita tidak bisa melakukan apa-apa.
                    logger.warning(f"Tidak dapat mengirim pesan error untuk penghapusan '{category_name}' karena channel asal sudah dihapus.")
        else:
            await ctx.send("Penghapusan kategori dibatalkan.", delete_after=10)


    # Error handler untuk cog ini
    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(f"❌ Anda tidak memiliki izin yang diperlukan untuk menjalankan perintah ini. Izin yang dibutuhkan: `{', '.join(error.missing_permissions)}`")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Perintah ini sedang dalam cooldown. Coba lagi dalam **{error.retry_after:.1f} detik**.")
        else:
            logger.error(f"Error pada cog ServerCreator: {error}", exc_info=True)
            # await ctx.send("Terjadi kesalahan yang tidak diketahui.")

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerCreatorCog(bot))

