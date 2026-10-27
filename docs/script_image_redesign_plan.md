# Skript-Bild: Redesign-Plan (zum Review)

Stand: 27.10.2026 · Status: **umgesetzt (Historie)**

> **Stand 27.10.2026:** umgesetzt in `logic/script_sheet/`, Übergabe in `docs/script_sheet_handover.md`. Dieses Dokument ist die Entwurfshistorie; das Labor `lab/script_image_v2/` existiert nicht mehr, lizenzierte Quellen liegen in `private_assets/` (gitignored).

Ziel: Das Skript-PNG soll als Discord-Anhang auf dem Handy ohne Download lesbar sein, auf eine
DIN-A4-Seite passen (inkl. Nachtreihenfolge und Jinxes), deutlich runder aussehen und dabei
billig bleiben (Railway-CPU/RAM, Dateigröße).

Grundregel: **Bis zur Freigabe wird nichts angefasst, was der Bot nutzt.** Alles entsteht in
einem eigenen Labor-Ordner und liest bestehende Daten (Fonts, Icons, characters.json, jinxes.json)
nur aus.

---

## 1. Befund: Was ist heute das Problem?

Referenz: Boozling (25 Charaktere, 5 Jinxes) mit dem aktuellen `logic/script_image.py` gerendert.

| Punkt | Heute | Folge |
|---|---|---|
| Format | 1780 × 4456 px, Verhältnis **1 : 2,5** | Discord skaliert hohe Bilder im Embed und im Vollbild auf die **Höhe** → das ganze Bild schrumpft auf etwa 1/5, die Ability-Schrift landet bei ca. 5 px. Das ist der Hauptgrund für „man muss herunterladen“. |
| Flächennutzung | Zeilenhöhe = Icon (240 px), Text nur 2–3 Zeilen | ca. 40 % der Fläche ist Weißraum. Das Bild ist hoch, ohne mehr zu zeigen. |
| Typo-Hierarchie | Name 15 / Ability 13 / Team-Überschrift **14** | Name und Ability sind fast gleich groß, die Team-Überschrift ist kleiner als ein Name. Es gibt keine klare Ebene, deshalb wirkt es „blass“. |
| Umbruch | `textwrap` nach **Zeichenanzahl** (42) | Ränder flattern, einzelne Wörter hängen in der letzten Zeile („is evil.“), und die Spaltenbreite wird nicht genutzt. |
| Jinxes | Eine Spalte, 72-px-Icons, eigener Djinn-Block | Die Jinxes brauchen ca. 20 % der Bildhöhe für 5 Einträge. |
| Farbe | Nur Namen farbig, sonst Schwarz auf Weiß, Haarlinien | Keine Identität und keine visuelle Gliederung. |
| Nachtreihenfolge | fehlt | — |

## 2. Was machen die Beispiele besser?

Quelle: `docs/examples_pretty scripts/` (4× „scribe“-PDFs von Derek Y., 1× gedrucktes deutsches Blatt).

1. **Klare Typo-Hierarchie.** Titel sehr groß (Zierschrift), Namen in fetter Serif (Goudy Old Style
   Bold, ca. 13 pt), Ability in schlichter Sans (Lato, ca. 9 pt). Das Verhältnis Name : Ability liegt bei
   etwa **1,45 : 1** (bei uns 1,15 : 1). Serif gegen Sans schafft den Kontrast, nicht nur die Größe.
2. **Team-Labels als vertikales Seitenband** (TOWNSFOLK / OUTSIDERS / … gedreht in einem farbigen
   Rand) statt eigener Überschriftenzeilen. Das spart pro Team eine Zeile und bringt Farbe ins Bild.
3. **Treppen-Trenner.** Hat ein Team eine ungerade Anzahl, beginnt das nächste Team im freien Feld
   rechts. Die Trennlinie macht dort einen Knick (siehe Boozling: Cannibal/Mutant, Klutz). Es gibt keine leeren Zellen.
4. **Bewusste Zeilenumbrüche.** Umbruch nach Sinneinheiten (nach „:“ oder „&“) und keine einzelnen Wörter
   in der letzten Zeile. Das wirkt ruhig und „gesetzt“.
5. **Icons ohne Zeilen-Diktat.** Die Icons sind groß, aber die Zeilenhöhe richtet sich nach dem Text.
   Das Icon ist zentriert und darf leicht überstehen.
6. **Jinx-Marker am Namen.** Kleine Icons der gejinxten Partner direkt neben dem Namen (Marionette 🎈⛰👠).
   So sieht man die Jinxes schon in der Liste, und der Jinx-Block selbst kann knapp bleiben.
