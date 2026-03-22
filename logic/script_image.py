"""Script-Bild-Generierung mit HTML/CSS → PNG via html2image.

Erzeugt ein PNG im Stil der botcscripts.com PDFs.
Layout wird per HTML/CSS (Flexbox) definiert — kein manuelles Pixel-Positionieren.
"""

import asyncio
import base64
import io
import logging
import os
import re

import requests
from html2image import Html2Image
from PIL import Image

from logic.script_cache import (
    get_character_icon_path,
    get_jinxes_for_script,
    load_characters,
    STATIC_DIR,
)

logger = logging.getLogger(__name__)

DJINN_ID = "djinn"
TEAM_ORDER = ["Townsfolk", "Outsider", "Minion", "Demon"]
TEAM_ORDER_ALL = ["Townsfolk", "Outsider", "Minion", "Demon", "Traveller", "Fabled", "Loric"]

FONT_DIR = os.path.join(STATIC_DIR, "fonts")
_F_TITLE = os.path.join(FONT_DIR, "Dumbledor.ttf")
_F_AUTHOR = os.path.join(FONT_DIR, "Inter.ttf")
_F_NAME = os.path.join(FONT_DIR, "TradeGothic-BoldCond.otf")
_F_ABILITY = os.path.join(FONT_DIR, "TradeGothic-Regular.otf")

NAME_COLORS = {
    "Townsfolk": "#0064ac",
    "Outsider": "#0064ac",
    "Minion": "#b42828",
    "Demon": "#b42828",
    "Traveller": "#9678c8",
    "Fabled": "#6b633c",
    "Loric": "#758a54",
}

IMG_WIDTH = 850


# ── Icon Loading ──────────────────────────────────────────────────────────────

def _load_icon_b64(char_id, evil=False, icon_urls=None) -> str:
    """Lädt ein Icon und gibt es als Base64 Data-URL zurück."""
    # Lokales Icon versuchen
    icon_path = get_character_icon_path(char_id, evil=evil)
    if icon_path:
        try:
            with open(icon_path, "rb") as f:
                data = f.read()
            return f"data:image/png;base64,{base64.b64encode(data).decode()}"
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
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    return f"data:image/png;base64,{base64.b64encode(r.content).decode()}"
            except Exception as e:
                logger.debug("Homebrew-Icon download failed for %s: %s", char_id, e)

    return ""


