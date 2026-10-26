"""TESTSERVER: Test-Karte im Willkommens-Channel (Dalyan, 26.10.2026).

Buttons, mit denen die Tester:innen Dinge ausprobieren, die sonst erst später oder nur bei anderen passieren.
Alles mit [Dev] arbeitet mit erfundenen Daten: echte Anmeldungen bleiben unverändert, niemand wird angepingt.
Buttons sind DynamicItems (`tsc:<aktion>[:<a>[:<b>]]`) und funktionieren nach einem Neustart weiter.
"""

from __future__ import annotations

import io
import json
import logging
import re
from datetime import datetime, timedelta

import discord

from events import reminders
from events.schema import BERLIN_TZ, EventData, Person, ScriptRef
from events.store import EventRecord
from testserver import is_test_guild, texts

logger = logging.getLogger(__name__)

CARD_COLOR = 0x5865F2
TEST_NOTE = "-# Test: Es wurde nichts geändert."


def now() -> datetime:
    return datetime.now(BERLIN_TZ)


# ── Karte ────────────────────────────────────────────────────────────────────


def card_layout(events_link: str) -> discord.ui.LayoutView:
    text = texts.TEST_CARD.format(events=events_link)
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(discord.ui.Container(discord.ui.TextDisplay(text), accent_colour=CARD_COLOR))
    first = discord.ui.ActionRow()
    first.add_item(TestCardButton("create", label="Event erstellen", style=discord.ButtonStyle.primary))
    first.add_item(TestCardButton("sample", label="[Dev] Beispiel-Event posten"))
    layout.add_item(first)
    second = discord.ui.ActionRow()
    second.add_item(TestCardButton("myevents", label="[Dev] Meine Events ansehen"))
    second.add_item(TestCardButton("double", label="[Dev] Doppelanmeldung testen"))
    second.add_item(TestCardButton("reminder", label="[Dev] Erinnerung ansehen"))
    layout.add_item(second)
    return layout


# ── Erfundene Daten ──────────────────────────────────────────────────────────


def _day(days: int, hour: int) -> datetime:
    return (now() + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)


def fake_my_events() -> list[dict]:
    return [
        {"key": 0, "title": "🟡 Boozling mit Mara", "start_ts": int(_day(2, 20).timestamp()),
         "status": "Zugesagt", "url": None},
        {"key": 1, "title": "💚 Trouble Brewing mit Dalyan", "start_ts": int(_day(4, 19).timestamp()),
         "status": "Warteliste, Platz 2", "url": None},
        {"key": 2, "title": "Communityabend", "start_ts": int(_day(6, 20).timestamp()),
         "status": "Vorläufig", "url": None},
    ]


def _fake_round(key: int, title: str, start: datetime) -> EventRecord:
    data = EventData(start=start, title=title, storyteller=Person("Mara"),
                     script=ScriptRef(kind="base", name="Trouble Brewing", base_key="trouble_brewing"))
    return EventRecord(id=-(key + 1), guild_id=0, channel_id=None, message_id=None, creator_id=0, creator_name="",
                       data=data, created_at=0, updated_at=0, deleted_at=None)


def fake_double_group() -> list[EventRecord]:
    return [_fake_round(0, "Boozling mit Mara", _day(1, 18)), _fake_round(1, "Trouble Brewing mit Theo", _day(1, 20))]


# ── Aktionen ─────────────────────────────────────────────────────────────────


def _my_events_view(guild_name: str, mask: int, notice: str | None = None):
    from discord_ui.my_events import my_events_card

    entries = [e for e in fake_my_events() if mask & (1 << e["key"])]
    return my_events_card(guild_name, entries, notice,
                          lambda entry: TestCardButton("leave", entry["key"], mask, label="Abmelden",
                                                       style=discord.ButtonStyle.danger))


def _double_view(notice: str | None = None):
    from discord_ui.conflicts import decision_layout

    group = fake_double_group()
    return decision_layout(group, notice,
                           lambda e, label: TestCardButton("choose", -e.id - 1, label=label,
                                                           style=discord.ButtonStyle.primary))


async def _dm(interaction: discord.Interaction, *messages: dict):
    """Schickt die Vorschau per DM und bestätigt kurz im Channel."""
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        for kwargs in messages:
            await interaction.user.send(**kwargs)
    except discord.Forbidden:
        await interaction.followup.send(texts.TEST_DM_CLOSED, ephemeral=True)
        return
    await interaction.followup.send(texts.TEST_SEE_DMS, ephemeral=True)


