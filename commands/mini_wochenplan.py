import asyncio
from datetime import date, datetime, timedelta
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands
from commands.aaron import split_symbols
from config import get_guild_config, save_guild_config
from logic.parser import BERLIN_TZ, TAGE, parse_events

# temporär, am PC springen links in andere channels nicht mehr (seit 09.11.). ausbauen: siehe readme

INFO = "Das ist der Event-Channel: Hier werden alle Runden angekündigt. Neue Events erstellst du mit `/event_classic`."
LABELS = ["Heute", "Morgen", "Übermorgen"]
DEBOUNCE_SECONDS = 10
MAX_LENGTH = 2000
COUNT_LIMIT = 1000
NO_MENTIONS = discord.AllowedMentions.none()


def _day(e: dict) -> date:
    return datetime.fromtimestamp(e["start_ts"], tz=BERLIN_TZ).date()


def _message_id(e: dict) -> int:
    return int(e["url"].rsplit("/", 1)[1])


def heading(label: str, day: date) -> str:
    return f"**{label} · {TAGE[day.weekday()]}, {day:%d.%m.}**"


def event_line(e: dict) -> str:
    start =datetime.fromtimestamp(e["start_ts"], tz=BERLIN_TZ)
    symbols, text = split_symbols(e["title"])
    prefix = f"{symbols} " if symbols else ""
    return f"`{start:%H:%M}` {prefix}[{text}](<{e['url']}>) **({e['accepted']}/{e['max_players']})**"


def newest_event(events: list[dict], today: date) -> dict | None:
    # zuletzt gepostet, nicht zuletzt startend
    if not events:
        return None
    newest = max(events, key=_message_id)
    return newest if _day(newest) >= today else None


def build_content(events: list[dict], today: date, info: bool = False) -> str:
    groups = []
    for offset, label in enumerate(LABELS):
        day = today + timedelta(days=offset)
        lines = [event_line(e) for e in events if _day(e) == day]
        if lines:
            groups.append([heading(label, day), *lines])

    tail = []
    newest = newest_event(events, today)
    if newest:
        tail.append(f"{heading('Neustes Event', _day(newest))}\n{event_line(newest)}")
    if info:
        tail.append(INFO)

    # zu lang: hinten kürzen
    hidden = 0
    while True:
        body = ["\n".join(g) for g in groups] or ["Keine Runden in den nächsten drei Tagen."]
        if hidden:
            body.append(f"… und {hidden} weitere im Wochenplan")
        content = "\n\n".join(body + tail)
        if len(content) <= MAX_LENGTH or not groups:
            return content
        groups[-1].pop()
        hidden += 1
        if len(groups[-1]) == 1:
            groups.pop()


def missing_permissions(perms: discord.Permissions) -> list[str]:
    needed = [("Kanäle ansehen", perms.view_channel), ("Nachrichten senden", perms.send_messages),
              ("Nachrichtenverlauf anzeigen", perms.read_message_history)]
    return [name for name, ok in needed if not ok]


