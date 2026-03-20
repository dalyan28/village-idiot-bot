"""Deterministische Label-Berechnung für BotC-Events.

Labels werden NICHT vom LLM bestimmt, sondern anhand fester Regeln in Python berechnet.
"""

import logging

logger = logging.getLogger(__name__)

LABEL_EMOJI = {
    "dove": "🕊️",
    "green": "💚",
    "yellow": "🟡",
    "red": "🟥",
    "hammer": "⚒️",
    "camera": "🎦",
}

LABEL_DESCRIPTION = {
    "dove": "Casual / Anfängerfreundlich",
    "green": "Neuling-freundlich",
    "yellow": "Fortgeschritten (S&V / BMR)",
    "red": "Komplex / Erfahrene Spieler",
    "hammer": "Homebrew / Amnesiac",
    "camera": "Aufgezeichnet für YouTube",
}

FREE_CHOICE_EMOJI = "💚/🟡/🟥"
FREE_CHOICE_DESCRIPTION = "Freie Skriptwahl"


def compute_label(fields: dict) -> str | None:
    """Berechnet das Event-Label anhand der gesammelten Felder.

    Returns:
        Label-Key (z.B. "green") oder None wenn noch nicht bestimmbar.
    """
    if fields.get("is_recorded"):
        return "camera"

    if fields.get("is_casual"):
        return "dove"

    complexity = fields.get("script_complexity")
    if complexity in ("homebrew", "amnesiac"):
        return "hammer"

    if complexity == "simple":
        return "green"

    if complexity == "SnV_BMR":
        return "yellow"

    if complexity == "complex":
        return "red"

    return None  # Noch nicht bestimmbar


def get_label_emoji(label: str | None, is_free_choice: bool = False) -> str:
    """Gibt das Emoji für ein Label zurück, oder leer wenn None."""
    if is_free_choice:
        return FREE_CHOICE_EMOJI
    if label is None:
        return ""
    return LABEL_EMOJI.get(label, "")
