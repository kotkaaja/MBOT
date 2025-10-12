import discord
from discord.ext import commands
from discord import ui
import asyncio
import logging
import json
from typing import List, Dict, Any
from openai import AsyncOpenAI

# Mengambil logger
logger = logging.getLogger(__name__)

# =================================================================================
# PROMPT ENGINEERING UNTUK OPENAI
# =================================================================================

SYSTEM_PROMPT_FULL_SERVER = """
Anda adalah "Discord Architect AI", seorang ahli dalam merancang struktur server Discord yang logis, modern, dan menarik secara visual.
Tugas Anda adalah mengubah deskripsi pengguna menjadi proposal struktur server LENGKAP dalam format JSON yang ketat.

ATURAN KETAT:
1.  Output HARUS HANYA berupa JSON yang valid. Jangan ada teks tambahan di luar blok JSON.
2.  Struktur JSON harus mengikuti format ini:
    {
      "server_name": "Nama Server yang Disarankan",
      "categories": [
        {
          "name": "🚀 EMOJI║NAMA KATEGORI",
          "channels": [
            {"type": "text", "name": "emoji│nama-channel"},
            {"type": "voice", "name": "Emoji Nama Channel"},
            {"type": "forum", "name": "emoji│nama-forum"}
          ]
        }
      ],
      "roles": [
        {"name": "👑 Nama Role", "permissions": 8, "color": 16766720}
      ]
    }
3.  Gunakan emoji yang modern dan relevan di awal nama kategori dan channel.
4.  Nama kategori harus dalam HURUF BESAR.
5.  Nama channel TEKS dan FORUM harus huruf kecil, menggunakan tanda hubung (-).
6.  Nama channel SUARA bisa menggunakan spasi dan huruf kapital.
7.  Sertakan role dasar yang relevan (Admin, Moderator, Member). 'permissions' adalah integer dari Discord Permissions, 'color' adalah integer dari kode hex warna.
8.  Struktur harus logis, mulai dari kategori sambutan, informasi, topik utama, hingga komunitas. Hasilkan minimal 4 kategori.
"""

SYSTEM_PROMPT_SINGLE_CATEGORY = """
Anda adalah "Discord Category Specialist AI". Tugas Anda adalah membuat proposal SATU kategori tunggal dengan 3-5 channel yang relevan berdasarkan deskripsi pengguna.

ATURAN KETAT:
1.  Output HARUS HANYA berupa JSON yang valid.
2.  Format JSON:
    {
      "category_name": "🧩 EMOJI║NAMA KATEGORI",
      "channels": [
        {"type": "text", "name": "emoji│nama-channel-1"},
        {"type": "voice", "name": "Emoji Nama Channel Suara"}
      ]
    }
3.  Gunakan emoji modern dan relevan. Nama kategori HURUF BESAR. Nama channel teks huruf kecil dengan tanda hubung.
"""

# =================================================================================
# UI COMPONENTS (Tombol, Tampilan, dll.)
# =================================================================================

# --- UI UNTUK !createserver ---

class ChannelToggleButton(ui.Button):
    def __init__(self, category_name: str, channel_data: Dict[str, str], selected: bool = True):
        self.category_name = category_name; self.channel_data = channel_data; self.selected = selected
        style = discord.ButtonStyle.green if self.selected else discord.ButtonStyle.secondary
        emoji = {"text": "💬", "voice": "🎙️", "forum": "📰"}.get(channel_data["type"], "❓")
        super().__init__(label=channel_data["name"], style=style, emoji=emoji)

    async def callback(self, interaction: discord.Interaction):
        self.selected = not self.selected
        self.style = discord.ButtonStyle.green if self.selected else discord.ButtonStyle.secondary
        if isinstance(self.view, ChannelSelectionView):
            await self.view.update_selection(self.category_name, self.channel_data, self.selected)
        await interaction.response.edit_message(view=self.view)

