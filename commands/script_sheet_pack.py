"""/skriptblatt_paket: Asset-Paket fürs Skript-Blatt per ZIP hochladen (Dalyan, 27.10.2026).

Nur in den DMs und nur für den Besitzer der Bot-Anwendung. Zusätzlich muss die Umgebungsvariable
SCRIPT_SHEET_UPLOAD=1 gesetzt sein, sonst wird der Befehl gar nicht geladen: Für den Upload kurz einschalten,
danach wieder entfernen. So bleibt der Befehl zu, selbst wenn jemand Zugriff auf das Besitzer-Konto bekäme.
"""

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

ENV_VAR = "SCRIPT_SHEET_UPLOAD"
COMMAND_NAME = "skriptblatt_paket"


def upload_enabled() -> bool:
    return os.getenv(ENV_VAR, "").strip().lower() in ("1", "true", "ja", "yes")


class ScriptSheetPack(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name=COMMAND_NAME, description="Asset-Paket fürs Skript-Blatt hochladen (nur Bot-Besitzer)")
    @app_commands.describe(datei="ZIP von data/script_sheet_assets (mit manifest.json)")
    @app_commands.allowed_contexts(guilds=False, dms=True, private_channels=False)
    @app_commands.allowed_installs(guilds=True, users=False)
    async def skriptblatt_paket(self, interaction: discord.Interaction, datei: discord.Attachment):
        from logic.script_sheet import pack_install

        if not upload_enabled() or not await self.bot.is_owner(interaction.user):
            logger.warning("Paket-Upload abgelehnt für %s (%s)", interaction.user, interaction.user.id)
            await interaction.response.send_message("Das darf nur der Besitzer des Bots.", ephemeral=True)
            return
        if datei.size > pack_install.MAX_ZIP_BYTES:
            await interaction.response.send_message("Die Datei ist größer als 25 MB.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            raw = await datei.read()
            manifest = pack_install.install_pack(raw)
        except pack_install.PackError as e:
            await interaction.followup.send(f"Nicht installiert, das bisherige Paket bleibt. {e}", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.followup.send("Die Datei konnte nicht geladen werden. Versuch es nochmal.",
                                            ephemeral=True)
            return
        logger.info("Asset-Paket installiert: %s Dateien (Version %s)", manifest["installed_files"],
                    manifest.get("version"))
        missing = manifest.get("missing") or []
        text = (f"Asset-Paket installiert: {manifest['installed_files']} Dateien, "
                f"Version {manifest.get('version', '?')}. Neue Skript-Blätter nutzen es ab sofort, bestehende "
                "Posts zeigen es, sobald ihr Bild neu erzeugt wird.")
        if missing:
            text += f"\nLaut Manifest fehlen {len(missing)} Grafiken, dort gilt der Ersatz ohne Paket."
        text += f"\n-# Denk daran, {ENV_VAR} in Railway wieder zu entfernen."
        await interaction.followup.send(text, ephemeral=True)


async def setup(bot):
    if not upload_enabled():
        return  # Befehl bleibt aus (siehe oben)
    await bot.add_cog(ScriptSheetPack(bot))
