# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import ui
import logging
import io
import base64
from PIL import Image, ImageDraw, ImageFont
from openai import AsyncOpenAI
from typing import List, Dict, Optional, Tuple
import asyncio
import re
import os
import json

logger = logging.getLogger(__name__)

# ============================
# MODAL & VIEW COMPONENTS (REVISED WITH BACKGROUND STYLE)
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

        file = discord.File(io.BytesIO(self.images[0]), filename="image_preview_0.png")
        embed.set_image(url=f"attachment://image_preview_0.png")

        await interaction.followup.send(embed=embed, view=view, file=file, ephemeral=True)


class DialogSettingsView(ui.View):
    """View untuk mengatur dialog count, posisi, dan background per gambar"""

    def __init__(self, cog_instance, images: List[bytes], info_data: Dict):
        super().__init__(timeout=300)
        self.cog = cog_instance
        self.images = images
        self.info_data = info_data
        self.dialog_counts = [5] * len(images)
        self.positions = ["bawah"] * len(images)
        self.background_styles = ["overlay"] * len(images) # Default overlay
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

        file = discord.File(io.BytesIO(self.images[idx]), filename=f"image_preview_{idx}.png")
        embed.set_image(url=f"attachment://image_preview_{idx}.png")

        await interaction.response.edit_message(embed=embed, view=self, attachments=[file])


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
# COG UTAMA (REVISED WITH CHATLOG MAGICIAN STYLE)
# ============================

