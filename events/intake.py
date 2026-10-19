"""Auswertung der /botc-Modal-Eingaben zu EventData (ohne Discord, damit testbar)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from events.parse import ParseError, parse_start
from events.schema import (
    CAMERA_OPTIONAL,
    CAMERA_REQUIRED,
    DEFAULT_LEVEL,
    DEFAULT_MAX_PLAYERS,
    LEVELS,
    MAX_PLAYERS,
    MIN_PLAYERS,
    EventData,
)

OPTION_CASUAL = "casual"
OPTION_ACADEMY = "academy"
OPTION_RECORDED = "recorded"
OPTION_CAMERA = "camera"
OPTIONS = (OPTION_CASUAL, OPTION_ACADEMY, OPTION_RECORDED, OPTION_CAMERA)


@dataclass
class ModalInput:
    """Die Rohwerte aus dem Modal. Bei einem Fehler wird das Modal damit vorbelegt neu geöffnet."""

    date_text: str = ""
    time_text: str = ""
    players_text: str = str(DEFAULT_MAX_PLAYERS)
    level: str = DEFAULT_LEVEL
    options: list[str] = field(default_factory=list)


def parse_players(text: str) -> int:
    t = text.strip()
    if not t:
        return DEFAULT_MAX_PLAYERS
    if not t.isdigit():
        raise ParseError(f"„{t}“ ist keine Zahl. Bitte gib die maximale Spielerzahl an, z. B. 12.")
    n = int(t)
    if not MIN_PLAYERS <= n <= MAX_PLAYERS:
        raise ParseError(f"Die Spielerzahl muss zwischen {MIN_PLAYERS} und {MAX_PLAYERS} liegen.")
    return n


def parse_modal_input(raw: ModalInput, now: datetime | None = None) -> EventData:
    """Modal-Eingaben → EventData. Wirft ParseError mit deutscher Meldung."""
    start = parse_start(raw.date_text, raw.time_text, now)
    max_players = parse_players(raw.players_text)
    level = raw.level if raw.level in LEVELS else DEFAULT_LEVEL
    unknown = set(raw.options) - set(OPTIONS)
    if unknown:
        raise ParseError(f"Unbekannte Option: {', '.join(sorted(unknown))}.")

    return EventData(
        start=start,
        max_players=max_players,
        level=level,
        is_casual=OPTION_CASUAL in raw.options and OPTION_ACADEMY not in raw.options,
        is_academy=OPTION_ACADEMY in raw.options,
        is_recorded=OPTION_RECORDED in raw.options,
        camera=CAMERA_REQUIRED if OPTION_CAMERA in raw.options else CAMERA_OPTIONAL,
    )
