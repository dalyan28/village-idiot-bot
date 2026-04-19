"""Gallery-Test: rendert den Neon-Titel für verschiedene Titel-Längen und
stapelt die Ergebnisse vertikal auf Sternenhimmel-BG, damit man alle
Varianten auf einen Blick sieht."""

import os

from PIL import Image

from logic.script_image import (
    _render_neon_title,
    _render_sticker_author,
    _apply_finishing_filter,
)
from logic.starfield_bg import render_starfield_bg


TITLES = [
    ("One", "One"),
    ("Stranger Things", "Duffer Brothers"),
    ("Ich gehe morgen shoppen", "Eiker"),
    ("Trouble Brewing", "TPI"),
    ("Sects and Violets", "TPI"),
    ("To tell the truth", "Eiker"),
    ("Bad Moon Rising", "TPI"),
    ("Ides of March and April", "LongerAuthor"),
    ("The final gambit of destiny", "TestAuthor"),
    ("Midnight at the cathedral of lies", "Author"),
]

TILE_W = 1780


def main():
    os.makedirs("test_output", exist_ok=True)

    tiles = []
    for title, author in TITLES:
        title_img = _render_neon_title(title)
        author_img = _render_sticker_author(f"by {author}")
        overlap = 20 * 2
        gap_top = 40
        gap_bottom = 60
        H = gap_top + title_img.height + (author_img.height - overlap) + gap_bottom
        bg = render_starfield_bg(TILE_W, H).convert("RGBA")
        tx = (TILE_W - title_img.width) // 2
        ty = gap_top
        bg.paste(title_img, (tx, ty), title_img)
        ax = (TILE_W - author_img.width) // 2
        ay = ty + title_img.height - overlap
        bg.paste(author_img, (ax, ay), author_img)
        tiles.append((title, bg))

    # Stack vertically
    sep = 6
    total_h = sum(t.height for _, t in tiles) + sep * (len(tiles) - 1)
    gallery = Image.new("RGBA", (TILE_W, total_h), (0, 0, 0, 255))
    y = 0
    for _, t in tiles:
        gallery.paste(t, (0, y))
        y += t.height + sep

    gallery = _apply_finishing_filter(gallery)
    path = "test_output/_neon_gallery.png"
    gallery.convert("RGB").save(path)
    print(f"Gallery: {path} ({os.path.getsize(path) // 1024} KB)")
    for title, t in tiles:
        print(f"  {title!r}: {t.width}x{t.height}")


if __name__ == "__main__":
    main()