def _placeholder_b64(size=80) -> str:
    """Erzeugt ein Placeholder-Icon als Base64."""
    from PIL import ImageDraw, ImageFont
    img = Image.new("RGBA", (size, size), (220, 220, 230, 200))
    draw = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype(_F_NAME, size // 3)
    except Exception:
        f = ImageFont.load_default()
    draw.text((size // 2, size // 2), "?", fill=(100, 100, 100), font=f, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


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


# ── Ability Formatting ────────────────────────────────────────────────────────

def _ability_html(text):
    """Konvertiert [bracket]-Text zu <b>-Tags und escaped HTML."""
    if not text:
        return ""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # [text] → <b>text</b>
    text = re.sub(r'\[([^\]]*)\]', r'<b>[\1]</b>', text)
    return text


# ── HTML Builder ──────────────────────────────────────────────────────────────

def _build_html(script_name, author, version, cats, fabled_loric, jinxes,
                bootlegger_rules, chars_db, content_data, placeholder):
    """Baut das komplette HTML für das Script-Bild."""

    # Font-Pfade für @font-face (absolute file:// URLs)
    font_title = _F_TITLE.replace("\\", "/")
    font_author = _F_AUTHOR.replace("\\", "/")
    font_name = _F_NAME.replace("\\", "/")
    font_ability = _F_ABILITY.replace("\\", "/")

    css = f"""
    @font-face {{ font-family: 'Dumbledor'; src: url('file:///{font_title}'); }}
    @font-face {{ font-family: 'Inter'; src: url('file:///{font_author}'); }}
    @font-face {{ font-family: 'TradeGothic'; src: url('file:///{font_ability}'); }}
    @font-face {{ font-family: 'TradeGothicBold'; src: url('file:///{font_name}'); }}

    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        width: {IMG_WIDTH}px;
        background: white;
        font-family: 'TradeGothic', Arial, sans-serif;
        color: #040404;
        padding: 25px;
    }}

    .title {{
        font-family: 'Dumbledor', serif;
        font-size: 36px;
        color: #040404;
        display: flex;
        align-items: baseline;
        gap: 12px;
    }}
    .version {{
        font-family: 'Inter', sans-serif;
        font-size: 14px;
        color: #646464;
    }}
    .author {{
        font-family: 'Inter', sans-serif;
        font-size: 14px;
        color: #646464;
        margin: 2px 0 4px 0;
    }}

    .fabled-row {{
        display: flex;
        align-items: center;
        gap: 5px;
        margin: 4px 0 8px 0;
        flex-wrap: wrap;
    }}
    .fabled-chip {{
        display: flex;
        align-items: center;
        gap: 5px;
        margin-right: 10px;
    }}
    .fabled-chip img {{ width: 36px; height: 36px; }}
    .fabled-chip span {{ font-family: 'Inter', sans-serif; font-size: 13px; }}

    .section-header {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 8px 0 4px 0;
    }}
    .section-header span {{
        font-family: 'Dumbledor', serif;
        font-size: 14px;
        white-space: nowrap;
    }}
    .section-header .line {{
        flex: 1;
        height: 1px;
        background: #040404;
    }}

    .char-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
    }}

    .char-block {{
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 2px 0;
        min-height: 72px;
    }}
    .char-block img {{
        width: 80px;
        height: 80px;
        flex-shrink: 0;
    }}
    .char-text {{
        display: flex;
        flex-direction: column;
        justify-content: center;
    }}
    .char-name {{
        font-family: 'TradeGothicBold', Arial, sans-serif;
        font-size: 15px;
        line-height: 1.2;
    }}
    .char-ability {{
        font-size: 13px;
        line-height: 1.3;
        color: #040404;
    }}

    .fl-section {{ margin-top: 4px; }}
    .fl-block {{
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 2px 0;
        min-height: 72px;
    }}
    .fl-block img {{
        width: 80px;
        height: 80px;
        flex-shrink: 0;
    }}

    .jinx-block {{
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 2px 0 2px 86px;
        min-height: 48px;
    }}
    .jinx-icons {{
        display: flex;
        flex-shrink: 0;
    }}
    .jinx-icons img {{
        width: 48px;
        height: 48px;
    }}
    .jinx-icons img:last-child {{
        margin-left: -8px;
    }}
    .jinx-text {{
        display: flex;
        flex-direction: column;
        justify-content: center;
    }}
    .jinx-header {{
        font-family: 'TradeGothicBold', Arial, sans-serif;
        font-size: 15px;
    }}
    .jinx-reason {{
        font-size: 12px;
        line-height: 1.3;
    }}

    .bootlegger-rule {{
        padding: 2px 0 2px 100px;
        font-size: 12px;
        line-height: 1.3;
    }}

    .footer {{
        display: flex;
        justify-content: space-between;
        margin-top: 12px;
        font-family: 'Inter', sans-serif;
        font-size: 9px;
        color: #969696;
    }}
    """

    parts = [f"<style>{css}</style>"]

    # Titel + Version
    parts.append(f'<div class="title">{_esc(script_name)}')
    if version:
        parts.append(f'<span class="version">v{_esc(version)}</span>')
    parts.append('</div>')

    # Autor
    if author:
        parts.append(f'<div class="author">by {_esc(author)}</div>')

    # Fabled/Loric Icons unter Autor
    if fabled_loric:
        parts.append('<div class="fabled-row">')
        for fl in fabled_loric:
            icon = _load_icon_b64(fl["id"], icon_urls=fl.get("icon_urls")) or placeholder
            color = NAME_COLORS.get(fl["team"], "#040404")
            parts.append(
                f'<div class="fabled-chip">'
                f'<img src="{icon}">'
                f'<span style="color:{color}">{_esc(fl["name"])}</span>'
                f'</div>'
            )
        parts.append('</div>')

    # Character Sektionen
    for team in TEAM_ORDER:
        chars = cats.get(team, [])
        if not chars:
            continue

        color = NAME_COLORS.get(team, "#0064ac")
        is_evil = team in ("Minion", "Demon")

        parts.append(f'<div class="section-header"><span>{team.upper()}</span><div class="line"></div></div>')
        parts.append('<div class="char-grid">')

        for char in chars:
            icon = _load_icon_b64(char["id"], evil=is_evil, icon_urls=char.get("icon_urls")) or placeholder
            parts.append(
                f'<div class="char-block">'
                f'<img src="{icon}">'
                f'<div class="char-text">'
                f'<div class="char-name" style="color:{color}">{_esc(char["name"])}</div>'
                f'<div class="char-ability">{_ability_html(char["ability"])}</div>'
                f'</div></div>'
            )

        parts.append('</div>')

    # Fabled & Loric Sektion
    if fabled_loric or jinxes or bootlegger_rules:
        parts.append('<div class="section-header"><span>FABLED &amp; LORIC</span><div class="line"></div></div>')
        parts.append('<div class="fl-section">')

        for fl in fabled_loric:
            color = NAME_COLORS.get(fl["team"], "#040404")
            icon = _load_icon_b64(fl["id"], icon_urls=fl.get("icon_urls")) or placeholder
            parts.append(
                f'<div class="fl-block">'
                f'<img src="{icon}">'
                f'<div class="char-text">'
                f'<div class="char-name" style="color:{color}">{_esc(fl["name"])}</div>'
                f'<div class="char-ability">{_ability_html(fl["ability"])}</div>'
                f'</div></div>'
            )

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
                    color_a = NAME_COLORS.get(team_a, "#040404")
                    color_b = NAME_COLORS.get(team_b, "#040404")
                    is_evil_a = team_a in ("Minion", "Demon")
                    is_evil_b = team_b in ("Minion", "Demon")
                    icon_a = _load_icon_b64(jnx["char_a"], evil=is_evil_a,
                                            icon_urls=hw_a.get("image")) or placeholder
                    icon_b = _load_icon_b64(jnx["char_b"], evil=is_evil_b,
                                            icon_urls=hw_b.get("image")) or placeholder

                    parts.append(
                        f'<div class="jinx-block">'
                        f'<div class="jinx-icons"><img src="{icon_a}"><img src="{icon_b}"></div>'
                        f'<div class="jinx-text">'
                        f'<div class="jinx-header">'
                        f'{_esc(name_a)} &amp; {_esc(name_b)}'
                        f'</div>'
                        f'<div class="jinx-reason">{_esc(jnx["reason"])}</div>'
                        f'</div></div>'
                    )

            # Bootlegger-Regeln
            if fl["id"] == "bootlegger" and bootlegger_rules:
                for rule in bootlegger_rules:
                    parts.append(f'<div class="bootlegger-rule">• {_esc(rule)}</div>')

        parts.append('</div>')

    # Footer
    parts.append(
        '<div class="footer">'
        '<span>© Steven Medway  bloodontheclocktower.com</span>'
        '<span>*not the first night</span>'
        '</div>'
    )

    return "\n".join(parts)


def _esc(text):
    """HTML-Escape."""
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
    placeholder = _placeholder_b64()

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

    html = _build_html(
        script_name, author, version, cats, fabled_loric,
        jinxes, bootlegger_rules, chars_db, content_data, placeholder,
    )

    # Render HTML → PNG
    import shutil
    import tempfile

    # Chromium-Pfad finden
    chrome_path = None
    # 1. Standard-Pfade per which
    for name in ["chromium-browser", "chromium", "google-chrome", "google-chrome-stable"]:
        found = shutil.which(name)
        if found:
            chrome_path = found
            break
    # 2. Nixpacks: Chromium liegt unter /nix/store/
    if not chrome_path:
        import glob
        nix_matches = glob.glob("/nix/store/*/bin/chromium")
        if nix_matches:
            chrome_path = nix_matches[0]

    logger.info("Chrome/Chromium path: %s", chrome_path or "NOT FOUND (using html2image default)")

    with tempfile.TemporaryDirectory() as tmpdir:
        kwargs = {
            "size": (IMG_WIDTH, 8000),
            "output_path": tmpdir,
            "custom_flags": [
                "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                "--disable-dev-shm-usage", "--disable-software-rasterizer",
            ],
        }
        if chrome_path:
            kwargs["browser_executable"] = chrome_path
        hti = Html2Image(**kwargs)
        hti.screenshot(html_str=html, save_as="script.png")

        png_path = os.path.join(tmpdir, "script.png")
        with Image.open(png_path) as img:
            # Auto-crop: Von unten nach oben scannen, erste nicht-weiße Zeile finden
            img = img.convert("RGB")
            pixels = img.load()
            w, h = img.size
            bottom = h
            for row in range(h - 1, 0, -1):
                is_white = all(
                    pixels[x, row][0] > 250 and pixels[x, row][1] > 250 and pixels[x, row][2] > 250
                    for x in range(0, w, 10)  # Jeden 10. Pixel prüfen (schneller)
                )
                if not is_white:
                    bottom = row + 15  # Etwas Padding
                    break

            cropped = img.crop((0, 0, w, min(bottom, h)))

            buf = io.BytesIO()
            cropped.save(buf, format="PNG", optimize=True)
            buf.seek(0)

    logger.info("Script-Bild: '%s' (%d chars, %d jinxes)",
                script_name, len(char_ids), len(jinxes))
    return buf


async def generate_script_image(script_name, author, char_ids,
                                 version="", meta=None, content=None):
    """Generiert ein Script-Bild als PNG."""
    return await asyncio.to_thread(_generate_sync, script_name, author, char_ids, version, meta, content)
