"""Script-Bild-Generierung mit Pillow.

Erzeugt ein PNG-Bild eines BotC-Scripts mit Character-Icons, Namen und Abilities,
gruppiert nach Team (Townsfolk, Outsider, Minion, Demon, Traveller, Fabled, Loric).

Layout: 2 Charaktere pro Reihe, weißer Hintergrund, Kategorie-Header mit Trennlinie.
"""

import asyncio
import io
import logging
import os
import re
import textwrap

from PIL import Image, ImageDraw, ImageFont

from logic.script_cache import get_character_icon_path, load_characters, STATIC_DIR

logger = logging.getLogger(__name__)

# ── Layout-Konstanten ────────────────────────────────────────────────────────

COLS = 2
ICON_SIZE = 64
CHAR_WIDTH = 420
CHAR_HEIGHT_BASE = 85      # Mindesthöhe, wird dynamisch erweitert
ABILITY_LINE_HEIGHT = 13
MAX_ABILITY_LINES = 6       # Mehr Zeilen erlauben, kein Cropping
PADDING = 30
SECTION_GAP = 15
TITLE_HEIGHT = 70
HEADER_HEIGHT = 35
TEXT_PADDING = 10
DIVIDER_THICKNESS = 2
FOOTER_HEIGHT = 30

# Farben
BG_COLOR = (255, 255, 255)          # Weiß
TITLE_COLOR = (4, 4, 4)             # Schwarz (#040404)
SUBTITLE_COLOR = (100, 100, 100)    # Grau
HEADER_COLOR = (4, 4, 4)            # Schwarz für Kategorie-Header
ABILITY_COLOR = (4, 4, 4)           # Schwarz für Beschreibungstext
ABILITY_BOLD_COLOR = (4, 4, 4)      # Schwarz für fette Teile
DIVIDER_COLOR = (200, 200, 200)     # Hellgrau
FOOTER_COLOR = (150, 150, 150)      # Grau

# Charakter-Name-Farben nach Team
NAME_COLORS = {
    "Townsfolk": (0, 100, 172),     # #0064ac — Blau (gut)
    "Outsider":  (0, 100, 172),     # #0064ac — Blau (gut)
    "Minion":    (180, 40, 40),     # Rot (böse)
    "Demon":     (180, 40, 40),     # Rot (böse)
    "Traveller": (150, 120, 200),
    "Fabled":    (107, 99, 60),     # #6b633c
    "Loric":     (117, 138, 84),    # #758a54
}

# Trennlinien-Farbe: schwarz
TEAM_LINE_COLOR = (4, 4, 4)

# Font-Pfade
FONT_DIR = os.path.join(STATIC_DIR, "fonts")
_FONT_TITLE = os.path.join(FONT_DIR, "Dumbledor.ttf")           # Dumbledor — Script-Titel
_FONT_AUTHOR = os.path.join(FONT_DIR, "Inter.ttf")              # Serif/Neutral — Autorname
_FONT_HEADER = os.path.join(FONT_DIR, "Dumbledor.ttf")          # Dumbledor — Kategorie-Header
_FONT_CHAR_NAME = os.path.join(FONT_DIR, "TradeGothic-BoldCond.otf")  # Trade Gothic Bold Condensed — Charakter-Name
_FONT_CHAR_ABILITY = os.path.join(FONT_DIR, "TradeGothic-Regular.otf") # Trade Gothic Regular — Ability-Text

TEAM_ORDER = ["Townsfolk", "Outsider", "Minion", "Demon", "Traveller", "Fabled", "Loric"]


def _get_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except (OSError, IOError):
        logger.warning("Font nicht gefunden: %s", path)
        return ImageFont.load_default()


def _load_icon(char_id: str) -> Image.Image | None:
    icon_path = get_character_icon_path(char_id)
    if icon_path is None:
        return None
    try:
        img = Image.open(icon_path).convert("RGBA")
        img = img.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
        return img
    except Exception as e:
        logger.debug("Icon laden fehlgeschlagen für %s: %s", char_id, e)
        return None


