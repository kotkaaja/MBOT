import discord
from discord import app_commands
from discord.ext import commands
from discord import ui
import logging
import json
from utils.database import save_catalog_config, get_catalog_config

logger = logging.getLogger(__name__)

# --- VIEW & SELECT MENU DINAMIS ---

class DynamicRoleSelect(ui.Select):
    def __init__(self, options_data=None):
        discord_options = []
        if options_data:
            for opt in options_data:
                discord_options.append(discord.SelectOption(
                    label=opt['label'],
                    value=str(opt['role_id']),
                    emoji=opt.get('emoji'),
                    description=opt.get('description', '')[:100]
                ))
        else:
            # Placeholder biar gak error pas restart
            discord_options.append(discord.SelectOption(label="Loading...", value="0"))

        super().__init__(
            placeholder="Pilih role di sini...",
            min_values=0,
            max_values=len(discord_options) if options_data else 1,
            options=discord_options,
            custom_id="dynamic_catalog_select"
        )

    async def callback(self, interaction: discord.Interaction):
        # 1. Tarik config dari Database berdasarkan ID Pesan
        config = get_catalog_config(interaction.message.id)
        if not config:
            await interaction.response.send_message("❌ Data katalog ini hilang/rusak.", ephemeral=True)
            return

        # 2. Logic Add/Remove Role
        catalog_role_ids = [int(opt['role_id']) for opt in config['options']]
        selected_role_ids = [int(val) for val in self.values]
        
        user = interaction.user
        guild = interaction.guild
        added, removed, errors = [], [], []

        await interaction.response.defer(ephemeral=True)

        for r_id in catalog_role_ids:
            role = guild.get_role(r_id)
            if not role: continue

            if r_id in selected_role_ids:
                if role not in user.roles:
                    try:
                        await user.add_roles(role)
                        added.append(role.name)
                    except discord.Forbidden:
                        errors.append(f"Gagal add {role.name}")
            else:
                if role in user.roles:
                    try:
                        await user.remove_roles(role)
                        removed.append(role.name)
                    except discord.Forbidden:
                        errors.append(f"Gagal remove {role.name}")

        # 3. Feedback ke user
        response = []
        if added: response.append(f"✅ **Diterima:** {', '.join(added)}")
        if removed: response.append(f"🗑️ **Dicabut:** {', '.join(removed)}")
        if errors: response.append(f"⚠️ **Error:** {', '.join(errors)}")
        
        await interaction.followup.send("\n".join(response) or "ℹ️ Role tidak berubah.", ephemeral=True)

class DynamicCatalogView(ui.View):
    def __init__(self, options_data=None):
        super().__init__(timeout=None)
        self.add_item(DynamicRoleSelect(options_data))

# --- COG UTAMA ---

class RoleCatalogCog(commands.Cog, name="RoleCatalog"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="create_catalog", description="Buat katalog role. Paste JSON di 'json_input', upload gambar di 'image'.")
    @app_commands.describe(
        json_input="Paste teks JSON konfigurasi di sini",
        image="Upload gambar banner (Opsional, menimpa image_url di JSON)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def create_catalog(self, interaction: discord.Interaction, json_input: str, image: discord.Attachment = None):
        await interaction.response.defer(ephemeral=True)

        try:
            # 1. Parsing Text JSON
            config = json.loads(json_input)
            
            # Validasi minimal
            if "options" not in config:
                await interaction.followup.send("❌ JSON Error: Wajib ada key `'options'` berisi list role.", ephemeral=True)
                return

            # 2. Bikin Embed (Ala Discohook simpel)
            embed = discord.Embed(
                title=config.get('title', 'Role Catalog'),
                description=config.get('description', 'Silahkan pilih role di bawah.'),
                color=int(config.get('color', 0x2b2d31)) # Default dark gray discord
            )
            
            # Isi deskripsi role di body embed biar user baca
            desc_text = ""
            for opt in config['options']:
                emoji = opt.get('emoji', '🔹')
                desc_text += f"{emoji} | **{opt['label']}** — {opt.get('description', '')}\n"
            
            if desc_text:
                embed.add_field(name="Daftar Role", value=desc_text)

            # 3. Handle Gambar (Prioritas: Uploadan Command > URL di JSON)
            if image:
                embed.set_image(url=image.url)
            elif config.get('image_url'):
                embed.set_image(url=config.get('image_url'))
            
            # Thumbnail/Footer opsional dari JSON
            if config.get('thumbnail_url'):
                embed.set_thumbnail(url=config.get('thumbnail_url'))
            if config.get('footer_text'):
                embed.set_footer(text=config.get('footer_text'))

            # 4. Kirim Barang
            view = DynamicCatalogView(config['options'])
            sent_msg = await interaction.channel.send(embed=embed, view=view)

            # 5. Simpan Config ke Database (Biar tombol jalan selamanya)
            save_success = save_catalog_config(sent_msg.id, interaction.guild.id, interaction.channel.id, config)

            if save_success:
                await interaction.followup.send(f"✅ Katalog berhasil dibuat! (ID: {sent_msg.id})", ephemeral=True)
            else:
                await sent_msg.delete()
                await interaction.followup.send("❌ Gagal simpan ke DB. Coba lagi.", ephemeral=True)

        except json.JSONDecodeError:
            await interaction.followup.send("❌ Format JSON salah. Cek tanda kurung/koma.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error catalog: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        # Listener biar tombol tetap hidup kalau bot restart
        if interaction.type == discord.InteractionType.component:
            if interaction.data.get("custom_id") == "dynamic_catalog_select":
                config = get_catalog_config(interaction.message.id)
                if not config:
                    await interaction.response.send_message("❌ Data katalog hilang.", ephemeral=True)
                    return
                
                # Rebuild view on-the-fly
                view = DynamicCatalogView(config['options'])
                select = view.children[0]
                select.values = interaction.data.get('values', [])
                await select.callback(interaction)

async def setup(bot):
    await bot.add_cog(RoleCatalogCog(bot))
