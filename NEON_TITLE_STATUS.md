# Neon-Titel Status & TODO

Stand: 2026-04-19 — Arbeit im `DESIGN_STARFIELD_NEON` Theme, Hauptdatei
[logic/script_image.py](logic/script_image.py).

## Was fertig ist

**Layout-Konzept** (final, abgestimmt mit User über Box-Diagramm):

Multi-Word (z. B. `STRANGER / THINGS`, `ICH GEHE MORGEN / SHOPPEN`, `TO TELL THE / TRUTH`):
- **Zeile 1**: erster und letzter Buchstabe groß (Orange), Middle-Buchstaben kleiner und top-aligned (Blau)
- **Zeile 2** (letzte Wort-Gruppe): eingeschoben im Band zwischen Small-Bottom und Big-Bottom (Rosa), horizontal zentriert zwischen den beiden großen Buchstaben
- **Bars** (Grün): zwei kurze horizontale Striche UNTER den Orange-Buchstaben, beide gleich lang:
  `bar_len = max(first_w + 0.4×second_w, last_w + 0.4×second_to_last_w)`
- **Split**: `_choose_wider_line1_split` wählt Split so, dass Zeile 1 mind. 12% breiter als Zeile 2 (in natürlicher Wort-Reihenfolge). Fallback bei nicht möglichem Split: uniform-2-Zeilen-ST-Stil mit externen Bars

Single-Word (z. B. `ONE`):
- First + Last groß, Middle top-aligned smaller
- EIN Bar UNTER den Middle-Buchstaben (Underline-Effekt)
- KEINE Bars unter First/Last

**Farben** (exakt die Mid-Tönen der Neon-Icons, damit Titel + Icons nach dem Finishing-Filter dieselbe Sättigung haben):
- Fill (Schrift) = Evil-Magenta-Mid = `(175, 30, 75)` (aus `_magenta_icon`)
- Stroke (Outline) = Good-Teal-Mid = `(35, 140, 165)` (aus `_teal_icon`)

**Stroke-Clearance**: Line 2 im Band vertikal zentriert, mit `effective_top_clearance = 2 × stroke_w` und `effective_bottom_clearance = stroke_w`, damit Stroke nicht mit Middle-Buchstaben überlappt.

**Font + Tracking**:
- Benguiat Bold (`_F_TITLE_GOLD`)
- `size_big = SZ_TITLE × 2.1` mit Auto-Shrink wenn Zeile 1 max_line_w überschreitet
- 5% Tracking (Letter-Spacing)
- Middle-Ratio = 0.55 (Band ≈ 0.45 × full_h für Line 2)

**Rendering-Technik**: 2-Pass (Strokes-Layer unter Fills-Layer + alpha_composite), damit benachbarte Buchstaben-Strokes nicht gegenseitig Fills überschreiben.

## Getestet via

- [test_neon_gallery.py](test_neon_gallery.py) — rendert 10 verschiedene Titel-Längen auf einen Blick → `test_output/_neon_gallery.png`
- [test_starfield.py](test_starfield.py) — rendert den vollständigen Script mit Charakteren → `test_output/To_tell_the_truth_starfield_neon.png`
- Raw-Closeups auf grauem BG in `test_output/_raw_*.png` (ohne Finishing-Filter, zeigt Geometrie am deutlichsten)

Getestete Titel:
`One`, `Stranger Things`, `Ich gehe morgen shoppen`, `Trouble Brewing`, `Sects and Violets`, `To tell the truth`, `Bad Moon Rising`, `Ides of March and April`, `The final gambit of destiny`, `Midnight at the cathedral of lies`.

## Key-Funktionen in [logic/script_image.py](logic/script_image.py)

- `_render_neon_title(text, font_size)` — Dispatcher, entscheidet Single-Word vs Multi-Word, mit Fallback
- `_render_neon_single_word(...)` — Single-Word-Layout mit Underline-Bar unter Middle
- `_render_neon_composite(line1, line2, ...)` — Multi-Word-Layout (Orange+Blau+Rosa+Grün)
- `_render_neon_line(line, font, ...)` — Fallback uniform-line (wird nur vom Multi-Word-Fallback genutzt)
- `_choose_wider_line1_split(words, ...)` — Split-Algorithmus mit Line1 > Line2 Constraint
- `_split_title_for_neon(text, font, max_w)` — Einfacher balancierter Split für Fallback
- `_fit_size_to_width(line, max_w, base, min, tracking_ratio)` — Auto-Shrink bis Zeile passt
- `_measure_line_mixed(chars, f_big, f_small, tr_big, tr_small)` — Measurement-Helper für Mixed-Size-Zeilen
- `_render_sticker_author(text, font_size)` — Autor in Cream Cake Bold, weißer Sticker-Look

## Nächste mögliche Iterationen

Nichts Dringendes, aber falls Feedback kommt:

1. **Feintuning der Proportionen** — falls Line 2 zu klein oder Bars zu kurz wirken:
   - `small_mid_ratio` (aktuell 0.55) anpassen für andere Band-Höhe
   - `ext_ratio` (aktuell 0.40) für Bar-Extension auf zweite Letter ändern
   - `bar_thick` Formel (aktuell `max(10, int(full_h * 0.10))`)
2. **Chromatic Aberration / Glow** — falls der Effekt mehr Stranger-Things-Feel bekommen soll (war in früherer Iteration drin, rausgenommen für Clean-Look)
3. **Long-Title-Handling** — sehr lange Titel (>6 Wörter) funktionieren aber Line 2 wird klein; könnte Warning loggen oder 3-Zeilen-Layout überlegen
4. **Fallback-Styling** — der Uniform-2-Lines-Fallback (wenn Line 1 nicht wider sein kann) unterscheidet sich stark vom Hauptstil. Überlegen ob man ihn auch ans neue Konzept anpasst

## Offenes Infrastruktur-Problem

- **venv korrumpiert durch OneDrive** — `venv/Scripts/` fehlt, `venv/Lib/site-packages/PIL/` ist fast leer
- Workaround: `python -m pip install --user Pillow requests` gegen System-Python 3.12
- Langfristig: Projekt aus OneDrive rausziehen (z. B. `C:\dev\VillageBot`) — `venv/`, `__pycache__/`, `test_output/`, `.git/` gehören nicht in die Cloud-Virtualisierung

## Relevante Dateien

- [logic/script_image.py](logic/script_image.py) — alle Neon-Titel-Funktionen (ca. Zeilen 549-1000)
- [logic/starfield_bg.py](logic/starfield_bg.py) — Sternenhimmel-Background (unverändert)
- [test_scripts/To tell the truth.json](test_scripts/To tell the truth.json) — Test-Script-Daten
- [test_neon_gallery.py](test_neon_gallery.py) — Gallery-Test für Title-Varianten
- [test_starfield.py](test_starfield.py) — Full-Script-Test mit Gold + Neon + White Varianten
