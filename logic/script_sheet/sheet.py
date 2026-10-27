"""Seitenaufbau des Skript-Blatts: Exlibris-Kopf, Charaktere zweispaltig je Team, Anhang (Fabled/Loric und
Jinxes, kleiner), Nachtreihenfolge in einer getönten Fläche, Fußzeile und Musterrahmen.

Ablauf: Layout messen (derselbe Code wie beim Zeichnen, nur ohne Zeichenfläche) → größte Skalierung suchen, bei
der alles auf A4 passt → Restplatz auf die Abschnittsabstände verteilen → zeichnen. Passt es nicht, wird die
Seite länger; ab MAX_LENGTH × A4 gibt es kein Bild.
"""

import functools
import random
import re
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from logic.script_cache import load_icon  # lokale TPI-Icons und Homebrew-URLs (mit Zwischenspeicher)

from . import assets, ornaments, title
from .model import DJINN_ID, GRID_TEAMS, NIGHT_SPECIALS, defining
from .style import (A4_H, A4_W, COMPACT, EXTRAS_SCALE, FRAME, GREY, GUTTER, HAIR, HEAD, INK, JINX_LIMIT, K_MAX,
                    K_MIN, LONG_K, MARGIN_X, MAX_LENGTH, NAME_COLORS, ORNAMENT_INK, PAPER, SEARCH_STEPS, SZ, THEMES,
                    TITLE_X)

TEAM_HEAD = {"Townsfolk": "Townsfolk", "Outsider": "Outsiders", "Minion": "Minions", "Demon": "Demons"}


# ── Papier und Icons ─────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=4)
def _paper(W, H):
    """Fast weißes Papier mit feiner, kaum sichtbarer Körnung und einem Hauch Randabdunklung."""
    rnd = random.Random(7)  # fest, damit das Papier immer gleich aussieht
    fibers = Image.new("L", (W // 5, H // 5))
    fibers.putdata([rnd.randint(0, 255) for _ in range(fibers.width * fibers.height)])
    fibers = fibers.resize((W, H), Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(1))
    paper = ImageOps.colorize(fibers, (247, 244, 238), PAPER)
    edge = Image.new("L", (W, H), 0)
    ImageDraw.Draw(edge).ellipse((-W * 0.2, -H * 0.12, W * 1.2, H * 1.12), fill=255)
    edge = edge.filter(ImageFilter.GaussianBlur(W / 7))
    return Image.composite(paper, ImageChops.multiply(paper, Image.new("RGB", (W, H), (246, 243, 237))), edge)


def _placeholder(px):
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, px - 1, px - 1), fill=(228, 222, 212, 255))
    d.text((px / 2, px / 2), "?", fill=GREY, font=assets.font("label", px * 0.5), anchor="mm")
    return img


@functools.lru_cache(maxsize=512)
def _icon(cid, evil, px, urls=()):
    """Icon auf den sichtbaren Inhalt beschnitten und in ein px-Quadrat eingepasst (einheitliche optische Größe)."""
    src = load_icon(cid, evil=evil, size=max(px * 2, 64), icon_urls=list(urls) or None)
    if src is None:
        return _placeholder(px)
    bbox = src.getchannel("A").getbbox()
    return assets.fit(src.crop(bbox) if bbox else src, px)


def _char_icon(ch, px):
    return _icon(ch.id, ch.evil, px, ch.urls)


@functools.lru_cache(maxsize=64)
def _receded(ch, px):
    """Hinteres Jinx-Icon: blasser, wie in die Ferne gerückt."""
    icon = _char_icon(ch, px)
    faded = Image.blend(icon, Image.new("RGBA", icon.size, PAPER + (255,)), 0.42)
    faded.putalpha(icon.getchannel("A"))
    return faded


