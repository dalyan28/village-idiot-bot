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
        rows.setdefault(item.row or 0, []).append(item)
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


def text_layout(text: str) -> discord.ui.LayoutView:
    """Abschluss-Nachricht (abgebrochen, veröffentlicht) für eine V2-Nachricht."""
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(discord.ui.TextDisplay(text))
    return layout