7. **Jinxes kompakt.** Zwei kleine Icons und 1–2 Zeilen Text, ohne Überschrift „A & B“.
8. **Nachtreihenfolge als Icon-Leiste** (gedrucktes Blatt): je eine Zeile „Erste Nacht“ und
   „Andere Nächte“ mit Sondermarken (Abenddämmerung, Minion-Info „M“, Demon-Info „D“, Morgengrauen).
9. **Identitätsfarbe pro Skript** (Rahmen türkis/blau/grün, Titel in derselben Farbe).

Was wir **nicht** übernehmen: Papiertextur und Ornament-Hintergründe. Das passt zur früheren
Entscheidung „Plain White“, außerdem machen Texturen das PNG 3–5× größer und lassen sich schlecht komprimieren.
Die Farbe kommt stattdessen über das Seitenband, den Titel und die Trenner.

## 3. Zielbild: Ein-Seiten-Layout A4

```
┌─┬───────────────────────────────────────────────────┐
│ │  BOOZLING                      by Lau   [Djinn] … │  Kopf: Titel links, Fabled/Loric als Chips rechts
│T├────────────────────────┬──────────────────────────┤
│O│ ◉ Noble                │ ◉ Pixie                  │
│W│   You start knowing 3… │   You start knowing 1…   │  2 Spalten, Zeilenhöhe = Text
│N│ ◉ …                    │ ◉ …                      │
│S│ ◉ Slayer               │ ◉ Ravenkeeper            │
│ ├────────────────────────┼──┐                       │  Treppen-Trenner
│O│ ◉ Cannibal (TF, 13.)   │ ◉ Mutant                 │
│U│ ◉ …                    │ ◉ …                      │
│T├────────────────────────┴──────────────────────────┤
│M│ ◉ Cerenovus            │ ◉ Marionette 🎈⛰         │  Jinx-Marker am Namen
│I│ ◉ Baron                │ ◉ Scarlet Woman 🐉       │
│ ├────────────────────────┴──────────────────────────┤
│D│ ◉ Imp                  │ ◉ Fang Gu 💋             │
│ │ ◉ No Dashii            │                          │
│ ├───────────────────────────────────────────────────┤
│ │ JINXES  ◉◉ If the Marionette…  │ ◉◉ If the Fang Gu… │  2 Spalten, 7,5 pt
│ │         ◉◉ …                  │ ◉◉ …               │
│ ├───────────────────────────────────────────────────┤
│ │ 1. NACHT  ☾ ◉ ◉ M ◉ D ◉ ◉ ◉ ◉ ◉ ☀                  │  Nachtreihenfolge
│ │ ANDERE    ☾ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ☀                      │
│ │ © Steven Medway · *not the first night            │
└─┴───────────────────────────────────────────────────┘
 ↑ farbiges Seitenband (Identitätsfarbe), Team-Namen gedreht
```

### Platzbudget (A4 = 595 × 842 pt, Rand 22 pt → 551 × 798 nutzbar)

Für ein typisches 25er-Skript (13 TF / 4 OS / 4 MI / 4 DE) mit 5 Jinxes:

| Block | Höhe |
|---|---|
| Kopf (Titel, Autor, Fabled/Loric-Chips) | 50 pt |
| Charaktere: 13 Reihen × ~44 pt (Icon 38 pt, Name 11 pt + 3 × 8,5-pt-Zeilen) | 572 pt |
| 3 Team-Trenner | 12 pt |
| Jinxes: 5 in 2 Spalten → 3 Reihen × 22 pt + Label | 72 pt |
| Nachtreihenfolge: 2 Leisten × 26 pt + Abstand | 60 pt |
| Fußzeile | 12 pt |
| **Summe** | **≈ 778 pt** von 798 |

**Fazit zur Machbarkeit:** Für ein normales Skript passt alles auf eine A4-Seite, aber es wird eng.
Ohne Seitenband-Labels, Treppen-Trenner und Pixel-Umbruch würde es nicht passen.
Für Ausreißer (viele Jinxes, Bootlegger-Regeln, Skripte mit mehr als 25 Charakteren) braucht es eine Stufenlogik:

### Overflow-Stufen (automatisch, in dieser Reihenfolge)

1. **Normal:** wie oben.
2. **Kompakt:** Jinx-Text 7 pt, Jinx-Icons 14 pt, Abstände −20 %.
3. **Skalieren:** Inhalt gleichmäßig verkleinern, **höchstens bis 88 %**. Darunter leidet die Handy-Lesbarkeit.
4. **Zweites Bild:** Jinxes und Bootlegger-Regeln wandern auf ein zweites A4-Bild, das im selben Post
   angehängt wird (Discord zeigt beide als Galerie). Seite 1 behält Charaktere und Nachtreihenfolge.

