"""Feste Vorlagen für Titel, Beschreibung und Label-Emojis (ersetzt die KI-Texte)."""

from __future__ import annotations

from events.schema import (
    RATING_GREEN,
    RATING_RED,
    RATING_YELLOW,
    SCRIPT_BASE,
    SCRIPT_FREE,
    EventData,
)

LABEL_EMOJI = {
    "recorded": "🎦",
    "academy": "🎓",
    "casual": "🕊️",
    "homebrew": "⚒️",
    RATING_GREEN: "💚",
    RATING_YELLOW: "🟡",
    RATING_RED: "🟥",
}
FREE_CHOICE_EMOJI = "💚/🟡/🟥"

RATING_WORDS = {
    RATING_GREEN: "grün",
    RATING_YELLOW: "gelb",
    RATING_RED: "rot",
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
    """Emoji-Präfix vor dem Titel: [Aufzeichnung] [Academy|Casual] [Homebrew] [Einschätzung]."""
    parts = []
    if data.is_recorded:
        parts.append(LABEL_EMOJI["recorded"])
    if data.is_academy:
        parts.append(LABEL_EMOJI["academy"])
    elif data.is_casual:
        parts.append(LABEL_EMOJI["casual"])

    if data.script is not None and data.script.kind == SCRIPT_FREE:
        parts.append(FREE_CHOICE_EMOJI)
    else:
        if data.is_homebrew:
            parts.append(LABEL_EMOJI["homebrew"])
        if data.rating in LABEL_EMOJI:
            parts.append(LABEL_EMOJI[data.rating])
    return " ".join(parts)


def full_title(data: EventData) -> str:
    """Titel, wie er im Event-Post steht (mit Emoji-Präfix)."""
    prefix = title_prefix(data)
    return f"{prefix} {data.title}" if prefix else data.title


def default_title(data: EventData) -> str:
    """„{Skript} mit {ST}“ bzw. „… mit {ST} und {Co-ST}“."""
    script = data.script.display_name if data.script else "BotC"
    if data.script and data.script.kind == SCRIPT_BASE:
        script = BASE3_FULL_NAMES.get(data.script.base_key, script)
    if data.storyteller is None:
        return script
    title = f"{script} mit {data.storyteller.name}"
    if data.co_storyteller is not None:
        title += f" und {data.co_storyteller.name}"
    return title


def default_description(data: EventData) -> str:
    """Beschreibung ohne KI. Academy hat einen festen Text."""
    if data.is_academy:
        return academy_description(data.rating)
    if data.script is None:
        return ""
    if data.script.kind == SCRIPT_FREE:
        return "Freie Skriptwahl: Welches Skript wir spielen, entscheiden wir gemeinsam. Meldet euch an!"
    if data.script.kind == SCRIPT_BASE:
        name = BASE3_FULL_NAMES.get(data.script.base_key, data.script.name)
        return f"Wir spielen klassisches {name} 😌 Meldet euch an!"
    return f"Wir spielen {data.script.name}. Meldet euch an!"


def academy_description(rating: str | None) -> str:
    """Fester Academy-Text. Die Zeile zur Komplexitätsstufe (rating) ist **fett**."""
    rounds_lines_raw = [
        (RATING_GREEN, "💚-Angebote: maximal 100 Runden gespielt"),
        (RATING_YELLOW, "🟡-Angebote: maximal 200 Runden gespielt"),
        (RATING_RED, "🟥-Angebote: maximal 300 Runden gespielt"),
    ]
    rounds_lines = [f"**{text}**" if key == rating else text for key, text in rounds_lines_raw]

    max_rounds = ACADEMY_MAX_ROUNDS.get(rating)
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
