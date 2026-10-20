"""DM-Wizard: eine Nachricht pro Entwurf, die bei jedem Schritt bearbeitet wird.

Schritte: Skript → Einschätzung → Leitung & Details → Beschreibung → Bild → Vorschau.
Beim Bearbeiten eines Events startet der Wizard in der Vorschau; von dort springt man in einen
Schritt und mit „Weiter“ direkt zurück (Step-Suffix „:p“).

Alle Buttons und Selects sind DynamicItems mit der Entwurfs-ID im custom_id
(`wiz:<draft_id>:<aktion>[:<arg>]` bzw. `wizs:<draft_id>:<name>`). Damit funktionieren sie
nach einem Neustart weiter: Der Zustand liegt in der Datenbank, nicht im Arbeitsspeicher.
"""

from __future__ import annotations

import copy
import io
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

import discord

from discord_ui.members import actor_from_member, fetch_member
from events import guild_lock, permissions, service
from events.intake import parse_players
from events.parse import ParseError, format_termin, parse_start
from events.permissions import Actor
from events.rating import rate_script
from events.schema import (
    BERLIN_TZ,
    CAMERA_LABELS,
    DESCRIPTION_MAX_LENGTH,
    IMAGE_AUTO,
    IMAGE_CUSTOM,
    IMAGE_NONE,
    LEVELS,
    RATING_ANY,
    RATING_SOURCE_FIXED,
    RATING_SOURCE_MANUAL,
    RATING_SOURCE_RATER,
    SCRIPT_BASE,
    SCRIPT_BOTCSCRIPTS,
    SCRIPT_FREE,
    RATINGS,
    SCRIPT_UPLOAD,
    TITLE_MAX_LENGTH,
    EventData,
    Person,
    ScriptRef,
    missing_for_publish,
)
from events.store import Draft, Store
from events.templates import BASE3_FULL_NAMES, LABEL_EMOJI, RATING_WORDS, base_title, full_title
from logic import botcscripts
from logic.event_images import (
    IMAGE_FILENAME,
    ImageError,
    delete_custom_image,
    has_auto_image,
    render_image,
    save_custom_image,
)
from logic.event_builder import embed_color
from logic.script_cache import get_base_script, validate_script_json
from logic.script_flags import special_reasons

logger = logging.getLogger(__name__)

WIZARD_COLOR = 0x5865F2
SEARCH_LIMIT = 10
PREVIEW_IMAGE = "vorschau.png"

STEP_SCRIPT = "script"
STEP_DESCRIPTION = "description"
STEP_IMAGE = "image"
STEP_PREVIEW = "preview"
# Standardwerte (Dauer, Kamera, Co-ST, Erinnerungen …) werden nicht abgefragt, sondern nur in der
# Zusammenfassung geändert (Dalyan, 20.10.2026).
# Die Schwierigkeit legt der Algorithmus fest; geändert wird sie nur in der Zusammenfassung.
STEPS = (STEP_SCRIPT, STEP_DESCRIPTION, STEP_IMAGE, STEP_PREVIEW)
STEP_LABELS = {
    STEP_SCRIPT: "Skript",
    STEP_DESCRIPTION: "Beschreibung",
    STEP_IMAGE: "Bild",
    STEP_PREVIEW: "Zusammenfassung",
}
RETURN_SUFFIX = ":p"


def now() -> datetime:
    return datetime.now(BERLIN_TZ)


# ── Schritte und Navigation ──────────────────────────────────────────────────


def base_step(step: str) -> str:
    return step.split(":")[0]


def returns_to_preview(step: str) -> bool:
    return step.endswith(RETURN_SUFFIX)


def steps_for(data: EventData) -> list[str]:
    return list(STEPS)


def next_step(data: EventData, step: str) -> str:
    if returns_to_preview(step):
        return STEP_PREVIEW
    order = steps_for(data)
    current = base_step(step)
    i = order.index(current) if current in order else 0
    return order[min(i + 1, len(order) - 1)]


def previous_step(data: EventData, step: str) -> str:
    if returns_to_preview(step):
        return STEP_PREVIEW
    order = steps_for(data)
    current = base_step(step)
    i = order.index(current) if current in order else 0
    return order[max(i - 1, 0)]


def step_number(data: EventData, step: str) -> tuple[int, int]:
    order = steps_for(data)
    current = base_step(step)
    return (order.index(current) + 1 if current in order else 1), len(order)


# ── Kontext und Dispatch ─────────────────────────────────────────────────────


@dataclass
class WizardContext:
    bot: discord.Client
    store: Store
    draft: Draft
    actor: Actor
    member: discord.Member

    @property
    def data(self) -> EventData:
        return copy.deepcopy(self.draft.data)

    @property
    def ui(self) -> dict:
        return dict(self.draft.ui or {})

    def save(self, data: EventData | None = None, step: str | None = None) -> Draft:
        """Speichert Felder und/oder Schritt über den Service (Rechte, Validierung)."""
        self.draft = service.update_draft(self.store, self.draft, self.actor, data or self.draft.data,
                                          step or self.draft.step, now())
        return self.draft

    def set_ui(self, ui: dict):
        self.store.set_draft_ui(self.draft.id, ui)
        self.draft.ui = ui


Handler = Callable[[discord.Interaction, WizardContext, str | None], Awaitable[None]]
SelectHandler = Callable[[discord.Interaction, WizardContext, list[str]], Awaitable[None]]
_ACTIONS: dict[str, Handler] = {}
_SELECTS: dict[str, SelectHandler] = {}


def action(name: str):
    """Registriert eine Button-Aktion (`wiz:<id>:<name>[:<arg>]`)."""
    def deco(fn: Handler) -> Handler:
        _ACTIONS[name] = fn
        return fn
    return deco


def select_action(name: str):
    """Registriert eine Select-Aktion (`wizs:<id>:<name>`)."""
    def deco(fn: SelectHandler) -> SelectHandler:
        _SELECTS[name] = fn
        return fn
    return deco


