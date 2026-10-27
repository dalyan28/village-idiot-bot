import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import logging
import os
import asyncio

from events import guild_lock

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True


class LockedCommandTree(app_commands.CommandTree):
    """Slash-Commands nur auf erlaubten Servern (siehe events/guild_lock.py)."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if guild_lock.is_allowed(interaction.guild_id):
            return True
        # /botc in den DMs: der Command prüft selbst, auf welchem freigeschalteten Server der User ist
        if interaction.guild_id is None and guild_lock.is_configured():
            return True
        await interaction.response.send_message(
            "Dieser Bot ist auf diesem Server nicht freigeschaltet.", ephemeral=True
        )
        return False


bot = commands.Bot(command_prefix="!", intents=intents, tree_cls=LockedCommandTree)


async def leave_if_not_allowed(guild: discord.Guild):
    if guild_lock.should_leave(guild.id):
        logger.warning(
            "Server nicht in %s, verlasse ihn: %s (ID %s)", guild_lock.ENV_VAR, guild.name, guild.id
        )
        await guild.leave()


async def sync_commands():
    """Commands nur je erlaubtem Server registrieren, globale Commands leeren.

    Ohne ALLOWED_GUILD_IDS wird nichts synchronisiert (der Bot verweigert dann ohnehin alles).
    """
    allowed = guild_lock.allowed_guild_ids()
    if not allowed:
        logger.warning(
            "%s ist nicht gesetzt: Der Bot verweigert alle Interaktionen, Commands werden nicht synchronisiert.",
            guild_lock.ENV_VAR,
        )
        return
    from commands.botc import DM_COMMANDS

    guilds = [discord.Object(id=gid) for gid in allowed]
    # /botc bleibt global (auch in den DMs nutzbar); alles andere nur je Server
    dm_commands = [c for c in bot.tree.get_commands() if c.name in DM_COMMANDS]
    for g in guilds:
        bot.tree.copy_global_to(guild=g)
        for c in dm_commands:
            bot.tree.remove_command(c.name, guild=g)
    bot.tree.clear_commands(guild=None)
    for c in dm_commands:
        bot.tree.add_command(c)
    synced_global = await bot.tree.sync()
    print(f"Synced global (auch DMs): {[c.name for c in synced_global]}")
    for g in guilds:
        try:
            synced = await bot.tree.sync(guild=g)
        except discord.Forbidden:
            # Server steht in der Liste, der Bot ist dort aber (noch) nicht eingeladen
            logger.warning("Commands für Guild %s nicht synchronisiert: Bot ist dort nicht Mitglied", g.id)
            continue
        print(f"Synced commands für Guild {g.id}: {[c.name for c in synced]}")


_synced = False


@bot.event
async def on_ready():
    global _synced
    for guild in list(bot.guilds):
        await leave_if_not_allowed(guild)
    if not _synced:  # on_ready kommt bei jedem Reconnect, synchronisiert wird nur einmal
        await sync_commands()
        _synced = True
    print(f"Bot ist online als {bot.user}")
    from config import cleanup_config
    cleanup_config()
    await asyncio.sleep(3)
    await restore_auto_tasks()


@bot.event
async def on_guild_join(guild: discord.Guild):
    await leave_if_not_allowed(guild)
    # Eingeladen, nachdem der Bot schon lief: Beim Start ging die Registrierung für diesen Server
    # mit „Forbidden“ schief, also die Commands jetzt nachholen.
    if guild_lock.is_allowed(guild.id) and _synced:
        try:
            synced = await bot.tree.sync(guild=guild)
            print(f"Synced commands für neu beigetretene Guild {guild.id}: {[c.name for c in synced]}")
        except discord.HTTPException:
            logger.exception("Commands für Guild %s konnten nicht synchronisiert werden", guild.id)


async def restore_auto_tasks():
    from config import load_config

    cfg = load_config() #Logging
    print(f"Config beim Start: {cfg}") #

    overview_cog = bot.cogs.get("Overview")
    print(f"Overview Cog gefunden: {overview_cog}")
    if not overview_cog:
        return

    cfg = load_config()

    for guild_id_str, guild_cfg in cfg.items():
        # config.json kann Altlasten auf oberster Ebene enthalten (z. B. "auto_interval_hours": 0)
        if not isinstance(guild_cfg, dict) or not guild_id_str.isdigit():
            continue
        if not guild_cfg.get("auto_active"):
            continue

        guild_id = int(guild_id_str)
        # on_ready kommt auch bei jedem Reconnect: läuft der Listen-Modus schon, nicht neu posten
        if guild_id in overview_cog.listening:
            continue
        if not guild_lock.is_allowed(guild_id):
            print(f"Guild {guild_id} ist nicht freigeschaltet, überspringe Automatisierung")
            continue
        event_channel = bot.get_channel(guild_cfg.get("event_channel_id"))
        overview_channel = bot.get_channel(guild_cfg.get("overview_channel_id"))

        if not event_channel or not overview_channel:
            print(f"Channels nicht gefunden für Guild {guild_id}, überspringe")
            continue

        # Früher eingestellte Smart- oder Stunden-Modi laufen jetzt ebenfalls als Listen-Modus
        await overview_cog.start_listening(guild_id, event_channel, overview_channel)
        print(f"Automatisierung wiederhergestellt für Guild {guild_id} (Listen Mode)")


async def main():
    from discord_ui.event_post import EventButton
    from discord_ui.wizard import WizardButton, WizardSelect
    from discord_ui.botc_start import StartButton
    from discord_ui.my_events import LeaveButton
    from discord_ui.conflicts import ChooseButton
    from discord_ui.user_settings import SettingsButton
    from discord_ui.text_edit import TextEditButton
    from events.store import Store

    bot.store = Store()  # SQLite: Events, Entwürfe, Anmeldungen, Server-Einstellungen
    # Buttons und Selects mit ID im custom_id: funktionieren auch nach einem Neustart
    bot.add_dynamic_items(WizardButton, WizardSelect, EventButton, StartButton, LeaveButton, ChooseButton, SettingsButton,
                          TextEditButton)
    async with bot:
        await bot.load_extension("commands.settings")
        await bot.load_extension("commands.overview")
        await bot.load_extension("commands.event_settings")
        await bot.load_extension("commands.botc")
        await bot.load_extension("commands.reminder")
        await bot.load_extension("commands.my_events")
        await bot.load_extension("commands.user_settings")
        await bot.load_extension("commands.script_sheet_pack")  # lädt nur mit SCRIPT_SHEET_UPLOAD=1
        if os.getenv("TEST_SERVER") == "1":  # TESTSERVER
            await bot.load_extension("commands.test_server")  # TESTSERVER
            print("Testserver-Commands geladen")  # TESTSERVER
        await bot.start(os.getenv("DISCORD_TOKEN"))


asyncio.run(main())