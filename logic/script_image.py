"""Script-Bild-Generierung mit Pillow.

Erzeugt ein PNG im Stil der botcscripts.com PDFs.
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
ICON_SIZE = 80              # Charakter-Icon (PDF: ~32x28, skaliert)
ICON_OVERLAP = -8           # Negativer Abstand → Icons überlappen leicht (kompakter)
ICON_SMALL = 36             # Fabled/Loric neben Autor (+30% von 28)
ICON_JINX = 48              # Jinx-Icons (doppelt so groß wie vorher)
CHAR_WIDTH = 400            # Schmaler → kompakter
PADDING = 25
SECTION_GAP = 8             # Weniger Abstand zwischen Sektionen
TITLE_HEIGHT = 42
AUTHOR_HEIGHT = 18
FABLED_TITLE_HEIGHT = 40
HEADER_HEIGHT = 28
ABILITY_LINE_HEIGHT = 13
JINX_LINE_HEIGHT = 14
JINX_INDENT = 35
FOOTER_HEIGHT = 22
TEXT_PADDING = 6            # Weniger Padding zwischen Icon und Text
DIVIDER_THICKNESS = 1

DJINN_ID = "djinn"          # Wird automatisch eingefügt wenn Jinxes existieren

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


def _load_icon(char_id, evil=False, size=ICON_SIZE, icon_urls=None):
    """Lädt ein Icon: lokal zuerst, dann URL-Fallback für Homebrew."""
    # Lokales Icon versuchen
    icon_path = get_character_icon_path(char_id, evil=evil)
    if icon_path:
        try:
            img = Image.open(icon_path).convert("RGBA")
            return img.resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            pass

    # URL-Fallback für Homebrew-Icons
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
                import requests
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


def _wrap(text, max_chars=42):
    return textwrap.wrap(text, width=max_chars)


def _text_height(text, max_chars=42):
    """Berechnet die Texthöhe in Pixeln."""
    lines = len(_wrap(text)) if text else 1
    return lines * ABILITY_LINE_HEIGHT


def _draw_ability(draw, x, y, text, font_r, font_b, max_width=300):
    """Zeichnet Ability mit [bracket]-Fettdruck. Returns end_y."""
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
    start_y = y
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

    return y + ABILITY_LINE_HEIGHT


def _categorize(char_ids, chars_db, content_data=None):
    """Kategorisiert Charaktere nach Team.

    content_data: Dict {char_id: {name, team, ability, image}} aus dem Script-Content
                  für Homebrew-Fallback.
    """
    content_data = content_data or {}
    cats = {t: [] for t in TEAM_ORDER_ALL}
    for cid in char_ids:
        info = chars_db.get(cid, {})
        hw = content_data.get(cid, {})

        # Team: chars_db > content_data > default
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


def _team_from_content(team_str):
    """Konvertiert team-String aus Content ('townsfolk') zu Display ('Townsfolk')."""
    if not team_str:
        return None
    mapping = {
        "townsfolk": "Townsfolk", "outsider": "Outsider",
        "minion": "Minion", "demon": "Demon",
        "traveller": "Traveller", "traveler": "Traveller",
        "fabled": "Fabled", "loric": "Loric",
    }
    return mapping.get(team_str.lower())


def _char_block_height(ability_text):
    """Höhe eines Charakter-Blocks: Icon oder Text, was größer ist."""
    text_h = 20 + _text_height(ability_text)  # Name + Ability
    return max(ICON_SIZE + ICON_OVERLAP, text_h)


def _generate_sync(script_name, author, char_ids, version="", meta=None, content=None):
    chars_db = load_characters()

    # Content-Dict für Homebrew-Fallback aufbauen
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

    # Auto-insert Djinn wenn Jinxes existieren und Djinn nicht schon im Script
    if jinxes and not any(fl["id"] == DJINN_ID for fl in fabled_loric):
        djinn_info = chars_db.get(DJINN_ID, {})
        fabled_loric.insert(0, {
            "id": DJINN_ID,
            "name": djinn_info.get("character_name", "Djinn"),
            "ability": djinn_info.get("ability", "Use the Djinn's special rule. All players know what it is."),
            "team": "Fabled",
        })
    # Djinn immer ganz oben
    fabled_loric.sort(key=lambda x: (0 if x["id"] == DJINN_ID else 1))

    f_title = _font(_F_TITLE, SZ_TITLE)
    f_author = _font(_F_AUTHOR, SZ_AUTHOR)
    f_fabled_t = _font(_F_AUTHOR, SZ_FABLED_TITLE)
    f_header = _font(_F_HEADER, SZ_HEADER)
    f_name = _font(_F_NAME, SZ_NAME)
    f_ability = _font(_F_ABILITY, SZ_ABILITY)
    f_ability_b = _font(_F_NAME, SZ_ABILITY)
    f_jinx = _font(_F_ABILITY, SZ_JINX)
    f_jinx_b = _font(_F_NAME, SZ_JINX)
    f_footer = _font(_F_AUTHOR, SZ_FOOTER)

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
            height += max(_char_block_height(c["ability"]) for c in row)
        height += SECTION_GAP

    # Jinx/Bootlegger wrap width (Text-Bereich ab Icon+Padding bis fast zum Rand)
    _jinx_text_x = PADDING + ICON_SIZE + TEXT_PADDING
    _jinx_text_w = img_width - _jinx_text_x - PADDING - 5
    _jinx_wrap = max(40, _jinx_text_w // 7)
    _boot_wrap = max(40, _jinx_text_w // 7)

    if fabled_loric or jinxes or bootlegger_rules:
        height += HEADER_HEIGHT + SECTION_GAP
        for fl in fabled_loric:
            height += _char_block_height(fl["ability"])
            # Alle Jinxes unter Djinn
            if fl["id"] == DJINN_ID and jinxes:
                for jnx in jinxes:
                    jh = SZ_NAME + 4 + len(_wrap(jnx["reason"], _jinx_wrap)) * JINX_LINE_HEIGHT + 5
                    height += max(ICON_JINX + 3, jh)
            # Alle Bootlegger-Regeln unter Bootlegger
            if fl["id"] == "bootlegger" and bootlegger_rules:
                for rule in bootlegger_rules:
                    height += len(_wrap(rule, _boot_wrap)) * JINX_LINE_HEIGHT + 10
        height += SECTION_GAP

    height += FOOTER_HEIGHT + PADDING

    # ── Zeichnen ─────────────────────────────────────────────────────
    img = Image.new("RGB", (img_width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)
    y = PADDING

    # Titel + Version
    draw.text((PADDING + 5, y), script_name, fill=TITLE_COLOR, font=f_title)
    if version:
        tb = draw.textbbox((PADDING + 5, y), script_name, font=f_title)
        mid = (tb[1] + tb[3]) // 2
        vb = draw.textbbox((0, 0), f"v{version}", font=f_author)
        draw.text((tb[2] + 12, mid - (vb[3] - vb[1]) // 2),
                  f"v{version}", fill=SUBTITLE_COLOR, font=f_author)
    y += TITLE_HEIGHT

    # Autor (leicht eingerückt)
    if author:
        draw.text((PADDING + 8, y), f"by {author}", fill=SUBTITLE_COLOR, font=f_author)
    y += AUTHOR_HEIGHT

    # Fabled/Loric Icons + Namen unter Autor (Icon + Text vertikal zentriert zueinander)
    if fabled_loric:
        fx = PADDING + 8
        for fl in fabled_loric:
            icon = _load_icon(fl["id"], size=ICON_SMALL, icon_urls=fl.get("icon_urls")) or ph_sm
            # Icon und Text jeweils zur Mitte der Zeile zentrieren
            icon_y = y + (FABLED_TITLE_HEIGHT - ICON_SMALL) // 2
            _paste(img, icon, fx, icon_y)
            fx += ICON_SMALL + 5
            color = NAME_COLORS.get(fl["team"], TITLE_COLOR)
            # Text vertikal zentriert zum Icon (Mitte Icon = Mitte Text)
            icon_mid = icon_y + ICON_SMALL // 2
            text_bb = draw.textbbox((0, 0), fl["name"], font=f_fabled_t)
            text_h = text_bb[3] - text_bb[1]
            text_y = icon_mid - text_h // 2
            draw.text((fx, text_y), fl["name"], fill=color, font=f_fabled_t)
            nb = draw.textbbox((fx, text_y), fl["name"], font=f_fabled_t)
            fx = nb[2] + 15
        y += FABLED_TITLE_HEIGHT

    y += SECTION_GAP

    # ── Character Sektionen ──────────────────────────────────────────
    text_area_width = CHAR_WIDTH - ICON_SIZE - TEXT_PADDING - 5

    for team in TEAM_ORDER:
        chars = cats.get(team, [])
        if not chars:
            continue

        # Header mit zentrierter Trennlinie
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
            row_h = max(_char_block_height(c["ability"]) for c in row)

            for col, char in enumerate(row):
                x = PADDING + col * CHAR_WIDTH

                # Text-Höhe berechnen für vertikale Zentrierung
                name_h = SZ_NAME + 4
                ability_h = _text_height(char["ability"])
                total_text_h = name_h + ability_h
                total_content_h = max(ICON_SIZE, total_text_h)

                # Vertikaler Offset für Zentrierung innerhalb row_h
                content_y = y + (row_h - total_content_h) // 2

                # Icon vertikal zentriert zum Text
                icon_y = content_y + (total_content_h - ICON_SIZE) // 2
                icon = _load_icon(char["id"], evil=is_evil, icon_urls=char.get("icon_urls")) or ph
                _paste(img, icon, x, icon_y)

                # Text vertikal zentriert
                text_y = content_y + (total_content_h - total_text_h) // 2
                tx = x + ICON_SIZE + TEXT_PADDING
                draw.text((tx, text_y), char["name"], fill=name_color, font=f_name)

                if char["ability"]:
                    _draw_ability(draw, tx, text_y + name_h, char["ability"],
                                  f_ability, f_ability_b, max_width=text_area_width)
            y += row_h
        y += SECTION_GAP

    # ── Fabled & Loric Sektion ───────────────────────────────────────
    if fabled_loric or jinxes or bootlegger_rules:
        header_text = "FABLED & LORIC"
        draw.text((PADDING, y + 4), header_text, fill=HEADER_COLOR, font=f_header)
        hb = draw.textbbox((PADDING, y + 4), header_text, font=f_header)
        text_mid_y = (hb[1] + hb[3]) // 2
        draw.line([(hb[2] + 10, text_mid_y), (img_width - PADDING, text_mid_y)],
                  fill=LINE_COLOR, width=DIVIDER_THICKNESS)
        y += HEADER_HEIGHT

        fl_text_width = img_width - PADDING * 2 - ICON_SIZE - TEXT_PADDING - 10

        # Jinx/Bootlegger Textbereich: eingerückt auf Text-Ebene (nicht Icon-Ebene)
        jinx_x = PADDING + ICON_SIZE + TEXT_PADDING  # Gleiche Einrückung wie Char-Text
        jinx_text_w = img_width - jinx_x - PADDING - 5
        jinx_icon_text_w = jinx_text_w - ICON_JINX * 2 + 4 - 6
        jinx_wrap_chars = max(40, jinx_icon_text_w // 7)
        boot_wrap_chars = max(40, (jinx_text_w - 12) // 7)

        for fl in fabled_loric:
            color = NAME_COLORS.get(fl["team"], TITLE_COLOR)
            block_h = _char_block_height(fl["ability"])

            # Icon
            icon = _load_icon(fl["id"], size=ICON_SIZE, icon_urls=fl.get("icon_urls")) or ph
            icon_y = y + (block_h - ICON_SIZE) // 2
            _paste(img, icon, PADDING, icon_y)

            # Text
            name_h = SZ_NAME + 4
            ability_h = _text_height(fl["ability"])
            total_text_h = name_h + ability_h
            text_y = y + (block_h - total_text_h) // 2
            tx = PADDING + ICON_SIZE + TEXT_PADDING

            draw.text((tx, text_y), fl["name"], fill=color, font=f_name)
            if fl["ability"]:
                _draw_ability(draw, tx, text_y + name_h, fl["ability"],
                              f_ability, f_ability_b, max_width=fl_text_width)
            y += block_h

            # Alle Jinxes unter dem Djinn
            if fl["id"] == DJINN_ID and jinxes:
                for jnx in jinxes:
                    char_a_info = chars_db.get(jnx["char_a"], {})
                    char_b_info = chars_db.get(jnx["char_b"], {})
                    name_a = char_a_info.get("character_name", jnx["char_a"])
                    name_b = char_b_info.get("character_name", jnx["char_b"])
                    team_a = char_a_info.get("character_type", "Townsfolk")
                    team_b = char_b_info.get("character_type", "Townsfolk")
                    color_a = NAME_COLORS.get(team_a, ABILITY_COLOR)
                    color_b = NAME_COLORS.get(team_b, ABILITY_COLOR)

                    is_evil_a = team_a in ("Minion", "Demon")
                    is_evil_b = team_b in ("Minion", "Demon")
                    icon_a = _load_icon(jnx["char_a"], evil=is_evil_a, size=ICON_JINX,
                                        icon_urls=content_data.get(jnx["char_a"], {}).get("image")) or ph_jinx
                    icon_b = _load_icon(jnx["char_b"], evil=is_evil_b, size=ICON_JINX,
                                        icon_urls=content_data.get(jnx["char_b"], {}).get("image")) or ph_jinx

                    reason_lines = _wrap(jnx["reason"], jinx_wrap_chars)
                    header_h = SZ_NAME + 4
                    text_h = len(reason_lines) * JINX_LINE_HEIGHT
                    content_h = header_h + text_h
                    jh = max(ICON_JINX + 3, content_h + 5)

                    # Icons auf Text-Ebene eingerückt
                    icon_y_j = y + (jh - ICON_JINX) // 2
                    _paste(img, icon_a, jinx_x, icon_y_j)
                    _paste(img, icon_b, jinx_x + ICON_JINX - 8, icon_y_j)
                    text_x = jinx_x + ICON_JINX * 2 - 4

                    # Überschrift: "Char A & Char B"
                    content_y = y + (jh - content_h) // 2
                    draw.text((text_x, content_y), name_a, fill=color_a, font=f_name)
                    ab = draw.textbbox((text_x, content_y), name_a, font=f_name)
                    draw.text((ab[2], content_y), " & ", fill=ABILITY_COLOR, font=f_name)
                    amp_bb = draw.textbbox((ab[2], content_y), " & ", font=f_name)
                    draw.text((amp_bb[2], content_y), name_b, fill=color_b, font=f_name)

                    # Jinx-Text
                    jt_y = content_y + header_h
                    for li, line in enumerate(reason_lines):
                        draw.text((text_x, jt_y + li * JINX_LINE_HEIGHT),
                                  line, fill=ABILITY_COLOR, font=f_jinx)
                    y += jh

            # Alle Bootlegger-Regeln unter dem Bootlegger
            if fl["id"] == "bootlegger" and bootlegger_rules:
                for rule in bootlegger_rules:
                    lines = _wrap(rule, boot_wrap_chars)
                    draw.text((jinx_x, y), "•", fill=ABILITY_COLOR, font=f_jinx)
                    for li, line in enumerate(lines):
                        draw.text((jinx_x + 12, y + li * JINX_LINE_HEIGHT),
                                  line, fill=ABILITY_COLOR, font=f_jinx)
                    y += len(lines) * JINX_LINE_HEIGHT + 8

        y += SECTION_GAP

    # ── Footer ───────────────────────────────────────────────────────
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
    """Generiert ein Script-Bild als PNG.

    content: Rohe Character-Dicts aus dem Script-JSON (für Homebrew-Icons/Namen/Abilities).
    """
    return await asyncio.to_thread(_generate_sync, script_name, author, char_ids, version, meta, content)
