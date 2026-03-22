"""botcscripts.com API-Client: REST API first, HTML-Scraping als Fallback.

Lookup-Kette (aufgerufen von script_cache.py / host_command.py):
1. REST API: /api/scripts/?search=... → JSON mit content direkt dabei
2. Fallback: HTML-Scraping der Suchseite + separater Download-Endpoint
"""

import asyncio
import json
import logging
import time
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BOTCSCRIPTS_BASE = "https://www.botcscripts.com"

# REST API
API_SEARCH = "https://www.botcscripts.com/api/scripts/?format=json&search={query}&limit={limit}&include_homebrew=true&include_hybrid=true"

# HTML Fallback
HTML_SEARCH = "https://www.botcscripts.com/?search={query}"
DOWNLOAD_URL = "https://www.botcscripts.com/script/{id}/{version}/download"

REQUEST_TIMEOUT = 15
REQUEST_DELAY = 0.5
HEADERS = {"User-Agent": "BotC-EventBot/1.0"}


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
        "url": f"{BOTCSCRIPTS_BASE}/script/{script_id}/{version}/" if script_id else "",
    }


def _search_api(query: str, limit: int = 5) -> list[dict] | None:
    """Suche via REST API. Gibt None zurück wenn API nicht erreichbar."""
    url = API_SEARCH.format(query=quote_plus(query), limit=limit)
    logger.debug("API-Suche: %s", url)

    r = _get(url)
    if r is None:
        logger.warning("API nicht erreichbar, Fallback auf Scraping")
        return None

    if r.status_code != 200:
        logger.warning("API returned %d, Fallback auf Scraping", r.status_code)
        return None

    try:
        data = r.json()
    except (json.JSONDecodeError, ValueError):
        logger.warning("API returned ungültiges JSON, Fallback auf Scraping")
        return None

    results_raw = data.get("results", [])
    results = [_parse_api_result(r) for r in results_raw[:limit]]
    logger.debug("API: %d Ergebnisse für '%s'", len(results), query)
    return results


# ── HTML Scraping (Fallback) ─────────────────────────────────────────────────


def _parse_search_html(soup: BeautifulSoup) -> list[dict]:
    """Parst Suchergebnisse aus dem HTML."""
    results = []

    # Strategy 1: Card-basiertes Layout
    for card in soup.select("div.script-card, article.script, div.card, li.script"):
        name_el = card.select_one("h2, h3, .script-name, .title, a")
        author_el = card.select_one(".author, .by, span.author")
        link_el = card.select_one("a[href]")

        name = name_el.get_text(strip=True) if name_el else None
        author = author_el.get_text(strip=True) if author_el else None
        href = link_el["href"] if link_el else None
        if href and not href.startswith("http"):
            href = BOTCSCRIPTS_BASE + href

        if name:
            results.append({"name": name, "author": author, "url": href})

    if results:
        return results

    # Strategy 2: Alle Links die /script/ enthalten
    for a in soup.select("a[href]"):
        href = a["href"]
        if "/script/" in href:
            if not href.startswith("http"):
                href = BOTCSCRIPTS_BASE + href
            name = a.get_text(strip=True)
            if name:
                results.append({"name": name, "author": None, "url": href})

    return results


def _extract_id_version(script_url: str) -> tuple[str | None, str | None]:
    """Extrahiert Script-ID und Version aus einer botcscripts.com URL."""
    parts = [p for p in script_url.split("/") if p]
    try:
        idx = parts.index("script")
        script_id = parts[idx + 1]
        version = parts[idx + 2] if idx + 2 < len(parts) else None
        return script_id, version
    except (ValueError, IndexError):
        return None, None


def _search_scrape(query: str, limit: int = 5) -> list[dict]:
    """Fallback-Suche via HTML-Scraping."""
    url = HTML_SEARCH.format(query=quote_plus(query))
    logger.debug("Scraping-Suche: %s", url)

    r = _get(url)
    if r is None or r.status_code != 200:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    html_results = _parse_search_html(soup)[:limit]

    # Konvertiere Scraping-Ergebnisse ins einheitliche Format
    results = []
    for item in html_results:
        script_id, version = _extract_id_version(item.get("url", ""))
        results.append({
            "name": item.get("name", ""),
            "author": item.get("author", ""),
            "version": version or "",
            "botcscripts_id": script_id or "",
            "pk": None,
            "characters": [],  # Müssen separat per Download geholt werden
            "url": item.get("url", ""),
        })

    logger.debug("Scraping: %d Ergebnisse für '%s'", len(results), query)
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
    """Synchrone Suche: API first, Scraping als Fallback."""
    # 1. REST API versuchen
    results = _search_api(query, limit)
    if results is not None:
        return results

    # 2. Fallback: HTML Scraping
    logger.info("API fehlgeschlagen, nutze Scraping-Fallback für '%s'", query)
    scrape_results = _search_scrape(query, limit)

    # Characters nachladen für Scraping-Ergebnisse
    for result in scrape_results:
        if not result["characters"] and result["botcscripts_id"] and result["version"]:
            result["characters"] = _download_script_sync(
                result["botcscripts_id"], result["version"]
            )

    return scrape_results


async def search_scripts(query: str, limit: int = 5) -> list[dict]:
    """Sucht Scripts auf botcscripts.com (API first, Scraping fallback).

    Returns:
        Liste von Dicts mit: name, author, version, botcscripts_id, pk, characters, url
    """
    return await asyncio.to_thread(_search_sync, query, limit)


async def download_script_characters(script_id: str, version: str) -> list[str]:
    """Lädt Character-IDs eines Scripts.

    Returns:
        Liste von Character-ID-Strings.
    """
    return await asyncio.to_thread(_download_script_sync, script_id, version)
