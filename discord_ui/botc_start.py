"""Startnachricht von /botc: erklärt kurz den Ablauf, der Button öffnet das Modal.

Alles passiert in den DMs (Dalyan, 20.10.2026): /botc in einem Channel schickt diese Nachricht per DM,
in den DMs erscheint sie direkt. Nach dem Modal wird sie zur Skript-Karte, der Wizard bleibt
eine einzige Nachricht.

Der Button ist ein DynamicItem (`botc:<guild_id>:<aktion>`) und funktioniert nach einem Neustart weiter.
"""

from __future__ import annotations

import io
import re

import discord

from config import get_guild_config
from discord_ui import wizard
from discord_ui.botc_modal import BotcModal
from discord_ui.members import NOT_READY, actor_from_member, fetch_member, is_ready
from events import guild_lock, permissions, service
from events.parse import format_start
from events.templates import RULES_URL, STORYTELLER_GUIDE_URL

START_COLOR = 0x5865F2


def _link(url: str, label: str, bold: bool = False) -> str:
    # Ohne Link ein sichtbarer Platzhalter
    text = f"[{label}]({url})" if url else f"{label} *(Link folgt)*"
    return f"**{text}**" if bold and url else text


DRAFT_IMAGE = "entwurf.png"


async def start_layout(guild: discord.Guild, user_id: int, open_draft=None, links: tuple[str, str] | None = None):
    """Startnachricht mit dem offenen Entwurf (Skript-Bild wird dafür erzeugt). Gibt (LayoutView, Dateien) zurück.
    `links`: (Hinweise, Regeln) des Servers, siehe service.get_start_links."""
    if open_draft is None:
        return build_start_layout(guild, user_id, links=links), []
    block, files = await _draft_block(open_draft)
    return build_start_layout(guild, user_id, block, links=links), files


def build_start_layout(guild: discord.Guild, user_id: int, draft_block=None,
                       links: tuple[str, str] | None = None) -> discord.ui.LayoutView:
    """Startnachricht (Dalyan, 21.10.2026): kurze Einleitung, Links zu Hinweisen und Regeln, ggf. der offene
    Entwurf (`draft_block`). Eine Karte, eine Button-Reihe."""
    esc = discord.utils.escape_markdown
    container = discord.ui.Container(accent_colour=START_COLOR)
    intro = discord.ui.TextDisplay(
        f"-# {esc(guild.name)}\n\n"
        "**Neues Event anlegen**\n"
        "Ich führe dich in ein paar Schritten durch die Erstellung. Bevor etwas veröffentlicht wird, siehst du "
        "alles in einer Zusammenfassung und kannst es dort noch anpassen.")
    icon = getattr(guild, "icon", None)
    if icon:  # Server-Icon rechts neben dem Titel
        container.add_item(discord.ui.Section(intro, accessory=discord.ui.Thumbnail(icon.url)))
    else:
        container.add_item(intro)
    guide_url, rules_url = links or (STORYTELLER_GUIDE_URL, RULES_URL)
    container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
    container.add_item(discord.ui.TextDisplay(
        "Was beim Leiten zählt, welche Symbole es im Wochenplan gibt und eine Vorlage für gute Beschreibungen "
        f"findest du in den {_link(guide_url, 'Hinweisen zum Mitspielen und Storytellen', bold=True)}. "
        f"Für alle Events gelten unsere {_link(rules_url, 'Serverregeln', bold=True)}."))
    container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))

    if draft_block is None:
        container.add_item(discord.ui.TextDisplay("Los geht es mit dem Termin."))
    else:
        container.add_item(draft_block)
        container.add_item(discord.ui.TextDisplay("Du kannst dort weitermachen oder neu beginnen."))

    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    row = discord.ui.ActionRow()
    if draft_block is not None:
        row.add_item(StartButton(guild.id, "resume", "Entwurf fortsetzen", discord.ButtonStyle.primary))
        row.add_item(StartButton(guild.id, "new", "Neu beginnen", discord.ButtonStyle.secondary))
    else:
        row.add_item(StartButton(guild.id, "new", "Termin festlegen", discord.ButtonStyle.primary))
    layout.add_item(row)
    return layout


