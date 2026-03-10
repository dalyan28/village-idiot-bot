import discord
from discord.ext import commands
from dotenv import load_dotenv
import os

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Synced commands: {[c.name for c in bot.tree.get_commands()]}")
    print(f"Bot ist online als {bot.user}")

async def main():
    async with bot:
        await bot.load_extension("commands.settings")
        await bot.load_extension("commands.overview")
        await bot.start(os.getenv("DISCORD_TOKEN"))

import asyncio
asyncio.run(main())