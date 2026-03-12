import discord
from discord import app_commands
from discord.ext import commands, tasks
from config import get_guild_config, save_guild_config
from logic.parser import parse_events, build_overview


class Overview(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_tasks: dict[int, tasks.Loop] = {}

    async def fetch_and_post(self, guild_id: int, event_channel: discord.TextChannel, target_channel: discord.TextChannel):
        messages = [msg async for msg in event_channel.history(limit=100)]
        events = parse_events(messages)
        embed = build_overview(events)

        cfg = get_guild_config(guild_id)

        last_id = cfg.get("last_overview_message_id")
        if last_id:
            try:
                old_msg = await target_channel.fetch_message(last_id)
                await old_msg.delete()
            except discord.NotFound:
                pass

        new_msg = await target_channel.send(embed=embed)
        cfg["last_overview_message_id"] = new_msg.id
        save_guild_config(guild_id, cfg)

    def resolve_channels(self, guild_id: int, cfg: dict, event_channel=None, overview_channel=None):
        resolved_event = event_channel or (
            self.bot.get_channel(cfg["event_channel_id"]) if cfg.get("event_channel_id") else None
        )
        resolved_overview = overview_channel or (
            self.bot.get_channel(cfg["overview_channel_id"]) if cfg.get("overview_channel_id") else None
        )
        return resolved_event, resolved_overview

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.author.bot or not message.guild:
            return

        cfg = get_guild_config(message.guild.id)

        # nur reagieren wenn on_new_event aktiv und eine Automatisierung läuft
        if not cfg.get("on_new_event", False):
            return
        if message.guild.id not in self.auto_tasks:
            return
        if message.channel.id != cfg.get("event_channel_id"):
            return

        overview_id = cfg.get("overview_channel_id")
        overview_channel = self.bot.get_channel(overview_id) if overview_id else None
        if overview_channel:
            await self.fetch_and_post(message.guild.id, message.channel, overview_channel)

    @app_commands.command(name="overview_events", description="Erstellt eine Übersicht der Events")
    async def overview_events(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        cfg = get_guild_config(interaction.guild_id)

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
        await self.fetch_and_post(interaction.guild_id, event_channel, channel)

    @app_commands.command(name="automate_overview", description="Automatisiert die Übersicht in einem Intervall")
    @app_commands.choices(frequenz=[
        app_commands.Choice(name="3 Sekunden (Test)", value=0),
        app_commands.Choice(name="2 Stunden",         value=2),
        app_commands.Choice(name="4 Stunden",         value=4),
        app_commands.Choice(name="8 Stunden",         value=8),
        app_commands.Choice(name="12 Stunden",        value=12),
        app_commands.Choice(name="24 Stunden",        value=24),
    ])
    async def automate_overview(
        self,
        interaction: discord.Interaction,
        frequenz: int,
        event_channel: discord.TextChannel = None,
        overview_channel: discord.TextChannel = None,
        on_new_event: bool = True
    ):
        guild_id = interaction.guild_id
        cfg = get_guild_config(guild_id)
        resolved_event, resolved_overview = self.resolve_channels(guild_id, cfg, event_channel, overview_channel)

        missing = []
        if not resolved_event:
            missing.append("`event_channel` (oder `/set_event_channel` nutzen)")
        if not resolved_overview:
            missing.append("`overview_channel` (oder `/set_overview_channel` nutzen)")

        if missing:
            await interaction.response.send_message(
                "Folgende Channel fehlen noch:\n" + "\n".join(f"- {m}" for m in missing),
                ephemeral=True
            )
            return

        if guild_id in self.auto_tasks and self.auto_tasks[guild_id].is_running():
            self.auto_tasks[guild_id].stop()

        if frequenz == 0:
            @tasks.loop(seconds=3)
            async def auto_job():
                await self.fetch_and_post(guild_id, resolved_event, resolved_overview)
            label = "3 Sekunden (Test)"
        else:
            @tasks.loop(hours=frequenz)
            async def auto_job():
                await self.fetch_and_post(guild_id, resolved_event, resolved_overview)
            label = f"{frequenz} Stunden"

        self.auto_tasks[guild_id] = auto_job
        self.auto_tasks[guild_id].start()

        cfg["auto_interval_hours"] = frequenz
        cfg["on_new_event"] = on_new_event
        save_guild_config(guild_id, cfg)

        on_new_event_label = "aktiv" if on_new_event else "inaktiv"
        await interaction.response.send_message(
            f"Automatische Übersicht alle {label}.\n"
            f"Events aus: {resolved_event.mention} -> Übersicht in: {resolved_overview.mention}\n"
            f"Aktualisierung bei neuem Event: {on_new_event_label}",
            ephemeral=True
        )

    @app_commands.command(name="stop_automate", description="Stoppt alle laufenden automatischen Übersichten")
    async def stop_automate(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        if guild_id in self.auto_tasks and self.auto_tasks[guild_id].is_running():
            self.auto_tasks[guild_id].stop()
            del self.auto_tasks[guild_id]
            await interaction.response.send_message("Automatische Übersicht gestoppt.", ephemeral=True)
        else:
            await interaction.response.send_message("Es läuft gerade keine automatische Übersicht.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Overview(bot))