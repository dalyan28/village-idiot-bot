"""Script-Bild-Generierung mit Pillow.

Erzeugt ein PNG im Stil der botcscripts.com PDFs.
Layout-Zentrierung über _draw_row() Helper — kein manuelles Pixel-Shifting.
"""

import asyncio
import io
import logging
import os
import random
import re
import textwrap

import math

import requests
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

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
TEXT_PADDING = 0 * SCALE
DIVIDER_THICKNESS = 1 * SCALE
DJINN_ID = "djinn"

# ── Designs ──────────────────────────────────────────────────────────────────

DESIGN_PLAIN_WHITE = "plain_white"
DESIGN_MYSTIC_PAPER = "mystic_paper"
DESIGN_STARFIELD = "starfield"
DESIGN_STARFIELD_NEON = "starfield_neon"

IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "images")
PAPER_TEXTURE_PATH = os.path.join(IMAGES_DIR, "paper textures", "Texturelabs_Paper_331S.jpg")
PAPER_CROP_MARGIN = 0.20  # 20% oben/unten abschneiden (dunkle Ränder)
PAPER_BLEND_HEIGHT = 100  # Pixel für Überblendung an Tile-Nähten

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

STARFIELD_COLORS = {
    "header":  (232, 195, 118),
    "ability": (240, 240, 245),
    "line":    (180, 145, 70),
    "footer":  (140, 135, 125),
    "subtitle": (200, 170, 110),
    "title":   (232, 195, 118),
    "names": {
        "Townsfolk": (232, 195, 118),  # gold
        "Outsider":  (232, 195, 118),  # gold
        "Minion":    (220, 110, 110),  # rot
        "Demon":     (220, 110, 110),  # rot
        "Traveller": (190, 170, 235),
        "Fabled":    (232, 195, 118),
        "Loric":     (170, 200, 130),
    },
}

STARFIELD_NEON_COLORS = {
    "header":  (232, 195, 118),
    "ability": (240, 240, 245),
    "line":    (180, 145, 70),
    "footer":  (140, 135, 125),
    "subtitle": (200, 170, 110),
    "title":   (232, 195, 118),
    "names": {
        "Townsfolk": (100, 210, 230),  # teal
        "Outsider":  (100, 210, 230),  # teal
        "Minion":    (235, 100, 145),  # magenta
        "Demon":     (235, 100, 145),  # magenta
        "Traveller": (190, 170, 235),
        "Fabled":    (232, 195, 118),
        "Loric":     (170, 200, 130),
    },
}
# Gold-Hue für Icon-Colorization (matched Title-Gradient-Mittelwert)
STARFIELD_ICON_GOLD_HUE = 0.114

# ── Fonts ────────────────────────────────────────────────────────────────────

FONT_DIR = os.path.join(STATIC_DIR, "fonts")
_F_TITLE = os.path.join(FONT_DIR, "Dumbledor.ttf")
_F_TITLE_STYLED = os.path.join(FONT_DIR, "Thesead.ttf")
_F_TITLE_GOLD = os.path.join(FONT_DIR, "Benguiat Bold.ttf")
_F_AUTHOR = os.path.join(FONT_DIR, "Inter.ttf")
_F_CREAM_CAKE = os.path.join(FONT_DIR, "Cream Cake Bold.otf")
_F_HEADER = os.path.join(FONT_DIR, "Dumbledor.ttf")
_F_NAME = os.path.join(FONT_DIR, "TradeGothic-BoldCond.otf")
_F_ABILITY = os.path.join(FONT_DIR, "TradeGothic-Regular.otf")

SZ_TITLE = 36 * SCALE
SZ_AUTHOR = 14 * SCALE
SZ_AUTHOR_NEON = 32 * SCALE
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


def _draw_ability(draw, x, y, text, font_r, font_b, max_width=300, color=None):
    """Zeichnet Ability mit [bracket]-Fettdruck."""
    if color is None:
        color = ABILITY_COLOR
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
        draw.text((curr_x, y), t, fill=color, font=f)
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


def _draw_row(draw, img, x, y, icon, name, ability, name_color, fonts,
              text_width, icon_size=ICON_SIZE, ability_color=None,
              name_glitch_color=None, name_glitch_offset=None):
    """Zeichnet eine Zeile (Icon + Name + Ability) vertikal zentriert. Gibt row_height zurück.

    name_glitch_color: optionale Komplementärfarbe für einen versetzten
    "Shadow"-Druck hinter dem Namen (Chromatic-Aberration-Glitch).
    """
    if name_glitch_offset is None:
        name_glitch_offset = GLITCH_NAME_OFFSET
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
    if name_glitch_color is not None:
        gx, gy = name_glitch_offset
        draw.text((tx + gx, text_y + gy), name,
                  fill=name_glitch_color, font=fonts["name"])
    draw.text((tx, text_y), name, fill=name_color, font=fonts["name"])
    if ability:
        _draw_ability(draw, tx, text_y + name_offset + name_h, ability,
                      fonts["ability"], fonts["ability_b"], max_width=text_width,
                      color=ability_color)

    return row_h


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


# ── Icon Color Manipulation ──────────────────────────────────────────────────

def _colorize_icon(icon, target_hue):
    """Färbt farbige Pixel eines Icons um (Hue-Shift). Weiß bleibt erhalten."""
    import colorsys
    result = icon.copy()
    pixels = result.load()
    w, h = result.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            hue, sat, val = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if sat > 0.1:
                nr, ng, nb = colorsys.hsv_to_rgb(target_hue, sat, val)
                pixels[x, y] = (int(nr * 255), int(ng * 255), int(nb * 255), a)
    return result


# ── Sticker-Style Effects (Mystic Paper) ─────────────────────────────────────

def _offset_alpha(alpha, x, y, cw, ch):
    """Hilfsfunktion: Alpha-Kanal an Position (x, y) auf Canvas (cw, ch) platzieren."""
    canvas = Image.new("L", (cw, ch), 0)
    canvas.paste(alpha, (x, y))
    return canvas


def _stylize_icon(icon, outline_color=(60, 20, 100)):
    """Sticker-Style: Shadow + weiße Outline + dunkle Outline + Original Icon."""
    w, h = icon.size
    pad = 12 * SCALE
    cw, ch = w + pad * 2, h + pad * 2
    ox, oy = pad, pad

    _, _, _, alpha = icon.split()

    # Shadow
    shadow_a = Image.new("L", (cw, ch), 0)
    shadow_a.paste(alpha, (ox + 3 * SCALE, oy + 3 * SCALE))
    shadow = Image.new("RGBA", (cw, ch), (0, 0, 0, 80))
    shadow.putalpha(shadow_a)
    shadow = shadow.filter(ImageFilter.GaussianBlur(4 * SCALE))

    # White outline (outer)
    white_a = Image.new("L", (cw, ch), 0)
    r_outer = 5 * SCALE
    for angle in range(0, 360, 15):
        dx = int(r_outer * math.cos(math.radians(angle)))
        dy = int(r_outer * math.sin(math.radians(angle)))
        white_a = ImageChops.lighter(white_a, _offset_alpha(alpha, ox + dx, oy + dy, cw, ch))
    white_ol = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))
    white_ol.putalpha(white_a)

    # Dark outline (inner)
    dark_a = Image.new("L", (cw, ch), 0)
    r_inner = 3 * SCALE
    for angle in range(0, 360, 15):
        dx = int(r_inner * math.cos(math.radians(angle)))
        dy = int(r_inner * math.sin(math.radians(angle)))
        dark_a = ImageChops.lighter(dark_a, _offset_alpha(alpha, ox + dx, oy + dy, cw, ch))
    dark_ol = Image.new("RGBA", (cw, ch), outline_color + (255,))
    dark_ol.putalpha(dark_a)

    # Composite
    result = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    result = Image.alpha_composite(result, shadow)
    result = Image.alpha_composite(result, white_ol)
    result = Image.alpha_composite(result, dark_ol)
    icon_layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    icon_layer.paste(icon, (ox, oy), icon)
    result = Image.alpha_composite(result, icon_layer)
    return result


# ── Styled Title (Mystic Paper) ──────────────────────────────────────────────

def _render_styled_title(text, font_size=SZ_TITLE):
    """Rendert einen Sticker-Style Titel: Shadow + weiße Outline + dunkle Outline + Gradient Fill."""
    font = _font(_F_TITLE_STYLED, font_size)

    dummy = Image.new("RGBA", (1, 1))
    dd = ImageDraw.Draw(dummy)
    bb = dd.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    ox, oy = bb[0], bb[1]

    pad = 20 * SCALE
    w, h = tw + pad * 2, th + pad * 2
    tx, ty = pad - ox, pad - oy

    # Shadow
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((tx + 3 * SCALE, ty + 3 * SCALE), text, fill=(0, 0, 0, 100), font=font)
    shadow = shadow.filter(ImageFilter.GaussianBlur(4 * SCALE))

    # White outline (outer)
    white_ol = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    wd = ImageDraw.Draw(white_ol)
    for angle in range(0, 360, 10):
        dx = int(4 * SCALE * math.cos(math.radians(angle)))
        dy = int(4 * SCALE * math.sin(math.radians(angle)))
        wd.text((tx + dx, ty + dy), text, fill=(255, 255, 255, 255), font=font)

    # Dark outline (inner)
    dark_ol = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dkd = ImageDraw.Draw(dark_ol)
    for angle in range(0, 360, 10):
        dx = int(2 * SCALE * math.cos(math.radians(angle)))
        dy = int(2 * SCALE * math.sin(math.radians(angle)))
        dkd.text((tx + dx, ty + dy), text, fill=(60, 20, 100, 255), font=font)

    # Gradient fill
    gradient = Image.new("RGBA", (w, h))
    for row in range(h):
        t = row / h
        r = int(220 + (140 - 220) * t)
        g = int(80 + (40 - 80) * t)
        b = int(180 + (120 - 180) * t)
        ImageDraw.Draw(gradient).line([(0, row), (w, row)], fill=(r, g, b, 255))

    text_mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(text_mask).text((tx, ty), text, fill=255, font=font)
    gradient.putalpha(text_mask)

    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    result = Image.alpha_composite(result, shadow)
    result = Image.alpha_composite(result, white_ol)
    result = Image.alpha_composite(result, dark_ol)
    result = Image.alpha_composite(result, gradient)
    return result


