"""Startnachricht von /botc: erklärt kurz den Ablauf, der Button öffnet das Modal.

Alles passiert in den DMs (Dalyan, 20.10.2026): /botc in einem Channel schickt diese Nachricht per DM,
in den DMs erscheint sie direkt. Nach dem Modal wird sie zur Skript-Karte, der Wizard bleibt
eine einzige Nachricht.

Der Button ist ein DynamicItem (`botc:<guild_id>:<aktion>`) und funktioniert nach einem Neustart weiter.
"""

from __future__ import annotations

import re

import discord

from config import get_guild_config
from discord_ui import wizard
from discord_ui.botc_modal import BotcModal
from discord_ui.members import actor_from_member, fetch_member
from events import guild_lock, permissions, service
from events.parse import format_start
from events.templates import RULES_URL, STORYTELLER_GUIDE_URL

START_COLOR = 0x5865F2


def _link(url: str, label: str) -> str:
    # Bis die Links feststehen, ein sichtbarer Platzhalter für die Tester:innen
    return f"[{label}]({url})" if url else f"{label} *(Link folgt)*"


def start_layout(guild: discord.Guild, user_id: int, open_draft=None) -> discord.ui.LayoutView:
    """Startnachricht: was gleich passiert, darunter „Termin festlegen“ bzw. „Entwurf fortsetzen“."""
    esc = discord.utils.escape_markdown
    # Persönlicher Ton, Emojis nur dort, wo man sie auch im Gespräch setzen würde (Dalyan, 20.10.2026)
    container = discord.ui.Container(accent_colour=START_COLOR)
    intro = discord.ui.TextDisplay(
        f"-# {esc(guild.name)}\n\n"
        "**Neue Runde anlegen**\n"
        "Schön, dass du eine Runde leiten möchtest! Das dauert nur ein paar Minuten.")
    icon = getattr(guild, "icon", None)
    if icon:  # Server-Icon rechts neben dem Titel
        container.add_item(discord.ui.Section(intro, accessory=discord.ui.Thumbnail(icon.url)))
    else:
        container.add_item(intro)
    container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
    container.add_item(discord.ui.TextDisplay(
        "Als Erstes legst du den Termin und ein paar Optionen für die Runde fest. "
        "Danach suchst du dir das Skript aus, entweder über botcscripts.com, als Basis-Skript oder als "
        "eigenes JSON.\n\n"
        "Am Ende siehst du eine Zusammenfassung, in der du noch eine kurze Beschreibung schreibst, alles "
        "anpassen kannst und die Runde veröffentlichst 🎉"))
    container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
    container.add_item(discord.ui.TextDisplay(
        "Neu im Storytelling? In den "
        f"{_link(STORYTELLER_GUIDE_URL, 'Hinweisen zum Storytellen')} steht, worauf es ankommt.\n"
        f"Und wie immer gelten unsere {_link(RULES_URL, 'Serverregeln')}.\n"
        "-# Dein Entwurf bleibt 24 Stunden gespeichert, du kannst also auch später weitermachen."))
    if open_draft is not None:
        d = open_draft.data
        what = [d.script.display_name if d.script else None,
                format_start(d.start, d.duration_minutes) if d.start else None]
        detail = " · ".join(x for x in what if x)
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "**Du hast noch einen offenen Entwurf**" + (f"\n{esc(detail)}" if detail else "")))

    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    row = discord.ui.ActionRow()
    if open_draft is not None:
        row.add_item(StartButton(guild.id, "resume", "Entwurf fortsetzen", discord.ButtonStyle.primary))
        row.add_item(StartButton(guild.id, "new", "Neu beginnen", discord.ButtonStyle.secondary))
    else:
        row.add_item(StartButton(guild.id, "new", "Termin festlegen", discord.ButtonStyle.primary))
    layout.add_item(row)
    return layout


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
        member = await fetch_member(bot, self.guild_id, interaction.user.id) if guild else None
        if guild is None or member is None or not guild_lock.is_allowed(self.guild_id):
            await interaction.response.send_message("Für diesen Server kannst du gerade keine Runde anlegen.",
                                                    ephemeral=True)
            return
        problem = start_problem(store, guild, member)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return

        if self.name == "resume":
            draft = service.open_draft(store, guild.id, member.id, wizard.now())
            if draft is None:
                await interaction.response.edit_message(view=start_layout(guild, member.id))
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