def custom_id(draft_id: int, name: str, arg: str | None = None) -> str:
    return f"wiz:{draft_id}:{name}" + (f":{arg}" if arg else "")


async def load_context(interaction: discord.Interaction, draft_id: int) -> WizardContext | None:
    """Lädt Entwurf und Mitglied und prüft Besitz und Server-Lock. Antwortet selbst bei Fehlern."""
    store: Store = interaction.client.store
    draft = store.get_draft(draft_id)
    if draft is None:
        await _reply(interaction, "Diesen Entwurf gibt es nicht mehr. Starte mit `/botc` neu.")
        return None
    if draft.user_id != interaction.user.id:
        await _reply(interaction, "Das ist nicht dein Entwurf.")
        return None
    if not guild_lock.is_allowed(draft.guild_id):
        await _reply(interaction, "Dieser Bot ist auf dem Server des Entwurfs nicht freigeschaltet.")
        return None
    member = await fetch_member(interaction.client, draft.guild_id, interaction.user.id)
    if member is None:
        await _reply(interaction, "Du bist nicht mehr Mitglied des Servers, für den dieser Entwurf ist.")
        return None
    return WizardContext(interaction.client, store, draft, actor_from_member(member), member)


async def _reply(interaction: discord.Interaction, text: str):
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


async def _run(interaction: discord.Interaction, ctx: WizardContext, coro):
    """Führt eine Aktion aus; Fachfehler landen als Hinweis in der Wizard-Nachricht."""
    try:
        await coro
    except service.ServiceError as e:
        await show(interaction, ctx, notice=str(e))


class WizardButton(discord.ui.DynamicItem[discord.ui.Button],
                   template=r"wiz:(?P<draft_id>\d+):(?P<name>[a-z_]+)(?::(?P<arg>[\w\-]+))?"):
    def __init__(self, draft_id: int, name: str, label: str | None = None, style=discord.ButtonStyle.secondary,
                 arg: str | None = None, emoji=None, row: int | None = None, disabled: bool = False):
        super().__init__(discord.ui.Button(label=label, style=style, emoji=emoji, disabled=disabled,
                                           custom_id=custom_id(draft_id, name, arg)), row=row)
        self.draft_id, self.name, self.arg = draft_id, name, arg

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["draft_id"]), match["name"], item.label, item.style, match["arg"], item.emoji)

    async def callback(self, interaction: discord.Interaction):
        ctx = await load_context(interaction, self.draft_id)
        if ctx is None:
            return
        handler = _ACTIONS.get(self.name)
        if handler is None:
            await _reply(interaction, "Diese Aktion gibt es nicht mehr.")
            return
        await _run(interaction, ctx, handler(interaction, ctx, self.arg))


class WizardSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"wizs:(?P<draft_id>\d+):(?P<name>[a-z_]+)"):
    def __init__(self, draft_id: int, name: str, options: list[discord.SelectOption], placeholder: str,
                 row: int | None = None, min_values: int = 1, max_values: int = 1):
        super().__init__(discord.ui.Select(custom_id=f"wizs:{draft_id}:{name}", options=options,
                                           placeholder=placeholder, min_values=min_values,
                                           max_values=max_values), row=row)
        self.draft_id, self.name = draft_id, name

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Select, match: re.Match[str], /):
        return cls(int(match["draft_id"]), match["name"], item.options or [discord.SelectOption(label="-")],
                   item.placeholder or "", min_values=item.min_values, max_values=item.max_values)

    async def callback(self, interaction: discord.Interaction):
        ctx = await load_context(interaction, self.draft_id)
        if ctx is None:
            return
        handler = _SELECTS.get(self.name)
        values = list(interaction.data.get("values", []))  # bei Mehrfachauswahl auch leer möglich
        if handler is None:
            await _reply(interaction, "Diese Auswahl gibt es nicht mehr.")
            return
        await _run(interaction, ctx, handler(interaction, ctx, values))


# ── Darstellung ──────────────────────────────────────────────────────────────


def _esc(text: str) -> str:
    return discord.utils.escape_markdown(text)


def step_embed(draft: Draft, notice: str | None = None) -> discord.Embed:
    """Kasten für den aktuellen Schritt (unter der Zusammenfassung)."""
    n, total = step_number(draft.data, draft.step)
    label = STEP_LABELS[base_step(draft.step)]
    title = f"Schritt {n}/{total}: {label}" if base_step(draft.step) in STEPS else label
    embed = discord.Embed(title=title, color=WIZARD_COLOR)
    if notice:
        embed.description = notice
    embed.set_footer(text="Entwürfe bleiben 24 Stunden gespeichert. Die Buttons funktionieren auch später noch.")
    return embed


@dataclass
class Screen:
    embeds: list[discord.Embed]
    view: discord.ui.View
    files: list[discord.File]


def _nav(view: discord.ui.View, draft: Draft, row: int, next_label: str = "Weiter", next_disabled: bool = False,
         back: bool = True):
    view.add_item(WizardButton(draft.id, "next", next_label, discord.ButtonStyle.success, row=row,
                               disabled=next_disabled))
    if back and base_step(draft.step) != STEP_SCRIPT:
        view.add_item(WizardButton(draft.id, "back", "Zurück", row=row))
    _cancel_button(view, draft, row)


def _cancel_button(view: discord.ui.View, draft: Draft, row: int):
    label = "Abbrechen" if draft.event_id is None else "Bearbeitung verwerfen"
    view.add_item(WizardButton(draft.id, "cancel", label, discord.ButtonStyle.danger, row=row))


