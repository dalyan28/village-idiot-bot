"""Einhängepunkte für den Bestandscode (dort mit `# TESTSERVER` markiert).

Jede Funktion tut nichts, wenn TEST_SERVER nicht gesetzt ist oder der Server kein
Testserver ist. Fehler hier dürfen den Wizard nie stören: sie werden nur geloggt.
"""

from __future__ import annotations

import functools
import logging
import time

import discord

from testserver import history, is_test_guild

logger = logging.getLogger(__name__)

MAX_COMPONENTS = 40
MAX_BUTTONS_PER_ROW = 5


def _quiet(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception("Testserver-Hook %s fehlgeschlagen", fn.__name__)
    return wrapper


# ── Feedback-Button ──────────────────────────────────────────────────────────


@_quiet
def wizard_card(layout: discord.ui.LayoutView, draft, card: str):
    """Hängt „Feedback“ an eine Wizard-Karte: in die letzte Button-Zeile mit Platz, sonst in eine neue.

    Verdrängt keinen vorhandenen Button. Ist die Karte an der Grenze von 40 Komponenten, bleibt sie ohne.
    """
    if not is_test_guild(draft.guild_id):
        return
    from testserver.feedback import KIND_WIZARD, FeedbackButton

    button = FeedbackButton(KIND_WIZARD, draft.id, card)
    used = sum(1 for _ in layout.walk_children())
    rows = [i for i in layout.children if isinstance(i, discord.ui.ActionRow)]
    free = [r for r in rows if len(r.children) < MAX_BUTTONS_PER_ROW and all(_is_button(c) for c in r.children)]
    if free and used + 1 <= MAX_COMPONENTS:
        free[-1].add_item(button)
    elif used + 2 <= MAX_COMPONENTS:
        row = discord.ui.ActionRow()
        row.add_item(button)
        layout.add_item(row)


def _is_button(item) -> bool:
    """Ein Select belegt eine ganze Zeile; dort passt kein Button dazu."""
    if isinstance(item, discord.ui.DynamicItem):
        item = item.item
    return isinstance(item, discord.ui.Button)


@_quiet
def start_card(layout: discord.ui.LayoutView, guild_id: int):
    """„Feedback“ an der Startnachricht von /botc (noch ohne Entwurf, deshalb mit der Server-ID)."""
    if not is_test_guild(guild_id):
        return
    from testserver.feedback import KIND_START, FeedbackButton

    rows = [i for i in layout.children if isinstance(i, discord.ui.ActionRow)]
    if rows and len(rows[-1].children) < MAX_BUTTONS_PER_ROW:
        rows[-1].add_item(FeedbackButton(KIND_START, guild_id, "start"))


@_quiet
def event_view(view: discord.ui.View, event):
    """„Feedback“ am Event-Post, in einer eigenen Zeile unter den fünf vorhandenen Buttons."""
    if not is_test_guild(event.guild_id):
        return
    from testserver.feedback import KIND_EVENT, FeedbackButton

    view.add_item(FeedbackButton(KIND_EVENT, event.id, row=1))


# ── Aktions-Historie ─────────────────────────────────────────────────────────


def _record(ctx, text: str):
    ts = int(time.time())
    ui = history.append(ctx.ui, text, ts)
    ctx.set_ui(ui)
    history.remember(ctx.draft.user_id, text, ts)


@_quiet
def wizard_button(ctx, name: str, arg: str | None):
    if is_test_guild(ctx.draft.guild_id):
        _record(ctx, history.describe_button(name, arg, ctx.draft.ui))


@_quiet
def wizard_select(ctx, name: str, values: list[str]):
    if is_test_guild(ctx.draft.guild_id):
        _record(ctx, history.describe_select(name, values))


@_quiet
def wizard_modal(ctx, modal):
    if is_test_guild(ctx.draft.guild_id):
        _record(ctx, history.describe_modal(modal))


@_quiet
def start_button(interaction: discord.Interaction, guild_id: int, name: str):
    if is_test_guild(guild_id):
        text = {"new": "Termin festlegen bzw. Neu beginnen geklickt", "resume": "Entwurf fortsetzen geklickt"}
        history.remember(interaction.user.id, text.get(name, name), int(time.time()))


@_quiet
def event_button(interaction: discord.Interaction, event, name: str):
    if is_test_guild(event.guild_id):
        text = f"{history.EVENT_ACTIONS.get(name, name)} (Event {event.id})"
        history.remember(interaction.user.id, text, int(time.time()))
