# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import ui
import logging
import io
import base64
from PIL import Image, ImageDraw, ImageFont, ImageOps
from openai import AsyncOpenAI
import httpx
import google.generativeai as genai
from typing import List, Dict, Optional, Tuple
import asyncio
import re
import os
import json
import textwrap
import itertools

# --- [BARU REQ #3] Import database untuk limit AI ---
from utils.database import check_ai_limit, increment_ai_usage, get_user_rank

logger = logging.getLogger(__name__)

# ============================
# MODAL & VIEW COMPONENTS (Tidak Berubah)
# ============================

class SSRPInfoModal(ui.Modal, title="Informasi Bersama untuk SSRP"):
    """Modal untuk mengumpulkan informasi dasar SSRP"""

    jumlah_pemain = ui.TextInput(
        label="Jumlah Pemain",
        placeholder="Contoh: 2",
        required=True,
        max_length=2,
        style=discord.TextStyle.short
    )

    detail_karakter = ui.TextInput(
        label="Detail Karakter (Nama dan Peran)",
        placeholder="Contoh:\nJohn Doe (Polisi)\nJane Smith (Warga Sipil)",
        style=discord.TextStyle.paragraph,
        required=True
    )

    skenario = ui.TextInput(
        label="Topik atau Skenario Pembahasan",
        placeholder="Contoh: Investigasi sebuah perampokan kecil di toko...",
        style=discord.TextStyle.paragraph,
        required=True
    )

    language = ui.TextInput(
        label="Bahasa/Aksen Dialog (Opsional)",
        placeholder="Contoh: Bahasa Indonesia baku, English with casual slang",
        default="Bahasa Indonesia baku",
        style=discord.TextStyle.short,
        required=False
    )

    def __init__(self, cog_instance, images: List[bytes]):
        super().__init__()
        self.cog = cog_instance
        self.images = images

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        self.data = {
            'jumlah_pemain': self.jumlah_pemain.value,
            'detail_karakter': self.detail_karakter.value,
            'skenario': self.skenario.value,
            'language': self.language.value
        }

        await self.show_dialog_settings(interaction)

    async def show_dialog_settings(self, interaction: discord.Interaction):
        """Menampilkan view untuk setting dialog per gambar"""
        view = DialogSettingsView(self.cog, self.images, self.data)

        embed = discord.Embed(
            title="⚙️ Pengaturan Dialog per Gambar",
            description=f"Atur jumlah baris, posisi, dan gaya background untuk setiap gambar ({len(self.images)} gambar)",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Instruksi",
            value="• Maksimal 7 baris per gambar.\n"
                  "• Pilih posisi teks: Atas, Bawah, atau Split.\n"
                  "• Pilih gaya background: Overlay (hitam transparan) atau Transparan.",
            inline=False
        )

        try:
            file = discord.File(io.BytesIO(self.images[0]), filename="image_preview_0.png")
            embed.set_image(url=f"attachment://image_preview_0.png")
            await interaction.followup.send(embed=embed, view=view, file=file, ephemeral=True)
        except Exception as e:
            logger.error(f"Gagal mengirim preview gambar di show_dialog_settings: {e}")
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class DialogSettingsView(ui.View):
    """View untuk mengatur dialog count, posisi, dan background per gambar"""

    def __init__(self, cog_instance, images: List[bytes], info_data: Dict):
        super().__init__(timeout=300)
        self.cog = cog_instance
        self.images = images
        self.info_data = info_data
        self.dialog_counts = [5] * len(images)
        self.positions = ["bawah"] * len(images)
        self.background_styles = ["transparent"] * len(images)
        self.current_image_index = 0

        self.update_ui()

    def update_ui(self):
        """Update tombol dan select berdasarkan gambar saat ini"""
        self.clear_items()

        self.add_item(DialogCountSelect(self, self.dialog_counts[self.current_image_index]))
        self.add_item(PositionSelect(self, self.positions[self.current_image_index]))
        self.add_item(BackgroundStyleSelect(self, self.background_styles[self.current_image_index]))

        row_nav = 3
        if self.current_image_index > 0:
            self.add_item(PrevImageButton(self, row=row_nav))

        if self.current_image_index < len(self.images) - 1:
            self.add_item(NextImageButton(self, row=row_nav))
        else:
            self.add_item(FinishButton(self, row=row_nav))

    async def update_message(self, interaction: discord.Interaction):
        """Edit pesan interaksi dengan info gambar saat ini"""
        idx = self.current_image_index
        embed = discord.Embed(
            title=f"🖼️ Gambar {idx + 1}/{len(self.images)}",
            description="Atur jumlah baris dialog, posisi, dan gaya background.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Jumlah Baris", value=f"`{self.dialog_counts[idx]}` baris", inline=True)
        embed.add_field(name="Posisi Teks", value=f"`{self.positions[idx].capitalize()}`", inline=True)
        embed.add_field(name="Background", value=f"`{self.background_styles[idx].capitalize()}`", inline=True)

        try:
            file = discord.File(io.BytesIO(self.images[idx]), filename=f"image_preview_{idx}.png")
            embed.set_image(url=f"attachment://image_preview_{idx}.png")
            await interaction.response.edit_message(embed=embed, view=self, attachments=[file])
        except Exception as e:
            logger.error(f"Gagal update message preview: {e}")
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])


