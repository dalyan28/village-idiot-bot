"""Standalone-Test für den Sternenhimmel-Hintergrund.

Nutzt `logic.starfield_bg.render_starfield_bg` als Quelle der Wahrheit.

Erzeugt:
  test_output/starfield_1780x1900.png          (Standalone BG, unter 2000px)
  test_output/starfield_crop.png               (700x700 native Crop)
  test_output/starfield_overview.png           (downscaled Übersicht)
  test_output/To_tell_the_truth_starfield.png  (mit Script darüber)
"""

import json
import logging
import os

from PIL import Image

from logic.script_image import (
    DESIGN_STARFIELD,
    DESIGN_STARFIELD_NEON,
    _generate_sync,
)
from logic.starfield_bg import render_starfield_bg


logging.basicConfig(level=logging.WARNING)


SCRIPT_PATH = "test_scripts/To tell the truth.json"


def main():
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

    bg_rgba = render_starfield_bg(W, H)

    os.makedirs("test_output", exist_ok=True)

    alt_W, alt_H = 1780, 1900
    alt_bg = render_starfield_bg(alt_W, alt_H)
    alt_path = "test_output/starfield_1780x1900.png"
    alt_bg.convert("RGB").save(alt_path)
    print(f"Preview: {alt_path}  ({os.path.getsize(alt_path) // 1024} KB)")

    crop_size = 700
    crop = bg_rgba.crop((0, 0, crop_size, crop_size))
    crop_path = "test_output/starfield_crop.png"
    crop.convert("RGB").save(crop_path)
    print(f"Crop:    {crop_path}    ({os.path.getsize(crop_path) // 1024} KB)")

    overview_w = 600
    overview_h = int(H * (overview_w / W))
    overview = bg_rgba.resize((overview_w, overview_h), Image.LANCZOS)
    overview_path = "test_output/starfield_overview.png"
    overview.convert("RGB").save(overview_path)
    print(f"Overview:{overview_path} ({os.path.getsize(overview_path) // 1024} KB)")

    def render(design, filename, **kwargs):
        buf = _generate_sync(
            meta_entry.get("name", ""),
            meta_entry.get("author", ""),
            char_ids,
            version="",
            meta=meta_entry,
            content=data,
            show_fabled=False,
            transparent=False,
            design=design,
            **kwargs,
        )
        path = f"test_output/{filename}"
        Image.open(buf).convert("RGB").save(path)
        print(f"{filename}  ({os.path.getsize(path) // 1024} KB)")

    # Gold-Variante (stabil, User-Favorit)
    render(DESIGN_STARFIELD, "To_tell_the_truth_starfield.png")
    # Neon-Variante (Stranger-Things-Experiment)
    render(DESIGN_STARFIELD_NEON, "To_tell_the_truth_starfield_neon.png")
    # White-Icon Vergleich
    render(DESIGN_STARFIELD, "To_tell_the_truth_starfield_white.png",
           white_icons=True)
    print("Done")


if __name__ == "__main__":
    main()
