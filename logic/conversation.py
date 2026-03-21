"""Session-Management und LLM-Calls für die Event-Erstellung.

Verwaltet Multi-Turn-Konversationen mit Claude Haiku 4.5 in Discord-DMs.
"""

import asyncio
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
    DESCRIPTION_PROMPT,
    INITIAL_USER_MESSAGE,
    MAX_TOKENS,
    MODEL,
    PRICE_INPUT_PER_MTOK,
    PRICE_OUTPUT_PER_MTOK,
    SYSTEM_PROMPT_TEMPLATE,
)
from logic.label import compute_label

logger = logging.getLogger(__name__)

BERLIN_TZ = ZoneInfo("Europe/Berlin")
SESSION_TIMEOUT_SECONDS = 5 * 60  # 5 Minuten

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
        "is_casual": None, "is_recorded": None,
        "script_complexity": None, "script_version": None, "is_free_choice": None,
    })
    messages: list = field(default_factory=list)  # Anthropic message history
    last_update: float = field(default_factory=time.time)
    label: str | None = None
    user_display_name: str = ""
    user_avatar_url: str = ""
    rules_summary: str = DEFAULT_RULES
    # Kosten-Tracking
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    call_count: int = 0
    # Concurrency Lock
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def is_expired(self) -> bool:
        return (time.time() - self.last_update) > SESSION_TIMEOUT_SECONDS

    def touch(self):
        self.last_update = time.time()


# In-Memory Session-Storage: user_id → EventSession
_sessions: dict[int, EventSession] = {}

# Kürzlich abgelaufene Sessions: user_id → expiry timestamp
_recently_expired: dict[int, float] = {}
_RECENTLY_EXPIRED_TTL = 60  # 1 Minute merken


def start_session(
    user_id: int,
    guild_id: int,
    guild_name: str,
    event_channel_id: int,
    user_display_name: str = "",
    user_avatar_url: str = "",
    rules_summary: str = DEFAULT_RULES,
) -> EventSession:
    """Startet eine neue Event-Erstellungs-Session."""
    _recently_expired.pop(user_id, None)
    session = EventSession(
        user_id=user_id,
        guild_id=guild_id,
        guild_name=guild_name,
        event_channel_id=event_channel_id,
        user_display_name=user_display_name,
        user_avatar_url=user_avatar_url,
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
        _recently_expired[user_id] = time.time()
        end_session(user_id)
        return None
    return session


def end_session(user_id: int):
    """Beendet eine Session."""
    removed = _sessions.pop(user_id, None)
    if removed:
        logger.info(
            "Session beendet: user=%s (calls=%d, cost=$%.4f)",
            user_id, removed.call_count, removed.total_cost_usd,
        )


def has_active_session(user_id: int) -> bool:
    """Prüft ob ein User eine aktive (nicht abgelaufene) Session hat."""
    return get_session(user_id) is not None


def was_recently_expired(user_id: int) -> bool:
    """Prüft ob ein User kürzlich eine abgelaufene Session hatte."""
    expired_at = _recently_expired.get(user_id)
    if expired_at is None:
        return False
    if (time.time() - expired_at) > _RECENTLY_EXPIRED_TTL:
        _recently_expired.pop(user_id, None)
        return False
    return True


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
        user_display_name=session.user_display_name or "User",
    )


def _strip_markdown_fences(text: str) -> str:
    """Entfernt Markdown-Code-Fences von der Antwort."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
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
        session.messages.pop()
        return None

    raw_text = response.content[0].text
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    call_cost = (input_tokens * PRICE_INPUT_PER_MTOK + output_tokens * PRICE_OUTPUT_PER_MTOK) / 1_000_000

    # Session-Tracking aktualisieren
    session.total_input_tokens += input_tokens
    session.total_output_tokens += output_tokens
    session.total_cost_usd += call_cost
    session.call_count += 1

    logger.debug(
        "Haiku-Response: tokens_in=%d, tokens_out=%d, cost=$%.5f (session total: $%.5f, %d calls)",
        input_tokens, output_tokens, call_cost, session.total_cost_usd, session.call_count,
    )
    logger.debug("Haiku raw: %s", raw_text[:500])

    parsed = _parse_response(raw_text)
    if parsed is None:
        session.messages.append({"role": "assistant", "content": raw_text})
        return None

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
    """Startet die Konversation mit einer initialen Nachricht."""
    return await call_haiku(session, INITIAL_USER_MESSAGE)


async def generate_description(session: EventSession) -> str | None:
    """Generiert eine Event-Beschreibung basierend auf den gesammelten Feldern.

    Separater LLM-Call, nicht Teil der Konversation.
    Returns: Beschreibungstext oder None bei Fehler.
    """
    fields = session.fields
    prompt = DESCRIPTION_PROMPT.format(
        script=fields.get("script") or "Unbekannt",
        storyteller=fields.get("storyteller") or session.user_display_name,
        level=fields.get("level") or "Alle",
        start_time=fields.get("start_time") or "TBD",
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        logger.error("Description-Generierung fehlgeschlagen: %s", e)
        return None

    text = response.content[0].text.strip()
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    call_cost = (input_tokens * PRICE_INPUT_PER_MTOK + output_tokens * PRICE_OUTPUT_PER_MTOK) / 1_000_000

    session.total_input_tokens += input_tokens
    session.total_output_tokens += output_tokens
    session.total_cost_usd += call_cost
    session.call_count += 1

    logger.debug("Description generiert: %d tokens, $%.5f", output_tokens, call_cost)
    return text