class DialogCountSelect(ui.Select):
    """Select untuk jumlah dialog"""
    def __init__(self, parent_view: DialogSettingsView, current_value: int):
        options = [discord.SelectOption(label=f"{i} baris", value=str(i), default=(i == current_value)) for i in range(1, 8)]
        super().__init__(placeholder="Pilih jumlah baris (1-7)", options=options, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.dialog_counts[self.parent_view.current_image_index] = int(self.values[0])
        for option in self.options: option.default = (int(option.value) == int(self.values[0]))
        await self.parent_view.update_message(interaction)


class PositionSelect(ui.Select):
    """Select untuk posisi dialog"""
    def __init__(self, parent_view: DialogSettingsView, current_value: str):
        options = [
            discord.SelectOption(label="Atas", value="atas", emoji="⬆️", default=(current_value == "atas")),
            discord.SelectOption(label="Bawah", value="bawah", emoji="⬇️", default=(current_value == "bawah")),
            discord.SelectOption(label="Split (Atas & Bawah)", value="split", emoji="↕️", default=(current_value == "split"))
        ]
        super().__init__(placeholder="Pilih posisi dialog", options=options, row=1)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.positions[self.parent_view.current_image_index] = self.values[0]
        for option in self.options: option.default = (option.value == self.values[0])
        await self.parent_view.update_message(interaction)

class BackgroundStyleSelect(ui.Select):
    """Select untuk gaya background teks"""
    def __init__(self, parent_view: DialogSettingsView, current_value: str):
        options = [
            discord.SelectOption(label="Overlay", value="overlay", description="Background hitam semi-transparan.", emoji="⬛", default=(current_value == "overlay")),
            discord.SelectOption(label="Transparan", value="transparent", description="Tanpa background, hanya teks + shadow.", emoji="⬜", default=(current_value == "transparent"))
        ]
        super().__init__(placeholder="Pilih gaya background teks", options=options, row=2)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.background_styles[self.parent_view.current_image_index] = self.values[0]
        for option in self.options: option.default = (option.value == self.values[0])
        await self.parent_view.update_message(interaction)


class PrevImageButton(ui.Button):
    """Button untuk gambar sebelumnya"""
    def __init__(self, parent_view: DialogSettingsView, row: int):
        super().__init__(label="◀️ Sebelumnya", style=discord.ButtonStyle.secondary, row=row)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.current_image_index > 0:
            self.parent_view.current_image_index -= 1
            self.parent_view.update_ui()
            await self.parent_view.update_message(interaction)


class NextImageButton(ui.Button):
    """Button untuk gambar selanjutnya"""
    def __init__(self, parent_view: DialogSettingsView, row: int):
        super().__init__(label="Selanjutnya ▶️", style=discord.ButtonStyle.primary, row=row)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.current_image_index < len(self.parent_view.images) - 1:
            self.parent_view.current_image_index += 1
            self.parent_view.update_ui()
            await self.parent_view.update_message(interaction)


class FinishButton(ui.Button):
    """Button untuk memulai proses"""
    def __init__(self, parent_view: DialogSettingsView, row: int):
        super().__init__(label="✅ Proses Semua Gambar", style=discord.ButtonStyle.success, row=row)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        for item in self.view.children: item.disabled = True
        await interaction.response.edit_message(content="⏳ Memulai proses...", view=self.view, embed=None, attachments=[])

        await self.parent_view.cog.process_ssrp(
            interaction,
            self.parent_view.images,
            self.parent_view.info_data,
            self.parent_view.dialog_counts,
            self.parent_view.positions,
            self.parent_view.background_styles
        )


# ============================
# COG UTAMA (DIPERBAIKI)
# ============================

class SSRPChatlogCog(commands.Cog, name="SSRPChatlog"):
    """Cog untuk membuat SSRP Chatlog dengan AI - Styling seperti Chatlog Magician"""

    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config

        # Setup API Clients & Key Cyclers
        self.openai_key_cycler = None
        if hasattr(self.config, 'OPENAI_API_KEYS') and self.config.OPENAI_API_KEYS:
            self.openai_key_cycler = itertools.cycle(self.config.OPENAI_API_KEYS)
            logger.info(f"✅ OpenAI keys ({len(self.config.OPENAI_API_KEYS)}) dimuat untuk SSRP Chatlog.")
        else:
            logger.warning("⚠️ OpenAI API keys (OPENAI_API_KEYS) tidak ditemukan di config.")

        self.deepseek_key_cycler = None
        if hasattr(self.config, 'DEEPSEEK_API_KEYS') and self.config.DEEPSEEK_API_KEYS:
            self.deepseek_key_cycler = itertools.cycle(self.config.DEEPSEEK_API_KEYS)
            logger.info(f"✅ DeepSeek keys ({len(self.config.DEEPSEEK_API_KEYS)}) dimuat untuk SSRP Chatlog.")
        else:
            logger.warning("⚠️ DeepSeek API keys (DEEPSEEK_API_KEYS) tidak ditemukan di config.")

        self.gemini_key_cycler = None
        if hasattr(self.config, 'GEMINI_API_KEYS') and self.config.GEMINI_API_KEYS:
            self.gemini_key_cycler = itertools.cycle(self.config.GEMINI_API_KEYS)
            logger.info(f"✅ Gemini keys ({len(self.config.GEMINI_API_KEYS)}) dimuat untuk SSRP Chatlog.")
        else:
            logger.warning("⚠️ Gemini API keys (GEMINI_API_KEYS) tidak ditemukan di config.")

        self.openrouter_key_cycler = None
        # --- [PERBAIKAN REQ #2] Gunakan ..._KEYS (plural) dari config ---
        if hasattr(self.config, 'OPENROUTER_API_KEYS') and self.config.OPENROUTER_API_KEYS:
            self.openrouter_key_cycler = itertools.cycle(self.config.OPENROUTER_API_KEYS)
            self.openrouter_headers = {
                "HTTP-Referer": getattr(self.config, 'OPENROUTER_SITE_URL', 'http://localhost'),
                "X-Title": getattr(self.config, 'OPENROUTER_SITE_NAME', 'MBOT'),
            }
            logger.info(f"✅ OpenRouter keys ({len(self.config.OPENROUTER_API_KEYS)}) dimuat untuk SSRP Chatlog.")
        else:
            logger.warning("⚠️ OpenRouter API keys (OPENROUTER_API_KEY) tidak ditemukan di config.")

        self.agentrouter_key_cycler = None
        # --- [PERBAIKAN REQ #2] Gunakan ..._KEYS (plural) dari config ---
        if hasattr(self.config, 'AGENTROUTER_API_KEYS') and self.config.AGENTROUTER_API_KEYS:
            self.agentrouter_key_cycler = itertools.cycle(self.config.AGENTROUTER_API_KEYS)
            logger.info(f"✅ AgentRouter keys ({len(self.config.AGENTROUTER_API_KEYS)}) dimuat untuk SSRP Chatlog.")
        else:
            logger.warning("⚠️ AgentRouter API keys (AGENTROUTER_API_KEY) tidak ditemukan di config.")
        # --- [AKHIR PERBAIKAN REQ #2] ---

        # ===== STYLING SETTINGS (DIPERBAIKI) =====
        self.FONT_SIZE = 13  # Dinaikkan dari 12 untuk ketajaman
        self.LINE_HEIGHT_ADD = 4  # Sedikit ditambah
        self.FONT_PATH = self._find_font(["arial.ttf", "Arial.ttf", "arialbd.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"])

        # Warna teks (DIPERBAIKI: /do sama dengan /me)
        self.COLOR_CHAT = (255, 255, 255)
        self.COLOR_ME = (194, 162, 218)  # Ungu muda
        self.COLOR_DO = (194, 162, 218)  # SAMA DENGAN /me (bukan biru lagi)
        self.COLOR_WHISPER = (255, 255, 1)
        self.COLOR_LOWCHAT = (187, 187, 187)
        self.COLOR_DEATH = (255, 0, 0)
        self.COLOR_YELLOW = (255, 255, 0)
        self.COLOR_PALEYELLOW = (255, 236, 139)
        self.COLOR_GREY = (187, 187, 187)
        self.COLOR_GREEN = (51, 170, 51)
        self.COLOR_MONEY = (0, 128, 0)
        self.COLOR_OOC = (170, 170, 170)

        # Text shadow settings (DIPERBAIKI: shadow lebih tegas)
        self.COLOR_SHADOW = (0, 0, 0, 255)  # Shadow lebih gelap
        self.SHADOW_OFFSETS = [(-1, -1), (1, -1), (-1, 1), (1, 1), (0, -1), (-1, 0), (1, 0), (0, 1)]  # 8 arah

        # Background overlay
        self.BG_COLOR = (0, 0, 0, 180)

        # Muat font dengan antialiasing
        try:
            self.font = ImageFont.truetype(self.FONT_PATH, self.FONT_SIZE)
            logger.info(f"✅ Font '{os.path.basename(self.FONT_PATH)}' ({self.FONT_SIZE}pt) dimuat untuk SSRP.")
        except IOError:
            logger.warning(f"Font SSRP ({self.FONT_PATH}) tidak ditemukan, pakai default.")
            try:
                self.font = ImageFont.truetype("DejaVuSans.ttf", self.FONT_SIZE)
                logger.info("✅ Fallback ke DejaVuSans.")
            except IOError:
                self.font = ImageFont.load_default()
                logger.warning("⚠️ Gagal load DejaVuSans, pakai font default Pillow.")
        except Exception as e:
            logger.error(f"Error load font: {e}", exc_info=True)
            self.font = ImageFont.load_default()

    def _find_font(self, font_names: List[str]) -> str:
        """Mencari path font yang valid dari daftar nama."""
        font_dirs = []
        if os.name == 'nt':
            font_dirs.append(os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts'))
        elif os.name == 'posix':
            font_dirs.extend([
                '/usr/share/fonts',
                '/usr/local/share/fonts',
                os.path.expanduser('~/.fonts'),
                '/Library/Fonts',
                os.path.expanduser('~/Library/Fonts')
            ])

        for name in font_names:
            for dir_path in font_dirs:
                font_path = os.path.join(dir_path, name)
                if os.path.exists(font_path):
                    return font_path
                try:
                    for item in os.listdir(dir_path):
                        subdir_path = os.path.join(dir_path, item)
                        if os.path.isdir(subdir_path):
                             font_path_subdir = os.path.join(subdir_path, name)
                             if os.path.exists(font_path_subdir):
                                 return font_path_subdir
                except OSError:
                    continue

        logger.warning(f"Tidak dapat menemukan font: {font_names} di direktori {font_dirs}.")
        return font_names[0]

    # ===== FUNGSI CROP IMAGE KE RASIO 4:3 (BARU) =====
    def crop_to_4_3_ratio(self, img_bytes: bytes) -> bytes:
        """Crop gambar ke rasio 4:3 (800x600) jika bukan ukuran tersebut"""
        try:
            img = Image.open(io.BytesIO(img_bytes))
            original_width, original_height = img.size

            # Jika sudah 800x600, langsung return
            if original_width == 800 and original_height == 600:
                return img_bytes

            target_ratio = 4 / 3
            current_ratio = original_width / original_height

            # Crop ke rasio 4:3
            if current_ratio > target_ratio:
                # Gambar terlalu lebar, crop kiri-kanan
                new_width = int(original_height * target_ratio)
                left = (original_width - new_width) // 2
                img_cropped = img.crop((left, 0, left + new_width, original_height))
            else:
                # Gambar terlalu tinggi, crop atas-bawah
                new_height = int(original_width / target_ratio)
                top = (original_height - new_height) // 2
                img_cropped = img.crop((0, top, original_width, top + new_height))

            # Resize ke 800x600
            img_resized = img_cropped.resize((800, 600), Image.Resampling.LANCZOS)

            output = io.BytesIO()
            img_resized.save(output, format='PNG')
            output.seek(0)
            logger.info(f"✅ Gambar di-crop dari {original_width}x{original_height} ke 800x600")
            return output.getvalue()

        except Exception as e:
            logger.error(f"Error saat crop gambar: {e}")
            return img_bytes

    @commands.command(name="buatssrp", aliases=["createssrp"])
    async def create_ssrp(self, ctx: commands.Context):
        """Buat SSRP Chatlog dari gambar dengan AI (gaya Chatlog Magician)"""

        # --- [BARU REQ #3] Cek Limitasi AI berbasis Pangkat (Rank) ---
        can_use, remaining, limit = check_ai_limit(ctx.author.id)
        if not can_use:
            rank = get_user_rank(ctx.author.id)
            limit_display = "Unlimited" if limit == -1 else limit
            usage_today = (limit - remaining) if limit > 0 else 0
            await ctx.send(
                f"❌ Batas harian AI Anda (Rank: **{rank.title()}**) telah tercapai ({usage_today}/{limit_display}). Coba lagi besok."
            )
            return
        # --- [AKHIR PERBAIKAN REQ #3] ---

        if not self.openai_key_cycler and not self.deepseek_key_cycler and \
           not self.gemini_key_cycler and not self.openrouter_key_cycler and \
           not self.agentrouter_key_cycler:
            await ctx.send("❌ Fitur SSRP Chatlog tidak tersedia (Tidak ada API Key AI yang dikonfigurasi)")
            return

        if not ctx.message.attachments:
            embed = discord.Embed(
                title="📸 Cara Menggunakan `!buatssrp`",
                description="Lampirkan **1-10 gambar** (.png/.jpg) saat mengirim command.",
                color=discord.Color.blue()
            )
            embed.add_field(name="Langkah", value="1. Upload gambar\n2. Ketik `!buatssrp` di caption\n3. Ikuti instruksi di tombol & form", inline=False)
            embed.add_field(name="📏 Format Gambar", value="Gambar akan otomatis di-crop ke rasio 4:3 (800x600) untuk hasil optimal.", inline=False)
            await ctx.send(embed=embed)
            return

        images_bytes_list = []
        valid_extensions = ('.png', '.jpg', '.jpeg')
        count = 0

        for attachment in ctx.message.attachments:
            if count >= 10: break
            if attachment.filename.lower().endswith(valid_extensions):
                if attachment.size > 8 * 1024 * 1024:
                    await ctx.send(f"⚠️ Gambar `{attachment.filename}` terlalu besar (>8MB), dilewati.")
                    continue
                try:
                    img_bytes = await attachment.read()
                    # CROP GAMBAR KE RASIO 4:3 (BARU)
                    img_bytes_cropped = self.crop_to_4_3_ratio(img_bytes)
                    images_bytes_list.append(img_bytes_cropped)
                    count += 1
                except Exception as e:
                    logger.error(f"Gagal download/crop gambar '{attachment.filename}': {e}")
                    await ctx.send(f"❌ Gagal memproses `{attachment.filename}`.")

        if not images_bytes_list:
            await ctx.send("❌ Tidak ada gambar valid (.png/.jpg/.jpeg) yang ditemukan atau berhasil diunduh!")
            return

        modal = SSRPInfoModal(self, images_bytes_list)
        view = ui.View(timeout=180)
        button = ui.Button(label=f"📝 Isi Informasi SSRP ({len(images_bytes_list)} gambar)", style=discord.ButtonStyle.primary)

        async def button_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Hanya peminta asli yang bisa mengisi!", ephemeral=True)
                return
            await interaction.response.send_modal(modal)
            button.disabled = True
            try:
                await interaction.message.delete()
            except discord.NotFound:
                pass

        button.callback = button_callback
        view.add_item(button)

        embed_start = discord.Embed(
            title="✅ Gambar Diterima & Di-crop",
            description=f"`{len(images_bytes_list)}` gambar siap diproses (800x600). Klik tombol di bawah untuk melanjutkan.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed_start, view=view)

    async def process_ssrp(
        self,
        interaction: discord.Interaction,
        images_bytes_list: List[bytes],
        info_data: Dict,
        dialog_counts: List[int],
        positions: List[str],
        background_styles: List[str]
    ):
        """Proses generate dialog dan overlay ke gambar"""
        processing_msg = None
        try:
            await interaction.edit_original_response(
                 content=f"⏳ Memulai proses untuk {len(images_bytes_list)} gambar dengan AI...",
                 view=None, embed=None, attachments=[]
            )
            processing_msg = await interaction.channel.send(f"⏳ {interaction.user.mention} sedang memproses {len(images_bytes_list)} gambar SSRP...")

        except discord.NotFound:
            processing_msg = await interaction.channel.send(f"⏳ {interaction.user.mention} memulai proses {len(images_bytes_list)} gambar SSRP...")
        except Exception as e:
             logger.error(f"Error saat edit initial process_ssrp message: {e}")
             await interaction.channel.send(f"❌ Error memulai proses: {e}")
             return

        warnings = []

        try:
            await processing_msg.edit(content=f"🧠 {interaction.user.mention}, AI sedang membuat dialog...")

            language = info_data.get('language', 'Bahasa Indonesia baku')

            all_dialogs_raw, ai_used = await self.generate_dialogs_with_ai(
                images_bytes_list, info_data, dialog_counts, language,
                processing_msg, interaction.user.mention
            )

            # --- [BARU REQ #3] Tambah hitungan AI usage SETELAH AI berhasil ---
            increment_ai_usage(interaction.user.id)
            # --- [AKHIR PERBAIKAN REQ #3] ---

            processed_images_bytes = []
            for idx, (img_bytes, raw_dialogs, position, bg_style) in enumerate(zip(images_bytes_list, all_dialogs_raw, positions, background_styles)):

                limited_dialogs = raw_dialogs[:dialog_counts[idx]]

                await processing_msg.edit(
                    content=f"🎨 {interaction.user.mention}, memproses gambar {idx + 1}/{len(images_bytes_list)} ({len(limited_dialogs)} baris, bg: {bg_style})..."
                )

                processed_img = await self.add_dialogs_to_image(
                    img_bytes,
                    limited_dialogs,
                    position,
                    bg_style
                )
                processed_images_bytes.append(processed_img)
                await asyncio.sleep(0.2)

            final_content = f"✅ Selesai! Hasil SSRP untuk {interaction.user.mention}:"
            if warnings:
                warning_text = "\n".join(f"- {w}" for w in warnings)
                final_content += f"\n\n**Peringatan:**\n{warning_text}"

            await processing_msg.edit(content=final_content)

            for i in range(0, len(processed_images_bytes), 10):
                chunk = processed_images_bytes[i:i+10]
                files = [
                    discord.File(io.BytesIO(img_data), filename=f"ssrp_generated{i+j+1}.png")
                    for j, img_data in enumerate(chunk)
                ]

                embed_result = discord.Embed(
                    title=f"📸 Hasil SSRP Chatlog (Gambar {i+1}-{i+len(chunk)})",
                    color=discord.Color.green()
                )
                skenario = info_data.get('skenario', 'N/A')
                embed_result.add_field(
                    name="Skenario",
                    value=skenario[:1000] + "..." if len(skenario) > 1000 else skenario,
                    inline=False
                )
                embed_result.set_footer(text=f"Dialog Meggunakan Bahasa: {language}")

                await interaction.channel.send(embed=embed_result, files=files)

        except Exception as e:
            logger.error(f"Error saat proses SSRP: {e}", exc_info=True)
            error_message = f"❌ Terjadi kesalahan: {str(e)[:1500]}"
            if processing_msg:
                try:
                    await processing_msg.edit(content=f"{interaction.user.mention}, {error_message}")
                except discord.NotFound:
                    await interaction.channel.send(content=f"{interaction.user.mention}, {error_message}")
            else:
                 await interaction.channel.send(content=f"{interaction.user.mention}, {error_message}")

    # ===== FUNGSI AI DENGAN PROMPT DIPERBAIKI =====

    async def _generate_with_openai(self, api_key: str, prompt: str, image_content: Optional[Dict]) -> Optional[List[List[str]]]:
        """Coba generate dialog dengan OpenAI (Hanya Teks)"""
        try:
            client = AsyncOpenAI(api_key=api_key, timeout=30.0)
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Anda adalah penulis SSRP ahli. Output HANYA JSON."},
                    {"role": "user", "content": prompt} # --- PERBAIKAN: Hanya kirim teks prompt
                ],
                response_format={"type": "json_object"},
                max_tokens=3000,
                temperature=0.7
            )
            response_content = response.choices[0].message.content
            cleaned_response = re.sub(r'```json\s*|\s*```', '', response_content.strip(), flags=re.DOTALL)
            data = json.loads(cleaned_response)
            result = data.get("dialogs_per_image")
            if not result or not isinstance(result, list):
                 raise ValueError("Format JSON dari OpenAI tidak valid (bukan list).")
            return result
        except Exception as e:
            logger.warning(f"SPOILER: OpenAI Gagal: {e}")
            if "rate_limit_exceeded" in str(e).lower() or "429" in str(e):
                 raise Exception(f"OpenAI Rate Limit. Mencoba AI lain...") from e
            raise e

    async def _generate_with_agentrouter(self, api_key: str, prompt: str, image_content: Optional[Dict]) -> Optional[List[List[str]]]:
        """Coba generate dialog dengan Agent Router (Hanya Teks)"""
        try:
            client = AsyncOpenAI(
                api_key=api_key,
                base_url="https://agentrouter.org/v1",
                timeout=45.0
            )
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Anda adalah penulis SSRP ahli. Output HANYA JSON."},
                    {"role": "user", "content": prompt} # --- PERBAIKAN: Hanya kirim teks prompt
                ],
                response_format={"type": "json_object"},
                max_tokens=3000,
                temperature=0.7
            )
            response_content = response.choices[0].message.content
            cleaned_response = re.sub(r'```json\s*|\s*```', '', response_content.strip(), flags=re.DOTALL)
            data = json.loads(cleaned_response)
            result = data.get("dialogs_per_image")
            if not result or not isinstance(result, list):
                 raise ValueError("Format JSON dari AgentRouter tidak valid (bukan list).")
            return result
        except Exception as e:
            logger.warning(f"SPOILER: AgentRouter Gagal: {e}")
            raise e

    async def _generate_with_deepseek(self, api_key: str, prompt: str, image_content: Optional[Dict]) -> Optional[List[List[str]]]:
        """Coba generate dialog dengan DeepSeek (Hanya Teks)"""
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                payload = {
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.7,
                    "max_tokens": 3000
                }

                response = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                response.raise_for_status()

                response_json = response.json()
                response_content = response_json["choices"][0]["message"]["content"]

                cleaned_response = re.sub(r'```json\s*|\s*```', '', response_content.strip(), flags=re.DOTALL)

                data = json.loads(cleaned_response)
                result = data.get("dialogs_per_image")
                if not result or not isinstance(result, list):
                     raise ValueError("Format JSON dari DeepSeek tidak valid (bukan list).")
                return result
        except Exception as e:
            logger.warning(f"SPOILER: DeepSeek Gagal: {e}")
            raise e

    async def _generate_with_gemini(self, api_key: str, prompt: str, image_content: Optional[Dict]) -> Optional[List[List[str]]]:
        """Coba generate dialog dengan Gemini (Hanya Teks)"""
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash-latest')

            # --- PERBAIKAN: Hanya kirim teks prompt
            gemini_content = [prompt]
            # --- BLOK IMAGE DIHAPUS ---

            response = await model.generate_content_async(
                gemini_content,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.7
                ),
                request_options={"timeout": 60}
            )

            if response.prompt_feedback.block_reason:
                raise Exception(f"Gemini diblokir: {response.prompt_feedback.block_reason.name}")
            if response.candidates and response.candidates[0].finish_reason.name != "STOP":
                raise Exception(f"Gemini finish reason: {response.candidates[0].finish_reason.name}")

            cleaned_response = re.sub(r'```json\s*|\s*```', '', response.text.strip(), flags=re.DOTALL)
            if not cleaned_response:
                 raise ValueError("Respons JSON dari Gemini kosong setelah dibersihkan.")

            data = json.loads(cleaned_response)
            result = data.get("dialogs_per_image")
            if not result or not isinstance(result, list):
                 raise ValueError("Format JSON dari Gemini tidak valid (bukan list).")
            return result
        except Exception as e:
            logger.warning(f"SPOILER: Gemini Gagal: {e}")
            raise e

    async def _generate_with_openrouter(self, api_key: str, prompt: str, image_content: Optional[Dict]) -> Optional[List[List[str]]]:
        """Coba generate dialog dengan OpenRouter (Hanya Teks)"""
        # --- PERBAIKAN: Hapus cek image content

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # --- PERBAIKAN: Model Teks dan Payload Teks ---
                payload = {
                    "model": "mistralai/mistral-7b-instruct:free", # Model Teks Gratis
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt # Hanya Teks
                        }
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.7,
                    "max_tokens": 3000
                }
                # --- AKHIR PERBAIKAN PAYLOAD ---

                headers = {"Authorization": f"Bearer {api_key}"}
                if hasattr(self, 'openrouter_headers'):
                    headers.update(self.openrouter_headers)

                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()

                response_json = response.json()
                response_content = response_json["choices"][0]["message"]["content"]

                cleaned_response = re.sub(r'```json\s*|\s*```', '', response_content.strip(), flags=re.DOTALL)

                data = json.loads(cleaned_response)
                result = data.get("dialogs_per_image")
                if not result or not isinstance(result, list):
                    raise ValueError("Format JSON dari OpenRouter tidak valid (bukan list).")
                return result
        except Exception as e:
            logger.warning(f"SPOILER: OpenRouter Gagal: {e}")
            raise e

    # ===== PROMPT AI YANG DIPERBAIKI =====
    async def generate_dialogs_with_ai(
        self,
        images_bytes_list: List[bytes],
        info_data: Dict,
        dialog_counts: List[int],
        language: str,
        processing_msg: discord.Message,
        user_mention: str
    ) -> Tuple[List[List[str]], str]:
        """Generate dialog SSRP SAMP dengan fallback AI - HANYA TEKS - PROMPT DIPERBAIKI"""

        dialog_requirements = "\n".join([f"Gambar {i+1}: HARUS berisi TEPAT {count} baris dialog." for i, count in enumerate(dialog_counts)])
        char_details = info_data.get('detail_karakter', '')
        char_names_raw = re.findall(r"([A-Za-z']+(?:\s+[A-Za-z']+)*)", char_details)
        if not char_names_raw:
            char_names_raw = [line.split('(')[0].strip() for line in char_details.split('\n') if line.strip()]
            char_names_raw = [re.sub(r"[^A-Za-z\s]+", "", name).strip() for name in char_names_raw if name]
        char_names_formatted = [name.replace(' ', ' ') for name in char_names_raw if name]  # TANPA underscore

        # ===== PROMPT YANG SANGAT KETAT (DIPERBAIKI) =====
        prompt = f"""
Anda adalah penulis dialog SSRP server SAMP profesional. PATUHI ATURAN INI:
Anda HANYA boleh menggunakan TEKS di bawah ini. JANGAN gunakan gambar.

KONTEKS (HANYA TEKS):
- Karakter: {info_data.get('detail_karakter', 'N/A')}
- Nama AI (TANPA underscore): {', '.join(char_names_formatted)}
- Skenario: {info_data.get('skenario', 'N/A')}
- Bahasa: {language}
- Jumlah Gambar (untuk pembagian dialog): {len(images_bytes_list)}

KEBUTUHAN BARIS PER GAMBAR:
{dialog_requirements}

ATURAN FORMAT KETAT ({language}):

1. **CHAT BIASA** - Format: `Nama Karakter says: Teks dialog.`
   - JANGAN tulis "Chat:" di depan
   - Nama TANPA underscore (gunakan spasi)
   - Maksimal 50 kata per dialog
   - Contoh: `John Doe says: Halo, apa kabar?`

2. **LOW CHAT** - Format: `Nama Karakter [low]: Teks dialog.`
   - Nama TANPA underscore
   - Maksimal 40 kata
   - Contoh: `Jane Smith [low]: Psst, dengar ini.`

3. **/ME (AKSI)** - Format: `*Nama Karakter aksi tanpa titik akhir`
   - HANYA satu bintang (*)
   - Nama di AWAL, lalu aksi
   - TANPA titik di akhir
   - TANPA underscore di nama
   - Maksimal 45 kata
   - Contoh: `*John Doe mengangguk pelan sambil tersenyum`

4. **/DO (DESKRIPSI)** - Format: `*Deskripsi kejadian (( Nama Karakter ))`
   - Hanya Satu bintang (*)
   - Nama di AKHIR dalam tanda kurung (( ))
   - TANPA underscore di nama
   - Maksimal 50 kata
   - Contoh: `*Angin sepoi-sepoi menerpa wajahnya dengan lembut (( Jane Smith ))`

5. **WHISPER/PHONE** - JANGAN GUNAKAN format `whispers:` atau `(phone):` KECUALI jika Skenario secara eksplisit memintanya (e.g., "skenario: berbisik di telepon"). Jika tidak, fokus pada format 1-4.

6. **JANGAN GUNAKAN**:
   - Radio format (`** [CH:X]`)
   - Department format (`** [Dept]`)
   - Format whisper/phone KECUALI diminta Skenario.

7. **PANJANG DIALOG**:
   - Setiap baris maksimal 60 kata
   - Jika ada dialog panjang, pecah jadi beberapa baris

OUTPUT JSON:
{{
  "dialogs_per_image": [
    ["dialog baris 1 gambar 1", "dialog baris 2 gambar 1", ...],
    ["dialog baris 1 gambar 2", "dialog baris 2 gambar 2", ...],
    ...
  ]
}}

PENTING:
- Nama karakter HARUS tanpa underscore (gunakan spasi)
- Jumlah baris HARUS TEPAT sesuai kebutuhan
- Dialog natural, logis, sesuai skenario
- Variasikan format (jangan semua says)
- Lanjutkan cerita antar gambar
"""

        dialogs_list = None
        ai_used = "Tidak ada"

        # --- PERBAIKAN: Kirim 'None' untuk argumen image_content ---

        # Coba OpenRouter (Prioritas 1)
        if self.openrouter_key_cycler:
            try:
                await processing_msg.edit(content=f"🧠 {user_mention}, Mencoba OpenRouter (Teks)...")
                key = next(self.openrouter_key_cycler)
                dialogs_list = await self._generate_with_openrouter(key, prompt, None)
                if dialogs_list: ai_used = "OpenRouter (Teks)"
            except Exception as e:
                 logger.error(f"====== SSRP: OPENROUTER GAGAL: {e} ======")
                 await processing_msg.edit(content=f"⚠️ {user_mention}, OpenRouter gagal... Mencoba AgentRouter...")
                 await asyncio.sleep(1)

        # Coba AgentRouter (Prioritas 2)
        if not dialogs_list and self.agentrouter_key_cycler:
            try:
                await processing_msg.edit(content=f"🧠 {user_mention}, Mencoba AgentRouter (Teks)...")
                key = next(self.agentrouter_key_cycler)
                dialogs_list = await self._generate_with_agentrouter(key, prompt, None)
                if dialogs_list: ai_used = "AgentRouter (Teks)"
            except Exception as e:
                 logger.error(f"====== SSRP: AGENTROUTER GAGAL: {e} ======")
                 await processing_msg.edit(content=f"⚠️ {user_mention}, AgentRouter gagal... Mencoba OpenAI...")
                 await asyncio.sleep(1)

        # Coba OpenAI (Fallback 1)
        if not dialogs_list and self.openai_key_cycler:
            try:
                await processing_msg.edit(content=f"🧠 {user_mention}, Mencoba OpenAI (Teks)...")
                key = next(self.openai_key_cycler)
                dialogs_list = await self._generate_with_openai(key, prompt, None)
                if dialogs_list: ai_used = "OpenAI (Teks)"
            except Exception as e:
                 logger.error(f"====== SSRP: OPENAI GAGAL: {e} ======")
                 await processing_msg.edit(content=f"⚠️ {user_mention}, OpenAI gagal... Mencoba Gemini...")
                 await asyncio.sleep(1)

        # Coba Gemini (Fallback 2)
        if not dialogs_list and self.gemini_key_cycler:
            try:
                await processing_msg.edit(content=f"🧠 {user_mention}, Mencoba Gemini (Teks)...")
                key = next(self.gemini_key_cycler)
                dialogs_list = await self._generate_with_gemini(key, prompt, None)
                if dialogs_list: ai_used = "Gemini (Teks)"
            except Exception as e:
                 logger.error(f"====== SSRP: GEMINI GAGAL: {e} ======")
                 await processing_msg.edit(content=f"⚠️ {user_mention}, Gemini gagal... Mencoba DeepSeek...")
                 await asyncio.sleep(1)

        # Coba DeepSeek (Fallback 3)
        if not dialogs_list and self.deepseek_key_cycler:
            try:
                await processing_msg.edit(content=f"🧠 {user_mention}, Mencoba DeepSeek (Hanya Teks)...")
                key = next(self.deepseek_key_cycler)
                dialogs_list = await self._generate_with_deepseek(key, prompt, None)
                if dialogs_list: ai_used = "DeepSeek (Text-Only)"
            except Exception as e:
                 logger.error(f"====== SSRP: DEEPSEEK GAGAL: {e} ======")
                 await processing_msg.edit(content=f"⚠️ {user_mention}, DeepSeek gagal...")
                 await asyncio.sleep(1)

        if not dialogs_list:
            logger.error("Semua API AI gagal untuk SSRP Chatlog setelah fallback.")
            raise Exception("Semua layanan AI gagal dihubungi atau error.")

        # Padding/Truncating
        while len(dialogs_list) < len(images_bytes_list):
            dialogs_list.append([f"[AI Error Gbr {len(dialogs_list)+1}]"])
        dialogs_list = dialogs_list[:len(images_bytes_list)]

        logger.info(f"AI ({ai_used}) generated dialogs for {len(dialogs_list)} images in '{language}'.")
        return dialogs_list, ai_used

    # ===== FUNGSI RENDER TEXT YANG DIPERBAIKI (TANPA WORDWRAP) =====
    async def add_dialogs_to_image(
        self,
        image_bytes: bytes,
        dialogs: List[str],
        position: str,
        background_style: str
    ) -> bytes:
        """Tambahkan dialog ke gambar dengan styling SEMPURNA & TANPA word wrap"""
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
            width, height = img.size
            txt_overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(txt_overlay)
            padding = 10

            # --- PERBAIKAN: Logika textwrap dihapus total ---
            wrapped_dialog_lines = []
            for dialog in dialogs:
                wrapped_dialog_lines.append(dialog)
            # --- AKHIR PERBAIKAN ---

            # Hitung Tinggi & Posisi Y
            total_lines = len(wrapped_dialog_lines)
            line_pixel_height = self.FONT_SIZE + self.LINE_HEIGHT_ADD
            total_dialog_height_pixels = (total_lines * line_pixel_height) + (padding * 2)

            y_coords = []

            # Gambar Background & Tentukan y_coords
            if background_style == "overlay":
                if position == "atas":
                    bg_y_end = min(total_dialog_height_pixels, height)
                    draw.rectangle([(0, 0), (width, bg_y_end)], fill=self.BG_COLOR)
                    y_coords.append(padding)
                elif position == "bawah":
                    bg_y_start_rect = max(0, height - total_dialog_height_pixels)
                    draw.rectangle([(0, bg_y_start_rect), (width, height)], fill=self.BG_COLOR)
                    y_coords.append(bg_y_start_rect + padding)
                else:  # split
                    half_lines_idx = (total_lines + 1) // 2
                    top_lines = wrapped_dialog_lines[:half_lines_idx]
                    bottom_lines = wrapped_dialog_lines[half_lines_idx:]

                    top_height_pixels = (len(top_lines) * line_pixel_height) + (padding * 2) if top_lines else 0
                    bg_top_end = min(top_height_pixels, height)
                    draw.rectangle([(0, 0), (width, bg_top_end)], fill=self.BG_COLOR)
                    y_coords.append(padding)

                    bottom_height_pixels = (len(bottom_lines) * line_pixel_height) + (padding * 2) if bottom_lines else 0
                    bg_bottom_start_rect = max(0, height - bottom_height_pixels)
                    draw.rectangle([(0, bg_bottom_start_rect), (width, height)], fill=self.BG_COLOR)
                    y_coords.append(bg_bottom_start_rect + padding)

            else:  # transparent
                 if position == "atas":
                     y_coords.append(padding)
                 elif position == "bawah":
                     y_coords.append(max(padding, height - total_dialog_height_pixels + padding))
                 else:  # split transparent
                     half_lines_idx = (total_lines + 1) // 2
                     y_coords.append(padding)
                     bottom_lines_count = total_lines - half_lines_idx
                     bottom_height_pixels = (bottom_lines_count * line_pixel_height) + (padding * 2) if bottom_lines_count > 0 else 0
                     y_coords.append(max(padding, height - bottom_height_pixels + padding))

            # Draw Dialogs
            if position == "split":
                half_lines_idx = (total_lines + 1) // 2
                y_pos_top = y_coords[0]
                for line in wrapped_dialog_lines[:half_lines_idx]:
                    self.draw_text_with_multi_shadow(draw, (padding, y_pos_top), line, self.font)
                    y_pos_top += line_pixel_height
                y_pos_bottom = y_coords[1]
                for line in wrapped_dialog_lines[half_lines_idx:]:
                    self.draw_text_with_multi_shadow(draw, (padding, y_pos_bottom), line, self.font)
                    y_pos_bottom += line_pixel_height
            else:  # atas atau bawah
                y_pos = y_coords[0]
                for line in wrapped_dialog_lines:
                    self.draw_text_with_multi_shadow(draw, (padding, y_pos), line, self.font)
                    y_pos += line_pixel_height

            out_img = Image.alpha_composite(img, txt_overlay)

            output = io.BytesIO()
            out_img.convert("RGB").save(output, format='PNG', quality=95)  # Quality tinggi
            output.seek(0)
            return output.getvalue()

        except Exception as e:
            logger.error(f"Error di add_dialogs_to_image: {e}", exc_info=True)
            return image_bytes

    # ===== FUNGSI WARNA & RENDER TEXT YANG DIPERBAIKI =====
    def get_text_color(self, text: str) -> tuple:
        """Tentukan warna teks - DIPERBAIKI (DO sama dengan ME)"""
        text_lower = text.strip().lower()

        # /do (DUA bintang, nama di akhir)
        if text.startswith('*') and '(( ' in text and ' ))' in text:
            return self.COLOR_DO  # Warna SAMA dengan /me

        # /me (SATU bintang, nama di awal)
        if text.startswith('*') and not text.startswith('**'):
            return self.COLOR_ME

        # Whisper
        if ' whispers:' in text_lower or '(phone):' in text_lower or ':o<' in text:
            return self.COLOR_WHISPER

        # Low chat
        if ' [low]:' in text_lower:
            return self.COLOR_LOWCHAT

        # Chat biasa
        if ' says:' in text_lower:
            return self.COLOR_CHAT

        # OOC
        if '(( ' in text and ' ))' in text and not text.startswith('**'):
            return self.COLOR_OOC

        return self.COLOR_CHAT

    def draw_text_with_multi_shadow(self, draw: ImageDraw.ImageDraw, pos: Tuple[int, int], text: str, font: ImageFont.FreeTypeFont):
        """Gambar teks dengan shadow 8 arah dan penyesuaian nama TANPA underscore"""
        x, y = pos
        text_color = self.get_text_color(text)
        cleaned_text = text

        # Hapus underscore dari nama di semua format
        # Format: "Nama_Karakter says:" -> "Nama Karakter says:"
        match_say = re.match(r"^\s*([A-Za-z0-9_]+)\s+says:", text, re.IGNORECASE)
        match_low = re.match(r"^\s*([A-Za-z0-9_]+)\s+\[low\]:", text, re.IGNORECASE)
        match_whisper = re.match(r"^\s*([A-Za-z0-9_]+)\s+whispers:", text, re.IGNORECASE)

        if match_say:
            name = match_say.group(1).replace('_', ' ')
            rest_of_line = text[match_say.end():]
            cleaned_text = f"{name} says:{rest_of_line}"
            if not rest_of_line.startswith(' '):
                 cleaned_text = f"{name} says: {rest_of_line.lstrip()}"

        elif match_low:
            name = match_low.group(1).replace('_', ' ')
            rest_of_line = text[match_low.end():]
            cleaned_text = f"{name} [low]:{rest_of_line}"
            if not rest_of_line.startswith(' '):
                 cleaned_text = f"{name} [low]: {rest_of_line.lstrip()}"

        elif match_whisper:
            name = match_whisper.group(1).replace('_', ' ')
            rest_of_line = text[match_whisper.end():]
            cleaned_text = f"{name} whispers:{rest_of_line}"
            if not rest_of_line.startswith(' '):
                 cleaned_text = f"{name} whispers: {rest_of_line.lstrip()}"

        # /me format: "* Nama_Karakter aksi" -> "* Nama Karakter aksi"
        elif text.startswith('*') and not text.startswith('**'):
            parts = text.split(' ', 2)
            if len(parts) >= 3:
                name = parts[1].replace('_', ' ')
                action = parts[2]
                cleaned_text = f"* {name} {action}"
            elif len(parts) == 2:
                 name = parts[1].replace('_', ' ')
                 cleaned_text = f"* {name}"

        # /do format: "** Deskripsi (( Nama_Karakter ))" -> "** Deskripsi (( Nama Karakter ))"
        elif text.startswith('*'):
            # Cari dan replace underscore dalam (( Nama_Karakter ))
            cleaned_text = re.sub(
                r'\(\(\s*([A-Za-z0-9_]+(?:\s+[A-Za-z0-9_]+)*)\s*\)\)',
                lambda m: f"(( {m.group(1).replace('_', ' ')} ))",
                text
            )

        # Shadow dengan 8 arah untuk ketajaman maksimal
        for dx, dy in self.SHADOW_OFFSETS:
            draw.text((x + dx, y + dy), cleaned_text, font=font, fill=self.COLOR_SHADOW)

        # Text utama dengan antialiasing
        draw.text(pos, cleaned_text, font=font, fill=text_color)


# Setup function
async def setup(bot):
    await bot.add_cog(SSRPChatlogCog(bot))

