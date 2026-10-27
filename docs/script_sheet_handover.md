# Übergabe: Skript-Blatt (neues Skript-Bild)

Stand 27.10.2026 · Branch `script-image-redesign` (Worktree `BOT_VillageIdiot_sheet`, von `event-wizard` abgezweigt)

Das neue Skript-Bild liegt als eigenständiges Modul in `logic/script_sheet/`.

**Nachtrag 27.10.2026: eingebaut** (Abschnitt 6.1 und 6.2 erledigt, 6.2.4 und 6.3 offen):
- Asset-Paket per ZIP-Upload über `/skriptblatt_paket` (nur DMs, nur Bot-Besitzer, nur mit
  `SCRIPT_SHEET_UPLOAD=1`; Code `commands/script_sheet_pack.py`, `logic/script_sheet/pack_install.py`). Entpackt
  erst nach `script_sheet_assets.neu`, prüft Pfade, Dateitypen und Größe, tauscht dann; kaputte ZIP → altes Paket
  bleibt. Verworfen: Railway CLI (kein Datei-Upload), privates Repo/Release mit Token, Speicher-Link,
  verschlüsselt im Repo.
- `event_images.py` nutzt `generate_script_sheet`, Theme aus der Schwierigkeit (im Cache-Schlüssel und in
  `image_signature`). `None` → kein Bild, die Zusammenfassung sagt „keins (Skript zu groß für ein Bild)“.
- Anhang heißt `event_image.jpg` (Skript-Blatt) bzw. `event_image.png` (eigene Bilder und alte Posts);
  `image_filename(bytes)` wählt nach Format, `_shown_images` liest den Namen aus der Bild-URL.
- `nightsheet.json` kommt beim TPI-Update aufs Volume. Icon-Laden steckt jetzt in `logic/script_cache.py`
  (`load_icon`, `fetch_icon`, `prefetch_icons`, Homebrew-Icons parallel vorgeladen);
  `logic/script_image.py` und `test_generate_image.py` sind gelöscht.

---

## 1. ⚠️ Lizenzierte Grafiken – dürfen NICHT gepusht werden

Das Repo `dalyan28/village-idiot-bot` ist **öffentlich**. Folgende Dateien sind gekauft oder nur zum Testen
freigegeben und dürfen weder committet noch irgendwo öffentlich hochgeladen werden (auch nicht als Release-Datei,
Gist oder in einem anderen öffentlichen Repo):

| Ort (alle per `.gitignore` ausgeschlossen) | Inhalt | Herkunft |
|---|---|---|
| `private_assets/etsy/` | Original-Sets (Witchcraft Graphics, Mystical Mushroom, Mystic Ockult Wiccan Symbole, Clipping Masks, Celestial Backgrounds), 265 MB | von Dalyan auf Etsy gekauft |
| `private_assets/scribe/pattern_tile.png` | Damast-Kachel des Rands | aus den scribe-PDFs von Derek Y. – **nur Testfreigabe**, vor dem Live-Betrieb ersetzen |
| `private_assets/tpi_night/` | Nachtmarken Dusk/Minion-Info/Demon-Info/Dawn | aus dem TPI-Script-Tool |
| `private_assets/references/`, `private_assets/asset_db.json` | Beispielbilder, getaggte Asset-Datenbank (Review-Ergebnis) | Arbeitsmaterial |
| `data/script_sheet_assets/` | **das gebaute Asset-Paket** (111 Dateien, 8,9 MB), Ableitungen der obigen Dateien | `python -m logic.script_sheet.build_pack` |
| `docs/examples_pretty scripts/` | scribe-PDFs und Foto als Designvorlage | Derek Y. bzw. Dalyan |

Regeln:
- Kein `git add -f` auf diese Pfade, die `.gitignore`-Einträge nicht entfernen.
- Vor jedem Commit `git status --short` prüfen: Es darf nichts unter `private_assets/`, `data/script_sheet_assets/`
  oder `docs/examples_pretty scripts/` auftauchen.
- Auch abgeleitete Dateien (verkleinerte Masken im Paket) gelten als lizenziert.

**Darf ins Repo** (frei bzw. selbst erstellt, bereits so angelegt):
- `static/fonts/PlayfairDisplay*.ttf`, `BodoniModa*.ttf`, `SourceSerif4*.ttf`, `Lato-Bold.ttf`: SIL Open Font
  License, Lizenztexte in `static/fonts/licenses/`
