"""Aktions-Historie für das Feedback: was hat die Person kurz davor gemacht?

Je Entwurf in `drafts.ui` (übersteht einen Neustart), zusätzlich je User im Arbeitsspeicher
für Klicks am Event-Post. Nur Texte, kein Discord.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime

from events.schema import BERLIN_TZ
from events.templates import BASE3_FULL_NAMES

UI_KEY = "ts_history"
MAX_ENTRIES = 10
SHOWN = 6

CARD_LABELS = {
    "script": "Skript-Karte",
    "summary": "Zusammenfassung",
    "image": "Bild-Seite",
    "event": "Event-Post",
    "start": "Startnachricht",
    "testcard": "Ausprobieren-Karte",
}

FIELD_LABELS = {
    "script": "Skript", "rating": "Schwierigkeit", "image": "Bild", "description": "Beschreibung",
    "title": "Titel", "people": "Leitung", "selection": "Auswahl",
    "frame": "Termin",
}

EVENT_ACTIONS = {
    "accept": "Zusagen geklickt", "decline": "Absagen geklickt", "tentative": "Vorläufig geklickt",
    "edit": "Bearbeiten geklickt", "delete": "Löschen geklickt",
}


# ── Beschreibungen ───────────────────────────────────────────────────────────


def describe_button(name: str, arg: str | None, ui: dict | None = None) -> str:
    ui = ui or {}
    if name == "pick":
        return "Freie Skriptwahl gewählt" if arg == "free" else f"Basis-Skript gewählt: {BASE3_FULL_NAMES.get(arg, arg)}"
    if name == "pick_result" and (arg or "").isdigit():
        i = int(arg)
        results = ui.get("search_results") or []
        hit = f" ({results[i]['name']})" if i < len(results) else ""
        return f"Treffer {i + 1} gewählt{hit}"
    if name == "page" and (arg or "").isdigit():
        return f"Treffer-Seite {int(arg) + 1}"
    if name == "img":
        return {"auto": "Bild: aus dem Skript", "none": "Bild: keins"}.get(arg, f"Bild: {arg}")
    if name == "edit_field":
        return "Bild ändern geklickt" if arg == "image" else f"Ändern bei {FIELD_LABELS.get(arg, arg)}"
    if name == "fix_field":
        return f"Roter Button: {FIELD_LABELS.get(arg, arg)}"
    fixed = {
        "script_dialog": "Skript-Dialog geöffnet", "versions": "Andere Version gesucht",
        "next": "Zur Zusammenfassung", "cancel": "Abgebrochen", "upload_img": "Bild-Upload geöffnet",
        "publish": "Veröffentlichen geklickt",
    }
    if name in fixed:
        return fixed[name]
    return f"Button {name}" + (f":{arg}" if arg else "")


def describe_select(name: str, values: list[str]) -> str:
    if name == "version" and values:
        return f"Version gewählt: v{values[0].partition('|')[2]}"
    return f"Auswahl {name}: {', '.join(values) or 'leer'}"


def _option_label(radio, value: str) -> str:
    return next((o.label for o in radio.options if o.value == value), value)


def describe_modal(modal) -> str:
    """Abgeschickter Wizard-Dialog. Erkennt die Dialoge am Klassennamen (kein Import des Wizards)."""
    kind = type(modal).__name__
    if kind == "ScriptModal":
        if modal.file.values:
            return f"Skript-JSON hochgeladen: {modal.file.values[0].filename}"
        if modal.kind.value:
            return f"Skript im Dialog gewählt: {_option_label(modal.kind, modal.kind.value)}"
        return f"Skript gesucht: {(modal.query.value or '').strip()}"
    if kind == "RatingModal":
        return f"Schwierigkeit gewählt: {_option_label(modal.rating, modal.rating.value or '')}"
    if kind == "DescriptionModal":
        return f"Beschreibung geschrieben ({len((modal.text.value or '').strip())} Zeichen)"
    if kind == "FrameModal":
        return f"Termin geändert: {modal.date.value} {modal.time.value}"
    fixed = {
        "TitleModal": "Titel geändert", "PeopleModal": "Leitung und Co-Storytelling geändert",
        "SelectionModal": "Labels, Level und Kamera geändert", "ImageUploadModal": "Eigenes Bild hochgeladen",
    }
    return fixed.get(kind, f"Dialog „{modal.title}“ abgeschickt")


# ── Speichern und Lesen ──────────────────────────────────────────────────────


def append(ui: dict, text: str, ts: int) -> dict:
    entries = list(ui.get(UI_KEY) or [])
    entries.append([ts, text])
    ui[UI_KEY] = entries[-MAX_ENTRIES:]
    return ui


def recent(entries: list, n: int = SHOWN) -> list[str]:
    """Letzte Einträge als Zeilen „`20:14` Skript gesucht: boo“, älteste zuerst."""
    lines = []
    for ts, text in list(entries)[-n:]:
        t = datetime.fromtimestamp(ts, BERLIN_TZ)
        lines.append(f"`{t:%H:%M}` {text}")
    return lines


_by_user: dict[int, deque] = {}


def remember(user_id: int, text: str, ts: int):
    _by_user.setdefault(user_id, deque(maxlen=MAX_ENTRIES)).append([ts, text])


def user_entries(user_id: int) -> list:
    return list(_by_user.get(user_id, ()))


def forget_all():
    _by_user.clear()
