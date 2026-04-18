"""Starfield-Hintergrund-Renderer für Script-Bilder.

Erzeugt einen dunklen Sternenhimmel-Hintergrund mit Papier-Textur-Grain,
organischen Cluster-Regionen und Power-law-Größenverteilung der Sterne.
"""

import os
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter


_IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "images"
)
PAPER_TEXTURE_PATH = os.path.join(
    _IMAGES_DIR, "paper textures", "Texturelabs_Paper_331S.jpg"
)

STARFIELD_BG_COLOR = (0x1e, 0x1f, 0x22)
STARFIELD_SEED_DEFAULT = 3


def _gold(brightness):
    return (brightness, int(brightness * 0.88), int(brightness * 0.55))


def _white_star(b):
    return (b, b, b)


def _pick_star_color(rng, gold_chance=0.78, b_lo=180, b_hi=240):
    b = rng.randint(b_lo, b_hi)
    if rng.random() < gold_chance:
        return _gold(b)
    return _white_star(b)


def _draw_disc(draw, x, y, radius, color):
    r = max(0.5, radius)
    draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def hard_light_blend(base, blend):
    """Photoshop-style Hard Light per PIL (kein numpy).

    Formel pro Kanal:
      blend < 128:  2 * base * blend / 255
      blend ≥ 128:  255 − 2*(255−base)*(255−blend)/255
    blend's Alpha-Channel gewichtet die Mischung mit base.
    """
    base_rgb = base.convert("RGB")
    blend_rgb = blend.convert("RGB")
    blend_alpha = blend.split()[3]

    mult = ImageChops.multiply(base_rgb, blend_rgb).point(
        lambda v: min(255, v * 2)
    )
    inv_base = ImageChops.invert(base_rgb)
    inv_blend = ImageChops.invert(blend_rgb)
    screen = ImageChops.invert(
        ImageChops.multiply(inv_base, inv_blend).point(
            lambda v: min(255, v * 2)
        )
    )
    gray = blend_rgb.convert("L")
    mask = gray.point(lambda v: 255 if v >= 128 else 0)
    hl = Image.composite(screen, mult, mask)
    result = Image.composite(hl, base_rgb, blend_alpha).convert("RGBA")
    result.putalpha(base.split()[3])
    return result