async def build_screen(bot: discord.Client, store: Store, draft: Draft, notice: str | None = None) -> Screen:
    guild = bot.get_guild(draft.guild_id)
    view = discord.ui.View(timeout=None)
    step = base_step(draft.step)
    if step not in STEPS:
        step = STEP_PREVIEW  # Entwurf aus einer älteren Version mit inzwischen entferntem Schritt
    if step == STEP_PREVIEW:
        embeds, files = await _screen_preview(bot, store, draft, view, guild.name if guild else None, notice)
        return Screen(embeds, view, files)
    summary = summary_fields(store, draft)
    heading = "Neue Runde" if draft.event_id is None else "Runde bearbeiten"
    summary.description = f"{heading} für **{_esc(guild.name)}**" if guild else heading
    head = step_embed(draft, notice)
    builder = {
        STEP_SCRIPT: _screen_script,
        STEP_DESCRIPTION: _screen_description,
        STEP_IMAGE: _screen_image,
        STEP_PREVIEW: _screen_preview,
    }[step]
    extra_embeds, files = await builder(bot, store, draft, head, view)
    return Screen([summary, head, *extra_embeds], view, files)


async def _screen_script(bot, store, draft: Draft, head: discord.Embed, view: discord.ui.View):
    d, ui = draft.data, draft.ui or {}
    text = "Welches Skript spielt ihr? Wähle ein Basis-Skript, such auf botcscripts.com oder lade ein Skript-JSON hoch."
    if d.script:
        text = f"Aktuell: **{_esc(d.script.display_name)}**. Du kannst es hier ändern.\n\n" + text
    head.add_field(name="Skript", value=text, inline=False)
    for key, name in BASE3_FULL_NAMES.items():
        view.add_item(WizardButton(draft.id, "pick", name, discord.ButtonStyle.primary, arg=key, row=0))
    view.add_item(WizardButton(draft.id, "pick", "Freie Skriptwahl", arg="free", row=0))
    view.add_item(WizardButton(draft.id, "search", "Auf botcscripts.com suchen", row=1))
    view.add_item(WizardButton(draft.id, "upload", "Skript-JSON hochladen", row=1))
    if d.script is not None and d.script.kind == SCRIPT_BOTCSCRIPTS:
        view.add_item(WizardButton(draft.id, "versions", "Andere Version", row=1))
        versions = ui.get("versions") or []
        if versions:
            options = [discord.SelectOption(label=f"v{v['version']}"[:100], value=f"{v['id']}|{v['version']}",
                                            default=v["version"] == d.script.version)
                       for v in versions[:25]]
            view.add_item(WizardSelect(draft.id, "version", options, "Version wählen", row=3))

    results = ui.get("search_results") or []
    if results:
        options = [
            discord.SelectOption(
                label=f"{r['name']} v{r['version']}"[:100],
                description=f"von {r['author']}"[:100] if r.get("author") else None,
                value=f"{r['id']}|{r['version']}",
            )
            for r in results[:25]
        ]
        view.add_item(WizardSelect(draft.id, "result", options, f"Treffer für „{ui.get('query', '')}“"[:150], row=2))
    elif ui.get("query"):
        head.add_field(name="Suche", value=f"Keine Treffer für „{_esc(ui['query'])}“.", inline=False)

    if d.script and returns_to_preview(draft.step):
        view.add_item(WizardButton(draft.id, "next", "Zurück zur Zusammenfassung", discord.ButtonStyle.success,
                                   row=4))
    _cancel_button(view, draft, row=4)
    return [], []


async def _screen_description(bot, store, draft: Draft, head: discord.Embed, view: discord.ui.View):
    d = draft.data
    if d.description.strip():
        text = "\n".join(f"> {line}" for line in d.description.strip().splitlines())
    else:
        text = "Noch keine Beschreibung. Erzähl den Mitspieler:innen kurz, worauf sie sich freuen können."
    if d.is_academy:
        text += "\n-# Bei Academy-Runden folgt darunter automatisch der feste Academy-Text."
    head.add_field(name="Beschreibung", value=text[:1024], inline=False)
    label = "Beschreibung bearbeiten" if d.description.strip() else "Beschreibung schreiben"
    view.add_item(WizardButton(draft.id, "describe", label, discord.ButtonStyle.primary, row=0))
    missing = not d.description.strip() and not d.is_academy
    _nav(view, draft, row=1, next_disabled=missing)
    return [], []


async def _screen_image(bot, store, draft: Draft, head: discord.Embed, view: discord.ui.View):
    d = draft.data
    auto_possible = has_auto_image(d)
    mode_text = {
        IMAGE_AUTO: "Automatisch aus dem Skript" if auto_possible else "Automatisch (bei diesem Skript gibt es keins)",
        IMAGE_CUSTOM: "Eigenes Bild",
        IMAGE_NONE: "Kein Bild",
    }[d.image_mode]
    head.add_field(name="Bild", value=f"{mode_text}\n-# Die Vorschau hängt an dieser Nachricht.", inline=False)
    view.add_item(WizardButton(draft.id, "img", "Aus dem Skript", arg="auto", row=0,
                               style=discord.ButtonStyle.primary if d.image_mode == IMAGE_AUTO else discord.ButtonStyle.secondary,
                               disabled=not auto_possible))
    view.add_item(WizardButton(draft.id, "upload_img", "Eigenes Bild hochladen", row=0,
                               style=discord.ButtonStyle.primary if d.image_mode == IMAGE_CUSTOM else discord.ButtonStyle.secondary))
    view.add_item(WizardButton(draft.id, "img", "Kein Bild", arg="none", row=0,
                               style=discord.ButtonStyle.primary if d.image_mode == IMAGE_NONE else discord.ButtonStyle.secondary))
    _nav(view, draft, row=1)

    image = await render_image(d)
    if image is None:
        return [], []
    preview = discord.Embed(color=WIZARD_COLOR).set_image(url=f"attachment://{PREVIEW_IMAGE}")
    return [preview], [discord.File(io.BytesIO(image), filename=PREVIEW_IMAGE)]


