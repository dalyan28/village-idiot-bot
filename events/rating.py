"""Einschätzung eines Skripts (grün/gelb/rot) über den ScriptRater.

Der Algorithmus lebt im ScriptRater (widow-botc.com/script-check), nicht im Bot. Gelesen werden
nur `rating`, `headline`, `reasons` und `metrics.is_homebrew`. Ist der ScriptRater nicht
erreichbar oder die Antwort unlesbar, gibt `rate_script` None zurück und der Storyteller
schätzt selbst ein. Die Basis-Skripte haben eine feste Einschätzung.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

import requests

from events.schema import RATINGS, SCRIPT_BASE, SCRIPT_FREE, ScriptRef
from events.templates import BASE3_RATINGS

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://widow-botc.com/script-check"
TIMEOUT_SECONDS = 15


@dataclass
class RatingResult:
    rating: str
    headline: str = ""
    reasons: list[str] = field(default_factory=list)
    is_homebrew: bool = False


def rater_url() -> str:
    return os.getenv("SCRIPT_RATER_URL", DEFAULT_URL).rstrip("/")


def parse_response(payload) -> RatingResult | None:
    """Liest die Antwort von /api/analyse. Unbekanntes Format → None."""
    if not isinstance(payload, dict) or payload.get("rating") not in RATINGS:
        return None
    reasons = payload.get("reasons")
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    return RatingResult(
        rating=payload["rating"],
        headline=str(payload.get("headline") or ""),
        reasons=[str(r) for r in reasons] if isinstance(reasons, list) else [],
        is_homebrew=bool(metrics.get("is_homebrew") or metrics.get("is_amnesiac")),
    )


def _request(body) -> RatingResult | None:
    try:
        r = requests.post(f"{rater_url()}/api/analyse", json=body, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        logger.warning("ScriptRater nicht erreichbar: %s", e)
        return None
    if r.status_code != 200:
        logger.warning("ScriptRater antwortet %s: %s", r.status_code, r.text[:200])
        return None
    try:
        result = parse_response(r.json())
    except ValueError:
        result = None
    if result is None:
        logger.warning("ScriptRater-Antwort unlesbar: %s", r.text[:200])
    return result


async def rate_script(script: ScriptRef) -> RatingResult | None:
    """Einschätzung für ein Skript. Basis-3 fest, freie Wahl ohne Einschätzung."""
    if script.kind == SCRIPT_FREE:
        return None
    if script.kind == SCRIPT_BASE:
        rating = BASE3_RATINGS.get(script.base_key)
        return RatingResult(rating=rating, headline="Feste Einschätzung für das Basis-Skript.") if rating else None
    # Hochgeladene Skripte mit komplettem Inhalt schicken (Homebrew-Charaktere), sonst die IDs
    body = script.content if script.content else {"characters": script.characters}
    if not body:
        return None
    return await asyncio.to_thread(_request, body)
