"""Tests für den Mini-Wochenplan und seine Hooks in overview.py"""
import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from commands import mini_wochenplan as mini
from commands.mini_wochenplan import INFO, MiniWochenplan, build_content
from commands.overview import Overview
from logic.parser import BERLIN_TZ, parse_events

GUILD = 1
CHANNEL = 10
BOT_ID = 999
TODAY = date(2026, 11, 13)  # Freitag


def _event(title, day, hour, minute=0, msg_id=None, accepted=3):
    ts = int(datetime(2026, 11, day, hour, minute, tzinfo=BERLIN_TZ).timestamp())
    msg_id = msg_id or ts
    return {"title": title, "start_ts": ts, "accepted": accepted, "max_players": "12",
            "url": f"https://discord.com/channels/{GUILD}/{CHANNEL}/{msg_id}"}


def _msg(msg_id, content="", author_id=1):
    return SimpleNamespace(id=msg_id, content=content, embeds=[], author=SimpleNamespace(id=author_id, bot=False))


def _not_found():
    return discord.NotFound(MagicMock(), "not found")


async def _aiter(items):
    for item in items:
        yield item


class FakeChannel:
    def __init__(self, messages=()):
        self.id = CHANNEL
        self.mention = "#events"
        self.messages = list(messages)  # neueste zuerst, wie history()
        self.partials = {}
        self.send = AsyncMock(side_effect=self._send)

    async def _send(self, content, **kwargs):
        new = _msg(max([m.id for m in self.messages] + [10_000]) + 1, content, BOT_ID)
        self.messages.insert(0, new)
        return new

    def get_partial_message(self, message_id):
        return self.partials.setdefault(message_id, SimpleNamespace(edit=AsyncMock(), delete=AsyncMock()))

    def history(self, limit=100, oldest_first=False, before=None):
        msgs = self.messages[::-1] if oldest_first else list(self.messages)
        if before is not None:
            msgs = [m for m in msgs if m.id < before.id]
        return _aiter(msgs[:limit])

    async def fetch_message(self, message_id):
        for m in self.messages:
            if m.id == message_id:
                return m
        raise _not_found()


@pytest.fixture
def store():
    data = {"mini_wochenplan": True, "event_channel_id": CHANNEL}

    def save(_guild_id, cfg):
        data.clear()
        data.update(cfg)

    with patch.object(mini, "get_guild_config", side_effect=lambda _guild_id: dict(data)), \
         patch.object(mini, "save_guild_config", side_effect=save):
        yield data


@pytest.fixture
def overview():
    return SimpleNamespace(auto_tasks={GUILD: object()}, _fetch_locks={})


@pytest.fixture
def cog(overview):
    bot = MagicMock()
    bot.user.id = BOT_ID
    cogs = {"Overview": overview}
    bot.get_cog = lambda name: cogs.get(name)
    c = MiniWochenplan(bot)
    cogs["MiniWochenplan"] = c
    return c


def test_today_tomorrow_day_after():
    events = [
        _event("Gestern", 12, 20, msg_id=1),
        _event("Nachmittag", 13, 14, msg_id=2),
        _event("🟥 Srunde Broken Circles mit Doctor", 13, 20, msg_id=3),
        _event("Trouble Brewing", 14, 19, 30, msg_id=4, accepted=0),
        _event("💚 Boozling", 15, 20, msg_id=6),
        _event("Nächste Woche", 16, 20, msg_id=5),
    ]
    u = {i: f"https://discord.com/channels/{GUILD}/{CHANNEL}/{i}" for i in range(1, 7)}
    assert build_content(events, TODAY) == "\n".join([
        "**Heute · Freitag, 13.11.**",
        f"`14:00` [Nachmittag](<{u[2]}>) **(3/12)**",
        f"`20:00` 🟥 [Srunde Broken Circles mit Doctor](<{u[3]}>) **(3/12)**",
        "",
        "**Morgen · Samstag, 14.11.**",
        f"`19:30` [Trouble Brewing](<{u[4]}>) **(0/12)**",
        "",
        "**Übermorgen · Sonntag, 15.11.**",
        f"`20:00` 💚 [Boozling](<{u[6]}>) **(3/12)**",
        "",
        "**Neustes Event · Sonntag, 15.11.**",
        f"`20:00` 💚 [Boozling](<{u[6]}>) **(3/12)**",
    ])


def test_empty_days_are_left_out():
    content = build_content([_event("A", 15, 20)], TODAY)
    assert content.startswith("**Übermorgen · Sonntag, 15.11.**\n")
    assert "Heute" not in content and "Morgen ·" not in content


