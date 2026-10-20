"""Experimentelle Darstellung des Wizards mit Discord Components V2 (/botc2).

Wie bei Apollo steht neben jedem Abschnitt der Zusammenfassung ein eigener „Bearbeiten“-Button.
Der Ablauf ist derselbe wie bei /botc: Die Seiten werden wie gewohnt gebaut und hier nur in ein
LayoutView übersetzt.

Grenzen von Discord: höchstens 40 Komponenten und 4000 Zeichen Text je Nachricht. Felder mit
demselben Bearbeitungs-Ziel (z. B. Storyteller und Co-ST) stehen deshalb in einem Abschnitt.
Eine V2-Nachricht kann keinen Text und keine Embeds mehr haben, nur Komponenten.
"""

from __future__ import annotations

import discord

SUMMARY_TITLE = "Event-Zusammenfassung"
TEXT_LIMIT = 4000

# Nummer im Feldnamen → Ziel von „Feld ändern“ (siehe wizard.EDIT_CHOICES)
FIELD_TARGETS = {
    "1": "title", "2": "script", "3": "rating", "4": "description",
    "5": "people", "6": "people", "7": "basics", "10": "basics", "11": "basics",
    "8": "labels", "9": "labels", "12": "image",
}


def _target(field_name: str) -> str | None:
    number = field_name.split("·")[0].strip()
    return FIELD_TARGETS.get(number)


def _field_text(field) -> str:
    return f"**{field.name}**\n{field.value}"


def to_layout(embeds: list[discord.Embed], view: discord.ui.View, draft_id: int,
              editable: bool = True) -> discord.ui.LayoutView:
    """Übersetzt Embeds + Buttons einer Wizard-Seite in ein LayoutView.

    `editable`: Bearbeiten-Buttons je Abschnitt (nur auf der Zusammenfassungs-Seite). Auf den
    Zwischenschritten steht die Zusammenfassung als ein Textblock, sonst reichen 40 Komponenten nicht.
    """
    from discord_ui.wizard import WizardButton  # zirkulären Import vermeiden

    layout = discord.ui.LayoutView(timeout=None)
    for embed in embeds:
        container = discord.ui.Container(accent_colour=embed.colour)
        if embed.title:
            container.add_item(discord.ui.TextDisplay(f"### {embed.title}"))
        if embed.description:
            container.add_item(discord.ui.TextDisplay(embed.description))

        if embed.title == SUMMARY_TITLE and not editable:
            container.add_item(discord.ui.TextDisplay("\n".join(_field_text(f) for f in embed.fields)))
        elif embed.title == SUMMARY_TITLE:
            # Felder nach Bearbeitungs-Ziel gruppieren (Reihenfolge des ersten Auftretens),
            # je Gruppe ein Abschnitt mit Bearbeiten-Button
            groups: dict[str | None, list] = {}
            for field in embed.fields:
                groups.setdefault(_target(field.name), []).append(field)
            for target, fields in groups.items():
                text = discord.ui.TextDisplay("\n".join(_field_text(f) for f in fields))
                if target is None:
                    container.add_item(text)
                    continue
                container.add_item(discord.ui.Section(text, accessory=WizardButton(
                    draft_id, "edit_field", "Bearbeiten", arg=target)))
        else:
            for field in embed.fields:
                container.add_item(discord.ui.TextDisplay(_field_text(field)))

        if embed.image and embed.image.url:
            container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(embed.image.url)))
        if embed.footer and embed.footer.text:
            container.add_item(discord.ui.TextDisplay(f"-# {embed.footer.text}"))
        layout.add_item(container)

    # Buttons und Selects der Seite, zeilenweise; das „Feld ändern“-Select entfällt (Buttons pro Abschnitt)
    rows: dict[int, list] = {}
    for item in view.children:
        if getattr(item, "custom_id", "").endswith(":edit"):
            continue
        # Selects speichern ihre Zeile anders als Buttons: am inneren Element nachsehen
        rows.setdefault(getattr(item, "item", item).row or 0, []).append(item)
    for row in sorted(rows):
        action_row = discord.ui.ActionRow()
        for item in rows[row]:
            action_row.add_item(item)
        layout.add_item(action_row)

    _shorten(layout)
    return layout


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
    """Zusammenfassung für /botc2 (Dalyan, 20.10.2026, nach Test auf dem Handy).

    Titel als Überschrift mit eigenem „Ändern“, danach je ein Abschnitt mit kleiner Überschrift:
    Beschreibung · Skript (mit Schwierigkeit) · Leitung · Auswahl (Labels, Level, Kamera) ·
    Termin (organisatorisch) · Bild (kleine Vorschau). Alle Buttons heißen „Ändern“; die Beschreibung
    öffnet einen Dialog nur mit dem Beschreibungsfeld. Gibt (LayoutView, Dateien) zurück.
    """
    from discord_ui import wizard as wz  # zirkulären Import vermeiden
    from discord_ui.event_post import build_files
    from events.parse import format_start
    from events.schema import CAMERA_LABELS, IMAGE_AUTO, IMAGE_CUSTOM, SCRIPT_BASE, missing_for_publish
    from events.templates import full_title
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
    results = (draft.ui or {}).get("search_results") or []
    if results:
        status += f"\n👇 Wähle unten deinen Treffer für „{esc((draft.ui or {}).get('query', ''))}“."
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
        rating_lines = [f"{wz.LABEL_EMOJI[d.rating]} {wz.RATING_WORDS[d.rating].capitalize()}"]
        if d.rating_source == wz.RATING_SOURCE_RATER:
            explanation = wz.rating_explanation(draft.ui or {}, limit=2)
            if explanation:
                rating_lines.append(explanation)
    else:
        rating_lines = [MISSING_MARK if s is not None else "Ergibt sich aus dem Skript"]
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
    if results:
        pick_row = discord.ui.ActionRow()
        options = []
        for r in results[:25]:
            details = [f"von {r['author']}" if r.get("author") else "", f"v{r['version']}",
                       "Teensyville" if r.get("type") == "Teensyville" else "", "⭐" if r.get("special") else ""]
            options.append(discord.SelectOption(label=r["name"][:100], value=f"{r['id']}|{r['version']}",
                                                description=" · ".join(x for x in details if x)[:100] or None))
        pick_row.add_item(wz.WizardSelect(draft.id, "result", options, "Treffer wählen …"))
        layout.add_item(pick_row)
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


