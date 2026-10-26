"""/meine_events: Wofür bin ich angemeldet? Je Event ein Abschnitt mit „Abmelden“ daneben (Dalyan, 26.10.2026).

Die Liste ist ephemer (nur für die Person sichtbar). „Abmelden“ entfernt die Anmeldung, aktualisiert den
Event-Post und zeigt die Liste neu. Der Button ist ein DynamicItem (`leave:<event_id>`) und funktioniert
nach einem Neustart weiter.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import discord

from events import guild_lock, service
from events.schema import BERLIN_TZ
from events.store import RSVP_ACCEPTED, RSVP_TENTATIVE, EventRecord, Store
from events.templates import full_title

logger = logging.getLogger(__name__)

MAX_SHOWN = 10  # je Event 3 Komponenten; Discord erlaubt 40 je Nachricht
LIST_COLOR = 0x5865F2


def now() -> datetime:
    return datetime.now(BERLIN_TZ)


def my_events(store: Store, guild_id: int, user_id: int, now_: datetime) -> list[tuple[EventRecord, str]]:
    """Kommende Events, für die die Person zugesagt hat (auch Warteliste) oder vorläufig ist, mit Status-Text."""
    result = []
    for event in store.list_events(guild_id, start_from=int(now_.timestamp())):
        rsvp = store.get_rsvp(event.id, user_id)
        if rsvp is None or rsvp.status not in (RSVP_ACCEPTED, RSVP_TENTATIVE):
            continue
        if rsvp.status == RSVP_TENTATIVE:
            status = "Vorläufig"
        else:
            lists = service.rsvp_lists(store, event)
            waiting = [p.user_id for p in lists.waitlist]
            status = f"Warteliste, Platz {waiting.index(user_id) + 1}" if user_id in waiting else "Zugesagt"
        result.append((event, status))
    return result


def my_events_layout(store: Store, guild: discord.Guild, user_id: int, notice: str | None = None):
    entries = []
    for event, status in my_events(store, guild.id, user_id, now()):
        url = (f"https://discord.com/channels/{event.guild_id}/{event.channel_id}/{event.message_id}"
               if event.channel_id and event.message_id else None)
        entries.append({"key": event.id, "title": full_title(event.data), "start_ts": int(event.data.start.timestamp()),
                        "status": status, "url": url})
    return my_events_card(guild.name, entries, notice, lambda entry: LeaveButton(entry["key"]))


def my_events_card(guild_name: str, entries: list[dict], notice: str | None, make_button) -> discord.ui.LayoutView:
    """Die Karte selbst. `entries`: dicts mit key, title, start_ts, status, url; `make_button(entry)` liefert
    den „Abmelden“-Button (so lässt sich die Karte auch mit erfundenen Runden zeigen)."""
    esc = discord.utils.escape_markdown
    container = discord.ui.Container(accent_colour=LIST_COLOR)
    head = f"-# {esc(guild_name)}\n\n**Deine Anmeldungen**"
    if notice:
        head += f"\n{notice}"
    if not entries:
        head += "\nDu bist für keine kommende Runde angemeldet."
    container.add_item(discord.ui.TextDisplay(head))
    for entry in entries[:MAX_SHOWN]:
        ts = entry["start_ts"]
        title = esc(entry["title"])
        if entry.get("url"):
            title = f"[{title}]({entry['url']})"
        text = f"**{title}**\n<t:{ts}:F> · <t:{ts}:R>\nStatus: `{entry['status']}`"
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(text), accessory=make_button(entry)))
    if len(entries) > MAX_SHOWN:
        container.add_item(discord.ui.TextDisplay(
            f"-# Dazu {len(entries) - MAX_SHOWN} weitere. Abmelden kannst du dich dort direkt im Event-Post."))
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    return layout


class LeaveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"leave:(?P<event_id>\d+)"):
    def __init__(self, event_id: int):
        super().__init__(discord.ui.Button(label="Abmelden", style=discord.ButtonStyle.danger,
                                           custom_id=f"leave:{event_id}"))
        self.event_id = event_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["event_id"]))

    async def callback(self, interaction: discord.Interaction):
        from discord_ui.event_post import update_event_message  # zirkulären Import vermeiden

        bot, store = interaction.client, interaction.client.store
        event = store.get_event(self.event_id)
        guild = bot.get_guild(event.guild_id) if event else None
        if event is None or guild is None or not guild_lock.is_allowed(event.guild_id):
            await interaction.response.send_message("Dieses Event gibt es nicht mehr.", ephemeral=True)
            return
        notice = None
        if store.get_rsvp(event.id, interaction.user.id) is not None:
            store.remove_rsvp(event.id, interaction.user.id)
            notice = f"Du bist von „{discord.utils.escape_markdown(full_title(event.data))}“ abgemeldet."
        await interaction.response.edit_message(view=my_events_layout(store, guild, interaction.user.id, notice))
        try:
            await update_event_message(bot, store, event, images_changed=False)
        except discord.HTTPException:
            logger.exception("Event-Post %s nach Abmeldung nicht aktualisiert", event.id)
