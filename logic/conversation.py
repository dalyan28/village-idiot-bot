"""Session-Management und LLM-Calls für die Event-Erstellung.

Verwaltet Multi-Turn-Konversationen mit Claude Haiku 4.5 in Discord-DMs.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

from logic.llm_config import (
    DEFAULT_RULES,
    INITIAL_USER_MESSAGE,
    MAX_TOKENS,
    MODEL,
    SYSTEM_PROMPT_TEMPLATE,
)
from logic.label import compute_label

logger = logging.getLogger(__name__)

BERLIN_TZ = ZoneInfo("Europe/Berlin")
SESSION_TIMEOUT_SECONDS = 30 * 60  # 30 Minuten

TAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

# Anthropic Client — lazy init
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


@dataclass
class EventSession:
    user_id: int
    guild_id: int
    guild_name: str
    event_channel_id: int
    fields: dict = field(default_factory=lambda: {
        "title": None, "script": None, "storyteller": None,
        "co_storyteller": None, "start_time": None, "duration_minutes": None,
        "max_players": None, "camera": None, "description": None, "level": None,
        "is_casual": None, "is_recorded": None, "tb_rounds_played": None,
        "script_complexity": None, "script_version": None, "is_free_choice": None,
    })
    messages: list = field(default_factory=list)  # Anthropic message history
    last_update: float = field(default_factory=time.time)
    label: str | None = None
    user_display_name: str = ""
    rules_summary: str = DEFAULT_RULES

    def is_expired(self) -> bool:
        return (time.time() - self.last_update) > SESSION_TIMEOUT_SECONDS

    def touch(self):
        self.last_update = time.time()


# In-Memory Session-Storage: user_id → EventSession
_sessions: dict[int, EventSession] = {}


def start_session(
    user_id: int,
    guild_id: int,
    guild_name: str,
    event_channel_id: int,
    user_display_name: str = "",
    rules_summary: str = DEFAULT_RULES,
) -> EventSession:
    """Startet eine neue Event-Erstellungs-Session."""
    session = EventSession(
        user_id=user_id,
        guild_id=guild_id,
        guild_name=guild_name,
        event_channel_id=event_channel_id,
        user_display_name=user_display_name,
        rules_summary=rules_summary,
    )
    _sessions[user_id] = session
    logger.info("Session gestartet: user=%s, guild=%s (%s)", user_id, guild_id, guild_name)
    return session


def get_session(user_id: int) -> EventSession | None:
    """Gibt die aktive Session für einen User zurück, oder None."""
    session = _sessions.get(user_id)
    if session is None:
        return None
    if session.is_expired():
        logger.info("Session abgelaufen: user=%s", user_id)
        end_session(user_id)
        return None
    return session


def end_session(user_id: int):
    """Beendet eine Session."""
    removed = _sessions.pop(user_id, None)
    if removed:
        logger.info("Session beendet: user=%s", user_id)


def has_active_session(user_id: int) -> bool:
    """Prüft ob ein User eine aktive (nicht abgelaufene) Session hat."""
    return get_session(user_id) is not None


def _build_system_prompt(session: EventSession) -> str:
    """Baut den System-Prompt mit aktuellen Daten zusammen."""
    now = datetime.now(BERLIN_TZ)
    today_date = now.strftime("%Y-%m-%d")
    today_weekday = TAGE[now.weekday()]

    rules = session.rules_summary or ""
    if rules:
        rules = f"## SERVER-REGELN\n{rules}"

    return SYSTEM_PROMPT_TEMPLATE.format(
        today_date=today_date,
        today_weekday=today_weekday,
        rules_summary=rules,
    )


def _strip_markdown_fences(text: str) -> str:
    """Entfernt Markdown-Code-Fences von der Antwort."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Erste Zeile (```json oder ```) entfernen
        lines = lines[1:]
        # Letzte Zeile (```) entfernen falls vorhanden
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _parse_response(raw_text: str) -> dict | None:
    """Parst die JSON-Antwort von Haiku."""
    cleaned = _strip_markdown_fences(raw_text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Ungültiges JSON von Haiku: %s", cleaned[:200])
        return None


async def call_haiku(session: EventSession, user_message: str) -> dict | None:
    """Ruft Claude Haiku mit der aktuellen Konversation auf.

    Args:
        session: Die aktive EventSession.
        user_message: Die Nachricht des Users.

    Returns:
        Geparste JSON-Antwort oder None bei Fehler.
        Format: {message, action, fields, missing_required, label_determined}
    """
    session.touch()

    # User-Nachricht zur History hinzufügen
    session.messages.append({"role": "user", "content": user_message})

    system_prompt = _build_system_prompt(session)

    logger.debug(
        "Haiku-Call: user=%s, messages=%d, prompt_len=%d",
        session.user_id, len(session.messages), len(system_prompt),
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=session.messages,
        )
    except anthropic.APIError as e:
        logger.error("Anthropic API-Fehler: %s", e)
        # Letzte User-Nachricht wieder entfernen bei Fehler
        session.messages.pop()
        return None

    raw_text = response.content[0].text
    logger.debug(
        "Haiku-Response: tokens_in=%d, tokens_out=%d",
        response.usage.input_tokens, response.usage.output_tokens,
    )
    logger.debug("Haiku raw: %s", raw_text[:500])

    parsed = _parse_response(raw_text)
    if parsed is None:
        # Ungültiges JSON — Haiku-Antwort trotzdem zur History hinzufügen
        session.messages.append({"role": "assistant", "content": raw_text})
        return None

    # Haiku-Antwort zur History hinzufügen (das rohe JSON, nicht die geparste Version)
    session.messages.append({"role": "assistant", "content": raw_text})

    action = parsed.get("action", "ask")

    # Felder nur bei ask/done updaten, NICHT bei refuse
    if action in ("ask", "done", "explain"):
        new_fields = parsed.get("fields", {})
        for key, value in new_fields.items():
            if value is not None:
                session.fields[key] = value

    # Label berechnen wenn möglich
    session.label = compute_label(session.fields)

    logger.info(
        "Haiku action=%s, missing=%s, label=%s",
        action, parsed.get("missing_required", []), session.label,
    )

    return parsed


async def start_conversation(session: EventSession) -> dict | None:
    """Startet die Konversation mit einer initialen Nachricht.

    Returns:
        Erste Haiku-Antwort oder None bei Fehler.
    """
    return await call_haiku(session, INITIAL_USER_MESSAGE)