def render_starfield_bg(W, H, seed=STARFIELD_SEED_DEFAULT):
    """Rendert Sternenhimmel-BG mit Papier-Grain, Cluster + Power-law-Dust."""
    rng = random.Random(seed)

    # Hintergrund: dunkle Basis + subtile Papier-Luminanz-Variation (Grain)
    paper = (
        Image.open(PAPER_TEXTURE_PATH)
        .convert("L")
        .resize((W, H), Image.LANCZOS)
    )

    def paper_offset(target):
        return paper.point(lambda v: target + int(((v - 150) / 105) * 12))
    bg = Image.merge(
        "RGB",
        (paper_offset(STARFIELD_BG_COLOR[0]),
         paper_offset(STARFIELD_BG_COLOR[1]),
         paper_offset(STARFIELD_BG_COLOR[2]))
    ).convert("RGBA")

    unit = min(W, H) / 1900
    area = W * H
    area_ref = 1780 * 3048

    R_FINE = max(1.0, 1.0 * unit)
    R_BIG_MIN = max(2.2, 2.2 * unit)
    R_BIG_MAX = max(7.0, 7.0 * unit)

    def make_region(rng_seed_off, low_scale, blur_mult, threshold, contrast,
                    floor_val=0):
        nw, nh = max(8, W // low_scale), max(8, H // low_scale)
        local = random.Random(seed + rng_seed_off)
        src = Image.new("L", (nw, nh))
        px = src.load()
        for y in range(nh):
            for x in range(nw):
                px[x, y] = local.randint(0, 255)
        src = src.resize((W, H), Image.BILINEAR)
        src = src.filter(ImageFilter.GaussianBlur(radius=unit * blur_mult))
        src = src.point(
            lambda v: max(floor_val, min(255, int((v - threshold) * contrast)))
        )
        return src

    small_region = make_region(1, 18, 50, 128, 2.4)
    small_px = small_region.load()
    big_region = make_region(7, 20, 48, 130, 2.0)
    big_px = big_region.load()
    gaps = make_region(13, 35, 18, 110, 2.3)
    gap_px = gaps.load()

    def sample_pix(arr, x, y):
        return arr[min(W - 1, max(0, int(x))),
                   min(H - 1, max(0, int(y)))] / 255

    def small_density(x, y):
        base = sample_pix(small_px, x, y)
        gap = sample_pix(gap_px, x, y)
        return max(0, base - gap * 0.85)

    # Layer A: Power-law Dust — viele winzige Punkte mit variabler Alpha
    fine_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fine_layer)
    fine_px = fine_layer.load()

    n_dust = int(48000 * (area / area_ref))
    for _ in range(n_dust):
        x = rng.randint(0, W - 1)
        y = rng.randint(0, H - 1)
        d = sample_pix(small_px, x, y)
        if rng.random() > d * 0.55 + 0.30:
            continue
        roll = rng.random()
        if roll < 0.78:
            a = rng.randint(35, 130)
            color = _pick_star_color(rng, 0.78, 150, 220)
            fine_px[x, y] = (color[0], color[1], color[2], a)
        elif roll < 0.93:
            a = rng.randint(150, 225)
            color = _pick_star_color(rng, 0.80, 185, 235)
            fine_px[x, y] = (color[0], color[1], color[2], a)
        elif roll < 0.985:
            a = rng.randint(170, 230)
            color = _pick_star_color(rng, 0.82, 200, 240)
            _draw_disc(fd, x, y, 0.9, (color[0], color[1], color[2], a))
        else:
            a = rng.randint(200, 245)
            color = _pick_star_color(rng, 0.86, 215, 250)
            _draw_disc(fd, x, y, 1.4, (color[0], color[1], color[2], a))

    # Layer B: Cluster-Sterne (2x supersampling für saubere Anti-Aliasing)
    SS = 2
    cluster_ss = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    cd = ImageDraw.Draw(cluster_ss)

    n_cluster_total = int(2200 * (area / area_ref))
    placed = 0
    attempts = 0
    while placed < n_cluster_total and attempts < n_cluster_total * 10:
        attempts += 1
        x = rng.randint(0, W - 1)
        y = rng.randint(0, H - 1)
        d = small_density(x, y)
        if rng.random() > d * 1.3:
            continue
        r = R_FINE * rng.uniform(1.0, 1.7)
        color = _pick_star_color(rng, 0.78, 190, 240)
        a = rng.randint(190, 240)
        _draw_disc(cd, x * SS, y * SS, r * SS,
                   (color[0], color[1], color[2], a))
        placed += 1
    cluster_layer = cluster_ss.resize((W, H), Image.LANCZOS)

    # Layer C: Große Sterne — solide Punkte, folgen big_region
    big_layer_ss = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    bl = ImageDraw.Draw(big_layer_ss)
    n_big = int(220 * (area / area_ref))
    placed = 0
    attempts = 0
    while placed < n_big and attempts < n_big * 12:
        attempts += 1
        x = rng.randint(int(unit * 5), W - int(unit * 5) - 1)
        y = rng.randint(int(unit * 5), H - int(unit * 5) - 1)
        place_prob = sample_pix(big_px, x, y) * 0.95 + 0.04
        if rng.random() > place_prob:
            continue
        t = rng.random()
        if t < 0.55:
            r = rng.uniform(R_BIG_MIN, R_BIG_MIN * 1.6)
        elif t < 0.90:
            r = rng.uniform(R_BIG_MIN * 1.6, R_BIG_MAX * 0.75)
        else:
            r = rng.uniform(R_BIG_MAX * 0.75, R_BIG_MAX)
        color = _pick_star_color(rng, 0.85, 225, 250)
        _draw_disc(bl, x * SS, y * SS, r * SS, color + (255,))
        placed += 1
    big_layer = big_layer_ss.resize((W, H), Image.LANCZOS)

    # Compose: Nebel emergent aus Grain + Dust-Dichte, kein separater Layer
    canvas = bg
    canvas = Image.alpha_composite(canvas, fine_layer)
    canvas = Image.alpha_composite(canvas, cluster_layer)
    canvas = Image.alpha_composite(canvas, big_layer)
    return canvas