# ── Styled Title (Starfield — Stranger-Things-Stil in Gold) ────────────────

def _render_gold_title(text, font_size=None):
    """Rendert einen goldenen Titel in Benguiat Bold.

    - Großbuchstaben, einheitliche Größe (keine Per-Char-Variation)
    - Gold-Gradient (hell oben → dunkler unten)
    - Horizontale dünne Gold-Linien über und unter dem Text
    - Dezenter warmer Glow + Shadow für Tiefe auf dunklem BG
    """
    text = text.upper()
    size = font_size or int(SZ_TITLE * 1.15)
    font = _font(_F_TITLE_GOLD, size)

    dummy = Image.new("RGBA", (1, 1))
    dd = ImageDraw.Draw(dummy)
    bb = dd.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    ox, oy = bb[0], bb[1]

    pad_x = 24 * SCALE
    pad_y = 14 * SCALE
    line_gap = 10 * SCALE
    line_thickness = max(2, 2 * SCALE)

    w = tw + pad_x * 2
    h = th + pad_y * 2 + (line_gap + line_thickness) * 2
    tx = pad_x - ox
    ty = pad_y + line_gap + line_thickness - oy

    # Warmer Glow (gold, passt zum Sternen-Gold)
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).text((tx, ty), text, fill=(200, 150, 60, 130), font=font)
    glow = glow.filter(ImageFilter.GaussianBlur(8 * SCALE))

    # Dicker dunkler Outline (dunkelbraun, harmoniert mit Gold)
    outline = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(outline)
    outline_radius = max(3, 3 * SCALE)
    for angle in range(0, 360, 8):
        dx = int(outline_radius * math.cos(math.radians(angle)))
        dy = int(outline_radius * math.sin(math.radians(angle)))
        od.text((tx + dx, ty + dy), text, fill=(28, 18, 8, 255), font=font)

    # Gold-Gradient: hellgold oben → warmgold mitte → bronze unten
    gradient = Image.new("RGBA", (w, h))
    for row in range(h):
        t = row / h
        if t < 0.5:
            u = t * 2
            r = int(255 + (232 - 255) * u)
            g = int(232 + (180 - 232) * u)
            b = int(140 + (70 - 140) * u)
        else:
            u = (t - 0.5) * 2
            r = int(232 + (162 - 232) * u)
            g = int(180 + (105 - 180) * u)
            b = int(70 + (30 - 70) * u)
        ImageDraw.Draw(gradient).line([(0, row), (w, row)], fill=(r, g, b, 255))

    text_mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(text_mask).text((tx, ty), text, fill=255, font=font)
    gradient.putalpha(text_mask)

    # Horizontale Gold-Linien
    lines_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lines_layer)
    line_color = (212, 168, 72, 255)
    line_left = pad_x
    line_right = w - pad_x
    line_top_y = pad_y
    line_bottom_y = h - pad_y - line_thickness
    ld.rectangle(
        [line_left, line_top_y, line_right, line_top_y + line_thickness - 1],
        fill=line_color,
    )
    ld.rectangle(
        [line_left, line_bottom_y, line_right, line_bottom_y + line_thickness - 1],
        fill=line_color,
    )

    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    result = Image.alpha_composite(result, glow)
    result = Image.alpha_composite(result, outline)
    result = Image.alpha_composite(result, gradient)
    result = Image.alpha_composite(result, lines_layer)
    return result


# ── Styled Title (Starfield Neon — Stranger-Things-Style) ──────────────────

def _split_title_for_neon(text, font, max_width):
    """Teilt einen Titel in 1 oder 2 Zeilen. Für Stranger-Things-Block-Feel
    wird ab 2 Wörtern immer gesplittet. Der Split wird so gewählt, dass die
    Breiten beider Zeilen möglichst balanciert sind und unter `max_width`
    bleiben."""
    words = text.split()
    if not words or len(words) == 1:
        return [text]
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    best = None
    for i in range(1, len(words)):
        l1 = " ".join(words[:i])
        l2 = " ".join(words[i:])
        w1 = dummy.textbbox((0, 0), l1, font=font)[2]
        w2 = dummy.textbbox((0, 0), l2, font=font)[2]
        over = 1 if max(w1, w2) > max_width else 0
        score = (over, max(w1, w2), abs(w1 - w2))
        if best is None or score < best[0]:
            best = (score, [l1, l2])
    return best[1]


def _render_neon_line(line, font, fill, stroke, stroke_w, tracking_px):
    """Eine Stranger-Things-Zeile: uniforme Buchstabengröße, weites Tracking,
    Magenta-Fill + Teal-Stroke, horizontale Bars extern (links vor erstem
    und rechts nach letztem sichtbaren Buchstaben) auf Baseline-Höhe.

    Rendering in zwei Passes (Strokes unter Fills), damit sich benachbarte
    Buchstaben-Strokes nicht gegenseitig auf Fills draufmalen.
    """
    chars = list(line)
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    advances = [font.getlength(c) + tracking_px for c in chars]
    bboxes = [dummy.textbbox((0, 0), c, font=font) for c in chars]
    bb_ref = dummy.textbbox((0, 0), "H", font=font)
    ref_h = bb_ref[3] - bb_ref[1]

    # Pair-Adjustments (Serif-Overlap, Cut-Paare). Uniforme Size in dieser Zeile.
    size_uni = font.size
    sizes = [size_uni] * len(chars)
    advances, cut_indices = _apply_pair_adjustments(chars, advances, sizes)
    cut_set = set(cut_indices)

    first_vis_w = bboxes[0][2] - bboxes[0][0]
    last_vis_w = bboxes[-1][2] - bboxes[-1][0]
    bar_len = int(max(first_vis_w, last_vis_w) * 0.80)
    bar_thick = max(6, int(ref_h * 0.14))
    margin = max(10, stroke_w * 3 + 2)

    total_w = int(sum(advances)) + margin * 2 + bar_len * 2 + 4
    total_h = ref_h + margin * 2
    Y_top = margin

    stroke_img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    fill_img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stroke_img)
    fd = ImageDraw.Draw(fill_img)

    x = float(margin + bar_len)
    x_positions = []
    for i, c in enumerate(chars):
        y = Y_top - bboxes[i][1]
        xi = int(round(x))
        x_positions.append(xi)
        if i not in cut_set:
            sd.text((xi, y), c, fill=stroke, font=font,
                    stroke_width=stroke_w, stroke_fill=stroke)
            fd.text((xi, y), c, fill=fill, font=font)
        x += advances[i]

    first_vis_left = x_positions[0] + bboxes[0][0]
    last_vis_right = x_positions[-1] + bboxes[-1][2]

    # Bars auf Baseline-Höhe
    bar_y = Y_top + ref_h
    bh = bar_thick // 2

    sd.rectangle(
        [first_vis_left - bar_len - stroke_w, bar_y - bh - stroke_w,
         first_vis_left, bar_y + bh + stroke_w],
        fill=stroke,
    )
    fd.rectangle(
        [first_vis_left - bar_len, bar_y - bh,
         first_vis_left, bar_y + bh],
        fill=fill,
    )
    sd.rectangle(
        [last_vis_right, bar_y - bh - stroke_w,
         last_vis_right + bar_len + stroke_w, bar_y + bh + stroke_w],
        fill=stroke,
    )
    fd.rectangle(
        [last_vis_right, bar_y - bh,
         last_vis_right + bar_len, bar_y + bh],
        fill=fill,
    )

    # Cut-Rendering (nach Bars, damit nichts den Cut übermalt)
    for idx in cut_indices:
        c = chars[idx]
        prev_c = chars[idx - 1]
        xi = x_positions[idx]
        prev_xi = x_positions[idx - 1]
        y = Y_top - bboxes[idx][1]
        prev_y = Y_top - bboxes[idx - 1][1]
        dilate_px = max(3, int(size_uni * 0.05))
        fill_img = _draw_cut_char_on_layer(
            fill_img, c, xi, y, font, fill,
            prev_c, prev_xi, prev_y, font, dilate_px)
        if stroke_w > 0:
            stroke_img = _draw_cut_char_on_layer(
                stroke_img, c, xi, y, font, stroke,
                prev_c, prev_xi, prev_y, font, dilate_px,
                stroke_w=stroke_w, stroke_color=stroke)

    return Image.alpha_composite(stroke_img, fill_img)


def _fit_size_to_width(line, max_w, base_size, min_size, tracking_ratio=0.005):
    """Skaliert font_size schrittweise herunter, bis die Zeile in max_w passt."""
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    size = base_size
    while size > min_size:
        f = _font(_F_TITLE_GOLD, size)
        tr = int(size * tracking_ratio)
        w = int(dummy.textbbox((0, 0), line, font=f)[2] + tr * max(0, len(line) - 1))
        if w <= max_w:
            break
        size = max(min_size, int(size * 0.94))
    return size


# Serif-Overlap Sets:
#   BOTH       — kann linker UND rechter Partner in einer Chain sein
#   LEFT-only  — nur als RECHTER Partner (am Ende einer Chain; kann nach links
#                overlappen, aber nicht nach rechts)
#   RIGHT-only — nur als LINKER Partner (am Anfang einer Chain; kann nach
#                rechts overlappen, aber nicht nach links)
_OVERLAP_BOTH = "AHIKMNRX"
_OVERLAP_LEFT_ONLY = "BDFLP"  # kann nach links (right partner)
_OVERLAP_RIGHT_ONLY = "G"     # kann nach rechts (left partner)

# Chars deren RECHTE Seite overlappen kann → darf LINKER Partner sein
_OVERLAP_RIGHT = frozenset(_OVERLAP_BOTH + _OVERLAP_RIGHT_ONLY)
# Chars deren LINKE Seite overlappen kann → darf RECHTER Partner sein
_OVERLAP_LEFT = frozenset(_OVERLAP_BOTH + _OVERLAP_LEFT_ONLY)

