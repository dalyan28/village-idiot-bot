"""Script-Cache und Lookup-Kette für BotC-Scripts.

Lookup-Reihenfolge:
1. Base Scripts (TB, BMR, S&V) → sofort erkannt via Aliases
2. Cache Hit + TTL ok → aus script_cache.json
3. Cache Hit + TTL abgelaufen → alten Eintrag zurückgeben (Refresh extern)
4. Cache Miss → None (Caller muss botcscripts.com konsultieren)
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

# Statische Dateien aus Git — MUSS außerhalb des Railway-Volume-Mounts liegen
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
ICONS_DIR = os.path.join(STATIC_DIR, "icons")
BASE_SCRIPTS_FILE = os.path.join(STATIC_DIR, "base_scripts.json")
CHARACTERS_FILE = os.path.join(STATIC_DIR, "characters.json")
JINXES_FILE = os.path.join(STATIC_DIR, "jinxes.json")

# Cache auf Volume (Railway) oder lokal im data/ Ordner
CACHE_FILE = os.path.join(
    os.getenv("RAILWAY_VOLUME_MOUNT_PATH", os.path.join(PROJECT_ROOT, "data")),
    "script_cache.json",
)

CACHE_TTL_DAYS = 30

# TPI GitHub URLs
TPI_ROLES_URL = "https://raw.githubusercontent.com/ThePandemoniumInstitute/botc-release/main/resources/data/roles.json"
TPI_ICON_URL = "https://raw.githubusercontent.com/ThePandemoniumInstitute/botc-release/main/resources/characters/{edition}/{filename}"

# Lazy-loaded data
_base_scripts: dict | None = None
_characters: dict | None = None
_jinxes: list | None = None


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


# ── Characters (TPI Format) ─────────────────────────────────────────────────


def load_characters() -> dict:
    """Lädt die offizielle Charakterdatenbank (TPI roles.json Format).

    Returns:
        Dict von character_id → {character_name, character_type, ability, edition}
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
        char_id = entry.get("id", "")
        if not char_id:
            continue
        _characters[char_id] = {
            "character_name": entry.get("name", char_id),
            "character_type": entry.get("team", "").capitalize(),
            "ability": entry.get("ability", ""),
            "edition": entry.get("edition", ""),
        }

    logger.debug("Charakterdatenbank geladen: %d Charaktere", len(_characters))
    return _characters


def invalidate_characters_cache():
    """Invalidiert den Characters-Cache, damit er beim nächsten Zugriff neu geladen wird."""
    global _characters
    _characters = None
    logger.info("Characters-Cache invalidiert")


# ── Jinxes ───────────────────────────────────────────────────────────────────


def _load_jinxes_raw() -> list:
    """Lädt die rohen Jinxes-Daten."""
    global _jinxes
    if _jinxes is not None:
        return _jinxes
    if not os.path.exists(JINXES_FILE):
        logger.warning("jinxes.json nicht gefunden: %s", JINXES_FILE)
        _jinxes = []
        return _jinxes
    with open(JINXES_FILE, "r", encoding="utf-8") as f:
        _jinxes = json.load(f)
    logger.debug("Jinxes geladen: %d Einträge", len(_jinxes))
    return _jinxes


def get_jinxes_for_script(char_ids: list[str]) -> list[dict]:
    """Findet alle Jinxes die für ein Script relevant sind.

    Nur Jinxes wo BEIDE beteiligten Charaktere im Script sind.

    Returns:
        Liste von {char_a, char_b, reason} Dicts.
    """
    char_set = set(char_ids)
    jinxes_raw = _load_jinxes_raw()
    result = []

    for entry in jinxes_raw:
        char_a = entry.get("id", "")
        if char_a not in char_set:
            continue
        for jinx in entry.get("jinx", []):
            char_b = jinx.get("id", "")
            if char_b in char_set:
                result.append({
                    "char_a": char_a,
                    "char_b": char_b,
                    "reason": jinx.get("reason", ""),
                })

    logger.debug("Jinxes für Script: %d gefunden", len(result))
    return result


def get_character_icon_path(char_id: str, evil: bool = False) -> str | None:
    """Gibt den Pfad zum Character-Icon zurück, oder None wenn nicht vorhanden.

    Args:
        char_id: Character-ID
        evil: True für böse Charaktere (Minion/Demon) → bevorzugt _e.webp (rot)
    """
    if evil:
        variants = [f"{char_id}_e.webp", f"{char_id}.webp", f"{char_id}_g.webp"]
    else:
        variants = [f"{char_id}_g.webp", f"{char_id}.webp", f"{char_id}_e.webp"]

    for filename in variants:
        path = os.path.join(ICONS_DIR, filename)
        if os.path.exists(path):
            return path
    return None


# ── TPI Update ───────────────────────────────────────────────────────────────


def _download_file(url: str, timeout: int = 15, silent: bool = False) -> bytes | None:
    """Lädt eine Datei von einer URL. Returns bytes oder None."""
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.content
        if not silent:
            logger.warning("Download fehlgeschlagen: %s → %d", url, r.status_code)
        return None
    except requests.RequestException as e:
        if not silent:
            logger.warning("Download-Fehler: %s → %s", url, e)
        return None


