"""Button „Feedback“ an Wizard-Karten und Event-Posts, Dialog und Post in den Feedback-Channel.

custom_id: `fb:w:<draft_id>:<karte>` (Wizard), `fb:e:<event_id>` (Event-Post) bzw.
`fb:s:<guild_id>:start` (Startnachricht von /botc, noch ohne Entwurf) bzw. `fb:s:<guild_id>:testcard`
(Ausprobieren-Karte). Als
DynamicItem funktioniert der Button auch nach einem Neustart.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import discord

from discord_ui.members import fetch_member
from events.schema import BERLIN_TZ
from testserver import history, is_test_guild, registry

logger = logging.getLogger(__name__)

KIND_WIZARD, KIND_EVENT, KIND_START = "w", "e", "s"

FEEDBACK_KINDS = {
    "bug": ("Bug", 0xED4245),
    "idea": ("Idee", 0x5865F2),
    "like": ("Gefällt mir", 0x57F287),
    "dislike": ("Gefällt mir nicht", 0xFEE75C),
}
NEUTRAL_COLOR = 0x99AAB5
TEXT_MAX = 1500

NO_CHANNEL = "Es gibt noch keinen Feedback-Channel. Ein Admin muss einmal `/testserver setup` laufen lassen."
THANKS = "Danke, ist angekommen."


def now() -> datetime:
    return datetime.now(BERLIN_TZ)


def feedback_custom_id(kind: str, target_id: int, card: str | None = None) -> str:
    return f"fb:{kind}:{target_id}" + (f":{card}" if card else "")


class FeedbackButton(discord.ui.DynamicItem[discord.ui.Button],
                     template=r"fb:(?P<kind>[wes]):(?P<target>\d+)(?::(?P<card>[a-z]+))?"):
    def __init__(self, kind: str, target_id: int, card: str | None = None, row: int | None = None):
        super().__init__(discord.ui.Button(label="Feedback", style=discord.ButtonStyle.secondary,
                                           custom_id=feedback_custom_id(kind, target_id, card)), row=row)
        self.kind, self.target_id, self.card = kind, target_id, card

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["kind"], int(match["target"]), match["card"])

    async def callback(self, interaction: discord.Interaction):
        store = interaction.client.store
        if self.kind == KIND_WIZARD:
            draft = store.get_draft(self.target_id)
            if draft is None:
                await interaction.response.send_message(
                    "Den Entwurf gibt's nicht mehr. Schreib dein Feedback einfach direkt in den Feedback-Channel.",
                    ephemeral=True)
                return
            guild_id = draft.guild_id
        elif self.kind == KIND_START:
            guild_id = self.target_id
        else:
            guild_id = interaction.guild_id
        if not is_test_guild(guild_id):
            await interaction.response.send_message("Feedback gibt's nur auf dem Testserver.", ephemeral=True)
            return
        await interaction.response.send_modal(FeedbackModal(self.kind, self.target_id, self.card or "event", guild_id))


class FeedbackModal(discord.ui.Modal):
    def __init__(self, kind: str, target_id: int, card: str, guild_id: int):
        super().__init__(title="Feedback", timeout=30 * 60)
        self.kind, self.target_id, self.card, self.guild_id = kind, target_id, card, guild_id
        self.text = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=TEXT_MAX, required=True)
        self.category = discord.ui.RadioGroup(required=False)
        for value, (label, _) in FEEDBACK_KINDS.items():
            self.category.add_option(label=label, value=value)
        self.add_item(discord.ui.Label(text="Was ist dir hier aufgefallen?",
                                       description="Gut, schlecht, Bug, egal was.", component=self.text))
        self.add_item(discord.ui.Label(text="Was ist es?", description="Optional", component=self.category))

    async def on_submit(self, interaction: discord.Interaction):
        bot = interaction.client
        channel_id = registry.channel_id(bot.store, self.guild_id, "feedback")
        channel = bot.get_channel(channel_id) if channel_id else None
        if channel is None:
            await interaction.response.send_message(NO_CHANNEL, ephemeral=True)
            return
        member = await fetch_member(bot, self.guild_id, interaction.user.id)
        name = member.display_name if member else interaction.user.display_name
        embed = build_feedback_embed(bot, self.kind, self.target_id, self.card, self.category.value or "",
                                     self.text.value or "", name, interaction.user.id)
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        await interaction.response.send_message(THANKS, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.exception("Fehler im Feedback-Dialog", exc_info=error)
        if not interaction.response.is_done():
            await interaction.response.send_message("Das hat nicht geklappt. Versuch's bitte nochmal.", ephemeral=True)


def _where(bot, kind: str, target_id: int, card: str) -> tuple[str, list]:
    """Ort des Feedbacks als Text und die passende Historie."""
    store = bot.store
    card_label = history.CARD_LABELS.get(card, card)
    if kind == KIND_WIZARD:
        draft = store.get_draft(target_id)
        if draft is None:
            return f"{card_label} · Entwurf {target_id} (gibt's nicht mehr)", None
        what = "neue Runde" if draft.event_id is None else f"Bearbeitung von Event {draft.event_id}"
        lines = [f"{card_label} · Entwurf {draft.id} ({what})", f"Schritt: `{draft.step}`"]
        if draft.data.script is not None:
            lines.append(f"Skript: {discord.utils.escape_markdown(draft.data.script.display_name)}")
        return "\n".join(lines), list((draft.ui or {}).get(history.UI_KEY) or [])
    if kind == KIND_START:
        if card == "testcard":
            return f"{card_label} im Willkommens-Channel", None
        return f"{card_label} von /botc, noch kein Entwurf", None
    event = store.get_event(target_id, include_deleted=True)
    lines = [f"{card_label} · Event {target_id}"]
    if event is not None:
        from events.templates import full_title
        title = discord.utils.escape_markdown(full_title(event.data))
        if event.channel_id and event.message_id:
            title = f"[{title}](https://discord.com/channels/{event.guild_id}/{event.channel_id}/{event.message_id})"
        lines.append(title)
    return "\n".join(lines), None


def build_feedback_embed(bot, kind: str, target_id: int, card: str, category: str, text: str,
                         name: str, user_id: int) -> discord.Embed:
    label, color = FEEDBACK_KINDS.get(category, ("", NEUTRAL_COLOR))
    card_label = history.CARD_LABELS.get(card, card)
    embed = discord.Embed(title=f"{label} · {card_label}" if label else card_label,
                          description=text.strip()[:TEXT_MAX], color=color, timestamp=now())
    where, entries = _where(bot, kind, target_id, card)
    if entries is None:
        entries = history.user_entries(user_id)
    embed.add_field(name="Von", value=discord.utils.escape_markdown(name), inline=False)
    embed.add_field(name="Wo", value=where[:1024], inline=False)
    embed.add_field(name="Davor", value="\n".join(history.recent(entries))[:1024] or "nichts mitgeschrieben",
                    inline=False)
    embed.set_footer(text=f"User-ID {user_id}")
    return embed
