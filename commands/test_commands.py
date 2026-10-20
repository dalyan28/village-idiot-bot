"""
Dev-only Test-Commands für den VillageIdiot Bot.
Werden nur geladen wenn ENV=dev gesetzt ist (siehe bot.py).

Befehle:
    /create_test_event  – Postet ein Mock-Apollo-Event im Event-Channel
    /clear_test_events  – Löscht alle Test-Events aus dem Event-Channel
"""
import time as time_module
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from config import get_guild_config

BERLIN_TZ = ZoneInfo("Europe/Berlin")
TEST_MARKER = "[TEST]"  # Marker im Embed-Titel für Test-Events


class TestCommands(commands.Cog):
    __test__ = False  # Discord-Cog, kein pytest-Testfall

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="create_test_event",
        description="[DEV] Erstellt ein Mock-Event im Event-Channel"
    )
    @app_commands.describe(
        minutes_from_now="Startzeit in X Minuten (default: 60)",
        title="Titel des Test-Events (default: 'Test Event')",
    )
    async def create_test_event(
        self,
        interaction: discord.Interaction,
        minutes_from_now: int = 60,
        title: str = "Test Event",
    ):
        cfg = get_guild_config(interaction.guild_id)
        event_channel_id = cfg.get("event_channel_id")
        event_channel = self.bot.get_channel(event_channel_id) if event_channel_id else None

        if not event_channel:
            await interaction.response.send_message(
                "Kein Event-Channel gesetzt (`/set_event_channel` nutzen).", ephemeral=True
            )
            return

        start_ts = int(time_module.time()) + minutes_from_now * 60
        start_dt = datetime.fromtimestamp(start_ts, tz=BERLIN_TZ)

        embed = discord.Embed(
            title=f"{TEST_MARKER} {title}",
            color=0xFFA500,
        )
        embed.add_field(
            name="Time",
            value=f"<t:{start_ts}:F> – <t:{start_ts}:R>",
            inline=False,
        )
        embed.add_field(
            name="Accepted (0/10)",
            value="Keine Anmeldungen",
            inline=False,
        )
        embed.set_footer(text="⚠️ Dies ist ein Test-Event und kann mit /clear_test_events gelöscht werden.")

        await event_channel.send(embed=embed)
        await interaction.response.send_message(
            f"Test-Event erstellt: **{title}** – Start um {start_dt.strftime('%H:%M')} Uhr "
            f"({minutes_from_now} Min ab jetzt) in {event_channel.mention}",
            ephemeral=True,
        )

    @app_commands.command(
        name="clear_test_events",
        description="[DEV] Löscht alle Test-Events aus dem Event-Channel"
    )
    async def clear_test_events(self, interaction: discord.Interaction):
        cfg = get_guild_config(interaction.guild_id)
        event_channel_id = cfg.get("event_channel_id")
        event_channel = self.bot.get_channel(event_channel_id) if event_channel_id else None

        if not event_channel:
            await interaction.response.send_message(
                "Kein Event-Channel gesetzt.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        deleted = 0
        async for msg in event_channel.history(limit=100):
            if not msg.author.bot or not msg.embeds:
                continue
            if msg.embeds[0].title and TEST_MARKER in msg.embeds[0].title:
                try:
                    await msg.delete()
                    deleted += 1
                except discord.NotFound:
                    pass

        await interaction.followup.send(
            f"{deleted} Test-Event(s) gelöscht.", ephemeral=True
        )

    @app_commands.command(
        name="clear_past_events",
        description="[DEV] Löscht alle Events aus dem Event-Channel, deren Startzeit in der Vergangenheit liegt"
    )
    async def clear_past_events(self, interaction: discord.Interaction):
        cfg = get_guild_config(interaction.guild_id)
        event_channel_id = cfg.get("event_channel_id")
        event_channel = self.bot.get_channel(event_channel_id) if event_channel_id else None

        if not event_channel:
            await interaction.response.send_message(
                "Kein Event-Channel gesetzt.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        import re
        now_ts = time_module.time()
        deleted = 0

        async for msg in event_channel.history(limit=200):
            if not msg.author.bot or not msg.embeds:
                continue
            embed = msg.embeds[0]
            if not embed.title or not embed.fields:
                continue
            time_field = next((f for f in embed.fields if f.name in ("Time", "Termin")), None)
            if not time_field:
                continue
            timestamps = re.findall(r"<t:(\d+):[FtTdDfR]>", time_field.value)
            if not timestamps:
                continue
            if int(timestamps[0]) < now_ts:
                try:
                    await msg.delete()
                    deleted += 1
                except discord.NotFound:
                    pass

        await interaction.followup.send(
            f"{deleted} vergangene(s) Event(s) gelöscht.", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(TestCommands(bot))
