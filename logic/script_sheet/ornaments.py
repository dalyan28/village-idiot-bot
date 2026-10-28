"""Ornamentik: Rezept je Skript, Rahmen mit Eckstücken, Trenner-Emblem, Tinten-Kleckse für spielprägende
Charaktere. Alles in neutraler Tinte bzw. im Gold der Rahmenlinie; fehlt ein Asset, entfällt das Element.
"""

import functools
import hashlib
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from . import assets
from .style import FRAME, GOLD, PAPER, THEMES, mix

TITLE_TREATMENTS = ("rules", "seal", "sparkles", "motif", "seal", "motif")
TITLE_VARIANTS = ("P1", "P3", "P7", "P1", "P3", "P2")  # siehe title.VARIANTS; P2 seltener
WASH_MAX = 0.22  # Deckkraft der Kleckse bei Score 10; darunter abgestuft
WASH_ANCHORS = ("icon", "name", "text", "wide", "stroke", "right", "small")


def rng(name, salt=""):
    return random.Random(int(hashlib.sha1(f"{salt}{name}".encode("utf-8")).hexdigest(), 16))


def recipe(name):
    """Stabile, je Skript (bzw. je Event, siehe Script.seed) andere Kombination aus Titel-Variante, -Layout, -Behandlung, Eckstück und Trenner."""
    rnd = rng(name)
    r = {"title": rnd.choice(TITLE_TREATMENTS), "corner": rnd.choice(assets.CORNER_RULES)}
    r["title_rule"] = rnd.choice([k for k in assets.TITLE_RULES if k != r["corner"]])
    r["motif"] = rnd.choice(assets.MOTIFS)
    r["motif_side"] = rnd.choice(("left", "right"))
    r["motif_tuck"] = rnd.uniform(0.0, 0.35)  # wie weit das Motiv hinter den Rand-Buchstaben greift
    r["motif_rot"] = rnd.uniform(-12, 12)
    r["seal"] = rnd.choice(assets.SEALS)
    r["seal_place"] = rnd.choice(("center", "right", "left", "right"))
    r["seal_rot"] = rnd.uniform(8, 22) * rnd.choice((-1, 1))
    r["sparkles"] = r["title"] == "sparkles" or (r["title"] == "seal" and rnd.random() < 0.7)
    r["dots"] = r["title"] in ("seal", "sparkles") and rnd.random() < 0.5  # Punktzeile · ◆ · als Abschluss
    r["layout"] = rnd.choice(("center", "stacked"))
    r["divider"] = rnd.choice(assets.DIVIDERS)
    r["variant"] = rnd.choice(TITLE_VARIANTS)
    return r


def paper_box(pg):
    """Papierfläche innerhalb der goldenen Rahmenlinie (dorthin darf nichts überstehen)."""
    i = pg.m(FRAME + 6.5)
    return (i, i, pg.W - i, pg.H - i)


def paste_clipped(img, im, x, y, box, multiply=False):
    """RGBA-Element einfügen, nur innerhalb von box (x0, y0, x1, y1). multiply: wie Tinte (dunkelt nur ab)."""
    x, y = round(x), round(y)
    bx0, by0, bx1, by1 = (round(v) for v in box)
    cx0, cy0 = max(x, bx0), max(y, by0)
    cx1, cy1 = min(x + im.width, bx1), min(y + im.height, by1)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    part = im.crop((cx0 - x, cy0 - y, cx1 - x, cy1 - y))
    a = part.getchannel("A")
    if multiply:
        region = img.crop((cx0, cy0, cx1, cy1))
        region.paste(ImageChops.multiply(region, part.convert("RGB")), (0, 0), a)
        img.paste(region, (cx0, cy0))
    else:
        img.paste(part, (cx0, cy0), a)


# ── Rahmen ───────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=8)
def _border(theme, W, H, S, vivid=False):
    """Damast-Rand in zwei harten Tönen der Theme-Farbe; ohne Musterkachel einfarbig.
    vivid: kräftige Theme-Farben (Optik „plain“) statt dunkel mit Gold."""
    t = THEMES[theme]
    bg = t["vivid"][0] if vivid else mix(t["dark"], t["light"], 0.12)
    tile = assets.pattern_tile()
    if tile is None:
        return Image.new("RGB", (W, H), bg)
    fg = t["vivid"][1] if vivid else mix(mix(t["light"], GOLD, 0.45), bg, 0.25)
    tile = ImageOps.autocontrast(tile, cutoff=2)
    sc = S * 72 / assets.PATTERN_DPI * 0.75
    tile = tile.resize((round(tile.width * sc), round(tile.height * sc)), Image.Resampling.LANCZOS)
    tile = tile.point(lambda v: 255 if v > 118 else 0).filter(ImageFilter.GaussianBlur(0.6))
    out = Image.new("L", (W, H))
    for y in range(0, H, tile.height):
        for x in range(0, W, tile.width):
            out.paste(tile, (x, y))
    return ImageOps.colorize(out, bg, fg if vivid else mix(fg, bg, 0.35))


