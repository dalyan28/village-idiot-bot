import discord
from discord import app_commands
from discord.ext import commands
from config import get_guild_config, save_guild_config


class Settings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="set_event_channel", description="Setzt den Channel, aus dem Events ausgelesen werden")
    async def set_event_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = get_guild_config(interaction.guild_id)
        cfg["event_channel_id"] = channel.id
        save_guild_config(interaction.guild_id, cfg)
        await interaction.response.send_message(f"Event-Channel gesetzt: {channel.mention}", ephemeral=True)

    @app_commands.command(name="set_overview_channel", description="Setzt den Channel, in dem Übersichten gepostet werden")
    async def set_overview_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = get_guild_config(interaction.guild_id)
        cfg["overview_channel_id"] = channel.id
        save_guild_config(interaction.guild_id, cfg)
        await interaction.response.send_message(f"Übersichts-Channel gesetzt: {channel.mention}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Settings(bot))