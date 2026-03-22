"""Script-Bild-Generierung mit Pillow.

Erzeugt ein PNG im Stil der botcscripts.com PDFs.
Layout-Zentrierung über _draw_row() Helper — kein manuelles Pixel-Shifting.
"""

import asyncio
import io
import logging
import os
import re
import textwrap

import requests
from PIL import Image, ImageDraw, ImageFont

from logic.script_cache import (
    get_character_icon_path,
    get_jinxes_for_script,
    load_characters,
    STATIC_DIR,
)

logger = logging.getLogger(__name__)

# ── Layout ───────────────────────────────────────────────────────────────────

COLS = 2
ICON_SIZE = 80
ICON_SMALL = 36
ICON_JINX = 48
CHAR_WIDTH = 400
PADDING = 25
SECTION_GAP = 8
HEADER_HEIGHT = 28
ABILITY_LINE_HEIGHT = 13
JINX_LINE_HEIGHT = 14
FOOTER_HEIGHT = 22
TEXT_PADDING = 6
DIVIDER_THICKNESS = 1
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

SZ_TITLE = 36
SZ_AUTHOR = 14
SZ_FABLED_TITLE = 13
SZ_HEADER = 14
SZ_NAME = 15
SZ_ABILITY = 13
SZ_JINX = 12
SZ_FOOTER = 9

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
        bg = Image.new("RGB", icon.size, BG_COLOR)
        bg.paste(icon, (0, 0), icon)
        canvas.paste(bg, (x, y))
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


def _row_height(ability_text, icon_size=ICON_SIZE):
    """Berechnet die Höhe einer Zeile: max(Icon, Text)."""
    text_h = SZ_NAME + 4 + _text_height(ability_text)
    return max(icon_size, text_h)


def _draw_row(draw, img, x, y, icon, name, ability, name_color, fonts, text_width, icon_size=ICON_SIZE):
    """Zeichnet eine Zeile (Icon + Name + Ability) vertikal zentriert. Gibt row_height zurück."""
    # Sichtbare Texthöhe berechnen (mit Font-Offset-Korrektur)
    name_bb = draw.textbbox((0, 0), name, font=fonts["name"])
    name_h = name_bb[3] - name_bb[1] + 4
    name_offset = name_bb[1]
    ability_h = _text_height(ability)
    text_h = name_h + ability_h
    row_h = max(icon_size, text_h)

    # Icon: vertikal zentriert
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