class MiniWochenplan(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}
        self._debounce_tasks: dict[int, asyncio.Task] = {}
        self._tasks: set[asyncio.Task] = set()
        self.deleted_ids: set[int] = set()

    def _lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _automation_running(self, guild_id: int) -> bool:
        overview = self.bot.get_cog("Overview")
        return overview is not None and guild_id in overview.auto_tasks

    async def _save(self, guild_id: int, **values):
        # warten bis kein wochenplan-update läuft, das speichert am ende seine alte config
        overview = self.bot.get_cog("Overview")
        lock = overview._fetch_locks.setdefault(guild_id, asyncio.Lock()) if overview else asyncio.Lock()
        async with lock:
            cfg = get_guild_config(guild_id)
            cfg.update(values)
            save_guild_config(guild_id, cfg)

    async def _exists(self, channel: discord.TextChannel, message_id: int) -> bool:
        try:
            await channel.fetch_message(message_id)
        except discord.NotFound:
            return False
        return True

    async def _edit(self, channel: discord.TextChannel, message_id: int, content: str, known: dict) -> bool:
        old = known.get(message_id)
        if old is not None and old.content == content:
            return True
        try:
            await channel.get_partial_message(message_id).edit(content=content, allowed_mentions=NO_MENTIONS)
        except discord.NotFound:
            return False
        return True

    async def _delete(self, channel: discord.TextChannel, message_id: int):
        self.deleted_ids.add(message_id)
        try:
            await channel.get_partial_message(message_id).delete()
        except discord.NotFound:
            pass

    async def sync(self, guild_id: int, channel: discord.TextChannel, messages=None, events=None):
        async with self._lock(guild_id):
            try:
                await self._sync(guild_id, channel, messages, events)
            except discord.HTTPException as e:
                print(f"[Mini] Guild {guild_id}: Fehler beim Aktualisieren: {e}")

    async def _sync(self, guild_id: int, channel: discord.TextChannel, messages=None, events=None):
        cfg = get_guild_config(guild_id)
        if not cfg.get("mini_wochenplan") or not self._automation_running(guild_id):
            return
        if channel.id != cfg.get("event_channel_id"):
            return
        if messages is None:
            messages = [msg async for msg in channel.history(limit=100)]
            events = parse_events(messages)

        today = datetime.now(tz=BERLIN_TZ).date()
        known = {m.id: m for m in messages}
        anchor_id = cfg.get("mini_anchor_id")
        bottom_id = cfg.get("mini_bottom_id")

        if anchor_id and not await self._edit(channel, anchor_id, build_content(events, today, info=True), known):
            # anker nicht neu posten, der stünde sonst unten
            print(f"[Mini] Guild {guild_id}: Anker {anchor_id} gelöscht, neuer erst mit /mini_wochenplan an")
            anchor_id = None
            await self._save(guild_id, mini_anchor_id=None)

        mine = {anchor_id, bottom_id} | self.deleted_ids
        after_anchor = [m.id for m in messages if m.id not in mine and m.id > (anchor_id or 0)]
        if not after_anchor:
            if bottom_id:
                await self._delete(channel, bottom_id)
                await self._save(guild_id, mini_bottom_id=None)
            return

        content = build_content(events, today)
        # ids sind zeitlich sortiert, klappt auch mit älterer history
        if bottom_id and max(after_anchor) < bottom_id:
            if await self._edit(channel, bottom_id, content, known):
                return
        elif guild_id in self._debounce_tasks:
            # neu posten macht der debounce, sonst wandert der beitrag doppelt
            return
        elif bottom_id:
            await self._delete(channel, bottom_id)
        new_msg = await channel.send(content, suppress_embeds=True, allowed_mentions=NO_MENTIONS)
        await self._save(guild_id, mini_bottom_id=new_msg.id)

    async def pause(self, guild_id: int):
        cfg = get_guild_config(guild_id)
        channel = self.bot.get_channel(cfg["event_channel_id"]) if cfg.get("event_channel_id") else None
        if not channel:
            return
        async with self._lock(guild_id):
            try:
                await self._pause(guild_id, channel)
            except discord.HTTPException as e:
                print(f"[Mini] Guild {guild_id}: Fehler beim Pausieren: {e}")

    async def _pause(self, guild_id: int, channel: discord.TextChannel):
        cfg = get_guild_config(guild_id)
        anchor_id = cfg.get("mini_anchor_id")
        if anchor_id and not await self._edit(channel, anchor_id, INFO, {}):
            await self._save(guild_id, mini_anchor_id=None)
        if cfg.get("mini_bottom_id"):
            await self._delete(channel, cfg["mini_bottom_id"])
            await self._save(guild_id, mini_bottom_id=None)

    async def _turn_on(self, guild_id: int, channel: discord.TextChannel):
        anchor_id = get_guild_config(guild_id).get("mini_anchor_id")
        if not anchor_id or not await self._exists(channel, anchor_id):
            anchor = await channel.send(INFO, suppress_embeds=True, allowed_mentions=NO_MENTIONS)
            anchor_id = anchor.id
        await self._save(guild_id, mini_wochenplan=True, mini_anchor_id=anchor_id)
        await self._sync(guild_id, channel)

    async def _status(self, guild_id: int, channel: discord.TextChannel) -> str:
        cfg = get_guild_config(guild_id)
        active = cfg.get("mini_wochenplan", False)
        lines = [f"**Mini-Wochenplan:** {'an' if active else 'aus'} in {channel.mention}"]
        if active and not self._automation_running(guild_id):
            lines.append("Die automatische Übersicht läuft nicht, deshalb wird er nicht aktualisiert. Erst `/automate_overview` starten.")

        anchor_id = cfg.get("mini_anchor_id")
        if not anchor_id or not await self._exists(channel, anchor_id):
            lines.append("**Anker:** fehlt. `/mini_wochenplan an` postet einen neuen, der steht dann aber unten.")
            return "\n".join(lines)

        first = [msg async for msg in channel.history(limit=1, oldest_first=True)]
        if first and first[0].id == anchor_id:
            lines.append("**Anker:** ist die erste Nachricht im Channel.")
        else:
            before = len([msg async for msg in channel.history(limit=COUNT_LIMIT, before=discord.Object(id=anchor_id))])
            count = f"{before}+" if before >= COUNT_LIMIT else str(before)
            lines.append(f"**Anker:** Davor stehen noch {count} Nachrichten. Er rückt nach oben, sobald sie gelöscht sind.")
        return "\n".join(lines)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.id == self.bot.user.id:
            return
        guild_id = message.guild.id
        cfg = get_guild_config(guild_id)
        if message.channel.id != cfg.get("event_channel_id"):
            return
        if not cfg.get("mini_wochenplan") or not self._automation_running(guild_id):
            return

        # apollo postet und editiert gleich danach, deshalb debounce
        old = self._debounce_tasks.get(guild_id)
        if old and not old.done():
            old.cancel()
        self._debounce_tasks[guild_id] = self.spawn(self._debounced(guild_id, message.channel))

    async def _debounced(self, guild_id: int, channel: discord.TextChannel):
        await asyncio.sleep(DEBOUNCE_SECONDS)
        # ab hier nicht mehr abbrechbar
        self._debounce_tasks.pop(guild_id, None)
        await self.sync(guild_id, channel)

    @app_commands.command(name="mini_wochenplan", description="Mini-Wochenplan oben und unten im Event-Channel (temporär)")
    @app_commands.describe(aktion="an, aus oder nur den Status anzeigen")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def mini_wochenplan(self, interaction: discord.Interaction, aktion: Literal["an", "aus", "status"]):
        guild_id = interaction.guild_id
        cfg = get_guild_config(guild_id)
        channel = self.bot.get_channel(cfg["event_channel_id"]) if cfg.get("event_channel_id") else None
        if not channel:
            await interaction.response.send_message(
                "Kein Event-Channel gesetzt. Bitte erst `/set_event_channel` nutzen.", ephemeral=True
            )
            return

        missing = missing_permissions(channel.permissions_for(interaction.guild.me))
        if aktion == "an" and missing:
            await interaction.response.send_message(
                f"Mir fehlen in {channel.mention} diese Rechte: {', '.join(missing)}", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            async with self._lock(guild_id):
                if aktion == "an":
                    await self._turn_on(guild_id, channel)
                elif aktion == "aus":
                    await self._save(guild_id, mini_wochenplan=False)
                    await self._pause(guild_id, channel)
                status = await self._status(guild_id, channel)
        except discord.HTTPException as e:
            await interaction.followup.send(f"Das hat nicht geklappt: {e}", ephemeral=True)
            return
        await interaction.followup.send(status, ephemeral=True)


# hooks für overview.py
def overview_updated(bot, guild_id: int, event_channel, messages: list, events: list[dict]):
    cog = bot.get_cog("MiniWochenplan")
    if isinstance(cog, MiniWochenplan):
        cog.spawn(cog.sync(guild_id, event_channel, messages, events))


def overview_stopped(bot, guild_id: int):
    cog = bot.get_cog("MiniWochenplan")
    if isinstance(cog, MiniWochenplan) and get_guild_config(guild_id).get("mini_wochenplan"):
        cog.spawn(cog.pause(guild_id))


def is_own_delete(bot, message_id: int) -> bool:
    cog = bot.get_cog("MiniWochenplan")
    return isinstance(cog, MiniWochenplan) and message_id in cog.deleted_ids


async def setup(bot):
    await bot.add_cog(MiniWochenplan(bot))
