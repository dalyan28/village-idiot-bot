"""Deterministische Label-Berechnung und Skript-Komplexitätsanalyse für BotC-Events.

Labels werden NICHT vom LLM bestimmt, sondern anhand fester Regeln in Python berechnet.
Die Skript-Analyse vergleicht Charaktere gegen TB/BMR/SnV und bewertet Komplexität.
"""

import json
import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)

LABEL_EMOJI = {
    "dove": "🕊️",
    "academy": "🎓",
    "green": "💚",
    "yellow": "🟡",
    "red": "🟥",
    "hammer": "⚒️",
    "camera": "🎦",
}

LABEL_DESCRIPTION = {
    "dove": "Casual / Anfängerfreundlich",
    "academy": "Academy / Lernformat",
    "green": "Neuling-freundlich",
    "yellow": "Fortgeschritten (S&V / BMR)",
    "red": "Komplex / Erfahrene Spieler",
    "hammer": "Homebrew / Amnesiac",
    "camera": "Aufgezeichnet für YouTube",
}

FREE_CHOICE_EMOJI = "💚/🟡/🟥"
FREE_CHOICE_DESCRIPTION = "Freie Skriptwahl"

_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
_ROOT_DIR = os.path.dirname(os.path.dirname(__file__))

CORE_TEAMS = {"townsfolk", "outsider", "minion", "demon"}


