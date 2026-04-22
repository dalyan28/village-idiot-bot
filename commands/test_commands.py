"""
Dev-only Test-Commands für den VillageIdiot Bot.
Werden nur geladen wenn ENV=dev gesetzt ist (siehe bot.py).

Befehle:
    /create_test_event      – Postet ein Mock-Apollo-Event im Event-Channel
    /clear_test_events      – Löscht alle Test-Events aus dem Event-Channel
    /smart_status           – Zeigt internen Smart-Mode-Zustand (Locks, Dynamic Times, Last Run)
    /create_event           – Erstellt ein Event-Embed mit RSVP-Buttons (Test für Event-System)
    /delete_last_dm         – Löscht die zuletzt gesendete Bot-DM im aktuellen Private-Chat
"""
import time as time_module
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from config import get_guild_config

BERLIN_TZ = ZoneInfo("Europe/Berlin")

# Termin-Formate für /create_event
_TIME_FORMATS = [
    "%d.%m.%Y %H:%M",
    "%Y-%m-%d %H:%M",
    "%d.%m. %H:%M",
]
TEST_MARKER = "[TEST]"  # Marker im Embed-Titel für Test-Events


class TestCommands(commands.Cog):
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

    @app_commands.command(
        name="create_event",
        description="[DEV] Erstellt ein Event-Embed mit RSVP-Buttons im Event-Channel"
    )
    @app_commands.describe(
        title="Titel des Events",
        storyteller="Name der Storyteller:in",
        script="Name des BotC-Skripts",
        level="Schwierigkeitsgrad",
        termin="Startzeit, z.B. '25.03.2026 20:00' oder '2026-03-25 20:00'",
        dauer_stunden="Dauer in Stunden (default: 3)",
        description="Optionale Beschreibung",
        zusatzinfo="Optionale weitere Informationen",
    )
    @app_commands.choices(level=[
        app_commands.Choice(name="Neuling", value="Neuling"),
        app_commands.Choice(name="Erfahren", value="Erfahren"),
        app_commands.Choice(name="Profi", value="Profi"),
        app_commands.Choice(name="Alle", value="Alle"),
    ])
    async def create_event(
        self,
        interaction: discord.Interaction,
        title: str,
        storyteller: str,
        script: str,
        level: app_commands.Choice[str],
        termin: str,
        dauer_stunden: float = 3.0,
        description: str = None,
        zusatzinfo: str = None,
    ):
        cfg = get_guild_config(interaction.guild_id)
        event_channel_id = cfg.get("event_channel_id")
        event_channel = self.bot.get_channel(event_channel_id) if event_channel_id else None

        if not event_channel:
            await interaction.response.send_message(
                "Kein Event-Channel gesetzt (`/set_event_channel` nutzen).", ephemeral=True
            )
            return

        # Termin parsen
        parsed_dt = None
        for fmt in _TIME_FORMATS:
            try:
                parsed_dt = datetime.strptime(termin, fmt)
                if fmt == "%d.%m. %H:%M":
                    parsed_dt = parsed_dt.replace(year=datetime.now().year)
                break
            except ValueError:
                continue

        if parsed_dt is None:
            await interaction.response.send_message(
                "Ungültiges Termin-Format. Beispiele:\n"
                "• `25.03.2026 20:00`\n"
                "• `2026-03-25 20:00`\n"
                "• `25.03. 20:00` (aktuelles Jahr)",
                ephemeral=True,
            )
            return

        parsed_dt = parsed_dt.replace(tzinfo=BERLIN_TZ)
        start_ts = int(parsed_dt.timestamp())
        end_ts = int((parsed_dt + timedelta(hours=dauer_stunden)).timestamp())

        event_data = {
            "title": title,
            "description": description,
            "storyteller": storyteller,
            "script": script,
            "level": level.value,
            "timestamp": start_ts,
            "end_timestamp": end_ts,
            "additional_info": zusatzinfo,
            "creator_id": interaction.user.id,
            "creator_name": interaction.user.display_name,
        }

        event_cog = self.bot.cogs.get("EventCommands")
        if not event_cog:
            await interaction.response.send_message("EventCommands-Cog nicht geladen.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        msg = await event_cog.post_event(event_channel, event_data)
        await interaction.followup.send(
            f"Event erstellt: **{title}** in {event_channel.mention}\n{msg.jump_url}",
            ephemeral=True,
        )

    @app_commands.command(
        name="smart_status",
        description="[DEV] Zeigt den internen Smart-Mode-Zustand"
    )
    async def smart_status(self, interaction: discord.Interaction):
        overview_cog = self.bot.cogs.get("Overview")
        if not overview_cog:
            await interaction.response.send_message("Overview-Cog nicht gefunden.", ephemeral=True)
            return

        guild_id = interaction.guild_id

        # Task-Status
        task = overview_cog.auto_tasks.get(guild_id)
        import asyncio
        if isinstance(task, asyncio.Task):
            task_status = f"asyncio.Task – {'läuft' if not task.done() else 'beendet'}"
        elif task is not None:
            task_status = f"tasks.Loop – {'läuft' if task.is_running() else 'gestoppt'}"
        else:
            task_status = "kein Task aktiv"

        # Lock-Status
        lock = overview_cog._fetch_locks.get(guild_id)
        lock_status = "gesperrt" if (lock and lock.locked()) else "frei"

        # Dynamic Times
        dynamic = overview_cog.smart_dynamic_times.get(guild_id, set())
        dynamic_str = (
            ", ".join(f"{h:02d}:{m:02d}" for h, m in sorted(dynamic))
            if dynamic else "keine"
        )

        # Last Run
        last_run = overview_cog.last_smart_run.get(guild_id)
        from datetime import timezone
        if last_run:
            last_run_berlin = last_run.astimezone(BERLIN_TZ)
            seconds_ago = (datetime.now(tz=timezone.utc) - last_run).total_seconds()
            last_run_str = f"{last_run_berlin.strftime('%H:%M:%S')} ({seconds_ago:.0f}s her)"
        else:
            last_run_str = "noch nie"

        lines = [
            "**Smart Mode Debug-Status**",
            f"Task: {task_status}",
            f"Fetch-Lock: {lock_status}",
            f"Dynamische Zeiten heute: {dynamic_str}",
            f"Letzter Update: {last_run_str}",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


    @app_commands.command(
        name="delete_last_dm",
        description="[DEV] Löscht die zuletzt gesendete Bot-DM in diesem Private-Chat",
    )
    @app_commands.allowed_contexts(guilds=False, dms=True, private_channels=False)
    async def delete_last_dm(self, interaction: discord.Interaction):
        # Nur in DMs sinnvoll — in Guild-Channels kann der Bot die ephemeral
        # Response eh nicht als „DM" behandeln.
        if interaction.guild is not None:
            await interaction.response.send_message(
                "Nur in DMs nutzbar. Öffne den Private-Chat mit dem Bot.",
                ephemeral=True,
            )
            return

        # DM-Channel holen — bei DM-Interaktionen ist `interaction.channel`
        # manchmal None bis `create_dm()` gerufen wird.
        channel = interaction.channel or await interaction.user.create_dm()

        await interaction.response.defer(ephemeral=True)

        # Jüngste Bot-Message suchen (History läuft neu → alt).
        target = None
        async for msg in channel.history(limit=50):
            if msg.author.id == self.bot.user.id:
                target = msg
                break

        if target is None:
            await interaction.followup.send(
                "Keine Bot-Nachricht in den letzten 50 gefunden.", ephemeral=True
            )
            return

        try:
            await target.delete()
        except discord.NotFound:
            await interaction.followup.send(
                "Nachricht war schon weg.", ephemeral=True
            )
            return
        except discord.Forbidden:
            await interaction.followup.send(
                "Darf die Nachricht nicht löschen.", ephemeral=True
            )
            return

        await interaction.followup.send(
            f"Letzte Bot-DM gelöscht (ID `{target.id}`).", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(TestCommands(bot))
