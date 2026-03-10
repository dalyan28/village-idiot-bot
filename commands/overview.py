import discord
from discord import app_commands
from discord.ext import commands, tasks
from config import load_config, save_config
from logic.parser import parse_events, build_overview


class Overview(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_task = None

    async def fetch_and_post(self, target_channel: discord.TextChannel):
        cfg = load_config()
        event_channel_id = cfg.get("event_channel_id")

        if not event_channel_id:
            await target_channel.send("Kein Event-Channel gesetzt. Bitte erst `/set_event_channel` nutzen.")
            return

        event_channel = self.bot.get_channel(event_channel_id)
        if not event_channel:
            await target_channel.send("Event-Channel nicht gefunden.")
            return

        messages = [msg async for msg in event_channel.history(limit=100)]
        events = parse_events(messages)
        embed = build_overview(events)

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

    @app_commands.command(name="overview_events", description="Erstellt eine Übersicht der Events")
    async def overview_events(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        cfg = load_config()

        if channel is None:
            overview_id = cfg.get("overview_channel_id")
            channel = self.bot.get_channel(overview_id) if overview_id else interaction.channel

        await interaction.response.send_message(f"Erstelle Übersicht in {channel.mention}...", ephemeral=True)
        await self.fetch_and_post(channel)

    @app_commands.command(name="automate_overview", description="Automatisiert die Übersicht in einem Intervall")
    @app_commands.choices(frequenz=[
        app_commands.Choice(name="3 Sekunden (Test)", value=0),
        app_commands.Choice(name="2 Stunden",          value=2),
        app_commands.Choice(name="4 Stunden",          value=4),
        app_commands.Choice(name="8 Stunden",          value=8),
        app_commands.Choice(name="12 Stunden",         value=12),
        app_commands.Choice(name="24 Stunden",         value=24),
    ])
    async def automate_overview(self, interaction: discord.Interaction, frequenz: int):
        cfg = load_config()
        overview_id = cfg.get("overview_channel_id")
        target = self.bot.get_channel(overview_id) if overview_id else interaction.channel

        # Alten Task stoppen falls aktiv
        if self.auto_task and self.auto_task.is_running():
            self.auto_task.stop()

        # 0 = Testmodus mit 30 Sekunden
        if frequenz == 0:
            @tasks.loop(seconds=3)
            async def auto_job():
                await self.fetch_and_post(target)
            label = "30 Sekunden (Test)"
        else:
            @tasks.loop(hours=frequenz)
            async def auto_job():
                await self.fetch_and_post(target)
            label = f"{frequenz} Stunden"

        self.auto_task = auto_job
        self.auto_task.start()

        cfg["auto_interval_hours"] = frequenz
        save_config(cfg)

        await interaction.response.send_message(
            f"Automatische Übersicht alle {label} in {target.mention} aktiv.", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Overview(bot))