SEARCH_RESULTS_SHOWN = 5  # Treffer als Abschnitte mit „Wählen“ (je 3 Komponenten, Grenze 40)


async def script_layout(bot: discord.Client, store, draft, notice: str | None = None):
    """Skriptwahl für /botc2: Basis-Skripte als Buttons, Suchtreffer als Liste mit „Wählen“."""
    from discord_ui import wizard as wz  # zirkulären Import vermeiden
    from events.schema import SCRIPT_BOTCSCRIPTS

    d, ui = draft.data, draft.ui or {}
    esc = discord.utils.escape_markdown
    container = discord.ui.Container(accent_colour=0x5865F2)
    container.add_item(discord.ui.TextDisplay("### Skript wählen"))
    intro = ("Wähle ein Basis-Skript oder die freie Wahl, such auf botcscripts.com oder lade ein Skript-JSON hoch.")
    if d.script:
        intro = f"Aktuell: **{esc(d.script.display_name)}**\n" + intro
    if notice:
        intro += f"\n{notice}"
    container.add_item(discord.ui.TextDisplay(intro))

    results = ui.get("search_results") or []
    if results:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(f"**Treffer für „{esc(ui.get('query', ''))}“**"))
        for i, r in enumerate(results[:SEARCH_RESULTS_SHOWN]):
            line = f"**{esc(r['name'])}** v{esc(r['version'])}"
            details = [f"von {esc(r['author'])}" if r.get("author") else ""]
            if r.get("type") == "Teensyville":
                details.append("Teensyville")
            if r.get("special"):
                details.append("⭐ Abweichung")
            details = [x for x in details if x]
            text = line + ("\n-# " + " · ".join(details) if details else "")
            container.add_item(discord.ui.Section(discord.ui.TextDisplay(text), accessory=wz.WizardButton(
                draft.id, "pick_result", "Wählen", discord.ButtonStyle.primary, arg=str(i))))
        if len(results) > SEARCH_RESULTS_SHOWN:
            container.add_item(discord.ui.TextDisplay(
                f"-# {len(results) - SEARCH_RESULTS_SHOWN} weitere Treffer. Nicht dabei? Such genauer."))
    elif ui.get("query"):
        container.add_item(discord.ui.TextDisplay(f"Keine Treffer für „{esc(ui['query'])}“."))

    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)

    base_row = discord.ui.ActionRow()
    for key, name in wz.BASE3_FULL_NAMES.items():
        base_row.add_item(wz.WizardButton(draft.id, "pick", name, discord.ButtonStyle.primary, arg=key))
    base_row.add_item(wz.WizardButton(draft.id, "pick", "Freie Skriptwahl", arg="free"))
    layout.add_item(base_row)

    tool_row = discord.ui.ActionRow()
    tool_row.add_item(wz.WizardButton(draft.id, "search", "Suchen"))
    tool_row.add_item(wz.WizardButton(draft.id, "upload", "JSON hochladen"))
    if d.script is not None:
        tool_row.add_item(wz.WizardButton(draft.id, "rating_dialog", "Schwierigkeit ändern"))
    if d.script is not None and d.script.kind == SCRIPT_BOTCSCRIPTS:
        tool_row.add_item(wz.WizardButton(draft.id, "versions", "Andere Version"))
    layout.add_item(tool_row)

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
    end_row.add_item(wz.WizardButton(draft.id, "cancel",
                                     "Abbrechen" if draft.event_id is None else "Bearbeitung verwerfen",
                                     discord.ButtonStyle.secondary))
    layout.add_item(end_row)
    _shorten(layout)
    return layout, []


