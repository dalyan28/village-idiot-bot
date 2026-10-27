"""Doppelanmeldungen: Erkennung über überlappende Zeiträume, Hinweis, Entscheidungs-DM (Dalyan, 26.10.2026)."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from events import conflicts
from events.permissions import AccessSettings
from events import service
from events.schema import BERLIN_TZ, EventData, Person, ScriptRef
from events.store import RSVP_ACCEPTED, RSVP_TENTATIVE, Store

NOW = datetime(2026, 10, 24, 9, 0, tzinfo=BERLIN_TZ)
USER = 7


@pytest.fixture
def store():
    s = Store(":memory:")
    service.set_access(s, 1, AccessSettings())
    yield s
    s.close()


def add_event(store, hour, minute=0, duration=150, other=False, title="R"):
    data = EventData(start=NOW.replace(hour=hour, minute=minute), duration_minutes=duration,
                     storyteller=Person("ST", 99), title=title, description="x",
                     script=None if other else ScriptRef(kind="base", name="TB", base_key="trouble_brewing"),
                     rating=None if other else "green", is_other_event=other)
    return store.insert_event(1, 99, "ST", data, int(NOW.timestamp()))


def accept(store, event, status=RSVP_ACCEPTED):
    store.set_rsvp(event.id, USER, "Anna", status, int(NOW.timestamp()))


@pytest.mark.parametrize("a, b, expected", [
    ((18, 0), (20, 0), True),    # zwei Abendrunden, 30 Minuten Überschneidung
    ((19, 0), (19, 0), True),
    ((18, 0), (20, 30), False),  # B beginnt genau beim Ende von A
    ((11, 0), (14, 0), False),   # zwei Mittagsrunden hintereinander
    ((13, 0), (19, 0), False),   # Mittag und Abend
])
def test_overlap_rules(store, a, b, expected):
    ea, eb = add_event(store, *a), add_event(store, *b)
    accept(store, ea)
    accept(store, eb)
    group = conflicts.conflict_group(store, ea, USER, NOW)
    assert (len(group) > 1) == expected


def test_only_accepted_botc_rounds_count(store):
    a, b, c = add_event(store, 19), add_event(store, 19, other=True), add_event(store, 20)
    accept(store, a)
    accept(store, b)                 # Event ohne Clocktower: zählt nicht
    accept(store, c, RSVP_TENTATIVE)  # vorläufig: zählt nicht
    assert [e.id for e in conflicts.conflict_group(store, a, USER, NOW)] == [a.id]
    assert conflicts.conflict_group(store, b, USER, NOW) == [b]


def test_chain_forms_one_group_sorted_by_start(store):
    a, b, c = add_event(store, 18), add_event(store, 20), add_event(store, 22)  # A–B und B–C überlappen
    for e in (a, b, c):
        accept(store, e)
    assert [e.id for e in conflicts.conflict_group(store, c, USER, NOW)] == [a.id, b.id, c.id]


def test_decision_due_three_hours_before_earliest(store):
    a, b = add_event(store, 18), add_event(store, 20)
    accept(store, a)
    accept(store, b)
    group = conflicts.conflict_group(store, b, USER, NOW)
    assert not conflicts.decision_due(group, NOW.replace(hour=14, minute=59))
    assert conflicts.decision_due(group, NOW.replace(hour=15))


def test_decision_dm_once_and_choose_removes_other(store, monkeypatch):
    from discord_ui import conflicts as ui

    a, b = add_event(store, 18, title="Boozling"), add_event(store, 20, title="Trouble Brewing")
    accept(store, a)
    accept(store, b)
    sent = []

    async def fake_dm(bot, user_id, group):
        sent.append((user_id, [e.id for e in group]))
        return True
    monkeypatch.setattr(ui, "send_decision_dm", fake_dm)
    t = NOW.replace(hour=15, minute=5)
    asyncio.run(ui.check_decisions(None, store, 1, t))
    asyncio.run(ui.check_decisions(None, store, 1, t))  # zweiter Durchlauf: keine zweite DM
    assert sent == [(USER, [a.id, b.id])]

    layout = ui.decision_layout([a, b])
    labels = [getattr(i, "item", i).label for i in layout.walk_children()
              if isinstance(getattr(i, "item", i), discord.ui.Button)]
    assert labels[0].startswith("Ich spiele Boozling") and "18:00" in labels[0]
    text = " ".join(i.content for i in layout.walk_children() if isinstance(i, discord.ui.TextDisplay))
    assert "1547344778742595694" in text  # Link zu den Anmelderegeln

    updated, screen = [], {}

    async def fake_update(bot, st, event, images_changed):
        updated.append(event.id)
    monkeypatch.setattr("discord_ui.event_post.update_event_message", fake_update)
    monkeypatch.setattr(ui, "now", lambda: t)
    monkeypatch.setenv("ALLOWED_GUILD_IDS", "1")

    async def edit_message(**kw):
        screen.update(kw)
    inter = SimpleNamespace(client=SimpleNamespace(store=store), user=SimpleNamespace(id=USER),
                            response=SimpleNamespace(edit_message=edit_message))
    asyncio.run(ui.ChooseButton(b.id).callback(inter))
    assert store.get_rsvp(a.id, USER) is None and store.get_rsvp(b.id, USER) is not None
    assert updated == [a.id]
    done = " ".join(i.content for i in screen["view"].walk_children() if isinstance(i, discord.ui.TextDisplay))
    assert "Du spielst **Trouble Brewing** und bist von" in done


def test_signup_hint_links_rules(store):
    from discord_ui.conflicts import signup_hint
    a, b = add_event(store, 18, title="Boozling"), add_event(store, 20, title="TB")
    text = signup_hint(b, [a, b])
    assert "**Boozling** (Sa 18:00)" in text and "[Anmelderegeln](" in text and "Bitte entscheide dich" in text
    assert "1547344778742595694" in text


def _click(store, button):
    screen = {}

    async def edit_message(**kw):
        screen.update(kw)
    inter = SimpleNamespace(client=SimpleNamespace(store=store), user=SimpleNamespace(id=USER),
                            response=SimpleNamespace(edit_message=edit_message))
    asyncio.run(button.callback(inter))
    return " ".join(i.content for i in screen["view"].walk_children() if isinstance(i, discord.ui.TextDisplay))


def test_dm_text_links_ignore_and_expiry(store, monkeypatch):
    """Nüchterner Text mit Regel und Links; „Ignorieren“ ändert nichts; nach Beginn ist die Auswahl abgelaufen."""
    from discord_ui import conflicts as ui
    a, b = add_event(store, 18, title="Boozling"), add_event(store, 20, title="TB")
    store.set_event_message(a.id, 55, 66)
    a = store.get_event(a.id)
    accept(store, a)
    accept(store, b)
    monkeypatch.setenv("ALLOWED_GUILD_IDS", "1")

    layout = ui.decision_layout([a, b])
    text = " ".join(i.content for i in layout.walk_children() if isinstance(i, discord.ui.TextDisplay))
    assert "**Doppelanmeldung**" in text and "Für welche entscheidest du dich" not in text
    assert "[Boozling](https://discord.com/channels/1/55/66)" in text  # Link zum Event-Post
    ids = [getattr(i, "item", i).custom_id for i in layout.walk_children()
           if isinstance(getattr(i, "item", i), discord.ui.Button)]
    assert ids == [f"dbl:{a.id}", f"dbl:{b.id}", "dbl:ignore"]

    assert "Ignoriert" in _click(store, ui.ChooseButton(None, "Ignorieren"))
    assert store.get_rsvp(a.id, USER) and store.get_rsvp(b.id, USER)

    monkeypatch.setattr(ui, "now", lambda: NOW.replace(hour=18, minute=30))  # erste Runde läuft schon
    assert "nicht mehr aktuell" in _click(store, ui.ChooseButton(a.id))
    assert store.get_rsvp(b.id, USER) is not None  # nichts geändert

    monkeypatch.setattr(ui, "now", lambda: NOW.replace(hour=15))
    store.remove_rsvp(a.id, USER)  # selbst schon abgemeldet
    assert "Hat sich erledigt" in _click(store, ui.ChooseButton(b.id))