OPEN = "offen"
RATING_BUTTON_LABELS = {
    "green": "Grün", "yellow": "Gelb", "red": "Rot",
    "green_yellow": "Grün bis Gelb", "yellow_red": "Gelb bis Rot", "any": "Alle drei",
}


def rating_explanation(ui: dict, limit: int = 4) -> str:
    """Begründung vom ScriptRater: der Fließtext, wenn er geliefert wird, sonst die Kriterien."""
    detail = ui.get("rating_detail") or {}
    if detail.get("verdict"):
        text = _esc(detail["verdict"])
        if detail.get("tagline"):
            text += f"\n*{_esc(detail['tagline'])}*"  # zweite Zeile, wie auf der Ergebnisseite des ScriptRaters
        return text
    return "\n".join(f"• {_esc(r)}" for r in (detail.get("reasons") or [])[:limit])


def _code(text: str) -> str:
    """Wert als Code-Block wie in der Zusammenfassung des alten Branches."""
    return f"```{(text or '—').replace('`', 'ˋ')}```"


# „Feld ändern“: Wert → (Beschriftung, Nummern im Embed)
EDIT_CHOICES = {
    "title": "1 · Titel",
    "script": "2 · Skript",
    "rating": "3 · Schwierigkeit",
    "description": "4 · Beschreibung",
    "people": "5–6 · Storyteller:in & Co-Storyteller:in",
    "basics": "7, 10, 11 · Level, Max Spieler, Termin & Dauer",
    "labels": "8–9 · Labels (inkl. ⭐) & Kamera",
    "image": "12 · Bild",
}


def summary_fields(store: Store, draft: Draft) -> discord.Embed:
    """Nummerierte Zusammenfassung (Aufbau wie `_show_final_review` auf Branch event-creation)."""
    d, ui = draft.data, draft.ui or {}
    color = embed_color(d)
    embed = discord.Embed(title="Event-Zusammenfassung", color=color)

    embed.add_field(name="1 · Titel" + ("" if d.title.strip() else " (automatisch)"),
                    value=_code(full_title(d)), inline=False)

    s = d.script
    if s is None:
        script_info = OPEN
    else:
        script_info = s.display_name
        if s.author and s.kind != SCRIPT_BASE:
            script_info += f" von {s.author}"
        if s.version and s.kind != SCRIPT_BASE:
            script_info += f" · v{s.version}"
        if s.characters:
            script_info += f" · {len(s.characters)} Charaktere"
    embed.add_field(name="2 · Skript", value=_code(script_info), inline=True)

    if d.rating:
        if d.rating_source == RATING_SOURCE_FIXED:
            source = "Freie Skriptwahl" if s is not None and s.kind == SCRIPT_FREE else "Basis-Skript"
        else:
            source = {RATING_SOURCE_RATER: "laut ScriptRater", RATING_SOURCE_MANUAL: "von dir gewählt"}.get(
                d.rating_source, "")
        rating_text = f"**{RATING_WORDS[d.rating].capitalize()}** ({source})"
        if d.rating_source == RATING_SOURCE_RATER:
            rating_text += "\n" + rating_explanation(ui, limit=3)
    else:
        rating_text = OPEN
    if d.is_special:
        why = "; ".join(d.special_reasons) if d.special_reasons else "von dir gesetzt"
        rating_text += f"\n{LABEL_EMOJI['special']} Abweichung vom klassischen Clocktower: {_esc(why)}"
    quoted = "\n".join(f"> {line}" for line in rating_text.split("\n"))
    embed.add_field(name="3 · Einschätzung", value=quoted[:1024], inline=True)

    description = d.description.strip() or (OPEN if not d.is_academy else "—")
    if d.is_academy:
        description += "\n\n(+ fester Academy-Text)"
    if len(description) + 6 <= 1024:
        embed.add_field(name="4 · Beschreibung", value=_code(description), inline=False)
    else:
        embed.add_field(name="4 · Beschreibung", value=description[:1024], inline=False)

    embed.add_field(name="5 · Storyteller:in", value=_code(d.storyteller.name if d.storyteller else "—"), inline=True)
    embed.add_field(name="6 · Co-Storyteller:in",
                    value=_code(d.co_storyteller.name if d.co_storyteller else "—"), inline=True)
    embed.add_field(name="7 · Level", value=_code(d.level), inline=True)

    labels = [name for flag, name in ((d.is_casual, "Casual"), (d.is_academy, "Academy"),
                                      (d.is_recorded, "Aufzeichnung"), (d.is_special, "Abweichung")) if flag]
    embed.add_field(name="8 · Labels", value=_code(", ".join(labels) or "—"), inline=True)
    embed.add_field(name="9 · Kamera", value=_code(CAMERA_LABELS[d.camera]), inline=True)
    embed.add_field(name="10 · Max Spieler", value=_code(str(d.max_players)), inline=True)
    embed.add_field(name="11 · Termin",
                    value=_code(format_termin(d.start, d.duration_minutes) if d.start else "—"), inline=False)

    image_text = {IMAGE_AUTO: "Aus dem Skript" if has_auto_image(d) else "Keins (freie Skriptwahl)",
                  IMAGE_CUSTOM: "Eigenes Bild", IMAGE_NONE: "Kein Bild"}[d.image_mode]
    embed.add_field(name="12 · Bild", value=_code(image_text), inline=True)
    return embed


