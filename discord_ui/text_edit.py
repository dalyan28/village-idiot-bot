"""Längere Texte per DM bearbeiten statt im Dialog (Dalyan, 27.10.2026).

In Discord-Dialogen gibt es keine Formatierung und keine Emoji-Auswahl. Deshalb schickt der Bot eine Karte mit
dem aktuellen Text in die DMs; die nächste Nachricht dort (oder eine angehängte .txt-Datei) wird der neue Text.
Die offene Bearbeitung liegt in der Tabelle `text_edits` (eine je Person, 30 Minuten gültig), übersteht also
einen Neustart.

Texte: `academy` (Academy-Text des Servers) und `description` (eigene Standard-Beschreibung aus /einstellungen).
Buttons: DynamicItem `tedit:<guild_id>:<text>:<aktion>`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import discord

from discord_ui.members import actor_from_member, fetch_member
from events import permissions, service, user_settings
from events.schema import BERLIN_TZ, DESCRIPTION_MAX_LENGTH

logger = logging.getLogger(__name__)

CARD_COLOR = 0x5865F2
EDIT_MINUTES = 30
TXT_MAX_BYTES = 20_000
CARD_TEXT_LIMIT = 3000  # Rest der Karte bleibt unter Discords 4000 Zeichen
DM_CLOSED = ("Ich kann dir keine DM schicken. Erlaube DMs von Servermitgliedern (Servereinstellungen → "
             "Privatsphäre) und versuch es dann erneut.")
IN_DMS = "Es geht in deinen DMs weiter."


def now() -> datetime:
    return datetime.now(BERLIN_TZ)


@dataclass(frozen=True)
class TextKind:
    title: str
    hint: str
    reset_label: str
    reset_notice: str
    max_length: int


KINDS = {
    "academy": TextKind(
        title="Academy-Text",
        hint="Zeilen mit 💚, 🟡 oder 🟥 am Anfang werden passend zur Runde fett, `{hier}` wird zur Rundenzahl "
             "der Stufe.",
        reset_label="Auf Standard zurücksetzen",
        reset_notice="Der eingebaute Academy-Text gilt wieder.",
        max_length=4000,
    ),
    "description": TextKind(
        title="Standard-Beschreibung",
        hint="Sie steht in jedem neuen Event, das du anlegst. Im Entwurf kannst du sie danach noch ändern.",
        reset_label="Standard-Beschreibung entfernen",
        reset_notice="Neue Events starten wieder ohne Beschreibung.",
        max_length=DESCRIPTION_MAX_LENGTH,
    ),
}


# ── Lesen und Speichern ──────────────────────────────────────────────────────


def current_text(store, guild_id: int, user_id: int, kind: str) -> str:
    if kind == "academy":
        return service.get_academy_template(store, guild_id)
    return user_settings.get(store, guild_id, user_id).description or ""


def save_text(store, guild_id: int, user_id: int, kind: str, text: str | None):
    """`None` = zurücksetzen."""
    if kind == "academy":
        service.set_academy_template(store, guild_id, text)
        return
    d = user_settings.get(store, guild_id, user_id)
    d.description = (text or "").strip()
    user_settings.save(store, guild_id, user_id, d, int(now().timestamp()))


def preview(store, guild_id: int, user_id: int, kind: str) -> tuple[str, str]:
    """(Überschrift, Text) der Vorschau nach dem Speichern."""
    text = current_text(store, guild_id, user_id, kind)
    if kind == "academy":
        from events.templates import academy_description
        return "Vorschau für eine 🟡-Runde", academy_description("yellow", text)
    return "Deine Standard-Beschreibung", text or "*keine*"


async def may_edit(bot, guild_id: int, user_id: int, kind: str) -> bool:
    member = await fetch_member(bot, guild_id, user_id)
    if member is None:
        return False
    if kind != "academy":
        return True
    actor = actor_from_member(member)
    access = service.get_access(bot.store, guild_id)
    return permissions.can(actor, permissions.CONFIGURE, access) or permissions.can(
        actor, permissions.CREATE_ACADEMY, access)


# ── Karte ────────────────────────────────────────────────────────────────────


def _cut(text: str) -> str:
    return text if len(text) <= CARD_TEXT_LIMIT else text[:CARD_TEXT_LIMIT] + " …"


def edit_layout(guild_name: str, guild_id: int, kind: str, text: str, notice: str | None = None,
                waiting: bool = True) -> discord.ui.LayoutView:
    """`waiting`: Der Bot wartet auf den neuen Text. Sonst zeigt die Karte das Ergebnis (`text` = Vorschau)."""
    k = KINDS[kind]
    head = [f"-# {discord.utils.escape_markdown(guild_name)}", f"**{k.title}**"]
    if waiting:
        head.append("Schick mir den neuen Text als nächste Nachricht hier im Chat. Formatierung, Emojis und "
                    "Absätze übernehme ich so, wie du sie schreibst.")
        head.append(f"-# {k.hint} Ist der Text länger als 2000 Zeichen, häng ihn als .txt-Datei an.")
    if notice:
        head.append(notice)
    container = discord.ui.Container(accent_colour=CARD_COLOR)
    container.add_item(discord.ui.TextDisplay("\n".join(head)))
    container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
    label = "Aktueller Text" if waiting else ""
    body = _cut(text) if text.strip() else "*keiner*"
    container.add_item(discord.ui.TextDisplay(f"-# {label}\n{body}" if label else body))
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    row = discord.ui.ActionRow()
    if waiting:
        row.add_item(TextEditButton(guild_id, kind, "raw", "Als Rohtext zum Kopieren"))
        row.add_item(TextEditButton(guild_id, kind, "reset", k.reset_label))
        row.add_item(TextEditButton(guild_id, kind, "cancel", "Abbrechen"))
    else:
        row.add_item(TextEditButton(guild_id, kind, "again", "Nochmal ändern"))
    layout.add_item(row)
    return layout


def result_layout(store, guild_name: str, guild_id: int, user_id: int, kind: str, notice: str):
    title, text = preview(store, guild_id, user_id, kind)
    return edit_layout(guild_name, guild_id, kind, text, f"{notice}\n-# {title}", waiting=False)


def raw_layout(text: str) -> discord.ui.LayoutView:
    """Der Text unformatiert in einem Codeblock, damit man ihn mit Sternchen und Emoji-Codes kopieren kann."""
    layout = discord.ui.LayoutView(timeout=None)
    raw = text.replace("```", "ˋˋˋ") or " "
    layout.add_item(discord.ui.TextDisplay(f"```\n{raw[:3900]}\n```"))
    return layout


# ── Ablauf ───────────────────────────────────────────────────────────────────


def _arm(store, user_id: int, guild_id: int, kind: str, message: discord.Message | None):
    expires = int((now() + timedelta(minutes=EDIT_MINUTES)).timestamp())
    store.set_text_edit(user_id, guild_id, kind, message.channel.id if message else None,
                        message.id if message else None, expires)


async def start(bot, guild: discord.Guild, user: discord.abc.User, kind: str) -> bool:
    """Schickt die Karte in die DMs und wartet auf den Text. False, wenn die DMs zu sind."""
    store = bot.store
    layout = edit_layout(guild.name, guild.id, kind, current_text(store, guild.id, user.id, kind))
    try:
        message = await user.send(view=layout)
    except discord.Forbidden:
        return False
    _arm(store, user.id, guild.id, kind, message)
    return True


async def _read(message: discord.Message) -> str | None:
    """Text der Nachricht, oder der Inhalt einer angehängten .txt-Datei."""
    for attachment in message.attachments:
        if attachment.filename.lower().endswith(".txt") and attachment.size <= TXT_MAX_BYTES:
            try:
                return (await attachment.read()).decode("utf-8-sig").strip()
            except (discord.HTTPException, UnicodeDecodeError):
                return None
    return message.content.strip() or None


async def take_text(bot, message: discord.Message) -> bool:
    """DM-Nachricht als neuen Text übernehmen, wenn eine Bearbeitung offen ist."""
    if message.guild is not None or message.author.bot:
        return False
    store = bot.store
    pending = store.get_text_edit(message.author.id, int(now().timestamp()))
    if pending is None:
        return False
    guild_id, kind = pending["guild_id"], pending["kind"]
    guild = bot.get_guild(guild_id)
    if guild is None or kind not in KINDS or not await may_edit(bot, guild_id, message.author.id, kind):
        store.clear_text_edit(message.author.id)
        return False
    text = await _read(message)
    k = KINDS[kind]
    if text is None:
        await message.reply("Schick den Text als Nachricht oder als .txt-Datei.", mention_author=False)
        return True
    if len(text) > k.max_length:
        await message.reply(f"Der Text ist {len(text)} Zeichen lang, erlaubt sind {k.max_length}. "
                            "Kürz ihn und schick ihn nochmal.", mention_author=False)
        return True
    save_text(store, guild_id, message.author.id, kind, text)
    store.clear_text_edit(message.author.id)
    notice = "Gespeichert."
    if kind == "academy":
        notice += " Bestehende Academy-Events zeigen ihn, sobald ihr Post neu aufgebaut wird."
    layout = result_layout(store, guild.name, guild_id, message.author.id, kind, notice)
    target = None
    if pending.get("message_id"):
        try:
            target = await message.channel.fetch_message(pending["message_id"])
        except discord.HTTPException:
            target = None
    if target is not None:
        await target.edit(view=layout)
    else:
        await message.channel.send(view=layout)
    try:
        await message.add_reaction("✅")
    except discord.HTTPException:
        pass
    return True


class TextEditButton(discord.ui.DynamicItem[discord.ui.Button],
                     template=r"tedit:(?P<guild_id>\d+):(?P<kind>[a-z]+):(?P<action>[a-z]+)"):
    def __init__(self, guild_id: int, kind: str, action: str, label: str = "Ändern"):
        style = discord.ButtonStyle.danger if action == "reset" else discord.ButtonStyle.secondary
        super().__init__(discord.ui.Button(label=label, style=style,
                                           custom_id=f"tedit:{guild_id}:{kind}:{action}"))
        self.guild_id, self.kind, self.action = guild_id, kind, action

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["guild_id"]), match["kind"], match["action"], item.label or "Ändern")

    async def callback(self, interaction: discord.Interaction):
        bot, store, user_id = interaction.client, interaction.client.store, interaction.user.id
        guild = bot.get_guild(self.guild_id)
        if guild is None or self.kind not in KINDS or not await may_edit(bot, self.guild_id, user_id, self.kind):
            await interaction.response.send_message("Das kannst du gerade nicht ändern.", ephemeral=True)
            return
        k = KINDS[self.kind]
        if self.action == "raw":
            await interaction.response.send_message(
                view=raw_layout(current_text(store, guild.id, user_id, self.kind)), ephemeral=True)
        elif self.action == "reset":
            save_text(store, guild.id, user_id, self.kind, None)
            store.clear_text_edit(user_id)
            await interaction.response.edit_message(
                view=result_layout(store, guild.name, guild.id, user_id, self.kind, k.reset_notice))
        elif self.action == "cancel":
            store.clear_text_edit(user_id)
            await interaction.response.edit_message(view=result_layout(
                store, guild.name, guild.id, user_id, self.kind, "Abgebrochen, der Text bleibt, wie er ist."))
        elif self.action == "again":
            await interaction.response.edit_message(
                view=edit_layout(guild.name, guild.id, self.kind, current_text(store, guild.id, user_id, self.kind)))
            _arm(store, user_id, guild.id, self.kind, interaction.message)
