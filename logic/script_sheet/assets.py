"""Grafiken für das Skript-Blatt.

Zwei Quellen:
- Im Repo (frei bzw. selbst erstellt): Schriften unter OFL in static/fonts, Aquarell-Kleckse und eigene
  Nachtmarken in static/script_sheet/ (erzeugt mit `python -m logic.script_sheet.make_static`).
- Asset-Paket (lizenziert, darf NICHT ins Repo): Ornamente aus gekauften Etsy-Sets, Randmuster und die
  Nachtmarken aus dem TPI-Script-Tool. Gebaut mit `python -m logic.script_sheet.build_pack`, liegt auf dem
  Volume unter VOLUME_DIR/script_sheet_assets (überschreibbar mit der Umgebungsvariable SCRIPT_SHEET_ASSETS).

Fehlt das Paket ganz oder teilweise, entfällt das jeweilige Element: Rand einfarbig, keine Ornamente,
Kleckse nur aus den eigenen Formen, eigene Nachtmarken.
"""

import functools
import os

from PIL import Image, ImageFont

from logic.script_cache import STATIC_DIR, VOLUME_DIR

FONT_DIR = os.path.join(STATIC_DIR, "fonts")
OWN_DIR = os.path.join(STATIC_DIR, "script_sheet")
PACK_DIR = os.getenv("SCRIPT_SHEET_ASSETS") or os.path.join(VOLUME_DIR, "script_sheet_assets")
PATTERN_DPI = 200  # Auflösung, für die die Musterkachel im Paket gedacht ist

FONTS = {
    "title": ("PlayfairDisplay[wght].ttf", "Bold"),
    "title_black": ("PlayfairDisplay[wght].ttf", "Black"),
    "title_italic": ("PlayfairDisplay-Italic[wght].ttf", "Italic"),
    "title_italic_bold": ("PlayfairDisplay-Italic[wght].ttf", "Bold Italic"),
    "title_bodoni": ("BodoniModa[opsz,wght].ttf", "Bold"),
    "name": ("PlayfairDisplay[wght].ttf", "SemiBold"),
    "text": ("SourceSerif4[opsz,wght].ttf", "Regular"),
    "text_bold": ("SourceSerif4[opsz,wght].ttf", "SemiBold"),
    "label": ("Lato-Bold.ttf", None),
}

# Ornament-Pools aus dem Paket, von Dalyan im Review ausgewählt (27.10.2026). Schlüssel = Set-Kürzel und Datei,
# z. B. „m8:-87“ (Mystic-Set 8, Datei -87) oder „w:37“ (Witchcraft Graphics 37); Zuordnung in build_pack.SOURCES.
CORNER_RULES = ("m8:-87", "m8:-83", "m8:-88", "m8:-69")           # Eckstücke im Rahmen
TITLE_RULES = ("m8:-88", "m8:-69", "m8:-70", "mp:-17", "mp:-19", "mp:-23", "m7:-10", "m7:-3")
SEALS = ("m8:-26", "m8:-64", "m8:-68", "m8:-75", "m8:-86", "m2:-28", "m2:-10")
DIVIDERS = ("m8:-100", "mu:61", "mu:17", "m2:-47")                 # Trenner zum Anhang
SPARKLE = "mu:82"
MOTIFS = (  # Tusche-Zeichnungen neben dem Titel (ohne Kerzen und Blattwerk)
    "w:10", "w:101", "w:104", "w:107", "w:11", "w:12", "w:14", "w:16", "w:17", "w:21", "w:23", "w:24", "w:25",
    "w:26", "w:30", "w:31", "w:32", "w:33", "w:37", "w:40", "w:42", "w:44", "w:45", "w:47", "w:51", "w:52",
    "w:53", "w:56", "w:58", "w:61", "w:63", "w:64", "w:68", "w:69", "w:71", "w:74", "w:76", "w:86", "w:88",
    "w:92", "w:97", "w:98", "mu:10", "mu:14", "mu:16", "mu:18", "mu:19", "mu:2", "mu:20", "mu:21", "mu:23",
    "mu:24", "mu:25", "mu:27", "mu:28", "mu:29", "mu:30", "mu:31", "mu:32", "mu:33", "mu:34", "mu:35", "mu:36",
    "mu:5", "mu:76", "mu:77", "mu:8", "mu:86", "mu:88", "m2:-30", "m2:-32", "m2:-76", "m2:-83", "m2:-87",
    "m2:-90",
)
ALL_ORNAMENTS = tuple(dict.fromkeys(CORNER_RULES + TITLE_RULES + SEALS + DIVIDERS + (SPARKLE,) + MOTIFS))
PACK_WASH_COUNT = 9
NIGHT_TOKENS = ("dusk", "minioninfo", "demoninfo", "dawn")


