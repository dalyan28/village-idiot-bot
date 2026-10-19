"""DM-Wizard: eine Nachricht pro Entwurf, die bei jedem Schritt bearbeitet wird.

Alle Buttons sind DynamicItems mit der Entwurfs-ID im custom_id (`wiz:<draft_id>:<aktion>[:<arg>]`).
Damit funktionieren sie auch nach einem Neustart des Bots: Der Zustand liegt in der Datenbank,
nicht im Arbeitsspeicher. Neue Aktionen werden mit `@action("name")` registriert.
"""

from __future__ import annotations

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
from events.schema import BERLIN_TZ, CAMERA_LABELS
from events.store import Draft, Store

logger = logging.getLogger(__name__)

WIZARD_COLOR = 0x5865F2


@dataclass
class WizardContext:
    bot: discord.Client
    store: Store
    draft: Draft
    actor: Actor


Handler = Callable[[discord.Interaction, WizardContext, str | None], Awaitable[None]]
_ACTIONS: dict[str, Handler] = {}


def action(name: str):
    """Registriert eine Wizard-Aktion für Buttons mit `wiz:<id>:<name>`."""
    def deco(fn: Handler) -> Handler:
        _ACTIONS[name] = fn
        return fn
    return deco


def custom_id(draft_id: int, name: str, arg: str | None = None) -> str:
    return f"wiz:{draft_id}:{name}" + (f":{arg}" if arg else "")


def now() -> datetime:
    return datetime.now(BERLIN_TZ)


class WizardButton(discord.ui.DynamicItem[discord.ui.Button], template=r"wiz:(?P<draft_id>\d+):(?P<name>[a-z_]+)(?::(?P<arg>[\w\-]+))?"):
    def __init__(self, draft_id: int, name: str, label: str, style=discord.ButtonStyle.secondary,
                 arg: str | None = None, emoji: str | None = None, row: int | None = None):
        super().__init__(discord.ui.Button(label=label, style=style, emoji=emoji, row=row,
                                           custom_id=custom_id(draft_id, name, arg)))
        self.draft_id, self.name, self.arg = draft_id, name, arg

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["draft_id"]), match["name"], item.label or "", item.style, match["arg"])

    async def callback(self, interaction: discord.Interaction):
        ctx = await load_context(interaction, self.draft_id)
        if ctx is None:
            return
        handler = _ACTIONS.get(self.name)
        if handler is None:
            logger.warning("Unbekannte Wizard-Aktion: %s", self.name)
            await interaction.response.send_message("Diese Aktion gibt es nicht mehr.", ephemeral=True)
            return
        try:
            await handler(interaction, ctx, self.arg)
        except service.ServiceError as e:
            await _reply(interaction, f"⚠️ {e}")


async def _reply(interaction: discord.Interaction, text: str):
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


async def load_context(interaction: discord.Interaction, draft_id: int) -> WizardContext | None:
    """Lädt Entwurf und Actor und prüft Besitz und Server-Lock. Antwortet selbst bei Fehlern."""
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
    return WizardContext(interaction.client, store, draft, actor_from_member(member))


# ── Darstellung ──────────────────────────────────────────────────────────────


def summary_embed(draft: Draft, guild_name: str | None = None) -> discord.Embed:
    """Kopf des Wizards: was bisher feststeht."""
    d = draft.data
    embed = discord.Embed(title="📝 Neue Runde" if draft.event_id is None else "✏️ Runde bearbeiten",
                          color=WIZARD_COLOR)
    if guild_name:
        embed.description = f"für **{discord.utils.escape_markdown(guild_name)}**"
    embed.add_field(name="Termin", value=format_start(d.start, d.duration_minutes) if d.start else "-", inline=False)
    embed.add_field(name="Max. Spieler", value=str(d.max_players), inline=True)
    embed.add_field(name="Level", value=d.level, inline=True)
    labels = [name for flag, name in ((d.is_academy, "Academy 🎓"), (d.is_casual, "Casual 🕊️"),
                                      (d.is_recorded, "Aufzeichnung 🎦")) if flag]
    embed.add_field(name="Labels", value=", ".join(labels) or "-", inline=True)
    embed.add_field(name="Kamera", value=CAMERA_LABELS.get(d.camera, "-"), inline=True)
    st = d.storyteller.name if d.storyteller else "-"
    embed.add_field(name="Storytelling", value=discord.utils.escape_markdown(st), inline=True)
    embed.set_footer(text="Entwürfe bleiben 24 Stunden gespeichert.")
    return embed


def render(draft: Draft, guild_name: str | None = None) -> tuple[discord.Embed, discord.ui.View]:
    """Aktueller Schritt als Embed + Buttons. Die Schritte 1–6 kommen in Phase 3 dazu."""
    embed = summary_embed(draft, guild_name)
    embed.add_field(
        name="Als Nächstes",
        value="**Schritt 1: Skript.** Die Skriptauswahl wird gerade gebaut und folgt in Kürze.",
        inline=False,
    )
    view = discord.ui.View(timeout=None)
    view.add_item(WizardButton(draft.id, "cancel", "Abbrechen", discord.ButtonStyle.danger))
    return embed, view


async def send_wizard(user: discord.abc.User, draft: Draft, guild_name: str | None = None, intro: str | None = None):
    """Schickt die Wizard-Nachricht per DM. Wirft discord.Forbidden, wenn DMs geschlossen sind."""
    embed, view = render(draft, guild_name)
    await user.send(content=intro, embed=embed, view=view)


async def update_wizard(interaction: discord.Interaction, draft: Draft, content: str | None = None):
    """Bearbeitet die Wizard-Nachricht, auf deren Button geklickt wurde."""
    guild = interaction.client.get_guild(draft.guild_id)
    embed, view = render(draft, guild.name if guild else None)
    await interaction.response.edit_message(content=content, embed=embed, view=view)


# ── Aktionen ─────────────────────────────────────────────────────────────────


@action("cancel")
async def _cancel(interaction: discord.Interaction, ctx: WizardContext, arg: str | None):
    service.discard_draft(ctx.store, ctx.draft, ctx.actor)
    await interaction.response.edit_message(
        content="Event-Erstellung abgebrochen. ✌️ Mit `/botc` kannst du jederzeit neu starten.",
        embed=None, view=None,
    )