# ── Data Loading (cached) ────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_base_char_sets() -> tuple[frozenset, frozenset, frozenset, frozenset]:
    """Lädt TB, BMR, SnV Char-Sets und das kombinierte Base3-Set."""
    path = os.path.join(_STATIC_DIR, "base_scripts.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    tb = frozenset(data["trouble_brewing"]["characters"])
    bmr = frozenset(data["bad_moon_rising"]["characters"])
    snv = frozenset(data["sects_and_violets"]["characters"])
    base3 = tb | bmr | snv
    return tb, bmr, snv, base3


@lru_cache(maxsize=1)
def _load_char_db() -> dict:
    """Lädt characters.json als dict {id: {name, team}}."""
    path = os.path.join(_STATIC_DIR, "characters.json")
    with open(path, encoding="utf-8") as f:
        chars = json.load(f)
    return {c["id"]: {"name": c.get("name", c["id"]), "team": c.get("team", "?")} for c in chars}


@lru_cache(maxsize=1)
def _load_ratings() -> dict:
    """Lädt character_rating.json als dict {name_lower: {name, score}}."""
    path = os.path.join(_ROOT_DIR, "character_rating.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {name.lower(): {"name": name, "score": entry["score"]} for name, entry in data.items()}


# ── Skript-Komplexitätsanalyse ────────────────────────────────────────

def analyze_script_complexity(char_ids: list[str]) -> dict:
    """Analysiert die Komplexität eines Skripts anhand seiner Charaktere.

    Returns dict mit: rating, is_homebrew, is_amnesiac, tb_overlap, base3_overlap,
    loric_count, game_changer_count, score10_chars, score9_chars, unknown_chars,
    non_tb_chars, non_base3_chars, loric_chars, reasoning
    """
    if not char_ids:
        return {"rating": None, "reasoning": "Keine Charaktere vorhanden."}

    tb, _bmr, _snv, base3 = _load_base_char_sets()
    char_db = _load_char_db()
    ratings = _load_ratings()

    # Partitioniere Charaktere
    core_ids = []       # townsfolk/outsider/minion/demon
    loric_ids = []
    unknown_ids = []

    # Metadaten-Einträge filtern (z.B. _meta von botcscripts.com)
    META_PREFIXES = ("_",)

    for cid in char_ids:
        if any(cid.startswith(p) for p in META_PREFIXES):
            continue
        info = char_db.get(cid)
        if info is None:
            unknown_ids.append(cid)
        elif info["team"] == "loric":
            loric_ids.append(cid)
        elif info["team"] in CORE_TEAMS:
            core_ids.append(cid)
        # fabled/traveller werden ignoriert

    is_homebrew = len(unknown_ids) > 0
    unknown_names = unknown_ids  # IDs als Namen, da unbekannt

    # Amnesiac-Check
    amnesiac_count = sum(1 for cid in core_ids if cid == "amnesiac")
    is_amnesiac = len(core_ids) > 0 and amnesiac_count / len(core_ids) > 0.5

    # Loric-Namen
    loric_names = [char_db[cid]["name"] for cid in loric_ids]
    loric_count = len(loric_ids)

    # Overlap-Berechnung
    core_set = set(core_ids)
    total_core = len(core_set)  # unique
    if total_core == 0:
        tb_overlap = 0.0
        base3_overlap = 0.0
    else:
        tb_overlap = len(core_set & tb) / total_core
        base3_overlap = len(core_set & base3) / total_core

    # Nicht-TB und Nicht-Base3 Chars (mit Namen)
    non_tb_ids = core_set - tb
    non_base3_ids = core_set - base3
    non_tb_names = [char_db[cid]["name"] for cid in non_tb_ids if cid in char_db]
    non_base3_names = [char_db[cid]["name"] for cid in non_base3_ids if cid in char_db]

    # Game Changer Berechnung via character_rating.json
    score10_chars = []
    score9_chars = []

    for cid in core_set:
        info = char_db.get(cid)
        if not info:
            continue
        name_lower = info["name"].lower()
        rating_entry = ratings.get(name_lower)
        if rating_entry:
            if rating_entry["score"] == 10:
                score10_chars.append(rating_entry["name"])
            elif rating_entry["score"] == 9:
                score9_chars.append(rating_entry["name"])

    # Auch Lorics gegen Ratings prüfen
    for cid in loric_ids:
        info = char_db.get(cid)
        if not info:
            continue
        name_lower = info["name"].lower()
        rating_entry = ratings.get(name_lower)
        if rating_entry:
            if rating_entry["score"] == 10:
                score10_chars.append(rating_entry["name"])
            elif rating_entry["score"] == 9:
                score9_chars.append(rating_entry["name"])

    game_changer_count = len(score10_chars) + len(score9_chars) // 2

    # Rating bestimmen
    tb_high = tb_overlap >= 0.8
    base3_high = base3_overlap >= 0.8

    if is_amnesiac:
        rating = "red"
    elif tb_high and game_changer_count == 0 and loric_count == 0:
        rating = "green"
    elif tb_high and ((game_changer_count == 1 and loric_count == 0) or
                       (game_changer_count == 0 and loric_count == 1)):
        rating = "yellow"
    elif base3_high and game_changer_count == 0 and loric_count == 0:
        rating = "yellow"
    else:
        rating = "red"

    # Kompakte Fakten-Zusammenfassung für Haiku
    facts = _build_analysis_facts(
        rating=rating,
        is_homebrew=is_homebrew,
        is_amnesiac=is_amnesiac,
        tb_overlap=tb_overlap,
        base3_overlap=base3_overlap,
        non_tb_names=non_tb_names,
        non_base3_names=non_base3_names,
        loric_names=loric_names,
        score10_chars=score10_chars,
        score9_chars=score9_chars,
        unknown_names=unknown_names,
    )

    return {
        "rating": rating,
        "is_homebrew": is_homebrew,
        "is_amnesiac": is_amnesiac,
        "tb_overlap": tb_overlap,
        "base3_overlap": base3_overlap,
        "loric_count": loric_count,
        "game_changer_count": game_changer_count,
        "score10_chars": score10_chars,
        "score9_chars": score9_chars,
        "unknown_chars": unknown_names,
        "non_tb_chars": non_tb_names,
        "non_base3_chars": non_base3_names,
        "loric_chars": loric_names,
        "analysis_facts": facts,
    }


def _build_analysis_facts(
    *, rating, is_homebrew, is_amnesiac,
    tb_overlap, base3_overlap, non_tb_names, non_base3_names,
    loric_names, score10_chars, score9_chars, unknown_names,
) -> str:
    """Baut eine kompakte Fakten-Zusammenfassung für den LLM-Prompt."""
    lines = [f"RATING: {rating}"]

    if is_homebrew:
        lines.append(f"HOMEBREW: Ja — unbekannte Charaktere: {', '.join(unknown_names)}")
    if is_amnesiac:
        lines.append("AMNESIAC: >50% der Charaktere sind Amnesiac")

    lines.append(f"TB-Überlappung: {tb_overlap:.0%}")
    lines.append(f"Base3-Überlappung (TB+BMR+S&V): {base3_overlap:.0%}")

    if non_tb_names:
        lines.append(f"Nicht in TB: {', '.join(non_tb_names)}")
    if non_base3_names:
        lines.append(f"Nicht in Base3: {', '.join(non_base3_names)}")
    if score10_chars:
        lines.append(f"Game Changer (Score 10): {', '.join(score10_chars)}")
    if score9_chars:
        lines.append(f"Anspruchsvoll (Score 9): {', '.join(score9_chars)}")
    if loric_names:
        lines.append(f"Lorics: {', '.join(loric_names)}")

    return "\n".join(lines)


# ── Label-Berechnung ──────────────────────────────────────────────────

def compute_label(fields: dict) -> str | None:
    """Berechnet das Event-Label anhand der gesammelten Felder.

    Returns:
        Label-Key (z.B. "green") oder None wenn noch nicht bestimmbar.
    """
    # Neuer Pfad: complexity_analysis vorhanden
    analysis = fields.get("complexity_analysis")
    if analysis and analysis.get("rating"):
        if analysis.get("is_homebrew") or analysis.get("is_amnesiac"):
            return "hammer"
        return analysis["rating"]

    # Fallback: alter statischer Pfad
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

    return None


def build_title_prefix(fields: dict) -> str:
    """Baut den additiven Emoji-Prefix für den Event-Titel.

    Reihenfolge: [recorded] [academy|casual] [homebrew] [complexity]
    """
    if fields.get("is_free_choice"):
        return FREE_CHOICE_EMOJI

    parts = []
    analysis = fields.get("complexity_analysis") or {}

    # 1. Recorded
    if fields.get("is_recorded"):
        parts.append(LABEL_EMOJI["camera"])

    # 2. Academy ODER Casual (Academy hat Vorrang)
    if fields.get("is_academy"):
        parts.append(LABEL_EMOJI["academy"])
    elif fields.get("is_casual"):
        parts.append(LABEL_EMOJI["dove"])

    # 3. Homebrew
    if analysis.get("is_homebrew") or analysis.get("is_amnesiac"):
        parts.append(LABEL_EMOJI["hammer"])

    # 4. Complexity Rating
    rating = analysis.get("rating")
    if rating in ("green", "yellow", "red"):
        parts.append(LABEL_EMOJI[rating])

    return " ".join(parts)


def get_label_emoji(label: str | None, is_free_choice: bool = False) -> str:
    """Gibt das Emoji für ein Label zurück, oder leer wenn None."""
    if is_free_choice:
        return FREE_CHOICE_EMOJI
    if label is None:
        return ""
    return LABEL_EMOJI.get(label, "")