async def _screen_preview(bot, store, draft: Draft, view: discord.ui.View, guild_name: str | None,
                          notice: str | None):
    from discord_ui.event_post import build_files  # zirkulären Import vermeiden
    from logic.event_images import THUMB_FILENAME

    d = draft.data
    missing = missing_for_publish(d)
    embed = summary_fields(store, draft)
    lines = []
    if guild_name:
        lines.append(f"für **{_esc(guild_name)}**")
    lines.append("Schau in Ruhe drüber. Wenn alles passt: **Veröffentlichen**. "
                 "Zum Ändern wähle unten das Feld aus.")
    if missing:
        lines.append(f"**Es fehlt noch:** {', '.join(missing)}.")
    if notice:
        lines.append(notice)
    embed.description = "\n".join(lines)
    embed.set_footer(text="Entwürfe bleiben 24 Stunden gespeichert. Die Buttons funktionieren auch später noch.")

    files = await build_files(d)
    names = {f.filename for f in files}
    if IMAGE_FILENAME in names:
        embed.set_image(url=f"attachment://{IMAGE_FILENAME}")
    if THUMB_FILENAME in names:
        embed.set_thumbnail(url=f"attachment://{THUMB_FILENAME}")

    options = [discord.SelectOption(label=label, value=value) for value, label in EDIT_CHOICES.items()]
    view.add_item(WizardSelect(draft.id, "edit", options, "Feld ändern …", row=0))
    publish_label = "Veröffentlichen" if draft.event_id is None else "Änderungen speichern"
    view.add_item(WizardButton(draft.id, "publish", publish_label, discord.ButtonStyle.success, emoji="🎉",
                               row=1, disabled=bool(missing)))
    _cancel_button(view, draft, row=1)
    return [embed], files



def draft_creator_name(bot: discord.Client, draft: Draft) -> str:
    if draft.event_id is not None:
        event = bot.store.get_event(draft.event_id)
        if event is not None:
            return event.creator_name
    guild = bot.get_guild(draft.guild_id)
    member = guild.get_member(draft.user_id) if guild else None
    return member.display_name if member else (draft.data.storyteller.name if draft.data.storyteller else "")


async def send_wizard(bot: discord.Client, user: discord.abc.User, draft: Draft, intro: str | None = None):
    """Schickt die Wizard-Nachricht per DM. Wirft discord.Forbidden, wenn DMs geschlossen sind."""
    screen = await build_screen(bot, bot.store, draft)
    await user.send(content=intro, embeds=screen.embeds, view=screen.view, files=screen.files)


async def show(interaction: discord.Interaction, ctx: WizardContext, notice: str | None = None,
               content: str | None = None):
    """Zeigt den aktuellen Schritt in der Wizard-Nachricht, auf die geklickt wurde."""
    if not interaction.response.is_done():
        await interaction.response.defer()
    screen = await build_screen(ctx.bot, ctx.store, ctx.draft, notice)
    await interaction.edit_original_response(content=content, embeds=screen.embeds, view=screen.view,
                                             attachments=screen.files)


async def goto(interaction: discord.Interaction, ctx: WizardContext, step: str, data: EventData | None = None,
               notice: str | None = None):
    ctx.save(data, step)
    await show(interaction, ctx, notice)


# ── Aktionen: Navigation ─────────────────────────────────────────────────────


@action("next")
async def _next(interaction, ctx: WizardContext, arg):
    d = ctx.data
    step = base_step(ctx.draft.step)
    if step == STEP_SCRIPT and d.script is None:
        raise service.ServiceError("Wähle zuerst ein Skript.")
    if step == STEP_DESCRIPTION and not d.description.strip() and not d.is_academy:
        raise service.ServiceError("Schreib zuerst eine Beschreibung.")
    await goto(interaction, ctx, next_step(d, ctx.draft.step))


@action("back")
async def _back(interaction, ctx: WizardContext, arg):
    await goto(interaction, ctx, previous_step(ctx.data, ctx.draft.step))


@action("cancel")
async def _cancel(interaction, ctx: WizardContext, arg):
    d = ctx.draft.data
    if d.image_mode == IMAGE_CUSTOM and not _image_used_by_event(ctx, d.custom_image):
        delete_custom_image(d.custom_image)
    service.discard_draft(ctx.store, ctx.draft, ctx.actor)
    text = ("Event-Erstellung abgebrochen. Mit `/botc` kannst du jederzeit neu starten."
            if ctx.draft.event_id is None else "Bearbeitung verworfen, das Event bleibt unverändert.")
    await interaction.response.edit_message(content=text, embeds=[], view=None, attachments=[])


# ── Aktionen: Skript ─────────────────────────────────────────────────────────


def _after_script(ctx: WizardContext) -> str:
    """Nach der Skriptwahl: Beschreibung, beim Bearbeiten zurück zur Zusammenfassung."""
    return STEP_PREVIEW if returns_to_preview(ctx.draft.step) else STEP_DESCRIPTION


async def _set_script(interaction, ctx: WizardContext, script: ScriptRef, notice: str | None = None):
    d = ctx.data
    d.script = script
    d.rating, d.rating_source = None, None
    ui = ctx.ui
    for key in ("search_results", "query", "rating_detail"):
        ui.pop(key, None)

    if not interaction.response.is_done():
        await interaction.response.defer()
    result = await rate_script(script)
    if script.kind == SCRIPT_FREE:
        d.rating, d.rating_source = RATING_ANY, RATING_SOURCE_FIXED
    elif result is not None:
        d.rating = result.rating
        d.rating_source = RATING_SOURCE_FIXED if script.kind == SCRIPT_BASE else RATING_SOURCE_RATER
        ui["rating_detail"] = {"verdict": result.verdict, "tagline": result.tagline,
                               "headline": result.headline, "reasons": result.reasons}
    d.special_reasons = special_reasons(script, is_amnesiac=bool(result and result.is_amnesiac),
                                        rater_homebrew=bool(result and result.is_homebrew))
    d.is_special = bool(d.special_reasons)
    ctx.set_ui(ui)
    ctx.save(d)
    await goto(interaction, ctx, _after_script(ctx), notice=notice)


@action("pick")
async def _pick(interaction, ctx: WizardContext, arg):
    if arg == "free":
        await _set_script(interaction, ctx, ScriptRef(kind=SCRIPT_FREE))
        return
    base = get_base_script(arg or "")
    if base is None:
        raise service.ServiceError("Unbekanntes Basis-Skript.")
    await _set_script(interaction, ctx, ScriptRef(kind=SCRIPT_BASE, name=base["name"], author=base.get("author", ""),
                                                  base_key=arg, characters=list(base["characters"])))