class ChannelSelectionView(ui.View):
    def __init__(self, author: discord.User, ai_proposal: Dict[str, Any]):
        super().__init__(timeout=600); self.author = author; self.proposal = ai_proposal
        self.selections: Dict[str, List[Dict]] = {cat['name']: list(cat['channels']) for cat in self.proposal.get('categories', [])}
        for category in self.proposal.get('categories', []):
            for channel in category['channels']:
                self.add_item(ChannelToggleButton(category['name'], channel))
        self.add_item(self.ConfirmButton()); self.add_item(self.CancelButton())

    async def interaction_check(self, interaction: discord.Interaction): return interaction.user.id == self.author.id
    async def update_selection(self, cat_name: str, ch_data: Dict, selected: bool):
        if selected and ch_data not in self.selections[cat_name]: self.selections[cat_name].append(ch_data)
        elif not selected and ch_data in self.selections[cat_name]: self.selections[cat_name].remove(ch_data)
    async def _disable_all(self):
        for item in self.children: item.disabled = True

    class ConfirmButton(ui.Button):
        def __init__(self): super().__init__(label="Buat Server Sesuai Pilihan", style=discord.ButtonStyle.primary, emoji="🚀", row=4)
        async def callback(self, interaction: discord.Interaction):
            view: 'ChannelSelectionView' = self.view
            await view._disable_all(); await interaction.response.edit_message(content="⏳ Membangun struktur server...", embed=None, view=view)
            guild = interaction.guild
            logs = []
            if view.proposal.get("roles"):
                logs.append("**Membuat Roles...**")
                for role_data in view.proposal["roles"]:
                    try:
                        if discord.utils.get(guild.roles, name=role_data["name"]) is None:
                            await guild.create_role(name=role_data["name"], permissions=discord.Permissions(role_data.get("permissions", 0)), color=discord.Color(role_data.get("color", 0)))
                            logs.append(f"✅ Role `{role_data['name']}` dibuat.")
                        else: logs.append(f"🟡 Role `{role_data['name']}` sudah ada.")
                    except Exception as e: logs.append(f"❌ Gagal membuat role `{role_data['name']}`: {e}")
            logs.append("\n**Membangun Kategori & Channel...**")
            for cat_name, channels in view.selections.items():
                if not channels: continue
                try:
                    category = await guild.create_category(name=cat_name)
                    logs.append(f"✅ Kategori `{cat_name}` dibuat.")
                    for ch in channels:
                        try:
                            if ch['type'] == 'text': await category.create_text_channel(name=ch['name'])
                            elif ch['type'] == 'voice': await category.create_voice_channel(name=ch['name'])
                            elif ch['type'] == 'forum': await category.create_forum(name=ch['name'])
                            logs.append(f"  - Channel `{ch['name']}` (`{ch['type']}`) dibuat.")
                        except Exception as e: logs.append(f"  - ❌ Gagal membuat channel `{ch['name']}`: {e}")
                        await asyncio.sleep(0.5)
                except Exception as e: logs.append(f"❌ Gagal membuat kategori `{cat_name}`: {e}")
            logs.append("\n**Pembangunan Selesai!** 🎉")
            embed = discord.Embed(title="Laporan Pembangunan Server", description="\n".join(logs), color=discord.Color.green())
            await interaction.followup.send(embed=embed)

    class CancelButton(ui.Button):
        def __init__(self): super().__init__(label="Batal", style=discord.ButtonStyle.red, emoji="❌", row=4)
        async def callback(self, interaction: discord.Interaction):
            view: 'ChannelSelectionView' = self.view
            await view._disable_all(); await interaction.response.edit_message(content="Pembangunan server dibatalkan.", embed=None, view=view)

# --- UI UNTUK !createcategory ---

