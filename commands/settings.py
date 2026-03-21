import logging

import discord
from discord import app_commands
from discord.ext import commands
from config import get_guild_config, save_guild_config

logger = logging.getLogger(__name__)


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

    @app_commands.command(
        name="update",
        description="Aktualisiert die Charakterdatenbank und Icons von der offiziellen BotC-Quelle"
    )
    @app_commands.describe(
        force_icons="Alle Icons neu herunterladen, auch bereits vorhandene (default: nein)"
    )
    async def update(self, interaction: discord.Interaction, force_icons: bool = False):
        # Nur Bot-Owner
        app_info = await self.bot.application_info()
        if interaction.user.id != app_info.owner.id:
            await interaction.response.send_message(
                "Nur der Bot-Owner kann diesen Befehl ausführen.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        from logic.script_cache import update_characters_from_tpi
        result = await update_characters_from_tpi(force_icons=force_icons)

        if result["errors"]:
            error_text = "\n".join(f"• {e}" for e in result["errors"])
            await interaction.followup.send(
                f"⚠️ Update mit Fehlern:\n{error_text}\n\n"
                f"Charaktere: {result['characters_count']}\n"
                f"Neue Icons: {result['new_icons']}\n"
                f"Übersprungen: {result['skipped_icons']}",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"✅ Update erfolgreich!\n"
                f"**Charaktere:** {result['characters_count']}\n"
                f"**Jinxes:** {result.get('jinxes_count', 0)}\n"
                f"**Neue Icons:** {result['new_icons']}\n"
                f"**Übersprungen:** {result['skipped_icons']}",
                ephemeral=True,
            )
            logger.info(
                "/update: %d Charaktere, %d neue Icons",
                result["characters_count"], result["new_icons"],
            )


async def setup(bot):
    await bot.add_cog(Settings(bot))
