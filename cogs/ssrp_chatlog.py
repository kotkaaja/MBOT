# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import ui
import logging
import io
import base64
from PIL import Image, ImageDraw, ImageFilter # Pillow HANYA untuk composite
from openai import AsyncOpenAI
from typing import List, Dict, Optional, Tuple
import asyncio
import re
import os
import json
import time

# --- IMPORT BARU UNTUK PEROMBAKAN TOTAL ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

logger = logging.getLogger(__name__)

# --- PENGATURAN DRIVER BROWSER ---
try:
    # Menginstal/Manage ChromeDriver secara otomatis
    DRIVER_SERVICE = Service(ChromeDriverManager().install())
    DRIVER_OPTIONS = Options()
    DRIVER_OPTIONS.add_argument("--headless") # Wajib, berjalan di background
    DRIVER_OPTIONS.add_argument("--no-sandbox")
    DRIVER_OPTIONS.add_argument("--disable-dev-shm-usage")
    # Atur ukuran window yang konsisten. Penting untuk word-wrapping!
    # Kita set lebar 900px, cukup untuk chatlog (width: 850px) + padding
    DRIVER_OPTIONS.add_argument("--window-size=900,1000") 
    DRIVER_OPTIONS.add_argument("--force-device-scale-factor=1") # Paksa skala 1:1
    DRIVER_OPTIONS.add_argument("--high-dpi-support=1")
    DRIVER_OPTIONS.add_argument("--log-level=3") # Kurangi log spam dari selenium
    
    # CSS TEPAT SEPERTI CHATLOG-MAGICIAN (app.css) + STYLE SAMP
    # Ini adalah "logika" yang Anda minta, diekstrak ke string HTML.
    SAMP_CHATLOG_HTML_TEMPLATE = """
    <html>
    <head>
        <style>
            body {{
                background-color: transparent; /* Transparan total */
                margin: 0;
                padding: 0;
            }}

            /* Ini diekstrak dari app.css .output (LOGIKA FONT UTAMA) */
            #chatlog-container {{
                /* Ukuran container, sesuaikan jika perlu */
                width: 850px; 
                padding: 5px; /* Padding kecil agar shadow tidak terpotong */
                
                /* INI ADALAH FONT SAMP DARI CHATLOG-MAGICIAN */
                font-family: Arial, sans-serif;
                line-height: 0; /* Penting untuk rendering SAMP */
                -webkit-font-smoothing: none !important; /* WAJIB */
                font-weight: 700; /* WAJIB */
                text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000; /* WAJIB */
                letter-spacing: 0; /* WAJIB */
                font-size: 12px; /* WAJIB */
                
                /* Lainnya */
                overflow-wrap: break-word;
                word-wrap: break-word;
            }}

            .chat-line {{
                /* Beri jarak antar baris secara manual, karena line-height: 0 */
                margin-bottom: 12px; 
            }}

            /* Ini adalah warna dari LOGIKA LAMA (Pillow) Anda, sekarang di CSS */
            .chat-line.chat {{
                color: {color_chat}; /* #FFFFFF */
            }}
            .chat-line.me {{
                color: {color_me}; /* #C2A2DA */
            }}
            .chat-line.do {{
                color: {color_do}; /* #99CCFF */
            }}
            .chat-line.ooc {{
                color: {color_ooc}; /* #AAAAAA */
            }}
        </style>
    </head>
    <body>
        <div id="chatlog-container">
            {dialog_lines_html}
        </div>
    </body>
    </html>
    """

except Exception as e:
    logger.critical(f"GAGAL MENGINSTALL/SETUP SELENIUM/CHROMEDRIVER: {e}")
    logger.critical("Fitur SSRP tidak akan berfungsi sampai error ini diperbaiki.")
    DRIVER_SERVICE = None


# ============================
# MODAL & VIEW COMPONENTS (TIDAK BERUBAH)
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

    # BARU: Input Bahasa
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
        # Tidak perlu dialog_counts & positions di sini lagi

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Simpan data dari modal pertama
        self.data = {
            'jumlah_pemain': self.jumlah_pemain.value,
            'detail_karakter': self.detail_karakter.value,
            'skenario': self.skenario.value,
            'language': self.language.value # Simpan bahasa
        }

        # Lanjut ke input dialog settings
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
        # Kirim pesan awal untuk gambar pertama
        embed.set_image(url=f"attachment://image_preview_0.png") # Placeholder
        file = discord.File(io.BytesIO(self.images[0]), filename="image_preview_0.png")

        await interaction.followup.send(embed=embed, view=view, file=file, ephemeral=True)


