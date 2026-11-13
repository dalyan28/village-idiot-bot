import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import asyncio

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)
restored = False


@bot.event
async def on_ready():
    global restored
    await bot.tree.sync()
    print(f"Synced commands: {[c.name for c in bot.tree.get_commands()]}")
    print(f"Bot ist online als {bot.user}")
    # on_ready kommt auch bei jedem Reconnect, neu gepostet wird nur beim Start
    if restored:
        return
    restored = True
    from config import cleanup_config
    cleanup_config()
    await asyncio.sleep(3)
    await restore_auto_tasks()


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
        # alte Keys auf oberster Ebene (z.B. "auto_interval_hours": 0) überspringen
        if not isinstance(guild_cfg, dict) or not guild_cfg.get("auto_active"):
            continue

        guild_id = int(guild_id_str)
        event_channel = bot.get_channel(guild_cfg.get("event_channel_id"))
        overview_channel = bot.get_channel(guild_cfg.get("overview_channel_id"))

        if not event_channel or not overview_channel:
            print(f"Channels nicht gefunden für Guild {guild_id}, überspringe")
            continue

        task = asyncio.create_task(
            overview_cog._run_smart_scheduler(guild_id, event_channel, overview_channel)
        )
        overview_cog.auto_tasks[guild_id] = task
        print(f"Automatisierung wiederhergestellt für Guild {guild_id} (Smart Mode)")


async def main():
    async with bot:
        await bot.load_extension("commands.settings")
        await bot.load_extension("commands.overview")
        await bot.load_extension("commands.aaron")
        await bot.load_extension("commands.mini_wochenplan")
        if os.getenv("ENV") == "dev":
            await bot.load_extension("commands.test_commands")
            print("Dev-Modus: Test-Commands geladen")
        await bot.start(os.getenv("DISCORD_TOKEN"))


asyncio.run(main())