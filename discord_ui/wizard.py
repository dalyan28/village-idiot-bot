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
from events import guild_lock, service
from events.parse import format_start
from events.permissions import Actor
from events.rating import rate_script
from events.schema import (
    BERLIN_TZ,
    CAMERA_LABELS,
    DESCRIPTION_MAX_LENGTH,
    DURATION_CHOICES,
    IMAGE_AUTO,
    IMAGE_CUSTOM,
    IMAGE_NONE,
    RATING_SOURCE_FIXED,
    RATING_SOURCE_MANUAL,
    RATING_SOURCE_RATER,
    SCRIPT_BASE,
    SCRIPT_BOTCSCRIPTS,
    SCRIPT_FREE,
    SCRIPT_UPLOAD,
    EventData,
    Person,
    ScriptRef,
    missing_for_publish,
)
from events.store import Draft, Store
from events.templates import BASE3_FULL_NAMES, LABEL_EMOJI, RATING_WORDS, full_title
from logic import botcscripts
from logic.event_images import (
    IMAGE_FILENAME,
    ImageError,
    delete_custom_image,
    has_auto_image,
    render_image,
    save_custom_image,
)
from logic.script_cache import get_base_script, validate_script_json

logger = logging.getLogger(__name__)

WIZARD_COLOR = 0x5865F2
SEARCH_LIMIT = 10
PREVIEW_IMAGE = "vorschau.png"

STEP_SCRIPT = "script"
STEP_RATING = "rating"
STEP_DETAILS = "details"
STEP_DESCRIPTION = "description"
STEP_IMAGE = "image"
STEP_PREVIEW = "preview"
STEPS = (STEP_SCRIPT, STEP_RATING, STEP_DETAILS, STEP_DESCRIPTION, STEP_IMAGE, STEP_PREVIEW)
STEP_LABELS = {
    STEP_SCRIPT: "Skript",
    STEP_RATING: "Einschätzung",
    STEP_DETAILS: "Leitung & Details",
    STEP_DESCRIPTION: "Beschreibung",
    STEP_IMAGE: "Bild",
    STEP_PREVIEW: "Vorschau",
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
    """Bei freier Skriptwahl gibt es keine Einschätzung."""
    if data.script is not None and data.script.kind == SCRIPT_FREE:
        return [s for s in STEPS if s != STEP_RATING]
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
        await show(interaction, ctx, notice=f"⚠️ {e}")


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
                 row: int | None = None):
        super().__init__(discord.ui.Select(custom_id=f"wizs:{draft_id}:{name}", options=options,
                                           placeholder=placeholder, min_values=1, max_values=1), row=row)
        self.draft_id, self.name = draft_id, name

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Select, match: re.Match[str], /):
        return cls(int(match["draft_id"]), match["name"], item.options or [discord.SelectOption(label="-")],
                   item.placeholder or "")

    async def callback(self, interaction: discord.Interaction):
        ctx = await load_context(interaction, self.draft_id)
        if ctx is None:
            return
        handler = _SELECTS.get(self.name)
        values = list(interaction.data.get("values", []))
        if handler is None or not values:
            await _reply(interaction, "Diese Auswahl gibt es nicht mehr.")
            return
        await _run(interaction, ctx, handler(interaction, ctx, values))


# ── Darstellung ──────────────────────────────────────────────────────────────


def _esc(text: str) -> str:
    return discord.utils.escape_markdown(text)


