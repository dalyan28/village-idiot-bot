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


@bot.event
async def on_ready():
    import pytesseract
    try:
        print("Tesseract version:", pytesseract.get_tesseract_version())
    except Exception as e:
        print("Tesseract nicht gefunden:", e)

    await bot.tree.sync()
    print(f"Synced commands: {[c.name for c in bot.tree.get_commands()]}")
    print(f"Bot ist online als {bot.user}")
    await restore_auto_tasks()


async def restore_auto_tasks():
    from config import load_config
    from discord.ext import tasks

    cfg = load_config()
    print(f"Config beim Start: {cfg}")

    overview_cog = bot.cogs.get("Overview")
    print(f"Overview Cog gefunden: {overview_cog}")
    if not overview_cog:
        return

    for guild_id_str, guild_cfg in cfg.items():
        if not guild_cfg.get("auto_active"):
            continue

        guild_id = int(guild_id_str)
        event_channel = bot.get_channel(guild_cfg.get("event_channel_id"))
        overview_channel = bot.get_channel(guild_cfg.get("overview_channel_id"))
        frequenz = guild_cfg.get("auto_interval_hours", 2)

        if not event_channel or not overview_channel:
            print(f"Channels nicht gefunden für Guild {guild_id}, überspringe")
            continue

        if frequenz == 0:
            @tasks.loop(seconds=3)
            async def auto_job():
                await overview_cog.fetch_and_post(guild_id, event_channel, overview_channel)
            label = "3 Sekunden (Test)"
        else:
            @tasks.loop(hours=frequenz)
            async def auto_job():
                await overview_cog.fetch_and_post(guild_id, event_channel, overview_channel)
            label = f"{frequenz} Stunden"

        overview_cog.auto_tasks[guild_id] = auto_job
        overview_cog.auto_tasks[guild_id].start()
        print(f"Automatisierung wiederhergestellt für Guild {guild_id} ({label})")

        # einmal direkt aktualisieren mit frischem OCR
        await overview_cog.fetch_and_post(guild_id, event_channel, overview_channel, force_ocr=True)


async def main():
    async with bot:
        await bot.load_extension("commands.settings")
        await bot.load_extension("commands.overview")
        await bot.start(os.getenv("DISCORD_TOKEN"))


asyncio.run(main())