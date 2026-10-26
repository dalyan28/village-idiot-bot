"""/einstellungen: eigene Einstellungen, zuerst die Standardwerte für neue Events (Dalyan, 26.10.2026)."""

import discord
from discord import app_commands
from discord.ext import commands

from discord_ui.user_settings import overview_layout


class UserSettings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="einstellungen", description="Deine Einstellungen, z. B. Standardwerte für neue Events")
    @app_commands.guild_only()
    async def einstellungen(self, interaction: discord.Interaction):
        await interaction.response.send_message(view=overview_layout(interaction.guild), ephemeral=True)


async def setup(bot):
    await bot.add_cog(UserSettings(bot))
