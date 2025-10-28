# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import ui
import logging
import io
import base64
from PIL import Image, ImageDraw, ImageFont, ImageOps
from openai import AsyncOpenAI # Untuk OpenAI
import httpx # Untuk DeepSeek
import google.generativeai as genai # Untuk Gemini
from typing import List, Dict, Optional, Tuple
import asyncio
import re
import os
import json
import textwrap # Import textwrap untuk word wrapping
import itertools # Import untuk key cycler

logger = logging.getLogger(__name__)

# ============================
# MODAL & VIEW COMPONENTS
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
        # --- PERBAIKAN: Ubah default ke transparent ---
        self.background_styles = ["transparent"] * len(images) # Default transparent
        self.current_image_index = 0

        self.update_ui()

    def update_ui(self):
        """Update tombol dan select berdasarkan gambar saat ini"""
        self.clear_items()

        self.add_item(DialogCountSelect(self, self.dialog_counts[self.current_image_index]))
        self.add_item(PositionSelect(self, self.positions[self.current_image_index]))
        self.add_item(BackgroundStyleSelect(self, self.background_styles[self.current_image_index])) # Tambahkan select background

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
        embed.add_field(name="Background", value=f"`{self.background_styles[idx].capitalize()}`", inline=True) # Tampilkan style background

        try:
            file = discord.File(io.BytesIO(self.images[idx]), filename=f"image_preview_{idx}.png")
            embed.set_image(url=f"attachment://image_preview_{idx}.png")
            await interaction.response.edit_message(embed=embed, view=self, attachments=[file])
        except Exception as e:
            logger.error(f"Gagal update message preview: {e}")
            # Coba edit tanpa attachment jika gagal
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
        # 'current_value' akan 'transparent' by default dari DialogSettingsView
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
            self.parent_view.background_styles # Kirim background styles
        )


# ============================
# COG UTAMA (REVISED WITH MULTI-AI)
# ============================