@action("search")
async def _search(interaction, ctx: WizardContext, arg):
    await interaction.response.send_modal(SearchModal(ctx.draft.id, ctx.ui.get("query", "")))


async def _pick_botcscripts(interaction, ctx: WizardContext, value: str):
    script_id, _, version = value.partition("|")
    if not interaction.response.is_done():
        await interaction.response.defer()
    content = await botcscripts.download_script(script_id, version)
    if not content:
        raise service.ServiceError("Das Skript konnte nicht von botcscripts.com geladen werden. Versuch es nochmal.")
    parsed, error = validate_script_json(content)
    if error:
        raise service.ServiceError(error)
    await _set_script(interaction, ctx, ScriptRef(
        kind=SCRIPT_BOTCSCRIPTS, name=parsed["name"], author=parsed["author"], version=version,
        botcscripts_id=script_id, characters=parsed["characters"], content=content,
    ))


@select_action("result")
async def _result(interaction, ctx: WizardContext, values):
    await _pick_botcscripts(interaction, ctx, values[0])


@select_action("version")
async def _version(interaction, ctx: WizardContext, values):
    await _pick_botcscripts(interaction, ctx, values[0])


@action("versions")
async def _versions(interaction, ctx: WizardContext, arg):
    s = ctx.data.script
    await interaction.response.defer()
    found = await botcscripts.search_versions(s.name, s.author)
    ui = ctx.ui
    ui["versions"] = [{"id": v["botcscripts_id"], "version": v["version"]} for v in found if v.get("version")]
    ctx.set_ui(ui)
    notice = None if ui["versions"] else "Ich habe keine weiteren Versionen gefunden."
    await show(interaction, ctx, notice)


@action("upload")
async def _upload(interaction, ctx: WizardContext, arg):
    await interaction.response.send_modal(ScriptUploadModal(ctx.draft.id))


# ── Aktionen: Beschreibung und Bild ──────────────────────────────────────────


@action("describe")
async def _describe(interaction, ctx: WizardContext, arg):
    await interaction.response.send_modal(DescriptionModal(ctx.draft.id, ctx.draft.data.description))


def _image_used_by_event(ctx: WizardContext, name: str) -> bool:
    if not name or ctx.draft.event_id is None:
        return False
    event = ctx.store.get_event(ctx.draft.event_id)
    return event is not None and event.data.custom_image == name


def _drop_old_custom(ctx: WizardContext, d: EventData):
    if d.custom_image and not _image_used_by_event(ctx, d.custom_image):
        delete_custom_image(d.custom_image)
    d.custom_image = ""


@action("img")
async def _img(interaction, ctx: WizardContext, arg):
    d = ctx.data
    if arg == "auto":
        d.image_mode = IMAGE_AUTO
    elif arg == "none":
        d.image_mode = IMAGE_NONE
    else:
        return
    _drop_old_custom(ctx, d)
    ctx.save(d)
    await show(interaction, ctx)


@action("upload_img")
async def _upload_img(interaction, ctx: WizardContext, arg):
    await interaction.response.send_modal(ImageUploadModal(ctx.draft.id))


# ── Aktion: Veröffentlichen ──────────────────────────────────────────────────


@action("publish")
async def _publish(interaction, ctx: WizardContext, arg):
    from discord_ui.event_post import event_channel, images_changed, post_event, update_event_message

    # Vor dem Anlegen prüfen, sonst stünde ein Event in der Datenbank, das nie gepostet wird
    if ctx.draft.event_id is None and event_channel(ctx.bot, ctx.draft.guild_id) is None:
        raise service.ServiceError("Es ist kein Event-Channel eingerichtet. Ein Admin kann ihn mit "
                                   "`/set_event_channel` setzen, dein Entwurf bleibt so lange gespeichert.")
    await interaction.response.defer()
    old = ctx.store.get_event(ctx.draft.event_id) if ctx.draft.event_id is not None else None
    result = service.publish_draft(ctx.store, ctx.draft, ctx.actor, ctx.member.display_name, now())
    if result.created:
        msg = await post_event(ctx.bot, ctx.store, result.event)
        text = f"Dein Event ist online.\n{msg.jump_url}"
    else:
        msg = await update_event_message(ctx.bot, ctx.store, result.event,
                                         images_changed(old.data, result.event.data) if old else True)
        if old and old.data.custom_image and old.data.custom_image != result.event.data.custom_image:
            delete_custom_image(old.data.custom_image)
        text = f"Änderungen gespeichert.\n{msg.jump_url}" if msg else "Änderungen gespeichert."
    await interaction.edit_original_response(content=text, embeds=[], view=None, attachments=[])


# ── Aktion: Feld ändern (aus der Zusammenfassung) ────────────────────────────


@select_action("edit")
async def _edit(interaction, ctx: WizardContext, values):
    choice = values[0] if values else ""
    d = ctx.draft.data
    if choice in ("script", "rating", "image"):
        if choice == "rating":
            await interaction.response.send_modal(RatingModal(ctx.draft.id, d))
            return
        step = {"script": STEP_SCRIPT, "image": STEP_IMAGE}[choice]
        await goto(interaction, ctx, step + RETURN_SUFFIX)
    elif choice == "description":
        await interaction.response.send_modal(DescriptionModal(ctx.draft.id, d.description))
    elif choice == "title":
        await interaction.response.send_modal(TitleModal(ctx.draft.id, d))
    elif choice == "people":
        await interaction.response.send_modal(PeopleModal(ctx.draft.id, d))
    elif choice == "basics":
        await interaction.response.send_modal(BasicsModal(ctx.draft.id, d))
    elif choice == "labels":
        allow_academy = d.is_academy or permissions.can(
            ctx.actor, permissions.CREATE_ACADEMY, service.get_access(ctx.store, ctx.draft.guild_id))
        await interaction.response.send_modal(LabelsModal(ctx.draft.id, d, allow_academy))


