"""Titel im Exlibris-Kopf: klare Antiqua (Playfair Display, Bodoni Moda) in Tinte, darunter „by Autor“.

Der Titel nimmt nie viel Platz: bevorzugt eine Zeile (lieber etwas kleiner), zwei Zeilen erst, wenn eine
Zeile unter SINGLE_MIN_PT fiele, und dann höchstens TWO_LINE_MAX_PT. Füllwörter („The“, „in“ …) werden je
nach Variante kursiv und kleiner gesetzt; im Layout „stacked“ stehen sie auf eigener Zeile.
Behandlungen (je Skript aus dem Rezept): rules (Himmels-Linien links/rechts), seal (blasses Emblem hinter
dem Titel), sparkles (Funkelsterne), motif (Tusche-Zeichnung neben dem Titel). Fehlt das Asset, bleibt der
Titel schlicht.
"""

from dataclasses import dataclass

from PIL import ImageDraw

from . import assets
from .ornaments import paste_clipped
from .style import GREY, ORNAMENT_INK, TITLE_INK

MAX_PT = 32
SINGLE_MIN_PT = 22
TWO_LINE_MAX_PT = 24
ABS_MIN_PT = 18
AUTHOR_PT = 11
SMALL_SCALE = 0.58  # Füllwort-Zeile im Layout „stacked“
FILLERS = {"the", "of", "in", "and", "a", "an", "to", "for", "at", "on", "by", "&", "with", "from", "into"}


@dataclass(frozen=True)
class Variant:
    font: str             # Schriftrolle der Hauptwörter (assets.FONTS)
    filler: str = ""      # Schriftrolle der Füllwörter (leer = wie Hauptwörter)
    filler_scale: float = 0.7


VARIANTS = {
    "P1": Variant("title", "title_italic"),
    "P2": Variant("title_italic_bold"),
    "P3": Variant("title_bodoni", "title_italic"),
    "P7": Variant("title_black", "title_italic"),
}


def _words(words, v):
    """[(Wort, Füllwort?)]; das letzte Wort ist nie Füllwort."""
    return [(w, bool(v.filler) and i < len(words) - 1 and w.lower() in FILLERS) for i, w in enumerate(words)]


def _fonts(v, px):
    main = assets.font(v.font, px)
    return main, (assets.font(v.filler, px * v.filler_scale) if v.filler else main)


def _line_width(words, v, px):
    main, filler = _fonts(v, px)
    total = sum((filler if is_f else main).getlength(w) for w, is_f in words)
    return total + main.getlength(" ") * (len(words) - 1)


def _ink_shift(words, fonts, width):
    """Versatz, um den die sichtbare Form der Zeile neben ihrer Laufweite liegt. Kursive Buchstaben lehnen
    nach rechts und ragen über die Laufweite hinaus; ohne Ausgleich wirkt z. B. ein kleines „the“ über
    „Catacombs“ nicht mittig (Dalyan, 29.10.2026)."""
    left = fonts[0].getbbox(words[0], anchor="ls")[0]
    right = width - fonts[-1].getlength(words[-1]) + fonts[-1].getbbox(words[-1], anchor="ls")[2]
    return (left + right - width) / 2


def _draw_line(d, cx, base, words, v, px, color):
    main, filler = _fonts(v, px)
    fonts = [filler if is_f else main for _, is_f in words]
    width = _line_width(words, v, px)
    x = cx - width / 2 - _ink_shift([w for w, _ in words], fonts, width)
    for w, is_f in words:
        f = filler if is_f else main
        d.text((x, base), w, font=f, fill=color, anchor="ls")
        x += f.getlength(w) + main.getlength(" ")