# Cut-Effekt-Paare: linker Char hat eine klare rechte Kante (vertikaler
# Schaft), die sauber in die runde linke Seite des rechten Chars eingreifen
# kann. Rechter Char wird ranggeschoben und verliert den Überschneidungs-
# Teil seiner linken Seite (plus dilate_px „Virtual-Stroke"-Kerf).
_CUT_PAIR_LEFT = frozenset("HIMN")
_CUT_PAIR_RIGHT = frozenset("CGOQ")


def _apply_pair_adjustments(chars, advances, sizes):
    """Passt Char-Advances an für Serif-Overlap (zusammenschieben) und
    Cut-Paare (stärker zusammenschieben + rechten Char mit prev-Char-Mask
    cutten).

    Returns: (new_advances, cut_indices)
    cut_indices: Liste der Indizes die mit Cut-Rendering behandelt werden.
    """
    n = len(chars)
    new_advances = list(advances)
    cut_indices = []

    for i in range(n - 1):
        curr, nxt = chars[i], chars[i + 1]
        size_curr, size_nxt = sizes[i], sizes[i + 1]
        if size_curr != size_nxt:
            continue

        # Cut-Paar ({HIMN}x{CGOQ}): curr nicht erster, nxt nicht letzter Char
        if (curr in _CUT_PAIR_LEFT and nxt in _CUT_PAIR_RIGHT
                and i > 0 and i + 1 < n - 1):
            closer = max(4, int(size_curr * 0.20))
            new_advances[i] = max(1, new_advances[i] - closer)
            cut_indices.append(i + 1)
            continue

        # Serif-Overlap: linke Seite muss rechts-serifen-fähig sein, rechte
        # Seite links-serifen-fähig (P/F/L nur als rechter Partner erlaubt)
        if curr in _OVERLAP_RIGHT and nxt in _OVERLAP_LEFT:
            overlap = max(3, int(size_curr * 0.14))
            new_advances[i] = max(1, new_advances[i] - overlap)

    return new_advances, cut_indices


def _draw_cut_char_on_layer(layer_img, char, x, y, font, color,
                             prev_char, prev_x, prev_y, prev_font, dilate_px,
                             stroke_w=0, stroke_color=None):
    """Zeichnet `char` in eine neue Schicht, maskiert dort wo dilatiertes
    `prev_char` liegt, und composited auf `layer_img`."""
    W, H = layer_img.size
    tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    if stroke_w > 0:
        d.text((x, y), char, fill=color, font=font,
               stroke_width=stroke_w, stroke_fill=stroke_color or color)
    else:
        d.text((x, y), char, fill=color, font=font)

    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.text((prev_x, prev_y), prev_char, fill=255, font=prev_font,
            stroke_width=dilate_px + stroke_w, stroke_fill=255)

    r, g, b, a = tmp.split()
    inv_mask = ImageChops.invert(mask)
    a_cut = ImageChops.multiply(a, inv_mask)
    tmp_cut = Image.merge("RGBA", (r, g, b, a_cut))
    return Image.alpha_composite(layer_img, tmp_cut)


def _measure_line_mixed(chars, font_big, font_small, tr_big, tr_small):
    """Misst Advance-Widths + BBoxes für eine mixed-size Zeile
    (erster/letzter big, middle small). Gibt Listen zurück."""
    n = len(chars)
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    advances, bboxes, fonts = [], [], []
    for i, c in enumerate(chars):
        is_big = n <= 2 or i == 0 or i == n - 1
        f = font_big if is_big else font_small
        tr = tr_big if is_big else tr_small
        advances.append(f.getlength(c) + tr)
        bboxes.append(dummy.textbbox((0, 0), c, font=f))
        fonts.append(f)
    return advances, bboxes, fonts


def _choose_wider_line1_split(words, size_big, size_small_mid, size_l2,
                               tracking_ratio):
    """Wählt den Split so, dass Zeile 1 (mixed mit big+small-middle) sichtbar
    wider ist als Zeile 2 (uniform size_l2). Nur natürliche Wort-Reihenfolge.

    Gibt (line1_str, line2_str) oder None zurück wenn kein solcher Split
    möglich (z. B. wenn das längste Wort hinten steht).
    """
    if len(words) < 2:
        return None
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    f_big = _font(_F_TITLE_GOLD, size_big)
    f_mid = _font(_F_TITLE_GOLD, size_small_mid)
    f_l2 = _font(_F_TITLE_GOLD, size_l2)
    tr_big = int(size_big * tracking_ratio)
    tr_mid = int(size_small_mid * tracking_ratio)
    tr_l2 = int(size_l2 * tracking_ratio)

    def line1_width(s):
        chars = list(s)
        n = len(chars)
        w = 0.0
        for i, c in enumerate(chars):
            is_big = n <= 2 or i == 0 or i == n - 1
            f = f_big if is_big else f_mid
            tr = tr_big if is_big else tr_mid
            w += f.getlength(c) + tr
        return w

    def line2_width(s):
        return sum(f_l2.getlength(c) + tr_l2 for c in s)

    best = None
    for i in range(1, len(words)):
        l1 = " ".join(words[:i])
        l2 = " ".join(words[i:])
        w1 = line1_width(l1)
        w2 = line2_width(l2)
        if w1 <= w2 * 1.12:  # Zeile 1 muss deutlich wider sein (Bindeglied)
            continue
        # Score: bevorzuge Splits, bei denen Zeile 2 nicht zu schmal wird
        # (line2 zu schmal → Bars zu lang → unbalanciert)
        ratio = w2 / w1  # Zielbereich ≈ 0.55 – 0.82
        # Idealer Ratio ~0.7
        ideal_score = abs(ratio - 0.70)
        if best is None or ideal_score < best[0]:
            best = (ideal_score, l1, l2, w1, w2)
    if best is None:
        return None
    return best[1], best[2]


def _render_neon_single_word(text, fill, stroke, stroke_w, tracking_ratio,
                              max_line_w, font_size):
    """Single-Word-Neon-Titel. First/Last groß, Middle kleiner top-aligned.
    EIN Bar unter den Middle-Buchstaben (Underline-Effekt). Keine Bars unter
    First/Last."""
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    small_mid_ratio = 0.78

    size_big = font_size or int(SZ_TITLE * 1.95)
    min_big = int(SZ_TITLE * 0.9)
    while True:
        size_small = max(1, int(size_big * small_mid_ratio))
        f_big = _font(_F_TITLE_GOLD, size_big)
        f_small = _font(_F_TITLE_GOLD, size_small)
        tr_big = int(size_big * tracking_ratio)
        tr_small = int(size_small * tracking_ratio)
        chars = list(text)
        advances, bboxes, fonts = _measure_line_mixed(
            chars, f_big, f_small, tr_big, tr_small)
        sizes = [size_big if (i == 0 or i == len(chars) - 1) else size_small
                 for i in range(len(chars))]
        advances, cut_indices = _apply_pair_adjustments(chars, advances, sizes)
        line_w = int(sum(advances))
        if line_w <= max_line_w or size_big <= min_big:
            break
        size_big = max(min_big, int(size_big * 0.94))

    bb_big = dummy.textbbox((0, 0), "H", font=f_big)
    full_h = bb_big[3] - bb_big[1]
    bb_small = dummy.textbbox((0, 0), "H", font=f_small)
    small_h = bb_small[3] - bb_small[1]

    margin = max(10, stroke_w * 3 + 2)
    total_w = line_w + margin * 2
    total_h = full_h + margin * 2
    Y_top = margin

    x_cursor = float(margin)
    x_positions = []
    for adv in advances:
        x_positions.append(int(round(x_cursor)))
        x_cursor += adv

    stroke_img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    fill_img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stroke_img)
    fd = ImageDraw.Draw(fill_img)

    cut_set = set(cut_indices)
    for i, c in enumerate(chars):
        if i in cut_set:
            continue
        f = fonts[i]
        y = Y_top - bboxes[i][1]
        sd.text((x_positions[i], y), c, fill=stroke, font=f,
                stroke_width=stroke_w, stroke_fill=stroke)
        fd.text((x_positions[i], y), c, fill=fill, font=f)

    n = len(chars)
    if n >= 3:
        first_right = x_positions[0] + bboxes[0][2]
        last_left = x_positions[-1] + bboxes[-1][0]
        if last_left > first_right + 4:
            # Bar direkt unter den Middle-Buchstaben (Underline)
            bar_gap = max(4, int(size_small * 0.08))
            bar_y = Y_top + small_h + bar_gap
            bar_thick = max(6, int(full_h * 0.055))
            bh = bar_thick // 2
            pad_side = max(4, stroke_w)
            bar_x1 = first_right + pad_side
            bar_x2 = last_left - pad_side
            sd.rectangle(
                [bar_x1 - stroke_w, bar_y - bh - stroke_w,
                 bar_x2 + stroke_w, bar_y + bh + stroke_w],
                fill=stroke,
            )
            fd.rectangle(
                [bar_x1, bar_y - bh, bar_x2, bar_y + bh],
                fill=fill,
            )

    # Cut-Rendering am Ende (damit Bars/Nachbar-Buchstaben den Cut nicht übermalen)
    for idx in cut_indices:
        c = chars[idx]
        prev_c = chars[idx - 1]
        f = fonts[idx]
        prev_f = fonts[idx - 1]
        x = x_positions[idx]
        prev_x = x_positions[idx - 1]
        y = Y_top - bboxes[idx][1]
        prev_y = Y_top - bboxes[idx - 1][1]
        ref_size = size_small if (idx != 0 and idx != len(chars) - 1) else size_big
        dilate_px = max(3, int(ref_size * 0.05))
        fill_img = _draw_cut_char_on_layer(
            fill_img, c, x, y, f, fill,
            prev_c, prev_x, prev_y, prev_f, dilate_px)
        if stroke_w > 0:
            stroke_img = _draw_cut_char_on_layer(
                stroke_img, c, x, y, f, stroke,
                prev_c, prev_x, prev_y, prev_f, dilate_px,
                stroke_w=stroke_w, stroke_color=stroke)

    return Image.alpha_composite(stroke_img, fill_img)