- `static/script_sheet/washes/` (24 Aquarell-Kleckse) und `static/script_sheet/night/` (eigene Nachtmarken):
  selbst erzeugt mit `python -m logic.script_sheet.make_static`
- `static/nightsheet.json`: offizielle Nachtreihenfolge aus dem öffentlichen TPI-Repo (wie `characters.json`/`jinxes.json`)

## 2. Verhalten ohne Asset-Paket

Fehlt das Paket (frisches Deployment, kaputtes Volume, Tests), funktioniert alles weiter:

| Element | mit Paket | ohne Paket |
|---|---|---|
| Rand | Damast-Muster in Theme-Farbe | **nur die Theme-Farbe** |
| Eckstücke im Rahmen | Himmels-Linien mit Stern, Goldlinie endet in Rauten | durchgehende goldene Doppellinie |
| Titel-Verzierung (Linien, Siegel, Funkelsterne, Motiv) | je Skript eine Variante | keine; Titel schlicht |
| Trenner zum Anhang | Emblem in der Mitte | durchgehende Haarlinie |
| Kleckse (spielprägende Charaktere) | eigene Formen + Pinselstriche aus dem Paket | **nur die eigenen Formen** aus `static/` |
| Nachtmarken | TPI-Originale | eigene aus `static/` |

Getestet in `tests/test_script_sheet.py` (rendert ohne Paket).

## 3. Aufbau

```
logic/script_sheet/
  __init__.py      öffentliche API: generate_script_sheet, render_script_sheet, theme_for_rating
  style.py         Maße, Größen, Farben, Themes, Grenzwerte (JINX_LIMIT, MAX_LENGTH …)
  assets.py        Schriften, eigene Grafiken, Asset-Paket (Pfad, Pools, Fallbacks)
  model.py         Skript aufbereiten: Teams, Jinxes (+ Djinn), Bootlegger-Regeln, Nachtreihenfolge, spielprägend
  title.py         Titel-Varianten und -Behandlungen
  ornaments.py     Rezept je Skript, Rahmen mit Eckstücken, Tinten-Kleckse
  sheet.py         Seitenaufbau, Messen, Größensuche, Überlänge
  build_pack.py    CLI: Asset-Paket aus private_assets/ bauen
  make_static.py   CLI: eigene Kleckse und Nachtmarken nach static/script_sheet/ erzeugen (braucht numpy, steht in requirements-dev.txt)
  preview.py       CLI: Skript-JSONs rendern → test_output/script_sheet/
tests/test_script_sheet.py
```

Paket-Pfad zur Laufzeit: `VOLUME_DIR/script_sheet_assets` (lokal `data/script_sheet_assets`, auf Railway
`$RAILWAY_VOLUME_MOUNT_PATH/script_sheet_assets`), überschreibbar mit der Umgebungsvariable `SCRIPT_SHEET_ASSETS`.

Nützliche Befehle (aus dem Repo-Root):
```
python -m pytest tests/test_script_sheet.py
python -m logic.script_sheet.preview test_scripts/Boozling.json --theme red
python -m logic.script_sheet.preview test_scripts/Boozling.json --no-pack     # Stand ohne Lizenz-Grafiken
python -m logic.script_sheet.build_pack                                      # Paket neu bauen
```

## 4. Was das Blatt kann (Entscheidungen von Dalyan)

- DIN A4 (1654 × 2339 px bei 200 dpi), JPEG (Papierstruktur → ca. 0,9 MB statt 3 MB als PNG).
- Schriftgröße wird automatisch so groß wie möglich gewählt (86–110 %). Passt es nicht auf A4, wird die Seite
  länger; ab 2 × A4 (z. B. Skript mit allen Charakteren) gibt es **kein Bild** → `generate_script_sheet` liefert `None`.
- Theme nach Schwierigkeit (grün/gelb/rot); bei Bereichen die höhere Stufe (`theme_for_rating`).
- Spielprägend = Top 5 nach Score aus `static/character_rating.json` (gleiche Logik wie
  `event_builder.highlight_characters`), dargestellt als Tinten-Klecks, abgestuft nach Score.
- Travellers werden nirgends gezeigt (auch nicht in Jinxes oder in der Nachtreihenfolge).
- Mehr als 8 Jinxes → 7 plus Feld „+ N weitere Jinxes“. Bei Jinxes wird der Djinn ergänzt (als Icon an der Überschrift).
- Homebrew: Icons aus den Skript-URLs, Nachtposition aus den Zahlen im Skript-JSON.
- Verworfen (nicht wieder einbauen): Stempel, Hände in den Ecken, Verzierungen auf den Linien, Pergament-/Wolkenpapier,
  Fraktur/Gold-Titel. Details: `docs/script_image_redesign_plan.md`.