def _fit_lines(name, v, width, S):
    """(Zeilen, px): eine Zeile bevorzugt, sonst zwei ausgeglichene."""
    words = _words(name.split(), v)
    px = MAX_PT * S
    while px >= SINGLE_MIN_PT * S:
        if _line_width(words, v, px) <= width:
            return [words], px
        px *= 0.96
    if len(words) > 1:
        splits = [(words[:i], words[i:]) for i in range(1, len(words))]
        px = TWO_LINE_MAX_PT * S
        while px >= ABS_MIN_PT * S:
            best = min(splits, key=lambda p: max(_line_width(p[0], v, px), _line_width(p[1], v, px)))
            if max(_line_width(best[0], v, px), _line_width(best[1], v, px)) <= width:
                return list(best), px
            px *= 0.96
    px = SINGLE_MIN_PT * S
    while _line_width(words, v, px) > width and px > ABS_MIN_PT * S:
        px *= 0.96
    return [words], px


def _rows(name, v, width, S, layout):
    """Zeilen [(Art, Wörter)] und Größe der Hauptzeilen. Arten: main, small (Füllwörter im Layout „stacked“)."""
    words = name.split()
    if layout == "stacked":
        segs = []
        for i, w in enumerate(words):
            is_f = 0 < i < len(words) - 1 and w.lower() in FILLERS  # führendes Füllwort bleibt bei der Hauptzeile
            if segs and segs[-1][0] == is_f:
                segs[-1][1].append(w)
            else:
                segs.append((is_f, [w]))
        mains = [seg for is_f, seg in segs if not is_f]
        if len(segs) > 1 and mains:
            px = (TWO_LINE_MAX_PT if len(mains) > 1 else MAX_PT) * S
            while px > ABS_MIN_PT * S and any(_line_width([(w, False) for w in s], v, px) > width for s in mains):
                px *= 0.96
            return [("small" if is_f else "main", [(w, False) for w in seg]) for is_f, seg in segs], px
    lines, px = _fit_lines(name, v, width, S)
    return [("main", line) for line in lines], px


def _treatment(rec):
    """Behandlung aus dem Rezept, aber nur, wenn das nötige Asset im Paket ist."""
    needed = {"rules": rec["title_rule"], "seal": rec["seal"], "motif": rec["motif"], "sparkles": assets.SPARKLE}
    treat = rec["title"]
    return treat if assets.has(needed[treat]) else "plain"


