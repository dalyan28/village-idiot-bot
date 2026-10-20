"""Smoke-Tests der Discord-Anbindung ohne Verbindung zu Discord: Cogs laden, Modal bauen."""

import asyncio

import discord
from discord.ext import commands

from discord_ui.botc_modal import BotcModal
from discord_ui.wizard import WizardButton, custom_id
from events.intake import ModalInput
from events.store import Store


def run(coro):
    return asyncio.run(coro)


def test_cogs_register_commands():
    async def go():
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        bot.store = Store(":memory:")
        for ext in ("commands.settings", "commands.overview", "commands.event_settings", "commands.botc",
                    "commands.reminder"):
            await bot.load_extension(ext)
        names = {c.name for c in bot.tree.get_commands()}
        await bot.unload_extension("commands.reminder")  # Hintergrund-Schleifen stoppen
        return names

    names = run(go())
    assert {"botc", "set_event_roles", "see_event_roles", "set_academy_access", "set_event_channel",
            "set_reminders", "see_reminders", "update_characters"} <= names


def test_modal_has_five_components_and_hides_academy():
    async def go():
        with_academy = BotcModal(Store(":memory:"), allow_academy=True)
        without = BotcModal(Store(":memory:"), allow_academy=False)
        return with_academy, without

    with_academy, without = run(go())
    assert len(with_academy.children) == 5
    assert [o.value for o in with_academy.options.options] == ["academy", "casual", "recorded", "camera"]
    assert "academy" not in [o.value for o in without.options.options]
    assert without.options.max_values == 3


def test_modal_prefill_after_error():
    async def go():
        return BotcModal(Store(":memory:"), True, ModalInput("31.02.", "20", "8", "Profi", ["casual"]))

    m = run(go())
    # Datum außerhalb der Auswahl → „Anderes Datum“ mit Text; Uhrzeit ebenso
    assert m.date.default == "31.02." and [o.value for o in m.date_choice.options if o.default] == ["other"]
    assert m.time.default == "20" and [o.value for o in m.time_choice.options if o.default] == ["other"]
    assert [o.value for o in m.options.options if o.default] == ["casual"]


def test_wizard_custom_id_matches_template():
    cid = custom_id(42, "cancel")
    match = WizardButton.__discord_ui_compiled_template__.fullmatch(cid)
    assert match and match["draft_id"] == "42" and match["name"] == "cancel" and match["arg"] is None
    match = WizardButton.__discord_ui_compiled_template__.fullmatch(custom_id(7, "pick", "trouble_brewing"))
    assert match["arg"] == "trouble_brewing"
    assert len(custom_id(10**18, "select_version", "x" * 40)) <= 100  # Discord-Grenze für custom_id


def test_botc_modal_is_slim_with_date_choices():
    async def go():
        return BotcModal(Store(":memory:"), allow_academy=False)

    m = run(go())
    assert len(m.children) == 5  # Datum-Auswahl, anderes Datum, Uhrzeit-Auswahl, andere Uhrzeit, Optionen
    labels = [o.label for o in m.date_choice.options]
    assert labels[0].startswith("Heute") and labels[1].startswith("Morgen") and len(labels) == 10
    assert m.date_choice.options[-1].value == "other"
    assert [o.value for o in m.time_choice.options] == ["13:00", "14:00", "19:00", "20:00", "other"]
    m.date_choice._value = m.date_choice.options[1].value
    m.time_choice._value = "19:00"
    raw = m.raw_input()
    assert raw.date_text == m.date_choice.options[1].value and raw.time_text == "19:00"
    assert raw.players_text == "12" and raw.level == "Alle"
    # „Andere Uhrzeit“ nimmt das Textfeld
    m.time_choice._value, m.time._value = "other", "18:30"
    assert m.raw_input().time_text == "18:30"
