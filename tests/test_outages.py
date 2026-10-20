"""Ausfälle von ScriptRater und botcscripts.com: klare Meldung statt „fehlt“/„keine Treffer“, Ausweg bleibt."""

import asyncio

import discord
import pytest
import requests

from events import rating
from events.schema import SCRIPT_BOTCSCRIPTS, ScriptRef
from logic import botcscripts
from tests.test_wizard_flow import (  # noqa: F401  (Fixture env)
    USER,
    FakeInteraction,
    click,
    env,
    new_draft,
    run,
)


def script():
    return ScriptRef(kind=SCRIPT_BOTCSCRIPTS, name="X", characters=["imp"])


class TestRater:
    def test_timeout(self, monkeypatch):
        def slow(*a, **kw):
            raise requests.Timeout()
        monkeypatch.setattr(rating.requests, "post", slow)
        with pytest.raises(rating.RatingUnavailable) as e:
            asyncio.run(rating.rate_script(script()))
        assert e.value.timeout

    def test_server_error_and_garbage(self, monkeypatch):
        class Resp:
            def __init__(self, status, payload):
                self.status_code, self._payload, self.text = status, payload, "x"

            def json(self):
                return self._payload

        monkeypatch.setattr(rating.requests, "post", lambda *a, **kw: Resp(502, {}))
        with pytest.raises(rating.RatingUnavailable) as e:
            asyncio.run(rating.rate_script(script()))
        assert not e.value.timeout
        monkeypatch.setattr(rating.requests, "post", lambda *a, **kw: Resp(200, {"rating": "purple"}))
        with pytest.raises(rating.RatingUnavailable):
            asyncio.run(rating.rate_script(script()))


class TestBotcScripts:
    def test_unreachable_is_not_no_results(self, monkeypatch):
        monkeypatch.setattr(botcscripts, "_get", lambda url: None)
        with pytest.raises(botcscripts.BotcScriptsUnavailable):
            asyncio.run(botcscripts.search_scripts("boo"))

    def test_total_timeout(self, monkeypatch):
        monkeypatch.setattr(botcscripts, "TOTAL_TIMEOUT", 0.01)
        monkeypatch.setattr(botcscripts, "_search_sync", lambda q, limit: __import__("time").sleep(0.2) or [])
        with pytest.raises(botcscripts.BotcScriptsUnavailable):
            asyncio.run(botcscripts.search_scripts("boo"))


def test_wizard_shows_rater_outage_and_manual_rating_clears_it(env, monkeypatch):
    from discord_ui import wizard

    async def down(script):
        raise rating.RatingUnavailable("timeout")

    async def fake_download(script_id, version):
        return [{"id": "_meta", "name": "Boo", "author": "A"}, {"id": "imp"}]

    bot = env
    monkeypatch.setattr(wizard, "rate_script", down)
    monkeypatch.setattr(botcscripts, "download_script", fake_download)
    draft = new_draft(bot)
    bot.store.set_draft_ui(draft.id, {"v2": True, "search_results": [{"id": "1", "version": "1"}]})
    bot.store.update_draft(draft.id, bot.store.get_draft(draft.id).data, "preview", 0)
    inter = FakeInteraction(bot, bot.guild.get_member(USER), values=["1|1"])
    run(wizard.WizardSelect(draft.id, "result", [], "x").callback(inter))

    d = bot.store.get_draft(draft.id)
    assert d.data.rating is None and "zu lange" in d.ui["rating_error"]
    texts = " ".join(i.content for i in inter.screen["view"].walk_children() if isinstance(i, discord.ui.TextDisplay))
    assert "Der ScriptRater braucht gerade zu lange" in texts
    labels = [getattr(getattr(i, "item", i), "label", "") for i in inter.screen["view"].walk_children()]
    assert "Schwierigkeit wählen" in labels

    inter = click(bot, draft.id, "fix_field", "rating")
    modal = inter.response.modal
    modal.rating._value = "yellow"
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    d = bot.store.get_draft(draft.id)
    assert d.data.rating == "yellow" and "rating_error" not in d.ui


def test_search_outage_message(env, monkeypatch):
    from discord_ui.wizard import SearchModal

    async def down(query, limit=10):
        raise botcscripts.BotcScriptsUnavailable("timeout")

    bot = env
    monkeypatch.setattr(botcscripts, "search_scripts", down)
    draft = new_draft(bot)
    bot.store.set_draft_ui(draft.id, {"v2": True})
    modal = SearchModal(draft.id, "")
    modal.query._value = "boo"
    inter = FakeInteraction(bot, bot.guild.get_member(USER))
    run(modal.on_submit(inter))
    texts = " ".join(i.content for i in inter.screen["view"].walk_children() if isinstance(i, discord.ui.TextDisplay))
    assert "botcscripts.com antwortet gerade nicht" in texts and "JSON hochladen" in texts


def test_busy_message_while_searching(env, monkeypatch):
    """Während der Suche ersetzt eine Statusmeldung (ohne Buttons) die Karte, danach kommt die Karte zurück."""
    from discord_ui.wizard import SearchModal

    async def search(query, limit=10):
        return []

    bot = env
    monkeypatch.setattr(botcscripts, "search_scripts", search)
    draft = new_draft(bot)
    bot.store.set_draft_ui(draft.id, {"v2": True})
    modal = SearchModal(draft.id, "")
    modal.query._value = "boo"
    inter = FakeInteraction(bot, bot.guild.get_member(USER))
    screens = []

    async def record(**kw):
        screens.append(kw)
    inter.edit_original_response = record
    run(modal.on_submit(inter))

    def texts(view):
        return " ".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))

    assert "Einen Moment" in texts(screens[0]["view"]) and "„boo“" in texts(screens[0]["view"])
    assert not any(getattr(i, "custom_id", None) for i in screens[0]["view"].walk_children())  # keine Buttons
    assert "Keine Treffer" in texts(screens[-1]["view"])