# ── Modals ───────────────────────────────────────────────────────────────────


class _WizardModal(discord.ui.Modal):
    def __init__(self, draft_id: int, title: str):
        super().__init__(title=title, timeout=15 * 60)
        self.draft_id = draft_id

    async def on_submit(self, interaction: discord.Interaction):
        ctx = await load_context(interaction, self.draft_id)
        if ctx is None:
            return
        await _run(interaction, ctx, self.handle(interaction, ctx))

    async def handle(self, interaction: discord.Interaction, ctx: WizardContext):
        raise NotImplementedError

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.exception("Fehler im Wizard-Modal", exc_info=error)
        await _reply(interaction, "Da ist etwas schiefgelaufen. Versuch es bitte nochmal.")


class SearchModal(_WizardModal):
    def __init__(self, draft_id: int, query: str = ""):
        super().__init__(draft_id, "Skript suchen")
        self.query = discord.ui.TextInput(placeholder="Name des Skripts, z. B. Boozling", default=query or None,
                                          min_length=2, max_length=100)
        self.add_item(discord.ui.Label(text="Suchbegriff", description="Suche auf botcscripts.com",
                                       component=self.query))

    async def handle(self, interaction, ctx: WizardContext):
        query = self.query.value.strip()
        await interaction.response.defer()
        results = await botcscripts.search_scripts(query, limit=SEARCH_LIMIT)
        ui = ctx.ui
        ui["query"] = query
        ui["search_results"] = [
            {"id": r["botcscripts_id"], "version": r["version"], "name": r["name"], "author": r.get("author", "")}
            for r in results if r.get("botcscripts_id") and r.get("version")
        ]
        ctx.set_ui(ui)
        ctx.save(step=STEP_SCRIPT + (RETURN_SUFFIX if returns_to_preview(ctx.draft.step) else ""))
        await show(interaction, ctx)


class ScriptUploadModal(_WizardModal):
    def __init__(self, draft_id: int):
        super().__init__(draft_id, "Skript-JSON hochladen")
        self.file = discord.ui.FileUpload(required=True, min_values=1, max_values=1)
        self.add_item(discord.ui.Label(text="Skript-JSON", description="Die .json-Datei aus dem Script Tool",
                                       component=self.file))

    async def handle(self, interaction, ctx: WizardContext):
        import json

        attachment = self.file.values[0]
        if attachment.size > 1024 * 1024:
            raise service.ServiceError("Die Datei ist zu groß (maximal 1 MB).")
        try:
            content = json.loads(await attachment.read())
        except (ValueError, UnicodeDecodeError):
            raise service.ServiceError("Die Datei ist kein gültiges JSON.") from None
        parsed, error = validate_script_json(content)
        if error:
            raise service.ServiceError(error)
        await _set_script(interaction, ctx, ScriptRef(
            kind=SCRIPT_UPLOAD, name=parsed["name"], author=parsed["author"],
            characters=parsed["characters"], content=content,
        ))


class TitleModal(_WizardModal):
    """Eigener Titel. Leer = automatisch „{Skript} mit {ST}“. Die Symbole kommen immer davor."""

    def __init__(self, draft_id: int, data: EventData):
        super().__init__(draft_id, "Titel")
        self.text = discord.ui.TextInput(default=data.title or None, placeholder=base_title(data)[:100],
                                         required=False, max_length=TITLE_MAX_LENGTH)
        self.add_item(discord.ui.Label(text="Titel", description="Leer = automatischer Titel. "
                                       "Die Symbole (Labels, Schwierigkeit) kommen immer davor.", component=self.text))

    async def handle(self, interaction, ctx: WizardContext):
        d = ctx.data
        d.title = (self.text.value or "").strip()
        ctx.save(d)
        await show(interaction, ctx)


class RatingModal(_WizardModal):
    """Schwierigkeit selbst einstellen: eine Stufe oder ein Bereich."""

    def __init__(self, draft_id: int, data: EventData):
        super().__init__(draft_id, "Schwierigkeit")
        self.rating = discord.ui.RadioGroup()
        for value in RATINGS:
            self.rating.add_option(label=RATING_BUTTON_LABELS[value], value=value, default=value == data.rating)
        self.add_item(discord.ui.Label(text="Schwierigkeit", description="Eine Stufe oder einen Bereich wählen",
                                       component=self.rating))

    async def handle(self, interaction, ctx: WizardContext):
        d = ctx.data
        if self.rating.value in RATINGS and self.rating.value != d.rating:
            d.rating, d.rating_source = self.rating.value, RATING_SOURCE_MANUAL
            ctx.save(d)
        await show(interaction, ctx)


class PeopleModal(_WizardModal):
    """Storyteller:in und Co-Storyteller:in als einfacher Text (keine Mitgliedersuche)."""

    def __init__(self, draft_id: int, data: EventData):
        super().__init__(draft_id, "Storyteller:in & Co-Storyteller:in")
        self.st = discord.ui.TextInput(default=data.storyteller.name if data.storyteller else None,
                                       min_length=1, max_length=50)
        self.co = discord.ui.TextInput(default=data.co_storyteller.name if data.co_storyteller else None,
                                       required=False, max_length=50, placeholder="leer lassen, wenn es keine:n gibt")
        self.add_item(discord.ui.Label(text="Storyteller:in", component=self.st))
        self.add_item(discord.ui.Label(text="Co-Storyteller:in", component=self.co))

    async def handle(self, interaction, ctx: WizardContext):
        d = ctx.data
        st_name = self.st.value.strip()
        old_st = d.storyteller
        if old_st is not None and old_st.name == st_name:
            pass  # unverändert, User-ID bleibt
        elif st_name == ctx.member.display_name:
            d.storyteller = Person(name=st_name, user_id=ctx.member.id)
        else:
            d.storyteller = Person(name=st_name)
        co_name = (self.co.value or "").strip()
        if not co_name:
            d.co_storyteller = None
        elif d.co_storyteller is None or d.co_storyteller.name != co_name:
            d.co_storyteller = Person(name=co_name)
        ctx.save(d)
        await show(interaction, ctx)