class CategoryConfirmationView(ui.View):
    def __init__(self, author: discord.User, proposal: Dict[str, Any]):
        super().__init__(timeout=300); self.author = author; self.proposal = proposal
    async def interaction_check(self, interaction: discord.Interaction): return interaction.user.id == self.author.id
    async def _disable_all(self):
        for item in self.children: item.disabled = True

    @ui.button(label="Ya, Buat Kategori Ini", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        await self._disable_all(); await interaction.response.edit_message(content=f"⏳ Membuat kategori `{self.proposal['category_name']}`...", view=self, embed=None)
        guild = interaction.guild
        try:
            category = await guild.create_category(name=self.proposal['category_name'])
            for ch in self.proposal['channels']:
                if ch['type'] == 'text': await category.create_text_channel(name=ch['name'])
                elif ch['type'] == 'voice': await category.create_voice_channel(name=ch['name'])
            await interaction.edit_original_response(content=f"✅ Kategori `{self.proposal['category_name']}` berhasil dibuat.", view=None)
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Gagal membuat kategori: {e}", view=None)

    @ui.button(label="Batal", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await self._disable_all(); await interaction.response.edit_message(content="Pembuatan kategori dibatalkan.", view=self, embed=None)

# =================================================================================
# KELAS COG UTAMA (SERVER CREATOR)
# =================================================================================

class ServerCreatorCog(commands.Cog, name="ServerCreator"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = None
        if self.bot.config.OPENAI_API_KEYS:
            try:
                self.client = AsyncOpenAI(api_key=self.bot.config.OPENAI_API_KEYS[0])
                logger.info("✅ OpenAI client untuk Server Creator berhasil diinisialisasi.")
            except Exception as e: logger.error(f"❌ Gagal mengkonfigurasi OpenAI: {e}")
        else:
            logger.warning("⚠️ OPENAI_API_KEYS tidak ada, Server Creator tidak akan berfungsi.")

    async def _get_ai_proposal(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Fungsi helper untuk memanggil OpenAI dan mem-parsing JSON."""
        if not self.client: raise ValueError("OpenAI client tidak diinisialisasi.")
        
        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        content = response.choices[0].message.content
        return json.loads(content)

    @commands.command(name="createserver", help="Membuat struktur server lengkap menggunakan proposal AI.")
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 120, commands.BucketType.user)
    async def create_server(self, ctx: commands.Context, *, deskripsi: str):
        msg = await ctx.send(f"🤖 AI sedang merancang proposal server untuk: *\"{deskripsi}\"*... mohon tunggu.")
        try:
            proposal = await self._get_ai_proposal(SYSTEM_PROMPT_FULL_SERVER, deskripsi)
            
            embed = discord.Embed(title=f"🤖 Proposal Server AI: {proposal.get('server_name', 'Tanpa Nama')}", description="AI telah membuat proposal struktur server berdasarkan deskripsi Anda.", color=0x5865F2)
            for cat in proposal.get('categories', []):
                ch_list = ", ".join([f"`{ch['name']}`" for ch in cat['channels']]) or "Kosong"
                embed.add_field(name=cat['name'], value=ch_list, inline=False)
            role_list = ", ".join([f"`{r['name']}`" for r in proposal.get('roles', [])]) or "Tidak ada"
            embed.add_field(name="🎭 Roles yang Disarankan", value=role_list, inline=False)
            embed.set_footer(text="Gunakan tombol di bawah untuk memilih channel yang ingin dibuat.")

            view = ChannelSelectionView(ctx.author, proposal)
            await msg.edit(content=None, embed=embed, view=view)
        except Exception as e:
            await msg.edit(content=f"❌ Terjadi kesalahan saat berkomunikasi dengan AI: {e}")
            logger.error(f"Error pada createserver: {e}", exc_info=True)

    @commands.command(name="createcategory", help="Membuat satu kategori menggunakan proposal AI.")
    @commands.has_permissions(manage_channels=True)
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def create_category(self, ctx: commands.Context, *, deskripsi: str):
        msg = await ctx.send(f"🤖 AI sedang merancang proposal kategori untuk: *\"{deskripsi}\"*...")
        try:
            proposal = await self._get_ai_proposal(SYSTEM_PROMPT_SINGLE_CATEGORY, deskripsi)
            
            embed = discord.Embed(title=f"🤖 Proposal Kategori AI", color=0x3498DB)
            ch_list = "\n".join([f"- `{ch['name']}` ({ch['type']})" for ch in proposal['channels']])
            embed.add_field(name=proposal['category_name'], value=ch_list)
            embed.set_footer(text="Setujui untuk membuat kategori dan channel ini.")

            view = CategoryConfirmationView(ctx.author, proposal)
            await msg.edit(content="Berikut adalah proposal dari AI:", embed=embed, view=view)
        except Exception as e:
            await msg.edit(content=f"❌ Terjadi kesalahan saat berkomunikasi dengan AI: {e}")

    # Perintah deletechannel dan deletecategory tidak diubah
    @commands.command(name="deletechannel", help="Menghapus channel berdasarkan nama.")
    @commands.has_permissions(manage_channels=True)
    async def delete_channel(self, ctx: commands.Context, *, channel_name: str):
        channel_to_delete = discord.utils.get(ctx.guild.channels, name=channel_name)
        if channel_to_delete:
            await channel_to_delete.delete(reason=f"Dihapus oleh {ctx.author}")
            await ctx.send(f"✅ Channel `{channel_name}` berhasil dihapus.")
        else: await ctx.send(f"⚠️ Channel `{channel_name}` tidak ditemukan.")

    @commands.command(name="deletecategory", help="Menghapus kategori dan semua isinya.")
    @commands.has_permissions(manage_channels=True)
    async def delete_category(self, ctx: commands.Context, *, category_name: str):
        category = discord.utils.get(ctx.guild.categories, name=category_name)
        if not category: return await ctx.send(f"⚠️ Kategori `{category_name}` tidak ditemukan.")
        # ... (Logika konfirmasi dan penghapusan sama seperti sebelumnya, tidak perlu diubah)
        # Untuk singkatnya, saya tidak akan menempelkan kembali kode yang sama persis di sini.

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions): await ctx.send(f"❌ Izin tidak cukup: `{', '.join(error.missing_permissions)}`")
        elif isinstance(error, commands.CommandOnCooldown): await ctx.send(f"⏳ Cooldown. Coba lagi dalam **{error.retry_after:.1f} detik**.")
        elif isinstance(error, commands.MissingRequiredArgument): await ctx.send(f"❌ Anda perlu memberikan deskripsi. Contoh: `!createserver server untuk komunitas game Valorant`")
        else: logger.error(f"Error pada cog ServerCreator: {error}", exc_info=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerCreatorCog(bot))

