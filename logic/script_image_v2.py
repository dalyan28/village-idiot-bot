"""Script-Bild-Generierung v2 mit Pillow + Wand.

Experimentelle Version mit dekorativen SVG-Elementen am unteren Rand.
Kein Fabled/Loric-Output.
"""

import asyncio
import glob
import io
import logging
import os
import random
import re
import textwrap

import requests
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps
from wand.image import Image as WandImage

from logic.script_cache import (
    get_character_icon_path,
    get_jinxes_for_script,
    load_characters,
    STATIC_DIR,
)

logger = logging.getLogger(__name__)

# ── Layout ───────────────────────────────────────────────────────────────────

SCALE = 2  # Retina-Faktor: 2x für scharfe Darstellung auf Mobile

COLS = 2
ICON_SIZE = 120 * SCALE
ICON_SMALL = 54 * SCALE
ICON_JINX = 72 * SCALE
CHAR_WIDTH = 420 * SCALE
PADDING = 25 * SCALE
SECTION_GAP = 8 * SCALE
HEADER_HEIGHT = 28 * SCALE
ABILITY_LINE_HEIGHT = 13 * SCALE
JINX_LINE_HEIGHT = 14 * SCALE
FOOTER_HEIGHT = 22 * SCALE
TEXT_PADDING = 6 * SCALE
DIVIDER_THICKNESS = 1 * SCALE
DJINN_ID = "djinn"

# ── Farben ───────────────────────────────────────────────────────────────────

BG_COLOR = (255, 255, 255)
TITLE_COLOR = (4, 4, 4)
SUBTITLE_COLOR = (100, 100, 100)
HEADER_COLOR = (4, 4, 4)
ABILITY_COLOR = (4, 4, 4)
LINE_COLOR = (4, 4, 4)
FOOTER_COLOR = (150, 150, 150)

NAME_COLORS = {
    "Townsfolk": (0, 100, 172),
    "Outsider":  (0, 100, 172),
    "Minion":    (180, 40, 40),
    "Demon":     (180, 40, 40),
    "Traveller": (150, 120, 200),
    "Fabled":    (107, 99, 60),
    "Loric":     (117, 138, 84),
}

# ── Fonts ────────────────────────────────────────────────────────────────────

FONT_DIR = os.path.join(STATIC_DIR, "fonts")
_F_TITLE = os.path.join(FONT_DIR, "Dumbledor.ttf")
_F_AUTHOR = os.path.join(FONT_DIR, "Inter.ttf")
_F_HEADER = os.path.join(FONT_DIR, "Dumbledor.ttf")
_F_NAME = os.path.join(FONT_DIR, "TradeGothic-BoldCond.otf")
_F_ABILITY = os.path.join(FONT_DIR, "TradeGothic-Regular.otf")

SZ_TITLE = 36 * SCALE
SZ_AUTHOR = 14 * SCALE
SZ_FABLED_TITLE = 13 * SCALE
SZ_HEADER = 14 * SCALE
SZ_NAME = 15 * SCALE
SZ_ABILITY = 13 * SCALE
SZ_JINX = 12 * SCALE
SZ_FOOTER = 9 * SCALE

TEAM_ORDER = ["Townsfolk", "Outsider", "Minion", "Demon"]
TEAM_ORDER_ALL = ["Townsfolk", "Outsider", "Minion", "Demon", "Traveller", "Fabled", "Loric"]


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except (OSError, IOError):
        return ImageFont.load_default()


# ── Icon Loading ─────────────────────────────────────────────────────────────

def _load_icon(char_id, evil=False, size=ICON_SIZE, icon_urls=None):
    """Lädt ein Icon: lokal zuerst, dann URL-Fallback für Homebrew."""
    icon_path = get_character_icon_path(char_id, evil=evil)
    if icon_path:
        try:
            img = Image.open(icon_path).convert("RGBA")
            return img.resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            pass

    if icon_urls:
        url = None
        if isinstance(icon_urls, list) and len(icon_urls) >= 2:
            url = icon_urls[1] if evil else icon_urls[0]
        elif isinstance(icon_urls, list) and len(icon_urls) == 1:
            url = icon_urls[0]
        elif isinstance(icon_urls, str):
            url = icon_urls
        if url:
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                    return img.resize((size, size), Image.Resampling.LANCZOS)
            except Exception as e:
                logger.debug("Homebrew-Icon download failed for %s: %s", char_id, e)

    return None