class BasicsModal(_WizardModal):
    """Eckdaten aus dem /botc-Modal plus Dauer: Datum, Uhrzeit, Dauer, Max Spieler, Level."""

    def __init__(self, draft_id: int, data: EventData):
        super().__init__(draft_id, "Termin, Spieler & Level")
        start = data.start.astimezone(BERLIN_TZ) if data.start else None
        self.prefill = (f"{start:%d.%m.%Y}" if start else "", f"{start:%H:%M}" if start else "")
        self.date = discord.ui.TextInput(default=self.prefill[0] or None, placeholder="z. B. Sa, morgen, 24.10.",
                                         max_length=30)
        self.time = discord.ui.TextInput(default=self.prefill[1] or None, placeholder="z. B. 20:00", max_length=10)
        self.duration = discord.ui.TextInput(default=str(data.duration_minutes), max_length=4)
        self.players = discord.ui.TextInput(default=str(data.max_players), max_length=3)
        self.level = discord.ui.RadioGroup()
        for lvl in LEVELS:
            self.level.add_option(label=lvl, value=lvl, default=lvl == data.level)
        self.add_item(discord.ui.Label(text="Datum", component=self.date))
        self.add_item(discord.ui.Label(text="Uhrzeit", component=self.time))
        self.add_item(discord.ui.Label(text="Dauer in Minuten", component=self.duration))
        self.add_item(discord.ui.Label(text="Max. Spieler", description="1 bis 200", component=self.players))
        self.add_item(discord.ui.Label(text="Erfahrungslevel", component=self.level))

    async def handle(self, interaction, ctx: WizardContext):
        d = ctx.data
        try:
            # Unveränderter Termin bleibt, auch wenn er schon vorbei ist (Bearbeiten einer laufenden Runde)
            if (self.date.value.strip(), self.time.value.strip()) != self.prefill:
                d.start = parse_start(self.date.value, self.time.value, now())
            d.max_players = parse_players(self.players.value)
        except ParseError as e:
            raise service.ServiceError(str(e)) from None
        duration = self.duration.value.strip()
        if not duration.isdigit() or not 15 <= int(duration) <= 24 * 60:
            raise service.ServiceError("Die Dauer muss eine Zahl zwischen 15 und 1440 Minuten sein.")
        d.duration_minutes = int(duration)
        d.level = self.level.value or d.level
        ctx.save(d)
        await show(interaction, ctx)


class LabelsModal(_WizardModal):
    """Labels (Casual, Academy nur mit Berechtigung, Aufzeichnung) und Kamera."""

    def __init__(self, draft_id: int, data: EventData, allow_academy: bool):
        super().__init__(draft_id, "Labels & Kamera")
        self.options = discord.ui.CheckboxGroup(required=False, min_values=0)
        choices = [("casual", "Casual", data.is_casual), ("academy", "Academy", data.is_academy),
                   ("recorded", "Aufzeichnung", data.is_recorded),
                   ("special", "Abweichung vom klassischen Clocktower (⭐)", data.is_special)]
        for value, label, on in choices:
            if value == "academy" and not allow_academy:
                continue
            self.options.add_option(label=label, value=value, default=on)
        self.options.max_values = len(self.options.options)
        self.camera = discord.ui.RadioGroup()
        for key, label in CAMERA_LABELS.items():
            self.camera.add_option(label=label, value=key, default=key == data.camera)
        self.add_item(discord.ui.Label(text="Labels", component=self.options))
        self.add_item(discord.ui.Label(text="Kamera", component=self.camera))

    async def handle(self, interaction, ctx: WizardContext):
        d = ctx.data
        chosen = set(self.options.values)
        offered = {o.value for o in self.options.options}
        d.is_recorded = "recorded" in chosen
        d.is_special = "special" in chosen
        if "academy" in offered:
            d.is_academy = "academy" in chosen
        d.is_casual = "casual" in chosen
        d.camera = self.camera.value or d.camera
        ctx.save(d)  # prüft die Academy-Berechtigung
        await show(interaction, ctx)


class DescriptionModal(_WizardModal):
    def __init__(self, draft_id: int, current: str):
        super().__init__(draft_id, "Beschreibung")
        self.text = discord.ui.TextInput(style=discord.TextStyle.paragraph, default=current or None,
                                         placeholder="Worauf können sich die Mitspieler:innen freuen?",
                                         required=False, max_length=DESCRIPTION_MAX_LENGTH)
        self.add_item(discord.ui.Label(text="Beschreibung", description=f"Bis zu {DESCRIPTION_MAX_LENGTH} Zeichen",
                                       component=self.text))

    async def handle(self, interaction, ctx: WizardContext):
        d = ctx.data
        d.description = (self.text.value or "").strip()
        ctx.save(d)
        await show(interaction, ctx)


class ImageUploadModal(_WizardModal):
    def __init__(self, draft_id: int):
        super().__init__(draft_id, "Eigenes Bild")
        self.file = discord.ui.FileUpload(required=True, min_values=1, max_values=1)
        self.add_item(discord.ui.Label(text="Bild", description="PNG, JPG, WEBP oder GIF, bis 10 MB",
                                       component=self.file))

    async def handle(self, interaction, ctx: WizardContext):
        attachment = self.file.values[0]
        await interaction.response.defer()
        try:
            name = save_custom_image(await attachment.read())
        except ImageError as e:
            raise service.ServiceError(str(e)) from None
        d = ctx.data
        _drop_old_custom(ctx, d)
        d.image_mode, d.custom_image = IMAGE_CUSTOM, name
        ctx.save(d)
        await show(interaction, ctx)

