"""Eigene Standardwerte: robust speichern, beim Anlegen übernehmen, Teensyville-Regel, Dialoge (Dalyan, 26.10.2026)."""

import asyncio
from types import SimpleNamespace

import discord
import pytest

from events import service, user_settings
from events.permissions import AccessSettings, Actor
from events.user_settings import UserDefaults
from tests.test_wizard_flow import GUILD, NOW, USER, click, env, new_draft, run  # noqa: F401 (Fixture)


def test_tolerant_reading_keeps_good_fields():
    d = UserDefaults.from_dict({"version": 1, "max_players": 10, "duration_minutes": "lang", "level": "Profi",
                                "camera": "unbekannt", "co_st_status": "open", "co_st_note": "gern Neulinge",
                                "zukunft": True})
    assert d.max_players == 10 and d.level == "Profi" and d.co_st_status == "open"
    assert d.duration_minutes is None and d.camera is None  # kaputte Felder → eingebauter Standard
    assert UserDefaults.from_dict(None) == UserDefaults() and UserDefaults.from_dict("Unsinn") == UserDefaults()


def test_store_roundtrip_and_broken_json():
    from events.store import Store
    store = Store(":memory:")
    user_settings.save(store, 1, 2, UserDefaults(max_players=8, description="Vorlage"), 100)
    assert user_settings.get(store, 1, 2) == UserDefaults(max_players=8, description="Vorlage")
    assert user_settings.get(store, 1, 3) == UserDefaults()  # andere Person: eingebaute Standards
    assert user_settings.get(store, 9, 2) == UserDefaults()  # anderer Server: eigene Werte
    with store.conn:
        store.conn.execute("UPDATE user_settings SET data = '{kaputt' WHERE user_id = 2")
    assert user_settings.get(store, 1, 2) == UserDefaults()  # kein Absturz
    store.close()


def test_new_draft_starts_with_own_defaults(env):
    from events.schema import EventData
    bot = env
    user_settings.save(bot.store, GUILD, USER, UserDefaults(
        description="Meine Vorlage", max_players=10, duration_minutes=180, level="Erfahren", camera="required",
        camera_note="gern mit Kamera", co_st_status="open", co_st_note="gern Neulinge"), 0)
    draft = service.start_draft(bot.store, GUILD, Actor(USER, is_admin=True), "Dalyan", EventData(start=NOW.replace(
        day=NOW.day + 5)), NOW)
    d = draft.data
    assert (d.description, d.max_players, d.duration_minutes, d.level) == ("Meine Vorlage", 10, 180, "Erfahren")
    assert (d.camera, d.camera_note, d.co_st_status, d.co_st_note) == ("required", "gern mit Kamera", "open",
                                                                        "gern Neulinge")
    assert draft.ui["base_players"] == 10


def test_teensy_sets_six_and_back_to_own_default(env, monkeypatch):
    """Teensyville setzt immer 6; ohne Teensyville wieder der eigene Standard (hier 10)."""
    from discord_ui import wizard
    from events.schema import EventData, ScriptRef
    from tests.test_wizard_flow import FakeInteraction
    bot = env
    user_settings.save(bot.store, GUILD, USER, UserDefaults(max_players=10), 0)
    draft = service.start_draft(bot.store, GUILD, Actor(USER, is_admin=True), "Dalyan",
                                EventData(start=NOW.replace(day=NOW.day + 5)), NOW)

    async def no_rater(script):
        return None
    monkeypatch.setattr(wizard, "rate_script", no_rater)
    teensy = ScriptRef(kind="upload", name="Klein", characters=["imp"], teensy=True)
    normal = ScriptRef(kind="upload", name="Groß", characters=["imp"])

    async def go():
        result = []
        for script in (teensy, normal):
            inter = FakeInteraction(bot, bot.guild.get_member(USER))
            ctx = await wizard.load_context(inter, draft.id)
            await wizard._set_script(inter, ctx, script)
            result.append(bot.store.get_draft(draft.id).data.max_players)
        return result
    assert asyncio.run(go()) == [6, 10]


def test_camera_note_shown():
    from events.schema import EventData
    from events.templates import camera_text
    assert camera_text(EventData()) == "Keine Pflicht"
    assert camera_text(EventData(camera="required", camera_note="Video an")) == "Pflicht · Video an"


def test_settings_cards_and_dialogs(env):
    from discord_ui import user_settings as ui
    bot = env

    def texts(view):
        return " ".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))

    overview = ui.overview_layout(bot.guild)
    assert "**Standardwerte**" in texts(overview)
    card = ui.defaults_layout(bot.guild, UserDefaults())
    assert "`12 (Standard)`" in texts(card) and "`150 Minuten (Standard)`" in texts(card)

    screens = []

    async def edit_message(**kw):
        screens.append(kw)
    inter = SimpleNamespace(client=bot, user=SimpleNamespace(id=USER), response=SimpleNamespace(edit_message=edit_message))

    # Jedes Feld einzeln mit eigenem „Ändern“
    actions = [s.accessory.custom_id.split(":")[2] for s in card.walk_children() if isinstance(s, discord.ui.Section)]
    assert actions == ["description", "players", "duration", "level", "camera", "cost"]

    modal = ui.PlayersDefaultModal(bot.guild, UserDefaults())
    modal.players._value = "300"
    run(modal.on_submit(inter))
    assert "zwischen 1 und 200" in texts(screens[-1]["view"]) and user_settings.get(bot.store, GUILD, USER).is_empty()

    modal.players._value = "8"
    run(modal.on_submit(inter))
    modal = ui.DurationDefaultModal(bot.guild, UserDefaults())
    modal.duration._value = "200"
    run(modal.on_submit(inter))
    assert user_settings.get(bot.store, GUILD, USER) == UserDefaults(max_players=8, duration_minutes=200)
    assert "`8`" in texts(screens[-1]["view"]) and "Gespeichert." in texts(screens[-1]["view"])

    modal = ui.CoStDefaultModal(bot.guild, UserDefaults())
    modal.status._value, modal.note._value = "open", "gern Neulinge"
    run(modal.on_submit(inter))
    assert "Ja, frei · gern Neulinge" in texts(screens[-1]["view"])
