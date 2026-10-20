"""Feldschema eines Events: Felder, Defaults, Wertebereiche und Validierung.

Die einzige Stelle, an der die Felder definiert sind. Modal, Wizard, Embed, Speicherung
und Website lesen von hier.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BERLIN_TZ = ZoneInfo("Europe/Berlin")

# ── Wertebereiche ────────────────────────────────────────────────────────────

LEVELS = ("Neuling", "Erfahren", "Profi", "Alle")

CAMERA_REQUIRED = "required"
CAMERA_OPTIONAL = "optional"
CAMERA_OFF = "off"
CAMERA_LABELS = {
    CAMERA_REQUIRED: "Pflicht",
    CAMERA_OPTIONAL: "Keine Pflicht",
    CAMERA_OFF: "Aus",
}

RATING_GREEN = "green"
RATING_YELLOW = "yellow"
RATING_RED = "red"
SINGLE_RATINGS = (RATING_GREEN, RATING_YELLOW, RATING_RED)  # was der ScriptRater liefern kann
# Bereiche, die der Storyteller selbst wählen kann (Dalyan, 20.10.2026)
RATING_GREEN_YELLOW = "green_yellow"
RATING_YELLOW_RED = "yellow_red"
RATING_ANY = "any"  # alle drei Stufen, z. B. freie Skriptwahl
RATINGS = (*SINGLE_RATINGS, RATING_GREEN_YELLOW, RATING_YELLOW_RED, RATING_ANY)
RATING_RANGE = {
    RATING_GREEN: (RATING_GREEN,),
    RATING_YELLOW: (RATING_YELLOW,),
    RATING_RED: (RATING_RED,),
    RATING_GREEN_YELLOW: (RATING_GREEN, RATING_YELLOW),
    RATING_YELLOW_RED: (RATING_YELLOW, RATING_RED),
    RATING_ANY: (RATING_GREEN, RATING_YELLOW, RATING_RED),
}

TITLE_MAX_LENGTH = 200  # eigener Titel; die Symbole davor kommen dazu (Discord-Grenze 256)

# Woher die Einschätzung stammt
RATING_SOURCE_RATER = "rater"    # ScriptRater /api/analyse
RATING_SOURCE_MANUAL = "manual"  # vom Storyteller gewählt
RATING_SOURCE_FIXED = "fixed"    # Basis-3, fest hinterlegt
RATING_SOURCES = (RATING_SOURCE_RATER, RATING_SOURCE_MANUAL, RATING_SOURCE_FIXED)

SCRIPT_BASE = "base"
SCRIPT_BOTCSCRIPTS = "botcscripts"
SCRIPT_UPLOAD = "upload"
SCRIPT_FREE = "free"
SCRIPT_KINDS = (SCRIPT_BASE, SCRIPT_BOTCSCRIPTS, SCRIPT_UPLOAD, SCRIPT_FREE)

IMAGE_AUTO = "auto"
IMAGE_CUSTOM = "custom"
IMAGE_NONE = "none"
IMAGE_MODES = (IMAGE_AUTO, IMAGE_CUSTOM, IMAGE_NONE)

MIN_PLAYERS = 1
MAX_PLAYERS = 200
DURATION_CHOICES = (90, 120, 150, 180, 210, 240)
MAX_DAYS_AHEAD = 365

DESCRIPTION_MAX_LENGTH = 1000  # eigener Text des Erstellers, passt in ein Embed-Feld

# ── Defaults (unverändert aus Branch event-creation) ─────────────────────────

DEFAULT_MAX_PLAYERS = 12
DEFAULT_DURATION_MINUTES = 150
DEFAULT_LEVEL = "Alle"
DEFAULT_CAMERA = CAMERA_OPTIONAL


# ── Datenklassen ─────────────────────────────────────────────────────────────


@dataclass
class Person:
    """Ein Mensch, der im Event angezeigt wird.

    Angezeigt wird immer `name` als Text, nie eine Mention (Discord löst Mentions in Embeds
    oft nicht auf). `user_id` dient nur Rechten und Logik und fehlt bei Freitext-Namen.
    """

    name: str
    user_id: int | None = None


@dataclass
class ScriptRef:
    """Das Skript eines Events."""

    kind: str                      # SCRIPT_KINDS
    name: str = ""
    author: str = ""
    version: str = ""
    base_key: str = ""             # trouble_brewing, bad_moon_rising, sects_and_violets
    botcscripts_id: str = ""
    characters: list[str] = field(default_factory=list)
    content: list | None = None    # nur bei Upload: das komplette Skript-JSON

    @property
    def url(self) -> str:
        if self.botcscripts_id and self.version:
            return f"https://www.botcscripts.com/script/{self.botcscripts_id}/{self.version}"
        return ""

    @property
    def display_name(self) -> str:
        return "Freie Skriptwahl" if self.kind == SCRIPT_FREE else self.name


@dataclass
class EventData:
    """Alle Felder, die ein Storyteller festlegt. Entwurf und fertiges Event teilen sie."""

    start: datetime | None = None
    duration_minutes: int = DEFAULT_DURATION_MINUTES
    max_players: int = DEFAULT_MAX_PLAYERS
    level: str = DEFAULT_LEVEL
    is_casual: bool = False
    is_academy: bool = False
    is_recorded: bool = False
    camera: str = DEFAULT_CAMERA
    storyteller: Person | None = None
    co_storyteller: Person | None = None
    script: ScriptRef | None = None
    rating: str | None = None
    rating_source: str | None = None
    is_homebrew: bool = False      # unbekannte Charaktere (Homebrew/Amnesiac), zusätzlich zum Rating
    title: str = ""                # eigener Titel; leer = automatisch „{Skript} mit {ST}“ (templates.full_title)
    description: str = ""          # schreibt der Ersteller selbst
    image_mode: str = IMAGE_AUTO
    custom_image: str = ""         # Dateiname des hochgeladenen Bildes im Upload-Ordner
    reminder_overrides: dict = field(default_factory=dict)

    @property
    def end(self) -> datetime | None:
        if self.start is None:
            return None
        return self.start + timedelta(minutes=self.duration_minutes)

    # ── Serialisierung (JSON in der Datenbank) ───────────────────────────

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat() if self.start else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "EventData":
        d = dict(d)
        start = d.pop("start", None)
        st = d.pop("storyteller", None)
        co = d.pop("co_storyteller", None)
        script = d.pop("script", None)
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(
            start=datetime.fromisoformat(start) if start else None,
            storyteller=Person(**st) if st else None,
            co_storyteller=Person(**co) if co else None,
            script=ScriptRef(**script) if script else None,
            **known,
        )


# ── Regeln ───────────────────────────────────────────────────────────────────


def normalize(data: EventData) -> EventData:
    """Wendet die festen Regeln an, die keine Fehler sind, sondern Folgen.

    Derzeit keine: Academy und Casual dürfen zusammen gesetzt sein (Dalyan, 20.10.2026).
    """
    return data


def validate(data: EventData, now: datetime | None = None, check_start: bool = True) -> list[str]:
    """Prüft die Werte. Gibt deutsche Fehlermeldungen zurück, leer = alles in Ordnung.

    Fehlende Pflichtfelder sind hier kein Fehler (ein Entwurf darf unvollständig sein),
    dafür gibt es `missing_for_publish`. `check_start=False` überspringt die Prüfung, ob der
    Termin in der Zukunft liegt (Bearbeiten eines laufenden Events ohne Terminänderung).
    """
    errors = []
    now = now or datetime.now(BERLIN_TZ)

    if data.start is not None and check_start:
        if data.start.tzinfo is None:
            errors.append("Der Termin hat keine Zeitzone.")
        elif data.start <= now:
            errors.append("Der Termin liegt in der Vergangenheit.")
        elif data.start > now + timedelta(days=MAX_DAYS_AHEAD):
            errors.append(f"Der Termin liegt mehr als {MAX_DAYS_AHEAD} Tage in der Zukunft.")

    if not MIN_PLAYERS <= data.max_players <= MAX_PLAYERS:
        errors.append(f"Die Spielerzahl muss zwischen {MIN_PLAYERS} und {MAX_PLAYERS} liegen.")
    if data.duration_minutes <= 0 or data.duration_minutes > 24 * 60:
        errors.append("Die Dauer muss zwischen 1 Minute und 24 Stunden liegen.")
    if data.level not in LEVELS:
        errors.append(f"Unbekanntes Erfahrungslevel: {data.level}.")
    if data.camera not in CAMERA_LABELS:
        errors.append(f"Unbekannte Kamera-Einstellung: {data.camera}.")
    if data.script is not None and data.script.kind not in SCRIPT_KINDS:
        errors.append(f"Unbekannte Skript-Art: {data.script.kind}.")
    if data.rating is not None and data.rating not in RATINGS:
        errors.append(f"Unbekannte Einschätzung: {data.rating}.")
    if data.rating_source is not None and data.rating_source not in RATING_SOURCES:
        errors.append(f"Unbekannte Herkunft der Einschätzung: {data.rating_source}.")
    if data.image_mode not in IMAGE_MODES:
        errors.append(f"Unbekannter Bild-Modus: {data.image_mode}.")
    if len(data.title) > TITLE_MAX_LENGTH:
        errors.append(f"Der Titel ist länger als {TITLE_MAX_LENGTH} Zeichen.")
    if data.image_mode == IMAGE_CUSTOM and not data.custom_image:
        errors.append("Für ein eigenes Bild fehlt die Datei.")
    if len(data.description) > DESCRIPTION_MAX_LENGTH:
        errors.append(f"Die Beschreibung ist länger als {DESCRIPTION_MAX_LENGTH} Zeichen.")
    return errors


def missing_for_publish(data: EventData) -> list[str]:
    """Felder, ohne die ein Event nicht veröffentlicht werden kann (deutsche Namen).

    Bei Academy ist die Beschreibung freiwillig, weil der feste Academy-Text dazukommt.
    """
    missing = []
    if data.start is None:
        missing.append("Termin")
    if data.script is None:
        missing.append("Skript")
    if data.storyteller is None or not data.storyteller.name.strip():
        missing.append("Storyteller")
    if not data.description.strip() and not data.is_academy:
        missing.append("Beschreibung")
    return missing
