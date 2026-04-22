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
    INITIAL_USER_MESSAGE,
    MAX_TOKENS,
    MODEL,
    PRICE_INPUT_PER_MTOK,
    PRICE_OUTPUT_PER_MTOK,
    SYSTEM_PROMPT_TEMPLATE,
    TITLE_DESCRIPTION_PROMPT,
    TITLE_DESCRIPTION_UPDATE_PROMPT,
    SCRIPT_CHOICE_FALLBACK_PROMPT,
)
from logic.label import compute_label, enforce_label_mutex

logger = logging.getLogger(__name__)

BERLIN_TZ = ZoneInfo("Europe/Berlin")
SESSION_TIMEOUT_SECONDS = 5 * 60  # 5 Minuten Inaktivität
RESUMABLE_TTL_SECONDS = 60 * 60  # 1 Stunde Wiederaufnahme-Fenster

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
        "is_casual": None, "is_recorded": None, "is_academy": None,
        "script_complexity": None, "script_version": None, "is_free_choice": None,
        "complexity_analysis": None,
    })
    messages: list = field(default_factory=list)  # Anthropic message history
    last_update: float = field(default_factory=time.time)
    label: str | None = None
    user_display_name: str = ""
    user_avatar_url: str = ""
    rules_summary: str = DEFAULT_RULES
    # Edit-Modus (wenn bestehendes Event bearbeitet wird)
    editing_message_id: int | None = None
    editing_channel_id: int | None = None
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

# Pausierte Sessions (nach Inaktivitäts-Timeout), 1h wiederaufnehmbar.
# Key = user_id, Value = EventSession (mit touch-Zeitstempel auf Moment der Pausierung).
_resumable_sessions: dict[int, EventSession] = {}


def _cleanup_resumable():
    """Entfernt abgelaufene Wiederaufnahme-Sessions (>1h alt)."""
    now = time.time()
    for uid, sess in list(_resumable_sessions.items()):
        if (now - sess.last_update) > RESUMABLE_TTL_SECONDS:
            _resumable_sessions.pop(uid, None)
            logger.info("Wiederaufnahme-Fenster abgelaufen: user=%s", uid)


def start_session(
    user_id: int,
    guild_id: int,
    guild_name: str,
    event_channel_id: int,
    user_display_name: str = "",
    user_avatar_url: str = "",
    rules_summary: str = DEFAULT_RULES,
) -> EventSession:
    """Startet eine neue Event-Erstellungs-Session.

    Eine evtl. vorhandene wiederaufnehmbare Session wird hier NICHT verworfen —
    der Caller zeigt dem User erst ein Resume-Angebot. Wenn der User sich gegen
    Resume entscheidet (schreibt was anderes als das Resume-Keyword), wird die
    alte resumable erst in diesem Moment verworfen (siehe discard_resumable).
    """
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
    """Gibt die aktive Session zurück, oder None.

    Bei Inaktivitäts-Timeout wird die Session nicht gelöscht, sondern in
    `_resumable_sessions` verschoben — der User kann sie innerhalb 1h per
    `wiederaufnehmen` reaktivieren.
    """
    session = _sessions.get(user_id)
    if session is None:
        return None
    if session.is_expired():
        logger.info("Session pausiert (wiederaufnehmbar): user=%s", user_id)
        _sessions.pop(user_id, None)
        _resumable_sessions[user_id] = session
        return None
    return session


def end_session(user_id: int):
    """Beendet eine Session endgültig (Cancel, Erstellen, Max-Calls).

    Verwirft auch eine evtl. wiederaufnehmbare Session — nach explizitem Ende
    gibt es nichts mehr zum Wiederaufnehmen.
    """
    removed = _sessions.pop(user_id, None)
    _resumable_sessions.pop(user_id, None)
    if removed:
        logger.info(
            "Session beendet: user=%s (calls=%d, cost=$%.4f)",
            user_id, removed.call_count, removed.total_cost_usd,
        )


def has_active_session(user_id: int) -> bool:
    """Prüft ob ein User eine aktive (nicht pausierte) Session hat."""
    return get_session(user_id) is not None


def has_resumable_session(user_id: int) -> bool:
    """Prüft ob der User eine pausierte, noch wiederaufnehmbare Session hat."""
    _cleanup_resumable()
    return user_id in _resumable_sessions


