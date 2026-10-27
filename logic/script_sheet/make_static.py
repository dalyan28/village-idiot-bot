"""Erzeugt die eigenen (frei verwendbaren) Grafiken des Skript-Blatts nach static/script_sheet/:
- washes/wash_XX.png: Aquarell-Kleckse als Masken (dunkel = viel Pigment)
- night/<name>.png: Sondermarken der Nachtreihenfolge (Abenddämmerung, Minion-Info, Demon-Info, Morgengrauen)

Ergebnis ist deterministisch (feste Zufallswerte) und liegt im Repo; nur nach Änderungen neu erzeugen:
    python -m logic.script_sheet.make_static
"""

import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .assets import FONT_DIR, OWN_DIR

WASH_COUNT = 24
WASH_SIZE = 512
TOKEN_SIZE = 400


# ── Aquarell-Kleckse ─────────────────────────────────────────────────────────

def _noise(rnd, size, cells):
    small = Image.fromarray(np.uint8([[rnd.randint(0, 255) for _ in range(cells)] for _ in range(cells)]))
    return np.asarray(small.resize((size, size), Image.Resampling.BICUBIC), dtype=np.float32) / 255


def _fractal(rnd, size, base, octaves=4):
    out, amp, total = np.zeros((size, size), np.float32), 1.0, 0.0
    for o in range(octaves):
        out += _noise(rnd, size, base * 2 ** o) * amp
        total += amp
        amp *= 0.5
    return out / total


def _blur(a, r):
    img = Image.fromarray(np.uint8(np.clip(a, 0, 1) * 255))
    return np.asarray(img.filter(ImageFilter.GaussianBlur(r)), dtype=np.float32) / 255


def wash(seed):
    """Grundform aus verzerrtem Rauschen, ungleichmäßige Pigmentdichte, dunklerer Rand (Pigment sammelt sich
    beim Trocknen), Körnung, gelegentlich Ausblühen, weich verlaufende Ränder (nass-in-nass) und Spritzer."""
    rnd = random.Random(seed)
    s = WASH_SIZE
    yy, xx = np.mgrid[0:s, 0:s].astype(np.float32) / s
    ang = rnd.uniform(0, np.pi)
    sx, sy = rnd.uniform(0.28, 0.42), rnd.uniform(0.18, 0.32)
    dx, dy = xx - 0.5, yy - 0.5
    warp = (_fractal(rnd, s, 3) - 0.5) * 0.35
    u = (dx * np.cos(ang) + dy * np.sin(ang)) + warp
    v = (-dx * np.sin(ang) + dy * np.cos(ang)) + warp * 0.7
    field = 1 - np.sqrt((u / sx) ** 2 + (v / sy) ** 2) \
        + (_fractal(rnd, s, rnd.choice([4, 6, 8]), 5) - 0.5) * rnd.uniform(0.5, 0.85)
    shape = (field > rnd.uniform(0.0, 0.12)).astype(np.float32)
    bloom = np.zeros_like(shape)
    if rnd.random() < 0.3:
        bx, by, br = rnd.uniform(0.35, 0.65), rnd.uniform(0.35, 0.65), rnd.uniform(0.07, 0.13)
        bloom = ((np.sqrt((xx - bx) ** 2 + (yy - by) ** 2) + (_fractal(rnd, s, 6) - 0.5) * 0.08) < br).astype(np.float32)
    wet = rnd.random() < 0.4
    shape = _blur(shape, rnd.uniform(5, 9) if wet else 1.2)
    density = 0.35 + 0.45 * _fractal(rnd, s, rnd.choice([2, 3, 5]))
    edge = np.clip(shape - _blur(shape, 6), 0, 1) * (rnd.uniform(0.3, 0.8) if wet else rnd.uniform(1.2, 2.4))
    grain = (_noise(rnd, s, s // 3) - 0.5) * 0.12
    pig = np.clip(density + edge + grain, 0, 1) * shape
    if bloom.any():
        bl = _blur(bloom, 2)
        pig = pig * (1 - 0.3 * bl) + np.clip(bl - _blur(bl, 4), 0, 1) * 0.35 * shape
    for _ in range(rnd.randint(0, 6)):  # Spritzer
        a, r = rnd.uniform(0, 2 * np.pi), rnd.uniform(0.33, 0.47)
        cx, cy, rr = 0.5 + np.cos(a) * r, 0.5 + np.sin(a) * r * 0.8, rnd.uniform(0.006, 0.02)
        dot = (np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) < rr).astype(np.float32)
        pig = np.maximum(pig, _blur(dot, 0.8) * 0.7)
    img = Image.fromarray(np.uint8(np.clip(pig, 0, 1) * 255))
    return img.crop(img.getbbox())


# ── Nachtmarken ──────────────────────────────────────────────────────────────

DARK, RIM, EVIL, LIGHT = (28, 30, 38), (205, 205, 210), (150, 24, 24), (245, 240, 228)
GOLD, GOLD_DARK = (236, 170, 40), (190, 110, 20)
SS = 4  # gezeichnet in vierfacher Größe, dann verkleinert


def _disk(fill, rim):
    s = TOKEN_SIZE * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 10 * SS
    d.ellipse((pad, pad, s - pad, s - pad), fill=rim)
    d.ellipse((pad + 14 * SS, pad + 14 * SS, s - pad - 14 * SS, s - pad - 14 * SS), fill=fill)
    return img, d, s


def _tokens():
    img, d, s = _disk(DARK, RIM)  # Abenddämmerung: Mondsichel
    c, r = s / 2, s * 0.26
    d.ellipse((c - r, c - r, c + r, c + r), fill=LIGHT)
    off = r * 0.55
    d.ellipse((c - r + off, c - r - off * 0.45, c + r + off, c + r - off * 0.45), fill=DARK)
    yield "dusk", img
    for ch, name in (("M", "minioninfo"), ("D", "demoninfo")):
        img, d, s = _disk(DARK, EVIL)
        f = ImageFont.truetype(os.path.join(FONT_DIR, "Dumbledor.ttf"), int(s * 0.5))
        d.text((s / 2, s / 2 + s * 0.02), ch, font=f, fill=LIGHT, anchor="mm")
        yield name, img
    img, d, s = _disk(GOLD, GOLD_DARK)  # Morgengrauen: Sonne
    c = s / 2
    for k in range(12):
        a, r1, r2, w = k * math.pi / 6, s * 0.2, s * 0.33, 0.13
        d.polygon([(c + r1 * math.cos(a - w), c + r1 * math.sin(a - w)), (c + r2 * math.cos(a), c + r2 * math.sin(a)),
                   (c + r1 * math.cos(a + w), c + r1 * math.sin(a + w))], fill=LIGHT)
    r = s * 0.17
    d.ellipse((c - r, c - r, c + r, c + r), fill=LIGHT)
    yield "dawn", img


def main():
    os.makedirs(os.path.join(OWN_DIR, "washes"), exist_ok=True)
    os.makedirs(os.path.join(OWN_DIR, "night"), exist_ok=True)
    for i in range(WASH_COUNT):
        wash(1000 + i).save(os.path.join(OWN_DIR, "washes", f"wash_{i:02d}.png"), optimize=True)
    for name, img in _tokens():
        img.resize((TOKEN_SIZE, TOKEN_SIZE), Image.Resampling.LANCZOS).save(
            os.path.join(OWN_DIR, "night", name + ".png"), optimize=True)
    print(f"{WASH_COUNT} Kleckse und 4 Nachtmarken -> {OWN_DIR}")


if __name__ == "__main__":
    main()
