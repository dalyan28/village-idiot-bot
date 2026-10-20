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
    assert m.date.default == "31.02." and m.players.default == "8"
    assert [o.value for o in m.level.options if o.default] == ["Profi"]
    assert [o.value for o in m.options.options if o.default] == ["casual"]


def test_wizard_custom_id_matches_template():
    cid = custom_id(42, "cancel")
    match = WizardButton.__discord_ui_compiled_template__.fullmatch(cid)
    assert match and match["draft_id"] == "42" and match["name"] == "cancel" and match["arg"] is None
    match = WizardButton.__discord_ui_compiled_template__.fullmatch(custom_id(7, "pick", "trouble_brewing"))
    assert match["arg"] == "trouble_brewing"
    assert len(custom_id(10**18, "select_version", "x" * 40)) <= 100  # Discord-Grenze für custom_id