Die Engine **misst zuerst und zeichnet danach**: Sie berechnet für jede Stufe die Höhe und nimmt die erste, die passt.
Das kostet keine zweite Zeichnung.

## 4. Typografie & Farbe (Vorschlag)

| Element | Font | Größe (pt @ A4) | Farbe |
|---|---|---|---|
| Skript-Titel | Dumbledor (vorhanden) | 30–34, schrumpft bei langen Namen | Identitätsfarbe |
| Autor | Inter (vorhanden) | 9 | Grau 45 % |
| Team-Label (Band, gedreht) | Dumbledor, Versalien, gesperrt | 11 | Weiß auf Bandfarbe |
| Charakter-Name | **fette Serif** (s. u.) | 11 | Gut `#1F4E9A` / Böse `#9B1C1C` |
| Ability | **Lato Regular** (neu, OFL) oder Trade Gothic (vorhanden) | 8,5 | `#1A1A1A` |
| `[Setup]`-Text | Lato Bold | 8,5 | `#1A1A1A` |
| Jinx-Text | wie Ability | 7,5 | `#333` |
| Nacht-Label | Inter Semibold, Versalien | 7 | Grau |

- **Namens-Font:** Die Beispiele nutzen Goudy Old Style Bold, die ist kommerziell lizenziert. Freie Alternativen
  mit gleichem Charakter (OFL): *Sorts Mill Goudy* oder *Goudy Bookletter 1911*. Ich würde beide gegen
  Trade Gothic BoldCond als Muster rendern.
- **Ability-Font:** Trade Gothic Regular ist schmal und spart Platz, Lato ist besser lesbar, aber ca. 8 % breiter.
  Das soll ein A/B-Muster mit echtem Platzverbrauch entscheiden.
- **Identitätsfarbe:** Sie stammt aus `_meta.colour` (falls im Skript-JSON gesetzt), sonst aus einer kuratierten
  Palette von 6–8 gedeckten Tönen (Petrol, Indigo, Moos, Bordeaux, Ocker, Schiefer), deterministisch per Hash des Skriptnamens.
  So hat jedes Skript sein eigenes Gesicht, und das Ergebnis bleibt stabil.

## 5. Nachtreihenfolge

- **Datenquelle:** `nightsheet.json` aus dem TPI-Repo (`resources/data/nightsheet.json`, liegt neben
  `roles.json`/`jinxes.json`; geprüft). Sie enthält die Listen `firstNight` und `otherNight` inklusive `dusk`,
  `minioninfo`, `demoninfo` und `dawn`.
- **Priorität:** `_meta.firstNight` / `_meta.otherNight` aus dem Skript (eigene Reihenfolge des Autors), dann
  `nightsheet.json`, dann Homebrew-Zahlen `firstNight`/`otherNight` aus dem Skript-Content (einsortiert).
- **Inhalt:** Nur Charaktere aus dem Skript, die in der jeweiligen Nacht aufwachen, plus die vier Sondermarken.
  Travellers werden weggelassen. Fabled/Loric mit Nachtaktion kommen mit hinein.
- **Darstellung:** Icons 20–22 pt in einer Zeile. Bei mehr als 22 Einträgen wird die Leiste zweizeilig oder die Icons schrumpfen auf 17 pt.
- Im Labor lade ich `nightsheet.json` nur in den Labor-Ordner. Die Download-Routine des Bots (`script_cache.py`)
  bleibt unverändert und wird erst bei der Integration erweitert.

## 6. Discord & Handy-Lesbarkeit

Ehrliche Einordnung: Eine **komplette** A4-Seite ist auf einem Handy im ungezoomten Vollbild nie
„Lesebrille-frei“ lesbar. Bei 390 pt Displaybreite landet 8,5-pt-Text physisch bei ca. 5,5 pt. Realistische Ziele:

1. **Vorschau im Post:** Die Gliederung ist erkennbar (Farbe, Icons, Namen). Das liefert das A4-Verhältnis
   statt 1 : 2,5. Damit wird die Vorschau ungefähr doppelt so breit wie heute.
2. **Antippen → Vollbild → zoomen:** Alles ist **scharf lesbar ohne Download**. Dafür muss die Auflösung hoch genug sein
   und darf von Discord nicht zu stark heruntergerechnet werden.