class SSRPChatlogCog(commands.Cog, name="SSRPChatlog"):
    """Cog untuk membuat SSRP Chatlog dengan AI - Styling seperti Chatlog Magician"""

    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config # Akses config dari bot

        # --- Setup API Clients & Key Cyclers ---
        self.openai_client = None # Tidak dipakai lagi, diganti per-request
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
        # --- End Setup API ---


        # ===== STYLING SETTINGS (DISESUAIKAN DENGAN CHATLOG MAGICIAN) =====
        self.FONT_SIZE = 12
        self.LINE_HEIGHT_ADD = 3 # Kurangi spasi antar baris
        self.FONT_PATH = self._find_font(["arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"])

        # Warna teks
        self.COLOR_CHAT = (255, 255, 255); self.COLOR_ME = (194, 162, 218)
        self.COLOR_DO = (153, 204, 255); self.COLOR_WHISPER = (255, 255, 1)
        self.COLOR_LOWCHAT = (187, 187, 187); self.COLOR_DEATH = (255, 0, 0)
        self.COLOR_YELLOW = (255, 255, 0); self.COLOR_PALEYELLOW = (255, 236, 139)
        self.COLOR_GREY = (187, 187, 187); self.COLOR_GREEN = (51, 170, 51)
        self.COLOR_MONEY = (0, 128, 0); self.COLOR_NEWS = (16, 244, 65)
        self.COLOR_RADIO = self.COLOR_PALEYELLOW; self.COLOR_DEP = (251, 132, 131)
        self.COLOR_OOC = (170, 170, 170)

        # Text shadow settings (4 arah)
        self.COLOR_SHADOW = (0, 0, 0)
        self.SHADOW_OFFSETS = [(-1, -1), (1, -1), (-1, 1), (1, 1)]

        # Background overlay
        self.BG_COLOR = (0, 0, 0, 180) # Hitam semi-transparan (alpha 180/255)

        # Muat font
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
                '/Library/Fonts', # macOS
                os.path.expanduser('~/Library/Fonts') # macOS user
            ])

        for name in font_names:
            for dir_path in font_dirs:
                # Cek langsung di direktori
                font_path = os.path.join(dir_path, name)
                if os.path.exists(font_path):
                    return font_path

                # Cek rekursif 1 level
                try:
                    for item in os.listdir(dir_path):
                        subdir_path = os.path.join(dir_path, item)
                        if os.path.isdir(subdir_path):
                             font_path_subdir = os.path.join(subdir_path, name)
                             if os.path.exists(font_path_subdir):
                                 return font_path_subdir
                except OSError: # Izin baca
                    continue

        logger.warning(f"Tidak dapat menemukan font: {font_names} di direktori {font_dirs}.")
        return font_names[0] # Kembalikan nama pertama sebagai fallback

    @commands.command(name="buatssrp", aliases=["createssrp"])
    async def create_ssrp(self, ctx: commands.Context):
        """Buat SSRP Chatlog dari gambar dengan AI (gaya Chatlog Magician)"""

        # Cek ketersediaan AI
        if not self.openai_key_cycler and not self.deepseek_key_cycler and not self.gemini_key_cycler:
            await ctx.send("❌ Fitur SSRP Chatlog tidak tersedia (Tidak ada API Key AI yang dikonfigurasi)")
            return

        if not ctx.message.attachments:
            embed = discord.Embed(
                title="📸 Cara Menggunakan `!buatssrp`",
                description="Lampirkan **1-10 gambar** (.png/.jpg) saat mengirim command.",
                color=discord.Color.blue()
            )
            embed.add_field(name="Langkah", value="1. Upload gambar\n2. Ketik `!buatssrp` di caption\n3. Ikuti instruksi di tombol & form", inline=False)
            await ctx.send(embed=embed)
            return

        images_bytes_list = []
        valid_extensions = ('.png', '.jpg', '.jpeg'); count = 0
        for attachment in ctx.message.attachments:
            if count >= 10: break # Batasi 10 gambar
            if attachment.filename.lower().endswith(valid_extensions):
                if attachment.size > 8 * 1024 * 1024:
                    await ctx.send(f"⚠️ Gambar `{attachment.filename}` terlalu besar (>8MB), dilewati.")
                    continue
                try:
                    img_bytes = await attachment.read()
                    images_bytes_list.append(img_bytes)
                    count += 1
                except Exception as e:
                    logger.error(f"Gagal download gambar '{attachment.filename}': {e}")
                    await ctx.send(f"❌ Gagal mengunduh `{attachment.filename}`.")
            
        if not images_bytes_list:
            await ctx.send("❌ Tidak ada gambar valid (.png/.jpg/.jpeg) yang ditemukan atau berhasil diunduh!")
            return

        modal = SSRPInfoModal(self, images_bytes_list)
        view = ui.View(timeout=180)
        button = ui.Button(label=f"📝 Isi Informasi SSRP ({len(images_bytes_list)} gambar)", style=discord.ButtonStyle.primary)

        async def button_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Hanya peminta asli yang bisa mengisi!", ephemeral=True); return
            await interaction.response.send_modal(modal)
            button.disabled = True
            try:
                await interaction.message.edit(view=view)
            except discord.NotFound: pass

        button.callback = button_callback
        view.add_item(button)

        embed_start = discord.Embed(
            title="✅ Gambar Diterima",
            description=f"`{len(images_bytes_list)}` gambar siap diproses. Klik tombol di bawah untuk melanjutkan.",
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
        background_styles: List[str] # Terima background styles
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

        warnings = [] # Kumpulkan peringatan ukuran gambar

        try:
            await processing_msg.edit(content=f"🧠 {interaction.user.mention}, AI sedang membuat dialog...")

            language = info_data.get('language', 'Bahasa Indonesia baku')

            # --- Panggil Fungsi AI dengan Fallback ---
            all_dialogs_raw, ai_used = await self.generate_dialogs_with_ai(
                images_bytes_list, info_data, dialog_counts, language, 
                processing_msg, interaction.user.mention
            )
            # --- Akhir Panggil AI ---


            processed_images_bytes = []
            for idx, (img_bytes, raw_dialogs, position, bg_style) in enumerate(zip(images_bytes_list, all_dialogs_raw, positions, background_styles)):

                # --- Pengecekan Ukuran Gambar ---
                try:
                    img_check = Image.open(io.BytesIO(img_bytes))
                    if img_check.width != 800 or img_check.height != 600:
                        warnings.append(f"Gambar {idx+1} ({img_check.width}x{img_check.height}) bukan 800x600, hasil mungkin kurang optimal.")
                    img_check.close() # Tutup setelah cek
                except Exception as img_err:
                    logger.warning(f"Gagal memeriksa ukuran gambar {idx+1}: {img_err}")
                # --- Akhir Pengecekan ---

                limited_dialogs = raw_dialogs[:dialog_counts[idx]]

                await processing_msg.edit(
                    content=f"🎨 {interaction.user.mention}, memproses gambar {idx + 1}/{len(images_bytes_list)} ({len(limited_dialogs)} baris, bg: {bg_style}, AI: {ai_used})..."
                )

                # Panggil fungsi overlay yang sudah diperbarui
                processed_img = await self.add_dialogs_to_image(
                    img_bytes,
                    limited_dialogs,
                    position,
                    bg_style # Pass background style
                )
                processed_images_bytes.append(processed_img)
                await asyncio.sleep(0.2) # Perkecil delay

            final_content = f"✅ Selesai! Hasil SSRP untuk {interaction.user.mention} (AI: {ai_used}):"
            if warnings:
                warning_text = "\n".join(f"- {w}" for w in warnings)
                final_content += f"\n\n**Peringatan:**\n{warning_text}"

            await processing_msg.edit(content=final_content)

            # Kirim hasil dalam chunk (output PNG)
            for i in range(0, len(processed_images_bytes), 10):
                chunk = processed_images_bytes[i:i+10]
                files = [
                    discord.File(io.BytesIO(img_data), filename=f"ssrp_generated{i+j+1}.png") # Simpan sebagai PNG
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
                embed_result.set_footer(text=f"Dialog AI ({ai_used}) dalam: {language}")

                await interaction.channel.send(embed=embed_result, files=files)

        except Exception as e:
            logger.error(f"Error saat proses SSRP: {e}", exc_info=True)
            error_message = f"❌ Terjadi kesalahan: {str(e)[:1500]}"
            if processing_msg:
                try:
                    await processing_msg.edit(content=f"{interaction.user.mention}, {error_message}")
                except discord.NotFound: # Jika pesan sudah dihapus
                    await interaction.channel.send(content=f"{interaction.user.mention}, {error_message}")
            else:
                 await interaction.channel.send(content=f"{interaction.user.mention}, {error_message}")

    # --- Fungsi Helper Pemanggilan AI ---
    
    async def _generate_with_openai(self, api_key: str, prompt: str, image_content: Dict) -> Optional[List[List[str]]]:
        """Coba generate dialog dengan OpenAI"""
        try:
            client = AsyncOpenAI(api_key=api_key, timeout=30.0)
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Anda adalah penulis SSRP ahli. Output HANYA JSON."},
                    {"role": "user", "content": [{"type": "text", "text": prompt}, image_content]}
                ],
                response_format={"type": "json_object"}, 
                max_tokens=3000, 
                temperature=0.7
            )
            response_content = response.choices[0].message.content
            # Tambah pembersihan ringan jika JSON terbungkus markdown
            cleaned_response = re.sub(r'```json\s*|\s*```', '', response_content.strip(), flags=re.DOTALL)
            data = json.loads(cleaned_response)
            result = data.get("dialogs_per_image")
            if not result or not isinstance(result, list):
                 raise ValueError("Format JSON dari OpenAI tidak valid (bukan list).")
            return result
        except Exception as e:
            logger.warning(f"OpenAI gagal: {e}")
            if "rate_limit_exceeded" in str(e).lower() or "429" in str(e):
                 # Umpan balik spesifik untuk rate limit
                 raise Exception(f"OpenAI Rate Limit. Mencoba AI lain...") from e
            return None # Gagal karena alasan lain

    async def _generate_with_deepseek(self, api_key: str, prompt: str, image_content: Optional[Dict]) -> Optional[List[List[str]]]:
        """Coba generate dialog dengan DeepSeek (Note: DeepSeek mungkin tidak support gambar)"""
        # DeepSeek Chat API mungkin tidak secara langsung support gambar dalam format OpenAI
        # Kita hanya kirim prompt teksnya saja.
        try:
            async with httpx.AsyncClient(timeout=45.0) as client: # Timeout lebih lama
                # Buat payload hanya teks
                payload = {
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}], # Hanya teks
                    "response_format": {"type": "json_object"},
                    "temperature": 0.7,
                    "max_tokens": 3000
                }
                
                response = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                response.raise_for_status() # Error jika status 4xx atau 5xx
                
                # Ekstrak konten teks, lalu parse JSON
                response_json = response.json()
                response_content = response_json["choices"][0]["message"]["content"]
                
                # DeepSeek kadang membungkus JSON dalam markdown, bersihkan
                cleaned_response = re.sub(r'```json\s*|\s*```', '', response_content.strip(), flags=re.DOTALL)
                
                data = json.loads(cleaned_response)
                result = data.get("dialogs_per_image")
                if not result or not isinstance(result, list):
                     raise ValueError("Format JSON dari DeepSeek tidak valid (bukan list).")
                return result
        except Exception as e:
            logger.warning(f"DeepSeek gagal: {e}")
            return None

    async def _generate_with_gemini(self, api_key: str, prompt: str, image_content: Optional[Dict]) -> Optional[List[List[str]]]:
        """Coba generate dialog dengan Gemini"""
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash') # Gunakan model yang support vision & JSON

            gemini_content = [prompt] # Selalu mulai dengan prompt

            # Konversi format gambar OpenAI ke Gemini
            if image_content and image_content['type'] == 'image_url':
                 img_url_data = image_content['image_url']['url']
                 if img_url_data.startswith('data:image/'):
                     # Ekstrak base64 data
                     mime_type, base64_data = img_url_data.split(';base64,')
                     mime_type = mime_type.split(':')[1]
                     # Buat Image object dari bytes
                     img_bytes = base64.b64decode(base64_data)
                     img_part = Image.open(io.BytesIO(img_bytes))
                     gemini_content.append(img_part) # Tambahkan objek gambar PIL
                 else:
                     logger.warning("Format image_content tidak didukung untuk Gemini (bukan base64).")
            
            response = await model.generate_content_async(
                gemini_content,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json", # Minta JSON
                    temperature=0.7
                ),
                request_options={"timeout": 60} # Timeout 60 detik
            )

            # Cek safety ratings
            if response.prompt_feedback.block_reason:
                raise Exception(f"Gemini diblokir: {response.prompt_feedback.block_reason.name}")
            if response.candidates and response.candidates[0].finish_reason.name != "STOP":
                raise Exception(f"Gemini finish reason: {response.candidates[0].finish_reason.name}")

            # Bersihkan markdown dari respons JSON
            cleaned_response = re.sub(r'```json\s*|\s*```', '', response.text.strip(), flags=re.DOTALL)
            if not cleaned_response:
                 raise ValueError("Respons JSON dari Gemini kosong setelah dibersihkan.")
            
            data = json.loads(cleaned_response)
            result = data.get("dialogs_per_image")
            if not result or not isinstance(result, list):
                 raise ValueError("Format JSON dari Gemini tidak valid (bukan list).")
            return result
        except Exception as e:
            logger.warning(f"Gemini gagal: {e}")
            return None

    async def generate_dialogs_with_ai(
        self,
        images_bytes_list: List[bytes],
        info_data: Dict,
        dialog_counts: List[int],
        language: str,
        processing_msg: discord.Message, # Untuk update status
        user_mention: str # Untuk update status
    ) -> Tuple[List[List[str]], str]:
        """Generate dialog SSRP SAMP dengan fallback AI"""

        # --- Setup prompt dan image content (hanya gambar pertama) ---
        base64_img = base64.b64encode(images_bytes_list[0]).decode('utf-8')
        image_content_openai = {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
        }
        dialog_requirements = "\n".join([f"Gambar {i+1}: HARUS berisi TEPAT {count} baris dialog." for i, count in enumerate(dialog_counts)])
        char_details = info_data.get('detail_karakter', ''); char_names_raw = re.findall(r"([A-Za-z'_]+(?: [A-Za-z'_]+)?)", char_details)
        if not char_names_raw:
            char_names_raw = [line.split('(')[0].strip() for line in char_details.split('\n') if line.strip()]; char_names_raw = [re.sub(r"[^A-Za-z\s]+", "", name).strip() for name in char_names_raw if name]
        char_names_formatted = [name.replace(' ', '_') for name in char_names_raw if name]

        # Prompt ringkas untuk menghemat token
        prompt = f"""
        Anda adalah penulis dialog SSRP server SAMP ahli.
        Konteks: Karakter={info_data.get('detail_karakter', 'N/A')} (AI: {', '.join(char_names_formatted)}), Skenario={info_data.get('skenario', 'N/A')}, Bahasa={language}, Jml Gbr={len(images_bytes_list)}
        Kebutuhan Baris:\n{dialog_requirements}
        ATURAN FORMAT ({language}):
        1. Chat: `Nama_Karakter says: Teks.`
        2. Low: `Nama_Karakter [low]: Teks.`
        3. Me: `* Nama_Karakter aksi` (Tanpa titik akhir)
        4. Do: `** Deskripsi (( Nama_Karakter ))` (DUA bintang)
        5. Whisper: `Nama_Karakter whispers: Teks` / `... (phone): ...`
        6. Radio/Dept: `** [Dept] Nama_Karakter: Teks` / `** [CH:X] Nama_Karakter: Teks`
        7. Nama AI: {', '.join(char_names_formatted)}
        8. Adaptasi kata kunci format (says, *, dll) ke {language} jika bukan Indo/English. /do tetap `** ... (( Nama ))`.
        OUTPUT HANYA JSON: {{ "dialogs_per_image": [ ["dialog gbr1"], ["dialog gbr2"], ... ] }}
        INSTRUKSI: Buat dialog natural, logis, sesuai gambar#1 & skenario. Lanjutkan cerita antar gambar. Jumlah baris TEPAT. Variasikan format.
        """
        # --- End Setup Prompt ---

        dialogs_list = None
        ai_used = "Tidak ada"

        # --- Coba OpenAI ---
        if self.openai_key_cycler:
            try:
                await processing_msg.edit(content=f"🧠 {user_mention}, Mencoba OpenAI...")
                key = next(self.openai_key_cycler)
                dialogs_list = await self._generate_with_openai(key, prompt, image_content_openai)
                if dialogs_list: ai_used = "OpenAI"
            except Exception as e:
                 logger.warning(f"OpenAI error: {e}")
                 await processing_msg.edit(content=f"⚠️ {user_mention}, OpenAI gagal ({e})... Mencoba AI lain...")
                 await asyncio.sleep(1)

        # --- Coba DeepSeek (jika OpenAI gagal) ---
        if not dialogs_list and self.deepseek_key_cycler:
            try:
                await processing_msg.edit(content=f"🧠 {user_mention}, Mencoba DeepSeek (Hanya Teks)...")
                key = next(self.deepseek_key_cycler)
                dialogs_list = await self._generate_with_deepseek(key, prompt, None) # Pass None for image
                if dialogs_list: ai_used = "DeepSeek"
            except Exception as e:
                 logger.warning(f"DeepSeek error: {e}")
                 await processing_msg.edit(content=f"⚠️ {user_mention}, DeepSeek gagal... Mencoba AI lain...")
                 await asyncio.sleep(1)

        # --- Coba Gemini (jika DeepSeek gagal) ---
        if not dialogs_list and self.gemini_key_cycler:
            try:
                await processing_msg.edit(content=f"🧠 {user_mention}, Mencoba Gemini...")
                key = next(self.gemini_key_cycler)
                dialogs_list = await self._generate_with_gemini(key, prompt, image_content_openai) # Kirim gambar ke Gemini
                if dialogs_list: ai_used = "Gemini"
            except Exception as e:
                 logger.warning(f"Gemini error: {e}")
                 await processing_msg.edit(content=f"⚠️ {user_mention}, Gemini gagal...")
                 await asyncio.sleep(1)

        # --- Jika semua gagal ---
        if not dialogs_list:
            logger.error("Semua API AI gagal untuk SSRP Chatlog.")
            raise Exception("Semua layanan AI (OpenAI, DeepSeek, Gemini) gagal dihubungi atau error.")

        # Padding/Truncating
        while len(dialogs_list) < len(images_bytes_list):
            dialogs_list.append([f"[AI Error Gbr {len(dialogs_list)+1}]"])
        dialogs_list = dialogs_list[:len(images_bytes_list)]

        logger.info(f"AI ({ai_used}) generated dialogs for {len(dialogs_list)} images in '{language}'.")
        return dialogs_list, ai_used # Kembalikan AI yang berhasil digunakan


    async def add_dialogs_to_image(
        self,
        image_bytes: bytes,
        dialogs: List[str],
        position: str,
        background_style: str
    ) -> bytes:
        """Tambahkan dialog ke gambar dengan styling & word wrap"""
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
            width, height = img.size
            txt_overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(txt_overlay)
            padding = 8
            max_text_width_px = width - (padding * 2)

            wrapped_dialog_lines = []
            
            # --- Text Wrapping ---
            for dialog in dialogs:
                avg_char_width = self.font.getlength("a")
                approx_chars_per_line = int(max_text_width_px / avg_char_width) if avg_char_width > 0 else 70 

                lines = textwrap.wrap(dialog, width=max(10, approx_chars_per_line - 5), 
                                     break_long_words=True, 
                                     replace_whitespace=False,
                                     drop_whitespace=False)
                
                if not lines:
                    lines = [dialog]

                final_lines = []
                for line in lines:
                    # Cek ulang jika satu baris masih terlalu panjang
                    if self.font.getlength(line) > max_text_width_px:
                        # Potong paksa jika masih kepanjangan (jarang terjadi)
                        # Hitung ulang char per line yang lebih aman
                        safe_chars = max(10, approx_chars_per_line - 10)
                        for i in range(0, len(line), safe_chars):
                            final_lines.append(line[i:i + safe_chars])
                    else:
                        final_lines.append(line)
                
                wrapped_dialog_lines.extend(final_lines)

            # --- Hitung Tinggi & Posisi Y ---
            total_lines = len(wrapped_dialog_lines)
            line_pixel_height = self.FONT_SIZE + self.LINE_HEIGHT_ADD
            total_dialog_height_pixels = (total_lines * line_pixel_height) - self.LINE_HEIGHT_ADD + (padding * 2)

            y_coords = [] # y_start untuk top dan bottom

            # --- Gambar Background (jika overlay) & Tentukan y_coords ---
            if background_style == "overlay":
                if position == "atas":
                    bg_y_end = min(total_dialog_height_pixels, height)
                    draw.rectangle([(0, 0), (width, bg_y_end)], fill=self.BG_COLOR)
                    y_coords.append(padding)
                elif position == "bawah":
                    bg_y_start_rect = max(0, height - total_dialog_height_pixels)
                    draw.rectangle([(0, bg_y_start_rect), (width, height)], fill=self.BG_COLOR)
                    y_coords.append(bg_y_start_rect + padding)
                else: # split
                    half_lines_idx = (total_lines + 1) // 2
                    top_lines = wrapped_dialog_lines[:half_lines_idx]
                    bottom_lines = wrapped_dialog_lines[half_lines_idx:]

                    top_height_pixels = (len(top_lines) * line_pixel_height) - self.LINE_HEIGHT_ADD + (padding * 2) if top_lines else 0
                    bg_top_end = min(top_height_pixels, height)
                    draw.rectangle([(0, 0), (width, bg_top_end)], fill=self.BG_COLOR)
                    y_coords.append(padding)

                    bottom_height_pixels = (len(bottom_lines) * line_pixel_height) - self.LINE_HEIGHT_ADD + (padding * 2) if bottom_lines else 0
                    bg_bottom_start_rect = max(0, height - bottom_height_pixels)
                    draw.rectangle([(0, bg_bottom_start_rect), (width, height)], fill=self.BG_COLOR)
                    y_coords.append(bg_bottom_start_rect + padding)
            
            else: # background_style == "transparent"
                 if position == "atas": y_coords.append(padding)
                 elif position == "bawah": y_coords.append(max(padding, height - total_dialog_height_pixels + padding))
                 else: # split transparent
                     half_lines_idx = (total_lines + 1) // 2
                     y_coords.append(padding)
                     bottom_lines_count = total_lines - half_lines_idx
                     bottom_height_pixels = (bottom_lines_count * line_pixel_height) - self.LINE_HEIGHT_ADD + (padding * 2) if bottom_lines_count > 0 else 0
                     y_coords.append(max(padding, height - bottom_height_pixels + padding))

            # --- Draw Dialogs (dengan wrapping) ---
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
            else: # atas atau bawah
                y_pos = y_coords[0]
                for line in wrapped_dialog_lines:
                    self.draw_text_with_multi_shadow(draw, (padding, y_pos), line, self.font)
                    y_pos += line_pixel_height

            # Gabungkan gambar
            out_img = Image.alpha_composite(img, txt_overlay)

            # Simpan sebagai PNG
            output = io.BytesIO()
            out_img.convert("RGB").save(output, format='PNG')
            output.seek(0)
            return output.getvalue()

        except Exception as e:
            logger.error(f"Error di add_dialogs_to_image: {e}", exc_info=True)
            return image_bytes # Kembalikan asli jika gagal

    def get_text_color(self, text: str) -> tuple:
        """Tentukan warna teks berdasarkan format SSRP/Chatlog Magician"""
        original_text = text
        text_lower = text.strip().lower()

        # Urutan prioritas
        if text_lower.startswith('** [ch:'): return self.COLOR_RADIO
        if text_lower.startswith('** ['): return self.COLOR_DEP
        if text_lower.startswith('**'): return self.COLOR_DO
        if text_lower.startswith('*'): return self.COLOR_ME
        
        if ' whispers:' in text_lower: return self.COLOR_WHISPER
        if re.search(r'\(\s*phone\s*\):', text_lower): return self.COLOR_WHISPER
        if ':o<' in text: return self.COLOR_WHISPER
        
        if ' [low]:' in text_lower: return self.COLOR_LOWCHAT
        if '[san interview]' in text_lower: return self.COLOR_NEWS
        if ' says:' in text_lower: return self.COLOR_CHAT
        
        if ', $' in text or 'you have received $' in text_lower: return self.COLOR_GREY
        if '(( ' in text and ' ))' in text: return self.COLOR_OOC

        return self.COLOR_CHAT

    def draw_text_with_multi_shadow(self, draw: ImageDraw.ImageDraw, pos: Tuple[int, int], text: str, font: ImageFont.FreeTypeFont):
        """Gambar teks dengan shadow hitam di 4 arah dan penyesuaian nama"""
        x, y = pos
        text_color = self.get_text_color(text)
        cleaned_text = text
        
        # --- PERBAIKAN: Definisikan text_lower ---
        text_lower = text.strip().lower()

        # Ganti _ -> spasi untuk chat biasa (`says:` atau `[low]:`)
        match_say = re.match(r"^\s*([A-Za-z0-9_]+)\s+says:", text, re.IGNORECASE)
        match_low = re.match(r"^\s*([A-Za-z0-9_]+)\s+\[low\]:", text, re.IGNORECASE)

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

        # Ganti _ -> spasi untuk /me (format `* Nama_Pemain aksi`)
        elif text.startswith('* ') and ' (( ' not in text and ' [ch:' not in text and ' [' not in text_lower:
            parts = text.split(' ', 2)
            if len(parts) >= 3:
                name = parts[1].replace('_', ' ')
                action = parts[2]
                cleaned_text = f"* {name} {action}"
            elif len(parts) == 2:
                 name = parts[1].replace('_', ' ')
                 cleaned_text = f"* {name}"

        # Gambar shadow
        for dx, dy in self.SHADOW_OFFSETS:
            draw.text((x + dx, y + dy), cleaned_text, font=font, fill=self.COLOR_SHADOW)

        # Gambar teks utama
        draw.text(pos, cleaned_text, font=font, fill=text_color)

# Setup function
async def setup(bot):
    # Pastikan bot meneruskan config saat memuat cog
    await bot.add_cog(SSRPChatlogCog(bot))