def summary_embed(draft: Draft, guild_name: str | None, notice: str | None = None) -> discord.Embed:
    """Kopf des Wizards: was bisher feststeht."""
    d = draft.data
    n, total = step_number(d, draft.step)
    title = "📝 Neue Runde" if draft.event_id is None else "✏️ Runde bearbeiten"
    embed = discord.Embed(title=f"{title} · Schritt {n}/{total}: {STEP_LABELS[base_step(draft.step)]}",
                          color=WIZARD_COLOR)
    lines = []
    if guild_name:
        lines.append(f"für **{_esc(guild_name)}**")
    if d.script:
        lines.append(f"**{_esc(full_title(d))}**")
    if notice:
        lines.append(f"\n{notice}")
    embed.description = "\n".join(lines) or None
    embed.add_field(name="Termin", value=format_start(d.start, d.duration_minutes) if d.start else "-", inline=False)
    embed.add_field(name="Max. Spieler", value=str(d.max_players), inline=True)
    embed.add_field(name="Level", value=d.level, inline=True)
    labels = [name for flag, name in ((d.is_academy, "Academy 🎓"), (d.is_casual, "Casual 🕊️"),
                                      (d.is_recorded, "Aufzeichnung 🎦")) if flag]
    embed.add_field(name="Labels", value=", ".join(labels) or "-", inline=True)
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
    head = summary_embed(draft, guild.name if guild else None, notice)
    view = discord.ui.View(timeout=None)
    step = base_step(draft.step)
    builder = {
        STEP_SCRIPT: _screen_script,
        STEP_RATING: _screen_rating,
        STEP_DETAILS: _screen_details,
        STEP_DESCRIPTION: _screen_description,
        STEP_IMAGE: _screen_image,
        STEP_PREVIEW: _screen_preview,
    }[step]
    extra_embeds, files = await builder(bot, store, draft, head, view)
    return Screen([head, *extra_embeds], view, files)


async def _screen_script(bot, store, draft: Draft, head: discord.Embed, view: discord.ui.View):
    d, ui = draft.data, draft.ui or {}
    text = "Welches Skript spielt ihr? Wähle ein Basis-Skript, such auf botcscripts.com oder lade ein Skript-JSON hoch."
    if d.script:
        text = f"Aktuell: **{_esc(d.script.display_name)}**. Du kannst es hier ändern.\n\n" + text
    head.add_field(name="Skript", value=text, inline=False)
    for key, name in BASE3_FULL_NAMES.items():
        view.add_item(WizardButton(draft.id, "pick", name, discord.ButtonStyle.primary, arg=key, row=0))
    view.add_item(WizardButton(draft.id, "pick", "Freie Skriptwahl", arg="free", row=0))
    view.add_item(WizardButton(draft.id, "search", "Auf botcscripts.com suchen", emoji="🔎", row=1))
    view.add_item(WizardButton(draft.id, "upload", "Skript-JSON hochladen", emoji="📄", row=1))

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
        view.add_item(WizardButton(draft.id, "next", "Zurück zur Vorschau", discord.ButtonStyle.success, row=3))
    _cancel_button(view, draft, row=3)
    return [], []


async def _screen_rating(bot, store, draft: Draft, head: discord.Embed, view: discord.ui.View):
    d, ui = draft.data, draft.ui or {}
    s = d.script
    info = f"**{_esc(s.display_name)}**"
    if s.kind != SCRIPT_BASE:
        if s.version:
            info += f" v{_esc(s.version)}"
        if s.author:
            info += f" von {_esc(s.author)}"
    if s.url:
        info += f"\n{s.url}"
    head.add_field(name="Skript", value=info, inline=False)

    if d.rating:
        word = RATING_WORDS[d.rating]
        source = {RATING_SOURCE_RATER: "laut ScriptRater", RATING_SOURCE_FIXED: "feste Einschätzung",
                  RATING_SOURCE_MANUAL: "von dir gewählt"}.get(d.rating_source, "")
        text = f"{LABEL_EMOJI[d.rating]} **{word}** ({source})"
        if d.is_homebrew:
            text += f"\n{LABEL_EMOJI['homebrew']} Enthält unbekannte Charaktere (Homebrew)."
        detail = ui.get("rating_detail") or {}
        if d.rating_source == RATING_SOURCE_RATER and detail.get("reasons"):
            text += "\n" + "\n".join(f"• {_esc(r)}" for r in detail["reasons"][:4])
    else:
        text = ("Ich konnte das Skript nicht automatisch einschätzen. Bitte wähle selbst, "
                "wie anspruchsvoll es ist.")
    head.add_field(name="Einschätzung", value=text[:1024], inline=False)

    for rating in ("green", "yellow", "red"):
        view.add_item(WizardButton(draft.id, "rate", RATING_WORDS[rating].capitalize(), arg=rating,
                                   emoji=LABEL_EMOJI[rating], row=0))
    if s.kind == SCRIPT_BOTCSCRIPTS:
        view.add_item(WizardButton(draft.id, "versions", "Andere Version", row=1))
        versions = ui.get("versions") or []
        if versions:
            options = [discord.SelectOption(label=f"v{v['version']}"[:100], value=f"{v['id']}|{v['version']}",
                                            default=v["version"] == s.version)
                       for v in versions[:25]]
            view.add_item(WizardSelect(draft.id, "version", options, "Version wählen", row=2))
    _nav(view, draft, row=3, next_disabled=d.rating is None)
    return [], []


