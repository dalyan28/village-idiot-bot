import discord
from discord import app_commands
from discord.ext import commands, tasks
from config import load_config, save_config
from logic.parser import parse_events, build_overview


class Overview(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_task = None

    async def fetch_and_post(self, event_channel: discord.TextChannel, target_channel: discord.TextChannel):
        messages = [msg async for msg in event_channel.history(limit=100)]
        events = parse_events(messages)
        embed = build_overview(events)

        cfg = load_config()

        # Alte Übersicht löschen falls vorhanden
        last_id = cfg.get("last_overview_message_id")
        if last_id:
            try:
                old_msg = await target_channel.fetch_message(last_id)
                await old_msg.delete()
            except discord.NotFound:
                pass

        new_msg = await target_channel.send(embed=embed)
        cfg["last_overview_message_id"] = new_msg.id
        save_config(cfg)

    def resolve_channels(self, cfg: dict, event_channel=None, overview_channel=None):
        # Event-Channel: Parameter -> config -> None
        resolved_event = event_channel or (
            self.bot.get_channel(cfg["event_channel_id"]) if cfg.get("event_channel_id") else None
        )
        # Overveiw-Channel: Parameter -> config -> None
        resolved_overview = overview_channel or (
            self.bot.get_channel(cfg["overview_channel_id"]) if cfg.get("overview_channel_id") else None
        )
        return resolved_event, resolved_overview

    @app_commands.command(name="overview_events", description="Erstellt eine Übersicht der Events")
    async def overview_events(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        cfg = load_config()

        if channel is None:
            overview_id = cfg.get("overview_channel_id")
            channel = self.bot.get_channel(overview_id) if overview_id else interaction.channel

        event_channel_id = cfg.get("event_channel_id")
        event_channel = self.bot.get_channel(event_channel_id) if event_channel_id else None

        if not event_channel:
            await interaction.response.send_message(
                "Kein Event-Channel gesetzt. Bitte erst `/set_event_channel` nutzen.", ephemeral=True
            )
            return

        await interaction.response.send_message(f"Erstelle Übersicht in {channel.mention}...", ephemeral=True)
        await self.fetch_and_post(event_channel, channel)

    @app_commands.command(name="automate_overview", description="Automatisiert die Übersicht in einem Intervall")
    @app_commands.choices(frequenz=[
        app_commands.Choice(name="3 Sekunden (Test)", value=0),
        app_commands.Choice(name="2 Stunden",          value=2),
        app_commands.Choice(name="4 Stunden",          value=4),
        app_commands.Choice(name="8 Stunden",          value=8),
        app_commands.Choice(name="12 Stunden",         value=12),
        app_commands.Choice(name="24 Stunden",         value=24),
    ])
    async def automate_overview(
        self,
        interaction: discord.Interaction,
        frequenz: int,
        event_channel: discord.TextChannel = None,
        overview_channel: discord.TextChannel = None
    ):
        cfg = load_config()
        resolved_event, resolved_overview = self.resolve_channels(cfg, event_channel, overview_channel)

        # Fehlermeldung wenn einer der beiden Channel fehlt
        missing = []
        if not resolved_event:
            missing.append("`event_channel` (oder `/set_event_channel` nutzen)")
        if not resolved_overview:
            missing.append("`overview_channel` (oder `/set_overview_channel` nutzen)")

        if missing:
            await interaction.response.send_message(
                f"Folgende Channel fehlen noch:\n" + "\n".join(f"- {m}" for m in missing),
                ephemeral=True
            )
            return

        # Alten Task stoppen falls aktiv
        if self.auto_task and self.auto_task.is_running():
            self.auto_task.stop()

        if frequenz == 0:
            @tasks.loop(seconds=3)
            async def auto_job():
                await self.fetch_and_post(resolved_event, resolved_overview)
            label = "3 Sekunden (Test)"
        else:
            @tasks.loop(hours=frequenz)
            async def auto_job():
                await self.fetch_and_post(resolved_event, resolved_overview)
            label = f"{frequenz} Stunden"

        self.auto_task = auto_job
        self.auto_task.start()

        cfg["auto_interval_hours"] = frequenz
        save_config(cfg)

        await interaction.response.send_message(
            f"Automatische Übersicht alle {label}.\n"
            f"Events aus: {resolved_event.mention} → Übersicht in: {resolved_overview.mention}",
            ephemeral=True
        )
    @app_commands.command(name="stop_automate", description="Stoppt alle laufenden automatischen Übersichten")
    async def stop_automate(self, interaction: discord.Interaction):
            if self.auto_task and self.auto_task.is_running():
                self.auto_task.stop()
                self.auto_task = None
                await interaction.response.send_message("Automatische Übersicht gestoppt.", ephemeral=True)
            else:
                await interaction.response.send_message("Es läuft gerade keine automatische Übersicht.", ephemeral=True) 

async def setup(bot):
    await bot.add_cog(Overview(bot))