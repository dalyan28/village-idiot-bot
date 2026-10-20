"""Darstellung des DM-Wizards mit Discord Components V2.

Wie bei Apollo steht neben jedem Abschnitt der Zusammenfassung ein eigener „Ändern“-Button.

Grenzen von Discord: höchstens 40 Komponenten und 4000 Zeichen Text je Nachricht.
Eine V2-Nachricht kann keinen Text und keine Embeds mehr haben, nur Komponenten.
"""

from __future__ import annotations

import io

import discord

TEXT_LIMIT = 4000
WIZARD_COLOR = 0x5865F2
PREVIEW_IMAGE = "vorschau.png"


def _shorten(layout: discord.ui.LayoutView):
    """Kürzt die längsten Texte, falls die Nachricht über 4000 Zeichen käme."""
    while layout.content_length() > TEXT_LIMIT:
        longest = max((i for i in layout.walk_children() if isinstance(i, discord.ui.TextDisplay)),
                      key=lambda i: len(i.content))
        over = layout.content_length() - TEXT_LIMIT
        longest.content = longest.content[: max(20, len(longest.content) - over - 2)] + " …"


MISSING_MARK = "🔴 fehlt"

# Fehlende Pflichtangabe → (Ziel von „Feld ändern“, Button-Beschriftung)
MISSING_TARGETS = {
    "Skript": ("script", "Skript wählen"),
    "Beschreibung": ("description", "Beschreibung schreiben"),
    "Storyteller": ("people", "Storyteller eintragen"),
    "Schwierigkeit": ("rating", "Schwierigkeit wählen"),
    "Termin": ("frame", "Termin eintragen"),
}


def _missing_buttons(missing: list[str]) -> list[tuple[str, str]]:
    """Ein roter Button je fehlender Angabe, höchstens 2 (dazu „Bild ändern“ und „Abbrechen“).

    Discord erlaubt 40 Komponenten je Nachricht; mit Suchtreffer-Liste ist die Karte nah dran.
    """
    buttons, seen = [], set()
    for name in missing:
        target, label = MISSING_TARGETS.get(name, ("description", f"{name} ergänzen"))
        if target not in seen:
            seen.add(target)
            buttons.append((target, label))
    return buttons[:2]


def _block(label: str, *lines: str) -> str:
    """Abschnitt: kleine graue Überschrift, darunter die Werte."""
    return "\n".join([f"-# {label}", *lines])