def test_no_events():
    assert build_content([], TODAY) == "Keine Runden in den nächsten drei Tagen."
    assert build_content([], TODAY, info=True) == f"Keine Runden in den nächsten drei Tagen.\n\n{INFO}"


def test_days_in_berlin_time():
    # 00:30 Berlin ist in UTC noch der Vortag
    content = build_content([_event("Spät", 14, 0, 30)], TODAY)
    assert content.startswith("**Morgen · Samstag, 14.11.**\n`00:30` ")


def test_newest_event_is_last_posted_not_last_starting():
    events = [_event("Bald", 13, 20, msg_id=50), _event("Später gepostet", 20, 20, msg_id=60)]
    content = build_content(events, TODAY)
    assert content.endswith("**Neustes Event · Freitag, 20.11.**\n"
                            f"`20:00` [Später gepostet](<{events[1]['url']}>) **(3/12)**")


def test_newest_event_in_the_past_is_left_out():
    events = [_event("Heute", 13, 20, msg_id=50), _event("Gestern gepostet", 12, 20, msg_id=60)]
    assert "Neustes Event" not in build_content(events, TODAY)


def test_anchor_has_info_at_the_end():
    content = build_content([_event("A", 13, 20)], TODAY, info=True)
    assert content.endswith(f"\n\n{INFO}")
    assert content.index("Neustes Event") < content.index(INFO)


def test_shortened_at_discord_limit():
    events = [_event(f"Event {i} {'x' * 60}", 13 + i % 3, 20, msg_id=i + 1) for i in range(40)]
    content = build_content(events, TODAY, info=True)
    assert len(content) <= 2000
    assert content.endswith(INFO)
    assert "**Neustes Event" in content
    shown = sum(1 for line in content.split("\n") if line.startswith("`20:00`")) - 1
    hidden = int(content.split("… und ")[1].split(" ")[0])
    assert shown + hidden == 40


def test_mini_post_is_no_event():
    post = SimpleNamespace(author=SimpleNamespace(bot=True), embeds=[], content=build_content([], TODAY))
    assert parse_events([post]) == []


@pytest.mark.asyncio
async def test_bottom_is_last_only_edits(cog, store):
    store.update(mini_anchor_id=100, mini_bottom_id=300)
    ch = FakeChannel([_msg(300, "alt"), _msg(200), _msg(100, "alt")])

    await cog.sync(GUILD, ch, ch.messages, [])

    ch.get_partial_message(100).edit.assert_called_once()
    ch.get_partial_message(300).edit.assert_called_once()
    ch.get_partial_message(300).delete.assert_not_called()
    ch.send.assert_not_called()


@pytest.mark.asyncio
async def test_new_message_moves_bottom_down(cog, store):
    store.update(mini_anchor_id=100, mini_bottom_id=300)
    ch = FakeChannel([_msg(400), _msg(300), _msg(200), _msg(100)])

    await cog.sync(GUILD, ch, list(ch.messages), [])

    ch.get_partial_message(300).delete.assert_called_once()
    ch.send.assert_called_once()
    kwargs = ch.send.call_args.kwargs
    assert kwargs["suppress_embeds"] is True
    assert kwargs["allowed_mentions"].to_dict() == discord.AllowedMentions.none().to_dict()
    assert store["mini_bottom_id"] == ch.messages[0].id
    assert mini.is_own_delete(cog.bot, 300)


@pytest.mark.asyncio
async def test_waiting_debounce_does_the_repost(cog, store):
    store.update(mini_anchor_id=100, mini_bottom_id=300)
    ch = FakeChannel([_msg(400), _msg(300), _msg(100)])
    cog._debounce_tasks[GUILD] = MagicMock()

    await cog.sync(GUILD, ch, ch.messages, [])

    ch.get_partial_message(100).edit.assert_called_once()
    ch.get_partial_message(300).delete.assert_not_called()
    ch.send.assert_not_called()


@pytest.mark.asyncio
async def test_nothing_after_anchor_needs_no_bottom(cog, store):
    store.update(mini_anchor_id=100, mini_bottom_id=300)
    ch = FakeChannel([_msg(300), _msg(100)])

    await cog.sync(GUILD, ch, ch.messages, [])

    ch.get_partial_message(300).delete.assert_called_once()
    assert store["mini_bottom_id"] is None
    ch.send.assert_not_called()