def _people(people, name_for, empty: str = "–") -> str:
    """Namen als Text (keine Mentions), durch Komma getrennt."""
    if not people:
        return empty
    names = [discord.utils.escape_markdown((name_for(p) if name_for else None) or p.name) for p in people]
    return ", ".join(names)


def event_layout(data, creator_name: str, creator_avatar_url: str | None, rsvps, view_items: list,
                 has_image: bool, has_thumbnail: bool, created_ts: int, name_for=None) -> discord.ui.LayoutView:
    """Event-Post als V2-Karte (Test, nur Events aus /botc2).

    Die Übersicht liest diese Posts nicht aus Embeds, sondern direkt aus der Datenbank
    (logic/parser.parse_events mit lookup).
    """
    from events.schema import CAMERA_LABELS, SCRIPT_BASE
    from events.templates import BASE3_SCRIPT_URLS, full_description, full_title
    from logic.event_builder import (EMOJI_ACCEPTED, EMOJI_DECLINED, EMOJI_FILLER, EMOJI_TENTATIVE,
                                     embed_color, highlight_characters, npc_characters)
    from logic.event_images import IMAGE_FILENAME, THUMB_FILENAME

    esc = discord.utils.escape_markdown
    container = discord.ui.Container(accent_colour=embed_color(data))

    head = discord.ui.TextDisplay(f"## {esc(full_title(data))}")
    if has_thumbnail:
        container.add_item(discord.ui.Section(head, accessory=discord.ui.Thumbnail(f"attachment://{THUMB_FILENAME}")))
    else:
        container.add_item(head)

    if data.start:
        ts, end_ts = int(data.start.timestamp()), int(data.end.timestamp())
        termin = f"<t:{ts}:F> – <t:{end_ts}:t> · <t:{ts}:R>"
    else:
        termin = "–"
    st = esc(data.storyteller.name) if data.storyteller else "–"
    facts = [f"**Termin** {termin}", f"**Storytelling** {st}"
             + (f" · **Co-ST** {esc(data.co_storyteller.name)}" if data.co_storyteller else ""),
             f"**Level** {data.level} · **Kamera** {CAMERA_LABELS.get(data.camera, '–')}"]
    container.add_item(discord.ui.TextDisplay("\n".join(facts)))

    description = full_description(data)
    if description:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(description))

    s = data.script
    if s is not None:
        text = s.display_name
        if s.author and s.kind != SCRIPT_BASE:
            text += f" von {s.author}"
        if s.version and s.kind != SCRIPT_BASE:
            text += f" · v{s.version}"
        url = s.url or (BASE3_SCRIPT_URLS.get(s.base_key, "") if s.kind == SCRIPT_BASE else "")
        lines = [f"**Skript** [{esc(text)}]({url})" if url else f"**Skript** {esc(text)}"]
        if s.characters:
            npcs = npc_characters(s.characters)
            highlights = highlight_characters(s.characters)
            if npcs:
                lines.append(f"**NPCs** {npcs}")
            if highlights:
                lines.append(f"**Highlights** {highlights}")
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay("\n".join(lines)))
    if has_image:
        container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{IMAGE_FILENAME}")))

    # Anmeldungen: Namen als Text, kompakt durch Komma getrennt
    container.add_item(discord.ui.Separator())
    rsvp_lines = [f"{EMOJI_ACCEPTED} **Zusagen ({rsvps.accepted_count}/{data.max_players})** "
                  f"{_people(rsvps.players, name_for)}"]
    if rsvps.waitlist:
        rsvp_lines.append(f"**Warteliste** {_people(rsvps.waitlist, name_for)}")
    tentative = f"{EMOJI_FILLER} **Auffüller**" if data.is_academy else f"{EMOJI_TENTATIVE} **Vorläufig**"
    rsvp_lines.append(f"{tentative} {_people(rsvps.tentative, name_for)}")
    rsvp_lines.append(f"{EMOJI_DECLINED} **Abgelehnt** {_people(rsvps.declined, name_for)}")
    container.add_item(discord.ui.TextDisplay("\n".join(rsvp_lines)))

    footer = discord.ui.TextDisplay(f"-# Erstellt von {esc(creator_name)} · <t:{created_ts}:f>")
    if creator_avatar_url:
        container.add_item(discord.ui.Section(footer, accessory=discord.ui.Thumbnail(creator_avatar_url)))
    else:
        container.add_item(footer)

    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    row = discord.ui.ActionRow()
    for item in view_items:
        row.add_item(item)
    layout.add_item(row)
    _shorten(layout)
    return layout


def text_layout(text: str) -> discord.ui.LayoutView:
    """Abschluss-Nachricht (abgebrochen, veröffentlicht) für eine V2-Nachricht."""
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(discord.ui.TextDisplay(text))
    return layout