def frame(pg):
    """Musterrand, darin (Optik „fancy“) eine goldene Doppellinie. Mit Eckstück-Asset enden die Linien vor jeder Ecke in einer
    Raute; dort übernehmen zwei Himmels-Linien mit einem Stern im Eckpunkt."""
    f = round(pg.m(FRAME))
    mask = Image.new("L", (pg.W, pg.H), 255)
    ImageDraw.Draw(mask).rectangle((f, f, pg.W - f - 1, pg.H - f - 1), fill=0)
    pg.img.paste(_border(pg.theme_key, pg.W, pg.H, pg.S, pg.look.vivid), (0, 0), mask)
    if not pg.look.gold:
        return

    c = f + pg.m(4.1)   # Mittellinie zwischen den beiden Goldlinien
    gap = pg.m(5)       # Abstand zwischen Eckpunkt und Arm
    dia = pg.m(2.3)     # Raute, in die die Doppellinie ausläuft
    piece = assets.rule(pg.rec["corner"], pg.m(52), pg.m(6.5), GOLD)
    arm_end = c + gap + (max(piece.width, piece.height) if piece else 0)
    stop = arm_end + pg.m(3) + 2 * dia + pg.m(2.5) if piece else 0
    for inset, wpt in ((f + pg.m(3), 0.9), (f + pg.m(5.2), 0.4)):
        i, w = round(inset), max(1, round(pg.m(wpt)))
        a, b = (round(stop), round(pg.W - stop)) if piece else (i, pg.W - i)
        av, bv = (round(stop), round(pg.H - stop)) if piece else (i, pg.H - i)
        pg.dr.line([(a, i), (b, i)], fill=GOLD, width=w)
        pg.dr.line([(a, pg.H - i - 1), (b, pg.H - i - 1)], fill=GOLD, width=w)
        pg.dr.line([(i, av), (i, bv)], fill=GOLD, width=w)
        pg.dr.line([(pg.W - i - 1, av), (pg.W - i - 1, bv)], fill=GOLD, width=w)
    if not piece:
        return
    dc = arm_end + pg.m(3) + dia  # Mittelpunkt der Raute, vom Seitenrand gemessen
    for p in (dc, pg.W - dc):
        for q in (c, pg.H - c):
            pg.dr.polygon([(p - dia, q), (p, q - dia * 0.75), (p + dia, q), (p, q + dia * 0.75)], fill=GOLD)
    for p in (dc, pg.H - dc):
        for q in (c, pg.W - c):
            pg.dr.polygon([(q, p - dia), (q - dia * 0.75, p), (q, p + dia), (q + dia * 0.75, p)], fill=GOLD)
    vert = piece.rotate(-90, expand=True)
    star = assets.ornament(assets.SPARKLE, round(pg.m(11)), round(pg.m(11)), GOLD)
    for fx, fy in ((False, False), (True, False), (False, True), (True, True)):
        h, v = piece, vert
        if fx:
            h, v = h.transpose(Image.Transpose.FLIP_LEFT_RIGHT), v.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if fy:
            h, v = h.transpose(Image.Transpose.FLIP_TOP_BOTTOM), v.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        cx = pg.W - c if fx else c
        cy = pg.H - c if fy else c
        pg.paste(h, cx - gap - h.width if fx else cx + gap, cy - h.height / 2)
        pg.paste(v, cx - v.width / 2, cy - gap - v.height if fy else cy + gap)
        if star:
            pg.paste(star, cx - star.width / 2, cy - star.height / 2)


# ── Tinten-Kleckse für spielprägende Charaktere ─────────────────────────────

def _wash_strength(score):
    return WASH_MAX * {10: 1.0, 9: 0.8}.get(score, 0.62 if score >= 8 else 0.48)


