import discord
from discord.ext import commands
from discord import ui
import asyncio
import logging
from typing import List, Dict, Any, Optional

# Mengambil logger
logger = logging.getLogger(__name__)

# =================================================================================
# TEMPLATE STRUKTUR SERVER (VERSI BARU DENGAN LEBIH BANYAK VARIASI)
# =================================================================================
SERVER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "gta-roleplay": {
        "name": "GTA V / SAMP Roleplay",
        "description": "Template server modern yang dioptimalkan untuk komunitas roleplay interaktif.",
        "categories": [
            {
                "name": "🚀║START HERE",
                "channels": [
                    {"type": "text", "name": "✨│welcome"},
                    {"type": "text", "name": "📜│rules-and-lore"},
                    {"type": "text", "name": "📢│announcements"},
                ]
            },
            {
                "name": "📚║SERVER GUIDES",
                "channels": [
                    {"type": "text", "name": "🤖│bot-commands"},
                    {"type": "text", "name": "🗺️│server-maps"},
                    {"type": "text", "name": "💼│job-list"},
                ]
            },
            {
                "name": "🎬║ROLEPLAY ZONES",
                "channels": [
                    {"type": "text", "name": "📱│ic-social-media"},
                    {"type": "text", "name": "📰│los-santos-news"},
                    {"type": "forum", "name": "character-stories"},
                    {"type": "voice", "name": "🎙️ Downtown RP"},
                    {"type": "voice", "name": "🎙️ Vinewood RP"},
                ]
            },
            {
                "name": "🛠️║WORKSHOP",
                "channels": [
                    {"type": "text", "name": "📦│mod-showcase"},
                    {"type": "text", "name": "💡│script-discussion"},
                    {"type": "text", "name": "🆘│tech-support"},
                ]
            },
            {
                "name": "☕║COMMUNITY HUB",
                "channels": [
                    {"type": "text", "name": "😂│meme-gallery"},
                    {"type": "text", "name": "📸│screenshots"},
                    {"type": "text", "name": "🎵│music"},
                    {"type": "voice", "name": "🎧 Chill & Chat"},
                ]
            }
        ],
        "roles": [
            {"name": "👑 Server Owner", "permissions": discord.Permissions(administrator=True), "color": 0xFFD700}, # Gold
            {"name": "🛡️ Head Admin", "permissions": discord.Permissions(manage_guild=True, ban_members=True), "color": 0xE74C3C}, # Red
            {"name": "👮 Moderator", "permissions": discord.Permissions(manage_messages=True, kick_members=True), "color": 0x3498DB}, # Blue
            {"name": "✅ Verified Citizen", "permissions": discord.Permissions.general(), "color": 0x2ECC71}, # Green
            {"name": "🤖 Bot Army", "permissions": discord.Permissions.none(), "color": 0x95A5A6} # Grey
        ]
    }
}

# =================================================================================
# UI COMPONENTS (Tombol, Tampilan, dan Modal)
# =================================================================================

class ChannelToggleButton(ui.Button):
    """Tombol kustom yang dapat di-toggle untuk memilih atau membatalkan pilihan channel."""
    def __init__(self, category_name: str, channel_data: Dict[str, str], selected: bool = True):
        self.category_name = category_name
        self.channel_data = channel_data
        self.selected = selected
        
        # Atur style dan label berdasarkan status terpilih
        style = discord.ButtonStyle.green if self.selected else discord.ButtonStyle.secondary
        emoji = {"text": "💬", "voice": "🎙️", "forum": "📰"}.get(channel_data["type"], "❓")
        super().__init__(label=channel_data["name"], style=style, emoji=emoji)

    async def callback(self, interaction: discord.Interaction):
        self.selected = not self.selected
        self.style = discord.ButtonStyle.green if self.selected else discord.ButtonStyle.secondary
        
        # Panggil fungsi update di parent view
        if isinstance(self.view, ChannelSelectionView):
            await self.view.update_selection(self.category_name, self.channel_data, self.selected)
        
        await interaction.response.edit_message(view=self.view)

