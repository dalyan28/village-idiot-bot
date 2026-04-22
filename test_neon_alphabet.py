"""Rendert das komplette A-Z Alphabet in Benguiat Bold (Neon-Titel-Font).
Zeigt jeden Buchstaben einzeln groß + alle nebeneinander in einer Zeile,
damit man Serif-Profile links/rechts vergleichen kann."""

import os
import string

from PIL import Image, ImageDraw

from logic.script_image import _font, _F_TITLE_GOLD, SZ_TITLE

OUT_DIR = "test_output/neon"
SIZE = int(SZ_TITLE * 1.3)
FILL = (175, 30, 75)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    f = _font(_F_TITLE_GOLD, SIZE)
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    # Einzelne Tiles pro Buchstabe, mit visual baseline indicator
    letters = list(string.ascii_uppercase)
    per_row = 9  # A-I / J-R / S-Z (3 Zeilen)
    tiles = []
    for ch in letters:
        bb = dummy.textbbox((0, 0), ch, font=f)
        w = bb[2] - bb[0] + 20
        h = bb[3] - bb[1] + 20
        tile = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        td = ImageDraw.Draw(tile)
        td.text((10 - bb[0], 10 - bb[1]), ch, fill=FILL, font=f)
        # Baseline-Hilfslinie
        td.line([(0, h - 10), (w, h - 10)], fill=(200, 200, 200, 255), width=1)
        tiles.append((ch, tile))

    # Grid 3x9 (A-I / J-R / S-Z)
    col_w = max(t.width for _, t in tiles) + 4
    row_h = max(t.height for _, t in tiles) + 4
    rows = (len(letters) + per_row - 1) // per_row
    grid_w = col_w * per_row
    grid_h = row_h * rows
    grid = Image.new("RGBA", (grid_w, grid_h), (255, 255, 255, 255))
    for i, (ch, t) in enumerate(tiles):
        row = i // per_row
        col = i % per_row
        x = col * col_w + (col_w - t.width) // 2
        y = row * row_h + (row_h - t.height) // 2
        grid.paste(t, (x, y), t)

    path = f"{OUT_DIR}/_alphabet_benguiat.png"
    grid.convert("RGB").save(path)
    print(f"Alphabet: {path} ({os.path.getsize(path) // 1024} KB, {grid_w}x{grid_h})")

    # Bonus: Buchstaben nebeneinander in zwei Zeilen (Kerning-Blick, < 2000px)
    for idx, chunk in enumerate([letters[:13], letters[13:]]):
        line = " ".join(chunk)
        bb = dummy.textbbox((0, 0), line, font=f)
        lw = bb[2] - bb[0] + 40
        lh = bb[3] - bb[1] + 40
        row_img = Image.new("RGBA", (lw, lh), (255, 255, 255, 255))
        rd = ImageDraw.Draw(row_img)
        rd.text((20 - bb[0], 20 - bb[1]), line, fill=FILL, font=f)
        path2 = f"{OUT_DIR}/_alphabet_row_{idx + 1}.png"
        row_img.convert("RGB").save(path2)
        print(f"Alphabet row {idx + 1}: {path2} ({os.path.getsize(path2) // 1024} KB, {lw}x{lh})")


if __name__ == "__main__":
    main()