def _create_placeholder_icon() -> Image.Image:
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (220, 220, 230, 200))
    draw = ImageDraw.Draw(img)
    font = _get_font(_FONT_CHAR_NAME, 24)
    draw.text((ICON_SIZE // 2, ICON_SIZE // 2), "?", fill=(100, 100, 100), font=font, anchor="mm")
    return img


def _wrap_ability(text: str, max_chars: int = 42) -> list[str]:
    """Bricht Ability-Text um. Kein Cropping — vollständiger Text."""
    return textwrap.wrap(text, width=max_chars)


def _calc_char_height(ability_lines: int) -> int:
    """Berechnet die Höhe eines Character-Blocks basierend auf Ability-Zeilen."""
    text_height = 22 + ability_lines * ABILITY_LINE_HEIGHT + 5
    return max(CHAR_HEIGHT_BASE, text_height, ICON_SIZE + 10)


def _split_text_with_brackets(text: str) -> list[tuple[str, bool]]:
    """Splittet Text in Segmente: (text, is_bold).

    Alles innerhalb [...] wird als bold markiert (inkl. Klammern).
    """
    segments = []
    parts = re.split(r'(\[[^\]]*\])', text)
    for part in parts:
        if not part:
            continue
        if part.startswith('[') and part.endswith(']'):
            segments.append((part, True))
        else:
            segments.append((part, False))
    return segments


def _draw_ability_with_bold(draw: ImageDraw.Draw, x: int, y: int, text: str,
                             font_regular, font_bold, color: tuple, bold_color: tuple,
                             max_width: int = 320) -> int:
    """Zeichnet Ability-Text mit [bracketed] Teilen fett.

    Splitted erst nach Brackets, dann wrapped jedes Segment einzeln,
    damit Brackets nie zerrissen werden.

    Returns: Anzahl gezeichneter Zeilen.
    """
    # Erst Bracket-Segmente identifizieren, dann als Ganzes wrappen
    segments = _split_text_with_brackets(text)

    # Alles in Wörter mit Bold-Info aufteilen
    words: list[tuple[str, bool]] = []
    for segment_text, is_bold in segments:
        if is_bold:
            # Bracket-Inhalt als ein Wort behandeln (nicht umbrechen)
            words.append((segment_text, True))
        else:
            for word in segment_text.split():
                words.append((word, False))

    # Zeilenweise rendern mit Wort-Wrapping
    line_count = 0
    curr_x = x
    max_x = x + max_width

    for i, (word, is_bold) in enumerate(words):
        font = font_bold if is_bold else font_regular
        fill = bold_color if is_bold else color

        space = " " if curr_x > x else ""
        test_text = space + word
        bbox = draw.textbbox((0, 0), test_text, font=font)
        word_width = bbox[2] - bbox[0]

        # Passt das Wort noch in die aktuelle Zeile?
        if curr_x + word_width > max_x and curr_x > x:
            # Neue Zeile
            y += ABILITY_LINE_HEIGHT
            line_count += 1
            curr_x = x
            space = ""
            test_text = word

        draw.text((curr_x, y), space + word if curr_x > x else word, fill=fill, font=font)
        bbox = draw.textbbox((curr_x, y), space + word if curr_x > x else word, font=font)
        curr_x = bbox[2]

    line_count += 1  # Letzte Zeile zählen
    return line_count


def _categorize_for_image(char_ids: list[str]) -> dict[str, list[dict]]:
    characters_db = load_characters()
    categories: dict[str, list[dict]] = {team: [] for team in TEAM_ORDER}

    for char_id in char_ids:
        char_info = characters_db.get(char_id)
        if char_info:
            team = char_info.get("character_type", "Townsfolk")
            name = char_info.get("character_name", char_id)
            ability = char_info.get("ability", "")
        else:
            team = "Townsfolk"
            name = char_id.replace("_", " ").title()
            ability = ""

        if team not in categories:
            team = "Townsfolk"

        categories[team].append({
            "id": char_id,
            "name": name,
            "ability": ability,
            "team": team,
        })

    return categories


def _calculate_image_height(categories: dict[str, list[dict]]) -> int:
    height = PADDING + TITLE_HEIGHT + SECTION_GAP

    for team in TEAM_ORDER:
        chars = categories.get(team, [])
        if not chars:
            continue
        height += HEADER_HEIGHT + SECTION_GAP

        # Pro Reihe: max Höhe der beiden Spalten
        for row_start in range(0, len(chars), COLS):
            row_chars = chars[row_start:row_start + COLS]
            row_height = 0
            for char in row_chars:
                lines = len(_wrap_ability(char["ability"]))
                row_height = max(row_height, _calc_char_height(lines))
            height += row_height
        height += SECTION_GAP

    height += FOOTER_HEIGHT + PADDING
    return height


def _generate_sync(script_name: str, author: str, char_ids: list[str], version: str = "") -> io.BytesIO:
    categories = _categorize_for_image(char_ids)
    placeholder = _create_placeholder_icon()

    img_width = PADDING * 2 + COLS * CHAR_WIDTH
    img_height = _calculate_image_height(categories)

    img = Image.new("RGB", (img_width, img_height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    font_title = _get_font(_FONT_TITLE, 36)
    font_author = _get_font(_FONT_AUTHOR, 14)
    font_header = _get_font(_FONT_HEADER, 18)
    font_name = _get_font(_FONT_CHAR_NAME, 16)
    font_ability = _get_font(_FONT_CHAR_ABILITY, 12)
    font_ability_bold = _get_font(_FONT_CHAR_NAME, 12)  # Bold-Variante für [brackets]
    font_footer = _get_font(_FONT_AUTHOR, 9)

    y = PADDING

    # ── Titel (links) + Version (rechts neben Titel, am oberen Rand aligned) ─
    draw.text((PADDING, y), script_name, fill=TITLE_COLOR, font=font_title)
    if version:
        title_bbox = draw.textbbox((PADDING, y), script_name, font=font_title)
        title_mid = (title_bbox[1] + title_bbox[3]) // 2
        version_bbox = draw.textbbox((0, 0), f"v{version}", font=font_author)
        version_h = version_bbox[3] - version_bbox[1]
        version_x = title_bbox[2] + 12
        version_y = title_mid - version_h // 2  # Vertikal zentriert am Titel
        draw.text((version_x, version_y), f"v{version}", fill=SUBTITLE_COLOR, font=font_author)
    y += 36
    if author:
        draw.text((PADDING, y), f"by {author}", fill=SUBTITLE_COLOR, font=font_author)
    y += 28

    # ── Kategorien ───────────────────────────────────────────────────
    for team in TEAM_ORDER:
        chars = categories.get(team, [])
        if not chars:
            continue

        # Header mit Trennlinie
        line_color = TEAM_LINE_COLOR
        header_text = team.upper()
        draw.text((PADDING, y + 6), header_text, fill=HEADER_COLOR, font=font_header)

        text_bbox = draw.textbbox((PADDING, y + 6), header_text, font=font_header)
        line_start_x = text_bbox[2] + 12
        line_y = y + HEADER_HEIGHT // 2
        draw.line(
            [(line_start_x, line_y), (img_width - PADDING, line_y)],
            fill=line_color,
            width=DIVIDER_THICKNESS,
        )
        y += HEADER_HEIGHT

        # Characters in 2er-Reihen
        name_color = NAME_COLORS.get(team, (0, 100, 172))

        for row_start in range(0, len(chars), COLS):
            row_chars = chars[row_start:row_start + COLS]

            # Maximale Höhe dieser Reihe berechnen
            row_height = 0
            for char in row_chars:
                lines = len(_wrap_ability(char["ability"]))
                row_height = max(row_height, _calc_char_height(lines))

            for col_idx, char in enumerate(row_chars):
                x = PADDING + col_idx * CHAR_WIDTH
                char_y = y

                # Icon
                icon = _load_icon(char["id"])
                if icon is None:
                    icon = placeholder

                # Weißen Hintergrund unter Icon (falls RGBA)
                if icon.mode == "RGBA":
                    icon_bg = Image.new("RGB", (ICON_SIZE, ICON_SIZE), BG_COLOR)
                    icon_bg.paste(icon, (0, 0), icon)
                    img.paste(icon_bg, (x, char_y))
                else:
                    img.paste(icon, (x, char_y))

                # Name (farbig nach Team)
                text_x = x + ICON_SIZE + TEXT_PADDING
                draw.text((text_x, char_y + 3), char["name"], fill=name_color, font=font_name)

                # Ability (schwarz, mit [bold]-Erkennung, vollständig)
                if char["ability"]:
                    _draw_ability_with_bold(
                        draw, text_x, char_y + 20, char["ability"],
                        font_ability, font_ability_bold,
                        ABILITY_COLOR, ABILITY_BOLD_COLOR,
                    )

            y += row_height

        y += SECTION_GAP

    # ── Footer ───────────────────────────────────────────────────────
    y = img_height - FOOTER_HEIGHT
    draw.text((PADDING, y + 8), "© Steven Medway  bloodontheclocktower.com", fill=FOOTER_COLOR, font=font_footer)

    # "*not the first night" rechts
    nfn_text = "*not the first night"
    nfn_bbox = draw.textbbox((0, 0), nfn_text, font=font_footer)
    nfn_width = nfn_bbox[2] - nfn_bbox[0]
    draw.text((img_width - PADDING - nfn_width, y + 8), nfn_text, fill=FOOTER_COLOR, font=font_footer)

    # ── Export ────────────────────────────────────────────────────────
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)

    logger.info("Script-Bild generiert: '%s' (%dx%d, %d chars)", script_name, img_width, img_height, len(char_ids))
    return buffer


async def generate_script_image(script_name: str, author: str, char_ids: list[str], version: str = "") -> io.BytesIO:
    """Generiert ein Script-Bild als PNG."""
    return await asyncio.to_thread(_generate_sync, script_name, author, char_ids, version)
