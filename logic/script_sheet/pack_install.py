"""Asset-Paket aus einer ZIP-Datei aufs Volume bringen (Dalyan, 27.10.2026).

Das Paket enthält lizenzierte Grafiken und darf nicht ins (öffentliche) Repo. Deshalb lädt Dalyan die ZIP über
einen Befehl im Bot hoch (commands/script_sheet_pack.py), und der Bot entpackt sie hier nach
`assets.PACK_DIR`. Erst wird alles in einen Nachbarordner entpackt und geprüft, dann wird getauscht: Ist die
Datei kaputt, bleibt das alte Paket unverändert.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import zipfile

from . import assets

MAX_ZIP_BYTES = 25 * 1024 * 1024
MAX_UNPACKED_BYTES = 100 * 1024 * 1024  # Schutz gegen ZIP-Bomben
MAX_FILES = 1000
ALLOWED_SUFFIXES = (".png", ".json")


class PackError(ValueError):
    """ZIP ist kein brauchbares Asset-Paket (deutsche Meldung)."""


def _members(zf: zipfile.ZipFile) -> tuple[list[zipfile.ZipInfo], str]:
    """Dateien der ZIP und ein gemeinsamer Oberordner, falls die ZIP den Ordner selbst enthält."""
    files = [i for i in zf.infolist() if not i.is_dir()]
    names = [i.filename for i in files]
    if "manifest.json" in names:
        return files, ""
    prefixes = {n.split("/", 1)[0] for n in names}
    if len(prefixes) == 1 and f"{next(iter(prefixes))}/manifest.json" in names:
        return files, next(iter(prefixes)) + "/"
    raise PackError("In der ZIP fehlt manifest.json. Ist das wirklich das Asset-Paket aus build_pack?")


def install_pack(raw: bytes, target: str | None = None) -> dict:
    """Prüft und installiert das Paket. Gibt das Manifest zurück (mit „installed_files“)."""
    target = target or assets.PACK_DIR
    if len(raw) > MAX_ZIP_BYTES:
        raise PackError("Die Datei ist größer als 25 MB.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise PackError("Die Datei ist keine ZIP-Datei.") from None
    with zf:
        files, prefix = _members(zf)
        if len(files) > MAX_FILES:
            raise PackError(f"Die ZIP enthält mehr als {MAX_FILES} Dateien.")
        if sum(i.file_size for i in files) > MAX_UNPACKED_BYTES:
            raise PackError("Entpackt wäre die ZIP größer als 100 MB.")
        plan = []
        for info in files:
            rel = info.filename[len(prefix):]
            parts = rel.split("/")
            if rel.startswith("/") or "\\" in rel or any(p in ("", ".", "..") for p in parts):
                raise PackError(f"Unerlaubter Pfad in der ZIP: {info.filename}")
            if not rel.lower().endswith(ALLOWED_SUFFIXES):
                raise PackError(f"Unerwartete Datei in der ZIP: {info.filename} (erlaubt sind PNG und JSON)")
            plan.append((info, rel))
        try:
            manifest = json.loads(zf.read(prefix + "manifest.json"))
        except (ValueError, KeyError):
            raise PackError("manifest.json ist kein gültiges JSON.") from None
        if not isinstance(manifest, dict):
            raise PackError("manifest.json hat ein unerwartetes Format.")

        parent = os.path.dirname(os.path.abspath(target))
        os.makedirs(parent, exist_ok=True)
        fresh, old = target + ".neu", target + ".alt"
        shutil.rmtree(fresh, ignore_errors=True)
        try:
            for info, rel in plan:
                path = os.path.join(fresh, *rel.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with zf.open(info) as src, open(path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        except (OSError, zipfile.BadZipFile) as e:
            shutil.rmtree(fresh, ignore_errors=True)
            raise PackError(f"Entpacken fehlgeschlagen: {e}") from None

    # Tauschen: altes Paket kurz beiseite, neues an seinen Platz, dann das alte löschen
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(target):
        os.replace(target, old)
    os.replace(fresh, target)
    shutil.rmtree(old, ignore_errors=True)
    reset_caches(target)
    return {**manifest, "installed_files": len(plan)}


def reset_caches(pack_dir: str):
    """Alle Zwischenspeicher, die Grafiken aus dem Paket halten, plus fertige Skript-Blätter."""
    from logic import event_images

    from . import ornaments

    assets.set_pack_dir(pack_dir)
    ornaments._border.cache_clear()
    event_images._auto_cache.clear()