def _update_characters_sync(force_icons: bool = False) -> dict:
    """Synchron: Lädt characters + icons von TPI GitHub.

    Returns: {characters_count, new_icons, skipped_icons, errors}
    """
    result = {"characters_count": 0, "new_icons": 0, "skipped_icons": 0, "errors": []}

    # 1. roles.json downloaden
    logger.info("Lade roles.json von TPI...")
    data = _download_file(TPI_ROLES_URL)
    if data is None:
        result["errors"].append("roles.json konnte nicht geladen werden")
        return result

    try:
        roles = json.loads(data)
    except json.JSONDecodeError:
        result["errors"].append("roles.json ist kein gültiges JSON")
        return result

    if not isinstance(roles, list):
        result["errors"].append("roles.json ist keine Liste")
        return result

    # Validieren
    valid_roles = [r for r in roles if isinstance(r, dict) and r.get("id") and r.get("name") and r.get("team")]
    if not valid_roles:
        result["errors"].append("Keine gültigen Charaktere in roles.json")
        return result

    # Speichern
    with open(CHARACTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(roles, f, indent=2, ensure_ascii=False)
    result["characters_count"] = len(valid_roles)
    logger.info("roles.json gespeichert: %d Charaktere", len(valid_roles))

    # 2. Icons downloaden
    os.makedirs(ICONS_DIR, exist_ok=True)

    for role in valid_roles:
        char_id = role["id"]
        edition = role.get("edition", "")

        # Beide Varianten downloaden: _g (good/blau) und _e (evil/rot)
        filenames_to_try = [f"{char_id}_g.webp", f"{char_id}_e.webp", f"{char_id}.webp"]

        # Prüfen ob schon mindestens eine Variante vorhanden
        existing = [fn for fn in filenames_to_try if os.path.exists(os.path.join(ICONS_DIR, fn))]
        if existing and not force_icons:
            result["skipped_icons"] += 1
            continue

        # Alle Varianten downloaden die verfügbar sind
        any_downloaded = False
        for filename in filenames_to_try:
            url = TPI_ICON_URL.format(edition=edition, filename=filename)
            icon_data = _download_file(url, timeout=10, silent=True)
            if icon_data:
                icon_path = os.path.join(ICONS_DIR, filename)
                with open(icon_path, "wb") as f:
                    f.write(icon_data)
                any_downloaded = True
                logger.debug("Icon heruntergeladen: %s", filename)

        if any_downloaded:
            result["new_icons"] += 1
        else:
            logger.warning("Kein Icon gefunden für: %s (edition=%s)", char_id, edition)

        # Rate-Limiting
        time.sleep(0.3)

    return result


async def update_characters_from_tpi(force_icons: bool = False) -> dict:
    """Async: Lädt characters + icons von TPI GitHub und invalidiert Cache.

    Returns: {characters_count, new_icons, skipped_icons, errors}
    """
    result = await asyncio.to_thread(_update_characters_sync, force_icons)
    if result["characters_count"] > 0:
        invalidate_characters_cache()
    return result


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

    entry = cache.get(normalized)
    if entry:
        expired = _is_expired(entry)
        logger.debug("Cache %s: '%s' (expired=%s)", "hit" if not expired else "hit (stale)", query, expired)
        return entry, expired

    for key, entry in cache.items():
        if normalize_name(entry.get("name", "")) == normalized:
            expired = _is_expired(entry)
            logger.debug("Cache hit via name: '%s' → key='%s'", query, key)
            return entry, expired

    logger.debug("Cache miss: '%s'", query)
    return None, False


def cache_script(name: str, data: dict):
    """Speichert ein Script im Cache."""
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
    base = lookup_base_script(query)
    if base:
        return base, "base"

    cached, needs_refresh = lookup_cached_script(query)
    if cached and not needs_refresh:
        return cached, "cache"
    if cached and needs_refresh:
        return cached, "cache_stale"

    return None, "miss"


# ── Script-JSON Validierung (für Uploads) ────────────────────────────────────


def validate_script_json(data) -> tuple[dict | None, str | None]:
    """Validiert und parst eine hochgeladene BotC Script-JSON.

    Erwartetes Format: [{_meta}, {id: "character_id"}, ...]
    Auch akzeptiert: ["character_id", ...] (String-Array-Format)

    Returns:
        (parsed_data, error_message) — parsed_data ist None bei Fehler.
    """
    if not isinstance(data, list):
        return None, "Ungültiges Format: Erwartet wird eine JSON-Liste (Array)."

    if len(data) == 0:
        return None, "Leere Script-JSON. Mindestens ein Charakter wird erwartet."

    meta = {}
    characters = []

    for item in data:
        if isinstance(item, str):
            characters.append(item)
        elif isinstance(item, dict):
            if item.get("id") == "_meta":
                meta = item
            elif item.get("id"):
                characters.append(item["id"])

    if not characters:
        return None, "Keine Charaktere in der JSON gefunden."

    parsed = {
        "name": meta.get("name", "Custom Script"),
        "author": meta.get("author", ""),
        "characters": characters,
        "source": "upload",
    }

    logger.info("Script-JSON validiert: '%s' (%d Charaktere)", parsed["name"], len(characters))
    return parsed, None
