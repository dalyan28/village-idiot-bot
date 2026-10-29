"""Feste Vorlagen für Titel, Beschreibung und Label-Emojis (ersetzt die KI-Texte)."""

from __future__ import annotations

from events.schema import (
    RATING_ANY,
    RATING_GREEN,
    RATING_GREEN_YELLOW,
    RATING_RANGE,
    RATING_RED,
    RATING_YELLOW,
    RATING_YELLOW_RED,
    SCRIPT_BASE,
    SCRIPT_FREE,
    EventData,
)

LABEL_EMOJI = {
    "recorded": "🎦",
    "academy": "🎓",
    "casual": "🕊️",
    "special": "⭐",  # Abweichung vom klassischen Clocktower (ersetzt ⚒️)
    RATING_GREEN: "💚",
    RATING_YELLOW: "🟡",
    RATING_RED: "🟥",
    RATING_GREEN_YELLOW: "💚/🟡",
    RATING_YELLOW_RED: "🟡/🟥",
    RATING_ANY: "💚/🟡/🟥",
}
FREE_CHOICE_EMOJI = LABEL_EMOJI[RATING_ANY]

RATING_WORDS = {
    RATING_GREEN: "grün",
    RATING_YELLOW: "gelb",
    RATING_RED: "rot",
    RATING_GREEN_YELLOW: "grün bis gelb",
    RATING_YELLOW_RED: "gelb bis rot",
    RATING_ANY: "grün, gelb oder rot",
}

BASE3_FULL_NAMES = {
    "trouble_brewing": "Trouble Brewing",
    "bad_moon_rising": "Bad Moon Rising",
    "sects_and_violets": "Sects and Violets",
}
# Fest hinterlegte Einschätzung der Basis-Skripte (unabhängig vom ScriptRater)
BASE3_RATINGS = {
    "trouble_brewing": RATING_GREEN,
    "bad_moon_rising": RATING_YELLOW,
    "sects_and_violets": RATING_YELLOW,
}
BASE3_SCRIPT_URLS = {
    "trouble_brewing": "https://www.botcscripts.com/script/133/1.0.0",
    "bad_moon_rising": "https://www.botcscripts.com/script/135/1.0.0",
    "sects_and_violets": "https://www.botcscripts.com/script/134/1.0.0",
}

ACADEMY_MAX_ROUNDS = {
    RATING_GREEN: 100,
    RATING_YELLOW: 200,
    RATING_RED: 300,
}


def title_prefix(data: EventData) -> str:
    """Emoji-Präfix vor dem Titel: [Schwierigkeit] [Aufzeichnung] [Academy] [Casual] [⭐ Abweichung].
    Die Schwierigkeit steht immer zuerst (Dalyan, 29.10.2026; vorher zuletzt)."""
    if data.is_other_event:
        return ""  # Event ohne Clocktower: keine Symbole
    parts = []
    if data.rating in RATING_RANGE:
        parts.append(LABEL_EMOJI[data.rating])
    elif data.script is not None and data.script.kind == SCRIPT_FREE:
        parts.append(FREE_CHOICE_EMOJI)
    if data.is_recorded:
        parts.append(LABEL_EMOJI["recorded"])
    if data.is_academy:
        parts.append(LABEL_EMOJI["academy"])
    if data.is_casual:
        parts.append(LABEL_EMOJI["casual"])
    if data.is_special:
        parts.append(LABEL_EMOJI["special"])
    return " ".join(parts)


# Insider-Namen nach Startzeit (Dalyan, 29.10.2026): Nachmittagsrunde „Srunde“, Mitternachtsrunde „Trunde“.
# Stunden der Startzeit (Berliner Zeit); getrennt vom Titel mit einem schmalen Punkt statt Strich oder Doppelpunkt.
AFTERNOON_HOURS = range(12, 17)   # 12:00–16:59
MIDNIGHT_HOURS = (23, 0, 1)       # 23:00–01:59
TIME_NAME_SEPARATOR = " · "


def time_name(data: EventData) -> str:
    """„Srunde“, „Trunde“ oder leer, je nach Startzeit; nur bei Clocktower-Runden."""
    if data.is_other_event or data.start is None:
        return ""
    from events.schema import BERLIN_TZ

    hour = data.start.astimezone(BERLIN_TZ).hour
    if hour in AFTERNOON_HOURS:
        return "Srunde"
    if hour in MIDNIGHT_HOURS:
        return "Trunde"
    return ""


def base_title(data: EventData) -> str:
    """„{Skript} mit {ST}“ bzw. „… mit {ST} und {Co-ST}“ (ohne Symbole). Beim Event ohne Clocktower
    gibt es keinen automatischen Titel."""
    if data.is_other_event:
        return ""
    script = data.script.display_name if data.script else "BotC"
    if data.script and data.script.kind == SCRIPT_BASE:
        script = BASE3_FULL_NAMES.get(data.script.base_key, script)
    if data.script and data.script.teensy and "teensy" not in script.lower():
        script = f"Teensy {script}"  # Teensyville im Titel kenntlich machen (Dalyan, 20.10.2026)
    if data.storyteller is None:
        return script
    title = f"{script} mit {data.storyteller.name}"
    return title


def full_title(data: EventData) -> str:
    """Titel des Events: Symbole, ggf. „Srunde · “ bzw. „Trunde · “, dann der eigene Titel oder
    „{Skript} mit {ST}“."""
    prefix = title_prefix(data)
    title = data.title.strip() or base_title(data) or "Neues Event"
    name = time_name(data)
    if name:
        title = f"{name}{TIME_NAME_SEPARATOR}{title}"
    return f"{prefix} {title}" if prefix else title