def draw_wash(pg, name, color, score, x, y, icon_px):
    """Aquarell-Klecks hinter einem spielprägenden Charakter: je Charakter andere Form, Größe, Streckung,
    Drehung und Lage (am Icon, am Namen, im Text, breit darüber …); zwei Kleckse hintereinander bekommen nie
    dieselbe Lage. Deckkraft nach Score abgestuft, multipliziert, damit der Text dunkel bleibt."""
    own, pack = assets.own_washes(), assets.pack_washes()
    shapes = own + pack
    if not shapes:
        return
    rnd = rng(name, f"wash{pg.seed}" if getattr(pg, "seed", 0) else "wash")
    anchor = rnd.choice([a for a in WASH_ANCHORS if a != getattr(pg, "wash_prev", None)])
    pg.wash_prev = anchor
    text_x = x + icon_px * 1.2
    cx, fy, fw, fh = {  # Mittelpunkt x, Mittelpunkt y, Breite, Höhe (relativ zur Icongröße)
        "icon": (x + icon_px * rnd.uniform(0.3, 0.9), rnd.uniform(0.2, 0.8), rnd.uniform(1.8, 2.8), rnd.uniform(1.4, 2.1)),
        "name": (text_x + icon_px * rnd.uniform(0.6, 1.8), rnd.uniform(0.05, 0.35), rnd.uniform(2.6, 4.2), rnd.uniform(0.9, 1.4)),
        "text": (text_x + icon_px * rnd.uniform(1.4, 3.4), rnd.uniform(0.55, 1.0), rnd.uniform(2.6, 4.4), rnd.uniform(1.0, 1.6)),
        "wide": (x + icon_px * rnd.uniform(1.6, 2.8), rnd.uniform(0.3, 0.7), rnd.uniform(4.4, 6.2), rnd.uniform(1.2, 1.9)),
        "stroke": (x + icon_px * rnd.uniform(1.6, 2.6), rnd.uniform(0.3, 0.7), rnd.uniform(4.5, 6.5), rnd.uniform(1.8, 2.6)),
        "right": (text_x + icon_px * rnd.uniform(3.0, 4.6), rnd.uniform(0.2, 0.8), rnd.uniform(2.2, 3.4), rnd.uniform(1.2, 1.9)),
        "small": (x + icon_px * rnd.uniform(0.4, 2.2), rnd.uniform(0.2, 0.8), rnd.uniform(1.1, 1.6), rnd.uniform(0.8, 1.2)),
    }[anchor]
    w, h = round(icon_px * fw), round(icon_px * fh)
    # breite Striche bevorzugt aus den streifigen Paket-Masken, sonst aus allen Formen
    m = rnd.choice(pack) if anchor in ("stroke", "wide") and pack else shapes[rnd.randrange(len(shapes))]
    m = m.rotate(rnd.uniform(-35, 35) if anchor == "stroke" else rnd.uniform(0, 360), expand=True,
                 resample=Image.Resampling.BICUBIC)
    if rnd.random() < 0.5:
        m = m.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    m = m.crop(m.getbbox()).resize((w, h), Image.Resampling.LANCZOS)
    strength = _wash_strength(score) * rnd.uniform(0.85, 1.1)
    m = m.point(lambda v, o=strength: round(min(255, v * o)))
    cy = y + icon_px * fy
    left = cx - w / 2
    if left < pg.x0 - pg.m(10):  # nicht nach links aus dem Satzspiegel (sonst harte Kante am Rahmen)
        cx += pg.x0 - pg.m(10) - left
    parts = [(m, cx, cy)]
    if rnd.random() < 0.35:  # kleiner zweiter Klecks, versetzt
        m2 = shapes[rnd.randrange(len(shapes))].rotate(rnd.uniform(0, 360), expand=True)
        m2 = m2.crop(m2.getbbox() or (0, 0, 1, 1))
        s2 = rnd.uniform(0.35, 0.6)
        m2 = m2.resize((max(1, round(w * s2)), max(1, round(h * s2 * 1.2))), Image.Resampling.LANCZOS)
        m2 = m2.point(lambda v, o=strength * 0.8: round(min(255, v * o)))
        parts.append((m2, cx + w * rnd.uniform(-0.55, 0.55), cy + h * rnd.uniform(-0.5, 0.5)))
    tint = mix(color, PAPER, 0.25)
    for mm, px_, py_ in parts:
        im = Image.new("RGBA", mm.size, tint + (255,))
        im.putalpha(mm)
        paste_clipped(pg.img, im, px_ - mm.width / 2, py_ - mm.height / 2, paper_box(pg), multiply=True)