@pytest.mark.asyncio
async def test_messages_before_anchor_need_no_bottom(cog, store):
    store.update(mini_anchor_id=100)
    ch = FakeChannel([_msg(100), _msg(50), _msg(40)])

    await cog.sync(GUILD, ch, ch.messages, [])

    ch.send.assert_not_called()


@pytest.mark.asyncio
async def test_deleted_anchor_is_not_reposted(cog, store):
    store.update(mini_anchor_id=100)
    ch = FakeChannel([_msg(200)])
    ch.get_partial_message(100).edit.side_effect = _not_found()

    await cog.sync(GUILD, ch, ch.messages, [])

    assert store["mini_anchor_id"] is None
    ch.send.assert_called_once()
    assert INFO not in ch.send.call_args.args[0]


@pytest.mark.asyncio
async def test_unchanged_content_is_not_edited(cog, store):
    today = datetime.now(tz=BERLIN_TZ).date()
    store.update(mini_anchor_id=100, mini_bottom_id=300)
    ch = FakeChannel([_msg(300, build_content([], today)), _msg(200), _msg(100, build_content([], today, info=True))])

    await cog.sync(GUILD, ch, ch.messages, [])

    ch.get_partial_message(100).edit.assert_not_called()
    ch.get_partial_message(300).edit.assert_not_called()
    ch.send.assert_not_called()


@pytest.mark.asyncio
async def test_older_history_keeps_new_bottom(cog, store):
    # unterer beitrag wurde nach dem history-abruf neu gepostet
    store.update(mini_anchor_id=100, mini_bottom_id=500)
    ch = FakeChannel([_msg(400), _msg(100)])

    await cog.sync(GUILD, ch, ch.messages, [])

    ch.get_partial_message(500).edit.assert_called_once()
    ch.send.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["switch_off", "automation_off", "other_channel"])
async def test_inactive_does_nothing(cog, store, overview, change):
    store.update(mini_anchor_id=100)
    if change == "switch_off":
        store["mini_wochenplan"] = False
    elif change == "automation_off":
        overview.auto_tasks.clear()
    else:
        store["event_channel_id"] = 11
    ch = FakeChannel([_msg(200), _msg(100)])

    await cog.sync(GUILD, ch, ch.messages, [])

    ch.get_partial_message(100).edit.assert_not_called()
    ch.send.assert_not_called()


@pytest.mark.asyncio
async def test_loads_history_itself_without_overview(cog, store):
    store.update(mini_anchor_id=100)
    ch = FakeChannel([_msg(200), _msg(100)])

    await cog.sync(GUILD, ch)

    ch.send.assert_called_once()


@pytest.mark.asyncio
async def test_pause_leaves_only_info(cog, store):
    store.update(mini_anchor_id=100, mini_bottom_id=300)
    ch = FakeChannel([_msg(300), _msg(100)])
    cog.bot.get_channel = MagicMock(return_value=ch)

    await cog.pause(GUILD)

    ch.get_partial_message(100).edit.assert_called_once_with(content=INFO, allowed_mentions=mini.NO_MENTIONS)
    ch.get_partial_message(300).delete.assert_called_once()
    assert store["mini_bottom_id"] is None


@pytest.mark.asyncio
async def test_save_waits_for_running_overview_update(cog, store, overview):
    lock = overview._fetch_locks.setdefault(GUILD, asyncio.Lock())
    await lock.acquire()
    task = asyncio.create_task(cog._save(GUILD, mini_bottom_id=5))
    await asyncio.sleep(0.01)
    assert "mini_bottom_id" not in store

    lock.release()
    await task
    assert store["mini_bottom_id"] == 5


@pytest.mark.asyncio
async def test_turn_on_posts_anchor_only_once(cog, store):
    store["mini_wochenplan"] = False
    ch = FakeChannel([_msg(200), _msg(100)])

    await cog._turn_on(GUILD, ch)
    anchor_id = store["mini_anchor_id"]
    assert store["mini_wochenplan"] is True
    assert ch.messages[0].id == anchor_id
    assert ch.send.call_args.args[0] == INFO

    await cog._turn_on(GUILD, ch)
    assert ch.send.call_count == 1
    assert store["mini_anchor_id"] == anchor_id


@pytest.mark.asyncio
async def test_status_counts_messages_before_anchor(cog, store):
    store.update(mini_anchor_id=100)
    ch = FakeChannel([_msg(200), _msg(100), _msg(50), _msg(40), _msg(30)])
    assert "Davor stehen noch 3 Nachrichten" in await cog._status(GUILD, ch)

    ch.messages = [_msg(200), _msg(100)]
    assert "ist die erste Nachricht" in await cog._status(GUILD, ch)