Wie Discord (Embed-Bild vs. MediaGallery vs. Anhang, Desktop vs. iOS/Android) genau skaliert, ist nicht
dokumentiert. Deshalb gibt es **Phase 0 als Messung statt Vermutung**: ein Testpost auf dem Testserver mit 4 Varianten,
die wir am Handy vergleichen:

| Variante | Größe | Zweck |
|---|---|---|
| A | 1240 × 1754 (150 dpi) | klein und günstig |
| B | 1654 × 2339 (200 dpi) | Favorit |
| C | 2480 × 3508 (300 dpi) | Druckqualität |
| D | heutiges Bild | Referenz |

Jeweils als Embed-`set_image` (so nutzt es `event_post.py` heute) **und** als reine MediaGallery. Ergebnis: Wir legen
die Pixelgröße fest und sehen, ob die Darstellungsart wechseln sollte.

## 7. Performance / Railway

- **Nur Pillow**, kein Headless-Browser (Playwright/Chromium würde 300+ MB RAM und Sekunden pro Bild kosten).
- **Render-Cache:** Ergebnis-PNG unter `VOLUME_DIR/script_images/<sha1(Skript-JSON + RENDER_VERSION)>.png`.
  Dasselbe Skript wird nur einmal gerendert, egal wie viele Events es nutzen. `RENDER_VERSION` hochzählen erzwingt Neurendern nach Designänderungen.
- **Icon-Cache im Speicher:** Icons pro (id, Größe) einmal skalieren (LRU, ca. 200 Einträge ≈ 10 MB).
  Heute wird pro Bild jedes Icon neu von Platte geladen und skaliert.
- **Kein Supersampling** (kein 2× rendern + verkleinern), sondern direkt in Zielgröße. RAM bei 1654 × 2339 RGB ≈ 12 MB pro Bild.
- **Dateigröße:** PNG mit `optimize`. Zusätzlich teste ich eine Palettenquantisierung (256 Farben, für weißen Grund mit Icons
  meist unsichtbar), Ziel < 1,5 MB. JPEG fällt raus (Artefakte an Text), WebP nur, wenn Discord es überall sauber anzeigt.
- **Messlatte für die Freigabe:** < 600 ms Renderzeit pro Skript (kalt, auf meinem Rechner), < 1,5 MB Datei, < 60 MB Spitzen-RAM.
  Die Werte werden im Labor gemessen und im Review mitgeliefert.

## 8. Vorgehen in Phasen

**Isolation:** neuer Branch `script-image-redesign` (von `testphase`), neuer Ordner `lab/script_image_v2/`:

```
lab/script_image_v2/
  render.py        # Layout-Engine (measure → choose stage → draw), eigenständig
  fixtures/        # Test-Skripte als JSON
  data/            # nightsheet.json (nur Labor)
  out/             # erzeugte PNGs (gitignored)
  run_gallery.py   # rendert alle Fixtures + misst Zeit/Größe → out/index.html zum Durchklicken
```

Gelesen werden nur `static/fonts`, `data/icons`, `characters.json` und `jinxes.json`. Es gibt keinen Import, der etwas
am Bot verändert, und keine Änderung an `logic/`, `discord_ui/` oder `script_cache.py`.

| Phase | Inhalt | Ergebnis zum Review |
|---|---|---|
| 0 | Discord-Messung (Abschnitt 6) mit Dummy-Bildern | festgelegte Pixelgröße und Darstellungsart |
| 1 | Engine-Grundgerüst: Pixel-Umbruch mit Zeilenausgleich, Spaltenfluss mit Treppen-Trenner, Seitenband | Boozling als A4-PNG |
| 2 | Typo- und Farb-Varianten (2–3 Muster: Fonts, Identitätsfarbe) | Muster nebeneinander, du wählst |
| 3 | Jinx-Block, Jinx-Marker am Namen, Bootlegger, Nachtreihenfolge | vollständige Seite |
| 4 | Overflow-Stufen und Edge-Case-Galerie (s. u.) | Galerie aller Fixtures |
| 5 | Performance-Messung, Cache, Dateigröße | Messwerte |
| 6 | **Erst nach Freigabe:** Integration hinter Schalter, alter Generator bleibt als Fallback | eigener Plan |

**Edge-Case-Fixtures:** Trouble Brewing (keine Jinxes) · Boozling (5 Jinxes) · ein jinx-lastiges Skript (10–15) ·
Homebrew mit Bootlegger-Regeln und imgur-Icons · Teensyville (wenig Charaktere) · 30+ Charaktere ·
sehr langer Skriptname · Skript mit Fabled und Loric.

## 9. Offene Fragen an dich

1. **Weißer Grund bleibt?** Mein Vorschlag: ja, Farbe nur über Seitenband, Titel und Trenner.
   Papier bleibt verworfen.