async def summary_layout(bot: discord.Client, store, draft, notice: str | None = None):
    """Zusammenfassung (Dalyan, 20.10.2026, nach Test auf dem Handy).

    Titel als Überschrift mit eigenem „Ändern“, danach je ein Abschnitt mit kleiner Überschrift:
    Beschreibung · Skript (mit Schwierigkeit) · Leitung · Auswahl (Labels, Level, Kamera) ·
    Termin (organisatorisch) · Bild (kleine Vorschau). Alle Buttons heißen „Ändern“; die Beschreibung
    öffnet einen Dialog nur mit dem Beschreibungsfeld. Gibt (LayoutView, Dateien) zurück.
    """
    from discord_ui import wizard as wz  # zirkulären Import vermeiden
    from discord_ui.event_post import build_files
    from events.parse import format_start
    from events.schema import (CAMERA_LABELS, IMAGE_AUTO, IMAGE_CUSTOM, RATING_SOURCE_RATER, SCRIPT_BASE,
                               missing_for_publish)
    from events.templates import LABEL_EMOJI, RATING_WORDS, full_title
    from logic.event_builder import embed_color
    from logic.event_images import IMAGE_FILENAME, has_auto_image

    d = draft.data
    esc = discord.utils.escape_markdown
    guild = bot.get_guild(draft.guild_id)

    def section(text: str, target: str, label: str = "Ändern") -> discord.ui.Section:
        return discord.ui.Section(discord.ui.TextDisplay(text),
                                  accessory=wz.WizardButton(draft.id, "edit_field", label, arg=target))

    container = discord.ui.Container(accent_colour=embed_color(d))
    heading = "Neue Runde" if draft.event_id is None else "Runde bearbeiten"
    head = f"-# {heading} · {esc(guild.name)}" if guild else f"-# {heading}"
    # Titel als Überschrift, direkt änderbar
    title_note = "" if d.title.strip() else "\n-# Titel wird automatisch gebaut"
    container.add_item(section(f"{head}\n## {esc(full_title(d))}{title_note}", "title"))
    missing = missing_for_publish(d)
    status = (f"🔴 **Bevor du veröffentlichen kannst, fehlt noch:** {', '.join(missing)}" if missing
              else "Alles da. Wenn es passt: **Veröffentlichen**.")
    if notice:
        status += f"\n{notice}"
    container.add_item(discord.ui.TextDisplay(status))

    # Beschreibung (eigener Dialog, nur das Textfeld)
    if d.description.strip():
        description = esc(d.description.strip())
    else:
        description = MISSING_MARK
    if d.is_academy:
        description += "\n-# Darunter folgt der feste Academy-Text."
    container.add_item(discord.ui.Separator())
    container.add_item(section(_block("BESCHREIBUNG", description), "description",
                               "Ändern" if d.description.strip() else "Schreiben"))

    # Skript mit Schwierigkeit
    s = d.script
    if s is None:
        lines = [MISSING_MARK]
    else:
        script_line = f"**{esc(s.display_name)}**"
        if s.author and s.kind != SCRIPT_BASE:
            script_line += f" von {esc(s.author)}"
        if s.version and s.kind != SCRIPT_BASE:
            script_line += f" · v{esc(s.version)}"
        if s.teensy:
            script_line += " · Teensyville"
        lines = [script_line]
    container.add_item(discord.ui.Separator())
    container.add_item(section(_block("SKRIPT", *lines), "script", "Ändern" if s else "Wählen"))

    # Schwierigkeit (eigener Abschnitt, gleich unter dem Skript – ohne Trennlinie, gehört zusammen)
    if d.rating:
        rating_lines = [f"{LABEL_EMOJI[d.rating]} {RATING_WORDS[d.rating].capitalize()}"]
        if d.rating_source == RATING_SOURCE_RATER:
            explanation = wz.rating_explanation(draft.ui or {}, limit=2)
            if explanation:
                rating_lines.append(explanation)
    else:
        rating_lines = [MISSING_MARK if s is not None else "Ergibt sich aus dem Skript"]
        if (draft.ui or {}).get("rating_error"):
            rating_lines.append(esc(draft.ui["rating_error"]))
    if d.is_special:
        why = "; ".join(d.special_reasons) if d.special_reasons else "von dir gesetzt"
        rating_lines.append(f"⭐ {esc(why)}")
    container.add_item(section(_block("SCHWIERIGKEIT", *rating_lines), "rating"))

    # Leitung
    st = esc(d.storyteller.name) if d.storyteller else MISSING_MARK
    co = esc(d.co_storyteller.name) if d.co_storyteller else "–"
    container.add_item(discord.ui.Separator())
    container.add_item(section(_block("LEITUNG", f"{st} · Co-ST: {co}"), "people"))

    # Auswahl: Labels, Level, Kamera
    labels = [name for flag, name in ((d.is_academy, "🎓 Academy"), (d.is_casual, "🕊️ Casual"),
                                      (d.is_recorded, "🎦 Aufzeichnung"), (d.is_special, "⭐ Abweichung")) if flag]
    selection = " · ".join([*labels, f"Level {d.level}", f"Kamera: {CAMERA_LABELS[d.camera]}"])
    container.add_item(discord.ui.Separator())
    container.add_item(section(_block("AUSWAHL", selection), "selection"))

    # Termin & Rahmen
    termin = format_start(d.start, d.duration_minutes) if d.start else MISSING_MARK
    container.add_item(discord.ui.Separator())
    container.add_item(section(_block("TERMIN", f"{termin} · max. {d.max_players} Spieler"), "frame"))

    # Bild: kleine Vorschau rechts; geändert wird es über „Bild ändern“ unten
    files = await build_files(d)
    has_image = any(f.filename == IMAGE_FILENAME for f in files)
    image_text = {IMAGE_AUTO: "Aus dem Skript" if has_auto_image(d) else "Keins (freie Skriptwahl)",
                  IMAGE_CUSTOM: "Eigenes Bild"}.get(d.image_mode, "Kein Bild")
    container.add_item(discord.ui.Separator())
    image_block = discord.ui.TextDisplay(_block("BILD", image_text))
    if has_image:
        container.add_item(discord.ui.Section(
            image_block, accessory=discord.ui.Thumbnail(f"attachment://{IMAGE_FILENAME}")))
    else:
        container.add_item(image_block)

    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    row = discord.ui.ActionRow()
    if missing:
        # Statt Veröffentlichen: je fehlender Angabe ein roter Button, der direkt dorthin führt
        for target, label in _missing_buttons(missing):
            # eigene Aktion: dieselbe custom_id wie der Ändern-Button am Abschnitt lehnt Discord ab
            row.add_item(wz.WizardButton(draft.id, "fix_field", label, discord.ButtonStyle.danger, arg=target))
    else:
        publish_label = "Veröffentlichen" if draft.event_id is None else "Änderungen speichern"
        row.add_item(wz.WizardButton(draft.id, "publish", publish_label, discord.ButtonStyle.success, emoji="🎉"))
    row.add_item(wz.WizardButton(draft.id, "edit_field", "Bild ändern", arg="image"))
    row.add_item(wz.WizardButton(draft.id, "cancel",
                                 "Abbrechen" if draft.event_id is None else "Bearbeitung verwerfen",
                                 discord.ButtonStyle.secondary))
    layout.add_item(row)
    _shorten(layout)
    # Das Thumbnail (Basis-Skript/Academy) braucht V2 nicht; nur das Skript-Bild mitschicken
    return layout, [f for f in files if f.filename == IMAGE_FILENAME]