## 5. Abhängigkeiten zum bestehenden Code

- `sheet.py` importiert `_load_icon` aus `logic/script_image.py` (lokale TPI-Icons, Homebrew-Download mit Cache).
  Wenn der alte Generator gelöscht wird, `_load_icon`/`_fetch_icon`/`_prefetch_icons` vorher z. B. nach
  `logic/script_cache.py` verschieben (und `tests/test_homebrew_icons.py` mitziehen).
- `model.py` nutzt `load_characters`, `get_jinxes_for_script`, `STATIC_DIR`, `VOLUME_DIR` aus `logic/script_cache.py`.
- `__init__.py` nutzt die Rating-Konstanten aus `events/schema.py`.

## 6. Deine Aufgaben

### 6.1 Zuerst: Dalyan die einfachste Lösung für das Asset-Paket vorschlagen

Das Paket (8,9 MB, ändert sich selten) muss auf das Railway-Volume, ohne in Git zu landen. Bitte prüfe die
Möglichkeiten mit unserer Architektur (Railway deployt aus dem öffentlichen GitHub-Repo, persistentes Volume unter
`RAILWAY_VOLUME_MOUNT_PATH`, der Bot lädt dort heute schon TPI-Icons und Daten ab) und **präsentiere Dalyan die
einfachste**, bevor du etwas baust. Kandidaten, die du bewerten solltest:
- Paket einmalig per Railway CLI direkt aufs Volume kopieren (prüfen, ob `railway ssh` bzw. Upload ins Volume das zuverlässig kann)
- Bot lädt das Paket beim Start einmal von einer privaten Quelle (privates GitHub-Repo/Release mit Token,
  oder ein privater Speicher-Link) per Umgebungsvariable herunter und entpackt es aufs Volume
- Admin-Befehl im Bot, der eine hochgeladene ZIP-Datei aufs Volume entpackt (Discord-Anhangsgrenze beachten;
  `build_pack.MAX_SIDE` kann das Paket bei Bedarf verkleinern)

Kriterien: wenig neuer Code, keine Kosten, nichts Lizenziertes öffentlich, ohne Paket läuft der Bot weiter (Abschnitt 2).

### 6.2 Einbau (nach Dalyans Freigabe)

1. `logic/event_images.py`: statt `generate_script_image(...)` →
   `generate_script_sheet(name, author, characters, meta=meta, content=content, theme=theme_for_rating(data.rating))`.
   - `None` als Ergebnis abfangen (kein Auto-Bild).
   - `IMAGE_FILENAME` ist `event_image.png`, das Blatt ist JPEG → Dateinamen auf `.jpg` umstellen (Discord leitet den
     Typ aus der Endung ab) und alle `attachment://`-Verweise prüfen.
   - Theme hängt an `data.rating`: in den Cache-Schlüssel (`_auto_cache`) und in `image_signature` aufnehmen,
     sonst bleibt nach einer Schwierigkeitsänderung das alte Bild hängen.
2. `logic/script_cache.py`: beim TPI-Update zusätzlich
   `https://raw.githubusercontent.com/ThePandemoniumInstitute/botc-release/main/resources/data/nightsheet.json`
   aufs Volume laden (`model._resolve` liest Volume zuerst, sonst `static/nightsheet.json`).
3. Danach den alten Generator (`logic/script_image.py`, `test_generate_image.py`) entfernen – siehe Abschnitt 5.
4. Noch offen aus dem Plan: Test auf dem Testserver, wie Discord das A4-JPEG am Handy darstellt (Embed-Bild vs.
   MediaGallery).

### 6.3 Vor dem Live-Betrieb

- Die Damast-Kachel (`private_assets/scribe/pattern_tile.png`) ist nur für Tests freigegeben. Vor dem Live-Betrieb
  durch eine eigene oder lizenzierte Kachel ersetzen (gleicher Dateiname, dann `build_pack` neu ausführen) – oder
  ohne Kachel ausliefern (Rand einfarbig).
- Renderzeit: ca. 1–2 s beim ersten Bild eines Skripts (Icons laden), danach ca. 0,2 s; dazu `asyncio.to_thread`.
