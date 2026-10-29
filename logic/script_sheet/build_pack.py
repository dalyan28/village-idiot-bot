"""Baut das Asset-Paket des Skript-Blatts aus den lizenzierten Originalen.

Das Paket enthält Ableitungen gekaufter bzw. nur zum Test freigegebener Grafiken und darf NICHT ins Repo
(auch nicht als Release-Datei eines öffentlichen Repos). Es wird lokal gebaut und auf das Volume gebracht.

Erwartete Quellen (gitignored, Standard: private_assets/):
    etsy/            Etsy-Sets („Witchcraft Graphics“, „Mystical Mushroom“, „Mystic Ockult Wiccan Symbole“,
                     „Clippign Masks“) in der Ordnerstruktur wie gekauft
    scribe/pattern_tile.png   nahtlose Damast-Kachel (aus den scribe-PDFs von Derek Y.; nur Testfreigabe!)
    tpi_night/       dusk/minioninfo/demoninfo/dawn als .webp oder .png (aus dem TPI-Script-Tool)

Aufruf aus dem Repo-Root:
    python -m logic.script_sheet.build_pack [--sources private_assets] [--out data/script_sheet_assets]
"""

import argparse
import json
import os

from PIL import Image

from . import assets

PACK_VERSION = 2  # 2: weitere Trenner (29.10.2026)
MAX_SIDE = 900  # Ornamente werden verkleinert gespeichert (genügt für 200 dpi)

_MYSTIC = "Mystic Ockult Wiccan Symbole"
SOURCES = {  # Set-Kürzel → Pfad im Etsy-Ordner ({n} = Dateiname ohne Endung)
    "w": "Witchcraft Graphics/WitchCraftGraphicsPNGs (1)/PNGs/WitchCraft Graphics-{n}.png",
    "mu": "Mystical Mushroom/PNG/{n}.png",
    "m2": f"{_MYSTIC}/2/PNG/{{n}}.png",
    "m6": f"{_MYSTIC}/5-7/6/PNG/{{n}}.png",
    "m7": f"{_MYSTIC}/5-7/7/PNG/{{n}}.png",
    "m8": f"{_MYSTIC}/8/PNG/{{n}}.png",
    "m9": f"{_MYSTIC}/9/PNG/{{n}}.png",
    "mp": f"{_MYSTIC}/PNG/{{n}}.png",
}
WASH_MASK = "Clippign Masks/AWhimAdv-DeckThePalms-PhotoMasks{i}.png"


def _alpha(path):
    a = Image.open(path).convert("RGBA").getchannel("A")
    a = a.crop(a.getbbox())
    a.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return a


def build(sources, out):
    etsy = os.path.join(sources, "etsy")
    os.makedirs(os.path.join(out, "ornaments"), exist_ok=True)
    os.makedirs(os.path.join(out, "washes"), exist_ok=True)
    os.makedirs(os.path.join(out, "night"), exist_ok=True)
    missing, count = [], 0
    for key in assets.ALL_ORNAMENTS:
        prefix, n = key.split(":")
        src = os.path.join(etsy, SOURCES[prefix].format(n=n))
        if not os.path.exists(src):
            missing.append(key)
            continue
        _alpha(src).save(os.path.join(out, "ornaments", key.replace(":", "_") + ".png"), optimize=True)
        count += 1
    for i in range(1, assets.PACK_WASH_COUNT + 1):
        src = os.path.join(etsy, WASH_MASK.format(i=i))
        if os.path.exists(src):
            _alpha(src).save(os.path.join(out, "washes", f"mask_{i}.png"), optimize=True)
            count += 1
        else:
            missing.append(f"wash {i}")
    tile = os.path.join(sources, "scribe", "pattern_tile.png")
    if os.path.exists(tile):
        Image.open(tile).convert("L").save(os.path.join(out, "pattern_tile.png"), optimize=True)
        count += 1
    else:
        missing.append("pattern_tile")
    for name in assets.NIGHT_TOKENS:
        src = next((os.path.join(sources, "tpi_night", name + ext) for ext in (".webp", ".png")
                    if os.path.exists(os.path.join(sources, "tpi_night", name + ext))), None)
        if src:
            Image.open(src).convert("RGBA").save(os.path.join(out, "night", name + ".png"), optimize=True)
            count += 1
        else:
            missing.append(f"night {name}")
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"version": PACK_VERSION, "files": count, "missing": missing}, f, indent=1)
    return count, missing


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", default="private_assets")
    ap.add_argument("--out", default=assets.PACK_DIR)
    args = ap.parse_args()
    count, missing = build(args.sources, args.out)
    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(args.out) for f in fs)
    print(f"{count} Dateien, {size / 1e6:.1f} MB -> {args.out}")
    if missing:
        print("Fehlt:", ", ".join(missing))


if __name__ == "__main__":
    main()
