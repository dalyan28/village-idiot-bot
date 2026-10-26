"""Beispiel-Event: Boozling mit 23 erfundenen Anmeldungen, damit man ein volles Event sieht.

Zusagen mit Warteliste, Vorläufig und Absagen. Das Skript kommt aus test_scripts/Boozling.json,
es braucht also kein Netzwerk. Ersteller:in ist, wer es anlegt; so lässt es sich normal
bearbeiten und löschen. Alle angezeigten Namen sind erfunden. /testserver reset räumt es mit allen anderen Runden weg.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import discord

from events.schema import (
    BERLIN_TZ,
    CO_ST_TAKEN,
    RATING_SOURCE_MANUAL,
    RATING_YELLOW,
    SCRIPT_BOTCSCRIPTS,
    EventData,
    Person,
    ScriptRef,
)
from events.store import RSVP_ACCEPTED, RSVP_DECLINED, RSVP_TENTATIVE, EventRecord, Store
from logic.script_cache import validate_script_json
from logic.script_flags import special_reasons

SCRIPT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_scripts", "Boozling.json")

# Erfundene Leute; die IDs gibt es auf keinem Server, angezeigt wird der gespeicherte Name
FAKE_ID_BASE = 900_000_000_000_000_000
ACCEPTED = ["Anna", "Ben", "Clara", "David", "Emma", "Finn", "Greta", "Hannes", "Ida", "Jonas", "Karla", "Leo",
            "Mila", "Noah", "Olivia"]               # 12 spielen, 3 auf der Warteliste
TENTATIVE = ["Paul", "Quentin", "Rosa", "Sami"]
DECLINED = ["Tilda", "Umut", "Vera", "Wim"]
# Auch Storyteller:in und Co-ST sind erfunden (Dalyan, 20.10.2026: keine echten Namen)
STORYTELLER, CO_STORYTELLER = "Mara", "Theo"

DESCRIPTION = ("Das ist ein Beispiel-Event mit erfundenen Leuten, damit ihr seht, wie eine volle Runde aussieht: "
               "12 Plätze, Warteliste, Vorläufig und Absagen. Zusagen, Bearbeiten und Löschen funktionieren ganz "
               "normal.")


def boozling() -> ScriptRef:
    with open(SCRIPT_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    parsed, error = validate_script_json(raw["content"])
    if error:
        raise ValueError(error)
    script = ScriptRef(kind=SCRIPT_BOTCSCRIPTS, name=parsed["name"], author=parsed["author"],
                       version=raw.get("version", ""), botcscripts_id=str(raw.get("script_id", "")),
                       characters=parsed["characters"], content=raw["content"])
    return script


def sample_data(now: datetime) -> EventData:
    start = (now + timedelta(days=2)).astimezone(BERLIN_TZ).replace(hour=20, minute=0, second=0, microsecond=0)
    script = boozling()
    reasons = special_reasons(script)
    return EventData(start=start, storyteller=Person(STORYTELLER), co_st_status=CO_ST_TAKEN,
                     co_st_note=CO_STORYTELLER, script=script, rating=RATING_YELLOW,
                     rating_source=RATING_SOURCE_MANUAL, is_special=bool(reasons), special_reasons=reasons,
                     description=DESCRIPTION)


def add_rsvps(store: Store, event_id: int, now_ts: int):
    """Reihenfolge zählt: die ersten 12 Zusagen spielen, der Rest steht auf der Warteliste."""
    people = [(n, RSVP_ACCEPTED) for n in ACCEPTED] + [(n, RSVP_TENTATIVE) for n in TENTATIVE] + \
             [(n, RSVP_DECLINED) for n in DECLINED]
    for i, (name, status) in enumerate(people):
        store.set_rsvp(event_id, FAKE_ID_BASE + i, name, status, now_ts - (len(people) - i) * 60)


async def create_sample_event(bot, store: Store, guild: discord.Guild, member) -> EventRecord:
    """Legt das Beispiel-Event an und postet es in den Event-Channel."""
    from discord_ui.event_post import post_event

    now = datetime.now(BERLIN_TZ)
    ts = int(now.timestamp())
    data = sample_data(now)
    event = store.insert_event(guild.id, member.id, member.display_name, data, ts)
    store.add_log(event.id, member.id, "create", {"testserver": "beispiel"}, ts)
    add_rsvps(store, event.id, ts)
    try:
        await post_event(bot, store, event)
    except Exception:
        store.conn.execute("DELETE FROM events WHERE id = ?", (event.id,))
        store.conn.commit()
        raise
    return store.get_event(event.id)