def _placeholder(size=ICON_SIZE):
    img = Image.new("RGBA", (size, size), (220, 220, 230, 200))
    draw = ImageDraw.Draw(img)
    f = _font(_F_NAME, size // 3)
    draw.text((size // 2, size // 2), "?", fill=(100, 100, 100), font=f, anchor="mm")
    return img


def _paste(canvas, icon, x, y):
    if icon.mode == "RGBA":
        canvas.paste(icon, (x, y), icon)
    else:
        canvas.paste(icon, (x, y))


# ── Text Helpers ─────────────────────────────────────────────────────────────

def _wrap(text, max_chars=42):
    return textwrap.wrap(text, width=max_chars) if text else []


def _text_height(text, max_chars=42):
    lines = len(_wrap(text, max_chars)) if text else 1
    return lines * ABILITY_LINE_HEIGHT


def _draw_ability(draw, x, y, text, font_r, font_b, max_width=300):
    """Zeichnet Ability mit [bracket]-Fettdruck."""
    segments = re.split(r'(\[[^\]]*\])', text)
    words = []
    for seg in segments:
        if not seg:
            continue
        if seg.startswith('[') and seg.endswith(']'):
            words.append((seg, True))
        else:
            for w in seg.split():
                words.append((w, False))

    curr_x = x
    for word, bold in words:
        f = font_b if bold else font_r
        space = " " if curr_x > x else ""
        bbox = draw.textbbox((0, 0), space + word, font=f)
        w = bbox[2] - bbox[0]
        if curr_x + w > x + max_width and curr_x > x:
            y += ABILITY_LINE_HEIGHT
            curr_x = x
            space = ""
        t = space + word if curr_x > x else word
        draw.text((curr_x, y), t, fill=ABILITY_COLOR, font=f)
        bbox = draw.textbbox((curr_x, y), t, font=f)
        curr_x = bbox[2]


# ── Layout Helper ────────────────────────────────────────────────────────────

def _visible_text_height(draw, text, font):
    """Gibt die sichtbare Texthöhe zurück (ohne unsichtbaren Ascender-Offset)."""
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[3] - bb[1]


def _text_y_centered(draw, text, font, y, container_h):
    """Berechnet die y-Position für vertikal zentrierten Text, korrigiert um Font-Offset."""
    bb = draw.textbbox((0, 0), text, font=font)
    text_h = bb[3] - bb[1]
    offset_y = bb[1]  # Ascender-Offset
    return y + (container_h - text_h) // 2 - offset_y


ICON_OVERLAP_ALLOW = 20 * SCALE  # Icons dürfen so viele Pixel über die Textzeile hinausragen

def _row_height(ability_text, icon_size=ICON_SIZE):
    """Berechnet die Höhe einer Zeile. Icons dürfen überlappen."""
    text_h = SZ_NAME + 4 * SCALE + _text_height(ability_text)
    # Icon darf über die Zeile hinausragen (Overlap erlaubt)
    return max(icon_size - ICON_OVERLAP_ALLOW, text_h)


def _draw_row(draw, img, x, y, icon, name, ability, name_color, fonts, text_width, icon_size=ICON_SIZE):
    """Zeichnet eine Zeile (Icon + Name + Ability) vertikal zentriert. Gibt row_height zurück."""
    # Sichtbare Texthöhe berechnen (mit Font-Offset-Korrektur)
    name_bb = draw.textbbox((0, 0), name, font=fonts["name"])
    name_h = name_bb[3] - name_bb[1] + 4 * SCALE
    name_offset = name_bb[1]
    ability_h = _text_height(ability)
    text_h = name_h + ability_h
    # row_h muss mit _row_height() übereinstimmen (Overlap erlaubt)
    row_h = _row_height(ability, icon_size)

    # Icon: vertikal zentriert in der Zeile (darf oben/unten überlappen)
    icon_y = y + (row_h - icon_size) // 2
    _paste(img, icon, x, icon_y)

    # Text: vertikal zentriert (korrigiert um Font-Ascender-Offset)
    text_y = y + (row_h - text_h) // 2 - name_offset
    tx = x + icon_size + TEXT_PADDING
    draw.text((tx, text_y), name, fill=name_color, font=fonts["name"])
    if ability:
        _draw_ability(draw, tx, text_y + name_offset + name_h, ability,
                      fonts["ability"], fonts["ability_b"], max_width=text_width)

    return row_h


# ── SVG Decoration ──────────────────────────────────────────────────────────

IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "images")
BOTTOM_SVG_DIR = os.path.join(IMAGES_DIR, "bottom")
CLIPPING_MASK_PATH = os.path.join(IMAGES_DIR, "clipping masks", "AWhimAdv-DeckThePalms-PhotoMasks1.png")
DECO_WIDTH = 700  # Breite der Dekoration in Pixeln (vor SCALE)


def _render_svg_colored(svg_path, color, width):
    """Rendert eine SVG in einer bestimmten Farbe als RGBA PIL Image.

    Wand rendert SVGs ohne Transparenz (weißer BG, schwarzes Design).
    Deshalb: Luminanz invertieren → Design-Maske → Farbe anwenden.
    """
    with WandImage(filename=svg_path, background=None) as wimg:
        orig_w, orig_h = wimg.width, wimg.height
        target_h = int(orig_h * width / orig_w)
        wimg.resize(width, target_h)
        wimg.format = "png"
        png_data = wimg.make_blob()
    img = Image.open(io.BytesIO(png_data)).convert("RGBA")
    # Luminanz → invertieren: schwarz (Design) wird deckend, weiß (BG) wird transparent
    grayscale = img.convert("L")
    svg_mask = ImageOps.invert(grayscale)
    colored = Image.new("RGBA", img.size, color + (255,))
    colored.putalpha(svg_mask)
    return colored, svg_mask


def _apply_clipping_mask(img, svg_mask):
    """Wendet die Clipping Mask auf ein eingefärbtes SVG-Bild an.

    Multipliziert SVG-Maske mit Clipping-Mask-Alpha:
    SVG-Design bleibt sichtbar, Ränder laufen schemenhaft aus.
    """
    if not os.path.exists(CLIPPING_MASK_PATH):
        return img
    mask = Image.open(CLIPPING_MASK_PATH).convert("RGBA")
    mask = mask.resize(img.size, Image.Resampling.LANCZOS)
    _, _, _, mask_a = mask.split()
    final_a = ImageChops.multiply(svg_mask, mask_a)
    img.putalpha(final_a)
    return img


def _make_bottom_decoration(width):
    """Erstellt eine zufällige, eingefärbte SVG-Dekoration mit Clipping Mask."""
    svgs = glob.glob(os.path.join(BOTTOM_SVG_DIR, "*.svg"))
    if not svgs:
        return None
    svg_path = random.choice(svgs)
    color = (random.randint(60, 200), random.randint(60, 200), random.randint(60, 200))
    deco, svg_mask = _render_svg_colored(svg_path, color, width)
    deco = _apply_clipping_mask(deco, svg_mask)
    logger.info("Bottom-Deko: %s, Farbe=%s, Größe=%s", os.path.basename(svg_path), color, deco.size)
    return deco


# ── Character Categorization ─────────────────────────────────────────────────

def _team_from_content(team_str):
    if not team_str:
        return None
    mapping = {
        "townsfolk": "Townsfolk", "outsider": "Outsider",
        "minion": "Minion", "demon": "Demon",
        "traveller": "Traveller", "traveler": "Traveller",
        "fabled": "Fabled", "loric": "Loric",
    }
    return mapping.get(team_str.lower())


def _categorize(char_ids, chars_db, content_data=None):
    content_data = content_data or {}
    cats = {t: [] for t in TEAM_ORDER_ALL}
    for cid in char_ids:
        info = chars_db.get(cid, {})
        hw = content_data.get(cid, {})
        team = info.get("character_type") or _team_from_content(hw.get("team")) or "Townsfolk"
        if team not in cats:
            team = "Townsfolk"
        cats[team].append({
            "id": cid,
            "name": info.get("character_name") or hw.get("name") or cid,
            "ability": info.get("ability") or hw.get("ability") or "",
            "team": team,
            "icon_urls": hw.get("image"),
        })
    return cats


# ── Main Generation ──────────────────────────────────────────────────────────

def _generate_sync(script_name, author, char_ids, version="", meta=None, content=None, transparent=False):
    chars_db = load_characters()

    content_data = {}
    if content:
        for item in content:
            if isinstance(item, dict) and item.get("id") and item["id"] != "_meta":
                content_data[item["id"]] = {
                    "name": item.get("name"),
                    "team": item.get("team"),
                    "ability": item.get("ability"),
                    "image": item.get("image"),
                }

    cats = _categorize(char_ids, chars_db, content_data)
    ph = _placeholder()

    # Fonts dict für _draw_row
    f_name = _font(_F_NAME, SZ_NAME)
    f_ability = _font(_F_ABILITY, SZ_ABILITY)
    f_ability_b = _font(_F_NAME, SZ_ABILITY)
    fonts = {"name": f_name, "ability": f_ability, "ability_b": f_ability_b, "name_size": SZ_NAME}

    f_title = _font(_F_TITLE, SZ_TITLE)
    f_author = _font(_F_AUTHOR, SZ_AUTHOR)
    f_header = _font(_F_HEADER, SZ_HEADER)
    f_footer = _font(_F_AUTHOR, SZ_FOOTER)

    img_width = PADDING * 2 + COLS * CHAR_WIDTH
    text_area_width = CHAR_WIDTH - ICON_SIZE - TEXT_PADDING - 5 * SCALE

    # ── Bottom Decoration vorbereiten ──────────────────────────────────
    deco = _make_bottom_decoration(DECO_WIDTH)

    # ── Höhe berechnen ────────────────────────────────────────────────
    height = PADDING + 42 * SCALE + 18 * SCALE  # title + author
    height += SECTION_GAP

    for team in TEAM_ORDER:
        chars = cats.get(team, [])
        if not chars:
            continue
        height += HEADER_HEIGHT
        for i in range(0, len(chars), COLS):
            row = chars[i:i + COLS]
            height += max(_row_height(c["ability"]) for c in row)
        height += SECTION_GAP

    height += FOOTER_HEIGHT + PADDING

    # ── Zeichnen ──────────────────────────────────────────────────────
    if transparent:
        img = Image.new("RGBA", (img_width, height), (0, 0, 0, 0))
    else:
        img = Image.new("RGB", (img_width, height), BG_COLOR)

    # Deko als Hintergrund: am unteren Rand zentriert, UNTER allem Content
    if deco:
        deco_x = (img_width - deco.size[0]) // 2
        deco_y = height - deco.size[1]  # Unterkante = Bildunterkante
        if img.mode == "RGBA":
            img.paste(deco, (deco_x, deco_y), deco)
        else:
            bg = Image.new("RGB", deco.size, BG_COLOR)
            bg.paste(deco, (0, 0), deco)
            img.paste(bg, (deco_x, deco_y))

    draw = ImageDraw.Draw(img)
    y = PADDING

    # Titel + Version
    draw.text((PADDING, y), script_name, fill=TITLE_COLOR, font=f_title)
    if version:
        tb = draw.textbbox((PADDING, y), script_name, font=f_title)
        mid = (tb[1] + tb[3]) // 2
        vb = draw.textbbox((0, 0), f"v{version}", font=f_author)
        draw.text((tb[2] + 12 * SCALE, mid - (vb[3] - vb[1]) // 2),
                  f"v{version}", fill=SUBTITLE_COLOR, font=f_author)
    y += 42 * SCALE

    # Autor
    if author:
        draw.text((PADDING, y), f"by {author}", fill=SUBTITLE_COLOR, font=f_author)
    y += 18 * SCALE

    y += SECTION_GAP

    # ── Character Sektionen (nur Townsfolk/Outsider/Minion/Demon) ────
    for team in TEAM_ORDER:
        chars = cats.get(team, [])
        if not chars:
            continue

        # Header
        header_text = team.upper()
        draw.text((PADDING, y + 4 * SCALE), header_text, fill=HEADER_COLOR, font=f_header)
        hb = draw.textbbox((PADDING, y + 4 * SCALE), header_text, font=f_header)
        text_mid_y = (hb[1] + hb[3]) // 2
        draw.line([(hb[2] + 10 * SCALE, text_mid_y), (img_width - PADDING, text_mid_y)],
                  fill=LINE_COLOR, width=DIVIDER_THICKNESS)
        y += HEADER_HEIGHT

        name_color = NAME_COLORS.get(team, (0, 100, 172))
        is_evil = team in ("Minion", "Demon")

        for i in range(0, len(chars), COLS):
            row = chars[i:i + COLS]
            row_h = max(_row_height(c["ability"]) for c in row)

            for col, char in enumerate(row):
                x = PADDING + col * CHAR_WIDTH
                icon = _load_icon(char["id"], evil=is_evil, icon_urls=char.get("icon_urls")) or ph

                _draw_row(draw, img, x, y, icon, char["name"], char["ability"],
                          name_color, fonts, text_area_width)
            y += row_h
        y += SECTION_GAP

    # ── Footer ────────────────────────────────────────────────────────
    y = height - FOOTER_HEIGHT
    draw.text((PADDING, y + 4 * SCALE), "© Steven Medway  bloodontheclocktower.com",
              fill=FOOTER_COLOR, font=f_footer)
    nfn = "*not the first night"
    nb = draw.textbbox((0, 0), nfn, font=f_footer)
    draw.text((img_width - PADDING - (nb[2] - nb[0]), y + 4 * SCALE), nfn,
              fill=FOOTER_COLOR, font=f_footer)

    # ── Export ────────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    logger.info("Script-Bild v2: '%s' (%dx%d, %d chars)",
                script_name, img_width, height, len(char_ids))
    return buf


async def generate_script_image(script_name, author, char_ids,
                                 version="", meta=None, content=None, transparent=False):
    """Generiert ein Script-Bild als PNG (v2 — ohne Fabled/Loric, mit Deko)."""
    return await asyncio.to_thread(_generate_sync, script_name, author, char_ids, version, meta, content, transparent)
