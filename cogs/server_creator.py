import discord
from discord.ext import commands
from discord import ui
import asyncio
import logging
import json
import re # Import re
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
import google.generativeai as genai # Import Gemini
import httpx # Import httpx
import itertools

# Import database untuk limit AI
from utils.database import check_ai_limit, increment_ai_usage, get_user_rank

# Mengambil logger
logger = logging.getLogger(__name__)

# =================================================================================
# PROMPT ENGINEERING (Tetap sama)
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
            {"type": "text", "name": "✨│nama-channel-teks"},
            {"type": "voice", "name": "🎙️ Nama Channel Suara"},
            {"type": "forum", "name": "📰│nama-forum-diskusi"}
          ]
        }
      ],
      "roles": [
        {"name": "👑 Nama Role", "permissions": 8, "color": 16766720}
      ]
    }
3.  Gunakan emoji yang modern dan relevan (berbeda-beda) di awal nama kategori DAN channel.
4.  Nama kategori harus dalam HURUF BESAR dan singkat.
5.  Nama channel TEKS dan FORUM harus huruf kecil, menggunakan tanda hubung (-).
6.  Nama channel SUARA bisa menggunakan spasi dan huruf kapital.
7.  Sertakan 3-5 role dasar yang relevan (misal: Admin, Moderator, Member, Bot, VIP). 'permissions' adalah integer dari Discord Permissions, 'color' adalah integer dari kode hex warna (contoh: 0xFFD700 untuk emas).
8.  Struktur harus logis, mulai dari kategori sambutan, informasi, topik utama, hingga komunitas. Hasilkan minimal 4 kategori yang relevan.
"""

SYSTEM_PROMPT_SINGLE_CATEGORY = """
Anda adalah "Discord Category Specialist AI". Tugas Anda adalah membuat proposal SATU kategori tunggal dengan 3-5 channel yang relevan berdasarkan deskripsi pengguna.

ATURAN KETAT:
1.  Output HARUS HANYA berupa JSON yang valid.
2.  Format JSON:
    {
      "category_name": "🧩 EMOJI║NAMA KATEGORI",
      "channels": [
        {"type": "text", "name": "💬│nama-channel-satu"},
        {"type": "voice", "name": "🎙️ Voice Channel"}
      ]
    }
