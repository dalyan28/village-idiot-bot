"""/meine_events: eigene Anmeldungen ansehen und sich abmelden (Dalyan, 26.10.2026)."""

import discord
from discord import app_commands
from discord.ext import commands

from discord_ui.my_events import my_events_layout


class MyEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="meine_events", description="Zeigt, wofür du angemeldet bist, und lässt dich abmelden")
    @app_commands.guild_only()
    async def meine_events(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            view=my_events_layout(self.bot.store, interaction.guild, interaction.user.id), ephemeral=True)


async def setup(bot):
    await bot.add_cog(MyEvents(bot))