def resume_session(user_id: int) -> EventSession | None:
    """Reaktiviert eine pausierte Session. Gibt die Session zurück oder None."""
    _cleanup_resumable()
    session = _resumable_sessions.pop(user_id, None)
    if session is None:
        return None
    session.touch()
    _sessions[user_id] = session
    logger.info("Session wiederaufgenommen: user=%s", user_id)
    return session


def discard_resumable(user_id: int) -> None:
    """Verwirft eine wiederaufnehmbare Session (User hat sich gegen Resume
    entschieden oder hat ein neues Event ohne Wiederaufnahme gestartet)."""
    removed = _resumable_sessions.pop(user_id, None)
    if removed is not None:
        logger.info("Wiederaufnahme verworfen: user=%s", user_id)


def peek_resumable(user_id: int) -> EventSession | None:
    """Liest die resumable Session ohne sie zu aktivieren — nur für UI-Infos
    (z.B. Titel/Skript im Resume-Angebot). Gibt None zurück, wenn keine vorhanden."""
    _cleanup_resumable()
    return _resumable_sessions.get(user_id)


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
    """Parst die JSON-Antwort von Haiku.

    Mehrstufiger Fallback: zuerst direkt, dann Code-Fence-strip, dann das
    größte `{…}`-Substring greedy extrahieren. Haiku schreibt gelegentlich
    Prosa um das JSON herum — das soll uns nicht killen.
    """
    stripped = _strip_markdown_fences(raw_text)
    # (1) Direkt als JSON
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # (2) Größtes {…}-Substring (greedy) extrahieren
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last > first:
        candidate = stripped[first : last + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    logger.warning(
        "Ungültiges JSON von Haiku (auch nach Fallback). Raw (500): %s",
        raw_text[:500],
    )
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
        # Kaputte Response NICHT in die History schreiben — das würde Folge-Calls
        # kontaminieren (Haiku „lernt", dass Prosa-Antworten OK sind).
        # Auch die user-Message wieder rausnehmen, damit der nächste Call
        # mit intakter History neu ansetzen kann.
        if session.messages and session.messages[-1].get("role") == "user":
            session.messages.pop()
        return None

    session.messages.append({"role": "assistant", "content": raw_text})

    action = parsed.get("action", "ask")

    # Felder nur bei ask/done updaten, NICHT bei refuse
    if action in ("ask", "done", "explain"):
        new_fields = parsed.get("fields", {})
        for key, value in new_fields.items():
            if value is not None:
                session.fields[key] = value
        enforce_label_mutex(session.fields)

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


def _call_llm_simple(session: EventSession, prompt: str) -> str | None:
    """Einfacher LLM-Call ohne Konversations-History. Returns raw text."""
    try:
        client = _get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        logger.error("LLM-Call fehlgeschlagen: %s", e)
        return None

    text = response.content[0].text.strip()
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    call_cost = (input_tokens * PRICE_INPUT_PER_MTOK + output_tokens * PRICE_OUTPUT_PER_MTOK) / 1_000_000

    session.total_input_tokens += input_tokens
    session.total_output_tokens += output_tokens
    session.total_cost_usd += call_cost
    session.call_count += 1

    return text


async def generate_title_and_description(session: EventSession) -> tuple[str, str, str] | None:
    """Generiert Titel, Beschreibung und Reasoning basierend auf den Event-Feldern.

    Returns: (title, description, reasoning) oder None bei Fehler.
    """
    fields = session.fields
    co_st = fields.get("co_storyteller") or "Kein Co-ST"
    casual = "Ja" if fields.get("is_casual") else "Nein"
    academy = "Ja" if fields.get("is_academy") else "Nein"
    analysis = fields.get("complexity_analysis") or {}

    prompt = TITLE_DESCRIPTION_PROMPT.format(
        script=fields.get("script") or "Unbekannt",
        storyteller=fields.get("storyteller") or session.user_display_name,
        co_storyteller=co_st,
        level=fields.get("level") or "Alle",
        start_time=fields.get("start_time") or "TBD",
        is_casual=casual,
        is_academy=academy,
        analysis_facts=analysis.get("analysis_facts", "Keine Analyse verfügbar"),
    )

    raw = await asyncio.to_thread(_call_llm_simple, session, prompt)
    if not raw:
        return None

    # JSON parsen
    cleaned = _strip_markdown_fences(raw)
    try:
        data = json.loads(cleaned)
        title = data.get("title", "")
        description = data.get("description", "")
        reasoning = data.get("reasoning", "")
        if title and description:
            logger.debug("Titel/Beschreibung/Reasoning generiert")
            return title, description, reasoning
    except json.JSONDecodeError:
        logger.warning("Titel/Beschreibung JSON ungültig: %s", cleaned[:200])

    return None


async def update_title_description(session: EventSession, user_input: str) -> tuple[str, str, bool] | None:
    """Verarbeitet Freitext-Änderungen an Titel/Beschreibung.

    Returns: (new_title, new_description, accepted) oder None bei Fehler.
    accepted=True wenn User zufrieden ist (keine Änderung).
    """
    prompt = TITLE_DESCRIPTION_UPDATE_PROMPT.format(
        current_title=session.fields.get("title") or "",
        current_description=session.fields.get("description") or "",
        user_input=user_input,
    )

    raw = await asyncio.to_thread(_call_llm_simple, session, prompt)
    if not raw:
        return None

    cleaned = _strip_markdown_fences(raw)
    try:
        data = json.loads(cleaned)
        title = data.get("title", session.fields.get("title", ""))
        description = data.get("description", session.fields.get("description", ""))
        accepted = data.get("accepted", False)
        return title, description, accepted
    except json.JSONDecodeError:
        logger.warning("Title/Desc Update JSON ungültig: %s", cleaned[:200])

    return None


async def interpret_script_choice(session: EventSession, user_input: str, choices: list) -> dict | None:
    """Haiku interpretiert natürliche Sprache bei der Script-Auswahl.

    Returns: dict mit action, index, search_term, message oder None bei Fehler.
    """
    script_list = ""
    for i, c in enumerate(choices, 1):
        au = c.get("author", "?")
        ve = c.get("version", "?")
        ch = c.get("characters", [])
        cnt = f", {len(ch)} Chars" if ch else ""
        script_list += f"{i}. {c['name']} (von {au}, v{ve}{cnt})\n"

    prompt = SCRIPT_CHOICE_FALLBACK_PROMPT.format(
        script_list=script_list.strip(),
        user_input=user_input,
    )

    raw = await asyncio.to_thread(_call_llm_simple, session, prompt)
    if not raw:
        return None

    cleaned = _strip_markdown_fences(raw)
    try:
        data = json.loads(cleaned)
        action = data.get("action")
        if action in ("select", "search", "upload", "skip", "preview", "unclear"):
            return data
    except json.JSONDecodeError:
        logger.warning("Script-Choice Fallback JSON ungültig: %s", cleaned[:200])

    return None


async def interpret_final_review(session: EventSession, user_input: str, fields_summary: str) -> dict | None:
    """Haiku interpretiert Eingaben im Abschluss-Screen (Batch-Edits, Bestätigung, etc.).

    Returns: dict mit action, fields, message oder None bei Fehler.
    """
    from logic.llm_config import FINAL_REVIEW_FALLBACK_PROMPT

    now = datetime.now(ZoneInfo("Europe/Berlin"))
    today_date = now.strftime("%Y-%m-%d")
    weekdays = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    today_weekday = weekdays[now.weekday()]

    prompt = FINAL_REVIEW_FALLBACK_PROMPT.format(
        fields_summary=fields_summary,
        user_input=user_input,
        today_date=today_date,
        today_weekday=today_weekday,
    )

    raw = await asyncio.to_thread(_call_llm_simple, session, prompt)
    if not raw:
        return None

    cleaned = _strip_markdown_fences(raw)
    try:
        data = json.loads(cleaned)
        action = data.get("action")
        if action in ("edit", "confirm", "change_script", "change_version", "unclear"):
            return data
    except json.JSONDecodeError:
        logger.warning("Final-Review Fallback JSON ungültig: %s", cleaned[:200])

    return None


async def interpret_script_preview(session: EventSession, user_input: str, script_names: str) -> dict | None:
    """Haiku interpretiert Eingaben in der Script-Vorschau.

    Returns: dict mit action, index, message oder None bei Fehler.
    """
    from logic.llm_config import SCRIPT_PREVIEW_FALLBACK_PROMPT

    prompt = SCRIPT_PREVIEW_FALLBACK_PROMPT.format(
        script_names=script_names,
        user_input=user_input,
    )

    raw = await asyncio.to_thread(_call_llm_simple, session, prompt)
    if not raw:
        return None

    cleaned = _strip_markdown_fences(raw)
    try:
        data = json.loads(cleaned)
        action = data.get("action")
        if action in ("select", "back", "unclear"):
            return data
    except json.JSONDecodeError:
        logger.warning("Script-Preview Fallback JSON ungültig: %s", cleaned[:200])

    return None
