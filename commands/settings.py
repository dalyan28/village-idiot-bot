import discord
from discord import app_commands
from discord.ext import commands
from config import load_config, save_config


class Settings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="set_event_channel", description="Setzt den Channel, aus dem Events ausgelesen werden")
    async def set_event_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_config()
        cfg["event_channel_id"] = channel.id
        save_config(cfg)
        await interaction.response.send_message(f"Event-Channel gesetzt: {channel.mention}", ephemeral=True)

    @app_commands.command(name="set_overview_channel", description="Setzt den Channel, in dem Übersichten gepostet werden")
    async def set_overview_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_config()
        cfg["overview_channel_id"] = channel.id
        save_config(cfg)
        await interaction.response.send_message(f"Übersichts-Channel gesetzt: {channel.mention}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Settings(bot))