async def _screen_details(bot, store, draft: Draft, head: discord.Embed, view: discord.ui.View):
    d, ui = draft.data, draft.ui or {}
    st = _esc(d.storyteller.name) if d.storyteller else "-"
    co = _esc(d.co_storyteller.name) if d.co_storyteller else "keine:r"
    head.add_field(name="Storytelling", value=st, inline=True)
    head.add_field(name="Co-Storytelling", value=co, inline=True)
    head.add_field(name="Dauer", value=f"{d.duration_minutes} Minuten", inline=True)
    head.add_field(name="Kamera", value=CAMERA_LABELS[d.camera], inline=True)

    durations = sorted(set(DURATION_CHOICES) | {d.duration_minutes})
    view.add_item(WizardSelect(draft.id, "duration", [
        discord.SelectOption(label=f"Dauer: {m // 60}:{m % 60:02d} h ({m} Min.)", value=str(m),
                             default=m == d.duration_minutes)
        for m in durations
    ], "Dauer", row=0))
    view.add_item(WizardSelect(draft.id, "camera", [
        discord.SelectOption(label=f"Kamera: {label}", value=key, default=key == d.camera)
        for key, label in CAMERA_LABELS.items()
    ], "Kamera", row=1))

    candidates = ui.get("person_candidates") or []
    if candidates:
        role = "Storyteller" if ui.get("person_role") == "st" else "Co-Storyteller"
        options = [discord.SelectOption(label=c["name"][:100], value=str(c["id"])) for c in candidates[:24]]
        options.append(discord.SelectOption(label=f"„{ui.get('person_query', '')}“ als Text übernehmen"[:100],
                                            value="text"))
        view.add_item(WizardSelect(draft.id, "person", options, f"{role} auswählen", row=2))
    else:
        view.add_item(WizardButton(draft.id, "person", "Storyteller ändern", arg="st", row=2))
        view.add_item(WizardButton(draft.id, "person", "Co-ST festlegen" if not d.co_storyteller else "Co-ST ändern",
                                   arg="co", row=2))
        if d.co_storyteller:
            view.add_item(WizardButton(draft.id, "remove_co", "Co-ST entfernen", row=2))
    _nav(view, draft, row=3)
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
    view.add_item(WizardButton(draft.id, "describe", label, discord.ButtonStyle.primary, emoji="✍️", row=0))
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
    view.add_item(WizardButton(draft.id, "upload_img", "Eigenes Bild hochladen", emoji="🖼️", row=0,
                               style=discord.ButtonStyle.primary if d.image_mode == IMAGE_CUSTOM else discord.ButtonStyle.secondary))
    view.add_item(WizardButton(draft.id, "img", "Kein Bild", arg="none", row=0,
                               style=discord.ButtonStyle.primary if d.image_mode == IMAGE_NONE else discord.ButtonStyle.secondary))
    _nav(view, draft, row=1)

    image = await render_image(d)
    if image is None:
        return [], []
    preview = discord.Embed(color=WIZARD_COLOR).set_image(url=f"attachment://{PREVIEW_IMAGE}")
    return [preview], [discord.File(io.BytesIO(image), filename=PREVIEW_IMAGE)]


