"""botcscripts.com API-Client.

- Suche: REST API /api/scripts/?search=… (JSON mit Inhalt, Likes, Typ), beliebteste zuerst
- Skript einer Version: /script/<id>/<version>/download
Ist botcscripts.com nicht erreichbar oder zu langsam, wirft die Suche BotcScriptsUnavailable.
"""

import asyncio
import json
import logging
import time
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

BOTCSCRIPTS_BASE = "https://www.botcscripts.com"

# REST API
# ordering=-score: beliebteste zuerst (score = Daumen-hoch-Zahl auf botcscripts.com, Dalyan 20.10.2026)
API_SEARCH = ("https://www.botcscripts.com/api/scripts/?format=json&search={query}&limit={limit}"
              "&include_homebrew=true&include_hybrid=true&ordering=-score")

# Skript-JSON einer bestimmten Version
DOWNLOAD_URL = "https://www.botcscripts.com/script/{id}/{version}/download"

REQUEST_TIMEOUT = 8   # Sekunden je Anfrage
TOTAL_TIMEOUT = 15    # Sekunden für eine ganze Suche bzw. einen Download
REQUEST_DELAY = 0.5
HEADERS = {"User-Agent": "BotC-EventBot/1.0"}


class BotcScriptsUnavailable(Exception):
    """botcscripts.com antwortet nicht (Zeitüberschreitung, Fehler) – nicht zu verwechseln mit „keine Treffer“."""