def _render_neon_composite(line1, line2, fill, stroke, stroke_w,
                           tracking_ratio, max_line_w, font_size):
    """Multi-Word-Layout (Box-Diagramm-Spec):
    - Zeile 1 (Orange + Blau): first/last big (orange), middle top-aligned smaller (blau)
    - Zeile 2 (Rosa): eingeschoben im Vertikal-Band zwischen small-bottom und
      big-bottom (füllt den Platz, der durch die kleineren middle-Buchstaben
      entsteht), horizontal zentriert im Middle-Zone zwischen den beiden
      Big-Letters
    - Bars (Grün): UNTERHALB der big-Letters (nicht daneben), beide gleich lang:
      bar_len = max(first_w + 0.4*second_w, last_w + 0.4*second_to_last_w).
      Gap oberhalb der Bar zur Big-Letter-Baseline.
    """
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    small_mid_ratio = 2 / 3  # Middle ≈ 67% von Big → Band ≈ 33% für Line 2

    # Auto-Shrink Zeile 1, bis sie passt
    size_big = font_size or int(SZ_TITLE * 2.1)
    min_big = int(SZ_TITLE * 1.0)
    while True:
        size_small = max(1, int(size_big * small_mid_ratio))
        f_big = _font(_F_TITLE_GOLD, size_big)
        f_small = _font(_F_TITLE_GOLD, size_small)
        tr_big = int(size_big * tracking_ratio)
        tr_small = int(size_small * tracking_ratio)
        chars1 = list(line1)
        advances1, bboxes1, fonts1 = _measure_line_mixed(
            chars1, f_big, f_small, tr_big, tr_small)
        sizes1 = [size_big if (i == 0 or i == len(chars1) - 1) else size_small
                  for i in range(len(chars1))]
        advances1, cut_indices_line1 = _apply_pair_adjustments(
            chars1, advances1, sizes1)
        line1_w = int(sum(advances1))
        if line1_w <= max_line_w or size_big <= min_big:
            break
        size_big = max(min_big, int(size_big * 0.94))

    bb_big = dummy.textbbox((0, 0), "H", font=f_big)
    full_h = bb_big[3] - bb_big[1]
    bb_small = dummy.textbbox((0, 0), "H", font=f_small)
    small_h = bb_small[3] - bb_small[1]
    band_h = full_h - small_h

    # Canvas Layout
    margin = max(10, stroke_w * 3 + 2)
    total_w = line1_w + margin * 2
    Y_top = margin

    # Zeile 1 Positionen
    line1_x_start = (total_w - line1_w) // 2
    x_cursor = float(line1_x_start)
    x_positions = []
    for adv in advances1:
        x_positions.append(int(round(x_cursor)))
        x_cursor += adv

    n = len(chars1)
    first_vis_left = x_positions[0] + bboxes1[0][0]
    first_vis_right = x_positions[0] + bboxes1[0][2]
    last_vis_left = x_positions[-1] + bboxes1[-1][0]
    last_vis_right = x_positions[-1] + bboxes1[-1][2]
    first_w_v = first_vis_right - first_vis_left
    last_w_v = last_vis_right - last_vis_left

    # Middle-Zone (horizontal): zwischen first-rechts und last-links
    middle_zone_left = first_vis_right
    middle_zone_right = last_vis_left
    middle_zone_w = max(10, middle_zone_right - middle_zone_left)

    # Bars zuerst positionieren (x-Position unabhängig von Line 2)
    extra_px = max(6, int(size_big * 0.04))
    bar_len = max(first_w_v, last_w_v) + extra_px
    bar_thick = max(12, int(full_h * 0.10))
    bh = bar_thick // 2

    first_center = (first_vis_left + first_vis_right) // 2
    last_center = (last_vis_left + last_vis_right) // 2
    lb_x1 = first_center - bar_len // 2
    lb_x2 = first_center + bar_len // 2
    rb_x1 = last_center - bar_len // 2
    rb_x2 = last_center + bar_len // 2

    # Zeile 2 füllt den horizontalen Raum ZWISCHEN den Bars
    inner_gap_w = max(10, rb_x1 - lb_x2)
    l2_pad_side = max(4, int(size_big * 0.012))
    l2_avail_w = max(10, inner_gap_w - 2 * l2_pad_side)

    # Line 2 so groß wie möglich bis Breite l2_avail_w erreicht (kein harter Cap —
    # lass Line 2 den Gap zwischen Bars voll ausfüllen)
    size_l2_cap = int(size_big * 1.2)
    size_l2 = _fit_size_to_width(line2, l2_avail_w, size_l2_cap,
                                  int(SZ_TITLE * 0.35), tracking_ratio)
    f_l2 = _font(_F_TITLE_GOLD, size_l2)
    tr_l2 = int(size_l2 * tracking_ratio)
    chars2 = list(line2)
    l2_advances = [f_l2.getlength(c) + tr_l2 for c in chars2]
    sizes2 = [size_l2] * len(chars2)
    l2_advances, cut_indices_line2 = _apply_pair_adjustments(
        chars2, l2_advances, sizes2)
    l2_advance = int(sum(l2_advances))

    bb_l2_h = dummy.textbbox((0, 0), "H", font=f_l2)
    l2_ref_h = bb_l2_h[3] - bb_l2_h[1]
    bb_l2_full = dummy.textbbox((0, 0), line2, font=f_l2)
    l2_top_off = bb_l2_full[1]

    # Line 2 Top: direkt unter Small-Middle-Letters mit garantiertem Gap
    min_gap_top = max(14, int(full_h * 0.10))
    l2_y_top_logical = Y_top + small_h + min_gap_top
    l2_y_draw = l2_y_top_logical - l2_top_off
    l2_x_start = lb_x2 + l2_pad_side + (l2_avail_w - l2_advance) // 2

    # Bar-Y: UNTER den big-Buchstaben (gleicher Gap wie zwischen Line 1 und Line 2)
    gap_below_letters = min_gap_top
    bar_y_top = Y_top + full_h + gap_below_letters
    bar_y_center = bar_y_top + bh

    total_h = max(
        bar_y_top + bar_thick,
        l2_y_top_logical + l2_ref_h,
    ) + margin

    # Render
    stroke_img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    fill_img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stroke_img)
    fd = ImageDraw.Draw(fill_img)

    cut_set_line1 = set(cut_indices_line1)
    cut_set_line2 = set(cut_indices_line2)

    # Zeile 1 (Orange + Blau) — cut chars werden später separat gerendert
    for i, c in enumerate(chars1):
        if i in cut_set_line1:
            continue
        f = fonts1[i]
        y = Y_top - bboxes1[i][1]
        sd.text((x_positions[i], y), c, fill=stroke, font=f,
                stroke_width=stroke_w, stroke_fill=stroke)
        fd.text((x_positions[i], y), c, fill=fill, font=f)

    # Zeile 2 (Rosa) — x-Positionen aus adjusted l2_advances
    l2_x_positions = []
    xf = float(l2_x_start)
    for adv in l2_advances:
        l2_x_positions.append(int(round(xf)))
        xf += adv
    for i, c in enumerate(chars2):
        if i in cut_set_line2:
            continue
        xi = l2_x_positions[i]
        sd.text((xi, l2_y_draw), c, fill=stroke, font=f_l2,
                stroke_width=stroke_w, stroke_fill=stroke)
        fd.text((xi, l2_y_draw), c, fill=fill, font=f_l2)

    # Bars (Grün) — unter den big-Letters, gleiche Länge
    for bx1, bx2 in [(lb_x1, lb_x2), (rb_x1, rb_x2)]:
        sd.rectangle(
            [bx1 - stroke_w, bar_y_center - bh - stroke_w,
             bx2 + stroke_w, bar_y_center + bh + stroke_w],
            fill=stroke,
        )
        fd.rectangle(
            [bx1, bar_y_center - bh,
             bx2, bar_y_center + bh],
            fill=fill,
        )

    # Cut-Rendering: rechter Char bekommt linken Char als Alpha-Mask abgezogen
    # (NACH allen normalen fd/sd-Operationen, sonst übermalen wir den Cut)
    for idx in cut_indices_line1:
        c = chars1[idx]
        prev_c = chars1[idx - 1]
        f = fonts1[idx]
        prev_f = fonts1[idx - 1]
        x = x_positions[idx]
        prev_x = x_positions[idx - 1]
        y = Y_top - bboxes1[idx][1]
        prev_y = Y_top - bboxes1[idx - 1][1]
        ref_size = size_small if (idx != 0 and idx != len(chars1) - 1) else size_big
        dilate_px = max(3, int(ref_size * 0.05))
        fill_img = _draw_cut_char_on_layer(
            fill_img, c, x, y, f, fill,
            prev_c, prev_x, prev_y, prev_f, dilate_px)
        if stroke_w > 0:
            stroke_img = _draw_cut_char_on_layer(
                stroke_img, c, x, y, f, stroke,
                prev_c, prev_x, prev_y, prev_f, dilate_px,
                stroke_w=stroke_w, stroke_color=stroke)

    for idx in cut_indices_line2:
        c = chars2[idx]
        prev_c = chars2[idx - 1]
        x = l2_x_positions[idx]
        prev_x = l2_x_positions[idx - 1]
        dilate_px = max(3, int(size_l2 * 0.05))
        fill_img = _draw_cut_char_on_layer(
            fill_img, c, x, l2_y_draw, f_l2, fill,
            prev_c, prev_x, l2_y_draw, f_l2, dilate_px)
        if stroke_w > 0:
            stroke_img = _draw_cut_char_on_layer(
                stroke_img, c, x, l2_y_draw, f_l2, stroke,
                prev_c, prev_x, l2_y_draw, f_l2, dilate_px,
                stroke_w=stroke_w, stroke_color=stroke)

    return Image.alpha_composite(stroke_img, fill_img)


