"""Doppelanmeldungen in Discord: Hinweis beim Zusagen und Entscheidungs-DM (Logik: events/conflicts.py).

Der Button in der DM ist ein DynamicItem (`dbl:<event_id>`): „Ich spiele X“ meldet die Person von den
anderen zeitgleichen Runden ab und aktualisiert deren Posts.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import discord

from events import conflicts, guild_lock
from events.schema import BERLIN_TZ
from events.store import EventRecord, Store
from events.templates import SIGNUP_RULES_URL, base_title

logger = logging.getLogger(__name__)

DM_COLOR = 0x5865F2


def now() -> datetime:
    return datetime.now(BERLIN_TZ)


def _when(event: EventRecord) -> str:
    start = event.data.start.astimezone(BERLIN_TZ)
    from events.parse import WEEKDAY_NAMES
    return f"{WEEKDAY_NAMES[start.weekday()][:2]} {start:%H:%M}"


def _name(event: EventRecord) -> str:
    """Rundenname ohne Symbole (für Buttons und Hinweise)."""
    return event.data.title.strip() or base_title(event.data)


def _rules_link() -> str:
    return f"[Regeln zum Anmelden für BotC-Runden]({SIGNUP_RULES_URL})"


def signup_hint(event: EventRecord, group: list[EventRecord]) -> str:
    """Hinweis direkt nach dem Zusagen (nur für die Person sichtbar)."""
    others = [e for e in group if e.id != event.id]
    names = ", ".join(f"**{discord.utils.escape_markdown(_name(e))}** ({_when(e)})" for e in others)
    return (f"Du bist zur gleichen Zeit auch für {names} angemeldet. Bitte beachte dafür unsere {_rules_link()}: "
            f"Entscheide dich spätestens {conflicts.DECIDE_HOURS_BEFORE} Stunden vor Beginn der früheren Runde.")


def decision_layout(group: list[EventRecord], notice: str | None = None) -> discord.ui.LayoutView:
    lines = ["**Du bist für mehrere Runden zur gleichen Zeit angemeldet**",
             "Für welche entscheidest du dich? Die anderen Anmeldungen nehme ich dann raus."]
    for e in group:
        lines.append(f"- {discord.utils.escape_markdown(_name(e))}, <t:{int(e.data.start.timestamp())}:F>")
    lines.append(f"-# Mehr dazu in den {_rules_link()}.")
    if notice:
        lines.append(notice)
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(discord.ui.Container(discord.ui.TextDisplay("\n".join(lines)), accent_colour=DM_COLOR))
    if notice is None:
        row = discord.ui.ActionRow()
        for e in group[:5]:
            row.add_item(ChooseButton(e.id, f"Ich spiele {_name(e)}"[:70] + f" ({_when(e)})"))
        layout.add_item(row)
    return layout


async def send_decision_dm(bot: discord.Client, user_id: int, group: list[EventRecord]) -> bool:
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        await user.send(view=decision_layout(group))
        return True
    except discord.HTTPException as e:
        logger.info("Entscheidungs-DM an %s nicht zugestellt: %s", user_id, e)
        return False


async def check_decisions(bot: discord.Client, store: Store, guild_id: int, t: datetime):
    """Für die Reminder-Schleife: Runden, die in den nächsten 3 Stunden beginnen. Wer dort zugesagt hat und
    zeitgleich noch woanders, bekommt einmal die Entscheidungs-DM (an der frühesten Runde vermerkt)."""
    from events.store import RSVP_ACCEPTED
    from datetime import timedelta

    ts = int(t.timestamp())
    until = int((t + timedelta(hours=conflicts.DECIDE_HOURS_BEFORE)).timestamp()) + 60
    for event in store.list_events(guild_id, start_from=ts, start_until=until):
        if event.data.is_other_event:
            continue
        for rsvp in store.list_rsvps(event.id):
            if rsvp.status != RSVP_ACCEPTED:
                continue
            group = conflicts.conflict_group(store, event, rsvp.user_id, t)
            if not conflicts.decision_due(group, t) or group[0].id != event.id:
                continue  # keine Doppelanmeldung, noch zu früh, oder an einer anderen Runde vermerkt
            key = conflicts.notice_key(rsvp.user_id)
            if key in store.sent_reminders(event.id):
                continue
            store.mark_reminder_sent(event.id, key, ts)  # erst vermerken: lieber eine DM zu wenig als doppelt
            await send_decision_dm(bot, rsvp.user_id, group)


class ChooseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"dbl:(?P<event_id>\d+)"):
    def __init__(self, event_id: int, label: str = "Diese Runde"):
        super().__init__(discord.ui.Button(label=label, style=discord.ButtonStyle.primary,
                                           custom_id=f"dbl:{event_id}"))
        self.event_id = event_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["event_id"]), item.label or "Diese Runde")

    async def callback(self, interaction: discord.Interaction):
        from discord_ui.event_post import update_event_message  # zirkulären Import vermeiden

        bot, store = interaction.client, interaction.client.store
        chosen = store.get_event(self.event_id)
        if chosen is None or not guild_lock.is_allowed(chosen.guild_id):
            await interaction.response.edit_message(view=decision_layout([], "Diese Runde gibt es nicht mehr."))
            return
        group = conflicts.conflict_group(store, chosen, interaction.user.id, now())
        others = [e for e in group if e.id != chosen.id]
        for e in others:
            store.remove_rsvp(e.id, interaction.user.id)
        names = ", ".join(discord.utils.escape_markdown(_name(e)) for e in others)
        notice = (f"Erledigt: Du spielst **{discord.utils.escape_markdown(_name(chosen))}**."
                  + (f" Von {names} bist du abgemeldet." if others else ""))
        await interaction.response.edit_message(view=decision_layout(group, notice))
        for e in others:
            try:
                await update_event_message(bot, store, e, images_changed=False)
            except discord.HTTPException:
                logger.exception("Event-Post %s nach Doppelanmeldungs-Entscheidung nicht aktualisiert", e.id)
