"""Doppelanmeldungen: zeitgleiche Zusagen zu Clocktower-Runden (Dalyan, 26.10.2026).

Zwei Runden gelten als zeitgleich, wenn sich ihre Zeiträume (Beginn bis Beginn + Dauer) überschneiden.
Feste Tageszeit-Fenster würden an ihren Grenzen falsch anschlagen; so sind z. B. zwei Abendrunden
um 18 und 20 Uhr (je 2,5 Stunden) eine Doppelanmeldung, eine Mittags- und eine Abendrunde nicht.

Es zählen nur Zusagen (inkl. Warteliste), keine vorläufigen, und nur Clocktower-Runden (keine Events
ohne Clocktower). Überschneidet sich A mit B und B mit C, bilden alle drei eine Gruppe.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from events.store import RSVP_ACCEPTED, EventRecord, Store

DECIDE_HOURS_BEFORE = 3
NOTICE_KEY = "conflict:{user_id}"  # in event_reminders an der frühesten Runde der Gruppe


def overlaps(a: EventRecord, b: EventRecord) -> bool:
    return a.data.start < b.data.end and b.data.start < a.data.end


def _counts(event: EventRecord) -> bool:
    return event.data.start is not None and not event.data.is_other_event


def accepted_rounds(store: Store, guild_id: int, user_id: int, now: datetime) -> list[EventRecord]:
    """Kommende Clocktower-Runden, für die die Person zugesagt hat (auch Warteliste)."""
    result = []
    for event in store.list_events(guild_id, start_from=int(now.timestamp())):
        if not _counts(event):
            continue
        rsvp = store.get_rsvp(event.id, user_id)
        if rsvp is not None and rsvp.status == RSVP_ACCEPTED:
            result.append(event)
    return result


def conflict_group(store: Store, event: EventRecord, user_id: int, now: datetime) -> list[EventRecord]:
    """Alle zugesagten Runden, die mit `event` (direkt oder über eine Kette) zeitgleich sind, nach Beginn
    sortiert und inklusive `event`. Nur `event` allein heißt: keine Doppelanmeldung."""
    if not _counts(event):
        return [event]
    pool = [e for e in accepted_rounds(store, event.guild_id, user_id, now) if e.id != event.id]
    group, todo = [event], [event]
    while todo:
        current = todo.pop()
        for other in list(pool):
            if overlaps(current, other):
                pool.remove(other)
                group.append(other)
                todo.append(other)
    return sorted(group, key=lambda e: e.data.start)


def decision_due(group: list[EventRecord], now: datetime) -> bool:
    """Die Entscheidungs-DM kommt 3 Stunden vor Beginn der frühesten Runde (oder sofort, wenn es schon später ist)."""
    return len(group) > 1 and now >= group[0].data.start - timedelta(hours=DECIDE_HOURS_BEFORE)


def notice_key(user_id: int) -> str:
    return NOTICE_KEY.format(user_id=user_id)
