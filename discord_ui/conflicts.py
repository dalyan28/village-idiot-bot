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
    return f"[Anmelderegeln]({SIGNUP_RULES_URL})"


def _decide_text() -> str:
    """Die Regel als Bitte (Dalyan, 27.10.2026), gleich im Hinweis und in der DM."""
    return (f"Bitte entscheide dich bis spätestens {conflicts.DECIDE_HOURS_BEFORE} Stunden vor Beginn der früheren "
            f"Runde für eine und melde dich von den anderen ab ({_rules_link()}).")


def signup_hint(event: EventRecord, group: list[EventRecord]) -> str:
    """Hinweis direkt nach dem Zusagen (nur für die Person sichtbar)."""
    others = [e for e in group if e.id != event.id]
    names = ", ".join(f"**{discord.utils.escape_markdown(_name(e))}** ({_when(e)})" for e in others)
    return f"Du bist zur gleichen Zeit auch für {names} angemeldet. {_decide_text()}"


def _event_link(event: EventRecord) -> str:
    name = discord.utils.escape_markdown(_name(event))
    if event.channel_id and event.message_id:
        return f"[{name}](https://discord.com/channels/{event.guild_id}/{event.channel_id}/{event.message_id})"
    return name


def decision_layout(group: list[EventRecord], notice: str | None = None, make_button=None,
                    make_ignore=None) -> discord.ui.LayoutView:
    """Entscheidungs-DM (Dalyan, 27.10.2026: nüchtern, die Regel kurz erklärt, Links zu den Events).
    `make_button(event, label)` und `make_ignore()` liefern die Buttons (Standard: ChooseButton)."""
    make_button = make_button or (lambda e, label: ChooseButton(e.id, label))
    make_ignore = make_ignore or (lambda: ChooseButton(None, "Ignorieren"))
    lines = ["**Doppelanmeldung**",
             f"Du bist für Runden angemeldet, die sich zeitlich überschneiden. {_decide_text()}"]
    for e in group:
        lines.append(f"- {_event_link(e)} · <t:{int(e.data.start.timestamp())}:F>")
    if notice:
        lines.append(f"\n{notice}")
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(discord.ui.Container(discord.ui.TextDisplay("\n".join(lines)), accent_colour=DM_COLOR))
    if notice is None and group:
        row = discord.ui.ActionRow()
        for e in group[:4]:
            row.add_item(make_button(e, f"Ich spiele {_name(e)}"[:70] + f" ({_when(e)})"))
        row.add_item(make_ignore())
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


def choice_notice(chosen: EventRecord, others: list[EventRecord]) -> str:
    names = ", ".join(discord.utils.escape_markdown(_name(e)) for e in others)
    return (f"Erledigt: Du spielst **{discord.utils.escape_markdown(_name(chosen))}**."
            + (f" Von {names} bist du abgemeldet." if others else ""))


IGNORED_NOTICE = "Ignoriert. Deine Anmeldungen bleiben, wie sie sind."
EXPIRED_NOTICE = "Diese Auswahl ist nicht mehr aktuell. An deinen Anmeldungen hat sich nichts geändert."
RESOLVED_NOTICE = "Hat sich erledigt. Du bist nicht mehr zeitgleich für mehrere Runden angemeldet."


class ChooseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"dbl:(?P<event_id>\d+|ignore)"):
    """`dbl:<event_id>` = „Ich spiele diese Runde“, `dbl:ignore` = nichts ändern."""

    def __init__(self, event_id: int | None, label: str = "Diese Runde"):
        style = discord.ButtonStyle.secondary if event_id is None else discord.ButtonStyle.primary
        super().__init__(discord.ui.Button(label=label, style=style,
                                           custom_id=f"dbl:{'ignore' if event_id is None else event_id}"))
        self.event_id = event_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        event_id = None if match["event_id"] == "ignore" else int(match["event_id"])
        return cls(event_id, item.label or "Diese Runde")

    async def callback(self, interaction: discord.Interaction):
        from discord_ui.event_post import update_event_message  # zirkulären Import vermeiden

        if self.event_id is None:
            await interaction.response.edit_message(view=decision_layout([], IGNORED_NOTICE))
            return
        bot, store = interaction.client, interaction.client.store
        chosen = store.get_event(self.event_id)
        t = now()
        # Nicht mehr aktuell: Runde gibt es nicht mehr oder sie hat schon begonnen (DM von gestern o. Ä.)
        if chosen is None or not guild_lock.is_allowed(chosen.guild_id) or chosen.data.start <= t:
            await interaction.response.edit_message(view=decision_layout([], EXPIRED_NOTICE))
            return
        group = conflicts.conflict_group(store, chosen, interaction.user.id, t)
        others = [e for e in group if e.id != chosen.id]
        if not others:
            await interaction.response.edit_message(view=decision_layout([], RESOLVED_NOTICE))
            return
        for e in others:
            store.remove_rsvp(e.id, interaction.user.id)
        await interaction.response.edit_message(view=decision_layout(group, choice_notice(chosen, others)))
        for e in others:
            try:
                await update_event_message(bot, store, e, images_changed=False)
            except discord.HTTPException:
                logger.exception("Event-Post %s nach Doppelanmeldungs-Entscheidung nicht aktualisiert", e.id)
