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
    """Emoji-Präfix vor dem Titel: [Aufzeichnung] [Academy] [Casual] [⭐ Abweichung] [Schwierigkeit]."""
    if data.is_other_event:
        return ""  # Event ohne Clocktower: keine Symbole
    parts = []
    if data.is_recorded:
        parts.append(LABEL_EMOJI["recorded"])
    if data.is_academy:
        parts.append(LABEL_EMOJI["academy"])
    if data.is_casual:
        parts.append(LABEL_EMOJI["casual"])

    if data.is_special:
        parts.append(LABEL_EMOJI["special"])
    if data.rating in RATING_RANGE:
        parts.append(LABEL_EMOJI[data.rating])
    elif data.script is not None and data.script.kind == SCRIPT_FREE:
        parts.append(FREE_CHOICE_EMOJI)
    return " ".join(parts)


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
    if data.co_storyteller is not None:
        title += f" und {data.co_storyteller.name}"
    return title


def full_title(data: EventData) -> str:
    """Titel des Events: Symbole, dann der eigene Titel oder „{Skript} mit {ST}“."""
    prefix = title_prefix(data)
    title = data.title.strip() or base_title(data) or "Neues Event"
    return f"{prefix} {title}" if prefix else title


def full_description(data: EventData) -> str:
    """Eigener Text des Erstellers; bei Academy folgt der feste Academy-Text."""
    parts = [data.description.strip()] if data.description.strip() else []
    if data.is_academy and not data.is_other_event:
        parts.append(academy_description(data.rating))
    return "\n\n".join(parts)


def academy_description(rating: str | None) -> str:
    """Fester Academy-Text. Die Zeilen der Komplexitätsstufe(n) des Ratings sind **fett**.

    Bei einem Bereich (z. B. grün bis gelb) gilt die höchste Rundenzahl des Bereichs.
    """
    rounds_lines_raw = [
        (RATING_GREEN, "💚-Angebote: maximal 100 Runden gespielt"),
        (RATING_YELLOW, "🟡-Angebote: maximal 200 Runden gespielt"),
        (RATING_RED, "🟥-Angebote: maximal 300 Runden gespielt"),
    ]
    covered = RATING_RANGE.get(rating, ())
    rounds_lines = [f"**{text}**" if key in covered else text for key, text in rounds_lines_raw]

    max_rounds = max((ACADEMY_MAX_ROUNDS[r] for r in covered), default=None)
    rounds_suffix = f"(hier {max_rounds})" if max_rounds else "(s. oben)"

    return (
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
        f"{rounds_lines[0]}\n"
        f"{rounds_lines[1]}\n"
        f"{rounds_lines[2]}\n"
        "\n"
        f"Leute über der Stufe {rounds_suffix} können sich gerne unter "
        "„Auffüller\" anmelden. Wenn nicht ausreichend Spieler:innen "
        "angemeldet sind, freuen wir uns immer über „Auffüller\", da sonst "
        "die Runde teilweise nicht stattfinden kann. In diesem Fall gilt "
        "aber: Rücksicht (und bisweilen etwas Zurückhaltung) ist geboten!"
    )


# Links in der Startnachricht von /botc (Produktiv-Server, Dalyan 21.10.2026). Leer = Platzhalter „(Link folgt)“.
STORYTELLER_GUIDE_URL = ("https://discord.com/channels/1197876498980421652/1260650800141701121/"
                         "1548695371402711050")  # Hinweise zum Mitspielen und Storytellen
RULES_URL = "https://discord.com/channels/1197876498980421652/1197945543893188719"  # Kanal mit den Serverregeln
# Abschnitt „Regeln zum Anmelden für BotC-Runden“ (Hinweis bei Doppelanmeldungen, Dalyan 26.10.2026)
SIGNUP_RULES_URL = "https://discord.com/channels/1197876498980421652/1197945543893188719/1547344778742595694"


def co_st_text(data, name: str | None = None) -> str:
    """Co-Storytelling als Text: „Nein“, „Ja, frei“ oder „Ja, vergeben (Name)“, Freitext angehängt.
    `name`: aktueller Anzeigename der Co-Storyteller:in, sonst der gespeicherte."""
    from events.schema import CO_ST_LABELS, CO_ST_NO, CO_ST_TAKEN

    status = data.co_st_status if data.co_st_status in CO_ST_LABELS else CO_ST_NO
    text = CO_ST_LABELS[status]
    if status == CO_ST_TAKEN:
        who = name or (data.co_storyteller.name if data.co_storyteller else "")
        return f"{text} ({who})" if who else text
    note = data.co_st_note.strip()
    if status == CO_ST_NO and note:
        return note  # reiner Freitext
    return f"{text} · {note}" if note else text


def camera_text(data) -> str:
    """Kamera als Text: „Keine Pflicht“ bzw. mit eigenem Hinweis „Keine Pflicht · gern mit Kamera“."""
    from events.schema import CAMERA_LABELS

    label = CAMERA_LABELS.get(data.camera, "-")
    note = (data.camera_note or "").strip()
    return f"{label} · {note}" if note else label
