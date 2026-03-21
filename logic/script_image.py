"""Script-Bild-Generierung mit Pillow.

Erzeugt ein PNG im Stil der botcscripts.com PDFs:
- Titel + Autor + Fabled/Loric Icons
- Townsfolk/Outsider/Minion/Demon Sektionen (2 Spalten)
- Fabled & Loric Sektion mit Jinxes und Bootlegger-Regeln
- Footer mit Copyright
"""

import asyncio
import io
import logging
import os
import re
import textwrap

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
ICON_SIZE = 90
ICON_SMALL = 28            # Kleine Icons für Jinxes und Fabled/Loric neben Titel
CHAR_WIDTH = 420
PADDING = 30
SECTION_GAP = 15
TITLE_HEIGHT = 50
AUTHOR_HEIGHT = 20
FABLED_TITLE_HEIGHT = 30   # Fabled/Loric Icons unter Autor
HEADER_HEIGHT = 30
ABILITY_LINE_HEIGHT = 13
JINX_LINE_HEIGHT = 14
JINX_INDENT = 40
FOOTER_HEIGHT = 25
TEXT_PADDING = 10
DIVIDER_THICKNESS = 2

# ── Farben ───────────────────────────────────────────────────────────────────

BG_COLOR = (255, 255, 255)
TITLE_COLOR = (4, 4, 4)
SUBTITLE_COLOR = (100, 100, 100)
HEADER_COLOR = (4, 4, 4)
ABILITY_COLOR = (4, 4, 4)
DIVIDER_COLOR = (200, 200, 200)
FOOTER_COLOR = (150, 150, 150)
LINE_COLOR = (4, 4, 4)

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

# Schriftgrößen (skaliert von A4-PDF pt → Pixel für ~900px breites Bild)
# Faktor ~1.5x gegenüber PDF pt
SZ_TITLE = 36
SZ_AUTHOR = 14
SZ_FABLED_TITLE = 12       # 8pt
SZ_HEADER = 14              # 9pt
SZ_NAME = 15                # 10pt
SZ_ABILITY = 13             # 8.5pt
SZ_JINX = 12
SZ_FOOTER = 9

TEAM_ORDER = ["Townsfolk", "Outsider", "Minion", "Demon"]
TEAM_ORDER_ALL = ["Townsfolk", "Outsider", "Minion", "Demon", "Traveller", "Fabled", "Loric"]


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except (OSError, IOError):
        return ImageFont.load_default()


def _load_icon(char_id: str, evil: bool = False, size: int = ICON_SIZE) -> Image.Image | None:
    icon_path = get_character_icon_path(char_id, evil=evil)
    if not icon_path:
        return None
    try:
        img = Image.open(icon_path).convert("RGBA")
        return img.resize((size, size), Image.Resampling.LANCZOS)
    except Exception:
        return None