def draw_title(img, x0, x1, y, name, author, rec, S, clip):
    """Zeichnet Titel und Autor zentriert zwischen x0 und x1 ab y (img=None misst nur); clip ist die Papierfläche,
    über die Siegel und Motiv nie hinausragen. Liefert die y-Position unter dem Kopf."""
    v = VARIANTS[rec["variant"]]
    treat = _treatment(rec)
    sparkles = rec["sparkles"] and treat != "plain" and assets.has(assets.SPARKLE)
    dots = rec["dots"] and treat != "plain"
    side = {"rules": 0.6, "motif": 0.66}.get(treat, 0.74 if sparkles else 0.8)
    rows, px = _rows(name, v, (x1 - x0) * side, S, rec["layout"])
    cx = (x0 + x1) / 2
    asc, desc = assets.font(v.font, px).getmetrics()
    cap = asc * 0.72  # ungefähre Versalhöhe
    small = assets.font("title_italic", px * SMALL_SCALE)

    bases, cur = [], y + asc * 0.23
    for kind, _ in rows:
        if kind == "small":
            base = cur + small.getmetrics()[0] * 0.45 - px * 0.02
            cur = base + px * 0.12
        else:
            base = cur + cap
            cur = base + px * 0.3
        bases.append(base)
    first_main = next(i for i, (kind, _) in enumerate(rows) if kind == "main")
    block_top, last_base = bases[first_main] - cap, bases[-1]
    widest = max(_line_width(words, v, px) for kind, words in rows if kind == "main")
    fb = assets.font("title_italic", AUTHOR_PT * S)
    by_base = last_base + desc * 0.45 + fb.getmetrics()[0] + px * 0.05 if author else last_base
    end_y = by_base + fb.getmetrics()[1] * 0.5 if author else last_base + desc * 0.5
    if dots:
        end_y += px * 0.28
    if img is None:
        return end_y

    d = ImageDraw.Draw(img)
    if treat == "seal":  # blasses Strahlen-Emblem: mittig hinter dem Titel oder gedreht seitlich
        head_top, head_bot = clip[1] + px * 0.12, end_y + px * 0.12
        place = rec["seal_place"]
        seal = assets.ornament(rec["seal"], round(head_bot - head_top), round(head_bot - head_top), ORNAMENT_INK,
                               rot=0 if place == "center" else rec["seal_rot"], alpha=40)
        sx = {"center": cx, "right": cx + widest / 2 + px * 0.05, "left": cx - widest / 2 - px * 0.05}[place]
        paste_clipped(img, seal, sx - seal.width / 2, (head_top + head_bot) / 2 - seal.height / 2,
                      (clip[0], head_top, clip[2], head_bot))
    if treat == "motif":  # Tusche-Zeichnung neben dem Titel, greift leicht hinter den Rand-Buchstaben
        mh = round((end_y - block_top) * 1.15 + px * 0.2)
        mot = assets.ornament(rec["motif"], round(mh * 0.75), mh, ORNAMENT_INK, rot=rec["motif_rot"], alpha=150)
        sgn = 1 if rec["motif_side"] == "right" else -1
        mx = cx + sgn * (widest / 2 + px * 0.25 - mot.width * rec["motif_tuck"]) - (0 if sgn > 0 else mot.width)
        paste_clipped(img, mot, mx, (block_top + end_y) / 2 - mot.height / 2, clip)

    for (kind, words), base in zip(rows, bases):
        if kind == "small":
            text = " ".join(w for w, _ in words)
            width = small.getlength(text)
            x = cx - width / 2 - _ink_shift([text], [small], width)
            d.text((x, base), text, font=small, fill=TITLE_INK, anchor="ls")
        else:
            _draw_line(d, cx, base, words, v, px, TITLE_INK)

    if treat == "rules":  # Himmels-Linien links und rechts, auf Höhe der Titelmitte
        length = min(px * 3.6, (x1 - x0 - widest) / 2 - px * 0.5)
        mid = (block_top + last_base) / 2 if len(rows) > 1 else last_base - asc * 0.36
        rr = assets.rule(rec["title_rule"], length, px * 0.62, ORNAMENT_INK)
        rl = assets.rule(rec["title_rule"], length, px * 0.62, ORNAMENT_INK, flip=True)
        img.paste(rl, (round(cx - widest / 2 - px * 0.45 - rl.width), round(mid - rl.height / 2)), rl)
        img.paste(rr, (round(cx + widest / 2 + px * 0.45), round(mid - rr.height / 2)), rr)
    if sparkles:  # zwei Funkelsterne, asymmetrisch: oben links, unten rechts
        for sgn, yy in ((-1, block_top + px * 0.05), (1, last_base - px * 0.25)):
            for dx, dy, sz in ((0.38, 0.0, 0.4), (0.7, -0.32, 0.22)):
                st = assets.ornament(assets.SPARKLE, round(px * sz), round(px * sz), ORNAMENT_INK)
                img.paste(st, (round(cx + sgn * (widest / 2 + px * dx) - st.width / 2),
                               round(yy + px * dy - st.height / 2)), st)
    if author:
        d.text((cx, by_base), f"by {author}", font=fb, fill=GREY, anchor="ms")
    if dots:  # kleine Punktzeile · ◆ · als Abschluss
        yy, r = end_y - px * 0.12, px * 0.045
        for dx in (-px * 0.32, px * 0.32):
            d.ellipse((cx + dx - r, yy - r, cx + dx + r, yy + r), fill=ORNAMENT_INK)
        r *= 1.7
        d.polygon([(cx - r, yy), (cx, yy - r), (cx + r, yy), (cx, yy + r)], fill=ORNAMENT_INK)
    return end_y