3.  Gunakan emoji modern dan relevan untuk kategori dan setiap channel. Nama kategori HURUF BESAR. Nama channel teks huruf kecil dengan tanda hubung.
"""

# =================================================================================
# UI COMPONENTS (Tetap sama)
# =================================================================================

class ChannelToggleButton(ui.Button):
    def __init__(self, category_name: str, channel_data: Dict[str, str], selected: bool = True):
        self.category_name = category_name; self.channel_data = channel_data; self.selected = selected
        style = discord.ButtonStyle.green if self.selected else discord.ButtonStyle.secondary
        emoji_map = {"text": "💬", "voice": "🎙️", "forum": "📰"}
        super().__init__(label=channel_data["name"], style=style, emoji=emoji_map.get(channel_data["type"]))

    async def callback(self, interaction: discord.Interaction):
        self.selected = not self.selected
        self.style = discord.ButtonStyle.green if self.selected else discord.ButtonStyle.secondary
        if hasattr(self.view, 'update_selection'):
            await self.view.update_selection(self.category_name, self.channel_data, self.selected)
        await interaction.response.edit_message(view=self.view)

class RoleToggleButton(ui.Button):
    def __init__(self, create_roles: bool = True):
        self.create_roles = create_roles
        style = discord.ButtonStyle.green if self.create_roles else discord.ButtonStyle.secondary
        label = "Buat Roles (Aktif)" if self.create_roles else "Buat Roles (Nonaktif)"
        super().__init__(label=label, style=style, emoji="🎭", row=4)

    async def callback(self, interaction: discord.Interaction):
        self.create_roles = not self.create_roles
        self.style = discord.ButtonStyle.green if self.create_roles else discord.ButtonStyle.secondary
        self.label = "Buat Roles (Aktif)" if self.create_roles else "Buat Roles (Nonaktif)"
        if hasattr(self.view, 'toggle_role_creation'):
            self.view.toggle_role_creation(self.create_roles)
        await interaction.response.edit_message(view=self.view)

class BaseInteractiveView(ui.View):
    def __init__(self, cog, ctx: commands.Context, deskripsi: str, timeout: int = 600):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx
        self.deskripsi = deskripsi
        self.author = ctx.author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Hanya pengguna yang meminta yang dapat berinteraksi.", ephemeral=True)
            return False
        return True

    async def _disable_all(self):
        for item in self.children: item.disabled = True

    async def handle_refresh(self, interaction: discord.Interaction):
        raise NotImplementedError

class ServerCreationView(BaseInteractiveView):
    def __init__(self, cog, ctx: commands.Context, deskripsi: str, proposal: Dict[str, Any]):
        super().__init__(cog, ctx, deskripsi)
        self.proposal = proposal
        self.create_roles_enabled = True
        self.selections: Dict[str, List[Dict]] = {c['name']: list(c['channels']) for c in proposal.get('categories', [])}
        self._populate_items()

    def _populate_items(self):
        self.clear_items()
        for category in self.proposal.get('categories', []):
            for channel in category['channels']:
                self.add_item(ChannelToggleButton(category['name'], channel))
        self.add_item(RoleToggleButton(self.create_roles_enabled))
        self.add_item(self.ConfirmButton()); self.add_item(self.CancelButton()); self.add_item(self.RefreshButton())

    def toggle_role_creation(self, enabled: bool): self.create_roles_enabled = enabled
    async def update_selection(self, cat: str, chan: Dict, sel: bool):
        if sel and chan not in self.selections[cat]: self.selections[cat].append(chan)
        elif not sel and chan in self.selections[cat]: self.selections[cat].remove(chan)

    async def handle_refresh(self, interaction: discord.Interaction):
        can_use, remaining, limit = check_ai_limit(self.ctx.author.id)
        if not can_use:
            rank = get_user_rank(self.ctx.author.id)
            limit_display = "Unlimited" if limit == -1 else limit
            usage_today = (limit - remaining) if limit > 0 else 0
            await interaction.response.send_message(
                f"❌ Batas harian AI Anda (Rank: **{rank.title()}**) telah tercapai ({usage_today}/{limit_display}). Tidak bisa meminta proposal baru.",
                ephemeral=True
            )
            return

        await interaction.response.edit_message(content=f"🔄 Meminta proposal baru dari AI untuk: *\"{self.deskripsi}\"*...", view=None, embed=None)
        await self.cog.create_server(self.ctx, deskripsi=self.deskripsi, existing_message=interaction.message)

    class ConfirmButton(ui.Button):
        def __init__(self): super().__init__(label="Buat Pilihan", style=discord.ButtonStyle.primary, emoji="🚀", row=4)
        async def callback(self, interaction: discord.Interaction):
            view: 'ServerCreationView' = self.view
            await view._disable_all(); await interaction.response.edit_message(content="⏳ Membangun struktur server...", embed=None, view=view)
            guild = interaction.guild
            logs = []
            if view.create_roles_enabled and view.proposal.get("roles"):
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
            view: 'ServerCreationView' = self.view
            await view._disable_all(); await interaction.response.edit_message(content="Pembangunan server dibatalkan.", embed=None, view=view)

    class RefreshButton(ui.Button):
        def __init__(self): super().__init__(label="Proposal Baru", style=discord.ButtonStyle.blurple, emoji="🔄", row=4)
        async def callback(self, interaction: discord.Interaction):
            view: 'ServerCreationView' = self.view
            await view.handle_refresh(interaction)

class CategoryCreationView(ServerCreationView):
    def __init__(self, cog, ctx: commands.Context, deskripsi: str, proposal: Dict[str, Any]):
        super_proposal = {'categories': [{'name': proposal.get('category_name', 'Nama Kategori'), 'channels': proposal.get('channels', [])}]}
        super().__init__(cog, ctx, deskripsi, super_proposal)
        self.selections: Dict[str, List[Dict]] = {c['name']: list(c['channels']) for c in self.proposal.get('categories', [])}

    def _populate_items(self):
        self.clear_items()
        for category in self.proposal.get('categories', []):
            for channel in category['channels']:
                self.add_item(ChannelToggleButton(category['name'], channel))
        self.add_item(self.ConfirmButton())
        self.add_item(self.CancelButton())
        self.add_item(self.RefreshButton())

    async def handle_refresh(self, interaction: discord.Interaction):
        can_use, remaining, limit = check_ai_limit(self.ctx.author.id)
        if not can_use:
            rank = get_user_rank(self.ctx.author.id)
            limit_display = "Unlimited" if limit == -1 else limit
            usage_today = (limit - remaining) if limit > 0 else 0
            await interaction.response.send_message(
                f"❌ Batas harian AI Anda (Rank: **{rank.title()}**) telah tercapai ({usage_today}/{limit_display}). Tidak bisa meminta proposal baru.",
                ephemeral=True
            )
            return

        await interaction.response.edit_message(content=f"🔄 Meminta proposal baru dari AI untuk: *\"{self.deskripsi}\"*...", view=None, embed=None)
        await self.cog.create_category(self.ctx, deskripsi=self.deskripsi, existing_message=interaction.message)

    class ConfirmButton(ui.Button):
        def __init__(self): super().__init__(label="Buat Kategori", style=discord.ButtonStyle.green, emoji="✅", row=4)
        async def callback(self, interaction: discord.Interaction):
            view: 'CategoryCreationView' = self.view
            await view._disable_all()
            await interaction.response.edit_message(content=f"⏳ Membuat kategori...", embed=None, view=view)
            guild = interaction.guild
            logs = []
            for cat_name, channels in view.selections.items():
                if not channels: continue
                try:
                    category = await guild.create_category(name=cat_name)
                    logs.append(f"✅ Kategori `{cat_name}` dibuat.")
                    for ch in channels:
                        await asyncio.sleep(0.5)
                        if ch['type'] == 'text': await category.create_text_channel(name=ch['name'])
                        elif ch['type'] == 'voice': await category.create_voice_channel(name=ch['name'])
                        elif ch['type'] == 'forum': await category.create_forum(name=ch['name'])
                        logs.append(f"  - Channel `{ch['name']}` (`{ch['type']}`) dibuat.")
                except Exception as e: logs.append(f"❌ Gagal membuat kategori atau channel `{cat_name}`: {e}")
            result_message = "\n".join(logs) if logs else "Tidak ada yang dibuat."
            await interaction.edit_original_response(content=result_message, view=None)

# =================================================================================
# KELAS COG UTAMA (SERVER CREATOR)
# =================================================================================
class ServerCreatorCog(commands.Cog, name="ServerCreator"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = bot.config
        # Tambahkan key cyclers untuk SEMUA provider
        self.openai_client = None
        self.openai_key_cycler = itertools.cycle(self.config.OPENAI_API_KEYS) if self.config.OPENAI_API_KEYS else None
        self.gemini_key_cycler = itertools.cycle(self.config.GEMINI_API_KEYS) if self.config.GEMINI_API_KEYS else None
        self.deepseek_key_cycler = itertools.cycle(self.config.DEEPSEEK_API_KEYS) if self.config.DEEPSEEK_API_KEYS else None
        self.openrouter_key_cycler = itertools.cycle(self.config.OPENROUTER_API_KEYS) if self.config.OPENROUTER_API_KEYS else None
        self.agentrouter_key_cycler = itertools.cycle(self.config.AGENTROUTER_API_KEYS) if self.config.AGENTROUTER_API_KEYS else None

        if self.openai_key_cycler:
            first_key = self.config.OPENAI_API_KEYS[0]
            self.openai_client = AsyncOpenAI(api_key=first_key, timeout=30.0)
            logger.info(f"✅ OpenAI client untuk Server Creator berhasil diinisialisasi (menggunakan {len(self.config.OPENAI_API_KEYS)} keys).")
        else:
            logger.warning("⚠️ OPENAI_API_KEYS tidak ada.")
        if not self.gemini_key_cycler: logger.warning("⚠️ GEMINI_API_KEYS tidak ada.")
        if not self.deepseek_key_cycler: logger.warning("⚠️ DEEPSEEK_API_KEYS tidak ada.")
        if not self.openrouter_key_cycler: logger.warning("⚠️ OPENROUTER_API_KEYS tidak ada.")
        if not self.agentrouter_key_cycler: logger.warning("⚠️ AGENTROUTER_API_KEYS tidak ada.")

        # Siapkan header OpenRouter
        if self.openrouter_key_cycler:
            self.openrouter_headers = {
                "HTTP-Referer": getattr(self.config, 'OPENROUTER_SITE_URL', 'http://localhost'),
                "X-Title": getattr(self.config, 'OPENROUTER_SITE_NAME', 'MBOT'),
            }

    # --- [BARU] Fungsi AI Helper Terpisah ---
    async def _try_gemini(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
        if not self.gemini_key_cycler: return None
        try:
            key = next(self.gemini_key_cycler)
            genai.configure(api_key=key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            logger.info(f"Server Creator: Mencoba Gemini...")
            response = await model.generate_content_async(
                [system_prompt, user_prompt],
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json", temperature=0.7
                ),
                request_options={"timeout": 60}
            )
            if response.prompt_feedback.block_reason: raise Exception(f"Diblokir: {response.prompt_feedback.block_reason.name}")
            if response.candidates and response.candidates[0].finish_reason.name != "STOP": raise Exception(f"Finish reason: {response.candidates[0].finish_reason.name}")
            cleaned = re.sub(r'```json\s*|\s*```', '', response.text.strip(), flags=re.DOTALL)
            if not cleaned: raise ValueError("Respons JSON kosong.")
            data = json.loads(cleaned)
            logger.info("AI (Gemini) berhasil generate.")
            return data
        except Exception as e:
            logger.warning(f"Server Creator: Gemini gagal: {e}")
            await asyncio.sleep(1)
            return None

    async def _try_deepseek(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
        if not self.deepseek_key_cycler: return None
        try:
            key = next(self.deepseek_key_cycler)
            async with httpx.AsyncClient(timeout=40.0) as client:
                logger.info(f"Server Creator: Mencoba Deepseek...")
                response = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.7
                    },
                    headers={"Authorization": f"Bearer {key}"}
                )
                response.raise_for_status()
                cleaned = re.sub(r'```json\s*|\s*```', '', response.json()["choices"][0]["message"]["content"].strip(), flags=re.DOTALL)
                if not cleaned: raise ValueError("Respons JSON kosong.")
                data = json.loads(cleaned)
                logger.info("AI (DeepSeek) berhasil generate.")
                return data
        except Exception as e:
            logger.warning(f"Server Creator: DeepSeek gagal: {e}")
            await asyncio.sleep(1)
            return None

    async def _try_openai(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
        if not self.openai_key_cycler or not self.openai_client: return None
        max_retries = len(self.bot.config.OPENAI_API_KEYS)
        for attempt in range(max_retries):
            try:
                key = next(self.openai_key_cycler)
                self.openai_client.api_key = key
                logger.info(f"Server Creator: Mencoba OpenAI Key #{attempt+1}...")
                response = await self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                    response_format={"type": "json_object"}, temperature=0.7)
                cleaned = re.sub(r'```json\s*|\s*```', '', response.choices[0].message.content.strip(), flags=re.DOTALL)
                if not cleaned: raise ValueError("Respons JSON kosong.")
                data = json.loads(cleaned)
                logger.info("AI (OpenAI) berhasil generate.")
                return data
            except Exception as e:
                logger.warning(f"Server Creator: OpenAI Key #{attempt+1} gagal: {e}")
                if "rate_limit_exceeded" in str(e).lower() or "429" in str(e):
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                        continue
                    else:
                        logger.error("Semua OpenAI keys rate limited.")
                        return None
                else:
                     return None
        return None

    async def _try_openrouter(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
        if not self.openrouter_key_cycler: return None
        try:
            key = next(self.openrouter_key_cycler)
            async with httpx.AsyncClient(timeout=60.0) as client:
                logger.info(f"Server Creator: Mencoba OpenRouter...")
                payload = {
                    "model": "mistralai/mistral-7b-instruct:free",
                    "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.7, "max_tokens": 2048
                }
                headers = {"Authorization": f"Bearer {key}"}
                if hasattr(self, 'openrouter_headers'): headers.update(self.openrouter_headers)

                response = await client.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                cleaned = re.sub(r'```json\s*|\s*```', '', response.json()["choices"][0]["message"]["content"].strip(), flags=re.DOTALL)
                if not cleaned: raise ValueError("Respons JSON kosong.")
                data = json.loads(cleaned)
                logger.info("AI (OpenRouter) berhasil generate.")
                return data
        except Exception as e:
            logger.warning(f"Server Creator: OpenRouter gagal: {e}")
            await asyncio.sleep(1)
            return None

    async def _try_agentrouter(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
        if not self.agentrouter_key_cycler: return None
        try:
            key = next(self.agentrouter_key_cycler)
            logger.info(f"Server Creator: Mencoba AgentRouter...")
            client = AsyncOpenAI(api_key=key, base_url="https://agentrouter.org/v1", timeout=45.0)
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                response_format={"type": "json_object"},
                temperature=0.7
            )
            cleaned = re.sub(r'```json\s*|\s*```', '', response.choices[0].message.content.strip(), flags=re.DOTALL)
            if not cleaned: raise ValueError("Respons JSON kosong.")
            data = json.loads(cleaned)
            logger.info("AI (AgentRouter) berhasil generate.")
            return data
        except Exception as e:
            logger.warning(f"Server Creator: AgentRouter gagal: {e}")
            await asyncio.sleep(1)
            return None

    async def _get_ai_proposal(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Menghasilkan proposal dari AI dengan fallback lengkap."""
        proposal_json = None

        # Urutan Fallback: OpenRouter -> AgentRouter -> Gemini -> Deepseek -> OpenAI
        proposal_json = await self._try_openrouter(system_prompt, user_prompt)
        if not proposal_json: proposal_json = await self._try_agentrouter(system_prompt, user_prompt)
        if not proposal_json: proposal_json = await self._try_gemini(system_prompt, user_prompt)
        if not proposal_json: proposal_json = await self._try_deepseek(system_prompt, user_prompt)
        if not proposal_json: proposal_json = await self._try_openai(system_prompt, user_prompt)

        if not proposal_json:
            raise Exception("Semua layanan AI gagal dihubungi atau error.")

        return proposal_json
    # --- [AKHIR PERBAIKAN] ---


    @commands.command(name="createserver", help="Membuat struktur server lengkap menggunakan proposal AI.")
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 120, commands.BucketType.user)
    async def create_server(self, ctx: commands.Context, *, deskripsi: str, existing_message: Optional[discord.Message] = None):
        can_use, remaining, limit = check_ai_limit(ctx.author.id)
        if not can_use:
            rank = get_user_rank(ctx.author.id)
            limit_display = "Unlimited" if limit == -1 else limit
            usage_today = (limit - remaining) if limit > 0 else 0
            await ctx.send(
                f"❌ Batas harian AI Anda (Rank: **{rank.title()}**) telah tercapai ({usage_today}/{limit_display}). Coba lagi besok."
            )
            ctx.command.reset_cooldown(ctx)
            return

        message_handler = existing_message
        if not message_handler:
            message_handler = await ctx.send(f"🤖 AI sedang merancang proposal server untuk: *\"{deskripsi}\"*... mohon tunggu.")
        else:
            try:
                await message_handler.edit(content=f"🤖 AI sedang merancang proposal server untuk: *\"{deskripsi}\"*... mohon tunggu.", view=None, embed=None)
            except discord.NotFound:
                message_handler = await ctx.send(f"🤖 AI sedang merancang proposal server untuk: *\"{deskripsi}\"*... mohon tunggu.")
            except discord.HTTPException as e:
                 logger.error(f"Gagal edit pesan di create_server (HTTP {e.status}): {e.text}")
                 await ctx.send("Terjadi error saat update status, proses tetap berjalan.")

        try:
            proposal = await self._get_ai_proposal(SYSTEM_PROMPT_FULL_SERVER, deskripsi)
            increment_ai_usage(ctx.author.id)

            embed = discord.Embed(title=f"🤖 Proposal Server AI: {proposal.get('server_name', 'Tanpa Nama')}", description="Pilih channel yang ingin dibuat. Anda juga bisa meminta proposal baru atau membatalkan.", color=0x5865F2)
            role_list = ", ".join([f"`{r['name']}`" for r in proposal.get('roles', [])]) or "Tidak ada"
            embed.add_field(name="🎭 Roles yang Disarankan", value=role_list, inline=False)
            view = ServerCreationView(self, ctx, deskripsi, proposal)
            await message_handler.edit(content=None, embed=embed, view=view)
        except Exception as e:
            logger.error(f"Error di create_server: {e}", exc_info=True)
            error_msg = f"❌ Terjadi kesalahan: {e}"
            if "Semua layanan AI gagal" in str(e):
                error_msg = "❌ Semua layanan AI sedang bermasalah atau gagal dihubungi. Coba lagi nanti."
            await message_handler.edit(content=error_msg)
            ctx.command.reset_cooldown(ctx)


    @commands.command(name="createcategory", help="Membuat satu kategori interaktif menggunakan proposal AI.")
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def create_category(self, ctx: commands.Context, *, deskripsi: str, existing_message: Optional[discord.Message] = None):
        can_use, remaining, limit = check_ai_limit(ctx.author.id)
        if not can_use:
            rank = get_user_rank(ctx.author.id)
            limit_display = "Unlimited" if limit == -1 else limit
            usage_today = (limit - remaining) if limit > 0 else 0
            await ctx.send(
                f"❌ Batas harian AI Anda (Rank: **{rank.title()}**) telah tercapai ({usage_today}/{limit_display}). Coba lagi besok."
            )
            ctx.command.reset_cooldown(ctx)
            return

        message_handler = existing_message
        if not message_handler:
            message_handler = await ctx.send(f"🤖 AI sedang merancang proposal kategori untuk: *\"{deskripsi}\"*...")
        else:
            try:
                await message_handler.edit(content=f"🤖 AI sedang merancang proposal kategori untuk: *\"{deskripsi}\"*...", view=None, embed=None)
            except discord.NotFound:
                message_handler = await ctx.send(f"🤖 AI sedang merancang proposal kategori untuk: *\"{deskripsi}\"*...")
            except discord.HTTPException as e:
                 logger.error(f"Gagal edit pesan di create_category (HTTP {e.status}): {e.text}")
                 await ctx.send("Terjadi error saat update status, proses tetap berjalan.")

        try:
            proposal = await self._get_ai_proposal(SYSTEM_PROMPT_SINGLE_CATEGORY, deskripsi)
            increment_ai_usage(ctx.author.id)

            category_name_ai = proposal.get('category_name', 'Nama Kategori AI')
            embed = discord.Embed(title=f"🤖 Proposal Kategori AI", description=f"Pilih channel yang ingin dibuat untuk kategori **{category_name_ai}**.", color=0x3498DB)

            view = CategoryCreationView(self, ctx, deskripsi, proposal)
            await message_handler.edit(content=None, embed=embed, view=view)
        except Exception as e:
            logger.error(f"Error di create_category: {e}", exc_info=True)
            error_msg = f"❌ Terjadi kesalahan: {e}"
            if "Semua layanan AI gagal" in str(e):
                error_msg = "❌ Semua layanan AI sedang bermasalah atau gagal dihubungi. Coba lagi nanti."
            await message_handler.edit(content=error_msg)
            ctx.command.reset_cooldown(ctx)


    @commands.command(name="deletecategory", help="Menghapus kategori dan semua isinya.")
    @commands.has_permissions(administrator=True)
    async def delete_category(self, ctx: commands.Context, *, category_name: str):
        category = discord.utils.get(ctx.guild.categories, name=category_name)
        if not category: return await ctx.send(f"⚠️ Kategori `{category_name}` tidak ditemukan.")

        class ConfirmationView(ui.View):
            def __init__(self, author): super().__init__(timeout=60); self.author=author; self.confirmed=False
            async def interaction_check(self, interaction): return interaction.user.id == self.author.id
            @ui.button(label="Ya, Hapus Semua", style=discord.ButtonStyle.danger)
            async def confirm(self, interaction: discord.Interaction, button: ui.Button): self.confirmed=True; self.stop(); await interaction.response.defer()
            @ui.button(label="Batal", style=discord.ButtonStyle.secondary)
            async def cancel(self, interaction: discord.Interaction, button: ui.Button): self.stop(); await interaction.response.defer()

        view = ConfirmationView(ctx.author)
        warning_msg = await ctx.send(f"🚨 **PERINGATAN!** Anda akan menghapus `{category_name}` dan **SEMUA** channel di dalamnya. Aksi ini permanen.", view=view)
        await view.wait()
        try: await warning_msg.delete()
        except discord.NotFound: pass
        if view.confirmed:
            processing_msg = await ctx.send(f"⏳ Menghapus `{category_name}`...")
            try:
                channels_to_delete = list(category.channels)
                for channel in channels_to_delete:
                    await channel.delete(reason=f"Penghapusan kategori oleh {ctx.author}"); await asyncio.sleep(0.5)
                await category.delete(reason=f"Dihapus oleh {ctx.author}")
                await processing_msg.edit(content=f"✅ Kategori `{category_name}` berhasil dihapus.")
            except discord.errors.NotFound: logger.info(f"Berhasil hapus '{category_name}', channel konfirmasi sudah terhapus.")
            except Exception as e:
                try: await processing_msg.edit(content=f"❌ Gagal menghapus: {e}")
                except discord.NotFound: logger.warning(f"Gagal kirim error hapus '{category_name}'.")
        else:
            await ctx.send("Penghapusan dibatalkan.", delete_after=10)

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerCreatorCog(bot))