@pytest.mark.asyncio
async def test_status_reports_missing_anchor(cog, store):
    store.update(mini_anchor_id=100)
    assert "**Anker:** fehlt" in await cog._status(GUILD, FakeChannel([_msg(200)]))


def test_missing_permissions():
    assert mini.missing_permissions(discord.Permissions(view_channel=True, send_messages=True,
                                                        read_message_history=True)) == []
    assert mini.missing_permissions(discord.Permissions(view_channel=True)) == [
        "Nachrichten senden", "Nachrichtenverlauf anzeigen"]


@pytest.mark.asyncio
@pytest.mark.parametrize("manage_guild, owner, allowed", [(True, False, True), (False, True, True), (False, False, False)])
async def test_command_only_for_server_managers_and_owner(cog, store, manage_guild, owner, allowed):
    cog.bot.is_owner = AsyncMock(return_value=owner)
    del store["event_channel_id"]
    interaction = MagicMock()
    interaction.guild_id = GUILD
    interaction.user.guild_permissions = discord.Permissions(manage_guild=manage_guild)
    interaction.response.send_message = AsyncMock()

    await cog.mini_wochenplan.callback(cog, interaction, "status")

    text = interaction.response.send_message.call_args.args[0]
    assert ("Server verwalten" in text) is not allowed


def _incoming(author_id=1, channel_id=CHANNEL):
    return SimpleNamespace(guild=SimpleNamespace(id=GUILD), author=SimpleNamespace(id=author_id),
                           channel=SimpleNamespace(id=channel_id))


@pytest.mark.asyncio
async def test_new_messages_are_debounced(cog, store):
    cog.sync = AsyncMock()
    with patch.object(mini, "DEBOUNCE_SECONDS", 0):
        for _ in range(3):
            await cog.on_message(_incoming())
        await cog._debounce_tasks[GUILD]

    cog.sync.assert_called_once()


@pytest.mark.asyncio
async def test_own_messages_and_other_channels_are_ignored(cog, store):
    await cog.on_message(_incoming(author_id=BOT_ID))
    await cog.on_message(_incoming(channel_id=11))
    assert cog._debounce_tasks == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["_edit_overview_locked", "_fetch_and_post_locked"])
async def test_overview_passes_its_history_to_mini(method):
    overview_cog = Overview(MagicMock())
    messages = [_msg(200)]
    events = [_event("A", 13, 20)]
    event_ch = MagicMock()
    event_ch.history = MagicMock(return_value=_aiter(messages))
    target = AsyncMock()

    with patch("commands.overview.parse_events", return_value=events), \
         patch("commands.overview.get_guild_config", return_value={"last_overview_message_ids": []}), \
         patch("commands.overview.save_guild_config"), \
         patch("commands.overview.mini_wochenplan.overview_updated") as hook:
        await getattr(overview_cog, method)(GUILD, event_ch, target)

    hook.assert_called_once_with(overview_cog.bot, GUILD, event_ch, messages, events)


@pytest.mark.asyncio
async def test_overview_ignores_own_deletes(cog):
    overview_cog = Overview(cog.bot)
    overview_cog.auto_tasks[GUILD] = MagicMock()
    overview_cog._schedule_edit = AsyncMock()
    cog.bot.get_channel = MagicMock(return_value=MagicMock())
    cog.deleted_ids.add(300)
    cfg = {"event_channel_id": CHANNEL, "overview_channel_id": 20}

    with patch("commands.overview.get_guild_config", return_value=cfg):
        await overview_cog.on_raw_message_delete(SimpleNamespace(guild_id=GUILD, message_id=300, channel_id=CHANNEL))
        overview_cog._schedule_edit.assert_not_called()

        await overview_cog.on_raw_message_delete(SimpleNamespace(guild_id=GUILD, message_id=200, channel_id=CHANNEL))
        overview_cog._schedule_edit.assert_called_once()


@pytest.mark.asyncio
async def test_hook_starts_sync(cog):
    cog.sync = AsyncMock()
    ch = FakeChannel()
    mini.overview_updated(cog.bot, GUILD, ch, [], [])
    await asyncio.gather(*cog._tasks)
    cog.sync.assert_called_once_with(GUILD, ch, [], [])


def test_hooks_without_mini_cog_do_nothing():
    bot = MagicMock()
    mini.overview_updated(bot, GUILD, MagicMock(), [], [])
    mini.overview_stopped(bot, GUILD)
    assert mini.is_own_delete(bot, 300) is False
