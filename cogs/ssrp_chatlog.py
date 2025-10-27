# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import ui
import logging
import io
import base64
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from openai import AsyncOpenAI
from typing import List, Dict, Optional, Tuple
import asyncio
import re
import os # Untuk mencari font
import json # <<< DIPERLUKAN UNTUK MEMPROSES RESPON AI >>>

logger = logging.getLogger(__name__)

# ============================
# MODAL & VIEW COMPONENTS (REVISED)
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

        # Setup OpenAI client
        if not self.bot.config.OPENAI_API_KEYS:
            logger.error("OPENAI_API_KEYS tidak dikonfigurasi untuk SSRP Chatlog")
            self.client = None
        else:
            # Gunakan key pertama jika ada
            self.client = AsyncOpenAI(api_key=self.bot.config.OPENAI_API_KEYS[0])
            logger.info("✅ OpenAI client untuk SSRP Chatlog berhasil diinisialisasi")

        # --- Pengaturan Font & Warna (Disesuaikan) ---
        self.FONT_SIZE = 14 # Ukuran font diperkecil
        self.LINE_HEIGHT = 18 # Tinggi baris disesuaikan
        self.FONT_PATH = self._find_font(["arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"]) # Cari Arial dulu
        self.COLOR_CHAT = (255, 255, 255) # Putih
        self.COLOR_ME = (194, 162, 218)   # Ungu/Pink (#C2A2DA)
        self.COLOR_DO = (153, 204, 255)   # Biru Muda (#99CCFF)
        self.COLOR_OOC = (170, 170, 170)   # Abu-abu (#AAAAAA) - Opsional jika AI generate
        self.COLOR_SHADOW = (0, 0, 0)     # Hitam untuk shadow
        self.BG_COLOR = (0, 0, 0, 128)    # Hitam semi-transparan (alpha 128/255)
        self.SHADOW_OFFSET = (1, 1)       # Shadow 1px ke kanan bawah

        # Load font
        try:
            self.font = ImageFont.truetype(self.FONT_PATH, self.FONT_SIZE)
            logger.info(f"✅ Font '{self.FONT_PATH}' berhasil dimuat untuk SSRP.")
        except IOError:
            logger.warning(f"Font SSRP ({self.FONT_PATH}) tidak ditemukan, menggunakan font default Pillow.")
            self.font = ImageFont.load_default() # Fallback

    def _find_font(self, font_names: List[str]) -> str:
        """Mencari path font yang valid dari daftar nama."""
        font_dirs = []
        if os.name == 'nt': # Windows
            font_dirs.append(os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts'))
        elif os.name == 'posix': # Linux/macOS
            font_dirs.extend(['/usr/share/fonts/truetype', '/usr/local/share/fonts', os.path.expanduser('~/.fonts')])
            # macOS specific paths might be needed if the above don't work
            font_dirs.append('/Library/Fonts')
            font_dirs.append(os.path.expanduser('~/Library/Fonts'))

        for name in font_names:
            for dir_path in font_dirs:
                font_path = os.path.join(dir_path, name)
                # Check subdirectories common in Linux
                if os.name == 'posix':
                    subdirs = ["dejavu", "msttcorefonts", "liberation", "ubuntu"]
                    for subdir in subdirs:
                         sub_path = os.path.join(dir_path, subdir, name)
                         if os.path.exists(sub_path): return sub_path

                if os.path.exists(font_path):
                    return font_path # Kembalikan path pertama yang ditemukan

        # Jika tidak ketemu, kembalikan nama pertama sebagai fallback (akan error di ImageFont.truetype tapi log warning)
        logger.warning(f"Tidak dapat menemukan font: {font_names} di direktori {font_dirs}. Akan coba default Pillow.")
        return font_names[0]

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
            # Pesan ini hanya terlihat oleh pengguna yang menekan tombol
            await interaction.edit_original_response(
                 content=f"⏳ Memulai proses untuk {len(images_bytes_list)} gambar dengan AI...",
                 view=None, embed=None, attachments=[]
            )
            # Kirim pesan publik yang akan diupdate progressnya
            processing_msg = await interaction.channel.send(f"⏳ {interaction.user.mention} sedang memproses {len(images_bytes_list)} gambar SSRP...")

        except discord.NotFound:
            # Jika pesan ephemeral tidak ditemukan (misal timeout > 15 menit), kirim pesan publik baru
            processing_msg = await interaction.channel.send(f"⏳ {interaction.user.mention} memulai proses {len(images_bytes_list)} gambar SSRP...")
        except Exception as e:
             logger.error(f"Error saat edit initial process_ssrp message: {e}")
             await interaction.channel.send(f"❌ Error memulai proses: {e}")
             return

        try:
            # 1. Generate dialog dengan AI
            await processing_msg.edit(content=f"🧠 {interaction.user.mention}, AI sedang membuat dialog...")

            # Extract language from info_data
            language = info_data.get('language', 'Bahasa Indonesia baku')

            all_dialogs_raw = await self.generate_dialogs_with_ai(
                images_bytes_list,
                info_data,
                dialog_counts,
                language # Pass language to AI
            )

            # 2. Process setiap gambar
            processed_images_bytes = []
            for idx, (img_bytes, raw_dialogs, position, bg_style) in enumerate(zip(images_bytes_list, all_dialogs_raw, positions, background_styles)):

                # Pastikan dialog tidak melebihi jumlah yang diminta untuk gambar ini
                limited_dialogs = raw_dialogs[:dialog_counts[idx]]

                await processing_msg.edit(
                    content=f"🎨 {interaction.user.mention}, memproses gambar {idx + 1}/{len(images_bytes_list)} ({len(limited_dialogs)} baris)..."
                )

                # Tambahkan dialog ke gambar
                processed_img = await self.add_dialogs_to_image(
                    img_bytes,
                    limited_dialogs,
                    position,
                    bg_style # Pass background style
                )
                processed_images_bytes.append(processed_img)

                await asyncio.sleep(0.5) # Delay kecil antar gambar

            # 3. Kirim hasil
            await processing_msg.edit(
                content=f"✅ Selesai! Hasil SSRP untuk {interaction.user.mention}:"
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
        """Generate dialog SSRP SAMP yang benar menggunakan AI"""

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
        2.  Aksi /me: `* Nama_Karakter melakukan aksi.` (Diawali bintang+spasi, nama pakai underscore, AKHIRI DENGAN TITIK)
        3.  Deskripsi /do: `** Deskripsi keadaan atau hasil aksi. (( Nama_Karakter ))` (Diawali dua bintang+spasi, nama pakai underscore di akhir dalam kurung OOC, AKHIRI DENGAN TITIK sebelum kurung)
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

    async def add_dialogs_to_image(
        self,
        image_bytes: bytes,
        dialogs: List[str],
        position: str,
        background_style: str # Parameter baru
    ) -> bytes:
        """Tambahkan dialog ke gambar DENGAN BENAR (overlay opsional, drop shadow)"""

        try:
            # Buka gambar dan pastikan format RGBA untuk overlay transparan
            img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
            width, height = img.size

            # Buat layer overlay transparan seukuran gambar asli
            txt_overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(txt_overlay)

            padding = 10 # Padding dari tepi gambar/background

            # Tentukan posisi Y dan gambar background jika 'overlay' dipilih
            y_coords = [] # Simpan y awal untuk setiap bagian (atas/bawah)

            if background_style == "overlay":
                if position == "atas":
                    dialog_height = (len(dialogs) * self.LINE_HEIGHT) + (padding * 2)
                    bg_y_end = min(dialog_height, height) # Pastikan tidak melebihi tinggi gambar
                    draw.rectangle([(0, 0), (width, bg_y_end)], fill=self.BG_COLOR)
                    y_coords.append(padding)
                elif position == "bawah":
                    dialog_height = (len(dialogs) * self.LINE_HEIGHT) + (padding * 2)
                    bg_y_start = max(0, height - dialog_height) # Pastikan tidak negatif
                    draw.rectangle([(0, bg_y_start), (width, height)], fill=self.BG_COLOR)
                    y_coords.append(bg_y_start + padding)
                else:  # split
                    half_point = (len(dialogs) + 1) // 2
                    top_dialogs = dialogs[:half_point]
                    bottom_dialogs = dialogs[half_point:]

                    # Background Atas
                    top_height = (len(top_dialogs) * self.LINE_HEIGHT) + (padding * 2)
                    bg_top_end = min(top_height, height)
                    draw.rectangle([(0, 0), (width, bg_top_end)], fill=self.BG_COLOR)
                    y_coords.append(padding)

                    # Background Bawah
                    bottom_height = (len(bottom_dialogs) * self.LINE_HEIGHT) + (padding * 2)
                    bg_bottom_start = max(0, height - bottom_height)
                    draw.rectangle([(0, bg_bottom_start), (width, height)], fill=self.BG_COLOR)
                    y_coords.append(bg_bottom_start + padding)
            else: # background_style == "transparent"
                 # Tentukan y_start tanpa menggambar background
                 if position == "atas":
                     y_coords.append(padding)
                 elif position == "bawah":
                     # Perkirakan tinggi dialog untuk menempatkan di bawah
                     dialog_height_estimate = (len(dialogs) * self.LINE_HEIGHT) + padding
                     y_start_bawah = max(padding, height - dialog_height_estimate) # Mulai dari bawah atau padding atas
                     y_coords.append(y_start_bawah)
                 else: # split (transparent)
                     half_point = (len(dialogs) + 1) // 2
                     # Y atas
                     y_coords.append(padding)
                     # Y bawah (perkirakan tinggi dialog bawah)
                     bottom_height_estimate = (len(dialogs[half_point:]) * self.LINE_HEIGHT) + padding
                     y_start_bawah_split = max(padding, height - bottom_height_estimate)
                     y_coords.append(y_start_bawah_split)

            # Draw dialogs
            if position == "split":
                half = (len(dialogs) + 1) // 2
                # Top dialogs
                y_pos_top = y_coords[0]
                for dialog in dialogs[:half]:
                    self.draw_text_with_shadow(draw, (padding, y_pos_top), dialog, self.font)
                    y_pos_top += self.LINE_HEIGHT
                # Bottom dialogs
                y_pos_bottom = y_coords[1]
                for dialog in dialogs[half:]:
                    self.draw_text_with_shadow(draw, (padding, y_pos_bottom), dialog, self.font)
                    y_pos_bottom += self.LINE_HEIGHT
            else: # atas atau bawah
                y_pos = y_coords[0]
                for dialog in dialogs:
                    self.draw_text_with_shadow(draw, (padding, y_pos), dialog, self.font)
                    y_pos += self.LINE_HEIGHT

            # Gabungkan gambar asli dengan overlay teks
            # Ini menempelkan txt_overlay (yang berisi teks dan mungkin background) di atas img asli
            out_img = Image.alpha_composite(img, txt_overlay)

            # Convert kembali ke bytes (simpan sebagai JPEG)
            output = io.BytesIO()
            # Convert ke RGB sebelum save JPEG, kualitas 90
            out_img.convert("RGB").save(output, format='JPEG', quality=90)
            output.seek(0)
            return output.getvalue()

        except Exception as e:
            logger.error(f"Error di add_dialogs_to_image: {e}", exc_info=True)
            # Kembalikan gambar asli jika error
            return image_bytes

    def get_text_color(self, text: str) -> tuple:
        """Tentukan warna teks berdasarkan format SSRP"""
        text = text.strip()
        if text.startswith('**'): return self.COLOR_DO # Cek /do dulu karena diawali '*' juga
        if text.startswith('*'): return self.COLOR_ME
        if text.startswith('(('): return self.COLOR_OOC # Opsional
        # Default chat color
        return self.COLOR_CHAT

    def draw_text_with_shadow(self, draw: ImageDraw.ImageDraw, pos: Tuple[int, int], text: str, font: ImageFont.FreeTypeFont):
        """Gambar teks dengan drop shadow 1px"""
        x, y = pos
        shadow_pos = (x + self.SHADOW_OFFSET[0], y + self.SHADOW_OFFSET[1])
        text_color = self.get_text_color(text)

        cleaned_text = text # Teks yang akan digambar

        # Ganti underscore di nama karakter menjadi spasi HANYA untuk tampilan chat biasa
        # Contoh: John_Doe: -> John Doe:
        # TIDAK berlaku untuk /me atau /do
        if ':' in text and not text.startswith('*'):
            parts = text.split(':', 1)
            name = parts[0].replace('_', ' ')
            dialog = parts[1]
            cleaned_text = f"{name}:{dialog}"
            # Jika ingin warna nama berbeda, bisa di-split dan draw terpisah di sini

        # 1. Gambar bayangan
        draw.text(shadow_pos, cleaned_text, font=font, fill=self.COLOR_SHADOW)
        # 2. Gambar teks utama
        draw.text(pos, cleaned_text, font=font, fill=text_color)


async def setup(bot):
    await bot.add_cog(SSRPChatlogCog(bot))
