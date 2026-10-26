"""Eigene Standardwerte pro Person und Server (Dalyan, 26.10.2026).

Rangfolge beim Anlegen: eingebauter Standard → eigener Standard → Automatik (Teensyville = 6) → Änderung im
Entwurf. Die Werte werden beim Anlegen in den Entwurf übernommen; spätere Änderungen an den Einstellungen
wirken nicht auf laufende Entwürfe oder veröffentlichte Events.

Robustheit: gespeichert als JSON mit Versionsnummer in `user_settings` (SQLite auf dem Volume). Beim Lesen
wird jedes Feld einzeln geprüft; ein kaputtes oder unbekanntes Feld fällt auf den eingebauten Standard zurück,
ohne die anderen Werte zu verlieren. Aufräumen, Reset und Delete All fassen die Tabelle nicht an.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from events.schema import (
    CAMERA_LABELS,
    CO_ST_LABELS,
    CO_ST_TAKEN,
    Person,
    DESCRIPTION_MAX_LENGTH,
    EventData,
)

VERSION = 1
MAX_PLAYERS_RANGE = (1, 200)
DURATION_RANGE = (15, 24 * 60)
NOTE_MAX_LENGTH = 100


@dataclass
class UserDefaults:
    """Eigene Standardwerte. None bzw. leer = eingebauter Standard."""

    description: str = ""
    max_players: int | None = None
    duration_minutes: int | None = None
    level: str | None = None
    camera: str | None = None
    camera_note: str = ""
    co_st_status: str | None = None
    co_st_note: str = ""

    def to_dict(self) -> dict:
        return {"version": VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, raw: dict | None) -> "UserDefaults":
        """Tolerant lesen: jedes Feld einzeln prüfen, Unbrauchbares ignorieren."""
        from events.schema import LEVELS

        raw = raw if isinstance(raw, dict) else {}
        d = cls()

        def text(key: str, limit: int) -> str:
            value = raw.get(key)
            return value[:limit] if isinstance(value, str) else ""

        def number(key: str, low: int, high: int) -> int | None:
            value = raw.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else None

        d.description = text("description", DESCRIPTION_MAX_LENGTH)
        d.max_players = number("max_players", *MAX_PLAYERS_RANGE)
        d.duration_minutes = number("duration_minutes", *DURATION_RANGE)
        d.level = raw.get("level") if raw.get("level") in LEVELS else None
        d.camera = raw.get("camera") if raw.get("camera") in CAMERA_LABELS else None
        d.camera_note = text("camera_note", NOTE_MAX_LENGTH)
        d.co_st_status = raw.get("co_st_status") if raw.get("co_st_status") in CO_ST_LABELS else None
        d.co_st_note = text("co_st_note", NOTE_MAX_LENGTH)
        return d

    def is_empty(self) -> bool:
        return self == UserDefaults()

    def apply(self, data: EventData) -> EventData:
        """Übernimmt die eigenen Standardwerte in neue Event-Daten (Felder, die die Person gesetzt hat)."""
        if self.description and not data.description.strip():
            data.description = self.description
        if self.max_players is not None:
            data.max_players = self.max_players
        if self.duration_minutes is not None:
            data.duration_minutes = self.duration_minutes
        if self.level is not None:
            data.level = self.level
        if self.camera is not None:
            data.camera = self.camera
        if self.camera_note:
            data.camera_note = self.camera_note
        if self.co_st_status is not None:
            data.co_st_status = self.co_st_status
        if self.co_st_note:
            if data.co_st_status == CO_ST_TAKEN:
                # Bei „Ja, vergeben“ ist der Text der Name der Co-Storyteller:in (Titel, Erinnerung)
                data.co_storyteller, data.co_st_note = Person(name=self.co_st_note[:50]), ""
            else:
                data.co_st_note = self.co_st_note
        return data


def get(store, guild_id: int, user_id: int) -> UserDefaults:
    return UserDefaults.from_dict(store.get_user_settings(guild_id, user_id).get("defaults"))


def save(store, guild_id: int, user_id: int, defaults: UserDefaults, now: int):
    settings = store.get_user_settings(guild_id, user_id)
    settings["defaults"] = defaults.to_dict()
    store.set_user_settings(guild_id, user_id, settings, now)
