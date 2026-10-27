"""DM-Wizard: eine Nachricht pro Entwurf (Components V2), die bei jedem Schritt bearbeitet wird.

Ablauf: Skript wählen → Zusammenfassung. Alles Weitere ändert man in der Zusammenfassung per
Dialog („Ändern“ je Abschnitt); fehlende Pflichtangaben stehen dort als rote Buttons.
Die Seiten Skript und Bild können auch aus der Zusammenfassung heraus geöffnet werden; sie
führen danach dorthin zurück (Step-Suffix „:p“). Beim Bearbeiten startet der Wizard in der
Zusammenfassung.

Alle Buttons und Selects sind DynamicItems mit der Entwurfs-ID im custom_id
(`wiz:<draft_id>:<aktion>[:<arg>]` bzw. `wizs:<draft_id>:<name>`). Damit funktionieren sie
nach einem Neustart weiter: Der Zustand liegt in der Datenbank, nicht im Arbeitsspeicher.
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import discord

from discord_ui.layout_v2 import (cancelled_layout, chat_wait_layout, confirm_layout, image_layout, kind_layout, script_layout,
                                  summary_layout, text_layout)
from discord_ui.members import actor_from_member, fetch_member
from events import guild_lock, permissions, service
from events.intake import parse_players
from events.parse import ParseError, format_start, parse_start
from events.permissions import Actor
from events.rating import RatingUnavailable, rate_script
from events.schema import (
    BERLIN_TZ,
    CO_ST_LABELS,
    CO_ST_NO,
    CAMERA_LABELS,
    DEFAULT_MAX_PLAYERS,
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
    TEENSY_MAX_PLAYERS,
    TITLE_MAX_LENGTH,
    EventData,
    Person,
    ScriptRef,
)
from events.store import Draft, Store
from events.templates import BASE3_FULL_NAMES, base_title
from logic import botcscripts
from logic.event_images import MAX_UPLOAD_BYTES, ImageError, delete_custom_image, save_custom_image
from logic.script_cache import get_base_script, validate_script_json
from logic.script_flags import is_teensy, special_reasons
from testserver import hooks as testserver_hooks  # TESTSERVER

logger = logging.getLogger(__name__)

SEARCH_LIMIT = 50  # nach Likes sortiert; die Skript-Karte blättert in Seiten durch (layout_v2.RESULTS_PER_PAGE)
OUTAGE_SEARCH = ("botcscripts.com antwortet gerade nicht (zu langsam oder nicht erreichbar). Du kannst ein Basis-Skript oder die freie Skriptwahl nehmen, dein Skript als JSON hochladen oder es später erneut versuchen.")

STEP_SCRIPT = "script"
STEP_IMAGE = "image"
STEP_PREVIEW = "preview"
BASE_PLAYERS_KEY = "base_players"  # Spielerzahl beim Anlegen (eigener Standard bzw. 12), siehe _set_script
STEP_KIND = "kind"  # Zwischenschritt nach „Skriptwahl überspringen“: Clocktower oder anderes Event?
# Standardwerte (Dauer, Kamera, Co-ST, Level …) werden nicht abgefragt, sondern nur in der
# Zusammenfassung geändert (Dalyan, 20.10.2026). Die Schwierigkeit legt der Algorithmus fest.
RETURN_SUFFIX = ":p"


def now() -> datetime:
    return datetime.now(BERLIN_TZ)


# ── Schritte und Navigation ──────────────────────────────────────────────────


def base_step(step: str) -> str:
    return step.split(":")[0]


def returns_to_preview(step: str) -> bool:
    return step.endswith(RETURN_SUFFIX)


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
        await _reply(interaction, "Diesen Entwurf gibt es nicht mehr. Mit `/botc` kannst du neu beginnen.")
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
        testserver_hooks.wizard_button(ctx, self.name, self.arg)  # TESTSERVER
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
        testserver_hooks.wizard_select(ctx, self.name, values)  # TESTSERVER
        await _run(interaction, ctx, handler(interaction, ctx, values))


# ── Darstellung ──────────────────────────────────────────────────────────────


def _esc(text: str) -> str:
    return discord.utils.escape_markdown(text)


# Symbole der Server-Regeln bleiben überall stehen (Dalyan, 20.10.2026)
RATING_BUTTON_LABELS = {
    "green": "💚 Grün", "yellow": "🟡 Gelb", "red": "🟥 Rot",
    "green_yellow": "💚/🟡 Grün bis Gelb", "yellow_red": "🟡/🟥 Gelb bis Rot", "any": "💚/🟡/🟥 Alle drei",
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


def draft_creator_name(bot: discord.Client, draft: Draft) -> str:
    if draft.event_id is not None:
        event = bot.store.get_event(draft.event_id)
        if event is not None:
            return event.creator_name
    guild = bot.get_guild(draft.guild_id)
    member = guild.get_member(draft.user_id) if guild else None
    return member.display_name if member else (draft.data.storyteller.name if draft.data.storyteller else "")


async def render(bot: discord.Client, draft: Draft, notice: str | None = None):
    """Karte für den aktuellen Schritt: (LayoutView, Dateien)."""
    if (draft.ui or {}).get(CONFIRM_KEY):  # Termin oder Dauer ungewöhnlich: erst nachfragen
        return confirm_layout(bot, draft), []
    if (draft.ui or {}).get(AWAIT_KEY):  # wartet auf Titel/Beschreibung als Chat-Nachricht
        return chat_wait_layout(bot, draft, notice), []
    step = base_step(draft.step)
    if step == STEP_KIND:
        return kind_layout(bot, draft), []
    if step == STEP_SCRIPT:
        return await script_layout(bot, bot.store, draft, notice)
    if step == STEP_IMAGE:
        return await image_layout(bot, bot.store, draft, notice)
    # Zusammenfassung, auch für Entwürfe aus älteren Versionen mit inzwischen entfernten Schritten
    return await summary_layout(bot, bot.store, draft, notice)


async def send_wizard(bot: discord.Client, user: discord.abc.User, draft: Draft, intro: str | None = None):
    """Schickt die Wizard-Nachricht per DM. Wirft discord.Forbidden, wenn DMs geschlossen sind."""
    layout, files = await render(bot, draft, intro)
    await user.send(view=layout, files=files)


async def show(interaction: discord.Interaction, ctx: WizardContext, notice: str | None = None):
    """Zeigt den aktuellen Schritt in der Wizard-Nachricht, auf die geklickt wurde."""
    if not interaction.response.is_done():
        await interaction.response.defer()
    layout, files = await render(ctx.bot, ctx.draft, notice)
    await interaction.edit_original_response(view=layout, attachments=files)


async def busy(interaction: discord.Interaction, ctx: WizardContext, text: str):
    """Zeigt während einer Wartezeit eine Statusmeldung statt der Karte (ohne Buttons, gegen Doppelklicks).

    Die nächste Anzeige (show) ersetzt sie wieder; bei einem Fehler zeigt sie die Erklärung.
    """
    if not interaction.response.is_done():
        await interaction.response.defer()
    message = f"**Einen Moment …**\n{text}"
    try:
        await interaction.edit_original_response(view=text_layout(message), attachments=[])
    except discord.HTTPException:
        logger.debug("Statusmeldung konnte nicht angezeigt werden", exc_info=True)


async def goto(interaction: discord.Interaction, ctx: WizardContext, step: str, data: EventData | None = None,
               notice: str | None = None):
    ctx.save(data, step)
    await show(interaction, ctx, notice)


# ── Aktionen: Navigation ─────────────────────────────────────────────────────


@action("next")
async def _next(interaction, ctx: WizardContext, arg):
    """„Zur Zusammenfassung“ von der Skript- oder Bild-Seite."""
    if base_step(ctx.draft.step) == STEP_SCRIPT and ctx.data.script is None:
        raise service.ServiceError("Wähle zuerst ein Skript.")
    await goto(interaction, ctx, STEP_PREVIEW)


@action("cancel")
async def _cancel(interaction, ctx: WizardContext, arg):
    """Neue Runde: Abbrechen behält den Entwurf (Dalyan, 26.10.2026), Löschen geht ausdrücklich danach.
    Bearbeitung eines Events: die Änderungen werden verworfen, das Event bleibt unverändert."""
    if ctx.draft.event_id is None:
        await interaction.response.edit_message(view=cancelled_layout(ctx.draft), attachments=[])
        return
    await _discard(interaction, ctx, arg)


@action("discard")
async def _discard(interaction, ctx: WizardContext, arg):
    d = ctx.draft.data
    if d.image_mode == IMAGE_CUSTOM and not _image_used_by_event(ctx, d.custom_image):
        delete_custom_image(d.custom_image)
    service.discard_draft(ctx.store, ctx.draft, ctx.actor)
    text = ("Entwurf gelöscht. Mit `/botc` kannst du jederzeit neu starten."
            if ctx.draft.event_id is None else "Bearbeitung verworfen, das Event bleibt unverändert.")
    await interaction.response.edit_message(view=text_layout(text), attachments=[])


@action("resume")
async def _resume(interaction, ctx: WizardContext, arg):
    """„Weitermachen“ nach dem Abbrechen: dieselbe Karte wie vorher."""
    await show(interaction, ctx)


# ── Aktionen: Skript ─────────────────────────────────────────────────────────


async def _set_script(interaction, ctx: WizardContext, script: ScriptRef, notice: str | None = None):
    d = ctx.data
    was_teensy = bool(d.script and d.script.teensy)
    d.script = script
    d.is_other_event = False
    d.rating, d.rating_source = None, None
    # Teensyville setzt immer 6; danach lässt sich die Zahl im Entwurf ändern (Dalyan, 26.10.2026).
    # Ohne Teensyville wieder der Startwert des Entwurfs (eigener Standard bzw. 12).
    base_players = ctx.ui.get(BASE_PLAYERS_KEY, DEFAULT_MAX_PLAYERS)
    if script.teensy and not was_teensy and d.max_players != TEENSY_MAX_PLAYERS:
        d.max_players = TEENSY_MAX_PLAYERS
        notice = notice or f"Das Skript ist ein Teensyville, deshalb sind maximal {TEENSY_MAX_PLAYERS} Spieler eingestellt."
    elif was_teensy and not script.teensy and d.max_players == TEENSY_MAX_PLAYERS:
        d.max_players = base_players
    ui = ctx.ui
    for key in ("search_results", "query", "page", "rating_detail"):
        ui.pop(key, None)

    if script.kind in (SCRIPT_BOTCSCRIPTS, SCRIPT_UPLOAD):
        await busy(interaction, ctx, f"Der ScriptRater schätzt „{_esc(script.display_name)}“ ein.")
    elif not interaction.response.is_done():
        await interaction.response.defer()
    ui.pop("rating_error", None)
    try:
        result = await rate_script(script)
    except RatingUnavailable as e:
        result = None
        ui["rating_error"] = ("Der ScriptRater antwortet gerade nicht rechtzeitig" if e.timeout
                              else "Der ScriptRater ist gerade nicht erreichbar") + \
            ". Bitte stell die Schwierigkeit selbst ein."
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
    await goto(interaction, ctx, STEP_PREVIEW, notice=notice)


@action("pick")
async def _pick(interaction, ctx: WizardContext, arg):
    await _pick_base(interaction, ctx, arg or "")


async def _pick_base(interaction, ctx: WizardContext, key: str):
    """Basis-Skript (trouble_brewing, …) oder „free“ für die freie Skriptwahl."""
    if key == "free":
        await _set_script(interaction, ctx, ScriptRef(kind=SCRIPT_FREE))
        return
    base = get_base_script(key)
    if base is None:
        raise service.ServiceError("Unbekanntes Basis-Skript.")
    await _set_script(interaction, ctx, ScriptRef(kind=SCRIPT_BASE, name=base["name"], author=base.get("author", ""),
                                                  base_key=key, characters=list(base["characters"])))


@action("skip_script")
async def _skip_script(interaction, ctx: WizardContext, arg):
    """Skriptwahl überspringen: erst fragen, ob es überhaupt eine Clocktower-Runde ist (Dalyan, 20.10.2026)."""
    await goto(interaction, ctx, STEP_KIND)


@action("later_script")
async def _later_script(interaction, ctx: WizardContext, arg):
    """Clocktower-Runde, Skript später: zur Zusammenfassung, dort steht das Skript als fehlend."""
    d = ctx.data
    d.is_other_event = False
    await goto(interaction, ctx, STEP_PREVIEW, d)


@action("script_back")
async def _script_back(interaction, ctx: WizardContext, arg):
    await goto(interaction, ctx, STEP_SCRIPT)


@action("other_event")
async def _other_event(interaction, ctx: WizardContext, arg):
    """Event ohne Clocktower: alles Clocktower-Spezifische zurücksetzen."""
    d = ctx.data
    d.is_other_event = True
    d.script, d.rating, d.rating_source = None, None, None
    d.is_special, d.special_reasons = False, []
    d.is_academy = d.is_casual = d.is_recorded = False
    d.camera = EventData().camera
    d.co_st_status, d.co_st_note = CO_ST_NO, ""
    ui = ctx.ui
    for key in ("search_results", "query", "page", "rating_detail", "rating_error", "versions"):
        ui.pop(key, None)
    ctx.set_ui(ui)
    await goto(interaction, ctx, STEP_PREVIEW, d)


@action("script_dialog")
async def _script_dialog(interaction, ctx: WizardContext, arg):
    await interaction.response.send_modal(ScriptModal(ctx.draft.id, ctx.ui.get("query", "")))


@action("page")
async def _page(interaction, ctx: WizardContext, arg):
    """Suchtreffer blättern."""
    ui = ctx.ui
    ui["page"] = max(0, int(arg)) if (arg or "").isdigit() else 0
    ctx.set_ui(ui)
    await show(interaction, ctx)


async def _run_search(interaction, ctx: WizardContext, query: str):
    """Suche auf botcscripts.com; Treffer (nach Likes sortiert) landen in der Skript-Karte."""
    await busy(interaction, ctx, f"Ich suche „{_esc(query)}“ auf botcscripts.com.")
    try:
        results = await botcscripts.search_scripts(query, limit=SEARCH_LIMIT)
    except botcscripts.BotcScriptsUnavailable:
        raise service.ServiceError(OUTAGE_SEARCH) from None
    ui = ctx.ui
    ui["query"] = query
    ui["page"] = 0
    ui["search_results"] = [_result_entry(r) for r in results if r.get("botcscripts_id") and r.get("version")]
    ctx.set_ui(ui)
    step = ctx.draft.step
    if not step.startswith(STEP_SCRIPT):
        # aus der Zusammenfassung heraus gesucht: Treffer zeigen, nach der Wahl zurück
        step = STEP_SCRIPT + (RETURN_SUFFIX if step == STEP_PREVIEW or returns_to_preview(step) else "")
    ctx.save(step=step)
    notice = None if ui["search_results"] else f"Keine Treffer für „{_esc(query)}“. Versuch es mit einem anderen Suchbegriff."
    await show(interaction, ctx, notice)


def _result_entry(r: dict) -> dict:
    """Suchtreffer, wie er in drafts.ui gespeichert wird."""
    return {"id": r["botcscripts_id"], "version": r["version"], "name": r["name"], "author": r.get("author", ""),
            "type": r.get("script_type", ""), "likes": r.get("likes") or 0,
            "special": bool(special_reasons(ScriptRef(kind=SCRIPT_BOTCSCRIPTS, characters=r.get("characters") or [],
                                                      content=r.get("content"))))}


async def _pick_botcscripts(interaction, ctx: WizardContext, value: str):
    script_id, _, version = value.partition("|")
    ui = ctx.ui
    known = [*(ui.get("search_results") or []), *(ui.get("versions") or [])]
    script_type = next((r.get("type") for r in known if r["id"] == script_id and r["version"] == version), "")
    await busy(interaction, ctx, "Ich lade das Skript von botcscripts.com.")
    content = await botcscripts.download_script(script_id, version)
    if not content:
        raise service.ServiceError(
            "Das Skript konnte nicht von botcscripts.com geladen werden (zu langsam oder nicht erreichbar). "
            "Versuch es später erneut oder lade dein Skript als JSON hoch.")
    parsed, error = validate_script_json(content)
    if error:
        raise service.ServiceError(error)
    script = ScriptRef(kind=SCRIPT_BOTCSCRIPTS, name=parsed["name"], author=parsed["author"], version=version,
                       botcscripts_id=script_id, characters=parsed["characters"], content=content)
    script.teensy = is_teensy(script, script_type or None)
    await _set_script(interaction, ctx, script)


@action("pick_result")
async def _pick_result(interaction, ctx: WizardContext, arg):
    results = ctx.ui.get("search_results") or []
    if not (arg or "").isdigit() or int(arg) >= len(results):
        raise service.ServiceError("Diesen Treffer gibt es nicht mehr. Bitte starte eine neue Suche.")
    r = results[int(arg)]
    await _pick_botcscripts(interaction, ctx, f"{r['id']}|{r['version']}")


@select_action("version")
async def _version(interaction, ctx: WizardContext, values):
    await _pick_botcscripts(interaction, ctx, values[0])


@action("versions")
async def _versions(interaction, ctx: WizardContext, arg):
    s = ctx.data.script
    await busy(interaction, ctx, f"Ich suche weitere Versionen von „{_esc(s.name)}“ auf botcscripts.com.")
    try:
        found = await botcscripts.search_versions(s.name, s.author)
    except botcscripts.BotcScriptsUnavailable:
        raise service.ServiceError(OUTAGE_SEARCH) from None
    ui = ctx.ui
    ui["versions"] = [{"id": v["botcscripts_id"], "version": v["version"], "type": v.get("script_type", "")}
                      for v in found if v.get("version")]
    ctx.set_ui(ui)
    notice = None if ui["versions"] else "Keine weiteren Versionen gefunden."
    await show(interaction, ctx, notice)


# ── Aktionen: Beschreibung und Bild ──────────────────────────────────────────


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
    await busy(interaction, ctx, "Ich veröffentliche dein Event.")
    old = ctx.store.get_event(ctx.draft.event_id) if ctx.draft.event_id is not None else None
    result = service.publish_draft(ctx.store, ctx.draft, ctx.actor, ctx.member.display_name, now())
    if result.created:
        msg = await post_event(ctx.bot, ctx.store, result.event)
        text = f"Dein Event ist veröffentlicht.\n{msg.jump_url}"
    else:
        msg = await update_event_message(ctx.bot, ctx.store, result.event,
                                         images_changed(old.data, result.event.data) if old else True)
        if old and old.data.custom_image and old.data.custom_image != result.event.data.custom_image:
            delete_custom_image(old.data.custom_image)
        text = f"Änderungen gespeichert.\n{msg.jump_url}" if msg else "Änderungen gespeichert."
    await interaction.edit_original_response(view=text_layout(text), attachments=[])


# ── Aktion: Feld ändern (aus der Zusammenfassung) ────────────────────────────


@action("edit_field")
async def _edit_field(interaction, ctx: WizardContext, arg):
    """„Bearbeiten“-Button neben einem Abschnitt der Zusammenfassung."""
    await open_edit(interaction, ctx, arg or "")


@action("fix_field")
async def _fix_field(interaction, ctx: WizardContext, arg):
    """Roter Button für eine fehlende Angabe. Eigene Aktion, weil Discord doppelte custom_ids ablehnt."""
    await open_edit(interaction, ctx, arg or "")


async def open_edit(interaction, ctx: WizardContext, choice: str):
    d = ctx.draft.data
    if choice == "kind":  # „Art“ beim Event ohne Clocktower: doch eine Runde, also zur Skriptwahl
        nd = ctx.data
        nd.is_other_event = False
        await goto(interaction, ctx, STEP_SCRIPT, nd)
        return
    if choice == "script":
        await interaction.response.send_modal(ScriptModal(ctx.draft.id, ctx.ui.get("query", "")))
        return
    if choice == "rating":
        await interaction.response.send_modal(RatingModal(ctx.draft.id, d))
    elif choice == "image":
        await goto(interaction, ctx, STEP_IMAGE + RETURN_SUFFIX)
    elif choice == "description":
        # Leer: direkt im Chat schreiben; sonst Dialog mit dem bisherigen Text (Dalyan, 20.10.2026)
        if not d.description.strip():
            await _start_chat_input(interaction, ctx, "description")
        else:
            await interaction.response.send_modal(DescriptionModal(ctx.draft.id, d.description))
    elif choice == "title":
        # Ein automatischer Titel zählt nicht als leer; leer ist er nur beim Event ohne Clocktower
        if d.is_other_event and not d.title.strip():
            await _start_chat_input(interaction, ctx, "title")
        else:
            await interaction.response.send_modal(TitleModal(ctx.draft.id, d))
    elif choice == "people":
        await interaction.response.send_modal(PeopleModal(ctx.draft.id, d))
    elif choice == "selection":
        await interaction.response.send_modal(SelectionModal(ctx.draft.id, d, _allow_academy(ctx)))
    elif choice == "frame":
        await interaction.response.send_modal(FrameModal(ctx.draft.id, d))


def _allow_academy(ctx: WizardContext) -> bool:
    return ctx.draft.data.is_academy or permissions.can(
        ctx.actor, permissions.CREATE_ACADEMY, service.get_access(ctx.store, ctx.draft.guild_id))


# ── Modals ───────────────────────────────────────────────────────────────────


class _WizardModal(discord.ui.Modal):
    def __init__(self, draft_id: int, title: str):
        super().__init__(title=title, timeout=15 * 60)
        self.draft_id = draft_id

    async def on_submit(self, interaction: discord.Interaction):
        ctx = await load_context(interaction, self.draft_id)
        if ctx is None:
            return
        testserver_hooks.wizard_modal(ctx, self)  # TESTSERVER
        await _run(interaction, ctx, self.handle(interaction, ctx))

    async def handle(self, interaction: discord.Interaction, ctx: WizardContext):
        raise NotImplementedError

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.exception("Fehler im Wizard-Modal", exc_info=error)
        await _reply(interaction, "Ein Fehler ist aufgetreten. Bitte versuch es erneut.")


SKIP_SCRIPT = "skip"


class ScriptModal(_WizardModal):
    """Skript per Dialog, die Suche steht ganz oben (Dalyan, 20.10.2026).

    Geprüft wird von unten nach oben (Dalyan, 20.10.2026): angehängte Datei, dann Auswahl, zuletzt
    die Suche. Wer erst etwas eintippt und sich dann für ein Basis-Skript entscheidet, landet nicht
    wegen eines Suchrests in der Suche.
    """

    def __init__(self, draft_id: int, query: str = ""):
        super().__init__(draft_id, "Skript wählen")
        self.query = discord.ui.TextInput(required=False, max_length=100, default=query or None,
                                          placeholder="Name des Skripts, z. B. Boozling")
        self.kind = discord.ui.RadioGroup(required=False)
        for value, label in BASE3_FULL_NAMES.items():
            self.kind.add_option(label=label, value=value)
        # Basis-Skripte und „ohne festes Skript“ getrennt (Dalyan, 20.10.2026)
        self.open = discord.ui.RadioGroup(required=False)
        self.open.add_option(label="Freie Skriptwahl", value="free",
                             description="Ich weiß noch nicht, was ich leiten werde.")
        self.open.add_option(label="Diesen Schritt überspringen", value=SKIP_SCRIPT,
                             description="z. B. für ein Event ohne Clocktower")
        self.file = discord.ui.FileUpload(required=False, min_values=0, max_values=1)
        self.add_item(discord.ui.Label(text="Auf botcscripts.com suchen",
                                       description="Suchbegriff eintragen und abschicken",
                                       component=self.query))
        self.add_item(discord.ui.Label(text="Basis-Skript", component=self.kind))
        self.add_item(discord.ui.Label(text="Ohne festes Skript", component=self.open))
        self.add_item(discord.ui.Label(text="Oder eigenes Skript-JSON anhängen",
                                       component=self.file))

    async def handle(self, interaction, ctx: WizardContext):
        if self.file.values:
            await _set_script(interaction, ctx, await _script_from_upload(self.file.values[0]))
            return
        choice = self.kind.value or self.open.value or ""
        if choice == SKIP_SCRIPT:
            await goto(interaction, ctx, STEP_KIND)
            return
        if choice:
            await _pick_base(interaction, ctx, choice)
            return
        query = (self.query.value or "").strip()
        if len(query) < 2:
            raise service.ServiceError("Gib einen Suchbegriff (mindestens 2 Zeichen) ein oder wähl ein Skript aus.")
        await _run_search(interaction, ctx, query)


async def _script_from_upload(attachment: discord.Attachment) -> ScriptRef:
    import json

    if attachment.size > 1024 * 1024:
        raise service.ServiceError("Die Datei ist zu groß (maximal 1 MB).")
    try:
        content = json.loads(await attachment.read())
    except (ValueError, UnicodeDecodeError):
        raise service.ServiceError("Die Datei ist kein gültiges JSON.") from None
    parsed, error = validate_script_json(content)
    if error:
        raise service.ServiceError(error)
    script = ScriptRef(kind=SCRIPT_UPLOAD, name=parsed["name"], author=parsed["author"],
                       characters=parsed["characters"], content=content)
    script.teensy = is_teensy(script)
    return script


# ── Titel/Beschreibung als Chat-Nachricht ─────────────────────────────────────
# Im Dialog gibt es keine Emoji-Auswahl; im Chat schon (Dalyan, 20.10.2026). Der Entwurf merkt sich in
# drafts.ui, dass er auf die nächste DM-Nachricht wartet, und welche Wizard-Nachricht danach zu
# aktualisieren ist (commands/botc.py, on_message).
AWAIT_KEY = "await_text"
CHAT_FIELDS = {"title": "Titel", "description": "Beschreibung"}
CHAT_OPTION = "chat"


def _chat_checkbox() -> discord.ui.CheckboxGroup:
    group = discord.ui.CheckboxGroup(required=False, min_values=0, max_values=1)
    group.add_option(label="Lieber im Chat schreiben", value=CHAT_OPTION,
                     description="z. B. für Emojis; das Feld oben wird dann ignoriert")
    return group


async def _start_chat_input(interaction, ctx: WizardContext, field: str):
    ui = ctx.ui
    ui[AWAIT_KEY] = {"field": field, "channel_id": interaction.channel_id,
                     "message_id": interaction.message.id if interaction.message else None}
    ctx.set_ui(ui)
    ctx.store.clear_text_edit(interaction.user.id)
    await show(interaction, ctx)


@action("chat_cancel")
async def _chat_cancel(interaction, ctx: WizardContext, arg):
    ui = ctx.ui
    ui.pop(AWAIT_KEY, None)
    ctx.set_ui(ui)
    await show(interaction, ctx)


def apply_chat_text(ctx: WizardContext, text: str) -> str | None:
    """Übernimmt die Chat-Nachricht als Titel bzw. Beschreibung. Gibt bei zu langem Text einen
    Hinweis zurück und wartet weiter."""
    wait = (ctx.ui.get(AWAIT_KEY) or {})
    field = wait.get("field")
    text = (text or "").strip()
    d = ctx.data
    if field == "title":
        if len(text) > TITLE_MAX_LENGTH:
            return f"Der Titel ist zu lang ({len(text)} von {TITLE_MAX_LENGTH} Zeichen). Schreib ihn bitte kürzer."
        d.title = _title_from_input(d, text)
    elif field == "description":
        if len(text) > DESCRIPTION_MAX_LENGTH:
            return (f"Die Beschreibung ist zu lang ({len(text)} von {DESCRIPTION_MAX_LENGTH} Zeichen). "
                    "Schreib sie bitte kürzer.")
        d.description = text
    ctx.save(d)
    ui = ctx.ui
    ui.pop(AWAIT_KEY, None)
    ctx.set_ui(ui)
    return None


class TitleModal(_WizardModal):
    """Eigener Titel. Leer = automatisch „{Skript} mit {ST}“. Die Symbole kommen immer davor."""

    def __init__(self, draft_id: int, data: EventData):
        super().__init__(draft_id, "Titel")
        # Der aktuelle Titel steht ausgeschrieben drin (Dalyan, 20.10.2026), nicht nur als Platzhalter
        self.text = discord.ui.TextInput(default=(data.title or base_title(data))[:TITLE_MAX_LENGTH],
                                         required=False, max_length=TITLE_MAX_LENGTH)
        self.add_item(discord.ui.Label(text="Titel", description="Die Symbole (Labels, Schwierigkeit) kommen "
                                       "automatisch davor. Leer = automatischer Titel.", component=self.text))
        self.chat = _chat_checkbox()
        self.add_item(discord.ui.Label(text="Oder im Chat", component=self.chat))

    async def handle(self, interaction, ctx: WizardContext):
        if CHAT_OPTION in self.chat.values:
            await _start_chat_input(interaction, ctx, "title")
            return
        d = ctx.data
        d.title = _title_from_input(d, self.text.value)
        ctx.save(d)
        await show(interaction, ctx)


def _title_from_input(d: EventData, value: str | None) -> str:
    """Eigener Titel; unverändert vorbelegter (= automatischer) Titel bleibt automatisch."""
    value = (value or "").strip()
    return "" if value == base_title(d) else value


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
            ui = ctx.ui
            if ui.pop("rating_error", None):
                ctx.set_ui(ui)
        await show(interaction, ctx)


class PeopleModal(_WizardModal):
    """Storyteller:in und Co-Storyteller:in als einfacher Text (keine Mitgliedersuche)."""

    def __init__(self, draft_id: int, data: EventData):
        super().__init__(draft_id, "Storyteller:in & Co-Storyteller:in")
        self.st = discord.ui.TextInput(default=data.storyteller.name if data.storyteller else None,
                                       min_length=1, max_length=50)
        if data.is_other_event:
            self.co_status = None
            self.add_item(discord.ui.Label(text="Organisation", description="Wer leitet das Event?",
                                           component=self.st))
            return
        self.co_status = discord.ui.RadioGroup()
        for value, label in CO_ST_LABELS.items():
            self.co_status.add_option(label=label, value=value, default=value == data.co_st_status)
        self.co = discord.ui.TextInput(default=data.co_st_note or None, required=False, max_length=100,
                                       placeholder="z. B. „gern Neulinge“")
        self.add_item(discord.ui.Label(text="Storyteller:in", component=self.st))
        self.add_item(discord.ui.Label(text="Co-Storytellen möglich?", component=self.co_status))
        self.add_item(discord.ui.Label(text="Hinweis zum Co-Storytelling", description="Optional",
                                       component=self.co))

    async def handle(self, interaction, ctx: WizardContext):
        d = ctx.data
        if self.co_status is None:  # Event ohne Clocktower: nur die Organisation
            _apply_people(ctx, d, self.st.value, None, None)
        else:
            _apply_people(ctx, d, self.st.value, self.co.value, self.co_status.value or CO_ST_NO)
        ctx.save(d)
        await show(interaction, ctx)


def _apply_people(ctx: WizardContext, d: EventData, st_text: str, co_text: str | None, co_status: str | None):
    """Storyteller aus Freitext (ein unveränderter Name behält seine User-ID), Co-ST als Status + Hinweis."""
    st_name = st_text.strip()
    old_st = d.storyteller
    if old_st is not None and old_st.name == st_name:
        pass
    elif st_name == ctx.member.display_name:
        d.storyteller = Person(name=st_name, user_id=ctx.member.id)
    else:
        d.storyteller = Person(name=st_name)
    if co_status is None:  # Co-ST nicht abgefragt (Event ohne Clocktower)
        return
    d.co_st_status = co_status
    d.co_st_note = (co_text or "").strip()


def _label_checkboxes(data: EventData, allow_academy: bool) -> discord.ui.CheckboxGroup:
    group = discord.ui.CheckboxGroup(required=False, min_values=0)
    choices = [("academy", "🎓 Academy", data.is_academy), ("casual", "🕊️ Casual", data.is_casual),
               ("recorded", "🎦 Aufzeichnung", data.is_recorded),
               ("special", "⭐ Abweichung vom klassischen Clocktower", data.is_special)]
    for value, label, on in choices:
        if value == "academy" and not allow_academy:
            continue
        group.add_option(label=label, value=value, default=on)
    group.max_values = len(group.options)
    return group


def _apply_labels(d: EventData, group: discord.ui.CheckboxGroup):
    chosen = set(group.values)
    d.is_recorded = "recorded" in chosen
    d.is_special = "special" in chosen
    if "academy" in {o.value for o in group.options}:
        d.is_academy = "academy" in chosen
    d.is_casual = "casual" in chosen


def _camera_radio(data: EventData) -> discord.ui.RadioGroup:
    radio = discord.ui.RadioGroup()
    for key, label in CAMERA_LABELS.items():
        radio.add_option(label=label, value=key, default=key == data.camera)
    return radio


def _level_radio(data: EventData) -> discord.ui.RadioGroup:
    radio = discord.ui.RadioGroup()
    for lvl in LEVELS:
        radio.add_option(label=lvl, value=lvl, default=lvl == data.level)
    return radio


class SelectionModal(_WizardModal):
    """„Auswahl“: Labels, Erfahrungslevel, Kamera."""

    def __init__(self, draft_id: int, data: EventData, allow_academy: bool):
        super().__init__(draft_id, "Labels, Level & Kamera")
        self.options = _label_checkboxes(data, allow_academy)
        self.level = _level_radio(data)
        self.camera = _camera_radio(data)
        self.camera_note = discord.ui.TextInput(required=False, max_length=100, default=data.camera_note or None,
                                                placeholder="z. B. „gern mit Kamera“")
        self.add_item(discord.ui.Label(text="Labels", component=self.options))
        self.add_item(discord.ui.Label(text="Erfahrungslevel", component=self.level))
        self.add_item(discord.ui.Label(text="Kamera", component=self.camera))
        self.add_item(discord.ui.Label(text="Hinweis zur Kamera", description="Optional", component=self.camera_note))

    async def handle(self, interaction, ctx: WizardContext):
        d = ctx.data
        _apply_labels(d, self.options)
        d.level = self.level.value or d.level
        d.camera = self.camera.value or d.camera
        d.camera_note = (self.camera_note.value or "").strip()
        ctx.save(d)  # prüft die Academy-Berechtigung
        await show(interaction, ctx)


# ── Plausibilität: ungewöhnlicher Termin oder ungewöhnliche Dauer ──────────────
# Ein Tippfehler wie „01.04“ im Mai landet sonst ohne Warnung im nächsten Jahr (Dalyan, 21.10.2026).
CONFIRM_KEY = "confirm"
WARN_DAYS_AHEAD = 90
WARN_DURATION_MINUTES = 8 * 60


def plausibility_warnings(d: EventData, now_: datetime) -> list[str]:
    warnings = []
    if d.duration_minutes > WARN_DURATION_MINUTES:
        warnings.append("Dein Event geht länger als 8 Stunden. Bist du dir sicher, dass das richtig ist?")
    if d.start is not None and d.start - now_ > timedelta(days=WARN_DAYS_AHEAD):
        warnings.append(f"Dein Event liegt über {WARN_DAYS_AHEAD} Tage in der Zukunft "
                        f"({format_start(d.start, d.duration_minutes)}). Bist du dir sicher, dass das richtig ist?")
    return warnings


def _frame_prefill(data: EventData) -> tuple[str, str]:
    start = data.start.astimezone(BERLIN_TZ) if data.start else None
    return (f"{start:%d.%m.%Y}" if start else "", f"{start:%H:%M}" if start else "")


@action("confirm_yes")
async def _confirm_yes(interaction, ctx: WizardContext, arg):
    """„Ja, weiter“: die gemerkten Eingaben übernehmen."""
    ui = ctx.ui
    pending = ui.pop(CONFIRM_KEY, None) or {}
    if pending.get("kind") == "frame":
        d = ctx.data
        _apply_frame(d, _frame_prefill(d), *pending["inputs"])
        ctx.save(d)
    ctx.set_ui(ui)
    await show(interaction, ctx)


@action("confirm_no")
async def _confirm_no(interaction, ctx: WizardContext, arg):
    """„Nein, zurück“: den Dialog mit den eben gemachten Eingaben wieder öffnen."""
    pending = ctx.ui.get(CONFIRM_KEY) or {}
    if pending.get("kind") == "start":
        from discord_ui.botc_modal import BotcModal  # zirkulären Import vermeiden
        from events.intake import ModalInput

        guild = ctx.bot.get_guild(ctx.draft.guild_id)
        await interaction.response.send_modal(BotcModal(ctx.store, _allow_academy(ctx), ModalInput(**pending["raw"]),
                                                        guild, ctx.member, origin=interaction.message))
        return
    if pending.get("kind") == "frame":
        await interaction.response.send_modal(FrameModal(ctx.draft.id, ctx.data, inputs=pending["inputs"]))
        return
    ui = ctx.ui
    ui.pop(CONFIRM_KEY, None)
    ctx.set_ui(ui)
    await show(interaction, ctx)


class FrameModal(_WizardModal):
    """„Termin & Rahmen“: Datum, Uhrzeit, Dauer, Spieler.
    `inputs`: Eingaben, die vorbelegt werden sollen (nach „Nein, zurück“)."""

    def __init__(self, draft_id: int, data: EventData, inputs: list[str] | None = None):
        super().__init__(draft_id, "Termin & Rahmen")
        self.prefill = _frame_prefill(data)
        date_text, time_text, duration_text, players_text = inputs or (
            self.prefill[0], self.prefill[1], str(data.duration_minutes), str(data.max_players))
        self.date = discord.ui.TextInput(default=date_text or None, placeholder="z. B. Sa, morgen, 24.10.",
                                         max_length=30)
        self.time = discord.ui.TextInput(default=time_text or None, placeholder="z. B. 20:00", max_length=10)
        self.duration = discord.ui.TextInput(default=duration_text or None, max_length=4)
        self.players = discord.ui.TextInput(default=players_text or None, max_length=3)
        self.add_item(discord.ui.Label(text="Datum", component=self.date))
        self.add_item(discord.ui.Label(text="Uhrzeit", component=self.time))
        self.add_item(discord.ui.Label(text="Dauer in Minuten", component=self.duration))
        self.add_item(discord.ui.Label(text="Max. Teilnehmer" if data.is_other_event else "Max. Spieler",
                                       description="1 bis 200", component=self.players))

    async def handle(self, interaction, ctx: WizardContext):
        d = ctx.data
        inputs = [self.date.value, self.time.value, self.duration.value, self.players.value]
        _apply_frame(d, self.prefill, *inputs)
        ui = ctx.ui
        old = ctx.draft.data
        changed = (d.start, d.duration_minutes) != (old.start, old.duration_minutes)
        warnings = plausibility_warnings(d, now()) if changed else []
        if warnings:  # erst nachfragen, noch nichts speichern
            ui[CONFIRM_KEY] = {"kind": "frame", "inputs": inputs, "warnings": warnings}
            ctx.set_ui(ui)
            await show(interaction, ctx)
            return
        ui.pop(CONFIRM_KEY, None)
        ctx.set_ui(ui)
        ctx.save(d)
        await show(interaction, ctx)


def _apply_frame(d: EventData, prefill, date_text, time_text, duration_text, players_text):
    try:
        # Unveränderter Termin bleibt, auch wenn er schon vorbei ist (Bearbeiten einer laufenden Runde)
        if (date_text.strip(), time_text.strip()) != prefill:
            d.start = parse_start(date_text, time_text, now())
        d.max_players = parse_players(players_text)
    except ParseError as e:
        raise service.ServiceError(str(e)) from None
    duration = duration_text.strip()
    if not duration.isdigit() or not 15 <= int(duration) <= 24 * 60:
        raise service.ServiceError("Die Dauer muss eine Zahl zwischen 15 und 1440 Minuten sein.")
    d.duration_minutes = int(duration)


class DescriptionModal(_WizardModal):
    def __init__(self, draft_id: int, current: str):
        super().__init__(draft_id, "Beschreibung")
        self.text = discord.ui.TextInput(style=discord.TextStyle.paragraph, default=current or None,
                                         placeholder="Worauf können sich die Mitspieler:innen freuen?",
                                         required=False, max_length=DESCRIPTION_MAX_LENGTH)
        self.add_item(discord.ui.Label(text="Beschreibung", description=f"Bis zu {DESCRIPTION_MAX_LENGTH} Zeichen",
                                       component=self.text))
        self.chat = _chat_checkbox()
        self.add_item(discord.ui.Label(text="Oder im Chat", component=self.chat))

    async def handle(self, interaction, ctx: WizardContext):
        if CHAT_OPTION in self.chat.values:
            await _start_chat_input(interaction, ctx, "description")
            return
        d = ctx.data
        d.description = (self.text.value or "").strip()
        ctx.save(d)
        await show(interaction, ctx)


class ImageUploadModal(_WizardModal):
    def __init__(self, draft_id: int):
        super().__init__(draft_id, "Eigenes Bild")
        self.file = discord.ui.FileUpload(required=True, min_values=1, max_values=1)
        self.add_item(discord.ui.Label(text="Bild", description="PNG, JPG, WEBP oder GIF, bis 8 MB",
                                       component=self.file))

    async def handle(self, interaction, ctx: WizardContext):
        attachment = self.file.values[0]
        if attachment.size > MAX_UPLOAD_BYTES:  # vor dem Herunterladen prüfen, nicht erst danach
            raise service.ServiceError("Das Bild ist größer als 8 MB.")
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