def _get(url: str) -> requests.Response | None:
    """HTTP GET mit Timeout und Rate-Limiting."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        time.sleep(REQUEST_DELAY)
        return r
    except requests.exceptions.RequestException as e:
        logger.warning("HTTP-Fehler für %s: %s", url, e)
        return None


# ── REST API (Primary) ───────────────────────────────────────────────────────


def _parse_api_result(result: dict) -> dict:
    """Parst ein einzelnes API-Ergebnis in unser Format."""
    content = result.get("content", [])
    characters = [
        item["id"] for item in content
        if isinstance(item, dict) and item.get("id") != "_meta"
    ]

    pk = result.get("pk")
    script_id = result.get("script_id")
    version = result.get("version", "")

    return {
        "name": result.get("name", ""),
        "author": result.get("author", ""),
        "version": version,
        "botcscripts_id": str(script_id) if script_id else str(pk),
        "pk": pk,
        "characters": characters,
        "content": content,
        "script_type": result.get("script_type", ""),
        "likes": result.get("score") or 0,
        "url": f"{BOTCSCRIPTS_BASE}/script/{script_id}/{version}/" if script_id else "",
    }


def _search_api(query: str, limit: int = 5) -> list[dict] | None:
    """Suche via REST API. Gibt None zurück wenn API nicht erreichbar."""
    url = API_SEARCH.format(query=quote_plus(query), limit=limit)
    logger.debug("API-Suche: %s", url)

    r = _get(url)
    if r is None:
        logger.warning("botcscripts.com-API nicht erreichbar")
        return None

    if r.status_code != 200:
        logger.warning("botcscripts.com-API antwortet %d", r.status_code)
        return None

    try:
        data = r.json()
    except (json.JSONDecodeError, ValueError):
        logger.warning("botcscripts.com-API liefert ungültiges JSON")
        return None

    results_raw = data.get("results", [])
    results = [_parse_api_result(r) for r in results_raw[:limit]]
    logger.debug("API: %d Ergebnisse für '%s'", len(results), query)
    return results


def _download_script_sync(script_id: str, version: str) -> list[str]:
    """Lädt Character-IDs eines Scripts per Download-Endpoint."""
    url = DOWNLOAD_URL.format(id=script_id, version=version)
    logger.debug("Script-Download: %s", url)

    r = _get(url)
    if r is None or r.status_code != 200:
        return []

    try:
        data = r.json()
    except (json.JSONDecodeError, ValueError):
        return []

    items = data if isinstance(data, list) else data.get("roles", [])
    return [
        item["id"] for item in items
        if isinstance(item, dict) and item.get("id") != "_meta"
    ]


# ── Public async API ─────────────────────────────────────────────────────────


def _search_sync(query: str, limit: int = 5) -> list[dict]:
    """Synchrone Suche über die API. Kein Ausweichen auf die Webseite (Dalyan, 20.10.2026): API und Seite
    fallen praktisch gemeinsam aus, der Umweg kostete nur Zeit und lieferte weder Likes noch Typ."""
    results = _search_api(query, limit)
    if results is None:
        raise BotcScriptsUnavailable("API nicht erreichbar")
    return results


async def search_scripts(query: str, limit: int = 5) -> list[dict]:
    """Sucht Scripts auf botcscripts.com (API, beliebteste zuerst).

    Returns:
        Liste von Dicts mit: name, author, version, botcscripts_id, pk, characters, url
    """
    try:
        return await asyncio.wait_for(asyncio.to_thread(_search_sync, query, limit), TOTAL_TIMEOUT)
    except asyncio.TimeoutError:
        raise BotcScriptsUnavailable("Zeitüberschreitung bei der Suche") from None


def _download_script_json_sync(script_id: str, version: str) -> list | None:
    """Komplettes Skript-JSON (inkl. _meta) einer bestimmten Version."""
    r = _get(DOWNLOAD_URL.format(id=script_id, version=version))
    if r is None or r.status_code != 200:
        return None
    try:
        data = r.json()
    except (json.JSONDecodeError, ValueError):
        return None
    items = data if isinstance(data, list) else data.get("roles")
    return items if isinstance(items, list) else None


async def download_script(script_id: str, version: str) -> list | None:
    """Async: Skript-JSON über Skript-ID und Version.

    Eindeutig im Gegensatz zu /api/scripts/<id>/, das den internen pk erwartet und mit der
    Skript-ID ein anderes Skript liefert.
    """
    try:
        return await asyncio.wait_for(asyncio.to_thread(_download_script_json_sync, script_id, version),
                                      TOTAL_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("Download von Skript %s v%s: Zeitüberschreitung", script_id, version)
        return None


async def download_script_characters(script_id: str, version: str) -> list[str]:
    """Lädt Character-IDs eines Scripts.

    Returns:
        Liste von Character-ID-Strings.
    """
    return await asyncio.to_thread(_download_script_sync, script_id, version)


def _fetch_script_json_sync(botcscripts_id: str) -> list | None:
    """Holt die Script-JSON von botcscripts.com per API."""
    url = f"{BOTCSCRIPTS_BASE}/api/scripts/{botcscripts_id}/?format=json"
    r = _get(url)
    if r is None or r.status_code != 200:
        return None
    try:
        data = r.json()
        return data.get("content") or data.get("characters")
    except (json.JSONDecodeError, ValueError):
        return None


def _search_versions_sync(script_name: str, author: str = "", limit: int = 10) -> list[dict]:
    """Sucht alle Versionen eines Scripts per API."""
    url = API_SEARCH.format(query=quote_plus(script_name), limit=limit)
    r = _get(url)
    if r is None or r.status_code != 200:
        return []
    try:
        data = r.json()
    except (json.JSONDecodeError, ValueError):
        return []

    results_raw = data.get("results", [])
    versions = []
    for raw in results_raw:
        parsed = _parse_api_result(raw)
        # Nur exakte Name-Matches (case-insensitive)
        if parsed["name"].lower() == script_name.lower():
            # Optional: gleicher Autor
            if author and parsed.get("author", "").lower() != author.lower():
                continue
            versions.append(parsed)
    return versions


async def search_versions(script_name: str, author: str = "") -> list[dict]:
    """Async: Sucht alle Versionen eines Scripts auf botcscripts.com.

    Returns:
        Liste von Script-Dicts mit verschiedenen Versionen.
    """
    try:
        return await asyncio.wait_for(asyncio.to_thread(_search_versions_sync, script_name, author), TOTAL_TIMEOUT)
    except asyncio.TimeoutError:
        raise BotcScriptsUnavailable("Zeitüberschreitung bei der Versionssuche") from None


async def fetch_script_json(botcscripts_id: str) -> list | None:
    """Async: Holt die Script-JSON von botcscripts.com.

    Returns:
        Die Script-Content-Liste oder None bei Fehler.
    """
    return await asyncio.to_thread(_fetch_script_json_sync, botcscripts_id)