class SSRPChatlogCog(commands.Cog, name="SSRPChatlog"):
    """Cog untuk membuat SSRP Chatlog dengan AI - Styling seperti Chatlog Magician"""

    def __init__(self, bot):
        self.bot = bot

        if not self.bot.config.OPENAI_API_KEYS:
            logger.error("OPENAI_API_KEYS tidak dikonfigurasi untuk SSRP Chatlog")
            self.client = None
        else:
            self.client = AsyncOpenAI(api_key=self.bot.config.OPENAI_API_KEYS[0])
            logger.info("✅ OpenAI client untuk SSRP Chatlog berhasil diinisialisasi")

        # ===== STYLING SETTINGS (DISESUAIKAN DENGAN CHATLOG MAGICIAN) =====
        self.FONT_SIZE = 12 # Sesuai CSS
        self.LINE_HEIGHT_ADD = 4 # Spasi tambahan antar baris (total tinggi baris = FONT_SIZE + LINE_HEIGHT_ADD)
        self.FONT_PATH = self._find_font(["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]) # Prioritaskan Arial

        # Warna teks (sesuai CSS Chatlog Magician)
        self.COLOR_CHAT = (255, 255, 255)       # .white
        self.COLOR_ME = (194, 162, 218)         # .me (#C2A2DA)
        self.COLOR_DO = (153, 204, 255)         # Biru muda (#99CCFF) - Tambahan untuk /do
        self.COLOR_WHISPER = (255, 255, 1)      # .whisper (#FFFF01)
        self.COLOR_LOWCHAT = (187, 187, 187)    # [low]: uses .grey (#BBBBBB)
        self.COLOR_DEATH = (255, 0, 0)          # .death (#FF0000)
        self.COLOR_YELLOW = (255, 255, 0)       # .yellow (#FFFF00)
        self.COLOR_PALEYELLOW = (255, 236, 139) # .paleyellow / .radio (#FFEC8B)
        self.COLOR_GREY = (187, 187, 187)       # .grey (#BBBBBB)
        self.COLOR_GREEN = (51, 170, 51)        # .green (#3A3)
        self.COLOR_MONEY = (0, 128, 0)          # .money (#008000)
        self.COLOR_NEWS = (16, 244, 65)         # .news (#10F441)
        self.COLOR_RADIO = self.COLOR_PALEYELLOW # .radio sama dengan paleyellow
        self.COLOR_DEP = (251, 132, 131)        # .dep (#FB8483)
        self.COLOR_OOC = (170, 170, 170)        # Abu-abu (#AAAAAA) - Untuk (( OOC ))

        # Text shadow settings (4 arah)
        self.COLOR_SHADOW = (0, 0, 0)
        self.SHADOW_OFFSETS = [(-1, -1), (1, -1), (-1, 1), (1, 1)]

        # Background overlay
        self.BG_COLOR = (0, 0, 0, 180) # Hitam semi-transparan (alpha 180/255)

        try:
            self.font = ImageFont.truetype(self.FONT_PATH, self.FONT_SIZE)
            logger.info(f"✅ Font '{os.path.basename(self.FONT_PATH)}' ({self.FONT_SIZE}pt) dimuat untuk SSRP.")
        except IOError:
            logger.warning(f"Font SSRP ({self.FONT_PATH}) tidak ditemukan, pakai default.")
            try:
                # Coba fallback ke font default yang lebih baik jika arial tidak ada
                self.font = ImageFont.truetype("DejaVuSans.ttf", self.FONT_SIZE)
                logger.info("✅ Fallback ke DejaVuSans.")
            except IOError:
                self.font = ImageFont.load_default() # Fallback terakhir
                logger.warning("⚠️ Gagal load DejaVuSans, pakai font default Pillow.")
        except Exception as e:
            logger.error(f"Error load font: {e}")
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

                # Cek rekursif 1 level (umum di Linux /usr/share/fonts/truetype/dejavu/...)
                try:
                    for item in os.listdir(dir_path):
                        subdir_path = os.path.join(dir_path, item)
                        if os.path.isdir(subdir_path):
                             font_path_subdir = os.path.join(subdir_path, name)
                             if os.path.exists(font_path_subdir):
                                 return font_path_subdir
                except OSError: # Jika tidak punya izin baca direktori
                    continue

        logger.warning(f"Tidak dapat menemukan font: {font_names} di direktori {font_dirs}.")
        return font_names[0] # Kembalikan nama pertama sebagai fallback

    @commands.command(name="buatssrp", aliases=["createssrp"])
    async def create_ssrp(self, ctx: commands.Context):
        """Buat SSRP Chatlog dari gambar dengan AI (gaya Chatlog Magician)"""
        # ... (kode cek attachment dan limitasi ukuran/jumlah sama seperti sebelumnya) ...
        if not self.client:
            await ctx.send("❌ Fitur SSRP Chatlog tidak tersedia (API Key belum dikonfigurasi)")
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
        valid_extensions = ('.png', '.jpg', '.jpeg')
        for attachment in ctx.message.attachments:
            if attachment.filename.lower().endswith(valid_extensions):
                if attachment.size > 8 * 1024 * 1024:
                    await ctx.send(f"⚠️ Gambar `{attachment.filename}` terlalu besar (>8MB), dilewati.")
                    continue
                try:
                    img_bytes = await attachment.read()
                    images_bytes_list.append(img_bytes)
                except Exception as e:
                    logger.error(f"Gagal download gambar '{attachment.filename}': {e}")
                    await ctx.send(f"❌ Gagal mengunduh `{attachment.filename}`.")
            if len(images_bytes_list) >= 10: break

        if not images_bytes_list:
            await ctx.send("❌ Tidak ada gambar valid (.png/.jpg) yang ditemukan atau berhasil diunduh!")
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
            except discord.NotFound: pass # Abaikan jika pesan sudah dihapus

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
        # ... (kode setup pesan progress sama seperti sebelumnya) ...
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

        try:
            await processing_msg.edit(content=f"🧠 {interaction.user.mention}, AI sedang membuat dialog...")

            language = info_data.get('language', 'Bahasa Indonesia baku')

            all_dialogs_raw = await self.generate_dialogs_with_ai(
                images_bytes_list, info_data, dialog_counts, language
            )

            processed_images_bytes = []
            for idx, (img_bytes, raw_dialogs, position, bg_style) in enumerate(zip(images_bytes_list, all_dialogs_raw, positions, background_styles)): # Iterate background styles too

                limited_dialogs = raw_dialogs[:dialog_counts[idx]]

                await processing_msg.edit(
                    content=f"🎨 {interaction.user.mention}, memproses gambar {idx + 1}/{len(images_bytes_list)} ({len(limited_dialogs)} baris, bg: {bg_style})..."
                )

                # Panggil fungsi overlay yang sudah diperbarui
                processed_img = await self.add_dialogs_to_image(
                    img_bytes,
                    limited_dialogs,
                    position,
                    bg_style # Pass background style
                )
                processed_images_bytes.append(processed_img)
                await asyncio.sleep(0.3) # Kurangi delay

            await processing_msg.edit(
                content=f"✅ Selesai! Hasil SSRP untuk {interaction.user.mention}:"
            )

            for i in range(0, len(processed_images_bytes), 10):
                chunk = processed_images_bytes[i:i+10]
                files = [
                    discord.File(io.BytesIO(img_data), filename=f"ssrp_generated{i+j+1}.jpg") # Simpan sebagai JPG
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
                # Tambahkan info bahasa
                embed_result.set_footer(text=f"Dialog AI dalam: {language}")

                await interaction.channel.send(embed=embed_result, files=files)

        except Exception as e:
            # ... (kode error handling sama seperti sebelumnya) ...
            logger.error(f"Error saat proses SSRP: {e}", exc_info=True)
            error_message = f"❌ Terjadi kesalahan: {str(e)[:1500]}"
            if processing_msg:
                try:
                    await processing_msg.edit(content=f"{interaction.user.mention}, {error_message}")
                except discord.NotFound: # Jika pesan sudah dihapus oleh user/mod
                    await interaction.channel.send(content=f"{interaction.user.mention}, {error_message}")
            else:
                 await interaction.channel.send(content=f"{interaction.user.mention}, {error_message}")


    async def generate_dialogs_with_ai(
        self,
        images_bytes_list: List[bytes],
        info_data: Dict,
        dialog_counts: List[int],
        language: str
    ) -> List[List[str]]:
        """Generate dialog SSRP SAMP yang benar menggunakan AI (prompt sama)"""
        # ... (Kode prompt dan pemanggilan AI tetap sama seperti di revisi sebelumnya) ...
        base64_img = base64.b64encode(images_bytes_list[0]).decode('utf-8')
        image_content = {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
        }

        dialog_requirements = "\n".join([
            f"Gambar {i+1}: HARUS berisi TEPAT {count} baris dialog."
            for i, count in enumerate(dialog_counts)
        ])

        char_details = info_data.get('detail_karakter', '')
        char_names_raw = re.findall(r"([A-Za-z'_]+(?: [A-Za-z'_]+)?)", char_details)
        if not char_names_raw:
            char_names_raw = [line.split('(')[0].strip() for line in char_details.split('\n') if line.strip()]
            char_names_raw = [re.sub(r"[^A-Za-z\s]+", "", name).strip() for name in char_names_raw if name]

        char_names_formatted = [name.replace(' ', '_') for name in char_names_raw if name]

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
        1. Obrolan Normal (IC): `Nama_Karakter says: Dialognya disini.` (Gunakan underscore di nama)
        2. Obrolan Rendah: `Nama_Karakter [low]: Dialognya disini.`
        3. Aksi /me: `* Nama_Karakter melakukan aksi` (Diawali bintang+spasi, tanpa titik di akhir)
        4. Deskripsi /do: `* Deskripsi keadaan atau hasil aksi (( Nama_Karakter ))` (Diawali bintang+spasi)
        5. Whisper: `Nama_Karakter whispers: Pesan rahasia` atau `... (phone): ...` untuk telepon
        6. Radio/Dept: `** [Departemen] Nama_Karakter: Pesan` atau `** [CH:X] Nama_Karakter: Pesan`
        7. Gunakan nama karakter PERSIS seperti ini: {', '.join(char_names_formatted)}

        FORMAT OUTPUT JSON (WAJIB HANYA JSON):
        {{
          "dialogs_per_image": [
            [ // Gambar 1
              "Baris dialog 1 (format /me, /do, says:, [low]:, whispers:, dll.)",
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
        - Variasikan jenis format dialog.
        """

        response_content = ""
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Anda adalah penulis dialog SSRP SAMP ahli. Output HANYA JSON."},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        image_content
                    ]}
                ],
                response_format={"type": "json_object"},
                max_tokens=2500,
                temperature=0.7
            )

            response_content = response.choices[0].message.content
            parsed_data = json.loads(response_content)
            dialogs_list = parsed_data.get("dialogs_per_image", [])

            if not isinstance(dialogs_list, list) or not all(isinstance(img_dialogs, list) for img_dialogs in dialogs_list):
                 raise ValueError("Format JSON dari AI tidak sesuai struktur yang diharapkan.")

        except json.JSONDecodeError as json_err:
             logger.error(f"Gagal parse JSON dari AI: {json_err}\nResponse mentah:\n{response_content[:500]}...")
             raise Exception(f"AI mengembalikan format JSON yang tidak valid. Error: {json_err}")
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}", exc_info=True)
            raise Exception(f"Gagal menghubungi AI atau memproses respons: {e}")

        while len(dialogs_list) < len(images_bytes_list):
            dialogs_list.append([f"[AI Gagal Generate Dialog untuk Gambar {len(dialogs_list)+1}]"])

        dialogs_list = dialogs_list[:len(images_bytes_list)]

        logger.info(f"AI generated dialogs for {len(dialogs_list)} images.")
        return dialogs_list

    async def add_dialogs_to_image(
        self,
        image_bytes: bytes,
        dialogs: List[str],
        position: str,
        background_style: str # Terima background style
    ) -> bytes:
        """Tambahkan dialog ke gambar dengan styling mirip Chatlog Magician"""
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
            width, height = img.size

            txt_overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(txt_overlay)

            padding = 8 # Padding lebih kecil

            # Hitung tinggi dialog total (termasuk spasi antar baris)
            total_dialog_height_pixels = len(dialogs) * (self.FONT_SIZE + self.LINE_HEIGHT_ADD) - self.LINE_HEIGHT_ADD + (padding * 2)

            y_coords = [] # y_start untuk top dan bottom

            # --- Gambar Background (jika overlay) dan Tentukan y_coords ---
            if background_style == "overlay":
                if position == "atas":
                    bg_y_end = min(total_dialog_height_pixels, height)
                    draw.rectangle([(0, 0), (width, bg_y_end)], fill=self.BG_COLOR)
                    y_coords.append(padding)
                elif position == "bawah":
                    bg_y_start = max(0, height - total_dialog_height_pixels)
                    draw.rectangle([(0, bg_y_start), (width, height)], fill=self.BG_COLOR)
                    y_coords.append(bg_y_start + padding)
                else: # split
                    half = (len(dialogs) + 1) // 2
                    top_dialogs = dialogs[:half]
                    bottom_dialogs = dialogs[half:]

                    # Background Atas
                    top_height_pixels = len(top_dialogs) * (self.FONT_SIZE + self.LINE_HEIGHT_ADD) - self.LINE_HEIGHT_ADD + (padding * 2)
                    bg_top_end = min(top_height_pixels, height)
                    draw.rectangle([(0, 0), (width, bg_top_end)], fill=self.BG_COLOR)
                    y_coords.append(padding)

                    # Background Bawah
                    bottom_height_pixels = len(bottom_dialogs) * (self.FONT_SIZE + self.LINE_HEIGHT_ADD) - self.LINE_HEIGHT_ADD + (padding * 2)
                    bg_bottom_start = max(0, height - bottom_height_pixels)
                    draw.rectangle([(0, bg_bottom_start), (width, height)], fill=self.BG_COLOR)
                    y_coords.append(bg_bottom_start + padding)
            else: # background_style == "transparent"
                 if position == "atas":
                     y_coords.append(padding)
                 elif position == "bawah":
                     y_start_bawah = max(padding, height - total_dialog_height_pixels + padding) # Sesuaikan agar tidak terlalu bawah
                     y_coords.append(y_start_bawah)
                 else: # split (transparent)
                     half = (len(dialogs) + 1) // 2
                     y_coords.append(padding) # Y atas
                     bottom_height_pixels = len(dialogs[half:]) * (self.FONT_SIZE + self.LINE_HEIGHT_ADD) - self.LINE_HEIGHT_ADD + (padding * 2)
                     y_start_bawah_split = max(padding, height - bottom_height_pixels + padding)
                     y_coords.append(y_start_bawah_split)

            # --- Draw Dialogs ---
            if position == "split":
                half = (len(dialogs) + 1) // 2
                y_pos_top = y_coords[0]
                for dialog in dialogs[:half]:
                    self.draw_text_with_multi_shadow(draw, (padding, y_pos_top), dialog, self.font)
                    y_pos_top += self.FONT_SIZE + self.LINE_HEIGHT_ADD
                y_pos_bottom = y_coords[1]
                for dialog in dialogs[half:]:
                    self.draw_text_with_multi_shadow(draw, (padding, y_pos_bottom), dialog, self.font)
                    y_pos_bottom += self.FONT_SIZE + self.LINE_HEIGHT_ADD
            else: # atas atau bawah
                y_pos = y_coords[0]
                for dialog in dialogs:
                    self.draw_text_with_multi_shadow(draw, (padding, y_pos), dialog, self.font)
                    y_pos += self.FONT_SIZE + self.LINE_HEIGHT_ADD # Gunakan FONT_SIZE + LINE_HEIGHT_ADD

            # Gabungkan gambar
            out_img = Image.alpha_composite(img, txt_overlay)

            # Simpan sebagai JPEG
            output = io.BytesIO()
            out_img.convert("RGB").save(output, format='JPEG', quality=90) # Convert ke RGB
            output.seek(0)
            return output.getvalue()

        except Exception as e:
            logger.error(f"Error di add_dialogs_to_image: {e}", exc_info=True)
            return image_bytes # Kembalikan asli jika gagal

    def get_text_color(self, text: str) -> tuple:
        """Tentukan warna teks berdasarkan format SSRP/Chatlog Magician"""
        original_text = text # Simpan teks asli untuk cek case-sensitive jika perlu
        text = text.strip().lower() # Lowercase untuk matching

        # Urutan penting: cek yang lebih spesifik dulu
        if text.startswith('** [ch:'): return self.COLOR_RADIO
        if text.startswith('** ['): return self.COLOR_DEP # Department chat
        if text.startswith('**'): return self.COLOR_DO
        if text.startswith('*'): return self.COLOR_ME
        if ' whispers:' in text: return self.COLOR_WHISPER
        if ' (phone):' in text or ':o<' in text: return self.COLOR_WHISPER # Phone whisper
        if ' [low]:' in text: return self.COLOR_LOWCHAT
        if '[san interview]' in text: return self.COLOR_NEWS
        if ' says:' in text: return self.COLOR_CHAT # Default chat
        if ', $' in text or 'you have received $' in text: return self.COLOR_GREY # Money/Paycheck
        # Tambahkan rule lain jika perlu (misal death message)
        # if 'died' in text: return self.COLOR_DEATH

        # Fallback ke putih jika tidak cocok
        return self.COLOR_CHAT

    def draw_text_with_multi_shadow(self, draw: ImageDraw.ImageDraw, pos: Tuple[int, int], text: str, font: ImageFont.FreeTypeFont):
        """Gambar teks dengan shadow hitam di 4 arah"""
        x, y = pos
        text_color = self.get_text_color(text)

        cleaned_text = text # Teks yang akan digambar

        # Ganti _ -> spasi HANYA untuk chat biasa (format Nama_Pemain says:)
        match = re.match(r"([A-Za-z0-9_]+)\s*(says|\[low\]):", text)
        if match:
            name = match.group(1).replace('_', ' ')
            rest_of_line = text[match.end():] # Ambil sisa teks setelah ': '
            cleaned_text = f"{name}{match.group(2)}:{rest_of_line}"

        # Gambar shadow dulu
        for dx, dy in self.SHADOW_OFFSETS:
            draw.text((x + dx, y + dy), cleaned_text, font=font, fill=self.COLOR_SHADOW)

        # Gambar teks utama di atas shadow
        draw.text(pos, cleaned_text, font=font, fill=text_color)


async def setup(bot):
    await bot.add_cog(SSRPChatlogCog(bot))
