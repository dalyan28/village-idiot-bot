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
    "Beschreibung": ("descriptive", "Beschreibung schreiben"),
    "Storyteller": ("descriptive", "Storyteller eintragen"),
    "Schwierigkeit": ("rating", "Schwierigkeit wählen"),
    "Termin": ("frame", "Termin eintragen"),
}


def _missing_buttons(missing: list[str]) -> list[tuple[str, str]]:
    """Ein Button je Ziel (Beschreibung und Storyteller teilen sich einen Dialog), höchstens 4."""
    buttons, seen = [], set()
    for name in missing:
        target, label = MISSING_TARGETS.get(name, ("descriptive", f"{name} ergänzen"))
        if target not in seen:
            seen.add(target)
            buttons.append((target, label))
    return buttons[:4]


def _line(label: str, value: str) -> str:
    return f"**{label}** {value}"


async def summary_layout(bot: discord.Client, store, draft, notice: str | None = None):
    """Zusammenfassung für /botc2: fünf Abschnitte mit je einem Button, kompakte Zeilen.

    Gruppen nach Dalyan (20.10.2026): Beschreibendes · Skript & Schwierigkeit ·
    Auswahl (Labels, Level, Kamera) · Termin & Rahmen (organisatorisch) · Bild.
    Gibt (LayoutView, Dateien) zurück.
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

    def section(text: str, target: str, label: str = "Bearbeiten") -> discord.ui.Section:
        return discord.ui.Section(discord.ui.TextDisplay(text),
                                  accessory=wz.WizardButton(draft.id, "edit_field", label, arg=target))

    container = discord.ui.Container(accent_colour=embed_color(d))
    heading = "Neue Runde" if draft.event_id is None else "Runde bearbeiten"
    container.add_item(discord.ui.TextDisplay(f"{heading} für **{esc(guild.name)}**" if guild else heading))
    container.add_item(discord.ui.TextDisplay(f"## {esc(full_title(d))}"))
    missing = missing_for_publish(d)
    status = (f"🔴 **Bevor du veröffentlichen kannst, fehlt noch:** {', '.join(missing)}" if missing
              else "Alles da. Wenn es passt: **Veröffentlichen**.")
    if notice:
        status += f"\n{notice}"
    container.add_item(discord.ui.TextDisplay(status))

    # 1. Beschreibendes
    description = esc(d.description.strip()) if d.description.strip() else MISSING_MARK
    if d.is_academy:
        description += "\n-# Darunter folgt der feste Academy-Text."
    co = esc(d.co_storyteller.name) if d.co_storyteller else "–"
    st = esc(d.storyteller.name) if d.storyteller else MISSING_MARK
    title_hint = "" if d.title.strip() else " (automatisch)"
    container.add_item(discord.ui.Separator())
    container.add_item(section("\n".join([
        _line("Titel", esc(d.title.strip() or wz.base_title(d)) + title_hint),
        _line("Storyteller", st) + " · " + _line("Co-ST", co),
        _line("Beschreibung", ""), description,
    ]), "descriptive"))

    # 2. Skript & Schwierigkeit
    s = d.script
    if s is None:
        script_line = MISSING_MARK
    else:
        script_line = esc(s.display_name)
        if s.author and s.kind != SCRIPT_BASE:
            script_line += f" von {esc(s.author)}"
        if s.version and s.kind != SCRIPT_BASE:
            script_line += f" · v{esc(s.version)}"
        if s.teensy:
            script_line += " · Teensyville"
    lines = [_line("Skript", script_line)]
    if d.rating:
        lines.append(_line("Schwierigkeit", f"{wz.LABEL_EMOJI[d.rating]} {wz.RATING_WORDS[d.rating].capitalize()}"))
        if d.rating_source == wz.RATING_SOURCE_RATER:
            explanation = wz.rating_explanation(draft.ui or {}, limit=2)
            if explanation:
                lines.append("\n".join(f"> {line}" for line in explanation.split("\n")))
    else:
        lines.append(_line("Schwierigkeit", MISSING_MARK))
    if d.is_special:
        why = "; ".join(d.special_reasons) if d.special_reasons else "von dir gesetzt"
        lines.append(f"⭐ {esc(why)}")
    container.add_item(discord.ui.Separator())
    container.add_item(section("\n".join(lines), "script", "Ändern"))

    # 3. Auswahl: Labels, Level, Kamera
    labels = [name for flag, name in ((d.is_academy, "🎓 Academy"), (d.is_casual, "🕊️ Casual"),
                                      (d.is_recorded, "🎦 Aufzeichnung"), (d.is_special, "⭐ Abweichung")) if flag]
    container.add_item(discord.ui.Separator())
    container.add_item(section("\n".join([
        _line("Labels", ", ".join(labels) or "–"),
        _line("Level", d.level) + " · " + _line("Kamera", CAMERA_LABELS[d.camera]),
    ]), "selection"))

    # 4. Termin & Rahmen (organisatorisch)
    container.add_item(discord.ui.Separator())
    container.add_item(section("\n".join([
        _line("Termin", format_start(d.start, d.duration_minutes) if d.start else MISSING_MARK),
        _line("Spieler", f"max. {d.max_players}"),
    ]), "frame"))

    # 5. Bild
    files = await build_files(d)
    image_text = {IMAGE_AUTO: "Aus dem Skript" if has_auto_image(d) else "Keins (freie Skriptwahl)",
                  IMAGE_CUSTOM: "Eigenes Bild"}.get(d.image_mode, "Kein Bild")
    container.add_item(discord.ui.Separator())
    container.add_item(section(_line("Bild", image_text), "image", "Ändern"))
    if any(f.filename == IMAGE_FILENAME for f in files):
        container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{IMAGE_FILENAME}")))
    container.add_item(discord.ui.TextDisplay("-# Entwürfe bleiben 24 Stunden gespeichert."))

    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    row = discord.ui.ActionRow()
    if missing:
        # Statt Veröffentlichen: je fehlender Angabe ein roter Button, der direkt dorthin führt
        for target, label in _missing_buttons(missing):
            row.add_item(wz.WizardButton(draft.id, "edit_field", label, discord.ButtonStyle.danger, arg=target))
    else:
        publish_label = "Veröffentlichen" if draft.event_id is None else "Änderungen speichern"
        row.add_item(wz.WizardButton(draft.id, "publish", publish_label, discord.ButtonStyle.success, emoji="🎉"))
    row.add_item(wz.WizardButton(draft.id, "cancel",
                                 "Abbrechen" if draft.event_id is None else "Bearbeitung verwerfen",
                                 discord.ButtonStyle.secondary))
    layout.add_item(row)
    _shorten(layout)
    # Das Thumbnail (Basis-Skript/Academy) braucht V2 nicht; nur das Skript-Bild mitschicken
    return layout, [f for f in files if f.filename == IMAGE_FILENAME]


def text_layout(text: str) -> discord.ui.LayoutView:
    """Abschluss-Nachricht (abgebrochen, veröffentlicht) für eine V2-Nachricht."""
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(discord.ui.TextDisplay(text))
    return layout
