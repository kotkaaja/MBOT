# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)

class RoleAssignerCog(commands.Cog, name="RoleAssigner"):
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        
        # Mengambil variabel yang relevan dari config
        self.ROLE_REQUEST_CHANNEL_ID = self.config.ROLE_REQUEST_CHANNEL_ID
        self.SUBSCRIBER_ROLE_NAME = self.config.SUBSCRIBER_ROLE_NAME
        self.FOLLOWER_ROLE_NAME = self.config.FOLLOWER_ROLE_NAME
        self.FORGE_VERIFIED_ROLE_NAME = self.config.FORGE_VERIFIED_ROLE_NAME
        
        if not self.ROLE_REQUEST_CHANNEL_ID:
            logger.warning("ROLE_REQUEST_CHANNEL_ID belum diatur. Fitur Role Assigner tidak akan berfungsi.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Cek dasar
        if message.author.bot or not message.guild: return
        if not self.ROLE_REQUEST_CHANNEL_ID or message.channel.id != self.ROLE_REQUEST_CHANNEL_ID: return
        if not message.attachments: return
        
        guild = message.guild
        subscriber_role = discord.utils.get(guild.roles, name=self.SUBSCRIBER_ROLE_NAME)
        follower_role = discord.utils.get(guild.roles, name=self.FOLLOWER_ROLE_NAME)
        forge_verified_role = discord.utils.get(guild.roles, name=self.FORGE_VERIFIED_ROLE_NAME)
        
        if not all([subscriber_role, follower_role, forge_verified_role]):
            logger.error(f"ERROR: Satu atau lebih role ({self.SUBSCRIBER_ROLE_NAME}, {self.FOLLOWER_ROLE_NAME}, {self.FORGE_VERIFIED_ROLE_NAME}) tidak ditemukan.")
            return
        
        roles_to_add = set()
        author_roles = message.author.roles
        
        # Logika Penentuan Role
        if len(message.attachments) >= 2:
            # Jika kirim 2 foto atau lebih, asumsikan Sub + Follow
            roles_to_add.add(subscriber_role)
            roles_to_add.add(follower_role)
        else:
            # Jika kirim 1 foto, cek prioritas
            if subscriber_role not in author_roles:
                # Belum punya sub, kasih sub dulu
                roles_to_add.add(subscriber_role)
            elif follower_role not in author_roles:
                # Sudah punya sub tapi belum follow, kasih follower
                roles_to_add.add(follower_role)
                
        # Cek Role Verified (Gabungan Sub + Follow)
        # Kita cek set role yang akan dimiliki user setelah penambahan ini
        potential_final_roles = set(author_roles).union(roles_to_add)
        
        if subscriber_role in potential_final_roles and follower_role in potential_final_roles:
            roles_to_add.add(forge_verified_role)
            
        # Filter role yang sudah dimiliki agar tidak error/redundant
        final_roles_to_add = [role for role in roles_to_add if role not in author_roles]
        
        if final_roles_to_add:
            try:
                await message.author.add_roles(*final_roles_to_add, reason="Otomatis dari channel request role")
                role_names = ", ".join([f"**{r.name}**" for r in final_roles_to_add])
                
                # Logika Pesan Balasan (Custom Message)
                # Skenario 1: Dapat Verified (Punya Sub & Follow) -> Akses Download
                if forge_verified_role in final_roles_to_add or forge_verified_role in author_roles:
                    reply_msg = (
                        f"✅ Halo {message.author.mention}, Anda telah menerima role: {role_names}!\n"
                        f"Anda bisa Mendownload Filenya di <#1444529534677291100> dan claim token di <#1417335499852353671>!"
                    )
                # Skenario 2: Baru dapat Subscriber saja -> Minta Follow
                elif subscriber_role in final_roles_to_add and follower_role not in potential_final_roles:
                    reply_msg = (
                        f"✅ Halo {message.author.mention}, Anda telah menerima role: **{subscriber_role.name}**.\n"
                        f"⚠️ **Satu langkah lagi!** Silahkan kirim bukti **Follow TikTok kotkaaja** untuk mendapatkan akses download file."
                    )
                # Skenario 3: Fallback (jarang terjadi dengan logika di atas)
                else:
                    reply_msg = f"✅ Halo {message.author.mention}, Anda telah menerima role: {role_names}!"

                await message.reply(reply_msg)
                await message.add_reaction('✅')
                
            except discord.Forbidden: 
                logger.error(f"GAGAL: Bot tidak memiliki izin 'Manage Roles'.")
            except Exception as e: 
                logger.error(f"Terjadi error saat memberikan role: {e}")

async def setup(bot):
    await bot.add_cog(RoleAssignerCog(bot))