async def _screen_preview(bot, store, draft: Draft, head: discord.Embed, view: discord.ui.View):
    from discord_ui.event_post import build_files  # zirkulären Import vermeiden
    from logic.event_builder import build_event_embed
    from logic.event_images import THUMB_FILENAME

    d = draft.data
    missing = missing_for_publish(d)
    head.add_field(
        name="Vorschau",
        value=("So sieht dein Event im Channel aus. Über „Schritt ändern“ kannst du alles anpassen."
               if not missing else f"Es fehlt noch: {', '.join(missing)}."),
        inline=False,
    )
    rsvps = service.RsvpLists([], [], [], [])
    if draft.event_id is not None:
        event = store.get_event(draft.event_id)
        if event is not None:
            rsvps = service.rsvp_lists(store, event)
    files = await build_files(d)
    names = {f.filename for f in files}
    embed = build_event_embed(d, draft_creator_name(bot, draft), rsvps,
                              thumbnail_url=f"attachment://{THUMB_FILENAME}" if THUMB_FILENAME in names else None)
    if IMAGE_FILENAME in names:
        embed.set_image(url=f"attachment://{IMAGE_FILENAME}")

    publish_label = "Veröffentlichen" if draft.event_id is None else "Änderungen speichern"
    view.add_item(WizardButton(draft.id, "publish", publish_label, discord.ButtonStyle.success, emoji="🎉",
                               row=0, disabled=bool(missing)))
    _cancel_button(view, draft, row=0)
    view.add_item(WizardSelect(draft.id, "jump", [
        discord.SelectOption(label=f"{i}. {STEP_LABELS[s]}", value=s)
        for i, s in enumerate(steps_for(d)[:-1], 1)
    ], "Schritt ändern …", row=1))
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
    if step == STEP_RATING and d.rating is None:
        raise service.ServiceError("Wähle zuerst eine Einschätzung.")
    if step == STEP_DESCRIPTION and not d.description.strip() and not d.is_academy:
        raise service.ServiceError("Schreib zuerst eine Beschreibung.")
    await goto(interaction, ctx, next_step(d, ctx.draft.step))


@action("back")
async def _back(interaction, ctx: WizardContext, arg):
    await goto(interaction, ctx, previous_step(ctx.data, ctx.draft.step))


@select_action("jump")
async def _jump(interaction, ctx: WizardContext, values):
    if values[0] not in STEPS:
        return
    await goto(interaction, ctx, values[0] + RETURN_SUFFIX)


@action("cancel")
async def _cancel(interaction, ctx: WizardContext, arg):
    d = ctx.draft.data
    if d.image_mode == IMAGE_CUSTOM and not _image_used_by_event(ctx, d.custom_image):
        delete_custom_image(d.custom_image)
    service.discard_draft(ctx.store, ctx.draft, ctx.actor)
    text = ("Event-Erstellung abgebrochen. ✌️ Mit `/botc` kannst du jederzeit neu starten."
            if ctx.draft.event_id is None else "Bearbeitung verworfen, das Event bleibt unverändert.")
    await interaction.response.edit_message(content=text, embeds=[], view=None, attachments=[])


# ── Aktionen: Skript ─────────────────────────────────────────────────────────


def _after_script(ctx: WizardContext) -> str:
    """Nach der Skriptwahl: Einschätzung (außer freie Wahl), beim Bearbeiten zurück zur Vorschau."""
    d = ctx.draft.data
    if d.script.kind == SCRIPT_FREE:
        return STEP_PREVIEW if returns_to_preview(ctx.draft.step) else STEP_DETAILS
    return STEP_RATING + (RETURN_SUFFIX if returns_to_preview(ctx.draft.step) else "")


async def _set_script(interaction, ctx: WizardContext, script: ScriptRef, notice: str | None = None):
    d = ctx.data
    d.script = script
    d.rating, d.rating_source, d.is_homebrew = None, None, False
    ui = ctx.ui
    for key in ("search_results", "query", "versions", "rating_detail"):
        ui.pop(key, None)

    if not interaction.response.is_done():
        await interaction.response.defer()
    result = await rate_script(script)
    if result is not None:
        d.rating = result.rating
        d.is_homebrew = result.is_homebrew
        d.rating_source = RATING_SOURCE_FIXED if script.kind == SCRIPT_BASE else RATING_SOURCE_RATER
        ui["rating_detail"] = {"headline": result.headline, "reasons": result.reasons}
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


