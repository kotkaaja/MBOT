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
        message_content = message.content.lower()
        author_roles = message.author.roles
        
        if len(message.attachments) >= 2:
            roles_to_add.add(subscriber_role)
            roles_to_add.add(follower_role)
        else:
            has_youtube = "youtube" in message_content
            has_tiktok = "tiktok" in message_content
            if has_youtube or has_tiktok:
                if has_youtube: roles_to_add.add(subscriber_role)
                if has_tiktok: roles_to_add.add(follower_role)
            else:
                if subscriber_role not in author_roles: roles_to_add.add(subscriber_role)
                elif follower_role not in author_roles: roles_to_add.add(follower_role)
                
        potential_final_roles = set(author_roles).union(roles_to_add)
        if subscriber_role in potential_final_roles and follower_role in potential_final_roles:
            roles_to_add.add(forge_verified_role)
            
        final_roles_to_add = [role for role in roles_to_add if role not in author_roles]
        
        if final_roles_to_add:
            try:
                await message.author.add_roles(*final_roles_to_add, reason="Otomatis dari channel request role")
                role_names = ", ".join([f"**{r.name}**" for r in final_roles_to_add])
                
                # Anda bisa mengkustomisasi pesan balasan ini
                await message.reply(f"✅ Halo {message.author.mention}, Anda telah menerima role: {role_names}!, Anda bisa Mendownload Filenya di <#1444529534677291100> dan claim token di <#1417335499852353671>!")
                await message.add_reaction('✅')
            except discord.Forbidden: 
                logger.error(f"GAGAL: Bot tidak memiliki izin 'Manage Roles'.")
            except Exception as e: 
                logger.error(f"Terjadi error saat memberikan role: {e}")

async def setup(bot):
    await bot.add_cog(RoleAssignerCog(bot))
