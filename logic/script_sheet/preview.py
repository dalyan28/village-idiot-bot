"""Vorschau: rendert Skript-JSONs als Skript-Blatt nach test_output/script_sheet/ (gitignored).

    python -m logic.script_sheet.preview test_scripts/Boozling.json [--theme red] [--look fancy]
                                         [--pack PFAD | --no-pack]
"""

import argparse
import json
import os
import time

from . import assets
from .model import from_script_json
from .sheet import render_sheet
from .style import DEFAULT_LOOK, DPI, LOOKS, THEMES

OUT = os.path.join("test_output", "script_sheet")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--theme", default="green", choices=sorted(THEMES))
    ap.add_argument("--look", default=DEFAULT_LOOK, choices=sorted(LOOKS))
    ap.add_argument("--pack", help="anderes Asset-Paket")
    ap.add_argument("--no-pack", action="store_true", help="ohne Asset-Paket rendern (Stand ohne Lizenz-Grafiken)")
    args = ap.parse_args()
    if args.no_pack or args.pack:
        assets.set_pack_dir(args.pack or os.path.join(OUT, "_kein_paket"))
    os.makedirs(OUT, exist_ok=True)
    for path in args.files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):  # Antwort der botcscripts-API: Skript-JSON unter „content“
            sc = from_script_json(data["content"], data.get("name"), data.get("author"))
        else:
            sc = from_script_json(data)
        t0 = time.perf_counter()
        img = render_sheet(sc, theme=args.theme, dpi=DPI, look=args.look)
        ms = (time.perf_counter() - t0) * 1000
        if img is None:
            print(f"{sc.name}: zu groß, kein Bild ({ms:.0f} ms)")
            continue
        out = os.path.join(OUT, f"{os.path.splitext(os.path.basename(path))[0]}_{args.look}_{args.theme}.jpg")
        img.save(out, quality=90)
        print(f"{sc.name}: {img.width}x{img.height}, {ms:.0f} ms -> {out}")


if __name__ == "__main__":
    main()
