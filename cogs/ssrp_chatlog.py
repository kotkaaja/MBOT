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
            value="• Maksimal 7 baris per gambar\n• Pilih posisi: Atas, Bawah, atau Split",
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
            for i in range(1, 8)
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
            discord.SelectOption(label="Split (Atas & Bawah)", value="split", emoji="⬆️⬇️")
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
                
                processed_img = await self.add_dialogs_to_image(
                    img_bytes,
                    dialogs,
                    position
                )
                processed_images.append(processed_img)
                
                # Delay untuk menghindari rate limit
                await asyncio.sleep(1)
            
            # Kirim hasil
            await processing_msg.edit(
                content=f"✅ Semua gambar berhasil diproses! Diminta oleh {interaction.user.mention}"
            )
            
            # Send images in chunks (max 10 per message)
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
        """Generate dialog untuk semua gambar menggunakan Claude AI"""
        
        # Prepare image data untuk Claude
        image_contents = []
        for idx, img_bytes in enumerate(images):
            base64_img = base64.b64encode(img_bytes).decode('utf-8')
            image_contents.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64_img
                }
            })
        
        # Build dialog requirements
        dialog_requirements = "\n".join([
            f"Gambar {i+1}: {count} baris dialog"
            for i, count in enumerate(dialog_counts)
        ])
        
        # Create prompt
        prompt = f"""Anda adalah penulis dialog roleplay SAMP yang ahli. Berdasarkan informasi berikut:

INFORMASI KARAKTER:
{info_data['detail_karakter']}

SKENARIO ROLEPLAY:
{info_data['skenario']}

JUMLAH GAMBAR: {len(images)}

KEBUTUHAN DIALOG:
{dialog_requirements}

Buatlah dialog yang natural dan sesuai dengan gambar-gambar yang diberikan. Setiap dialog harus:
1. Sesuai dengan konteks visual di gambar
2. Mengikuti skenario yang diberikan
3. Mencerminkan karakter yang dijelaskan
4. Natural seperti percakapan asli dalam game roleplay SAMP

Format output HARUS seperti ini:
===GAMBAR_1===
Nama_Karakter says: Dialog baris 1
Nama_Karakter says: Dialog baris 2
===GAMBAR_2===
Nama_Karakter says: Dialog baris 1
...dan seterusnya

PENTING: 
- Gunakan format "Nama_Karakter says: dialog" (dengan underscore di nama)
- Gunakan nama karakter persis seperti yang disebutkan
- Jangan tambahkan timestamp atau format lain"""

        # Call OpenAI API
        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert SAMP roleplay dialogue writer."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            temperature=0.8
        )
        
        response_text = response.choices[0].message.content
        
        # Parse response
        dialogs_per_image = []
        current_dialogs = []
        
        for line in response_text.split('\n'):
            line = line.strip()
            if line.startswith('===GAMBAR_'):
                if current_dialogs:
                    dialogs_per_image.append(current_dialogs)
                    current_dialogs = []
            elif line and not line.startswith('==='):
                current_dialogs.append(line)
        
        if current_dialogs:
            dialogs_per_image.append(current_dialogs)
        
        # Ensure we have dialogs for all images
        while len(dialogs_per_image) < len(images):
            dialogs_per_image.append([])
        
        return dialogs_per_image

    async def add_dialogs_to_image(
        self,
        image_bytes: bytes,
        dialogs: List[str],
        position: str
    ) -> bytes:
        """Add dialog text to image"""
        
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        
        # Hitung tinggi yang dibutuhkan untuk dialog
        line_height = 25
        dialog_height = len(dialogs) * line_height + 20  # +20 untuk padding
        
        # Create new image dengan space untuk dialog
        if position == "atas":
            new_height = height + dialog_height
            new_img = Image.new('RGB', (width, new_height), color='black')
            new_img.paste(img, (0, dialog_height))
            y_start = 10
        elif position == "bawah":
            new_height = height + dialog_height
            new_img = Image.new('RGB', (width, new_height), color='black')
            new_img.paste(img, (0, 0))
            y_start = height + 10
        else:  # split
            half_dialogs = len(dialogs) // 2
            top_height = half_dialogs * line_height + 20
            bottom_height = (len(dialogs) - half_dialogs) * line_height + 20
            new_height = height + top_height + bottom_height
            new_img = Image.new('RGB', (width, new_height), color='black')
            new_img.paste(img, (0, top_height))
        
        draw = ImageDraw.Draw(new_img)
        
        # Load font
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        except:
            try:
                font = ImageFont.truetype("arial.ttf", 16)
            except:
                font = ImageFont.load_default()
        
        # Draw dialogs
        if position == "split":
            half = len(dialogs) // 2
            # Top dialogs
            y_pos = 10
            for dialog in dialogs[:half]:
                draw.text((10, y_pos), dialog, fill='white', font=font, stroke_width=2, stroke_fill='black')
                y_pos += line_height
            # Bottom dialogs
            y_pos = height + top_height + 10
            for dialog in dialogs[half:]:
                draw.text((10, y_pos), dialog, fill='white', font=font, stroke_width=2, stroke_fill='black')
                y_pos += line_height
        else:
            y_pos = y_start
            for dialog in dialogs:
                draw.text((10, y_pos), dialog, fill='white', font=font, stroke_width=2, stroke_fill='black')
                y_pos += line_height
        
        # Convert back to bytes
        output = io.BytesIO()
        new_img.save(output, format='PNG')
        output.seek(0)
        return output.getvalue()


async def setup(bot):
    await bot.add_cog(SSRPChatlogCog(bot))