@functools.lru_cache(maxsize=64)
def _with_shadow(ch, px, r):
    """Vorderes Jinx-Icon mit weichem Schatten (Ursprung bei −r), der auf das hintere fällt."""
    icon = _char_icon(ch, px)
    size = px + 2 * r
    sh = Image.new("L", (size, size), 0)
    sh.paste(icon.getchannel("A"), (r - r // 3, r - r // 3))
    sh = sh.filter(ImageFilter.GaussianBlur(r * 0.6)).point(lambda v: v * 55 // 100)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste((40, 30, 24, 255), (0, 0, size, size), sh)
    out.alpha_composite(icon, (r, r))
    return out


# ── Text ─────────────────────────────────────────────────────────────────────

def _tokens(text):
    """Wörter mit Fett-Markierung; [Setup-Text] wird fett."""
    out = []
    for seg in re.split(r"(\[[^\]]*\])", text or ""):
        if seg:
            bold = seg.startswith("[") and seg.endswith("]")
            out.extend((w, bold) for w in seg.split())
    return out


def _wrap(tokens, widths, sp, width):
    lines, cur = [], 0
    for tok, wl in zip(tokens, widths):
        if lines and cur + sp + wl <= width:
            lines[-1].append(tok)
            cur += sp + wl
        else:
            lines.append([tok])
            cur = wl
    return lines


@functools.lru_cache(maxsize=2048)
def _wrap_balanced(text, width, fr, fb):
    """Gleiche Zeilenzahl wie der gierige Umbruch, aber so schmal wie möglich → keine einzelnen Wörter am Ende."""
    tokens = _tokens(text)
    widths = [(fb if b else fr).getlength(w) for w, b in tokens]
    sp = fr.getlength(" ")
    lines = _wrap(tokens, widths, sp, width)
    if len(lines) > 1:
        lo, hi = width * 0.5, width
        for _ in range(10):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if len(_wrap(tokens, widths, sp, mid)) == len(lines) else (mid, hi)
        lines = _wrap(tokens, widths, sp, hi)
    return tuple(tuple(line) for line in lines)


def _lines_height(n, fr, lh):
    asc, desc = fr.getmetrics()
    return 0 if n == 0 else asc + desc * 0.4 + (n - 1) * lh


def _draw_lines(dr, x, y, lines, fr, fb, lh, color):
    asc, sp = fr.getmetrics()[0], fr.getlength(" ")
    for i, line in enumerate(lines):
        cx = x
        for w, b in line:
            f = fb if b else fr
            dr.text((cx, y + asc + i * lh), w, font=f, fill=color, anchor="ls")
            cx += f.getlength(w) + sp


def _spaced_width(text, font, tracking):
    return sum(font.getlength(ch) for ch in text) + tracking * (len(text) - 1)


def _draw_spaced(dr, x, y, text, font, tracking, color):
    for ch in text:
        dr.text((x, y), ch, font=font, fill=color, anchor="ls")
        x += font.getlength(ch) + tracking


# ── Seite ────────────────────────────────────────────────────────────────────

class Page:
    """Maße für eine Skalierung k; img/dr sind None, solange nur gemessen wird."""

    def __init__(self, sc, dpi, k, compact, theme, draw, extra=0):
        self.S, self.k, self.compact = dpi / 72, k, compact
        self.W, self.H = round(A4_W * self.S), round(A4_H * self.S + extra)
        self.x0, self.x1 = self.m(MARGIN_X), self.W - self.m(MARGIN_X)
        self.theme_key, self.theme = theme, THEMES[theme]
        self.sub = 1.0     # zusätzlicher Faktor für den Anhang
        self.spread = 0.0  # freier Platz, gleichmäßig auf die Abschnittsabstände verteilt
        self.slack = 0.0
        self.seed = sc.seed
        self.rec = ornaments.recipe(f"{sc.name}#{sc.seed}" if sc.seed else sc.name)
        self.defining = defining(sc)
        self.img = _paper(self.W, self.H).copy() if draw else None
        self.dr = ImageDraw.Draw(self.img) if draw else None

    def m(self, pt):  # Seitenmaß, skaliert nicht mit
        return pt * self.S

    def p(self, key_or_pt):  # Inhaltsmaß in px für die aktuelle Skalierung
        pt = key_or_pt
        if isinstance(key_or_pt, str):
            pt = COMPACT.get(key_or_pt, SZ[key_or_pt]) if self.compact else SZ[key_or_pt]
        return pt * self.S * self.k * self.sub

    def paste(self, icon, x, y):
        if self.img is not None:
            self.img.paste(icon, (round(x), round(y)), icon)


def _section_head(pg, label, y, icon=None, line=True):
    """Abschnitts-Überschrift: gesperrte Versalien links, eine feine Haarlinie bis zum rechten Rand.
    icon: optionales Charakter-Icon direkt nach dem Text (Djinn bei den Jinxes)."""
    f = assets.font("label", pg.p("head"))
    text, track = label.upper(), pg.p("head") * 0.24
    asc = f.getmetrics()[0]
    y += pg.p("section_gap") + (pg.spread if pg.sub == 1.0 else 0)
    if pg.dr:
        _draw_spaced(pg.dr, pg.x0, y + asc, text, f, track, HEAD)
        ly = round(y + asc * 0.6)
        x = pg.x0 + _spaced_width(text, f, track) + pg.p(6)
        if icon is not None:
            ipx = round(asc * 1.9)
            pg.paste(_char_icon(icon, ipx), x, ly - ipx / 2)
            x += ipx + pg.p(4)
        if line:
            pg.dr.line([(round(x + pg.p(4)), ly), (round(pg.x1), ly)], fill=HAIR, width=max(1, round(pg.m(0.6))))
    return y + asc + pg.p("head_gap")


# ── Einträge (Charaktere, Fabled/Loric, Jinxes) ─────────────────────────────

@dataclass
class Entry:
    name: str
    text: str
    color: tuple
    icons: tuple          # (Char,) oder (Char a, Char b) für Jinxes, leer für das Sammelfeld
    markers: tuple = ()   # Jinx-Partner neben dem Namen
    score: int = 0        # > 0: spielprägend → Tinten-Klecks, abgestuft nach Score


def _entry_layout(pg, e, text_w):
    f_name = assets.font("name", pg.p("name"))
    fr, fb = assets.font("text", pg.p("ability")), assets.font("text_bold", pg.p("ability"))
    lh = pg.p("ability") * SZ["lh"]
    lines = _wrap_balanced(e.text, round(text_w), fr, fb)
    name_h = pg.p("name") * 1.18
    return f_name, fr, fb, lh, lines, name_h, name_h + _lines_height(len(lines), fr, lh)


def _draw_entry(pg, e, x, y, h, text_w):
    f_name, fr, fb, lh, lines, name_h, th = _entry_layout(pg, e, text_w)
    icon_px = max(1, round(pg.p("icon")))
    iy = y + (h - icon_px) / 2
    if len(e.icons) == 1:
        if e.score and pg.img is not None:
            ornaments.draw_wash(pg, e.name, e.color, e.score, x, iy, icon_px)
        pg.paste(_char_icon(e.icons[0], icon_px), x, iy)
    elif len(e.icons) == 2:  # Jinx: hinteres Icon kleiner und blasser, vorderes kräftig mit Schatten
        a, b = e.icons
        back, front = round(icon_px * 0.62), round(icon_px * 0.76)
        r = max(2, round(pg.p(2.5)))
        pg.paste(_receded(a, back), x, iy)
        pg.paste(_with_shadow(b, front, r), x + icon_px - front - r, iy + icon_px - front - r)
    tx, ty = x + icon_px + pg.p(7), y + (h - th) / 2
    asc = f_name.getmetrics()[0]
    if pg.dr:
        pg.dr.text((tx, ty + asc), e.name, font=f_name, fill=e.color, anchor="ls")
    mx, mpx = tx + f_name.getlength(e.name) + pg.p(4), max(1, round(pg.p("marker")))
    for other in e.markers:  # Jinx-Marker: Icons der Partner direkt am Namen
        pg.paste(_char_icon(other, mpx), mx, ty + asc - mpx * 0.85)
        mx += mpx + pg.p(1)
    if pg.dr:
        _draw_lines(pg.dr, tx, ty + name_h, lines, fr, fb, lh, INK)


def _entries(pg, entries, y):
    """Einträge zweispaltig; eine unvollständige letzte Zeile bleibt rechts frei."""
    col_w = (pg.x1 - pg.x0 - pg.m(GUTTER)) / 2
    xs = (pg.x0, pg.x0 + col_w + pg.m(GUTTER))
    text_w = col_w - pg.p("icon") - pg.p(7)
    gap = pg.p("row_gap")
    for i in range(0, len(entries), 2):
        pair = entries[i:i + 2]
        h = max(max(pg.p("icon") * 0.92, _entry_layout(pg, e, text_w)[-1]) for e in pair)
        for col, e in enumerate(pair):
            _draw_entry(pg, e, xs[col], y + gap / 2, h, text_w)
        y += h + gap
    return y


def _characters(pg, sc, y):
    partners = {}
    for a, b, _ in sc.jinxes:
        partners.setdefault(a.id, []).append(b)
    for team in GRID_TEAMS:
        chars = sc.teams.get(team, [])
        if chars:
            y = _section_head(pg, TEAM_HEAD[team], y)
            y = _entries(pg, [Entry(c.name, c.ability, NAME_COLORS[team], (c,), tuple(partners.get(c.id, ())),
                                    pg.defining.get(c.id, 0)) for c in chars], y)
    return y


def _has_extras(sc):
    return bool(sc.fabled_loric or sc.jinxes or sc.rules)


def _extras(pg, sc, y):
    """Anhang: Fabled/Loric und Jinxes in einem gemeinsamen Raster, kleiner gesetzt. Der Djinn steht nur als
    Icon an der Überschrift, solange Jinxes da sind. Mehr als JINX_LIMIT Jinxes werden zusammengefasst."""
    pg.sub = EXTRAS_SCALE
    djinn = sc.by_id.get(DJINN_ID)
    npcs = [c for c in sc.fabled_loric if not (sc.jinxes and c.id == DJINN_ID)]
    label = [t for t, ok in (("Fabled", any(c.team == "Fabled" for c in npcs)),
                             ("Loric", any(c.team == "Loric" for c in npcs)), ("Jinxes", bool(sc.jinxes))) if ok]
    if label:
        y = _section_head(pg, " · ".join(label), y, icon=djinn if sc.jinxes else None, line=False)
        entries = [Entry(c.name, c.ability, NAME_COLORS[c.team], (c,)) for c in npcs]
        jinxes = sc.jinxes if len(sc.jinxes) <= JINX_LIMIT else sc.jinxes[:JINX_LIMIT - 1]
        entries += [Entry(f"{a.name} & {b.name}", reason, INK, (a, b)) for a, b, reason in jinxes]
        if len(jinxes) < len(sc.jinxes):
            entries.append(Entry(f"+ {len(sc.jinxes) - len(jinxes)} weitere Jinxes",
                                 "Die vollständige Liste steht im Skript-Tool.", GREY, (djinn,)))
        y = _entries(pg, entries, y)
    if sc.rules:
        y = _section_head(pg, "House Rules", y, line=False)
        fr, fb = assets.font("text", pg.p("ability")), assets.font("text_bold", pg.p("ability"))
        lh = pg.p("ability") * SZ["lh"]
        for rule in sc.rules:
            lines = _wrap_balanced(rule, round(pg.x1 - pg.x0 - pg.p(12)), fr, fb)
            if pg.dr:
                cy, r = y + fr.getmetrics()[0] * 0.65, pg.p(1.8)
                pg.dr.ellipse((pg.x0 + pg.p(2) - r, cy - r, pg.x0 + pg.p(2) + r, cy + r), fill=HEAD)
                _draw_lines(pg.dr, pg.x0 + pg.p(12), y, lines, fr, fb, lh, INK)
            y += _lines_height(len(lines), fr, lh) + pg.p("row_gap")
    pg.sub = 1.0
    return y


def _extras_panel(pg, sc, y, draw):
    """Anhang mit Trenner darüber: Haarlinie mit Emblem in der Mitte (ohne Emblem durchgehend). Liefert die Höhe."""
    sep = pg.m(14)
    img, dr = pg.img, pg.dr
    pg.img = pg.dr = None
    h = sep + _extras(pg, sc, 0) - pg.p("section_gap") * EXTRAS_SCALE * 0.5
    pg.img, pg.dr = img, dr
    if draw:
        cy, cx = y + sep / 2, (pg.x0 + pg.x1) / 2
        lw = max(1, round(pg.m(0.6)))
        emblem = assets.ornament(pg.rec["divider"], round(pg.m(70)), round(pg.m(11)), ORNAMENT_INK)
        half = emblem.width / 2 + pg.m(6) if emblem else 0
        pg.dr.line([(round(pg.x0), round(cy)), (round(cx - half), round(cy))], fill=HAIR, width=lw)
        pg.dr.line([(round(cx + half), round(cy)), (round(pg.x1), round(cy))], fill=HAIR, width=lw)
        if emblem:
            pg.paste(emblem, cx - emblem.width / 2, cy - emblem.height / 2)
        _extras(pg, sc, y + sep - pg.p("section_gap") * EXTRAS_SCALE * 0.5)
    return h


# ── Nachtreihenfolge und Fußzeile ────────────────────────────────────────────

def _night_height(pg):
    return pg.p("section_gap") + 2 * pg.p(7) + 2 * (pg.p("night_icon") + pg.p(4)) + pg.p(2)


def _night_block(pg, sc, y):
    """Getönte Fläche mit zwei Icon-Leisten: erste Nacht und andere Nächte."""
    y += pg.p("section_gap")
    pad, row_h = pg.p(7), pg.p("night_icon") + pg.p(4)
    box = (round(pg.x0 - pg.m(6)), round(y), round(pg.x1 + pg.m(6)), round(y + 2 * pad + 2 * row_h + pg.p(2)))
    pg.dr.rounded_rectangle(box, radius=round(pg.m(5)), fill=pg.theme["tint"])
    f_lab = assets.font("label", pg.p("night_label"))
    label_w = pg.p(70)
    avail = pg.x1 - pg.x0 - label_w
    ry = y + pad
    for label, order in (("FIRST NIGHT", sc.first_night), ("OTHER NIGHTS", sc.other_night)):
        ni = pg.p("night_icon")
        step = ni + pg.p(4)
        if order and len(order) * step > avail:  # zu viele Einträge: Icons verkleinern statt umbrechen
            step = avail / len(order)
            ni = step * 0.88
        cy = ry + row_h / 2
        _draw_spaced(pg.dr, pg.x0, cy + f_lab.getmetrics()[0] * 0.35, label, f_lab, pg.p("night_label") * 0.2, HEAD)
        x = pg.x0 + label_w
        for cid in order:
            px = round(ni)
            icon = (assets.night_token(cid, px) or _placeholder(px)) if cid in NIGHT_SPECIALS \
                else _char_icon(sc.by_id[cid], px)
            pg.paste(icon, x, cy - ni / 2)
            x += step
        ry += row_h + pg.p(2)


def _footer_height(pg):
    return pg.m(FRAME + 6) + pg.m(SZ["footer"]) * 2.6


def _footer(pg):
    f = assets.font("text", pg.m(SZ["footer"]))
    base = pg.H - pg.m(FRAME + 6) - pg.m(SZ["footer"]) * 1.1
    pg.dr.text((pg.x0, base), "© Steven Medway  ·  bloodontheclocktower.com", font=f, fill=GREY, anchor="ls")
    pg.dr.text((pg.x1, base), "* not the first night", font=f, fill=GREY, anchor="rs")


# ── Zusammenbau ──────────────────────────────────────────────────────────────

def _compose(sc, dpi, k, compact, theme, draw, extra=0):
    """Ein Durchlauf (messen oder zeichnen); extra = zusätzliche Seitenhöhe in px. Liefert die Page."""
    pg = Page(sc, dpi, k, compact, theme, draw, extra)
    if draw:  # Restplatz messen und auf die Abschnitte verteilen statt ihn an einer Stelle zu sammeln
        probe = _compose(sc, dpi, k, compact, theme, False, extra)
        heads = sum(1 for t in GRID_TEAMS if sc.teams.get(t)) + _has_extras(sc)
        pg.spread = min(pg.m(12), max(0.0, probe.slack) / (heads + 1))
    y = title.draw_title(pg.img, pg.m(TITLE_X), pg.W - pg.m(TITLE_X), pg.m(FRAME + 12), sc.name, sc.author,
                         pg.rec, pg.S, ornaments.paper_box(pg)) + pg.m(2)
    y = _characters(pg, sc, y)
    night_h = _night_height(pg)
    limit = pg.H - _footer_height(pg)
    extras_h = _extras_panel(pg, sc, 0, draw=False) if _has_extras(sc) else 0
    gap = pg.m(6) if extras_h else 0
    pg.slack = limit - (y + pg.p("section_gap") + extras_h + gap + night_h)
    if draw:  # Anhang direkt unter den Charakteren, Nachtreihenfolge unten über der Fußzeile verankert
        if extras_h:
            _extras_panel(pg, sc, y + pg.p("section_gap") + pg.spread, draw=True)
        _night_block(pg, sc, limit - night_h)
        _footer(pg)
        ornaments.frame(pg)
    return pg


def _best_fit(sc, dpi, theme):
    """Größte Skalierung, bei der alles auf A4 passt: (k, kompakt) oder None."""
    def fits(k, compact):
        return _compose(sc, dpi, k, compact, theme, False).slack >= 0

    best = None
    for compact in (False, True):
        if not fits(K_MIN, compact):
            continue
        lo, hi = K_MIN, K_MAX
        if fits(K_MAX, compact):
            lo = K_MAX
        else:
            for _ in range(SEARCH_STEPS):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if fits(mid, compact) else (lo, mid)
        if best is None or lo > best[0] + 0.03:
            best = (lo, compact)
        if not compact and lo >= 0.97:
            break
    return best


def render_sheet(sc, theme="green", dpi=200):
    """Rendert das Blatt als RGB-Bild (A4, bei Bedarf länger) oder None, wenn es über MAX_LENGTH × A4 bräuchte."""
    fit = _best_fit(sc, dpi, theme)
    if fit:
        return _compose(sc, dpi, *fit, theme, True).img
    probe = _compose(sc, dpi, LONG_K, False, theme, False)
    extra = -probe.slack + probe.m(4)
    if probe.H + extra > probe.H * MAX_LENGTH:
        return None
    return _compose(sc, dpi, LONG_K, False, theme, True, extra).img