RESULTS_PER_PAGE = 5  # Treffer als Abschnitte mit „Wählen“ (je 3 Komponenten, Grenze 40)


async def script_layout(bot: discord.Client, store, draft, notice: str | None = None):
    """Skriptwahl: ein Button öffnet den Skript-Dialog (Suche zuerst),
    Suchtreffer stehen seitenweise in der Karte."""
    from discord_ui import wizard as wz  # zirkulären Import vermeiden
    from events.schema import SCRIPT_BOTCSCRIPTS

    d, ui = draft.data, draft.ui or {}
    esc = discord.utils.escape_markdown
    results = ui.get("search_results") or []
    container = discord.ui.Container(accent_colour=0x5865F2)
    container.add_item(discord.ui.TextDisplay("### Skript wählen"))
    intro = ("Such dein Skript auf **botcscripts.com**, oder nimm ein Basis-Skript, "
             "die freie Wahl oder ein eigenes JSON.")
    if d.script:
        intro = f"Aktuell: **{esc(d.script.display_name)}**\n" + intro
    if notice:
        intro += f"\n{notice}"
    container.add_item(discord.ui.TextDisplay(intro))

    layout = discord.ui.LayoutView(timeout=None)
    if results:
        pages = (len(results) + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
        page = min(int(ui.get("page") or 0), pages - 1)
        first = page * RESULTS_PER_PAGE
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"**Treffer für „{esc(ui.get('query', ''))}“**\n-# nach Likes sortiert · Seite {page + 1} von {pages}"))
        for i, r in enumerate(results[first:first + RESULTS_PER_PAGE], start=first):
            line = f"**{esc(r['name'])}** v{esc(r['version'])}"
            details = [f"von {esc(r['author'])}" if r.get("author") else "",
                       f"{r['likes']} Likes" if r.get("likes") else ""]
            if r.get("type") == "Teensyville":
                details.append("Teensyville")
            if r.get("special"):
                details.append("⭐ Abweichung")
            details = [x for x in details if x]
            text = line + ("\n-# " + " · ".join(details) if details else "")
            container.add_item(discord.ui.Section(discord.ui.TextDisplay(text), accessory=wz.WizardButton(
                draft.id, "pick_result", "Wählen", discord.ButtonStyle.primary, arg=str(i))))
        layout.add_item(container)
        nav = discord.ui.ActionRow()
        back = wz.WizardButton(draft.id, "page", "◀ Zurück", arg=str(max(page - 1, 0)))
        back.item.disabled = page == 0
        forward = wz.WizardButton(draft.id, "page", "Weiter ▶", arg=str(page + 1))
        forward.item.disabled = page >= pages - 1
        nav.add_item(back)
        nav.add_item(forward)
        nav.add_item(wz.WizardButton(draft.id, "script_dialog", "Neue Suche", discord.ButtonStyle.primary))
        layout.add_item(nav)
    else:
        if ui.get("query") and not notice:
            container.add_item(discord.ui.TextDisplay(f"Keine Treffer für „{esc(ui['query'])}“."))
        layout.add_item(container)
        start = discord.ui.ActionRow()
        start.add_item(wz.WizardButton(draft.id, "script_dialog", "Skript suchen oder wählen",
                                       discord.ButtonStyle.primary))
        layout.add_item(start)

    versions = ui.get("versions") or []
    if versions and d.script is not None:
        version_row = discord.ui.ActionRow()
        version_row.add_item(wz.WizardSelect(draft.id, "version", [
            discord.SelectOption(label=f"v{v['version']}"[:100], value=f"{v['id']}|{v['version']}",
                                 default=v["version"] == d.script.version) for v in versions[:25]
        ], "Version wählen"))
        layout.add_item(version_row)

    end_row = discord.ui.ActionRow()
    if d.script is not None:
        end_row.add_item(wz.WizardButton(draft.id, "next", "Zur Zusammenfassung", discord.ButtonStyle.success))
        if d.script.kind == SCRIPT_BOTCSCRIPTS and not results:
            end_row.add_item(wz.WizardButton(draft.id, "versions", "Andere Version"))
    end_row.add_item(wz.WizardButton(draft.id, "cancel",
                                     "Abbrechen" if draft.event_id is None else "Bearbeitung verwerfen",
                                     discord.ButtonStyle.secondary))
    layout.add_item(end_row)
    _shorten(layout)
    return layout, []