@action("rate")
async def _rate(interaction, ctx: WizardContext, arg):
    if arg not in ("green", "yellow", "red"):
        return
    d = ctx.data
    d.rating, d.rating_source = arg, RATING_SOURCE_MANUAL
    ctx.save(d)
    await show(interaction, ctx)


# ── Aktionen: Details ────────────────────────────────────────────────────────


@select_action("duration")
async def _duration(interaction, ctx: WizardContext, values):
    d = ctx.data
    d.duration_minutes = int(values[0])
    ctx.save(d)
    await show(interaction, ctx)


@select_action("camera")
async def _camera(interaction, ctx: WizardContext, values):
    d = ctx.data
    d.camera = values[0]
    ctx.save(d)
    await show(interaction, ctx)


@action("person")
async def _person(interaction, ctx: WizardContext, arg):
    await interaction.response.send_modal(PersonModal(ctx.draft.id, arg or "co"))


@action("remove_co")
async def _remove_co(interaction, ctx: WizardContext, arg):
    d = ctx.data
    d.co_storyteller = None
    ctx.save(d)
    await show(interaction, ctx)


def _apply_person(ctx: WizardContext, choice: str):
    """Übernimmt die Auswahl aus der Mitgliedersuche ("text" = Suchbegriff als Freitext)."""
    ui = ctx.ui
    role = ui.get("person_role", "co")
    if choice == "text":
        person = Person(name=ui.get("person_query", "").strip())
    else:
        chosen = next((c for c in ui.get("person_candidates", []) if str(c["id"]) == choice), None)
        if chosen is None:
            return
        person = Person(name=chosen["name"], user_id=int(chosen["id"]))
    for key in ("person_candidates", "person_role", "person_query"):
        ui.pop(key, None)
    ctx.set_ui(ui)
    d = ctx.data
    if person.name:
        if role == "st":
            d.storyteller = person
        else:
            d.co_storyteller = person
    ctx.save(d)


@select_action("person")
async def _person_pick(interaction, ctx: WizardContext, values):
    _apply_person(ctx, values[0])
    await show(interaction, ctx)


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
        text = f"Dein Event ist online! 🎉\n{msg.jump_url}"
    else:
        msg = await update_event_message(ctx.bot, ctx.store, result.event,
                                         images_changed(old.data, result.event.data) if old else True)
        if old and old.data.custom_image and old.data.custom_image != result.event.data.custom_image:
            delete_custom_image(old.data.custom_image)
        text = f"Änderungen gespeichert. ✏️\n{msg.jump_url}" if msg else "Änderungen gespeichert. ✏️"
    await interaction.edit_original_response(content=text, embeds=[], view=None, attachments=[])


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


class PersonModal(_WizardModal):
    def __init__(self, draft_id: int, role: str):
        super().__init__(draft_id, "Storyteller ändern" if role == "st" else "Co-Storyteller festlegen")
        self.role = role
        self.name = discord.ui.TextInput(placeholder="Anfang des Namens auf dem Server", min_length=1, max_length=50)
        self.add_item(discord.ui.Label(text="Name", description="Ich suche passende Mitglieder auf dem Server",
                                       component=self.name))

    async def handle(self, interaction, ctx: WizardContext):
        query = self.name.value.strip()
        await interaction.response.defer()
        guild = ctx.bot.get_guild(ctx.draft.guild_id)
        members = []
        if guild is not None:
            try:
                members = await guild.query_members(query=query, limit=20)
            except (discord.ClientException, TimeoutError):
                members = []
        ui = ctx.ui
        ui["person_role"] = self.role
        ui["person_query"] = query
        ui["person_candidates"] = [{"id": m.id, "name": m.display_name} for m in members if not m.bot]
        ctx.set_ui(ui)
        if not ui["person_candidates"]:
            _apply_person(ctx, "text")
            await show(interaction, ctx, notice=f"Kein Mitglied „{_esc(query)}“ gefunden, ich habe den Namen als "
                                                f"Text übernommen.")
            return
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

