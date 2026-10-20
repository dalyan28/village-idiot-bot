"""Reminder vor Eventbeginn: Server-Standard + Anpassung je Event (Plan: Abschnitt „Reminder“).

Es gibt zwei Reminder ("first" und "second"). Gespeichert wird nur, was vom Standard abweicht:
im Server unter guild_settings["reminders"], im Event unter EventData.reminder_overrides.
Ändert ein Admin den Server-Standard, gilt das für alle Events ohne eigene Anpassung.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta

import discord

from events.schema import EventData, Person
from events.service import RsvpLists

FIRST, SECOND = "first", "second"
KEYS = (FIRST, SECOND)
KIND_REMINDER = "reminder"
KIND_ATTENDANCE = "attendance"
MODE_PING = "ping"
MODE_NAMES = "names"

TO_ACCEPTED = "accepted"
TO_WAITLIST = "waitlist"
TO_TENTATIVE = "tentative"
TO_CO = "co"
RECIPIENTS = (TO_ACCEPTED, TO_WAITLIST, TO_TENTATIVE, TO_CO)
RECIPIENT_LABELS = {
    TO_ACCEPTED: "Zusagen",
    TO_WAITLIST: "Warteliste",
    TO_TENTATIVE: "Vorläufig / Auffüller",
    TO_CO: "Co-ST",
}
MAX_MINUTES_BEFORE = 24 * 60

GUILD_SETTINGS_KEY = "reminders"


@dataclass
class ReminderConfig:
    key: str
    enabled: bool
    minutes_before: int
    mode: str                     # MODE_PING oder MODE_NAMES
    recipients: list[str] = field(default_factory=list)
    post_script: bool = False
    kind: str = KIND_REMINDER

    @property
    def label(self) -> str:
        return "Erinnerung" if self.kind == KIND_REMINDER else "Anwesenheitskontrolle"


DEFAULTS = {
    FIRST: ReminderConfig(FIRST, True, 15, MODE_PING, [TO_ACCEPTED], post_script=True, kind=KIND_REMINDER),
    SECOND: ReminderConfig(SECOND, True, 5, MODE_PING, [TO_ACCEPTED], post_script=False, kind=KIND_ATTENDANCE),
}
_FIELDS = ("enabled", "minutes_before", "mode", "recipients", "post_script")


def copy_of(cfg: ReminderConfig) -> ReminderConfig:
    """Unabhängige Kopie (die Empfängerliste wird nicht geteilt)."""
    return replace(cfg, recipients=list(cfg.recipients))


def _apply(base: ReminderConfig, changes: dict | None) -> ReminderConfig:
    changes = {k: v for k, v in (changes or {}).items() if k in _FIELDS}
    return copy_of(replace(base, **changes))


def server_defaults(guild_settings: dict) -> dict[str, ReminderConfig]:
    stored = guild_settings.get(GUILD_SETTINGS_KEY) or {}
    return {k: _apply(DEFAULTS[k], stored.get(k)) for k in KEYS}


def effective(guild_settings: dict, data: EventData) -> dict[str, ReminderConfig]:
    """Server-Standard mit den Abweichungen des Events."""
    base = server_defaults(guild_settings)
    return {k: _apply(base[k], (data.reminder_overrides or {}).get(k)) for k in KEYS}


def diff(base: ReminderConfig, wanted: ReminderConfig) -> dict:
    """Nur die Felder, die von `base` abweichen (das wird gespeichert)."""
    a, b = asdict(base), asdict(wanted)
    return {k: b[k] for k in _FIELDS if a[k] != b[k]}


def store_event_choice(guild_settings: dict, data: EventData, wanted: ReminderConfig):
    """Speichert die Wahl für ein Event als Abweichung vom Server-Standard."""
    base = server_defaults(guild_settings)[wanted.key]
    overrides = dict(data.reminder_overrides or {})
    d = diff(base, wanted)
    if d:
        overrides[wanted.key] = d
    else:
        overrides.pop(wanted.key, None)
    data.reminder_overrides = overrides


def store_server_choice(guild_settings: dict, wanted: ReminderConfig) -> dict:
    """Neuer Server-Standard; gibt die geänderten guild_settings zurück."""
    stored = dict(guild_settings.get(GUILD_SETTINGS_KEY) or {})
    d = diff(DEFAULTS[wanted.key], wanted)
    if d:
        stored[wanted.key] = d
    else:
        stored.pop(wanted.key, None)
    return {**guild_settings, GUILD_SETTINGS_KEY: stored}


def validate(cfg: ReminderConfig) -> list[str]:
    errors = []
    if not 0 <= cfg.minutes_before <= MAX_MINUTES_BEFORE:
        errors.append(f"Der Zeitpunkt muss zwischen 0 und {MAX_MINUTES_BEFORE} Minuten vor Beginn liegen.")
    if cfg.mode not in (MODE_PING, MODE_NAMES):
        errors.append("Unbekannte Benachrichtigungsart.")
    if set(cfg.recipients) - set(RECIPIENTS):
        errors.append("Unbekannte Empfänger.")
    return errors


def due(configs: dict[str, ReminderConfig], start: datetime, now: datetime, sent: set[str]) -> list[ReminderConfig]:
    """Fällig und noch nicht gesendet. Verpasste Reminder werden nachgeholt, solange das Event
    noch nicht begonnen hat; danach verfallen sie still."""
    if now >= start:
        return []
    return [
        cfg for k, cfg in configs.items()
        if cfg.enabled and k not in sent and now >= start - timedelta(minutes=cfg.minutes_before)
    ]


def recipients(cfg: ReminderConfig, lists: RsvpLists, data: EventData) -> list[Person]:
    people: list[Person] = []
    if TO_ACCEPTED in cfg.recipients:
        people += lists.players
    if TO_WAITLIST in cfg.recipients:
        people += lists.waitlist
    if TO_TENTATIVE in cfg.recipients:
        people += lists.tentative
    if TO_CO in cfg.recipients and data.co_storyteller is not None:
        people.append(data.co_storyteller)
    seen, unique = set(), []
    for p in people:
        key = p.user_id if p.user_id is not None else ("name", p.name)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _who(person: Person, mode: str) -> str:
    if mode == MODE_PING and person.user_id is not None:
        return f"<@{person.user_id}>"
    return discord.utils.escape_markdown(person.name)


def message_text(cfg: ReminderConfig, start: datetime, people: list[Person], is_academy: bool = False) -> str:
    ts = int(start.timestamp())
    if cfg.kind == KIND_ATTENDANCE:
        if not people:
            return "**Anwesenheitskontrolle!**\n\nKeine Zusagen vorhanden."
        lines = "\n".join(f"{i}. {_who(p, cfg.mode)}" for i, p in enumerate(people, 1))
        return f"**Anwesenheitskontrolle!**\n\n{lines}\n\nWer fehlt, bitte melden, es geht gleich los!"
    text = f"**Erinnerung!** Das Event startet <t:{ts}:R>!"
    if people:
        text += "\n\n" + " ".join(_who(p, cfg.mode) for p in people)
    return text


def describe(cfg: ReminderConfig) -> str:
    """Kurzbeschreibung für Wizard und /see_reminders."""
    if not cfg.enabled:
        return f"{cfg.label}: aus"
    who = ", ".join(RECIPIENT_LABELS[r] for r in cfg.recipients) or "niemand"
    how = "Ping" if cfg.mode == MODE_PING else "nur Namen"
    text = f"{cfg.label} {cfg.minutes_before} Min. vorher · {how} · an {who}"
    if cfg.post_script:
        text += " · mit Skript-JSON"
    return text