def _generate_sync(script_name, author, char_ids, version="", meta=None, content=None):
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
    text_area_width = CHAR_WIDTH - ICON_SIZE - TEXT_PADDING - 5
    fl_text_width = img_width - PADDING * 2 - ICON_SIZE - TEXT_PADDING - 10

    # Jinx/Bootlegger text area
    jinx_x = PADDING + ICON_SIZE + TEXT_PADDING
    jinx_text_w = img_width - jinx_x - PADDING - 5
    jinx_icon_text_w = jinx_text_w - ICON_JINX * 2 + 4 - 6
    jinx_wrap_chars = max(40, jinx_icon_text_w // 7)
    boot_wrap_chars = max(40, (jinx_text_w - 12) // 7)

    # ── Höhe berechnen ────────────────────────────────────────────────
    height = PADDING + 42 + 18  # title + author
    if fabled_loric:
        height += 40  # fabled row
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

    if fabled_loric or jinxes or bootlegger_rules:
        height += HEADER_HEIGHT + SECTION_GAP
        for fl in fabled_loric:
            height += _row_height(fl["ability"])
            if fl["id"] == DJINN_ID and jinxes:
                for jnx in jinxes:
                    jh = SZ_NAME + 4 + len(_wrap(jnx["reason"], jinx_wrap_chars)) * JINX_LINE_HEIGHT + 5
                    height += max(ICON_JINX + 3, jh)
            if fl["id"] == "bootlegger" and bootlegger_rules:
                for rule in bootlegger_rules:
                    height += len(_wrap(rule, boot_wrap_chars)) * JINX_LINE_HEIGHT + 10
        height += SECTION_GAP

    height += FOOTER_HEIGHT + PADDING

    # ── Zeichnen ──────────────────────────────────────────────────────
    img = Image.new("RGB", (img_width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)
    y = PADDING

    # Titel + Version
    draw.text((PADDING, y), script_name, fill=TITLE_COLOR, font=f_title)
    if version:
        tb = draw.textbbox((PADDING, y), script_name, font=f_title)
        mid = (tb[1] + tb[3]) // 2
        vb = draw.textbbox((0, 0), f"v{version}", font=f_author)
        draw.text((tb[2] + 12, mid - (vb[3] - vb[1]) // 2),
                  f"v{version}", fill=SUBTITLE_COLOR, font=f_author)
    y += 42

    # Autor
    if author:
        draw.text((PADDING, y), f"by {author}", fill=SUBTITLE_COLOR, font=f_author)
    y += 18

    # Fabled/Loric Icons unter Autor
    if fabled_loric:
        fx = PADDING
        fabled_h = 40
        for fl in fabled_loric:
            icon = _load_icon(fl["id"], size=ICON_SMALL, icon_urls=fl.get("icon_urls")) or ph_sm
            icon_y = y + (fabled_h - ICON_SMALL) // 2
            _paste(img, icon, fx, icon_y)
            fx += ICON_SMALL + 5
            color = NAME_COLORS.get(fl["team"], TITLE_COLOR)
            # Text vertikal zentriert zum Icon (bbox offset korrigieren)
            text_bb = draw.textbbox((0, 0), fl["name"], font=f_fabled_t)
            text_h = text_bb[3] - text_bb[1]
            text_offset_y = text_bb[1]  # Font-Ascender-Offset
            text_y = y + (fabled_h - text_h) // 2 - text_offset_y
            draw.text((fx, text_y), fl["name"], fill=color, font=f_fabled_t)
            nb = draw.textbbox((fx, text_y), fl["name"], font=f_fabled_t)
            fx = nb[2] + 15
        y += fabled_h

    y += SECTION_GAP

    # ── Character Sektionen ───────────────────────────────────────────
    for team in TEAM_ORDER:
        chars = cats.get(team, [])
        if not chars:
            continue

        # Header
        header_text = team.upper()
        draw.text((PADDING, y + 4), header_text, fill=HEADER_COLOR, font=f_header)
        hb = draw.textbbox((PADDING, y + 4), header_text, font=f_header)
        text_mid_y = (hb[1] + hb[3]) // 2
        draw.line([(hb[2] + 10, text_mid_y), (img_width - PADDING, text_mid_y)],
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

                # _draw_row zentriert automatisch
                _draw_row(draw, img, x, y, icon, char["name"], char["ability"],
                          name_color, fonts, text_area_width)
            y += row_h
        y += SECTION_GAP

    # ── Fabled & Loric Sektion ────────────────────────────────────────
    if fabled_loric or jinxes or bootlegger_rules:
        header_text = "FABLED & LORIC"
        draw.text((PADDING, y + 4), header_text, fill=HEADER_COLOR, font=f_header)
        hb = draw.textbbox((PADDING, y + 4), header_text, font=f_header)
        text_mid_y = (hb[1] + hb[3]) // 2
        draw.line([(hb[2] + 10, text_mid_y), (img_width - PADDING, text_mid_y)],
                  fill=LINE_COLOR, width=DIVIDER_THICKNESS)
        y += HEADER_HEIGHT

        for fl in fabled_loric:
            color = NAME_COLORS.get(fl["team"], TITLE_COLOR)
            icon = _load_icon(fl["id"], icon_urls=fl.get("icon_urls")) or ph

            row_h = _draw_row(draw, img, PADDING, y, icon, fl["name"], fl["ability"],
                              color, fonts, fl_text_width)
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
                    header_h = SZ_NAME + 4
                    text_h = len(reason_lines) * JINX_LINE_HEIGHT
                    content_h = header_h + text_h
                    jh = max(ICON_JINX + 3, content_h + 5)

                    # Icons + Text zentriert
                    icon_y = y + (jh - ICON_JINX) // 2
                    _paste(img, icon_a, jinx_x, icon_y)
                    _paste(img, icon_b, jinx_x + ICON_JINX - 8, icon_y)
                    text_x = jinx_x + ICON_JINX * 2 - 4

                    content_y = y + (jh - content_h) // 2
                    draw.text((text_x, content_y), f"{name_a} & {name_b}",
                              fill=ABILITY_COLOR, font=f_name)

                    jt_y = content_y + header_h
                    for li, line in enumerate(reason_lines):
                        draw.text((text_x, jt_y + li * JINX_LINE_HEIGHT),
                                  line, fill=ABILITY_COLOR, font=f_jinx)
                    y += jh

            # Bootlegger-Regeln
            if fl["id"] == "bootlegger" and bootlegger_rules:
                for rule in bootlegger_rules:
                    lines = _wrap(rule, boot_wrap_chars)
                    draw.text((jinx_x, y), "•", fill=ABILITY_COLOR, font=f_jinx)
                    for li, line in enumerate(lines):
                        draw.text((jinx_x + 12, y + li * JINX_LINE_HEIGHT),
                                  line, fill=ABILITY_COLOR, font=f_jinx)
                    y += len(lines) * JINX_LINE_HEIGHT + 8

        y += SECTION_GAP

    # ── Footer ────────────────────────────────────────────────────────
    y = height - FOOTER_HEIGHT
    draw.text((PADDING, y + 4), "© Steven Medway  bloodontheclocktower.com",
              fill=FOOTER_COLOR, font=f_footer)
    nfn = "*not the first night"
    nb = draw.textbbox((0, 0), nfn, font=f_footer)
    draw.text((img_width - PADDING - (nb[2] - nb[0]), y + 4), nfn,
              fill=FOOTER_COLOR, font=f_footer)

    # ── Export ────────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    logger.info("Script-Bild: '%s' (%dx%d, %d chars, %d jinxes)",
                script_name, img_width, height, len(char_ids), len(jinxes))
    return buf


async def generate_script_image(script_name, author, char_ids,
                                 version="", meta=None, content=None):
    """Generiert ein Script-Bild als PNG."""
    return await asyncio.to_thread(_generate_sync, script_name, author, char_ids, version, meta, content)
