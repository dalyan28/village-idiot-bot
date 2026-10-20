"""Testserver für die Admins: nur auf Branch `testserver`, wird nicht gemergt.

Alles läuft nur mit TEST_SERVER=1 und nur auf den Servern aus TEST_GUILD_IDS. Ohne die
Variable verhält sich der Bot exakt wie auf `event-wizard`: Der Cog wird nicht geladen, die
Hooks im Bestandscode (Kommentar `# TESTSERVER`) tun nichts.

Anleitung: docs/testserver.md
"""

from __future__ import annotations

import os

ENV_SWITCH = "TEST_SERVER"
ENV_GUILDS = "TEST_GUILD_IDS"


def enabled() -> bool:
    return os.getenv(ENV_SWITCH) == "1"


def test_guild_ids() -> frozenset[int]:
    """„123, 456“ → {123, 456}. Ungültige Einträge werden ignoriert (nur Testbetrieb)."""
    raw = os.getenv(ENV_GUILDS) or ""
    return frozenset(int(p) for p in raw.replace(";", ",").split(",") if p.strip().isdigit())


def is_test_guild(guild_id: int | None) -> bool:
    """Ist das ein freigegebener Testserver? Nur dann gibt es Setup, Reset und Feedback."""
    return enabled() and guild_id is not None and guild_id in test_guild_ids()