async def _draft_block(draft):
    """Offener Entwurf: Name und Termin als Werte, wann zuletzt bearbeitet und wann er abläuft,
    rechts klein das Skript-Bild (wenn es eins gibt)."""
    from logic.event_images import render_image

    d = draft.data
    name = d.title.strip() or (d.script.display_name if d.script else "ohne Titel")
    lines = ["**Offener Entwurf**", f"`{name.replace('`', 'ˋ')}`"]
    if d.start:
        lines.append(f"`{format_start(d.start, d.duration_minutes)}`")
    expires = draft.updated_at + service.DRAFT_TTL_SECONDS
    lines.append(f"-# zuletzt bearbeitet <t:{draft.updated_at}:R> · läuft <t:{expires}:R> ab")
    text = discord.ui.TextDisplay("\n".join(lines))
    image = await render_image(d) if d.script is not None else None
    if image is None:
        return text, []
    block = discord.ui.Section(text, accessory=discord.ui.Thumbnail(f"attachment://{DRAFT_IMAGE}"))
    return block, [discord.File(io.BytesIO(image), filename=DRAFT_IMAGE)]


def start_problem(store, guild: discord.Guild, member: discord.Member) -> str | None:
    """Grund, warum diese Person hier keine Runde anlegen kann, sonst None."""
    access = service.get_access(store, guild.id)
    if not permissions.can(actor_from_member(member), permissions.CREATE, access):
        if access.storyteller_role_id is None:
            return ("Für diesen Server ist noch keine Storyteller-Rolle festgelegt. Bis dahin dürfen nur "
                    "Event-Team und Admins Runden anlegen. Ein Admin kann die Rolle mit `/set_event_roles` setzen.")
        role = guild.get_role(access.storyteller_role_id)
        role_name = discord.utils.escape_markdown(role.name if role else "Storyteller")
        return f"Runden anlegen dürfen nur Mitglieder mit der Rolle **{role_name}**."
    event_channel_id = get_guild_config(guild.id).get("event_channel_id")
    if not event_channel_id or not guild.get_channel(event_channel_id):
        return "Es ist noch kein Event-Channel eingerichtet. Ein Admin kann ihn mit `/set_event_channel` setzen."
    return None


class StartButton(discord.ui.DynamicItem[discord.ui.Button],
                  template=r"botc:(?P<guild_id>\d+):(?P<name>new|resume)"):
    def __init__(self, guild_id: int, name: str, label: str | None = None, style=discord.ButtonStyle.primary):
        super().__init__(discord.ui.Button(label=label, style=style, custom_id=f"botc:{guild_id}:{name}"))
        self.guild_id, self.name = guild_id, name

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["guild_id"]), match["name"], item.label, item.style)

    async def callback(self, interaction: discord.Interaction):
        bot, store = interaction.client, interaction.client.store
        guild = bot.get_guild(self.guild_id)
        if guild is None or not is_ready(bot):
            # Meist ein Neustart (z. B. Deploy): Der Bot kennt den Server erst, wenn er bereit ist
            await interaction.response.send_message(NOT_READY, ephemeral=True)
            return
        if not guild_lock.is_allowed(self.guild_id):
            await interaction.response.send_message("Dieser Bot ist auf dem Server nicht freigeschaltet.",
                                                    ephemeral=True)
            return
        member = await fetch_member(bot, self.guild_id, interaction.user.id)
        if member is None:
            await interaction.response.send_message(
                "Ich konnte dich auf dem Server gerade nicht finden. Versuch es bitte noch einmal.", ephemeral=True)
            return
        problem = start_problem(store, guild, member)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return

        if self.name == "resume":
            draft = service.open_draft(store, guild.id, member.id, wizard.now())
            if draft is None:
                layout, files = await start_layout(guild, member.id, links=service.get_start_links(store, guild.id))
                await interaction.response.edit_message(view=layout, attachments=files)
                await interaction.followup.send("Den Entwurf gibt es nicht mehr. Du kannst neu beginnen.",
                                                ephemeral=True)
                return
            layout, files = await wizard.render(bot, draft)
            await interaction.response.edit_message(view=layout, attachments=files)
            return

        allow_academy = permissions.can(actor_from_member(member), permissions.CREATE_ACADEMY,
                                        service.get_access(store, guild.id))
        # Der alte Entwurf wird erst ersetzt, wenn das Modal abgeschickt ist (service.start_draft)
        await interaction.response.send_modal(BotcModal(store, allow_academy, guild=guild, member=member,
                                                        origin=interaction.message))