async def image_layout(bot: discord.Client, store, draft, notice: str | None = None):
    """Bild-Seite: aus dem Skript, eigenes Bild oder keins; Vorschau groß darunter."""
    from discord_ui import wizard as wz  # zirkulären Import vermeiden
    from events.schema import IMAGE_AUTO, IMAGE_CUSTOM, IMAGE_NONE
    from logic.event_images import has_auto_image, render_image

    d = draft.data
    auto_possible = has_auto_image(d)
    mode_text = {
        IMAGE_AUTO: "Automatisch aus dem Skript" if auto_possible else "Automatisch (bei diesem Skript gibt es keins)",
        IMAGE_CUSTOM: "Eigenes Bild",
        IMAGE_NONE: "Kein Bild",
    }[d.image_mode]
    container = discord.ui.Container(accent_colour=WIZARD_COLOR)
    container.add_item(discord.ui.TextDisplay("### Bild"))
    text = f"Aktuell: **{mode_text}**"
    if notice:
        text += f"\n{notice}"
    container.add_item(discord.ui.TextDisplay(text))
    files = []
    image = await render_image(d)
    if image is not None:
        files.append(discord.File(io.BytesIO(image), filename=PREVIEW_IMAGE))
        container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{PREVIEW_IMAGE}")))

    def style(mode):
        return discord.ButtonStyle.primary if d.image_mode == mode else discord.ButtonStyle.secondary

    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    choices = discord.ui.ActionRow()
    choices.add_item(wz.WizardButton(draft.id, "img", "Aus dem Skript", style(IMAGE_AUTO), arg="auto",
                                     disabled=not auto_possible))
    choices.add_item(wz.WizardButton(draft.id, "upload_img", "Eigenes Bild hochladen", style(IMAGE_CUSTOM)))
    choices.add_item(wz.WizardButton(draft.id, "img", "Kein Bild", style(IMAGE_NONE), arg="none"))
    layout.add_item(choices)
    end_row = discord.ui.ActionRow()
    end_row.add_item(wz.WizardButton(draft.id, "next", "Zur Zusammenfassung", discord.ButtonStyle.success))
    end_row.add_item(wz.WizardButton(draft.id, "cancel",
                                     "Abbrechen" if draft.event_id is None else "Bearbeitung verwerfen",
                                     discord.ButtonStyle.secondary))
    layout.add_item(end_row)
    _shorten(layout)
    return layout, files


def text_layout(text: str) -> discord.ui.LayoutView:
    """Abschluss-Nachricht (abgebrochen, veröffentlicht) für eine V2-Nachricht."""
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(discord.ui.TextDisplay(text))
    return layout
