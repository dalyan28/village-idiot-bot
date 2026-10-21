"""Bilder eines Events: Skript-Bild (automatisch oder eigenes) und Thumbnail.

Eigene Bilder werden als PNG im Upload-Ordner auf dem Volume gespeichert, weil Discord-CDN-
Links ablaufen. Im Event-Post heißen die Anhänge immer gleich (IMAGE_FILENAME, THUMB_FILENAME),
damit das Embed beim Neuaufbau (z. B. nach einer Anmeldung) per attachment:// darauf zeigen kann.
"""

from __future__ import annotations

import io
import logging
import os
import uuid

from PIL import Image, UnidentifiedImageError

from events.schema import IMAGE_AUTO, IMAGE_CUSTOM, SCRIPT_BASE, SCRIPT_FREE, EventData
from logic.script_cache import STATIC_DIR, VOLUME_DIR
from logic.script_image import generate_script_image

logger = logging.getLogger(__name__)

UPLOAD_DIR = os.path.join(VOLUME_DIR, "uploads")
IMAGE_FILENAME = "event_image.png"
THUMB_FILENAME = "thumbnail.png"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
# Größe in Pixeln vor dem Dekodieren prüfen: Eine kleine Datei kann zu einem riesigen Bild
# entpacken („Dekompressionsbombe“) und den Speicher sprengen.
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_SIDE = 1600  # reicht für Discord und hält die gespeicherten PNGs klein

THUMBNAIL_DIR = os.path.join(STATIC_DIR, "images", "thumbnails")
ACADEMY_THUMBNAIL = os.path.join(THUMBNAIL_DIR, "academy.png")
BASE3_THUMBNAILS = {
    "trouble_brewing": os.path.join(THUMBNAIL_DIR, "trouble_brewing.png"),
    "bad_moon_rising": os.path.join(THUMBNAIL_DIR, "bad_moon_rising.png"),
    "sects_and_violets": os.path.join(THUMBNAIL_DIR, "sects_and_violets.png"),
}


# Erzeugte Skript-Bilder (dauert Sekunden): Wizard und Vorschau zeigen dasselbe Bild mehrfach
AUTO_CACHE_SIZE = 16
_auto_cache: dict[tuple, bytes] = {}


class ImageError(ValueError):
    """Hochgeladene Datei ist kein brauchbares Bild (deutsche Meldung)."""


def save_custom_image(raw: bytes) -> str:
    """Prüft und speichert ein hochgeladenes Bild als PNG. Gibt den Dateinamen zurück."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageError("Das Bild ist größer als 8 MB.")
    try:
        img = Image.open(io.BytesIO(raw))  # liest nur den Kopf, noch keine Pixel
        if img.width * img.height > MAX_IMAGE_PIXELS:
            raise ImageError("Das Bild hat zu viele Pixel. Bitte nimm eine kleinere Version.")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ImageError("Die Datei ist kein Bild (erlaubt sind z. B. PNG, JPG, WEBP, GIF).") from None
    if max(img.size) > MAX_IMAGE_SIDE:
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = f"{uuid.uuid4().hex}.png"
    img.save(os.path.join(UPLOAD_DIR, name), format="PNG", optimize=True)
    return name


def custom_image_path(name: str) -> str | None:
    if not name or os.sep in name or "/" in name:
        return None
    path = os.path.join(UPLOAD_DIR, name)
    return path if os.path.exists(path) else None


def delete_custom_image(name: str):
    path = custom_image_path(name)
    if path:
        os.remove(path)


def has_auto_image(data: EventData) -> bool:
    return data.script is not None and data.script.kind != SCRIPT_FREE and bool(data.script.characters)


async def render_image(data: EventData) -> bytes | None:
    """PNG-Bytes des Event-Bildes je nach Modus, oder None (kein Bild)."""
    if data.image_mode == IMAGE_CUSTOM:
        path = custom_image_path(data.custom_image)
        if path is None:
            logger.warning("Eigenes Bild fehlt: %s", data.custom_image)
            return None
        with open(path, "rb") as f:
            return f.read()
    if data.image_mode == IMAGE_AUTO and has_auto_image(data):
        s = data.script
        key = (s.display_name, s.author, s.version, tuple(s.characters), repr(s.content))
        if key in _auto_cache:
            return _auto_cache[key]
        meta = next((x for x in (s.content or []) if isinstance(x, dict) and x.get("id") == "_meta"), None)
        try:
            buf = await generate_script_image(s.display_name, s.author if s.kind != SCRIPT_BASE else "",
                                              s.characters, s.version, meta=meta, content=s.content)
        except Exception:
            logger.exception("Skript-Bild konnte nicht erzeugt werden: %s", s.display_name)
            return None
        image = buf.getvalue()
        if len(_auto_cache) >= AUTO_CACHE_SIZE:
            _auto_cache.pop(next(iter(_auto_cache)))  # ältesten Eintrag verwerfen
        _auto_cache[key] = image
        return image
    return None


def thumbnail_path(data: EventData) -> str | None:
    """Academy-Logo vor Basis-Skript-Logo."""
    if data.is_other_event:
        return None
    if data.is_academy and os.path.exists(ACADEMY_THUMBNAIL):
        return ACADEMY_THUMBNAIL
    if data.script and data.script.kind == SCRIPT_BASE:
        path = BASE3_THUMBNAILS.get(data.script.base_key)
        if path and os.path.exists(path):
            return path
    return None


def image_signature(data: EventData) -> tuple:
    """Alles, was die Bilder bestimmt. Gleich → beim Bearbeiten die alten Anhänge behalten."""
    s = data.script
    script_key = (s.kind, s.base_key, s.botcscripts_id, s.version, tuple(s.characters)) if s else None
    return (data.image_mode, data.custom_image, script_key, data.is_academy)
