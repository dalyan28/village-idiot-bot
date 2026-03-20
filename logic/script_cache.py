"""Script-Cache und Lookup-Kette für BotC-Scripts.

Lookup-Reihenfolge:
1. Base Scripts (TB, BMR, S&V) → sofort erkannt via Aliases
2. Cache Hit + TTL ok → aus script_cache.json
3. Cache Hit + TTL abgelaufen → alten Eintrag zurückgeben (Refresh extern)
4. Cache Miss → None (Caller muss botcscripts.com konsultieren)
"""

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Statische Dateien aus Git — MUSS außerhalb des Railway-Volume-Mounts liegen
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
BASE_SCRIPTS_FILE = os.path.join(STATIC_DIR, "base_scripts.json")
CHARACTERS_FILE = os.path.join(STATIC_DIR, "characters.json")

# Cache auf Volume (Railway) oder lokal im data/ Ordner
CACHE_FILE = os.path.join(
    os.getenv("RAILWAY_VOLUME_MOUNT_PATH", os.path.join(PROJECT_ROOT, "data")),
    "script_cache.json",
)

CACHE_TTL_DAYS = 30

# Lazy-loaded data
_base_scripts: dict | None = None
_characters: dict | None = None


def normalize_name(name: str) -> str:
    """Normalisiert einen Script-Namen für Cache-Lookups."""
    return name.strip().lower()


# ── Base Scripts ─────────────────────────────────────────────────────────────


def _load_base_scripts() -> dict:
    global _base_scripts
    if _base_scripts is not None:
        return _base_scripts
    with open(BASE_SCRIPTS_FILE, "r", encoding="utf-8") as f:
        _base_scripts = json.load(f)
    logger.debug("Base Scripts geladen: %d", len(_base_scripts))
    return _base_scripts


def is_base_script(query: str) -> bool:
    """Prüft ob eine Query ein Base Script matcht."""
    return lookup_base_script(query) is not None


def lookup_base_script(query: str) -> dict | None:
    """Sucht in den Base Scripts nach einem Match via Aliases."""
    normalized = normalize_name(query)
    base = _load_base_scripts()
    for key, script in base.items():
        if normalized == key or normalized in [a.lower() for a in script["aliases"]]:
            logger.debug("Base Script erkannt: '%s' → %s", query, script["name"])
            return script
    return None


# ── Characters ───────────────────────────────────────────────────────────────


