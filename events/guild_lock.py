"""Server-Lock: Der Bot arbeitet nur auf den Servern aus ALLOWED_GUILD_IDS.

Der übrige Code bleibt mehrserverfähig. Ist die Variable leer oder fehlt sie, verlässt der
Bot keinen Server (Schutz vor Tippfehlern), verweigert aber alle Interaktionen.
"""

from __future__ import annotations

import os

ENV_VAR = "ALLOWED_GUILD_IDS"


def parse_guild_ids(raw: str | None) -> frozenset[int]:
    """„123, 456“ → {123, 456}. Ungültige Einträge sind ein Fehler, kein stilles Ignorieren."""
    if not raw or not raw.strip():
        return frozenset()
    ids = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(f"{ENV_VAR} enthält keine gültige Server-ID: {part!r}")
        ids.add(int(part))
    return frozenset(ids)


def allowed_guild_ids() -> frozenset[int]:
    return parse_guild_ids(os.getenv(ENV_VAR))


def is_configured() -> bool:
    return bool(allowed_guild_ids())


def is_allowed(guild_id: int | None) -> bool:
    """Darf der Bot auf diesem Server arbeiten? Ohne Konfiguration: nirgends."""
    return guild_id is not None and guild_id in allowed_guild_ids()


def should_leave(guild_id: int) -> bool:
    """Server verlassen? Nur wenn der Lock konfiguriert ist und der Server fehlt."""
    return is_configured() and guild_id not in allowed_guild_ids()