def _render_neon_title(text, font_size=None, no_stroke=True):
    """Stranger-Things-Neon-Titel. Dispatcht nach Wortzahl + Breiten-Fit:
    - 1 Wort: einzelne uniforme Zeile mit externen Bars.
    - 2+ Wörter: Bindeglied-Stil (Zeile 1 mit First/Last-big-middle-top-aligned,
      Zeile 2 uniform darunter, Bars an Zeile-1-Baseline füllen den Gap zu
      Zeile 2). Split wird so gewählt, dass Zeile 1 > Zeile 2 in Breite.
    - Fallback: wenn kein Split möglich (z. B. Zeile 2 wäre immer breiter),
      uniform-2-lines-mit-externen-Bars (simpler ST-Block).
    """
    text = text.upper()
    words = text.split()

    fill = (175, 30, 75)
    stroke = (35, 140, 165)
    stroke_w = 0 if no_stroke else 3 * SCALE
    tracking_ratio = 0.005

    img_width = PADDING * 2 + COLS * CHAR_WIDTH
    max_line_w = img_width - 120 * SCALE

    if len(words) <= 1:
        # Single-Word: first/last big, middle top-aligned, Bar UNTER Middle
        return _render_neon_single_word(text, fill, stroke, stroke_w,
                                         tracking_ratio, max_line_w, font_size)

    # Split-Suche: Zeile 1 muss wider als Zeile 2 sein
    size_big_target = font_size or int(SZ_TITLE * 2.0)
    split = _choose_wider_line1_split(
        words, size_big_target,
        int(size_big_target * 0.78),
        int(size_big_target * 0.56),
        tracking_ratio,
    )

    if split is not None:
        line1, line2 = split
        return _render_neon_composite(line1, line2, fill, stroke, stroke_w,
                                       tracking_ratio, max_line_w, font_size)

    # Fallback: Zeile 2 wäre breiter — uniform 2-lines mit externen Bars
    lines = _split_title_for_neon(
        text, _font(_F_TITLE_GOLD, SZ_TITLE), max_line_w)
    l1_str, l2_str = lines[0], lines[1]
    size_1 = _fit_size_to_width(l1_str, max_line_w, int(SZ_TITLE * 1.5),
                                 SZ_TITLE, tracking_ratio)
    size_2 = _fit_size_to_width(l2_str, max_line_w, int(size_1 * 0.72),
                                 int(SZ_TITLE * 0.7), tracking_ratio)

    def _render(line, size):
        f = _font(_F_TITLE_GOLD, size)
        tr = int(size * tracking_ratio)
        return _render_neon_line(line, f, fill, stroke, stroke_w, tr)

    l1_img = _render(l1_str, size_1)
    l2_img = _render(l2_str, size_2)
    gap = -6 * SCALE
    tot_w = max(l1_img.width, l2_img.width)
    tot_h = l1_img.height + l2_img.height + gap
    result = Image.new("RGBA", (tot_w, tot_h), (0, 0, 0, 0))
    result.paste(l1_img, ((tot_w - l1_img.width) // 2, 0), l1_img)
    result.paste(l2_img, ((tot_w - l2_img.width) // 2,
                          l1_img.height + gap), l2_img)
    return result


# ── Section-Header (Neon — Benguiat Bold, first/last big, middle ~3/4) ─────

def _render_neon_header(text, fill, size_big=None, small_ratio=0.78,
                        tracking_ratio=0.005):
    """Neon-Section-Header (TOWNSFOLK etc.): Benguiat Bold, first/last big,
    middle-Chars small, gleiche Pair-Adjustments wie der Titel. Fill-only.
    Liefert RGBA-Bild mit transparentem Hintergrund."""
    chars = list(text.upper())
    size_big = size_big or int(SZ_HEADER * 1.8)
    size_small = max(1, int(size_big * small_ratio))
    f_big = _font(_F_TITLE_GOLD, size_big)
    f_small = _font(_F_TITLE_GOLD, size_small)
    tr_big = max(1, int(size_big * tracking_ratio))
    tr_small = max(1, int(size_small * tracking_ratio))

    advances, bboxes, fonts = _measure_line_mixed(
        chars, f_big, f_small, tr_big, tr_small)
    sizes = [size_big if (i == 0 or i == len(chars) - 1) else size_small
             for i in range(len(chars))]
    advances, cut_indices = _apply_pair_adjustments(chars, advances, sizes)
    cut_set = set(cut_indices)
    line_w = int(sum(advances))

    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bb_big = dummy.textbbox((0, 0), "H", font=f_big)
    full_h = bb_big[3] - bb_big[1]

    margin = 4 * SCALE
    total_w = line_w + margin * 2
    total_h = full_h + margin * 2
    Y_top = margin

    x_cursor = float(margin)
    x_positions = []
    for adv in advances:
        x_positions.append(int(round(x_cursor)))
        x_cursor += adv

    img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    for i, c in enumerate(chars):
        if i in cut_set:
            continue
        f = fonts[i]
        y = Y_top - bboxes[i][1]
        d.text((x_positions[i], y), c, fill=fill, font=f)

    for idx in cut_indices:
        c = chars[idx]
        prev_c = chars[idx - 1]
        f = fonts[idx]
        prev_f = fonts[idx - 1]
        x = x_positions[idx]
        prev_x = x_positions[idx - 1]
        y = Y_top - bboxes[idx][1]
        prev_y = Y_top - bboxes[idx - 1][1]
        ref_size = size_small if (idx != 0 and idx != len(chars) - 1) else size_big
        dilate_px = max(3, int(ref_size * 0.05))
        img = _draw_cut_char_on_layer(
            img, c, x, y, f, fill,
            prev_c, prev_x, prev_y, prev_f, dilate_px)

    return img


# ── Sticker Author (Neon — weißer Cream-Cake-Bold) ─────────────────────────

def _render_sticker_author(text, font_size=None):
    """Rendert den Autor in Cream Cake Bold: weiße Schrift mit schwarzem
    Stroke. Designed um den Titel leicht von unten zu überlappen."""
    size = font_size or SZ_AUTHOR_NEON
    font = _font(_F_CREAM_CAKE, size)
    stroke_w = max(2, int(size * 0.08))

    dummy = Image.new("RGBA", (1, 1))
    dd = ImageDraw.Draw(dummy)
    bb = dd.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    ox, oy = bb[0], bb[1]

    pad = 6 * SCALE
    w = tw + pad * 2
    h = th + pad * 2
    tx = pad - ox
    ty = pad - oy

    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(result).text(
        (tx, ty), text,
        fill=(255, 255, 255, 255), font=font,
        stroke_width=stroke_w, stroke_fill=(0, 0, 0, 255),
    )
    return result


def _lum_gradient_icon(icon, c_dark, c_mid, c_light, mid_alpha=1.0):
    """Mappt das Icon auf einen monochromen Farb-Gradient basierend auf
    Pixel-Luminanz. Details bleiben erhalten, Farbe wird einheitlich.

    mid_alpha: Alpha-Faktor für Pixel nahe c_mid (< 1.0 dämpft den Körper,
    sodass dark/light prominent hervortreten und mid zurückhaltender wirkt).
    """
    result = icon.copy()
    pixels = result.load()
    w, h = result.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            if lum < 0.5:
                t = lum * 2
                nr = int(c_dark[0] + (c_mid[0] - c_dark[0]) * t)
                ng = int(c_dark[1] + (c_mid[1] - c_dark[1]) * t)
                nb = int(c_dark[2] + (c_mid[2] - c_dark[2]) * t)
                af = 1.0 + (mid_alpha - 1.0) * t   # 1.0 → mid_alpha
            else:
                t = (lum - 0.5) * 2
                nr = int(c_mid[0] + (c_light[0] - c_mid[0]) * t)
                ng = int(c_mid[1] + (c_light[1] - c_mid[1]) * t)
                nb = int(c_mid[2] + (c_light[2] - c_mid[2]) * t)
                af = mid_alpha + (1.0 - mid_alpha) * t  # mid_alpha → 1.0
            pixels[x, y] = (nr, ng, nb, int(a * af))
    return result


def _goldize_icon(icon):
    """Monochrome Gold-Silhouette (Gold-Folien-Prägung)."""
    return _lum_gradient_icon(icon, (96, 64, 22), (196, 150, 65), (248, 220, 140))


def _redize_icon(icon):
    """Monochrome Rot-Silhouette für Evil-Team."""
    return _lum_gradient_icon(icon, (70, 18, 22), (170, 48, 48), (245, 140, 130))


def _winered_icon(icon):
    """Variante A — tiefes Weinrot/Rost, Light heller + Mid dezenter."""
    return _lum_gradient_icon(
        icon, (50, 10, 10), (130, 35, 30), (255, 185, 170), mid_alpha=0.65,
    )


def _magenta_icon(icon):
    """Stranger-Things-Magenta/Rot — leuchtend, neon, Mid dezenter."""
    return _lum_gradient_icon(
        icon, (40, 8, 25), (175, 30, 75), (255, 160, 185), mid_alpha=0.6,
    )


def _teal_icon(icon):
    """Stranger-Things-Teal/Cyan — leuchtend, neon, Mid dezenter."""
    return _y_gradient_icon(
        icon, (8, 35, 55), (35, 140, 165), (195, 245, 250), mid_alpha=0.6,
    )


# Glitch/Chromatic-Aberration-Shift für Starfield-Neon:
#   Haupt-Icon wird über ein komplementär gefärbtes Duplikat gelegt, das
#   horizontal/vertikal leicht versetzt ist. So bleibt der zentrale Körper
#   in der Team-Farbe und der Glitch-Ton "blitzt" nur am Rand durch.
GLITCH_ICON_OFFSET = (-5 * SCALE, 3 * SCALE)
GLITCH_NAME_OFFSET = (-3, 2)


def _glitch_icon(main_icon, glitch_icon, offset=GLITCH_ICON_OFFSET):
    """Composited ein komplementär gefärbtes Icon versetzt hinter das
    Haupt-Icon (RGB-Split-artiger Glitch). Rückgabe hat die Größe von
    main_icon — der Versatz ragt nicht über den Icon-Rahmen hinaus."""
    w, h = main_icon.size
    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    result.paste(glitch_icon, (offset[0], offset[1]), glitch_icon)
    result.alpha_composite(main_icon)
    return result


def _darkcopper_icon(icon):
    """Variante B — Dunkelkupfer (näher am Bronze des Gold)."""
    return _lum_gradient_icon(icon, (55, 20, 12), (145, 70, 40), (225, 140, 90))


def _whitize_icon(icon):
    """Weißes Inverse-Design: dunkle Pixel (Lineart) werden weiß mit voller
    Alpha, helle Pixel werden zu transparentem Weiß gedämpft.

    Das dreht die Haupt-Sichtbarkeit um: was Farb-Fill war wird subtil,
    was Lineart/dunkle Details waren wird zur Hauptlinie in Weiß.
    """
    result = icon.copy()
    pixels = result.load()
    w, h = result.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            # Dunkel → volle Alpha; hell → reduzierte Alpha
            new_alpha = int(a * max(0.08, 1.0 - lum * 0.88))
            pixels[x, y] = (255, 255, 255, new_alpha)
    return result


def _y_gradient_icon(icon, c_dark, c_mid, c_light, mid_alpha=1.0):
    """Wie _lum_gradient_icon, zusätzlich mit vertikalem Positions-Gradient:
    obere Pixel werden heller in die Palette gemappt, untere dunkler."""
    result = icon.copy()
    pixels = result.load()
    w, h = result.size
    for y in range(h):
        y_mod = 1.30 - 0.55 * (y / h)
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            lum = max(0.0, min(1.0, lum * y_mod))
            if lum < 0.5:
                t = lum * 2
                nr = int(c_dark[0] + (c_mid[0] - c_dark[0]) * t)
                ng = int(c_dark[1] + (c_mid[1] - c_dark[1]) * t)
                nb = int(c_dark[2] + (c_mid[2] - c_dark[2]) * t)
                af = 1.0 + (mid_alpha - 1.0) * t
            else:
                t = (lum - 0.5) * 2
                nr = int(c_mid[0] + (c_light[0] - c_mid[0]) * t)
                ng = int(c_mid[1] + (c_light[1] - c_mid[1]) * t)
                nb = int(c_mid[2] + (c_light[2] - c_mid[2]) * t)
                af = mid_alpha + (1.0 - mid_alpha) * t
            pixels[x, y] = (nr, ng, nb, int(a * af))
    return result


def _goldize_icon_gradient(icon):
    """Gold mit y-Gradient: oben hellgold → fast weiß, unten bronze.
    Mid-Opacity reduziert → Highlights stechen stärker hervor."""
    return _y_gradient_icon(
        icon, (80, 50, 18), (200, 155, 70), (255, 250, 225), mid_alpha=0.65,
    )


def _apply_finishing_filter_gold(img):
    """Mildes Finishing für Gold-Starfield: leichter Kontrast + warmer Ton,
    keine aggressive Split-Tone oder Radialmaske."""
    from PIL import ImageEnhance
    img = ImageEnhance.Color(img).enhance(0.95)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    has_alpha = img.mode == "RGBA"
    if has_alpha:
        r, g, b, a = img.split()
    else:
        img = img.convert("RGB")
        r, g, b = img.split()
        a = None
    r = r.point(lambda v: min(255, int(v * 1.04)))
    b = b.point(lambda v: int(v * 0.93))
    if a is not None:
        img = Image.merge("RGBA", (r, g, b, a))
    else:
        img = Image.merge("RGB", (r, g, b))
    return img


def _apply_finishing_filter(img):
    """80s-Retro-Sci-Fi-Finishing für Starfield-Neon:

    - Hoher Kontrast + Sättigung (knackig, cinematic)
    - Split Tone: Shadows Richtung teal/blau, Highlights Richtung orange/gold
    - Subtles Bloom (weicher Glow um helle Bereiche → magisch/elektrisch)
    - Radialer Fokus (Ecken dunkler, Titel-Bereich geschützt)
    - Film-Grain
    """
    from PIL import ImageEnhance

    # 1. Kontrast + Sättigung dramatisch anheben
    img = ImageEnhance.Contrast(img).enhance(1.22)
    img = ImageEnhance.Color(img).enhance(1.28)

    # Alpha separat behandeln (muss beim Merge erhalten bleiben)
    has_alpha = img.mode == "RGBA"
    if has_alpha:
        r, g, b, a = img.split()
    else:
        img = img.convert("RGB")
        r, g, b = img.split()
        a = None

    # 2. Split Tone (Teal & Orange)
    # Dunkel (v<120): shift Richtung teal (B↑, R↓)
    # Hell (v>140): shift Richtung warm orange (R↑, B↓)
    def shadow_lift_r(v):
        if v < 120:
            return max(0, int(v * 0.94))
        return min(255, int(v * 1.08)) if v > 140 else v

    def shadow_lift_g(v):
        return min(255, int(v * 1.03)) if v < 120 else v

    def shadow_lift_b(v):
        if v < 120:
            return min(255, int(v * 1.12))
        return int(v * 0.86) if v > 140 else v

    r = r.point(shadow_lift_r)
    g = g.point(shadow_lift_g)
    b = b.point(shadow_lift_b)

    img = Image.merge("RGB", (r, g, b))

    # 3. Bloom: helle Bereiche bekommen weichen Glow (Screen-Blend)
    W, H = img.size
    blurred = img.filter(ImageFilter.GaussianBlur(radius=max(6, min(W, H) // 200)))
    # Nur helle Bereiche aus Blur für Screen-Blend
    bloom_mask = blurred.convert("L").point(lambda v: max(0, v - 120) * 2)
    bloom = Image.new("RGB", (W, H), (0, 0, 0))
    bloom.paste(blurred, mask=bloom_mask)
    img = ImageChops.screen(img, bloom)

    # 4. Radialer Fokus — Mitte hell, Ecken dunkler. Oberer Bereich
    # (ca. 20% Titel+Autor+Fabled) bleibt geschützt, Schriftzüge verschwinden
    # nicht im Rand-Shadow.
    cx, cy = W // 2, H // 2
    radius_ref = min(W, H) * 0.8
    protect_top = 0.20  # oberen 20% des Bildes vor Dimming schützen
    protect_fade = 0.08  # smoother fade-out über weitere 8%
    low_w = max(32, W // 6)
    low_h = max(32, H // 6)
    low_mask = Image.new("L", (low_w, low_h), 0)
    lm_px = low_mask.load()
    for y in range(low_h):
        yy_norm = y / low_h
        protect = max(0.0, min(1.0,
            (protect_top + protect_fade - yy_norm) / protect_fade
        ))
        yy = yy_norm * H
        for x in range(low_w):
            xx = (x / low_w) * W
            d = min(1.0, math.hypot(xx - cx, yy - cy) / radius_ref)
            dim = 1.0 - d * 0.35
            # protect=1 → kein Dimm; protect=0 → voller Effekt
            effective = dim + (1.0 - dim) * protect
            v = int(255 * max(0.65, effective))
            lm_px[x, y] = v
    focus_mask = low_mask.resize((W, H), Image.BILINEAR)
    focus_mask = focus_mask.filter(ImageFilter.GaussianBlur(radius=min(W, H) // 20))
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    img = Image.composite(img, dark, focus_mask)

    # 5. Film-Grain: low-res Random-Noise um 128, blend 6% → leichtes Rauschen
    # ohne Gesamt-Helligkeit merklich zu verändern.
    gs = 6
    gw, gh = max(1, W // gs), max(1, H // gs)
    grain = Image.new("L", (gw, gh))
    gpx = grain.load()
    grain_rng = random.Random(42)
    for y in range(gh):
        for x in range(gw):
            gpx[x, y] = grain_rng.randint(108, 148)  # ±20 um 128
    grain = grain.resize((W, H), Image.BILINEAR)
    grain_rgb = Image.merge("RGB", (grain, grain, grain))
    img = Image.blend(img, grain_rgb, 0.09)

    if a is not None:
        img = img.convert("RGBA")
        img.putalpha(a)
    return img


# ── Paper Background ─────────────────────────────────────────────────────────

def _tile_paper_background(width, height):
    """Erzeugt einen gekachelten Pergament-Hintergrund (Mystic Paper Design)."""
    paper = Image.open(PAPER_TEXTURE_PATH).convert("RGB")
    pw, ph = paper.size
    scale = width / pw
    new_ph = int(ph * scale)
    paper_scaled = paper.resize((width, new_ph), Image.Resampling.LANCZOS)

    crop_px = int(new_ph * PAPER_CROP_MARGIN)
    middle = paper_scaled.crop((0, crop_px, width, new_ph - crop_px))
    mid_h = middle.size[1]
    blend_h = PAPER_BLEND_HEIGHT

    bg = Image.new("RGB", (width, height))
    bg.paste(paper_scaled, (0, 0))

    y = new_ph
    flip = False
    while y < height:
        tile = middle.copy()
        if flip:
            tile = tile.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

        for row in range(min(blend_h, height - y + blend_h)):
            a = row / blend_h
            src_y = y - blend_h + row
            if src_y < 0 or src_y >= height:
                continue
            row_old = bg.crop((0, src_y, width, src_y + 1))
            row_new = tile.crop((0, row, width, row + 1))
            bg.paste(Image.blend(row_old, row_new, a), (0, src_y))

        rest_top = blend_h
        remaining = min(mid_h - rest_top, height - y)
        if remaining > 0:
            bg.paste(tile.crop((0, rest_top, width, rest_top + remaining)), (0, y))

        y += mid_h - blend_h
        flip = not flip

    return bg


# ── Main Generation ──────────────────────────────────────────────────────────

def _generate_sync(script_name, author, char_ids, version="", meta=None, content=None, transparent=False, show_fabled=True, design=DESIGN_PLAIN_WHITE, white_icons=False):
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
    jinxes = get_jinxes_for_script(char_ids)
    bootlegger_rules = (meta or {}).get("bootlegger", [])
    ph = _placeholder()
    ph_sm = _placeholder(ICON_SMALL)
    ph_jinx = _placeholder(ICON_JINX)

    fabled_loric = cats.get("Fabled", []) + cats.get("Loric", [])

    # Auto-insert Djinn
    if jinxes and not any(fl["id"] == DJINN_ID for fl in fabled_loric):
        djinn_info = chars_db.get(DJINN_ID, {})
        fabled_loric.insert(0, {
            "id": DJINN_ID,
            "name": djinn_info.get("character_name", "Djinn"),
            "ability": djinn_info.get("ability", "Use the Djinn's special rule. All players know what it is."),
            "team": "Fabled",
        })
    fabled_loric.sort(key=lambda x: (0 if x["id"] == DJINN_ID else 1))

    # Fonts dict für _draw_row
    f_name = _font(_F_NAME, SZ_NAME)
    f_ability = _font(_F_ABILITY, SZ_ABILITY)
    f_ability_b = _font(_F_NAME, SZ_ABILITY)
    fonts = {"name": f_name, "ability": f_ability, "ability_b": f_ability_b, "name_size": SZ_NAME}

    f_title = _font(_F_TITLE, SZ_TITLE)
    f_author = _font(_F_AUTHOR, SZ_AUTHOR)
    f_fabled_t = _font(_F_AUTHOR, SZ_FABLED_TITLE)
    f_header = _font(_F_HEADER, SZ_HEADER)
    f_jinx = _font(_F_ABILITY, SZ_JINX)
    f_footer = _font(_F_AUTHOR, SZ_FOOTER)

    img_width = PADDING * 2 + COLS * CHAR_WIDTH
    text_area_width = CHAR_WIDTH - ICON_SIZE - TEXT_PADDING - 5 * SCALE
    fl_text_width = img_width - PADDING * 2 - ICON_SIZE - TEXT_PADDING - 10 * SCALE

    # Jinx/Bootlegger text area
    jinx_x = PADDING + ICON_SIZE + TEXT_PADDING
    jinx_text_w = img_width - jinx_x - PADDING - 5 * SCALE
    jinx_icon_text_w = jinx_text_w - ICON_JINX * 2 + 4 * SCALE - 6 * SCALE
    jinx_wrap_chars = max(40, jinx_icon_text_w // (7 * SCALE))
    boot_wrap_chars = max(40, (jinx_text_w - 12 * SCALE) // (7 * SCALE))

    # ── Höhe berechnen ────────────────────────────────────────────────
    if design == DESIGN_MYSTIC_PAPER:
        _title_img = _render_styled_title(script_name)
        title_h = _title_img.height + 8 * SCALE
        height = PADDING + title_h + 18 * SCALE  # styled title + author
    elif design == DESIGN_STARFIELD:
        _title_img = _render_gold_title(script_name)
        title_h = _title_img.height + 8 * SCALE
        height = PADDING + title_h + 18 * SCALE
    elif design == DESIGN_STARFIELD_NEON:
        _title_img = _render_neon_title(script_name)
        # Author-Sticker überlappt den Titel um STICKER_OVERLAP
        if author:
            _author_img = _render_sticker_author(f"by {author}")
            overlap = 20 * SCALE
            # Gesamt: Titel + (Autor_height - overlap) + kleine Margin
            extra = max(18 * SCALE, _author_img.height - overlap + 6 * SCALE)
            height = PADDING + _title_img.height + extra
        else:
            height = PADDING + _title_img.height + 8 * SCALE + 18 * SCALE
    else:
        height = PADDING + 42 * SCALE + 18 * SCALE  # title + author
    if fabled_loric:
        height += 40 * SCALE  # fabled row
    height += SECTION_GAP

    # Für Neon-Theme: Section-Header sind größer → dynamische Höhe
    is_neon = design == DESIGN_STARFIELD_NEON
    neon_headers = {}
    neon_hdr_gap = 8 * SCALE  # Gap nach dem Header vor den Char-Rows
    if is_neon:
        for team in TEAM_ORDER:
            if cats.get(team):
                team_color = STARFIELD_NEON_COLORS["names"].get(
                    team, STARFIELD_NEON_COLORS["header"])
                neon_headers[team] = _render_neon_header(team, team_color)
        if show_fabled and (fabled_loric or jinxes or bootlegger_rules):
            neon_headers["_fabled"] = _render_neon_header(
                "Fabled & Loric",
                STARFIELD_NEON_COLORS["names"]["Fabled"])

    for team in TEAM_ORDER:
        chars = cats.get(team, [])
        if not chars:
            continue
        if is_neon:
            height += neon_headers[team].height + neon_hdr_gap
        else:
            height += HEADER_HEIGHT
        for i in range(0, len(chars), COLS):
            row = chars[i:i + COLS]
            height += max(_row_height(c["ability"]) for c in row)
        height += SECTION_GAP

    if show_fabled and (fabled_loric or jinxes or bootlegger_rules):
        if is_neon:
            height += neon_headers["_fabled"].height + neon_hdr_gap + SECTION_GAP
        else:
            height += HEADER_HEIGHT + SECTION_GAP
        for fl in fabled_loric:
            height += _row_height(fl["ability"])
            if fl["id"] == DJINN_ID and jinxes:
                for jnx in jinxes:
                    jh = SZ_NAME + 4 * SCALE + len(_wrap(jnx["reason"], jinx_wrap_chars)) * JINX_LINE_HEIGHT
                    height += max(ICON_JINX, jh)
            if fl["id"] == "bootlegger" and bootlegger_rules:
                for rule in bootlegger_rules:
                    height += len(_wrap(rule, boot_wrap_chars)) * JINX_LINE_HEIGHT + 2 * SCALE
        height += SECTION_GAP

    height += FOOTER_HEIGHT + PADDING

    # ── Zeichnen ──────────────────────────────────────────────────────
    is_mystic = design == DESIGN_MYSTIC_PAPER
    is_starfield_gold = design == DESIGN_STARFIELD
    is_starfield_neon = design == DESIGN_STARFIELD_NEON
    is_starfield = is_starfield_gold or is_starfield_neon
    is_centered = is_mystic or is_starfield

    # Theme-abhängige Farben (starfield = dunkler BG → helle Texte)
    if is_starfield_neon:
        _pal = STARFIELD_NEON_COLORS
    elif is_starfield_gold:
        _pal = STARFIELD_COLORS
    else:
        _pal = None

    if _pal is not None:
        theme_header = _pal["header"]
        theme_ability = _pal["ability"]
        theme_line = _pal["line"]
        theme_footer = _pal["footer"]
        theme_subtitle = _pal["subtitle"]
        theme_names = _pal["names"]
    else:
        theme_header = HEADER_COLOR
        theme_ability = ABILITY_COLOR
        theme_line = LINE_COLOR
        theme_footer = FOOTER_COLOR
        theme_subtitle = SUBTITLE_COLOR
        theme_names = NAME_COLORS

    if transparent:
        img = Image.new("RGBA", (img_width, height), (0, 0, 0, 0))
    elif is_mystic:
        img = _tile_paper_background(img_width, height).convert("RGBA")
    elif is_starfield_gold or is_starfield_neon:
        from logic.starfield_bg import render_starfield_bg
        img = render_starfield_bg(img_width, height).convert("RGBA")
    else:
        img = Image.new("RGB", (img_width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)
    y = PADDING

    # Titel + Version
    title_bottom = None
    if is_mystic or is_starfield:
        if is_mystic:
            title_img = _render_styled_title(script_name)
        elif is_starfield_neon:
            title_img = _render_neon_title(script_name)
        else:
            title_img = _render_gold_title(script_name)
        title_x = (img_width - title_img.width) // 2
        _paste(img, title_img, title_x, y)
        if version:
            vt = f"v{version}"
            vb = draw.textbbox((0, 0), vt, font=f_author)
            vw = vb[2] - vb[0]
            draw.text(((img_width - vw) // 2, y + title_img.height), vt,
                      fill=SUBTITLE_COLOR, font=f_author)
        title_bottom = y + title_img.height
        y += title_img.height + 8 * SCALE
    else:
        draw.text((PADDING, y), script_name, fill=TITLE_COLOR, font=f_title)
        if version:
            tb = draw.textbbox((PADDING, y), script_name, font=f_title)
            mid = (tb[1] + tb[3]) // 2
            vb = draw.textbbox((0, 0), f"v{version}", font=f_author)
            draw.text((tb[2] + 12 * SCALE, mid - (vb[3] - vb[1]) // 2),
                      f"v{version}", fill=SUBTITLE_COLOR, font=f_author)
        y += 42 * SCALE

    # Autor
    if is_starfield_neon and author:
        # Cream-Cake-Bold weißer Sticker, leicht überlappend mit Titel
        author_img = _render_sticker_author(f"by {author}")
        overlap = 20 * SCALE
        ax = (img_width - author_img.width) // 2
        ay = (title_bottom if title_bottom is not None else y) - overlap
        _paste(img, author_img, ax, ay)
        y = max(y, ay + author_img.height + 6 * SCALE)
    else:
        if author:
            if is_centered:
                at = f"by {author}"
                ab = draw.textbbox((0, 0), at, font=f_author)
                aw = ab[2] - ab[0]
                draw.text(((img_width - aw) // 2, y), at,
                          fill=theme_subtitle, font=f_author)
            else:
                draw.text((PADDING, y), f"by {author}", fill=theme_subtitle, font=f_author)
        y += 18 * SCALE

    # Fabled/Loric Icons unter Autor
    if fabled_loric:
        fabled_h = 40 * SCALE
        if is_centered:
            # Breite vorab messen für Zentrierung
            total_w = 0
            for i, fl in enumerate(fabled_loric):
                total_w += ICON_SMALL + 5 * SCALE
                nb = draw.textbbox((0, 0), fl["name"], font=f_fabled_t)
                total_w += nb[2] - nb[0]
                if i < len(fabled_loric) - 1:
                    total_w += 15 * SCALE
            fx = (img_width - total_w) // 2
        else:
            fx = PADDING
        for fl in fabled_loric:
            icon = _load_icon(fl["id"], size=ICON_SMALL, icon_urls=fl.get("icon_urls")) or ph_sm
            icon_y = y + (fabled_h - ICON_SMALL) // 2
            _paste(img, icon, fx, icon_y)
            fx += ICON_SMALL + 5 * SCALE
            color = theme_names.get(fl["team"], theme_header)
            text_bb = draw.textbbox((0, 0), fl["name"], font=f_fabled_t)
            text_h = text_bb[3] - text_bb[1]
            text_offset_y = text_bb[1]
            text_y = y + (fabled_h - text_h) // 2 - text_offset_y
            draw.text((fx, text_y), fl["name"], fill=color, font=f_fabled_t)
            nb = draw.textbbox((fx, text_y), fl["name"], font=f_fabled_t)
            fx = nb[2] + 15 * SCALE
        y += fabled_h

    y += SECTION_GAP

    # ── Character Sektionen ───────────────────────────────────────────
    neon_bar_pad = 18 * SCALE
    neon_bar_thick = 4 * SCALE
    for team in TEAM_ORDER:
        chars = cats.get(team, [])
        if not chars:
            continue

        # Header
        if is_neon:
            hdr_img = neon_headers[team]
            team_color = theme_names.get(team, theme_header)
            hx = (img_width - hdr_img.width) // 2
            _paste(img, hdr_img, hx, y)
            bar_y = y + hdr_img.height // 2
            left_end = hx - neon_bar_pad
            right_start = hx + hdr_img.width + neon_bar_pad
            if left_end > PADDING:
                draw.rectangle(
                    [PADDING, bar_y - neon_bar_thick // 2,
                     left_end, bar_y + neon_bar_thick // 2],
                    fill=team_color)
            if right_start < img_width - PADDING:
                draw.rectangle(
                    [right_start, bar_y - neon_bar_thick // 2,
                     img_width - PADDING, bar_y + neon_bar_thick // 2],
                    fill=team_color)
            y += hdr_img.height + neon_hdr_gap
        else:
            header_text = team.upper()
            draw.text((PADDING, y + 4 * SCALE), header_text, fill=theme_header, font=f_header)
            hb = draw.textbbox((PADDING, y + 4 * SCALE), header_text, font=f_header)
            text_mid_y = (hb[1] + hb[3]) // 2
            draw.line([(hb[2] + 10 * SCALE, text_mid_y), (img_width - PADDING, text_mid_y)],
                      fill=theme_line, width=DIVIDER_THICKNESS)
            y += HEADER_HEIGHT

        name_color = theme_names.get(team, theme_subtitle)
        is_evil = team in ("Minion", "Demon")

        # Glitch-Komplementärfarbe nur für Starfield-Neon Good/Evil Teams.
        # Regel: Haupt-Teal ↔ Glitch-Magenta und umgekehrt.
        name_glitch_color = None
        if is_starfield_neon:
            if team in ("Townsfolk", "Outsider"):
                name_glitch_color = theme_names["Minion"]
            elif team in ("Minion", "Demon"):
                name_glitch_color = theme_names["Townsfolk"]

        for i in range(0, len(chars), COLS):
            row = chars[i:i + COLS]
            row_h = max(_row_height(c["ability"]) for c in row)

            for col, char in enumerate(row):
                x = PADDING + col * CHAR_WIDTH
                icon = _load_icon(char["id"], evil=is_evil, icon_urls=char.get("icon_urls")) or ph

                if is_mystic and team in ("Townsfolk", "Outsider"):
                    icon = _colorize_icon(icon, 0.92)
                    icon = _stylize_icon(icon, outline_color=(120, 20, 80))
                elif is_mystic and team in ("Minion", "Demon"):
                    icon = _stylize_icon(icon, outline_color=(120, 20, 20))
                elif is_starfield and white_icons:
                    icon = _whitize_icon(icon)
                elif is_starfield_gold and team in ("Townsfolk", "Outsider"):
                    icon = _goldize_icon_gradient(icon)
                elif is_starfield_gold and team in ("Minion", "Demon"):
                    icon = _winered_icon(icon)
                elif is_starfield_neon and team in ("Townsfolk", "Outsider"):
                    icon = _glitch_icon(_teal_icon(icon), _magenta_icon(icon))
                elif is_starfield_neon and team in ("Minion", "Demon"):
                    icon = _glitch_icon(_magenta_icon(icon), _teal_icon(icon))

                _draw_row(draw, img, x, y, icon, char["name"], char["ability"],
                          name_color, fonts, text_area_width,
                          icon_size=icon.size[0] if is_mystic else ICON_SIZE,
                          ability_color=theme_ability,
                          name_glitch_color=name_glitch_color)
            y += row_h
        y += SECTION_GAP

    # ── Fabled & Loric Sektion ────────────────────────────────────────
    if show_fabled and (fabled_loric or jinxes or bootlegger_rules):
        if is_neon:
            hdr_img = neon_headers["_fabled"]
            fabled_color = theme_names.get("Fabled", theme_header)
            hx = (img_width - hdr_img.width) // 2
            _paste(img, hdr_img, hx, y)
            bar_y = y + hdr_img.height // 2
            left_end = hx - neon_bar_pad
            right_start = hx + hdr_img.width + neon_bar_pad
            if left_end > PADDING:
                draw.rectangle(
                    [PADDING, bar_y - neon_bar_thick // 2,
                     left_end, bar_y + neon_bar_thick // 2],
                    fill=fabled_color)
            if right_start < img_width - PADDING:
                draw.rectangle(
                    [right_start, bar_y - neon_bar_thick // 2,
                     img_width - PADDING, bar_y + neon_bar_thick // 2],
                    fill=fabled_color)
            y += hdr_img.height + neon_hdr_gap
        else:
            header_text = "FABLED & LORIC"
            draw.text((PADDING, y + 4 * SCALE), header_text, fill=theme_header, font=f_header)
            hb = draw.textbbox((PADDING, y + 4 * SCALE), header_text, font=f_header)
            text_mid_y = (hb[1] + hb[3]) // 2
            draw.line([(hb[2] + 10 * SCALE, text_mid_y), (img_width - PADDING, text_mid_y)],
                      fill=theme_line, width=DIVIDER_THICKNESS)
            y += HEADER_HEIGHT

        for fl in fabled_loric:
            color = theme_names.get(fl["team"], theme_header)
            icon = _load_icon(fl["id"], icon_urls=fl.get("icon_urls")) or ph

            row_h = _draw_row(draw, img, PADDING, y, icon, fl["name"], fl["ability"],
                              color, fonts, fl_text_width, ability_color=theme_ability)
            y += row_h

            # Jinxes unter Djinn
            if fl["id"] == DJINN_ID and jinxes:
                for jnx in jinxes:
                    a_info = chars_db.get(jnx["char_a"], {})
                    b_info = chars_db.get(jnx["char_b"], {})
                    hw_a = content_data.get(jnx["char_a"], {})
                    hw_b = content_data.get(jnx["char_b"], {})
                    name_a = a_info.get("character_name") or hw_a.get("name") or jnx["char_a"]
                    name_b = b_info.get("character_name") or hw_b.get("name") or jnx["char_b"]
                    team_a = a_info.get("character_type") or _team_from_content(hw_a.get("team")) or "Townsfolk"
                    team_b = b_info.get("character_type") or _team_from_content(hw_b.get("team")) or "Townsfolk"
                    is_evil_a = team_a in ("Minion", "Demon")
                    is_evil_b = team_b in ("Minion", "Demon")
                    icon_a = _load_icon(jnx["char_a"], evil=is_evil_a, size=ICON_JINX,
                                        icon_urls=hw_a.get("image")) or ph_jinx
                    icon_b = _load_icon(jnx["char_b"], evil=is_evil_b, size=ICON_JINX,
                                        icon_urls=hw_b.get("image")) or ph_jinx

                    reason_lines = _wrap(jnx["reason"], jinx_wrap_chars)
                    header_h = SZ_NAME + 4 * SCALE
                    text_h = len(reason_lines) * JINX_LINE_HEIGHT
                    content_h = header_h + text_h
                    jh = max(ICON_JINX, content_h)

                    # Icons + Text zentriert
                    icon_y = y + (jh - ICON_JINX) // 2
                    _paste(img, icon_a, jinx_x, icon_y)
                    _paste(img, icon_b, jinx_x + ICON_JINX - 8 * SCALE, icon_y)
                    text_x = jinx_x + ICON_JINX * 2 - 4 * SCALE

                    content_y = y + (jh - content_h) // 2
                    draw.text((text_x, content_y), f"{name_a} & {name_b}",
                              fill=theme_ability, font=f_name)

                    jt_y = content_y + header_h
                    for li, line in enumerate(reason_lines):
                        draw.text((text_x, jt_y + li * JINX_LINE_HEIGHT),
                                  line, fill=theme_ability, font=f_jinx)
                    y += jh

            # Bootlegger-Regeln
            if fl["id"] == "bootlegger" and bootlegger_rules:
                for rule in bootlegger_rules:
                    lines = _wrap(rule, boot_wrap_chars)
                    draw.text((jinx_x, y), "•", fill=theme_ability, font=f_jinx)
                    for li, line in enumerate(lines):
                        draw.text((jinx_x + 12 * SCALE, y + li * JINX_LINE_HEIGHT),
                                  line, fill=theme_ability, font=f_jinx)
                    y += len(lines) * JINX_LINE_HEIGHT + 2 * SCALE

        y += SECTION_GAP

    # ── Footer ────────────────────────────────────────────────────────
    y = height - FOOTER_HEIGHT
    draw.text((PADDING, y + 4 * SCALE), "© Steven Medway  bloodontheclocktower.com",
              fill=theme_footer, font=f_footer)
    nfn = "*not the first night"
    nb = draw.textbbox((0, 0), nfn, font=f_footer)
    draw.text((img_width - PADDING - (nb[2] - nb[0]), y + 4 * SCALE), nfn,
              fill=theme_footer, font=f_footer)

    # ── Finishing: Color-Grading pro Design-Variante ──────────────────
    if not transparent:
        if is_starfield_gold:
            img = _apply_finishing_filter_gold(img)

    # ── Export ────────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    logger.info("Script-Bild: '%s' (%dx%d, %d chars, %d jinxes)",
                script_name, img_width, height, len(char_ids), len(jinxes))
    return buf


async def generate_script_image(script_name, author, char_ids,
                                 version="", meta=None, content=None, transparent=False, show_fabled=True, design=DESIGN_PLAIN_WHITE):
    """Generiert ein Script-Bild als PNG."""
    return await asyncio.to_thread(_generate_sync, script_name, author, char_ids, version, meta, content, transparent, show_fabled, design)
