"""Skript-Blatt: das neue Skript-Bild (DIN A4, Exlibris-Optik, Theme nach Schwierigkeit).

Öffentliche Schnittstelle:
- generate_script_sheet(...): JPEG als BytesIO oder None (Skript zu groß, z. B. alle Charaktere)
- render_script_sheet(...): dasselbe als PIL-Bild
- theme_for_rating(rating): Schwierigkeit des Events → Theme (bei Bereichen die höhere Stufe)
Lizenzierte Grafiken kommen aus einem Asset-Paket außerhalb des Repos (siehe assets.py).
"""

import asyncio
import io
import logging

from events.schema import (RATING_ANY, RATING_GREEN, RATING_GREEN_YELLOW, RATING_RED, RATING_YELLOW,
                           RATING_YELLOW_RED)

from .model import build_script
from .sheet import render_sheet
from .style import DPI

logger = logging.getLogger(__name__)

JPEG_QUALITY = 90  # Papierstruktur → JPEG ist bei gleicher Optik viel kleiner und schneller als PNG

_THEME_BY_RATING = {RATING_GREEN: "green", RATING_YELLOW: "yellow", RATING_RED: "red",
                    RATING_GREEN_YELLOW: "yellow", RATING_YELLOW_RED: "red", RATING_ANY: "red"}


def theme_for_rating(rating):
    """Theme zur Schwierigkeit; bei Bereichen die höhere Stufe (Dalyan, 27.10.2026), ohne Angabe grün."""
    return _THEME_BY_RATING.get(rating, "green")


def render_script_sheet(script_name, author, char_ids, meta=None, content=None, theme="green"):
    sc = build_script(script_name, author, char_ids, meta=meta, content=content)
    return render_sheet(sc, theme=theme, dpi=DPI)


def _generate_sync(script_name, author, char_ids, meta, content, theme):
    img = render_script_sheet(script_name, author, char_ids, meta=meta, content=content, theme=theme)
    if img is None:
        logger.info("Skript-Blatt: '%s' ist zu groß für ein Bild (%d Charaktere)", script_name, len(char_ids))
        return None
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    buf.seek(0)
    logger.info("Skript-Blatt: '%s' (%dx%d, Theme %s)", script_name, img.width, img.height, theme)
    return buf


async def generate_script_sheet(script_name, author, char_ids, meta=None, content=None, theme="green"):
    """Skript-Blatt als JPEG (BytesIO) oder None, wenn das Skript zu groß ist."""
    return await asyncio.to_thread(_generate_sync, script_name, author, char_ids, meta, content, theme)
