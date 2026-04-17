"""Standalone-Test für den Sternenhimmel-Hintergrund.

Style-Referenz: dunkler Tarot-/Mystic-Hintergrund (#1f2023) mit
goldenen + weißen Sternen-Punkten in Cluster-Verteilung. Keine Streaks.
Dichte am Bildrand höher als in der Mitte (Mitte bleibt frei für Text).

Erzeugt:
  test_output/starfield_preview.png            (nur Background)
  test_output/To_tell_the_truth_starfield.png  (mit Script darüber)
"""

import json
import logging
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

from logic.script_image import _generate_sync


logging.basicConfig(level=logging.WARNING)


SCRIPT_PATH = "test_scripts/To tell the truth.json"
SEED = 3
BG_COLOR = (0x1f, 0x20, 0x23)


def gold(brightness):
    return (brightness, int(brightness * 0.88), int(brightness * 0.55))


def white_star(b):
    return (b, b, b)


def edge_weight(x, y, W):
    """Höher am linken/rechten Rand, niedriger in der Mitte → Mitte bleibt
    optisch ruhig, damit der Text gut lesbar bleibt."""
    return abs(x - W / 2) / (W / 2)


def put_star(draw, x, y, size, color):
    if size == 1:
        draw.point((x, y), fill=color)
    else:
        draw.ellipse(
            [x - (size - 1), y - (size - 1), x + (size - 1), y + (size - 1)],
            fill=color,
        )


def render_starfield_bg(W, H, seed=SEED):
    rng = random.Random(seed)

    bg = Image.new("RGB", (W, H), BG_COLOR)

    # ── Nebula-Wolken (sehr subtil, hellblau-weiß, stark geblurt) ───────────
    nebula = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    nd = ImageDraw.Draw(nebula)

    # Cluster-Zentren wählen (am Rand bevorzugt) — werden für Nebula
    # UND für die Small-Star-Cluster wiederverwendet
    small_clusters = []
    n_small = 22
    for _ in range(n_small):
        for _ in range(20):
            cx = rng.uniform(0, W)
            cy = rng.uniform(0, H)
            if rng.random() < edge_weight(cx, cy, W) * 0.6 + 0.3:
                small_clusters.append((cx, cy))
                break

    for cx, cy in small_clusters:
        radius = rng.randint(50, 110)
        alpha = rng.randint(18, 32)
        nd.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=(230, 235, 250, alpha),
        )
    nebula = nebula.filter(ImageFilter.GaussianBlur(30))

    # ── Sternen-Layer ───────────────────────────────────────────────────────
    star_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(star_layer)

    # 1) Große Cluster (helle, größere Sterne, gauss-verteilt)
    n_large = 14
    for _ in range(n_large):
        for _ in range(30):
            cx = rng.uniform(0, W)
            cy = rng.uniform(0, H)
            if rng.random() < edge_weight(cx, cy, W) ** 1.3:
                break
        n_stars = rng.randint(6, 14)
        spread = rng.uniform(50, 120)
        for _ in range(n_stars):
            x = cx + rng.gauss(0, spread)
            y = cy + rng.gauss(0, spread)
            if not (0 <= x < W and 0 <= y < H):
                continue
            r = rng.random()
            if r < 0.5:
                size = 2
            elif r < 0.85:
                size = 3
            else:
                size = 2
            if rng.random() < 0.7:
                color = gold(rng.randint(210, 250))
            else:
                color = white_star(rng.randint(220, 250))
            put_star(sd, x, y, size, color)

    # 2) Kleine Cluster (mehr Sterne, kleiner, weniger hell)
    for cx, cy in small_clusters:
        n_stars = rng.randint(12, 30)
        spread = rng.uniform(40, 80)
        for _ in range(n_stars):
            x = cx + rng.gauss(0, spread)
            y = cy + rng.gauss(0, spread)
            if not (0 <= x < W and 0 <= y < H):
                continue
            size = 1 if rng.random() < 0.80 else 2
            if rng.random() < 0.7:
                color = gold(rng.randint(180, 230))
            else:
                color = white_star(rng.randint(190, 230))
            put_star(sd, x, y, size, color)

    # 3) Über das gesamte Bild verstreute Einzel-Sterne
    for _ in range(350):
        x = rng.randint(0, W - 1)
        y = rng.randint(0, H - 1)
        if rng.random() > edge_weight(x, y, W) * 0.5 + 0.4:
            continue
        r = rng.random()
        if r < 0.85:
            size = 1
        elif r < 0.97:
            size = 2
        else:
            size = 3
        if rng.random() < 0.7:
            color = gold(rng.randint(160, 220))
        else:
            color = white_star(rng.randint(170, 220))
        put_star(sd, x, y, size, color)

    bg_rgba = bg.convert("RGBA")
    bg_rgba = Image.alpha_composite(bg_rgba, nebula)
    bg_rgba = Image.alpha_composite(bg_rgba, star_layer)
    return bg_rgba


def main():
    # Script laden
    with open(SCRIPT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    meta_entry = (
        data[0]
        if isinstance(data[0], dict) and data[0].get("id") == "_meta"
        else {}
    )
    char_ids = [
        i if isinstance(i, str) else i["id"]
        for i in data
        if isinstance(i, str)
        or (isinstance(i, dict) and i.get("id") != "_meta")
    ]

    # Script-Bild (transparent) generieren
    buf = _generate_sync(
        meta_entry.get("name", ""),
        meta_entry.get("author", ""),
        char_ids,
        version="",
        meta=meta_entry,
        content=data,
        show_fabled=False,
        transparent=True,
    )
    script = Image.open(buf).convert("RGBA")
    W, H = script.size
    print(f"Script-Größe: {W}x{H}")

    # Sternenhimmel rendern
    bg_rgba = render_starfield_bg(W, H)

    os.makedirs("test_output", exist_ok=True)

    # Nur Background (klein, gut zum Beurteilen)
    preview_path = "test_output/starfield_preview.png"
    bg_rgba.convert("RGB").save(preview_path)
    print(f"Preview: {preview_path}  ({os.path.getsize(preview_path) // 1024} KB)")

    # Mit Script darüber (groß, nur Final-Check)
    composed = bg_rgba.copy()
    composed.paste(script, (0, 0), script)
    final_path = "test_output/To_tell_the_truth_starfield.png"
    composed.convert("RGB").save(final_path)
    print(f"Final:   {final_path}  ({os.path.getsize(final_path) // 1024} KB)")
    print("Done")


if __name__ == "__main__":
    main()
