"""Lokaler Test: Lädt Icons von TPI herunter und generiert ein Script-Bild.

Nutzung:
    python test_generate_image.py

Beim ersten Lauf werden characters.json + Icons nach data/ heruntergeladen.
Danach werden vorhandene Icons wiederverwendet (--force-icons für Neuladen).
Erzeugt: test_script_output.png
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from logic.script_cache import _update_characters_sync, load_characters
from logic.script_image import _generate_sync

# Beispiel-Script: Trouble Brewing Charaktere
TEST_CHARS = [
    "washerwoman", "librarian", "investigator", "chef",
    "empath", "fortuneteller", "undertaker", "monk",
    "ravenkeeper", "virgin", "slayer", "soldier",
    "mayor", "butler", "drunk", "recluse",
    "saint", "poisoner", "spy", "scarletwoman",
    "baron", "imp",
]

TEST_SCRIPT_NAME = "Trouble Brewing"
TEST_AUTHOR = "Test Author"


def main():
    force = "--force-icons" in sys.argv

    # 1. Daten herunterladen (Icons + characters.json)
    print("Lade Charakterdaten von TPI GitHub...")
    result = _update_characters_sync(force_icons=force)
    print(f"  Charaktere: {result['characters_count']}")
    print(f"  Jinxes: {result['jinxes_count']}")
    print(f"  Neue Icons: {result['new_icons']}")
    print(f"  Übersprungen: {result['skipped_icons']}")
    if result["errors"]:
        print(f"  Fehler: {result['errors']}")

    # 2. Bild generieren
    print(f"\nGeneriere Script-Bild für '{TEST_SCRIPT_NAME}'...")
    buf = _generate_sync(TEST_SCRIPT_NAME, TEST_AUTHOR, TEST_CHARS)

    import os
    os.makedirs("test_output", exist_ok=True)
    out_path = "test_output/test_script_output.png"
    with open(out_path, "wb") as f:
        f.write(buf.read())
    print(f"Fertig: {out_path}")


if __name__ == "__main__":
    main()