def _reminder_messages() -> list[dict]:
    from commands.reminder import script_json
    from testserver.sample_event import ACCEPTED, STORYTELLER, boozling

    script = boozling()
    start = _day(0, 20) if now().hour < 19 else _day(1, 20)
    data = EventData(start=start, storyteller=Person(STORYTELLER), script=script,
                     title=f"Boozling mit {STORYTELLER}")
    people = [Person(n) for n in ACCEPTED[:12]] + [Person(STORYTELLER)]
    cfg = reminders.copy_of(reminders.DEFAULTS[reminders.FIRST])
    cfg.mode = reminders.MODE_NAMES  # erfundene Leute: Namen statt Pings
    text = f"{texts.TEST_REMINDER_NOTE}\n\n{reminders.message_text(cfg, start, people)}"
    content = json.dumps(script_json(script), indent=2, ensure_ascii=False).encode("utf-8")
    attendance = reminders.attendance_txt(data, people).encode("utf-8")
    no_pings = discord.AllowedMentions.none()
    return [
        {"content": text, "allowed_mentions": no_pings},
        {"content": f"Hier ist das Skript **{script.display_name}** zum Laden:",
         "file": discord.File(io.BytesIO(content), filename=f"{script.display_name}.json")},
        {"content": "Anwesenheitsliste zum Abhaken:",
         "file": discord.File(io.BytesIO(attendance), filename=reminders.ATTENDANCE_FILENAME)},
    ]


class TestCardButton(discord.ui.DynamicItem[discord.ui.Button],
                     template=r"tsc:(?P<action>[a-z]+)(?::(?P<a>\d+))?(?::(?P<b>\d+))?"):
    __test__ = False

    def __init__(self, action: str, a: int | None = None, b: int | None = None, label: str = "Test",
                 style=discord.ButtonStyle.secondary):
        custom_id = f"tsc:{action}" + (f":{a}" if a is not None else "") + (f":{b}" if b is not None else "")
        super().__init__(discord.ui.Button(label=label, style=style, custom_id=custom_id))
        self.action, self.a, self.b = action, a, b

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        a = int(match["a"]) if match["a"] else None
        b = int(match["b"]) if match["b"] else None
        return cls(match["action"], a, b, item.label or "Test", item.style)

    async def callback(self, interaction: discord.Interaction):
        action = self.action
        # Folge-Buttons in DMs bzw. ephemeren Nachrichten: nur Ansicht, kein Server nötig
        if action == "leave":
            entries = {e["key"]: e for e in fake_my_events()}
            left = entries.get(self.a)
            mask = (self.b or 0) & ~(1 << (self.a or 0))
            notice = (f"Du bist von „{discord.utils.escape_markdown(left['title'])}“ abgemeldet.\n{TEST_NOTE}"
                      if left else TEST_NOTE)
            name = interaction.guild.name if interaction.guild else "Testserver"
            await interaction.response.edit_message(view=_my_events_view(name, mask, notice))
            return
        if action == "choose":
            from discord_ui.conflicts import choice_notice
            group = fake_double_group()
            chosen = group[self.a or 0]
            others = [e for e in group if e is not chosen]
            await interaction.response.edit_message(view=_double_view(f"{choice_notice(chosen, others)}\n{TEST_NOTE}"))
            return

        if not is_test_guild(interaction.guild_id):
            await interaction.response.send_message(texts.NOT_A_TEST_SERVER, ephemeral=True)
            return
        if action == "create":
            cog = interaction.client.get_cog("Botc")
            await cog._start_for(interaction, interaction.guild, interaction.user)
        elif action == "sample":
            from testserver.sample_event import create_sample_event
            await interaction.response.defer(ephemeral=True, thinking=True)
            event = await create_sample_event(interaction.client, interaction.client.store, interaction.guild,
                                              interaction.user)
            link = f"https://discord.com/channels/{event.guild_id}/{event.channel_id}/{event.message_id}"
            await interaction.followup.send(f"Beispiel-Event ist da: {link}", ephemeral=True)
        elif action == "myevents":
            await interaction.response.send_message(
                view=_my_events_view(interaction.guild.name, 0b111, texts.TEST_MY_EVENTS_NOTE), ephemeral=True)
        elif action == "double":
            await _dm(interaction, {"view": _double_view()})
        elif action == "reminder":
            await _dm(interaction, *_reminder_messages())