def load_characters() -> dict:
    """Lädt die offizielle Charakterdatenbank.

    Returns:
        Dict von character_id → {character_name, character_type, ability, ...}
    """
    global _characters
    if _characters is not None:
        return _characters

    if not os.path.exists(CHARACTERS_FILE):
        logger.warning("characters.json nicht gefunden: %s", CHARACTERS_FILE)
        return {}

    with open(CHARACTERS_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    _characters = {}
    for entry in raw:
        pk = entry.get("pk", "")
        fields = entry.get("fields", {})
        _characters[pk] = {
            "character_name": fields.get("character_name", pk),
            "character_type": fields.get("character_type", ""),
            "ability": fields.get("ability", ""),
            "edition": fields.get("edition", 0),
        }

    logger.debug("Charakterdatenbank geladen: %d Charaktere", len(_characters))
    return _characters


# ── Script Cache ─────────────────────────────────────────────────────────────


def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _is_expired(entry: dict) -> bool:
    """Prüft ob ein Cache-Eintrag abgelaufen ist."""
    last_checked = entry.get("last_checked")
    if not last_checked:
        return True
    try:
        checked_dt = datetime.fromisoformat(last_checked)
        age_days = (datetime.now(timezone.utc) - checked_dt).days
        return age_days > CACHE_TTL_DAYS
    except (ValueError, TypeError):
        return True


def lookup_cached_script(query: str) -> tuple[dict | None, bool]:
    """Sucht ein Script im Cache.

    Returns:
        (script_data, needs_refresh) — script_data ist None bei Cache-Miss,
        needs_refresh ist True wenn der TTL abgelaufen ist.
    """
    normalized = normalize_name(query)
    cache = _load_cache()

    # Exakter Match auf normalisierten Key
    entry = cache.get(normalized)
    if entry:
        expired = _is_expired(entry)
        logger.debug(
            "Cache %s: '%s' (expired=%s)",
            "hit" if not expired else "hit (stale)", query, expired,
        )
        return entry, expired

    # Suche über gespeicherte Namen (falls Key anders ist als Query)
    for key, entry in cache.items():
        if normalize_name(entry.get("name", "")) == normalized:
            expired = _is_expired(entry)
            logger.debug("Cache hit via name: '%s' → key='%s'", query, key)
            return entry, expired

    logger.debug("Cache miss: '%s'", query)
    return None, False


def cache_script(name: str, data: dict):
    """Speichert ein Script im Cache.

    Args:
        name: Der Script-Name (wird als Key normalisiert).
        data: Dict mit mindestens {name, botcscripts_id, version, author, characters, url}.
    """
    cache = _load_cache()
    key = normalize_name(name)
    data["last_checked"] = datetime.now(timezone.utc).isoformat()
    cache[key] = data
    _save_cache(cache)
    logger.info("Script gecacht: '%s' (id=%s, v%s)", name, data.get("botcscripts_id"), data.get("version"))


def refresh_cached_script(name: str, data: dict):
    """Aktualisiert einen bestehenden Cache-Eintrag mit neuen Daten."""
    cache_script(name, data)


# ── Haupt-Lookup ─────────────────────────────────────────────────────────────


def lookup_script(query: str) -> tuple[dict | None, str]:
    """Haupt-Lookup-Funktion. Prüft Base Scripts, dann Cache.

    Returns:
        (script_data, source) — source ist "base", "cache", "cache_stale" oder "miss"
    """
    # 1. Base Scripts
    base = lookup_base_script(query)
    if base:
        return base, "base"

    # 2. Cache
    cached, needs_refresh = lookup_cached_script(query)
    if cached and not needs_refresh:
        return cached, "cache"
    if cached and needs_refresh:
        return cached, "cache_stale"

    # 3. Miss
    return None, "miss"


# ── Script-JSON Validierung (für Uploads) ────────────────────────────────────


def validate_script_json(data) -> tuple[dict | None, str | None]:
    """Validiert und parst eine hochgeladene BotC Script-JSON.

    Erwartetes Format: [{_meta}, {id: "character_id"}, ...]
    Auch akzeptiert: ["character_id", ...] (String-Array-Format)

    Returns:
        (parsed_data, error_message) — parsed_data ist None bei Fehler.
        parsed_data enthält: {name, author, characters, source: "upload"}
    """
    if not isinstance(data, list):
        return None, "Ungültiges Format: Erwartet wird eine JSON-Liste (Array)."

    if len(data) == 0:
        return None, "Leere Script-JSON. Mindestens ein Charakter wird erwartet."

    meta = {}
    characters = []

    for item in data:
        if isinstance(item, str):
            # String-Array-Format: ["washerwoman", "librarian", ...]
            characters.append(item)
        elif isinstance(item, dict):
            if item.get("id") == "_meta":
                meta = item
            elif item.get("id"):
                characters.append(item["id"])
        # Andere Einträge werden ignoriert

    if not characters:
        return None, "Keine Charaktere in der JSON gefunden. Erwartet: `[{\"id\": \"character_id\"}, ...]`"

    parsed = {
        "name": meta.get("name", "Custom Script"),
        "author": meta.get("author", ""),
        "characters": characters,
        "source": "upload",
    }

    logger.info(
        "Script-JSON validiert: '%s' von '%s' (%d Charaktere)",
        parsed["name"], parsed["author"], len(characters),
    )
    return parsed, None
