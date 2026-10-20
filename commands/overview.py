import asyncio
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from config import get_guild_config, save_guild_config
from events import guild_lock
from logic.parser import parse_events, build_overviews


class Overview(commands.Cog):
    """Übersicht der Events. Automatisch nur im Listen-Modus: aktualisiert, sobald sich im Event-Channel
    etwas tut (neues Event, Bearbeitung, Anmeldung, Löschen), sonst nie."""

    def __init__(self, bot):
        self.bot = bot
        self.listening: set[int] = set()  # Guilds mit aktiver automatischer Übersicht
        self._fetch_locks: dict[int, asyncio.Lock] = {}
        self._edit_debounce_tasks: dict[int, asyncio.Task] = {}
        self._edit_debounce_start: dict[int, float] = {}

    def _own_event(self, msg) -> dict | None:
        """Eigene Event-Posts direkt aus der Datenbank lesen (Embed- und V2-Posts)."""
        from events import service
        from events.store import Store
        from events.templates import full_title

        store = getattr(self.bot, "store", None)
        if not isinstance(store, Store) or self.bot.user is None or msg.author.id != self.bot.user.id:
            return None
        event = store.get_event_by_message(msg.id)
        if event is None or event.data.start is None:
            return None
        return {
            "title": full_title(event.data),
            "start_ts": int(event.data.start.timestamp()),
            "accepted": service.rsvp_lists(store, event).accepted_count,
            "max_players": str(event.data.max_players),
            "url": msg.jump_url,
        }

    async def fetch_and_post(self, guild_id: int, event_channel: discord.TextChannel, target_channel: discord.TextChannel):
        lock = self._fetch_locks.setdefault(guild_id, asyncio.Lock())
        if lock.locked():
            print(f"[fetch_and_post] Guild {guild_id}: Update bereits aktiv, überspringe")
            return
        async with lock:
            await self._fetch_and_post_locked(guild_id, event_channel, target_channel)

    async def _fetch_and_post_locked(self, guild_id: int, event_channel: discord.TextChannel, target_channel: discord.TextChannel):
        messages = [msg async for msg in event_channel.history(limit=100)]
        cfg = get_guild_config(guild_id)

        events = parse_events(messages, self._own_event)
        embeds = build_overviews(events)

        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        embeds[-1].add_field(name="", value=f"-# *Zuletzt aktualisiert <t:{now_ts}:R>*", inline=False)

        # debug
        for embed in embeds:
            print(f"Embed fields: {len(embed.fields)}")
            for field in embed.fields:
                print(f"  Field '{field.name}': {len(field.value)} Zeichen")

        # alte nachrichten löschen
        old_ids = cfg.get("last_overview_message_ids", [])
        print(f"Lösche alte Nachrichten: {old_ids}")
        for msg_id in old_ids:
            try:
                old_msg = await target_channel.fetch_message(msg_id)
                await old_msg.delete()
                print(f"Gelöscht: {msg_id}")
            except discord.NotFound:
                print(f"Nicht gefunden: {msg_id}")
            except Exception as e:
                print(f"Fehler beim Löschen {msg_id}: {e}")

        # neue nachrichten posten
        new_ids = []
        for embed in embeds:
            new_msg = await target_channel.send(embed=embed)
            new_ids.append(new_msg.id)

        cfg["last_overview_message_ids"] = new_ids
        save_guild_config(guild_id, cfg)

    async def edit_overview(self, guild_id: int, event_channel: discord.TextChannel, target_channel: discord.TextChannel):
        lock = self._fetch_locks.setdefault(guild_id, asyncio.Lock())
        if lock.locked():
            print(f"[edit_overview] Guild {guild_id}: Update bereits aktiv, überspringe")
            return
        async with lock:
            await self._edit_overview_locked(guild_id, event_channel, target_channel)

    async def _edit_overview_locked(self, guild_id: int, event_channel: discord.TextChannel, target_channel: discord.TextChannel):
        messages = [msg async for msg in event_channel.history(limit=100)]
        cfg = get_guild_config(guild_id)

        events = parse_events(messages, self._own_event)
        embeds = build_overviews(events)

        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        embeds[-1].add_field(name="", value=f"-# *Zuletzt aktualisiert <t:{now_ts}:R>*", inline=False)

        old_ids = cfg.get("last_overview_message_ids", [])
        new_count = len(embeds)
        old_count = len(old_ids)

        new_ids = []

        for i in range(min(old_count, new_count)):
            try:
                msg = await target_channel.fetch_message(old_ids[i])
                await msg.edit(embed=embeds[i])
                new_ids.append(msg.id)
            except discord.NotFound:
                new_msg = await target_channel.send(embed=embeds[i])
                new_ids.append(new_msg.id)
            except discord.HTTPException as e:
                print(f"[edit_overview] Fehler beim Editieren {old_ids[i]}: {e}")
                new_msg = await target_channel.send(embed=embeds[i])
                new_ids.append(new_msg.id)

        for i in range(old_count, new_count):
            new_msg = await target_channel.send(embed=embeds[i])
            new_ids.append(new_msg.id)

        for i in range(new_count, old_count):
            try:
                old_msg = await target_channel.fetch_message(old_ids[i])
                await old_msg.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException as e:
                print(f"[edit_overview] Fehler beim Löschen {old_ids[i]}: {e}")

        cfg["last_overview_message_ids"] = new_ids
        save_guild_config(guild_id, cfg)

    async def _schedule_edit(self, guild_id: int, event_channel: discord.TextChannel, overview_channel: discord.TextChannel):
        now = asyncio.get_event_loop().time()

        if guild_id not in self._edit_debounce_start:
            self._edit_debounce_start[guild_id] = now

        old = self._edit_debounce_tasks.get(guild_id)
        if old and not old.done():
            old.cancel()

        elapsed = now - self._edit_debounce_start[guild_id]
        wait = max(0, min(5, 15 - elapsed))

        async def _debounced():
            await asyncio.sleep(wait)
            self._edit_debounce_start.pop(guild_id, None)
            await self.edit_overview(guild_id, event_channel, overview_channel)

        self._edit_debounce_tasks[guild_id] = asyncio.create_task(_debounced())

    def resolve_channels(self, guild_id: int, cfg: dict, event_channel=None, overview_channel=None):
        resolved_event = event_channel or (
            self.bot.get_channel(cfg["event_channel_id"]) if cfg.get("event_channel_id") else None
        )
        resolved_overview = overview_channel or (
            self.bot.get_channel(cfg["overview_channel_id"]) if cfg.get("overview_channel_id") else None
        )
        return resolved_event, resolved_overview

    async def start_listening(self, guild_id: int, event_channel: discord.TextChannel,
                              overview_channel: discord.TextChannel) -> None:
        """Listen-Modus einschalten (auch über Neustarts) und die Übersicht einmal frisch posten."""
        cfg = get_guild_config(guild_id)
        cfg["auto_active"] = True
        save_guild_config(guild_id, cfg)
        self.listening.add(guild_id)
        await self.fetch_and_post(guild_id, event_channel, overview_channel)

    def stop_listening(self, guild_id: int) -> bool:
        """Listen-Modus aus. False, wenn er gar nicht lief."""
        was_on = guild_id in self.listening
        self.listening.discard(guild_id)
        debounce = self._edit_debounce_tasks.pop(guild_id, None)
        if debounce and not debounce.done():
            debounce.cancel()
        self._edit_debounce_start.pop(guild_id, None)
        cfg = get_guild_config(guild_id)
        if cfg.get("auto_active"):
            cfg["auto_active"] = False
            save_guild_config(guild_id, cfg)
        return was_on

    def _channels_if_listening(self, guild_id: int | None, channel_id: int):
        """(Event-Channel, Übersichts-Channel), wenn die Nachricht den Listen-Modus betrifft, sonst None."""
        if not guild_id or guild_id not in self.listening or not guild_lock.is_allowed(guild_id):
            return None
        cfg = get_guild_config(guild_id)
        if channel_id != cfg.get("event_channel_id"):
            return None
        event_channel, overview_channel = self.resolve_channels(guild_id, cfg)
        if not event_channel or not overview_channel:
            return None
        return event_channel, overview_channel

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.author.bot or not message.guild:
            return
        channels = self._channels_if_listening(message.guild.id, message.channel.id)
        if channels is None:
            return

        # Nur echte Events abfangen: Bot-Nachricht mit Embed das ein Time/Termin-Feld hat
        if not message.embeds:
            return
        embed = message.embeds[0]
        if not embed.title or not embed.fields:
            return
        if not any(f.name in ("Time", "Termin") for f in embed.fields):
            return

        # Neues Event: Übersicht neu posten, damit sie unten im Channel steht
        await self.fetch_and_post(message.guild.id, *channels)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        channels = self._channels_if_listening(payload.guild_id, payload.channel_id)
        if channels is None:
            return
        print(f"[Delete] Nachricht in Event-Channel gelöscht, aktualisiere Übersicht...")
        await self._schedule_edit(payload.guild_id, *channels)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        channels = self._channels_if_listening(payload.guild_id, payload.channel_id)
        if channels is None:
            return

        embeds_data = payload.data.get("embeds", [])
        if not embeds_data:
            return
        fields = embeds_data[0].get("fields", [])
        if not fields:
            return
        if not any(f.get("name") in ("Time", "Termin") for f in fields):
            return

        print(f"[Edit] Event in Event-Channel editiert, aktualisiere Übersicht...")
        await self._schedule_edit(payload.guild_id, *channels)

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
                "Es ist kein Event-Channel gesetzt. Bitte zuerst `/set_event_channel` nutzen.", ephemeral=True
            )
            return

        await interaction.response.send_message(f"Die Übersicht wird in {channel.mention} erstellt.", ephemeral=True)
        await self.fetch_and_post(interaction.guild_id, event_channel, channel)

    @app_commands.command(name="automate_overview",
                          description="Hält die Übersicht automatisch aktuell, sobald sich bei den Events etwas tut")
    async def automate_overview(
        self,
        interaction: discord.Interaction,
        event_channel: discord.TextChannel = None,
        overview_channel: discord.TextChannel = None,
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

        # Angegebene Channel merken, damit die Listener und der Neustart dieselben nutzen
        cfg["event_channel_id"] = resolved_event.id
        cfg["overview_channel_id"] = resolved_overview.id
        save_guild_config(guild_id, cfg)

        await interaction.response.send_message(
            f"Automatische Übersicht aktiv: Sie aktualisiert sich, sobald sich bei den Events etwas tut.\n"
            f"Events aus: {resolved_event.mention} -> Übersicht in: {resolved_overview.mention}",
            ephemeral=True
        )
        await self.start_listening(guild_id, resolved_event, resolved_overview)

    @app_commands.command(name="stop_automate", description="Stoppt die automatische Übersicht")
    async def stop_automate(self, interaction: discord.Interaction):
        if self.stop_listening(interaction.guild_id):
            await interaction.response.send_message("Automatische Übersicht gestoppt.", ephemeral=True)
        else:
            await interaction.response.send_message("Es läuft gerade keine automatische Übersicht.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Overview(bot))