def _placeholder(size: int = ICON_SIZE) -> Image.Image:
    img = Image.new("RGBA", (size, size), (220, 220, 230, 200))
    draw = ImageDraw.Draw(img)
    f = _font(_F_NAME, size // 3)
    draw.text((size // 2, size // 2), "?", fill=(100, 100, 100), font=f, anchor="mm")
    return img


def _paste_icon(canvas: Image.Image, icon: Image.Image, x: int, y: int):
    if icon.mode == "RGBA":
        bg = Image.new("RGB", icon.size, BG_COLOR)
        bg.paste(icon, (0, 0), icon)
        canvas.paste(bg, (x, y))
    else:
        canvas.paste(icon, (x, y))


def _wrap(text: str, max_chars: int = 42) -> list[str]:
    return textwrap.wrap(text, width=max_chars)


def _draw_ability(draw, x, y, text, font_r, font_b, max_width=310):
    """Zeichnet Ability-Text mit [bracketed] Teilen fett. Returns end_y."""
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
        draw.text((curr_x, y), space + word if curr_x > x else word,
                  fill=ABILITY_COLOR, font=f)
        bbox = draw.textbbox((curr_x, y), space + word if curr_x > x else word, font=f)
        curr_x = bbox[2]

    return y + ABILITY_LINE_HEIGHT


def _categorize(char_ids, chars_db):
    cats = {t: [] for t in TEAM_ORDER_ALL}
    for cid in char_ids:
        info = chars_db.get(cid, {})
        team = info.get("character_type", "Townsfolk")
        if team not in cats:
            team = "Townsfolk"
        cats[team].append({
            "id": cid, "name": info.get("character_name", cid),
            "ability": info.get("ability", ""), "team": team,
        })
    return cats


def _calc_char_height(ability: str, font_r) -> int:
    lines = len(_wrap(ability)) if ability else 1
    return max(ICON_SIZE + 5, 22 + lines * ABILITY_LINE_HEIGHT + 5)


def _generate_sync(script_name: str, author: str, char_ids: list[str],
                    version: str = "", meta: dict | None = None) -> io.BytesIO:
    chars_db = load_characters()
    cats = _categorize(char_ids, chars_db)
    jinxes = get_jinxes_for_script(char_ids)
    bootlegger_rules = (meta or {}).get("bootlegger", [])
    placeholder = _placeholder()
    placeholder_sm = _placeholder(ICON_SMALL)

    fabled_loric = cats.get("Fabled", []) + cats.get("Loric", [])

    font_title = _font(_F_TITLE, SZ_TITLE)
    font_author = _font(_F_AUTHOR, SZ_AUTHOR)
    font_fabled_title = _font(_F_AUTHOR, SZ_FABLED_TITLE)
    font_header = _font(_F_HEADER, SZ_HEADER)
    font_name = _font(_F_NAME, SZ_NAME)
    font_ability = _font(_F_ABILITY, SZ_ABILITY)
    font_ability_bold = _font(_F_NAME, SZ_ABILITY)
    font_jinx = _font(_F_ABILITY, SZ_JINX)
    font_jinx_bold = _font(_F_NAME, SZ_JINX)
    font_footer = _font(_F_AUTHOR, SZ_FOOTER)

    img_width = PADDING * 2 + COLS * CHAR_WIDTH

    # ── Höhe berechnen ───────────────────────────────────────────────
    height = PADDING + TITLE_HEIGHT + AUTHOR_HEIGHT
    if fabled_loric:
        height += FABLED_TITLE_HEIGHT
    height += SECTION_GAP

    for team in TEAM_ORDER:
        chars = cats.get(team, [])
        if not chars:
            continue
        height += HEADER_HEIGHT
        for i in range(0, len(chars), COLS):
            row = chars[i:i + COLS]
            height += max(_calc_char_height(c["ability"], font_ability) for c in row)
        height += SECTION_GAP

    # Fabled & Loric Sektion
    if fabled_loric or jinxes or bootlegger_rules:
        height += HEADER_HEIGHT + SECTION_GAP
        for fl in fabled_loric:
            height += _calc_char_height(fl["ability"], font_ability)
            # Jinxes für diesen Fabled
            fl_jinxes = [j for j in jinxes if j["char_a"] == fl["id"] or j["char_b"] == fl["id"]]
            for _ in fl_jinxes:
                height += max(ICON_SMALL + 5, 3 * JINX_LINE_HEIGHT)
        # Bootlegger-Regeln
        if bootlegger_rules:
            for rule in bootlegger_rules:
                height += len(_wrap(rule, 60)) * JINX_LINE_HEIGHT + 10
        # Restliche Jinxes (nicht Fabled-bezogen)
        other_jinxes = [j for j in jinxes if not any(
            j["char_a"] == fl["id"] or j["char_b"] == fl["id"] for fl in fabled_loric
        )]
        for _ in other_jinxes:
            height += max(ICON_SMALL + 5, 3 * JINX_LINE_HEIGHT)
        height += SECTION_GAP

    height += FOOTER_HEIGHT + PADDING

    # ── Zeichnen ─────────────────────────────────────────────────────
    img = Image.new("RGB", (img_width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)
    y = PADDING

    # Titel + Version
    draw.text((PADDING, y), script_name, fill=TITLE_COLOR, font=font_title)
    if version:
        tb = draw.textbbox((PADDING, y), script_name, font=font_title)
        mid = (tb[1] + tb[3]) // 2
        vb = draw.textbbox((0, 0), f"v{version}", font=font_author)
        draw.text((tb[2] + 12, mid - (vb[3] - vb[1]) // 2),
                  f"v{version}", fill=SUBTITLE_COLOR, font=font_author)
    y += TITLE_HEIGHT

    # Autor
    if author:
        draw.text((PADDING, y), f"by {author}", fill=SUBTITLE_COLOR, font=font_author)
    y += AUTHOR_HEIGHT

    # Fabled/Loric Icons + Namen neben Autor
    if fabled_loric:
        fx = PADDING
        for fl in fabled_loric:
            icon = _load_icon(fl["id"], size=ICON_SMALL)
            if icon:
                _paste_icon(img, icon, fx, y)
            else:
                _paste_icon(img, placeholder_sm, fx, y)
            fx += ICON_SMALL + 4
            color = NAME_COLORS.get(fl["team"], TITLE_COLOR)
            draw.text((fx, y + 6), fl["name"], fill=color, font=font_fabled_title)
            name_bb = draw.textbbox((fx, y + 6), fl["name"], font=font_fabled_title)
            fx = name_bb[2] + 15
        y += FABLED_TITLE_HEIGHT

    y += SECTION_GAP

    # ── Character Sektionen ──────────────────────────────────────────
    for team in TEAM_ORDER:
        chars = cats.get(team, [])
        if not chars:
            continue

        # Header
        header_text = team.upper()
        draw.text((PADDING, y + 4), header_text, fill=HEADER_COLOR, font=font_header)
        hb = draw.textbbox((PADDING, y + 4), header_text, font=font_header)
        line_y = y + HEADER_HEIGHT // 2
        draw.line([(hb[2] + 10, line_y), (img_width - PADDING, line_y)],
                  fill=LINE_COLOR, width=DIVIDER_THICKNESS)
        y += HEADER_HEIGHT

        name_color = NAME_COLORS.get(team, (0, 100, 172))
        is_evil = team in ("Minion", "Demon")

        for i in range(0, len(chars), COLS):
            row = chars[i:i + COLS]
            row_h = max(_calc_char_height(c["ability"], font_ability) for c in row)

            for col, char in enumerate(row):
                x = PADDING + col * CHAR_WIDTH
                icon = _load_icon(char["id"], evil=is_evil)
                _paste_icon(img, icon or placeholder, x, y)

                tx = x + ICON_SIZE + TEXT_PADDING
                draw.text((tx, y + 3), char["name"], fill=name_color, font=font_name)

                if char["ability"]:
                    _draw_ability(draw, tx, y + 22, char["ability"],
                                 font_ability, font_ability_bold)
            y += row_h
        y += SECTION_GAP

    # ── Fabled & Loric Sektion ───────────────────────────────────────
    if fabled_loric or jinxes or bootlegger_rules:
        header_text = "FABLED & LORIC"
        draw.text((PADDING, y + 4), header_text, fill=HEADER_COLOR, font=font_header)
        hb = draw.textbbox((PADDING, y + 4), header_text, font=font_header)
        line_y = y + HEADER_HEIGHT // 2
        draw.line([(hb[2] + 10, line_y), (img_width - PADDING, line_y)],
                  fill=LINE_COLOR, width=DIVIDER_THICKNESS)
        y += HEADER_HEIGHT

        for fl in fabled_loric:
            color = NAME_COLORS.get(fl["team"], TITLE_COLOR)
            icon = _load_icon(fl["id"], size=ICON_SIZE)
            _paste_icon(img, icon or placeholder, PADDING, y)

            tx = PADDING + ICON_SIZE + TEXT_PADDING
            draw.text((tx, y + 3), fl["name"], fill=color, font=font_name)
            if fl["ability"]:
                end_y = _draw_ability(draw, tx, y + 22, fl["ability"],
                                      font_ability, font_ability_bold)
            else:
                end_y = y + 22

            char_h = max(ICON_SIZE + 5, end_y - y + 5)
            y += char_h

            # Jinxes für diesen Fabled/Loric
            fl_jinxes = [j for j in jinxes if j["char_a"] == fl["id"] or j["char_b"] == fl["id"]]
            for jinx in fl_jinxes:
                # Icons der beiden beteiligten Chars
                other_id = jinx["char_b"] if jinx["char_a"] == fl["id"] else jinx["char_a"]
                jx = PADDING + JINX_INDENT

                icon_a = _load_icon(jinx["char_a"], evil=True, size=ICON_SMALL)
                icon_b = _load_icon(jinx["char_b"], evil=True, size=ICON_SMALL)
                _paste_icon(img, icon_a or placeholder_sm, jx, y)
                jx += ICON_SMALL + 4
                _paste_icon(img, icon_b or placeholder_sm, jx, y)
                jx += ICON_SMALL + 8

                # Jinx-Text
                reason_lines = _wrap(jinx["reason"], 55)
                for li, line in enumerate(reason_lines):
                    draw.text((jx, y + 2 + li * JINX_LINE_HEIGHT),
                              line, fill=ABILITY_COLOR, font=font_jinx)

                jinx_h = max(ICON_SMALL + 5, len(reason_lines) * JINX_LINE_HEIGHT + 8)
                y += jinx_h

        # Bootlegger-Regeln
        if bootlegger_rules:
            for rule in bootlegger_rules:
                rx = PADDING + JINX_INDENT
                draw.text((rx, y), "•", fill=ABILITY_COLOR, font=font_jinx)
                lines = _wrap(rule, 60)
                for li, line in enumerate(lines):
                    draw.text((rx + 12, y + li * JINX_LINE_HEIGHT),
                              line, fill=ABILITY_COLOR, font=font_jinx)
                y += len(lines) * JINX_LINE_HEIGHT + 8

        # Restliche Jinxes (nicht Fabled-bezogen)
        other_jinxes = [j for j in jinxes if not any(
            j["char_a"] == fl_char["id"] or j["char_b"] == fl_char["id"]
            for fl_char in fabled_loric
        )]
        for jinx in other_jinxes:
            jx = PADDING + JINX_INDENT
            icon_a = _load_icon(jinx["char_a"], size=ICON_SMALL)
            icon_b = _load_icon(jinx["char_b"], size=ICON_SMALL)
            _paste_icon(img, icon_a or placeholder_sm, jx, y)
            jx += ICON_SMALL + 4
            _paste_icon(img, icon_b or placeholder_sm, jx, y)
            jx += ICON_SMALL + 8

            reason_lines = _wrap(jinx["reason"], 55)
            for li, line in enumerate(reason_lines):
                draw.text((jx, y + 2 + li * JINX_LINE_HEIGHT),
                          line, fill=ABILITY_COLOR, font=font_jinx)
            y += max(ICON_SMALL + 5, len(reason_lines) * JINX_LINE_HEIGHT + 8)

        y += SECTION_GAP

    # ── Footer ───────────────────────────────────────────────────────
    y = height - FOOTER_HEIGHT
    draw.text((PADDING, y + 5), "© Steven Medway  bloodontheclocktower.com",
              fill=FOOTER_COLOR, font=font_footer)
    nfn = "*not the first night"
    nb = draw.textbbox((0, 0), nfn, font=font_footer)
    draw.text((img_width - PADDING - (nb[2] - nb[0]), y + 5), nfn,
              fill=FOOTER_COLOR, font=font_footer)

    # ── Export ────────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    logger.info("Script-Bild: '%s' (%dx%d, %d chars, %d jinxes)",
                script_name, img_width, height, len(char_ids), len(jinxes))
    return buf


async def generate_script_image(script_name: str, author: str, char_ids: list[str],
                                 version: str = "", meta: dict | None = None) -> io.BytesIO:
    """Generiert ein Script-Bild als PNG."""
    return await asyncio.to_thread(_generate_sync, script_name, author, char_ids, version, meta)