class ChannelSelectionView(ui.View):
    """Tampilan interaktif untuk memilih channel yang akan dibuat."""
    def __init__(self, author: discord.User, template: Dict[str, Any]):
        super().__init__(timeout=600)  # Timeout 10 menit
        self.author = author
        self.template = template
        # Inisialisasi semua channel sebagai terpilih secara default
        self.selections: Dict[str, List[Dict]] = {
            cat['name']: list(cat['channels']) for cat in self.template['categories']
        }

        # Buat tombol untuk setiap channel
        for category in self.template['categories']:
            for channel in category['channels']:
                self.add_item(ChannelToggleButton(category['name'], channel))

        # Tambahkan tombol aksi di baris baru
        self.add_item(self.ConfirmButton())
        self.add_item(self.CancelButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Hanya pembuat permintaan yang dapat berinteraksi.", ephemeral=True)
            return False
        return True

    async def update_selection(self, category_name: str, channel_data: Dict, selected: bool):
        """Memperbarui daftar channel yang dipilih."""
        if selected:
            if channel_data not in self.selections[category_name]:
                self.selections[category_name].append(channel_data)
        else:
            if channel_data in self.selections[category_name]:
                self.selections[category_name].remove(channel_data)

    async def _disable_all_items(self):
        for item in self.children:
            item.disabled = True

    # Mendefinisikan tombol aksi sebagai inner class agar bisa mengakses state view
    class ConfirmButton(ui.Button):
        def __init__(self):
            super().__init__(label="Buat Server Sesuai Pilihan", style=discord.ButtonStyle.primary, emoji="🚀", row=4)

        async def callback(self, interaction: discord.Interaction):
            view: 'ChannelSelectionView' = self.view
            await view._disable_all_items()
            await interaction.response.edit_message(content="⏳ Membangun struktur server... Ini mungkin memakan waktu beberapa saat.", embed=None, view=view)
            
            guild = interaction.guild
            log_messages = []

            # --- Proses Pembuatan Role ---
            if view.template.get("roles"):
                log_messages.append("**Membuat Roles...**")
                for role_data in view.template["roles"]:
                    try:
                        if discord.utils.get(guild.roles, name=role_data["name"]) is None:
                            await guild.create_role(**role_data)
                            log_messages.append(f"✅ Role `{role_data['name']}` dibuat.")
                        else:
                            log_messages.append(f"🟡 Role `{role_data['name']}` sudah ada.")
                    except Exception as e:
                        log_messages.append(f"❌ Gagal membuat role `{role_data['name']}`: {e}")
                await asyncio.sleep(1)

            # --- Proses Pembuatan Kategori dan Channel ---
            log_messages.append("\n**Membangun Kategori & Channel...**")
            for cat_name, channels in view.selections.items():
                if not channels: continue # Lewati kategori jika tidak ada channel yang dipilih

                try:
                    new_category = await guild.create_category(name=cat_name)
                    log_messages.append(f"✅ Kategori `{cat_name}` dibuat.")
                    for ch_data in channels:
                        try:
                            ch_type, ch_name = ch_data['type'], ch_data['name']
                            if ch_type == 'text': await new_category.create_text_channel(name=ch_name)
                            elif ch_type == 'voice': await new_category.create_voice_channel(name=ch_name)
                            elif ch_type == 'forum': await new_category.create_forum(name=ch_name)
                            log_messages.append(f"  - Channel `{ch_name}` (`{ch_type}`) dibuat.")
                        except Exception as e:
                            log_messages.append(f"  - ❌ Gagal membuat channel `{ch_name}`: {e}")
                        await asyncio.sleep(0.5)
                except Exception as e:
                    log_messages.append(f"❌ Gagal membuat kategori `{cat_name}`: {e}")
            
            log_messages.append("\n**Pembangunan Selesai!** 🎉")
            embed = discord.Embed(title="Laporan Pembangunan Server", description="\n".join(log_messages), color=discord.Color.green())
            await interaction.followup.send(embed=embed)

    class CancelButton(ui.Button):
        def __init__(self):
            super().__init__(label="Batal", style=discord.ButtonStyle.red, emoji="❌", row=4)

        async def callback(self, interaction: discord.Interaction):
            view: 'ChannelSelectionView' = self.view
            await view._disable_all_items()
            await interaction.response.edit_message(content="Pembangunan server dibatalkan.", embed=None, view=view)


class InitialView(ui.View):
    """Tampilan awal untuk memulai proses konfigurasi."""
    def __init__(self, author: discord.User, template: Dict[str, Any]):
        super().__init__(timeout=300)
        self.author = author
        self.template = template

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    @ui.button(label="Mulai Konfigurasi Server", style=discord.ButtonStyle.blurple, emoji="🔧")
    async def start_configuration(self, interaction: discord.Interaction, button: ui.Button):
        button.disabled = True
        await interaction.response.edit_message(view=self)

        # Buat embed yang menampilkan Rangkuman Template
        embed = discord.Embed(
            title="🛠️ Konfigurasi Channel & Kategori",
            description="Pilih atau batalkan pilihan channel yang ingin Anda buat. Secara default, semua channel telah dipilih. Klik tombol untuk membatalkan pilihan.",
            color=0x5865F2
        )
        # Menampilkan kategori dan role yang akan dibuat
        for category in self.template['categories']:
            channel_list = ", ".join([f"`{ch['name']}`" for ch in category['channels']])
            embed.add_field(name=category['name'], value=channel_list or "Tidak ada channel", inline=False)
        
        roles_list = ", ".join([f"`{role['name']}`" for role in self.template['roles']])
        embed.add_field(name="🎭 Roles yang akan Dibuat", value=roles_list or "Tidak ada", inline=False)
        
        view = ChannelSelectionView(self.author, self.template)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


# =================================================================================
# KELAS COG UTAMA (SERVER CREATOR)
# =================================================================================

class ServerCreatorCog(commands.Cog, name="ServerCreator"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="createserver", help="Membuat struktur server lengkap dari template secara interaktif.")
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 120, commands.BucketType.user)
    async def create_server(self, ctx: commands.Context, template_name: str = "gta-roleplay"):
        template = SERVER_TEMPLATES.get(template_name.lower())
        if not template:
            return await ctx.send(f"❌ Template `{template_name}` tidak ditemukan.")

        embed = discord.Embed(
            title=f"🤖 AI Server Builder - Template: {template['name']}",
            description=(
                f"{template['description']}\n\n"
                "Tekan tombol di bawah untuk memulai konfigurasi detail channel dan kategori yang ingin Anda buat."
            ),
            color=0x5865F2
        )
        embed.set_footer(text="Proses ini interaktif dan Anda memiliki kontrol penuh.")
        view = InitialView(ctx.author, template)
        await ctx.send(embed=embed, view=view)
    
    # ... (Perintah createcategory, deletechannel, deletecategory tidak diubah dan tetap ada di sini) ...
    @commands.command(name="createcategory", help="Membuat satu kategori dengan channel dasar.")
    @commands.has_permissions(manage_channels=True)
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def create_category(self, ctx: commands.Context, *, category_name: str):
        msg = await ctx.send(f"⚙️ Membuat kategori `{category_name}`...")
        try:
            emojis = ["📁", "📌", "✅", "💡", "⭐", "🔧", "🧩"]
            random_emoji = random.choice(emojis)
            new_category = await ctx.guild.create_category(name=f"{random_emoji}│{category_name.upper()}")
            await new_category.create_text_channel(name="💬│diskusi")
            await new_category.create_voice_channel(name="🎙️ Voice Chat")
            await msg.edit(content=f"✅ Kategori `{category_name}` berhasil dibuat.")
        except Exception as e:
            await msg.edit(content=f"❌ Gagal membuat kategori: {e}")

    @commands.command(name="deletechannel", help="Menghapus channel berdasarkan nama.")
    @commands.has_permissions(manage_channels=True)
    async def delete_channel(self, ctx: commands.Context, *, channel_name: str):
        channel_to_delete = discord.utils.get(ctx.guild.channels, name=channel_name)
        if channel_to_delete:
            try:
                await channel_to_delete.delete(reason=f"Dihapus oleh {ctx.author}")
                await ctx.send(f"✅ Channel `{channel_name}` berhasil dihapus.")
            except Exception as e:
                await ctx.send(f"❌ Gagal menghapus channel: {e}")
        else:
            await ctx.send(f"⚠️ Channel `{channel_name}` tidak ditemukan.")

    @commands.command(name="deletecategory", help="Menghapus kategori dan semua isinya.")
    @commands.has_permissions(manage_channels=True)
    async def delete_category(self, ctx: commands.Context, *, category_name: str):
        category_to_delete = discord.utils.get(ctx.guild.categories, name=category_name)
        if not category_to_delete:
            return await ctx.send(f"⚠️ Kategori `{category_name}` tidak ditemukan.")

        class ConfirmationView(ui.View):
            def __init__(self, author):
                super().__init__(timeout=60)
                self.author = author
                self.confirmed = False
            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                return interaction.user.id == self.author.id
            @ui.button(label="Ya, Hapus Semua", style=discord.ButtonStyle.danger)
            async def confirm(self, interaction: discord.Interaction, button: ui.Button):
                self.confirmed = True; self.stop(); await interaction.response.defer()
            @ui.button(label="Batal", style=discord.ButtonStyle.secondary)
            async def cancel(self, interaction: discord.Interaction, button: ui.Button):
                self.stop(); await interaction.response.defer()

        view = ConfirmationView(ctx.author)
        warning_msg = await ctx.send(f"🚨 **PERINGATAN!** Anda akan menghapus `{category_name}` dan semua channel di dalamnya. Aksi ini permanen.", view=view)
        await view.wait()
        await warning_msg.delete()

        if view.confirmed:
            processing_msg = await ctx.send(f"⏳ Menghapus kategori `{category_name}`...")
            try:
                channels_to_delete = list(category_to_delete.channels)
                for channel in channels_to_delete:
                    await channel.delete(reason=f"Penghapusan kategori oleh {ctx.author}"); await asyncio.sleep(0.5)
                await category_to_delete.delete(reason=f"Dihapus oleh {ctx.author}")
                await processing_msg.edit(content=f"✅ Kategori `{category_name}` berhasil dihapus.")
            except discord.errors.NotFound:
                logger.info(f"Berhasil menghapus '{category_name}', channel konfirmasi sudah terhapus.")
            except Exception as e:
                logger.error(f"Error saat menghapus {category_name}: {e}", exc_info=True)
                try: await processing_msg.edit(content=f"❌ Error saat menghapus: {e}")
                except discord.errors.NotFound: logger.warning(f"Tidak dapat mengirim pesan error untuk '{category_name}'.")
        else:
            await ctx.send("Penghapusan dibatalkan.", delete_after=10)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(f"❌ Izin tidak cukup: `{', '.join(error.missing_permissions)}`")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Cooldown. Coba lagi dalam **{error.retry_after:.1f} detik**.")
        else:
            logger.error(f"Error pada cog ServerCreator: {error}", exc_info=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerCreatorCog(bot))