# Academy-Vorlage des Servers (/academy_text): bleibt mit eigener Beschreibung unter Discords 6000 Zeichen je Embed
ACADEMY_TEMPLATE_MAX_LENGTH = 2000


def full_description(data: EventData, academy_template: str | None = None) -> str:
    """Eigener Text des Erstellers; bei Academy folgt der Academy-Text (Vorlage des Servers oder eingebaut)."""
    parts = [data.description.strip()] if data.description.strip() else []
    if data.is_academy and not data.is_other_event:
        parts.append(academy_description(data.rating, academy_template))
    return "\n\n".join(parts)


# Academy-Text (Dalyan, 26.10.2026: pro Server anpassbar mit /academy_text). Zeilen, die mit 💚, 🟡 oder 🟥
# beginnen, werden fett, wenn sie zur Schwierigkeit der Runde passen. {hier} wird zu „(hier 200)“: die größte
# Zahl aus den fetten Zeilen, sonst „(s. oben)“.
ACADEMY_TEMPLATE_DEFAULT = (
    "Dies ist ein Angebot der Clocktower Academy!\n"
    "\n"
    "Das heißt, hier dreht sich alles rund ums Erlernen des Spiels. "
    "Hier findet ihr einen geschützten Rahmen, in dem ihr mit anderen "
    "Spieler:innen das Spiel entdecken könnt, die ebenfalls noch frisch sind.\n"
    "\n"
    "**Was ist der Unterschied zu einer regulären Runde?**\n"
    "\n"
    "In Academy-Runden nehmen wir besonders Rücksicht auf neue Spieler:innen. "
    "Unsere Storyteller erklären an passenden Stellen Interaktionen und "
    "mechanische Zusammenhänge mit etwas mehr Ruhe und ohne Zeitdruck. "
    "Generell geben unsere Storyteller etwas mehr Zeit. "
    "Auch ein leichtes „Unter-die-Arme-Greifen\" ist möglich, wenn ihr mal "
    "ratlos seid und einen Tipp braucht bzgl. Strategie und Taktik.\n"
    "\n"
    "**Wer kann sich anmelden?**\n"
    "\n"
    "Prinzipiell haben wir eine maximale Anzahl gespielter Runden für jede Komplexitätsstufe:\n"
    "💚-Angebote: maximal 100 Runden gespielt\n"
    "🟡-Angebote: maximal 200 Runden gespielt\n"
    "🟥-Angebote: maximal 300 Runden gespielt\n"
    "\n"
    "Leute über der Stufe {hier} können sich gerne unter "
    "„Auffüller\" anmelden. Wenn nicht ausreichend Spieler:innen "
    "angemeldet sind, freuen wir uns immer über „Auffüller\", da sonst "
    "die Runde teilweise nicht stattfinden kann. In diesem Fall gilt "
    "aber: Rücksicht (und bisweilen etwas Zurückhaltung) ist geboten!"
)
ACADEMY_PLACEHOLDER = "{hier}"
_LEVEL_EMOJI = {"💚": RATING_GREEN, "🟡": RATING_YELLOW, "🟥": RATING_RED}


def academy_description(rating: str | None, template: str | None = None) -> str:
    """Academy-Text für eine Runde. Die Zeilen der Komplexitätsstufe(n) des Ratings sind **fett**;
    bei einem Bereich (z. B. grün bis gelb) gilt für {hier} die höchste Rundenzahl des Bereichs."""
    import re

    covered = RATING_RANGE.get(rating, ())
    lines, numbers = [], []
    for line in (template or ACADEMY_TEMPLATE_DEFAULT).split("\n"):
        level = next((r for emoji, r in _LEVEL_EMOJI.items() if line.lstrip().startswith(emoji)), None)
        if level in covered and line.strip():
            numbers += [int(n) for n in re.findall(r"\d+", line)]
            if not line.strip().startswith("**"):
                line = f"**{line.strip()}**"
        lines.append(line)
    hint = f"(hier {max(numbers)})" if numbers else "(s. oben)"
    return "\n".join(lines).replace(ACADEMY_PLACEHOLDER, hint)


# Links in der Startnachricht von /botc (Produktiv-Server, Dalyan 21.10.2026). Leer = Platzhalter „(Link folgt)“.
STORYTELLER_GUIDE_URL = ("https://discord.com/channels/1197876498980421652/1260650800141701121/"
                         "1548695371402711050")  # Hinweise zum Mitspielen und Storytellen
RULES_URL = "https://discord.com/channels/1197876498980421652/1197945543893188719"  # Kanal mit den Serverregeln
# Abschnitt „Regeln zum Anmelden für BotC-Runden“ (Hinweis bei Doppelanmeldungen, Dalyan 26.10.2026)
SIGNUP_RULES_URL = "https://discord.com/channels/1197876498980421652/1197945543893188719/1547344778742595694"


def co_st_text(data) -> str:
    """Co-Storytelling als Text: Status, mit Hinweis „Ja, frei · gern Neulinge“ (Dalyan, 26.10.2026)."""
    from events.schema import CO_ST_LABELS, CO_ST_NO

    label = CO_ST_LABELS.get(data.co_st_status, CO_ST_LABELS[CO_ST_NO])
    note = (data.co_st_note or "").strip()
    return f"{label} · {note}" if note else label



def camera_text(data) -> str:
    """Kamera als Text: „Keine Pflicht“ bzw. mit eigenem Hinweis „Keine Pflicht · gern mit Kamera“."""
    from events.schema import CAMERA_LABELS

    label = CAMERA_LABELS.get(data.camera, "-")
    note = (data.camera_note or "").strip()
    return f"{label} · {note}" if note else label