2. **Fonts:** Darf ich eine freie Goudy-artige Serif (OFL) und Lato ins Repo aufnehmen?
3. **Spieleranzahl-Tabelle** (wie in den Beispielen)? Mein Vorschlag: weglassen, das kostet ca. 70 pt und erfahrene Spieler kennen sie.
4. **Overflow:** Ist ein zweites Bild als letzte Stufe okay, oder soll lieber stärker verkleinert werden?
5. **Sprache:** Bleiben die Texte englisch wie heute? Die Labels (z. B. „FIRST NIGHT“) würde ich ebenfalls englisch halten.

## 10. Assets, die ich von dir bräuchte (optional)

- ~~Sondermarken der Nachtreihenfolge~~ erledigt, zwei Varianten zum Vergleich in Phase 2:
  - `lab/script_image_v2/assets/night/`: Originale aus dem TPI-Script-Tool (130 px, WebP)
  - `lab/script_image_v2/assets/night_custom/`: selbst gezeichnet (`make_night_tokens.py`, 400 px, PNG)
- ~~Lieblingsskripte als JSON~~ erledigt: Boozling, Do You Believe in Balloonists?, The Midnight Oasis
  (`lab/script_image_v2/fixtures/`, von botcscripts.com).
- Sonst nichts: Icons, Jinxes und Fonts sind vorhanden bzw. frei verfügbar.

---

## 11. Designstand Ornamentik (27.10.2026, im Labor umgesetzt)

Code: `lab/script_image_v2/ornaments.py` (Katalog, Randmuster, Ecken, Stempel, Rezept), Titel in `title_styles.py`.

- **Eine Formensprache:** feine Himmels-Linien (Etsy „Mystic“ Set 8) tragen Ecken, Titel und Trenner.
  Keine Ranken/Zweige (Lorbeerkranz-Look), keine Verzierung über dem Titel, keine Lückenfüller.
- **Asset-Katalog nach Rollen:** `rule` (Linie, waagrecht gedreht), `emblem` (Trenner Skript/Anhang),
  `seal` (blasses Emblem hinter dem Titel), `stamp` (Motiv, höchstens eins pro Seite). Kein Asset doppelt.
- **Rezept je Skript** (stabil aus dem Namen): Titelbehandlung (`rules`, `byline`, `seal`, `sparkles`,
  `seal_byline`), Eck-Linie, Trenner-Emblem, Stempel (oben rechts, rechtes Ende der Nachtleiste oder keiner;
  nie zusammen mit dem Siegel).
- **Rand:** scharf gezeichnetes Kleinmuster (`lattice`, `dots`, `stars`, `moons`); an den Ecken ersetzen
  Himmels-Linien mit Stern die Goldlinie.
- **Spielprägend:** wie im Bot (`logic/event_builder.highlight_characters`, Top 5 nach Score aus
  `static/character_rating.json`); dargestellt als runde Marke („Token“) in zarter Teamfarbe mit feinem Ring.
- **Farben:** Ornamente in neutraler Tinte, Rahmen und Eckstücke im Gold der Rahmenlinie, Stempel
  körnig per Multiplikation über Rahmen und Text.
- **Platz:** freier Platz wird gleichmäßig auf die Abschnittsabstände verteilt.

## 12. Asset-Datenbank (27.10.2026)

`lab/script_image_v2/assets/asset_db.json`, gebaut mit `build_asset_db.py` aus Form-Daten, Agenten-Tags und
Dalyans Entscheidungen (Vorrang). 644 Motive mit Rollen (title_motif, edge, centerpiece, seal, rule, foliage,
accent, divider), Themen und Stil. Die 181 Wegwerf-Vorschläge (`out/review/db/raus_*.png`) sind von Dalyan
abgenommen; seine 23 umstrittenen Auswahl-Motive bleiben drin.

## 13. Linien-Verzierungen verworfen (27.10.2026)

Bewuchs, Anhänger und Konstellationen an Linien, Linien-Fortsetzungen und der Konstellations-Editor sind
wieder entfernt („wirkt zufällig“). Behalten: Titel-Behandlungen (Motiv, Siegel, Linien, Funkelsterne),
Eckstücke im Rahmen, Hand aus der oberen Ecke, Tinten-Kleckse für spielprägende Charaktere, Trenner zum Anhang.
Stichprobe: `lab/script_image_v2/batch.py` rendert N zufällige Top-Skripte aus dem ScriptRater.
Travellers werden nicht gezeigt: weder im Raster noch im Anhang, in der Nachtreihenfolge oder in Jinxes.
