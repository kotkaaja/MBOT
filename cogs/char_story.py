import discord
from discord.ext import commands
from discord import ui
from openai import AsyncOpenAI
import logging
from typing import Dict
import io
import json
import os

# Import fungsi database untuk cooldown
from utils.database import check_char_story_cooldown, set_char_story_cooldown

# Mengambil logger
logger = logging.getLogger(__name__)

# ============================
# MANAJEMEN KONFIGURASI SERVER (JSON)
# ============================

SERVER_CONFIG_FILE = 'char_story_servers.json'

def load_server_config() -> Dict:
    """Memuat konfigurasi server dari file JSON."""
    if not os.path.exists(SERVER_CONFIG_FILE):
        logger.warning(f"{SERVER_CONFIG_FILE} tidak ditemukan. Membuat file kosong.")
        save_server_config({}) # Buat file kosong jika tidak ada
        return {}
    try:
        with open(SERVER_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error(f"Gagal mem-parsing {SERVER_CONFIG_FILE}. File mungkin rusak.")
        return {}
    except Exception as e:
        logger.error(f"Gagal memuat {SERVER_CONFIG_FILE}: {e}")
        return {}

def save_server_config(data: Dict) -> bool:
    """Menyimpan data konfigurasi server ke file JSON."""
    try:
        with open(SERVER_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Gagal menyimpan ke {SERVER_CONFIG_FILE}: {e}")
        return False

# ============================
# UI COMPONENTS (MODAL & VIEWS)
# ============================

# Modal Bagian 2: Mengumpulkan detail cerita yang lebih dalam
class CSInputModal_Part2(ui.Modal):
    bakat_dominan = ui.TextInput(label="Bakat/Keahlian Dominan Karakter", placeholder="Contoh: Penembak jitu, negosiator ulung, pembalap liar", style=discord.TextStyle.short, required=True)
    culture = ui.TextInput(label="Kultur/Etnis (Opsional)", placeholder="Contoh: African-American, Hispanic, Italian-American", style=discord.TextStyle.short, required=False)
    detail_tambahan = ui.TextInput(label="Detail Tambahan (Opsional)", placeholder="Contoh: Punya hutang, dikhianati geng lama, dll.", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, server: str, story_type: str, bot_instance, part1_data: Dict):
        super().__init__(title=f"Detail Cerita ({story_type.replace('_',' ').title()}) (2/2)")
        self.server = server
        self.story_type = story_type
        self.bot = bot_instance
        self.part1_data = part1_data

    async def on_submit(self, interaction: discord.Interaction):
        # Tampilkan status "thinking" secara publik
        await interaction.response.defer()
        
        # Kirim pesan bahwa proses sedang berjalan
        processing_msg = await interaction.followup.send(f"⏳ Character Story untuk **{self.part1_data['nama_char']}** sedang diproses oleh AI...")
        
        # Muat konfigurasi terbaru
        SERVER_CONFIGS = load_server_config()
        if self.server not in SERVER_CONFIGS:
            await processing_msg.edit(content="❌ Error: Konfigurasi server tidak ditemukan. Mungkin baru saja dihapus. Coba lagi.")
            return

        try:
            # Gabungkan data dari formulir bagian 1 dan 2
            all_data = self.part1_data.copy()
            all_data.update({
                "bakat": self.bakat_dominan.value,
                "culture": self.culture.value,
                "detail": self.detail_tambahan.value,
                "server": self.server,
                "story_type": self.story_type,
            })

            # Panggil AI untuk menghasilkan cerita
            story_text = await self.bot.get_cog("CharacterStory").generate_story_from_ai(SERVER_CONFIGS, **all_data)

            # Format output sesuai server
            server_format = SERVER_CONFIGS[self.server]["format"]
            final_cs = server_format.format(
                nama_char=all_data['nama_char'],
                tanggal_lahir=all_data['tanggal_lahir'],
                kota_asal=all_data['kota_asal'],
                story=story_text,
                level=all_data['level'],
                jenis_kelamin=all_data['jenis_kelamin']
            )

            # Buat embed untuk hasil
            embed = discord.Embed(
                title=f"✅ Character Story Selesai: {all_data['nama_char']}",
                description="Cerita Anda telah berhasil dibuat. Silakan unduh file `.txt` di bawah ini dan lengkapi bagian yang diperlukan.",
                color=discord.Color.green()
            )
            embed.add_field(name="Server", value=SERVER_CONFIGS[self.server]['name'], inline=True)
            embed.add_field(name="Sisi Cerita", value=self.story_type.replace("_", " ").title(), inline=True)
            embed.set_footer(text=f"Diminta oleh: {interaction.user.display_name}")

            # Buat file .txt dalam memori
            story_file = discord.File(
                io.StringIO(final_cs),
                filename=f"CS_{all_data['nama_char'].replace(' ', '_')}.txt"
            )

            # Edit pesan proses dengan hasil akhir (embed + file)
            await processing_msg.edit(
                content=f"Character Story untuk **{all_data['nama_char']}**, diminta oleh {interaction.user.mention}:",
                embed=embed,
                attachments=[story_file]
            )
            
            # Atur cooldown harian setelah berhasil membuat
            set_char_story_cooldown(interaction.user.id)

        except Exception as e:
            logger.error(f"Gagal membuat CS dengan OpenAI: {e}", exc_info=True)
            error_msg = "❌ Terjadi kesalahan saat menghubungi AI. Pastikan API Key valid dan memiliki kuota."
            await processing_msg.edit(content=error_msg, embed=None, view=None, attachments=[])

# View untuk tombol Lanjutkan ke Bagian 2
class ContinueToPart2View(ui.View):
    def __init__(self, server: str, story_type: str, bot_instance, part1_data: Dict):
        super().__init__(timeout=300) # 5 menit timeout
        self.server = server
        self.story_type = story_type
        self.bot = bot_instance
        self.part1_data = part1_data

    @ui.button(label="Lanjutkan ke Detail Cerita (2/2)", style=discord.ButtonStyle.primary, emoji="➡️")
    async def continue_button(self, interaction: discord.Interaction, button: ui.Button):
        # Tombol ini membuat interaksi baru, jadi kita bisa mengirim modal
        await interaction.response.send_modal(CSInputModal_Part2(
            server=self.server,
            story_type=self.story_type,
            bot_instance=self.bot,
            part1_data=self.part1_data
        ))
        # Hapus view setelah diklik agar tidak bisa digunakan lagi
        await interaction.message.edit(view=None)
        self.stop()

# Modal Bagian 1: Mengumpulkan data dasar karakter
class CSInputModal_Part1(ui.Modal):
    nama_char = ui.TextInput(label="Nama Lengkap Karakter (IC)", placeholder="Contoh: John Washington, Kenji Tanaka", style=discord.TextStyle.short, required=True)
    level = ui.TextInput(label="Level Karakter", placeholder="Contoh: 1", style=discord.TextStyle.short, required=True, max_length=3)
    jenis_kelamin = ui.TextInput(label="Jenis Kelamin", placeholder="Contoh: Laki-laki / Perempuan", style=discord.TextStyle.short, required=True)
    tanggal_lahir = ui.TextInput(label="Tanggal Lahir", placeholder="Contoh: 17 Agustus 1995", style=discord.TextStyle.short, required=True)
    kota_asal = ui.TextInput(label="Kota Asal", placeholder="Contoh: Chicago, Illinois", style=discord.TextStyle.short, required=True)

    def __init__(self, server: str, story_type: str, bot_instance):
        super().__init__(title=f"Detail Karakter ({story_type.replace('_',' ').title()}) (1/2)")
        self.server = server
        self.story_type = story_type
        self.bot = bot_instance

    async def on_submit(self, interaction: discord.Interaction):
        part1_data = {
            # Langsung bersihkan nama dari underscore
            "nama_char": self.nama_char.value.replace('_', ' '),
            "level": self.level.value,
            "jenis_kelamin": self.jenis_kelamin.value,
            "tanggal_lahir": self.tanggal_lahir.value,
            "kota_asal": self.kota_asal.value,
        }
        # Kirim pesan dengan tombol untuk membuka modal kedua
        view = ContinueToPart2View(
            server=self.server,
            story_type=self.story_type,
            bot_instance=self.bot,
            part1_data=part1_data
        )
        await interaction.response.send_message(
            "✅ Detail dasar berhasil disimpan. Tekan tombol di bawah untuk melanjutkan.",
            view=view,
            ephemeral=True
        )

# View untuk memilih tipe cerita (Goodside/Badside)
class StoryTypeView(ui.View):
    def __init__(self, server: str, bot_instance):
        super().__init__(timeout=180)
        self.server = server
        self.bot = bot_instance

    @ui.button(label="😇 Sisi Baik (Goodside)", style=discord.ButtonStyle.success, emoji="😇")
    async def good_side(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CSInputModal_Part1(server=self.server, story_type="good_side", bot_instance=self.bot))

    @ui.button(label="😈 Sisi Jahat (Badside)", style=discord.ButtonStyle.danger, emoji="😈")
    async def bad_side(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CSInputModal_Part1(server=self.server, story_type="bad_side", bot_instance=self.bot))

# View untuk dropdown pemilihan server
class ServerSelectionView(ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=180) 
        self.bot = bot_instance

        # === PERUBAHAN DI SINI ===
        # Muat opsi server secara dinamis dari file JSON
        configs = load_server_config()
        if not configs:
            # Jika tidak ada server, tampilkan pesan error di tombol
            options = [discord.SelectOption(label="Error: Tidak ada server dikonfigurasi", value="error_no_server", emoji="❌")]
        else:
            options = [
                discord.SelectOption(
                    label=data.get("name", key.title()), # Ambil nama, fallback ke key
                    value=key, 
                    description=f"Buat CS untuk server {data.get('name', key.title())}."
                ) for key, data in configs.items()
            ]

        # Buat komponen select dengan opsi dinamis
        self.server_select = ui.Select(
            placeholder="Pilih server tujuan...",
            options=options,
            custom_id="server_select"
        )
        # Tambahkan callback ke komponen
        self.server_select.callback = self.select_server_callback
        # Tambahkan komponen ke view
        self.add_item(self.server_select)

    async def select_server_callback(self, interaction: discord.Interaction):
        """Callback yang dijalankan saat server dipilih."""
        server_choice = self.server_select.values[0]
        
        if server_choice == "error_no_server":
            await interaction.response.send_message("❌ Gagal memuat server. Hubungi Admin.", ephemeral=True)
            return

        await interaction.response.send_message("Pilih alur cerita untuk karaktermu:", view=StoryTypeView(server=server_choice, bot_instance=self.bot), ephemeral=True)


# View utama yang berisi tombol untuk memulai proses
class CSPanelView(ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None) 
        self.bot = bot_instance

    @ui.button(label="Buat Character Story", style=discord.ButtonStyle.primary, emoji="📝", custom_id="create_cs_button")
    async def create_cs(self, interaction: discord.Interaction, button: ui.Button):
        # Cek cooldown sebelum memulai proses
        if not check_char_story_cooldown(interaction.user.id):
            await interaction.response.send_message(
                "❌ Anda sudah membuat satu Character Story hari ini. Silakan coba lagi besok.",
                ephemeral=True
            )
            return
            
        await interaction.response.send_message("Pilih server di mana karaktermu akan bermain:", view=ServerSelectionView(self.bot), ephemeral=True)


# ============================
# MODAL UNTUK PERINTAH ADMIN
# ============================
class AddServerModal(ui.Modal):
    server_name = ui.TextInput(label="Nama Tampilan Server", placeholder="Contoh: SSRP, Virtual RP", style=discord.TextStyle.short, required=True)
    rules = ui.TextInput(label="Rules (Gunakan \\n untuk baris baru)", placeholder="Contoh: - Minimal 4 paragraf.\\n- Wajib baku.", style=discord.TextStyle.paragraph, required=True)
    server_format = ui.TextInput(label="Format (Gunakan \\n untuk baris baru)", placeholder="Contoh: **Format CS**\\n- Nama: {nama_char}\\n- Story:\\n{story}", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, server_key: str):
        super().__init__(title=f"Tambah/Edit Server: {server_key}")
        self.server_key = server_key

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Ganti escape \\n menjadi newline \n
        cleaned_rules = self.rules.value.replace("\\n", "\n")
        cleaned_format = self.server_format.value.replace("\\n", "\n")

        new_data = {
            "name": self.server_name.value,
            "rules": cleaned_rules,
            "format": cleaned_format
        }

        configs = load_server_config()
        action = "diperbarui" if self.server_key in configs else "ditambahkan"
        configs[self.server_key] = new_data

        if save_server_config(configs):
            await interaction.followup.send(f"✅ Server `{self.server_key}` (Nama: {self.server_name.value}) berhasil {action}.", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Gagal menyimpan konfigurasi ke {SERVER_CONFIG_FILE}.", ephemeral=True)


# ============================
# KELAS COG UTAMA
# ============================
class CharacterStoryCog(commands.Cog, name="CharacterStory"):
    def __init__(self, bot):
        self.bot = bot
        if not hasattr(bot, 'persistent_views_added') or not bot.persistent_views_added:
            bot.add_view(CSPanelView(bot))
            bot.persistent_views_added = True
        
        # Panggil load_server_config saat init untuk memastikan file JSON dibuat jika belum ada
        load_server_config()

    async def generate_story_from_ai(self, server_configs: Dict, server: str, nama_char: str, tanggal_lahir: str, kota_asal: str, story_type: str, bakat: str, culture: str, detail: str, jenis_kelamin: str, level: str) -> str:
        """Menghasilkan story dari OpenAI berdasarkan input detail."""
        
        if not self.bot.config.OPENAI_API_KEYS:
            raise Exception("API Key OpenAI tidak dikonfigurasi.")
            
        api_key = self.bot.config.OPENAI_API_KEYS[0]
        client = AsyncOpenAI(api_key=api_key)

        server_rules = server_configs[server]["rules"]
        server_name = server_configs[server]["name"]
        
        story_direction = ""
        if story_type == "good_side":
            story_direction = "Cerita harus bernuansa 'goodside'. Fokus pada latar belakang karakter yang baik, normal, atau memiliki tujuan hidup yang positif. Alasan pindah ke Los Santos harus logis untuk mencari kehidupan lebih baik atau bergabung dengan faksi legal seperti kepolisian, medis, atau bisnis."
        else: # bad_side
            story_direction = "Cerita harus bernuansa 'badside'. Fokus pada latar belakang yang keras, tumbuh di lingkungan gangster, atau mengalami peristiwa tragis yang mendorongnya ke dunia kejahatan. Alasan pindah ke Los Santos adalah untuk melarikan diri dari masalah atau mencari peluang di dunia kriminal."

        prompt = f"""
        Peran: Anda adalah penulis cerita kreatif yang sangat berpengalaman dalam dunia roleplay GTA San Andreas Multiplayer (SAMP) di Indonesia, dengan pemahaman mendalam tentang kultur Amerika.

        Tugas: Buat sebuah Character Story (CS) yang unik, mendalam, dan logis untuk server roleplay berbasis di Amerika, berdasarkan informasi detail berikut:
        - Nama Karakter: {nama_char}
        - Jenis Kelamin: {jenis_kelamin}
        - Tanggal Lahir: {tanggal_lahir}
        - Kota Asal: {kota_asal} (Asumsikan ini adalah kota di Amerika)
        - Latar Belakang Kultur/Etnis (jika ada): {culture if culture else 'Amerika umum'}
        - Sisi Cerita: {story_type.replace('_', ' ')}
        - Bakat/Keahlian Utama: {bakat}
        - Detail Tambahan: {detail if detail else 'Tidak ada.'}

        Struktur Cerita (WAJIB DIIKUTI):
        1.  **Latar Belakang:** Ceritakan kehidupan awal karakter di {kota_asal}.
        2.  **Titik Balik:** Jelaskan satu peristiwa penting yang menjadi alasan utama karakter pindah ke Los Santos. Peristiwa ini harus mencerminkan bakat utamanya ({bakat}).
        3.  **Adaptasi di Los Santos:** Gambarkan perjuangan atau adaptasi awal setelah tiba di kota baru.
        4.  **Tujuan Masa Depan:** Jelaskan kondisi karakter saat ini dan apa tujuannya di Los Santos.

        Instruksi Spesifik (SANGAT PENTING):
        -   **Gaya Penulisan:** Gunakan sudut pandang orang ketiga (third-person point of view). Sebut karakter dengan namanya ({nama_char}), hindari kata 'aku' atau 'saya'.
        -   **Penulisan Nama:** Jangan pernah gunakan garis bawah (_) pada nama karakter. Tulis nama seperti nama orang pada umumnya (contoh: Muriel Bagge).
        -   **Kultur:** Cerita harus terasa seperti berlatar di Amerika. Jika kultur/etnis spesifik diberikan, integrasikan secara halus (misalnya, melalui nama, tradisi, lingkungan). Jika tidak, gunakan nuansa kultur Amerika pada umumnya.
        -   **Arah Cerita:** {story_direction}
        -   **Integrasi Bakat:** Jadikan bakat '{bakat}' sebagai pilar utama dalam alur cerita.

        ATURAN TEKNIS WAJIB UNTUK SERVER '{server_name}':
        {server_rules}

        Output akhir harus berupa teks cerita saja dalam Bahasa Indonesia, tanpa judul atau format tambahan. Pastikan cerita yang dihasilkan menarik, konsisten, dan memenuhi semua aturan.
        """
        
        logger.info(f"Mengirim prompt ke OpenAI untuk karakter {nama_char}...")
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.75,
            max_tokens=1200,
        )
        
        story_text = response.choices[0].message.content
        cleaned_story = story_text.strip().replace("```", "")
        
        return cleaned_story

    @commands.command(name="setupcs")
    @commands.has_permissions(administrator=True) # Sebaiknya hanya admin yang bisa setup panel
    async def setup_cs_panel(self, ctx):
        """Mengirim panel untuk membuat Character Story."""
        embed = discord.Embed(
            title="📝 Panel Pembuatan Character Story",
            description="Tekan tombol di bawah untuk memulai proses pembuatan **Character Story (CS)** yang lebih detail dan sesuai keinginanmu.",
            color=0x5865F2
        )
        embed.add_field(
            name="Alur Baru yang Lebih Detail",
            value="1. Pilih Server\n2. Pilih Sisi Cerita (Baik/Jahat)\n3. Isi Detail Lengkap Karakter (Nama, Kultur, Bakat, dll.)",
            inline=False
        )
        embed.set_footer(text="Created By Kotkaaja.")

        await ctx.send(embed=embed, view=CSPanelView(self.bot))

    # ============================
    # PERINTAH ADMIN BARU
    # ============================
    @commands.command(name="addserver")
    @commands.has_permissions(administrator=True)
    async def add_server_command(self, ctx, server_key: str):
        """[ADMIN] Menambah atau mengedit server di konfigurasi CS."""
        server_key = server_key.lower().strip()
        if not server_key:
            await ctx.send("❌ Key tidak boleh kosong. Contoh: `!addserver ssrp`")
            return
            
        await ctx.send_modal(AddServerModal(server_key))

    @commands.command(name="delserver")
    @commands.has_permissions(administrator=True)
    async def delete_server_command(self, ctx, server_key: str):
        """[ADMIN] Menghapus server dari konfigurasi CS."""
        server_key = server_key.lower().strip()
        configs = load_server_config()

        if server_key not in configs:
            await ctx.send(f"❌ Server dengan key `{server_key}` tidak ditemukan di `{SERVER_CONFIG_FILE}`.")
            return

        # Hapus server dari dictionary
        removed_name = configs.pop(server_key, {}).get('name', server_key)
        
        if save_server_config(configs):
            await ctx.send(f"✅ Server `{server_key}` (Nama: {removed_name}) berhasil dihapus dari konfigurasi.")
        else:
            await ctx.send(f"❌ Gagal menyimpan perubahan ke `{SERVER_CONFIG_FILE}`.")
            
    @commands.command(name="listservers")
    @commands.has_permissions(administrator=True)
    async def list_servers_command(self, ctx):
        """[ADMIN] Menampilkan daftar server CS yang terkonfigurasi."""
        configs = load_server_config()
        if not configs:
            await ctx.send(f"ℹ️ Tidak ada server yang dikonfigurasi di `{SERVER_CONFIG_FILE}`.")
            return

        embed = discord.Embed(title="Daftar Server Character Story", color=0x3498db)
        desc = ""
        for key, data in configs.items():
            desc += f"- **Key:** `{key}` | **Nama:** {data.get('name', 'N/A')}\n"
        
        embed.description = desc
        await ctx.send(embed=embed)


async def setup(bot):
    # Pastikan atribut 'persistent_views_added' ada di bot
    if not hasattr(bot, 'persistent_views_added'):
        bot.persistent_views_added = False
    await bot.add_cog(CharacterStoryCog(bot))
