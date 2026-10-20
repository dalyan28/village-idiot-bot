"""Abweichungen vom klassischen Clocktower (Label ⭐).

⭐ = „Hier gibt es eine Abweichung von traditionellem Clocktower (Homebrew, Lorics oder andere
Auffälligkeiten) – bitte die Beschreibung lesen!“ (Dalyan, 20.10.2026; ersetzt ⚒️ für Homebrew).

Gesetzt wird es, wenn das Skript Homebrew-Charaktere oder Lorics enthält oder überwiegend aus dem
Amnesiac besteht. Homebrew und Lorics erkennt der Bot selbst (Charakterdatenbank), das
All-Amnesiac-Skript meldet der ScriptRater (`metrics.is_amnesiac`).
"""

from __future__ import annotations

from events.schema import SCRIPT_FREE, ScriptRef
from logic.script_cache import load_characters

NAME_LIMIT = 5
TEENSY_TYPE = "Teensyville"   # script_type auf botcscripts.com
TEENSY_MAX_TOWNSFOLK = 6      # Faustregel für Skripte ohne Angabe (z. B. Uploads)


def is_teensy(script: ScriptRef | None, script_type: str | None = None) -> bool:
    """Teensyville? botcscripts.com sagt es über script_type, sonst höchstens 6 Townsfolk."""
    if script is None or script.kind == SCRIPT_FREE:
        return False
    if script_type:
        return script_type == TEENSY_TYPE
    db = load_characters()
    content = {item["id"]: item for item in (script.content or []) if isinstance(item, dict) and item.get("id")}
    townsfolk = 0
    for c in script.characters:
        team = db[c].get("character_type", "") if c in db else str(content.get(c, {}).get("team", ""))
        townsfolk += team.lower() == "townsfolk"
    return 0 < townsfolk <= TEENSY_MAX_TOWNSFOLK


def _names(names: list[str]) -> str:
    if len(names) <= NAME_LIMIT:
        return ", ".join(names)
    return ", ".join(names[:NAME_LIMIT]) + f" und {len(names) - NAME_LIMIT} weitere"


def special_reasons(script: ScriptRef | None, is_amnesiac: bool = False, rater_homebrew: bool = False) -> list[str]:
    """Gründe für ⭐ als kurze Sätze; leer = keine Abweichung."""
    if script is None or script.kind == SCRIPT_FREE:
        return []
    db = load_characters()
    content = {item["id"]: item for item in (script.content or []) if isinstance(item, dict) and item.get("id")}

    homebrew = [content.get(c, {}).get("name") or c for c in script.characters if c not in db]
    lorics = [db[c]["character_name"] for c in script.characters
              if c in db and db[c].get("character_type", "").lower() == "loric"]

    reasons = []
    if homebrew:
        reasons.append(f"Homebrew-Charaktere: {_names(homebrew)}")
    elif rater_homebrew:
        reasons.append("Enthält Homebrew-Charaktere")
    if lorics:
        reasons.append(f"{'Loric' if len(lorics) == 1 else 'Lorics'}: {_names(lorics)}")
    if is_amnesiac:
        reasons.append("Überwiegend Amnesiac (All-Amnesiac-Skript)")
    return reasons