def set_pack_dir(path):
    """Anderes Asset-Paket verwenden (Tests, Vorschau); leert alle Zwischenspeicher."""
    global PACK_DIR
    PACK_DIR = path
    for fn in (_mask, ornament, pattern_tile, pack_washes, night_token):
        fn.cache_clear()


def ornament_file(key):
    return os.path.join(PACK_DIR, "ornaments", key.replace(":", "_") + ".png")


@functools.lru_cache(maxsize=64)
def font(role, px):
    name, variation = FONTS[role]
    f = ImageFont.truetype(os.path.join(FONT_DIR, name), max(1, round(px)))
    if variation:
        f.set_variation_by_name(variation)
    return f


@functools.lru_cache(maxsize=None)
def _mask(key):
    """Form eines Ornaments (L-Maske aus dem Paket) oder None, wenn das Paket sie nicht enthält."""
    path = ornament_file(key)
    if not os.path.exists(path):
        return None
    return Image.open(path).convert("L")


def has(key):
    return _mask(key) is not None


@functools.lru_cache(maxsize=256)
def ornament(key, w, h, color, rot=0, flip=False, alpha=255):
    """Ornament einfarbig, gedreht/gespiegelt und in w × h px eingepasst (RGBA) oder None."""
    m = _mask(key)
    if m is None:
        return None
    m = m.crop(m.getbbox())
    if rot:
        m = m.rotate(rot, expand=True, resample=Image.Resampling.BICUBIC)
        m = m.crop(m.getbbox())
    if flip:
        m = m.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    s = min(w / m.width, h / m.height)
    m = m.resize((max(1, round(m.width * s)), max(1, round(m.height * s))), Image.Resampling.LANCZOS)
    if alpha < 255:
        m = m.point(lambda v: v * alpha // 255)
    out = Image.new("RGBA", m.size, color + (255,))
    out.putalpha(m)
    return out


def rule(key, length, thick, color, flip=False):
    """Schlanke Himmels-Linie waagrecht (die Vorlagen stehen senkrecht)."""
    return ornament(key, round(length), round(thick), color, rot=90, flip=flip)


@functools.lru_cache(maxsize=1)
def pattern_tile():
    """Nahtlose Musterkachel des Rands (L) oder None."""
    path = os.path.join(PACK_DIR, "pattern_tile.png")
    return Image.open(path).convert("L") if os.path.exists(path) else None


def _wash_shape(m):
    m = m.crop(m.getbbox())
    m.thumbnail((400, 400), Image.Resampling.LANCZOS)
    return m


@functools.lru_cache(maxsize=1)
def own_washes():
    """Selbst erzeugte Aquarell-Kleckse (L, 255 = viel Pigment); lockerer pigmentiert, daher verstärkt."""
    folder = os.path.join(OWN_DIR, "washes")
    files = sorted(f for f in os.listdir(folder) if f.endswith(".png")) if os.path.isdir(folder) else []
    return tuple(_wash_shape(Image.open(os.path.join(folder, f)).convert("L").point(lambda v: min(255, round(v * 1.6))))
                 for f in files)


@functools.lru_cache(maxsize=1)
def pack_washes():
    """Pinselstrich-Masken aus dem Paket (streifige Formen) – leer ohne Paket."""
    out = []
    for i in range(1, PACK_WASH_COUNT + 1):
        path = os.path.join(PACK_DIR, "washes", f"mask_{i}.png")
        if os.path.exists(path):
            out.append(_wash_shape(Image.open(path).convert("L")))
    return tuple(out)


@functools.lru_cache(maxsize=32)
def night_token(name, px):
    """Sondermarke der Nachtreihenfolge (TPI aus dem Paket, sonst die eigene) in px × px, oder None."""
    for path in (os.path.join(PACK_DIR, "night", name + ".png"), os.path.join(OWN_DIR, "night", name + ".png")):
        if os.path.exists(path):
            return fit(Image.open(path).convert("RGBA"), px)
    return None


def fit(img, px):
    """Bild in ein px-Quadrat einpassen (zentriert, transparent aufgefüllt)."""
    w, h = img.size
    s = px / max(w, h)
    img = img.resize((max(1, round(w * s)), max(1, round(h * s))), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    out.paste(img, ((px - img.width) // 2, (px - img.height) // 2), img)
    return out