class DialogSettingsView(ui.View):
    """View untuk mengatur dialog count, posisi, dan background per gambar"""

    def __init__(self, cog_instance, images: List[bytes], info_data: Dict):
        super().__init__(timeout=300)
        self.cog = cog_instance
        self.images = images
        self.info_data = info_data
        self.dialog_counts = [5] * len(images)  # Default 5 baris
        self.positions = ["bawah"] * len(images)  # Default posisi bawah
        self.background_styles = ["overlay"] * len(images) # BARU: Default overlay
        self.current_image_index = 0

        self.update_ui()

    def update_ui(self):
        """Update tombol dan select berdasarkan gambar saat ini"""
        self.clear_items()

        # Select jumlah baris
        self.add_item(DialogCountSelect(self, self.dialog_counts[self.current_image_index]))

        # Select posisi
        self.add_item(PositionSelect(self, self.positions[self.current_image_index]))

        # BARU: Select background style
        self.add_item(BackgroundStyleSelect(self, self.background_styles[self.current_image_index]))

        # Tombol Navigasi
        row_nav = 3 # Pindahkan ke baris bawah agar tidak terlalu ramai
        if self.current_image_index > 0:
            self.add_item(PrevImageButton(self, row=row_nav))

        if self.current_image_index < len(self.images) - 1:
            self.add_item(NextImageButton(self, row=row_nav))
        else:
            # Hanya tombol Finish di gambar terakhir
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

        # Update preview gambar
        file = discord.File(io.BytesIO(self.images[idx]), filename=f"image_preview_{idx}.png")
        embed.set_image(url=f"attachment://image_preview_{idx}.png")

        # Edit pesan
        await interaction.response.edit_message(embed=embed, view=self, attachments=[file])


