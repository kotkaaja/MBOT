import discord
from discord.ext import commands
from discord import ui
import logging
import io
import base64
from PIL import Image, ImageDraw, ImageFont
from openai import AsyncOpenAI
from typing import List, Dict, Optional
import asyncio
import re

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

    def __init__(self, cog_instance, images: List[bytes]):
        super().__init__()
        self.cog = cog_instance
        self.images = images
        self.dialog_counts = []
        self.positions = []

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Simpan data dari modal pertama
        self.data = {
            'jumlah_pemain': self.jumlah_pemain.value,
            'detail_karakter': self.detail_karakter.value,
            'skenario': self.skenario.value
        }
        
        # Lanjut ke input dialog settings
        await self.show_dialog_settings(interaction)
    
    async def show_dialog_settings(self, interaction: discord.Interaction):
        """Menampilkan view untuk setting dialog per gambar"""
        view = DialogSettingsView(self.cog, self.images, self.data)
        
        embed = discord.Embed(
            title="⚙️ Pengaturan Dialog",
            description=f"Atur jumlah baris dialog untuk setiap gambar ({len(self.images)} gambar)",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Instruksi",
            value="• Maksimal 7 baris per gambar\n• Pilih posisi: Atas, Bawah, atau Split\nPosisi ini menentukan di mana overlay chat akan ditempatkan.",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class DialogSettingsView(ui.View):
    """View untuk mengatur dialog count dan posisi per gambar"""
    
    def __init__(self, cog_instance, images: List[bytes], info_data: Dict):
        super().__init__(timeout=300)
        self.cog = cog_instance
        self.images = images
        self.info_data = info_data
        self.dialog_counts = [5] * len(images)  # Default 5 baris
        self.positions = ["bawah"] * len(images)  # Default posisi bawah
        self.current_image = 0
        
        self.update_ui()
    
    def update_ui(self):
        self.clear_items()
        
        # Counter untuk dialog
        self.add_item(DialogCountSelect(self))
        
        # Posisi selector
        self.add_item(PositionSelect(self))
        
        # Navigation buttons
        if self.current_image > 0:
            self.add_item(PrevImageButton(self))
        
        if self.current_image < len(self.images) - 1:
            self.add_item(NextImageButton(self))
        else:
            self.add_item(FinishButton(self))
    
    async def update_message(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"⚙️ Gambar {self.current_image + 1}/{len(self.images)}",
            description="Atur jumlah baris dialog dan posisi text",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Jumlah Baris Dialog",
            value=f"{self.dialog_counts[self.current_image]} baris",
            inline=True
        )
        embed.add_field(
            name="Posisi Dialog",
            value=self.positions[self.current_image].capitalize(),
            inline=True
        )
        
        await interaction.response.edit_message(embed=embed, view=self)


class DialogCountSelect(ui.Select):
    """Select untuk jumlah dialog"""
    
    def __init__(self, parent_view):
        options = [
            discord.SelectOption(label=f"{i} baris", value=str(i))
            for i in range(1, 8) # 1-7 baris
        ]
        super().__init__(
            placeholder="Pilih jumlah baris dialog (1-7)",
            options=options,
            row=0
        )
        self.parent_view = parent_view
    
    async def callback(self, interaction: discord.Interaction):
        self.parent_view.dialog_counts[self.parent_view.current_image] = int(self.values[0])
        await self.parent_view.update_message(interaction)


class PositionSelect(ui.Select):
    """Select untuk posisi dialog"""

    def __init__(self, parent_view):
        options = [
            discord.SelectOption(label="Atas", value="atas", emoji="⬆️"),
            discord.SelectOption(label="Bawah", value="bawah", emoji="⬇️"),
            discord.SelectOption(label="Split (Atas & Bawah)", value="split", emoji="↕️")
        ]
        super().__init__(
            placeholder="Pilih posisi dialog",
            options=options,
            row=1
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.positions[self.parent_view.current_image] = self.values[0]
        await self.parent_view.update_message(interaction)


class PrevImageButton(ui.Button):
    """Button untuk gambar sebelumnya"""
    
    def __init__(self, parent_view):
        super().__init__(
            label="◀️ Gambar Sebelumnya",
            style=discord.ButtonStyle.secondary,
            row=2
        )
        self.parent_view = parent_view
    
    async def callback(self, interaction: discord.Interaction):
        self.parent_view.current_image -= 1
        self.parent_view.update_ui()
        await self.parent_view.update_message(interaction)


class NextImageButton(ui.Button):
    """Button untuk gambar selanjutnya"""
    
    def __init__(self, parent_view):
        super().__init__(
            label="Gambar Selanjutnya ▶️",
            style=discord.ButtonStyle.primary,
            row=2
        )
        self.parent_view = parent_view
    
    async def callback(self, interaction: discord.Interaction):
        self.parent_view.current_image += 1
        self.parent_view.update_ui()
        await self.parent_view.update_message(interaction)


class FinishButton(ui.Button):
    """Button untuk memulai proses"""
    
    def __init__(self, parent_view):
        super().__init__(
            label="✅ Proses Semua Gambar",
            style=discord.ButtonStyle.success,
            row=2
        )
        self.parent_view = parent_view
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # Mulai proses generate dialog
        await self.parent_view.cog.process_ssrp(
            interaction,
            self.parent_view.images,
            self.parent_view.info_data,
            self.parent_view.dialog_counts,
            self.parent_view.positions
        )


# ============================
# COG UTAMA
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
            self.client = AsyncOpenAI(api_key=self.bot.config.OPENAI_API_KEYS[0])
            logger.info("✅ OpenAI client untuk SSRP Chatlog berhasil diinisialisasi")
            
        # Pengaturan Font dan Warna
        self.FONT_SIZE = 14
        self.LINE_HEIGHT = 18
        self.FONT_PATH = "arial.ttf" # Ganti jika perlu (misal: "tahoma.ttf")
        self.COLOR_CHAT = (255, 255, 255) # Putih
        self.COLOR_ME = (194, 162, 218) # Ungu/Pink #C2A2DA
        self.COLOR_DO = (153, 204, 255) # Biru Muda #99CCFF
        self.COLOR_OOC = (170, 170, 170) # Abu-abu #AAAAAA
        self.COLOR_SHADOW = (0, 0, 0)
        self.BG_COLOR = (0, 0, 0, 128) # Hitam semi-transparan (128 alpha)
        
        # Load font
        try:
            self.font = ImageFont.truetype(self.FONT_PATH, self.FONT_SIZE)
        except IOError:
            logger.warning(f"Font {self.FONT_PATH} tidak ditemukan, menggunakan font default.")
            try:
                # Coba font lain yang umum
                self.FONT_PATH = "DejaVuSans.ttf" 
                self.font = ImageFont.truetype(self.FONT_PATH, self.FONT_SIZE)
            except IOError:
                 self.font = ImageFont.load_default()


    @commands.command(name="buatssrp", aliases=["createssrp"])
    async def create_ssrp(self, ctx: commands.Context):
        """
        Buat SSRP Chatlog dari gambar-gambar dengan AI
        
        Cara pakai:
        1. Kirim command !buatssrp sambil upload 1-10 gambar
        2. Isi informasi SSRP (jumlah pemain, karakter, skenario)
        3. Atur dialog untuk setiap gambar
        4. Tunggu AI generate dialog dan overlay ke gambar
        """
        
        if not self.client:
            await ctx.send("❌ Fitur SSRP Chatlog tidak tersedia (API Key belum dikonfigurasi)")
            return
        
        # Cek apakah ada gambar yang dilampirkan
        if not ctx.message.attachments:
            embed = discord.Embed(
                title="📸 Cara Menggunakan !buatssrp",
                description="Lampirkan 1-10 gambar saat mengirim command",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Langkah-langkah",
                value=(
                    "1️⃣ Upload gambar (1-10 gambar)\n"
                    "2️⃣ Ketik `!buatssrp` di caption\n"
                    "3️⃣ Isi form informasi SSRP\n"
                    "4️⃣ Atur dialog untuk tiap gambar\n"
                    "5️⃣ Tunggu AI generate dialog"
                ),
                inline=False
            )
            embed.add_field(
                name="Contoh",
                value="Upload 3 screenshot RP, ketik `!buatssrp`, lalu ikuti instruksi",
                inline=False
            )
            await ctx.send(embed=embed)
            return
        
        # Filter hanya gambar
        images = []
        for attachment in ctx.message.attachments:
            if attachment.content_type and attachment.content_type.startswith('image/'):
                # Download gambar
                try:
                    image_bytes = await attachment.read()
                    images.append(image_bytes)
                except Exception as e:
                    logger.error(f"Gagal download gambar: {e}")
        
        if not images:
            await ctx.send("❌ Tidak ada gambar valid yang ditemukan!")
            return
        
        if len(images) > 10:
            await ctx.send("❌ Maksimal 10 gambar per sesi!")
            return
        
        # Tampilkan modal untuk input informasi
        modal = SSRPInfoModal(self, images)
        
        # Kirim button untuk membuka modal
        view = ui.View(timeout=60)
        button = ui.Button(
            label=f"📝 Isi Informasi SSRP ({len(images)} gambar)",
            style=discord.ButtonStyle.primary
        )
        
        async def button_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "❌ Hanya yang request yang bisa mengisi!",
                    ephemeral=True
                )
                return
            await interaction.response.send_modal(modal)
        
        button.callback = button_callback
        view.add_item(button)
        
        embed = discord.Embed(
            title="✅ Gambar Berhasil Diupload",
            description=f"{len(images)} gambar siap diproses",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Langkah Selanjutnya",
            value="Klik tombol di bawah untuk mengisi informasi SSRP",
            inline=False
        )
        
        await ctx.send(embed=embed, view=view)

    async def process_ssrp(
        self,
        interaction: discord.Interaction,
        images: List[bytes],
        info_data: Dict,
        dialog_counts: List[int],
        positions: List[str]
    ):
        """Proses generate dialog dan overlay ke gambar"""
        
        processing_msg = await interaction.followup.send(
            f"⏳ Memproses {len(images)} gambar dengan AI...",
            ephemeral=False
        )
        
        try:
            # Generate dialog dengan AI
            all_dialogs = await self.generate_dialogs_with_ai(
                images,
                info_data,
                dialog_counts
            )
            
            # Process setiap gambar
            processed_images = []
            for idx, (img_bytes, dialogs, position) in enumerate(zip(images, all_dialogs, positions)):
                await processing_msg.edit(
                    content=f"⏳ Memproses gambar {idx + 1}/{len(images)}..."
                )
                
                # Pastikan dialog tidak melebihi jumlah yang diminta
                limited_dialogs = dialogs[:dialog_counts[idx]]
                
                processed_img = await self.add_dialogs_to_image(
                    img_bytes,
                    limited_dialogs,
                    position
                )
                processed_images.append(processed_img)
                
                # Delay kecil
                await asyncio.sleep(0.5)
            
            # Kirim hasil
            await processing_msg.edit(
                content=f"✅ Semua gambar berhasil diproses! Diminta oleh {interaction.user.mention}"
            )
            
            # Kirim gambar dalam chunk (max 10 per pesan)
            for i in range(0, len(processed_images), 10):
                chunk = processed_images[i:i+10]
                files = [
                    discord.File(io.BytesIO(img_bytes), filename=f"ssrp_{i+j+1}.png")
                    for j, img_bytes in enumerate(chunk)
                ]
                
                embed = discord.Embed(
                    title=f"📸 Hasil SSRP Chatlog (Gambar {i+1}-{i+len(chunk)})",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="Skenario",
                    value=info_data['skenario'][:200] + "..." if len(info_data['skenario']) > 200 else info_data['skenario'],
                    inline=False
                )
                
                await interaction.followup.send(embed=embed, files=files)
        
        except Exception as e:
            logger.error(f"Error saat proses SSRP: {e}", exc_info=True)
            await processing_msg.edit(
                content=f"❌ Terjadi kesalahan: {str(e)}"
            )

    async def generate_dialogs_with_ai(
        self,
        images: List[bytes],
        info_data: Dict,
        dialog_counts: List[int]
    ) -> List[List[str]]:
        """Generate dialog untuk semua gambar menggunakan AI"""
        
        # Prepare image data untuk AI (hanya gambar pertama untuk konteks)
        # Mengirim semua gambar bisa sangat mahal dan lambat.
        # Kita akan kirim gambar pertama sebagai konteks utama.
        
        base64_img = base64.b64encode(images[0]).decode('utf-8')
        image_content = {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{base64_img}"
            }
        }
        
        # Build dialog requirements
        dialog_requirements = "\n".join([
            f"Gambar {i+1}: HARUS berisi TEPAT {count} baris dialog."
            for i, count in enumerate(dialog_counts)
        ])
        
        # Ambil nama karakter dari detail
        char_names = re.findall(r"([A-Za-z_]+ [A-Za-z_]+)", info_data['detail_karakter'])
        
        # Create prompt
        prompt = f"""Anda adalah penulis dialog SSRP (Screenshot Roleplay) untuk server SAMP (San Andreas Multiplayer) yang sangat ahli.
Tugas Anda adalah membuat dialog yang natural dan imersif berdasarkan skenario dan detail karakter, serta sesuai dengan jumlah baris yang diminta untuk setiap gambar.

INFORMASI KARAKTER:
{info_data['detail_karakter']}
Nama karakter yang terlibat: {', '.join(char_names)}

SKENARIO ROLEPLAY:
{info_data['skenario']}

JUMLAH GAMBAR: {len(images)}
(Anda hanya melihat gambar pertama sebagai referensi visual. Fokus pada skenario untuk dialog selanjutnya.)

KEBUTUHAN DIALOG PER GAMBAR:
{dialog_requirements}

ATURAN FORMAT SANGAT PENTING:
1.  Gunakan format SAMP yang benar.
2.  Untuk obrolan normal (IC), gunakan: `Nama_Karakter: Dialognya di sini.` (Gunakan underscore untuk spasi di nama)
3.  Untuk aksi /me, gunakan: `* Nama_Karakter melakukan sesuatu.` (diawali bintang dan spasi)
4.  Untuk aksi /do, gunakan: `** Sesuatu terjadi. (( Nama_Karakter ))` (diawali dua bintang, dan nama karakter di akhir dalam kurung OOC)
5.  Untuk OOC chat, gunakan: `(( Dialog OOC ))`

FORMAT OUTPUT HARUS SEPERTI INI (PISAHKAN DENGAN ===GAMBAR_X===):
===GAMBAR_1===
[baris 1]
[baris 2]
...
===GAMBAR_2===
[baris 1]
[baris 2]
...
(dan seterusnya)

Contoh output untuk 1 gambar:
===GAMBAR_1===
* John_Doe melihat ke arah Jane_Smith.
John_Doe: Apa yang kamu lihat di sana?
** Terlihat ada sebuah mobil hitam terparkir di ujung jalan. (( John_Doe ))
Jane_Smith: Sepertinya mobil itu mencurigakan.
* Jane_Smith menunjuk ke arah mobil tersebut.

PENTING:
- PASTIKAN jumlah baris dialog untuk setiap gambar TEPAT sesuai permintaan.
- Gunakan nama karakter persis seperti yang ada di 'Informasi Karakter'. Ganti spasi dengan underscore (contoh: John Doe menjadi John_Doe).
- Buat dialog mengalir natural dari gambar 1 ke gambar berikutnya, melanjutkan skenario.
- Jangan tambahkan timestamp.
"""

        # Call OpenAI API
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o", # Model yang lebih kuat untuk tugas kompleks
                messages=[
                    {"role": "system", "content": "Anda adalah penulis dialog SSRP SAMP yang ahli."},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        image_content # Kirim gambar pertama
                    ]}
                ],
                max_tokens=3000,
                temperature=0.7
            )
            
            response_text = response.choices[0].message.content
        
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}. Mencoba gpt-4o-mini...")
            # Fallback ke model mini jika 'o' gagal (misal karena gambar)
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Anda adalah penulis dialog SSRP SAMP yang ahli."},
                    {"role": "user", "content": prompt} # Kirim teks saja
                ],
                max_tokens=2000,
                temperature=0.7
            )
            response_text = response.choices[0].message.content

        
        # Parse response
        dialogs_per_image = []
        current_dialogs = []
        
        if not response_text:
            raise Exception("AI tidak mengembalikan respon teks.")

        # Split berdasarkan ===GAMBAR_X===
        parts = re.split(r'===GAMBAR_\d+===', response_text)
        
        for part in parts:
            if not part.strip():
                continue
                
            lines = [line.strip() for line in part.split('\n') if line.strip()]
            dialogs_per_image.append(lines)
        
        # Jika parsing gagal, coba parsing manual
        if not dialogs_per_image:
             for line in response_text.split('\n'):
                line = line.strip()
                if line.startswith('===GAMBAR_'):
                    if current_dialogs:
                        dialogs_per_image.append(current_dialogs)
                    current_dialogs = []
                elif line:
                    current_dialogs.append(line)
             if current_dialogs:
                dialogs_per_image.append(current_dialogs)

        
        # Pastikan jumlahnya sesuai
        while len(dialogs_per_image) < len(images):
            dialogs_per_image.append(["[AI Gagal generate dialog untuk gambar ini]", f"Jumlah: {len(dialogs_per_image)}/{len(images)}"])
        
        logger.info(f"AI generated {len(dialogs_per_image)} sets of dialogs.")
        return dialogs_per_image

    async def add_dialogs_to_image(
        self,
        image_bytes: bytes,
        dialogs: List[str],
        position: str
    ) -> bytes:
        """Tambahkan dialog ke gambar DENGAN BENAR (overlay, drop shadow)"""
        
        # Buka gambar dan konversi ke RGBA untuk transparansi
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        width, height = img.size
        
        # Buat overlay transparan untuk menggambar teks dan BG
        txt_overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(txt_overlay)
        
        padding = 10 # Padding dari tepi
        
        # Hitung tinggi yang dibutuhkan
        dialog_height = (len(dialogs) * self.LINE_HEIGHT) + (padding * 2)
        
        # Tentukan posisi Y dan gambar background semi-transparan
        if position == "atas":
            bg_y_start = 0
            bg_y_end = dialog_height
            y_pos = padding
            
        elif position == "bawah":
            bg_y_start = height - dialog_height
            bg_y_end = height
            y_pos = bg_y_start + padding
            
        else:  # split
            half_dialogs = (len(dialogs) + 1) // 2
            top_dialogs = dialogs[:half_dialogs]
            bottom_dialogs = dialogs[half_dialogs:]
            
            # Hitung tinggi atas
            top_height = (len(top_dialogs) * self.LINE_HEIGHT) + (padding * 2)
            draw.rectangle([(0, 0), (width, top_height)], fill=self.BG_COLOR)
            
            # Hitung tinggi bawah
            bottom_height = (len(bottom_dialogs) * self.LINE_HEIGHT) + (padding * 2)
            bottom_y_start = height - bottom_height
            draw.rectangle([(0, bottom_y_start), (width, height)], fill=self.BG_COLOR)
            
            # Draw dialogs (split)
            y_pos_top = padding
            for dialog in top_dialogs:
                self.draw_text_with_shadow(draw, (padding, y_pos_top), dialog, self.font)
                y_pos_top += self.LINE_HEIGHT
            
            y_pos_bottom = bottom_y_start + padding
            for dialog in bottom_dialogs:
                self.draw_text_with_shadow(draw, (padding, y_pos_bottom), dialog, self.font)
                y_pos_bottom += self.LINE_HEIGHT
            
            # Gabungkan gambar dan return
            out_img = Image.alpha_composite(img, txt_overlay)
            output = io.BytesIO()
            out_img.convert("RGB").save(output, format='JPEG', quality=90)
            output.seek(0)
            return output.getvalue()

        # Gambar background untuk 'atas' atau 'bawah'
        draw.rectangle([(0, bg_y_start), (width, bg_y_end)], fill=self.BG_COLOR)
        
        # Draw dialogs (atas atau bawah)
        for dialog in dialogs:
            self.draw_text_with_shadow(draw, (padding, y_pos), dialog, self.font)
            y_pos += self.LINE_HEIGHT
        
        # Gabungkan gambar asli dengan overlay teks
        out_img = Image.alpha_composite(img, txt_overlay)
        
        # Convert kembali ke bytes
        output = io.BytesIO()
        out_img.convert("RGB").save(output, format='JPEG', quality=90) # Simpan sebagai JPEG
        output.seek(0)
        return output.getvalue()
        
    def get_text_color(self, text: str) -> tuple:
        """Tentukan warna teks berdasarkan format SSRP"""
        text = text.strip()
        if text.startswith('*'):
            return self.COLOR_ME
        if text.startswith('**'):
            return self.COLOR_DO
        if text.startswith('(('):
            return self.COLOR_OOC
        return self.COLOR_CHAT

    def draw_text_with_shadow(self, draw, pos, text, font):
        """Gambar teks dengan drop shadow 1px"""
        x, y = pos
        shadow_pos = (x + 1, y + 1)
        text_color = self.get_text_color(text)
        
        # Ganti underscore di nama karakter menjadi spasi HANYA untuk tampilan
        # Contoh: John_Doe: -> John Doe:
        if ':' in text and not text.startswith('*'):
            parts = text.split(':', 1)
            name = parts[0].replace('_', ' ')
            dialog = parts[1]
            text = f"{name}:{dialog}"

        # Gambar bayangan
        draw.text(shadow_pos, text, font=font, fill=self.COLOR_SHADOW)
        # Gambar teks utama
        draw.text(pos, text, font=font, fill=text_color)


async def setup(bot):
    await bot.add_cog(SSRPChatlogCog(bot))