class DialogCountSelect(ui.Select):
    """Select untuk jumlah dialog"""
    def __init__(self, parent_view: DialogSettingsView, current_value: int):
        options = [discord.SelectOption(label=f"{i} baris", value=str(i), default=(i == current_value)) for i in range(1, 8)]
        super().__init__(placeholder="Pilih jumlah baris (1-7)", options=options, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.dialog_counts[self.parent_view.current_image_index] = int(self.values[0])
        # Perbarui nilai default di select
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
        # Perbarui nilai default di select
        for option in self.options: option.default = (option.value == self.values[0])
        await self.parent_view.update_message(interaction)

# BARU: Select untuk Gaya Background
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
        # Perbarui nilai default
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
            self.parent_view.update_ui() # Rebuild UI dengan state baru
            await self.parent_view.update_message(interaction) # Update message content


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
        # Disable view & show loading
        for item in self.view.children: item.disabled = True
        # Ganti pesan menjadi loading, hapus embed dan attachment
        await interaction.response.edit_message(content="⏳ Memulai proses...", view=self.view, embed=None, attachments=[])

        # Mulai proses generate dialog
        await self.parent_view.cog.process_ssrp(
            interaction,
            self.parent_view.images,
            self.parent_view.info_data,
            self.parent_view.dialog_counts,
            self.parent_view.positions,
            self.parent_view.background_styles # Kirim data background styles
        )


# ============================
# COG UTAMA (REVISED)
# ============================

class SSRPChatlogCog(commands.Cog, name="SSRPChatlog"):
    """Cog untuk membuat SSRP Chatlog dengan AI"""

    def __init__(self, bot):
        self.bot = bot
        self.driver = None # Placeholder untuk driver

        # Setup OpenAI client
        if not self.bot.config.OPENAI_API_KEYS:
            logger.error("OPENAI_API_KEYS tidak dikonfigurasi untuk SSRP Chatlog")
            self.client = None
        else:
            # Gunakan key pertama jika ada
            self.client = AsyncOpenAI(api_key=self.bot.config.OPENAI_API_KEYS[0])
            logger.info("✅ OpenAI client untuk SSRP Chatlog berhasil diinisialisasi")

        # --- Pengaturan Warna (diambil dari logika Pillow Anda sebelumnya) ---
        # Ini akan di-inject ke dalam CSS
        self.COLOR_CHAT = "#FFFFFF" # Putih
        self.COLOR_ME = "#C2A2DA"   # Ungu/Pink
        self.COLOR_DO = "#99CCFF"   # Biru Muda
        self.COLOR_OOC = "#AAAAAA"  # Abu-abu
        self.BG_COLOR = (0, 0, 0, 128) # Pillow-style tuple (R,G,B,A)

        # Inisialisasi WebDriver
        if DRIVER_SERVICE:
            try:
                logger.info("Menginisialisasi Headless Chrome Driver...")
                self.driver = webdriver.Chrome(service=DRIVER_SERVICE, options=DRIVER_OPTIONS)
                logger.info("✅ Headless Chrome Driver berhasil diinisialisasi.")
            except Exception as e:
                logger.critical(f"GAGAL MENGINISIALISASI DRIVER CHROME: {e}")
        else:
            logger.critical("Driver Service tidak tersedia. SSRP Cog tidak akan berfungsi.")
            
    def cog_unload(self):
        # Mematikan driver saat cog dimatikan
        if self.driver:
            logger.info("Mematikan Headless Chrome Driver...")
            self.driver.quit()

    @commands.command(name="buatssrp", aliases=["createssrp"])
    async def create_ssrp(self, ctx: commands.Context):
        """
        Buat SSRP Chatlog dari gambar-gambar dengan AI (format SAMP)

        Cara pakai:
        1. Kirim command !buatssrp sambil upload 1-10 gambar (.png/.jpg)
        2. Klik tombol untuk isi informasi SSRP
        3. Atur jumlah baris, posisi, dan background untuk tiap gambar
        4. Klik 'Proses' dan tunggu hasilnya
        """

        if not self.client:
            await ctx.send("❌ Fitur SSRP Chatlog tidak tersedia (API Key belum dikonfigurasi)")
            return
            
        if not self.driver:
            await ctx.send("❌ Fitur SSRP Chatlog mengalami error (Headless Browser gagal dimuat). Harap cek log bot.")
            return

        # Cek lampiran
        if not ctx.message.attachments:
            embed = discord.Embed(
                title="📸 Cara Menggunakan `!buatssrp`",
                description="Lampirkan **1-10 gambar** (.png/.jpg) saat mengirim command.",
                color=discord.Color.blue()
            )
            embed.add_field(name="Langkah", value="1. Upload gambar\n2. Ketik `!buatssrp` di caption\n3. Ikuti instruksi di tombol & form", inline=False)
            await ctx.send(embed=embed)
            return

        # Filter & download gambar
        images_bytes_list = []
        valid_extensions = ('.png', '.jpg', '.jpeg')
        for attachment in ctx.message.attachments:
            if attachment.filename.lower().endswith(valid_extensions):
                if attachment.size > 8 * 1024 * 1024: # Limit 8MB per gambar
                    await ctx.send(f"⚠️ Gambar `{attachment.filename}` terlalu besar (>8MB), dilewati.")
                    continue
                try:
                    img_bytes = await attachment.read()
                    images_bytes_list.append(img_bytes)
                except Exception as e:
                    logger.error(f"Gagal download gambar '{attachment.filename}': {e}")
                    await ctx.send(f"❌ Gagal mengunduh `{attachment.filename}`.")
            if len(images_bytes_list) >= 10: break # Batasi maks 10 gambar

        if not images_bytes_list:
            await ctx.send("❌ Tidak ada gambar valid (.png/.jpg) yang ditemukan atau berhasil diunduh!")
            return

        # Tampilkan modal via tombol
        modal = SSRPInfoModal(self, images_bytes_list)
        view = ui.View(timeout=180) # Timeout 3 menit untuk klik tombol
        button = ui.Button(label=f"📝 Isi Informasi SSRP ({len(images_bytes_list)} gambar)", style=discord.ButtonStyle.primary)

        async def button_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Hanya peminta asli yang bisa mengisi!", ephemeral=True); return
            await interaction.response.send_modal(modal)
            # Disable tombol setelah diklik
            button.disabled = True
            await interaction.message.edit(view=view)

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
        background_styles: List[str] # Terima data background styles
    ):
        """Proses generate dialog dan overlay ke gambar"""

        # Variabel untuk menyimpan pesan yang akan diedit
        processing_msg = None

        try:
            # Edit pesan ephemeral yang dikirim dari FinishButton callback
            await interaction.edit_original_response(
                 content=f"⏳ Memulai proses untuk {len(images_bytes_list)} gambar dengan AI...",
                 view=None, embed=None, attachments=[]
            )
            # Kirim pesan publik yang akan diupdate progressnya
            processing_msg = await interaction.channel.send(f"⏳ {interaction.user.mention} sedang memproses {len(images_bytes_list)} gambar SSRP...")

        except discord.NotFound:
            processing_msg = await interaction.channel.send(f"⏳ {interaction.user.mention} memulai proses {len(images_bytes_list)} gambar SSRP...")
        except Exception as e:
             logger.error(f"Error saat edit initial process_ssrp message: {e}")
             await interaction.channel.send(f"❌ Error memulai proses: {e}")
             return

        try:
            start_total_time = time.time()
            
            # 1. Generate dialog dengan AI (Tidak berubah)
            await processing_msg.edit(content=f"🧠 {interaction.user.mention}, AI sedang membuat dialog...")
            language = info_data.get('language', 'Bahasa Indonesia baku')

            all_dialogs_raw = await self.generate_dialogs_with_ai(
                images_bytes_list,
                info_data,
                dialog_counts,
                language
            )

            # 2. Process setiap gambar (INI YANG DIROMBAK)
            processed_images_bytes = []
            loop = self.bot.loop

            for idx, (img_bytes, raw_dialogs, position, bg_style) in enumerate(zip(images_bytes_list, all_dialogs_raw, positions, background_styles)):

                limited_dialogs = raw_dialogs[:dialog_counts[idx]]

                await processing_msg.edit(
                    content=f"🎨 {interaction.user.mention}, merender gambar {idx + 1}/{len(images_bytes_list)} ({len(limited_dialogs)} baris)..."
                )
                
                start_render_time = time.time()

                # --- LOGIKA PEROMBAKAN TOTAL ---
                
                # 2a. Buat HTML dari dialogs (Blocking, run di executor)
                #    Fungsi ini (generate_samp_html) adalah FUNGSI BARU
                generated_html = await loop.run_in_executor(
                    None, self.generate_samp_html, limited_dialogs
                )

                # 2b. Screenshot HTML menggunakan Selenium (Blocking, run di executor)
                #    Fungsi ini (screenshot_html_with_selenium) adalah FUNGSI BARU
                chatlog_screenshot_bytes = await loop.run_in_executor(
                    None, self.screenshot_html_with_selenium, generated_html
                )
                
                if not chatlog_screenshot_bytes:
                    logger.error(f"Gagal screenshot HTML untuk gambar {idx+1}")
                    raise Exception(f"Gagal screenshot HTML (gambar {idx+1})")

                # 2c. Composite gambar (Blocking, run di executor)
                #    Fungsi ini (composite_image) adalah FUNGSI BARU
                processed_img = await loop.run_in_executor(
                    None, self.composite_image,
                    img_bytes,
                    chatlog_screenshot_bytes,
                    position,
                    bg_style
                )
                
                # --- AKHIR LOGIKA PEROMBAKAN ---
                
                processed_images_bytes.append(processed_img)
                logger.info(f"Gambar {idx+1} selesai dirender dalam {time.time() - start_render_time:.2f} detik.")
                await asyncio.sleep(0.1) # Bernapas sejenak

            # 3. Kirim hasil
            end_total_time = time.time()
            await processing_msg.edit(
                content=f"✅ Selesai! {len(processed_images_bytes)} SSRP untuk {interaction.user.mention} dibuat dalam {end_total_time - start_total_time:.2f} detik."
            )

            # Kirim gambar dalam chunk (max 10 per pesan Discord)
            for i in range(0, len(processed_images_bytes), 10):
                chunk = processed_images_bytes[i:i+10]
                files = [
                    discord.File(io.BytesIO(img_data), filename=f"ssrp_{i+j+1}.jpg") # Simpan sebagai JPG
                    for j, img_data in enumerate(chunk)
                ]

                embed_result = discord.Embed(
                    title=f"📸 Hasil SSRP Chatlog (Gambar {i+1}-{i+len(chunk)})",
                    color=discord.Color.green()
                )
                skenario = info_data.get('skenario', 'N/A')
                embed_result.add_field(
                    name="Skenario",
                    value=skenario[:1000] + "..." if len(skenario) > 1000 else skenario, # Batas field value
                    inline=False
                )

                # Kirim sebagai pesan baru di channel
                await interaction.channel.send(embed=embed_result, files=files)

        except Exception as e:
            logger.error(f"Error saat proses SSRP: {e}", exc_info=True)
            error_message = f"❌ Terjadi kesalahan: {str(e)[:1500]}" # Batasi panjang pesan error
            if processing_msg:
                await processing_msg.edit(content=f"{interaction.user.mention}, {error_message}")
            else: # Jika pesan progress tidak terdefinisi
                 await interaction.channel.send(content=f"{interaction.user.mention}, {error_message}")

    async def generate_dialogs_with_ai(
        self,
        images_bytes_list: List[bytes],
        info_data: Dict,
        dialog_counts: List[int],
        language: str # Parameter bahasa baru
    ) -> List[List[str]]:
        """Generate dialog SSRP SAMP yang benar menggunakan AI (TIDAK BERUBAH)"""

        # Kirim hanya gambar pertama sebagai konteks visual
        base64_img = base64.b64encode(images_bytes_list[0]).decode('utf-8')
        image_content = {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"} # Asumsikan bisa JPG/PNG
        }

        # Kebutuhan dialog per gambar
        dialog_requirements = "\n".join([
            f"Gambar {i+1}: HARUS berisi TEPAT {count} baris dialog."
            for i, count in enumerate(dialog_counts)
        ])

        # Ekstrak nama karakter (ambil kata pertama sebelum spasi atau akhir string)
        char_details = info_data.get('detail_karakter', '')
        # Coba regex dulu untuk First_Last atau First Last
        char_names_raw = re.findall(r"([A-Za-z'_]+(?: [A-Za-z'_]+)?)", char_details)
        if not char_names_raw: # Fallback jika format tidak First Last
             char_names_raw = [line.split('(')[0].strip() for line in char_details.split('\n') if line.strip()]
             # Bersihkan nama fallback dari karakter non-alfanumerik kecuali spasi
             char_names_raw = [re.sub(r"[^A-Za-z\s]+", "", name).strip() for name in char_names_raw if name]


        # Ganti spasi -> underscore untuk AI
        char_names_formatted = [name.replace(' ', '_') for name in char_names_raw if name] # Pastikan tidak kosong

        # --- PROMPT DIPERBARUI ---
        prompt = f"""
        Anda adalah penulis dialog SSRP (Screenshot Roleplay) server SAMP (San Andreas Multiplayer) yang sangat ahli.

        INFORMASI KONTEKS:
        - Karakter Terlibat: {info_data.get('detail_karakter', 'Tidak ada info')} (Nama untuk AI: {', '.join(char_names_formatted)})
        - Skenario: {info_data.get('skenario', 'Tidak ada skenario')}
        - Bahasa/Aksen: {language}
        - Jumlah Gambar: {len(images_bytes_list)} (Anda hanya melihat gambar #1)

        KEBUTUHAN DIALOG PER GAMBAR:
        {dialog_requirements}

        ATURAN FORMAT SANGAT PENTING (Gunakan Bahasa: {language}):
        1.  Obrolan Normal (IC): `Nama_Karakter: Dialognya disini.` (Gunakan underscore di nama, AKHIRI DENGAN TITIK)
        2.  Aksi /me: `*Nama_Karakter melakukan aksi.` (Diawali bintang+spasi, nama pakai underscore, AKHIRI DENGAN TITIK)
        3.  Deskripsi /do: `*Deskripsi keadaan atau hasil aksi. (( Nama_Karakter ))` (Diawali dua bintang+spasi, nama pakai underscore di akhir dalam kurung OOC, AKHIRI DENGAN TITIK sebelum kurung)
        4.  Gunakan nama karakter PERSIS seperti ini: {', '.join(char_names_formatted)}

        FORMAT OUTPUT JSON (WAJIB HANYA JSON):
        {{
          "dialogs_per_image": [
            [ // Gambar 1
              "Baris dialog 1 (format /me, /do, atau chat)",
              "Baris dialog 2",
              ... (sesuai jumlah diminta)
            ],
            [ // Gambar 2
              "Baris dialog 1",
              ...
            ],
            ... // dst
          ]
        }}

        INSTRUKSI TAMBAHAN:
        - Buat dialog yang natural, logis, sesuai skenario dan visual (gambar #1).
        - Lanjutkan alur cerita antar gambar.
        - PASTIKAN JUMLAH BARIS TEPAT sesuai permintaan per gambar.
        - JANGAN tambahkan timestamp atau format lain.
        - JANGAN gunakan OOC lie di /do. /do mendeskripsikan fakta.
        - JANGAN gunakan /do untuk bertanya 'bisa?'.
        """

        # Call OpenAI API (Gunakan model yang support JSON mode & Vision)
        response_content = "" # Inisialisasi
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini", # Model ini support vision dan JSON mode
                messages=[
                    {"role": "system", "content": "Anda adalah penulis dialog SSRP SAMP ahli. Output HANYA JSON."},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        image_content # Kirim gambar pertama
                    ]}
                ],
                response_format={"type": "json_object"}, # Minta output JSON
                max_tokens=2500, # Tingkatkan token jika perlu
                temperature=0.7
            )

            response_content = response.choices[0].message.content
            # Coba parse JSON
            parsed_data = json.loads(response_content) # <-- Baris yang mungkin error
            dialogs_list = parsed_data.get("dialogs_per_image", [])

            # Validasi dasar struktur
            if not isinstance(dialogs_list, list) or not all(isinstance(img_dialogs, list) for img_dialogs in dialogs_list):
                 raise ValueError("Format JSON dari AI tidak sesuai struktur yang diharapkan.")

        except json.JSONDecodeError as json_err: # Tangkap error spesifik
             logger.error(f"Gagal parse JSON dari AI: {json_err}\nResponse mentah:\n{response_content[:500]}...")
             raise Exception(f"AI mengembalikan format JSON yang tidak valid. Error: {json_err}")
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}", exc_info=True)
            # Anda bisa menambahkan fallback ke model lain atau analisis manual di sini jika diperlukan
            raise Exception(f"Gagal menghubungi AI atau memproses respons: {e}")

        # Pastikan jumlah array dialog sesuai jumlah gambar (tambahkan array kosong jika kurang)
        while len(dialogs_list) < len(images_bytes_list):
            dialogs_list.append([f"[AI Gagal Generate Dialog untuk Gambar {len(dialogs_list)+1}]"])

        # Potong jika AI menghasilkan lebih banyak array gambar dari yang diminta
        dialogs_list = dialogs_list[:len(images_bytes_list)]

        logger.info(f"AI generated dialogs for {len(dialogs_list)} images.")
        return dialogs_list

    # ==========================================================
    # --- FUNGSI RENDERING BARU (PENGGANTI FUNGSI PILLOW) ---
    # ==========================================================

    def generate_samp_html(self, dialogs: List[str]) -> str:
        """
        FUNGSI BARU: Mengubah list dialog AI menjadi HTML dengan CSS yang tepat.
        Ini adalah inti dari logika parser "chatlog-magician" yang Anda inginkan.
        """
        
        dialog_lines_html = []
        
        for text in dialogs:
            text = text.strip()
            if not text:
                continue

            css_class = ""
            
            # Tentukan warna (logika dari get_text_color lama Anda)
            if text.startswith('**'):
                css_class = "do"
            elif text.startswith('*'):
                css_class = "me"
            elif text.startswith('(('):
                 css_class = "ooc"
            else:
                css_class = "chat"

            # Bersihkan nama (logika dari draw_text_with_shadow lama Anda)
            cleaned_text = text
            if ':' in text and not text.startswith('*'):
                try:
                    parts = text.split(':', 1)
                    name = parts[0].replace('_', ' ')
                    dialog = parts[1]
                    cleaned_text = f"{name}:{dialog}"
                except Exception:
                    pass # Biarkan teks apa adanya jika split gagal
            
            # Ganti karakter HTML spesial agar tidak merusak render
            cleaned_text = cleaned_text.replace("<", "&lt;").replace(">", "&gt;")

            # Buat tag HTML
            dialog_lines_html.append(f'<div class="chat-line {css_class}">{cleaned_text}</div>')

        # Gabungkan semua baris dialog
        final_dialog_html = "\n".join(dialog_lines_html)
        
        # Masukkan ke template utama
        full_html = SAMP_CHATLOG_HTML_TEMPLATE.format(
            color_chat=self.COLOR_CHAT,
            color_me=self.COLOR_ME,
            color_do=self.COLOR_DO,
            color_ooc=self.COLOR_OOC,
            dialog_lines_html=final_dialog_html
        )
        
        return full_html

    def screenshot_html_with_selenium(self, html_content: str) -> Optional[bytes]:
        """
        FUNGSI BARU: Me-render HTML di headless browser dan mengambil screenshot.
        Ini adalah inti dari logika rendering "chatlog-magician".
        """
        if not self.driver:
            logger.error("Driver Selenium tidak aktif, screenshot dibatalkan.")
            return None
            
        try:
            # Muat HTML string ke browser
            self.driver.get(f"data:text/html;charset=utf-8,{html_content}")
            
            # Tunggu hingga elemen #chatlog-container ada dan terlihat
            wait = WebDriverWait(self.driver, 5) # Tunggu maks 5 detik
            container = wait.until(
                EC.visibility_of_element_located((By.ID, "chatlog-container"))
            )
            
            # Ambil screenshot HANYA dari elemen container
            # Ini akan menghasilkan gambar PNG transparan
            screenshot_bytes = container.screenshot_as_png
            
            return screenshot_bytes
            
        except Exception as e:
            logger.error(f"Error saat screenshot Selenium: {e}", exc_info=True)
            return None

    def composite_image(
        self,
        image_bytes: bytes,
        overlay_bytes: bytes,
        position: str,
        background_style: str
    ) -> bytes:
        """
        FUNGSI BARU (Revisi): Menggabungkan gambar (Pillow) dengan screenshot (Selenium).
        """
        try:
            # Buka gambar utama
            base_img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
            width, height = base_img.size

            # Buka screenshot chatlog
            overlay_img = Image.open(io.BytesIO(overlay_bytes)).convert("RGBA")
            overlay_width, overlay_height = overlay_img.size

            # Buat canvas final
            final_img = Image.new("RGBA", base_img.size)
            final_img.paste(base_img, (0, 0)) # Tempel gambar asli
            
            # Layer untuk background (jika perlu)
            bg_layer = Image.new('RGBA', base_img.size, (255, 255, 255, 0))
            bg_draw = ImageDraw.Draw(bg_layer)

            # --- Logika Penempatan ---
            padding = 10 # Padding dari tepi
            
            # Tentukan area untuk background dan posisi Y untuk teks
            pos_y_list = [] # (y_coord)
            bg_rect_list = [] # [(x1, y1, x2, y2)]
            
            if position == "atas":
                bg_rect_list.append((0, 0, width, overlay_height + (padding * 2)))
                pos_y_list.append(padding)
            elif position == "bawah":
                bg_rect_list.append((0, height - overlay_height - (padding * 2), width, height))
                pos_y_list.append(height - overlay_height - padding)
            else: # split
                # Hitung dialog split (asumsi screenshot dibagi 2)
                # Ini tidak sempurna, tapi perkiraan terbaik tanpa info dialog
                half_height = overlay_height // 2
                
                # Area Atas
                bg_rect_list.append((0, 0, width, half_height + (padding * 2)))
                pos_y_list.append(padding)
                
                # Area Bawah
                bg_rect_list.append((0, height - half_height - (padding * 2), width, height))
                pos_y_list.append(height - half_height - padding)

            # 1. Gambar Background jika 'overlay'
            if background_style == "overlay":
                for rect in bg_rect_list:
                    bg_draw.rectangle(rect, fill=self.BG_COLOR)
                # Gabungkan background dulu
                final_img = Image.alpha_composite(final_img, bg_layer)

            # 2. Tempel Screenshot Teks
            if position == "split":
                # Potong gambar screenshot menjadi 2
                half_point = overlay_height // 2
                top_overlay = overlay_img.crop((0, 0, overlay_width, half_point))
                bottom_overlay = overlay_img.crop((0, half_point, overlay_width, overlay_height))
                
                # Tempel Atas
                final_img.paste(top_overlay, (padding, pos_y_list[0]), top_overlay)
                # Tempel Bawah
                final_img.paste(bottom_overlay, (padding, pos_y_list[1]), bottom_overlay)
            else:
                # Tempel penuh (atas atau bawah)
                final_img.paste(overlay_img, (padding, pos_y_list[0]), overlay_img)

            # Simpan hasil akhir sebagai JPEG
            output = io.BytesIO()
            final_img.convert("RGB").save(output, format='JPEG', quality=95) # Kualitas 95
            output.seek(0)
            return output.getvalue()

        except Exception as e:
            logger.error(f"Error di composite_image: {e}", exc_info=True)
            # Kembalikan gambar asli jika error
            return image_bytes

async def setup(bot):
    await bot.add_cog(SSRPChatlogCog(bot))
