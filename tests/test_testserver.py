"""Testserver (nur Branch testserver): Schalter, Feedback-Button, Aktions-Historie, Setup, Reset, Delete All.

Discord ist nachgebaut (Attrappen aus test_wizard_flow plus ein kleiner Server mit Channels und Rollen).
"""

import itertools
import json
from datetime import timedelta
from types import SimpleNamespace

import discord
import pytest
from discord.ext import commands

import config as bot_config
import tests.test_wizard_flow as flow
from discord_ui import wizard
from discord_ui.event_post import EventButton, event_view
from events import service
from events.permissions import Actor
from events.schema import SCRIPT_BOTCSCRIPTS, EventData, ScriptRef
from testserver import feedback, history, hooks, is_test_guild, registry, server, texts
from testserver.feedback import FeedbackButton

GUILD, USER, NOW = flow.GUILD, flow.USER, flow.NOW
run, click, FakeInteraction = flow.run, flow.click, flow.FakeInteraction
env = flow.env  # Fixture aus dem Wizard-Durchlauf


@pytest.fixture
def ts(env, monkeypatch, tmp_path):
    """Wizard-Umgebung mit eingeschaltetem Testserver und eigener config.json."""
    monkeypatch.setenv("TEST_SERVER", "1")
    monkeypatch.setenv("TEST_GUILD_IDS", str(GUILD))
    monkeypatch.setattr(bot_config, "CONFIG_FILE", str(tmp_path / "config.json"))
    history.forget_all()
    return env


def ids(view) -> list[str]:
    return [getattr(i, "custom_id", None) for i in view.walk_children() if getattr(i, "custom_id", None)]


# ── Schalter ─────────────────────────────────────────────────────────────────


def test_switch_needs_env_and_listed_guild(monkeypatch):
    monkeypatch.delenv("TEST_SERVER", raising=False)
    monkeypatch.setenv("TEST_GUILD_IDS", "10, 11")
    assert not is_test_guild(10)
    monkeypatch.setenv("TEST_SERVER", "1")
    assert is_test_guild(10) and is_test_guild(11) and not is_test_guild(12) and not is_test_guild(None)


def test_without_switch_nothing_changes(env, monkeypatch):
    """Ohne TEST_SERVER: keine Feedback-Buttons, keine Historie, alles wie auf event-wizard."""
    monkeypatch.delenv("TEST_SERVER", raising=False)
    bot = env
    draft = flow.new_draft(bot)
    inter = click(bot, draft.id, "pick", "trouble_brewing")
    assert not any(c.startswith("fb:") for c in ids(inter.screen["view"]))
    assert history.UI_KEY not in bot.store.get_draft(draft.id).ui


# ── Feedback-Button ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("step", ["script", "image", "preview"])
def test_feedback_button_on_every_card_within_limits(ts, step):
    bot = ts
    draft = flow.new_draft(bot)
    if step != "script":
        click(bot, draft.id, "pick", "trouble_brewing")
        bot.store.update_draft(draft.id, bot.store.get_draft(draft.id).data, step, int(NOW.timestamp()))
    layout, _ = run(wizard.render(bot, bot.store.get_draft(draft.id)))
    layout.to_components()
    card = {"script": "script", "image": "image", "preview": "summary"}[step]
    assert f"fb:w:{draft.id}:{card}" in ids(layout)
    assert sum(1 for _ in layout.walk_children()) <= 40
    assert len(set(ids(layout))) == len(ids(layout))  # custom_ids eindeutig
    for row in (i for i in layout.children if isinstance(i, discord.ui.ActionRow)):
        assert len(row.children) <= 5


def test_feedback_fits_on_fullest_script_card(ts):
    """Skript-Karte mit 5 Treffern, Blättern und Versions-Auswahl: der Button passt noch und verdrängt nichts."""
    bot = ts
    draft = flow.new_draft(bot)
    d = draft.data
    d.script = ScriptRef(kind=SCRIPT_BOTCSCRIPTS, name="Boo", version="1", botcscripts_id="5", characters=["imp"])
    bot.store.update_draft(draft.id, d, "script", int(NOW.timestamp()))
    bot.store.set_draft_ui(draft.id, {
        "query": "boo", "search_results": [{"id": str(i), "version": "1", "name": f"Boo {i}", "author": "A",
                                            "likes": 1, "type": "", "special": False} for i in range(7)],
        "versions": [{"id": "5", "version": str(v), "type": ""} for v in range(3)]})
    before_hook = run(_render_without_hook(bot, draft.id))
    layout, _ = run(wizard.render(bot, bot.store.get_draft(draft.id)))
    assert set(before_hook) < set(ids(layout)) and f"fb:w:{draft.id}:script" in ids(layout)
    assert sum(1 for _ in layout.walk_children()) <= 40


async def _render_without_hook(bot, draft_id):
    import os
    os.environ.pop("TEST_SERVER")
    try:
        layout, _ = await wizard.render(bot, bot.store.get_draft(draft_id))
    finally:
        os.environ["TEST_SERVER"] = "1"
    return ids(layout)


def test_card_at_limit_stays_without_button(ts):
    bot = ts
    draft = flow.new_draft(bot)
    layout = discord.ui.LayoutView()
    for _ in range(13):
        row = discord.ui.ActionRow()
        row.add_item(discord.ui.Button(label="x", custom_id=f"x{len(layout.children)}"))
        row.add_item(discord.ui.Button(label="y", custom_id=f"y{len(layout.children)}"))
        layout.add_item(row)
    layout.add_item(discord.ui.TextDisplay("z"))  # 40 Komponenten
    hooks.wizard_card(layout, draft, "summary")
    assert not any(c.startswith("fb:") for c in ids(layout))


def test_event_post_gets_feedback_in_own_row(ts):
    bot = ts
    event = _published_event(bot)
    view = event_view(event)
    fb = [i for i in view.children if getattr(i, "custom_id", "").startswith("fb:")]
    assert len(fb) == 1 and fb[0].custom_id == f"fb:e:{event.id}"
    assert [i.row for i in view.children if not i.custom_id.startswith("fb:")][:5] == [None] * 5
    assert fb[0].row == 1  # fünf Buttons oben, Feedback darunter (neben „[Dev] Reminder testen“)
    assert len(view.to_components()) == 2


def test_custom_id_template():
    for cid in ("fb:w:12:summary", "fb:e:7"):
        assert FeedbackButton.__discord_ui_compiled_template__.fullmatch(cid)
    assert len(feedback.feedback_custom_id("w", 10**18, "summary")) <= 100


# ── Historie und Feedback-Post ───────────────────────────────────────────────


class FeedbackChannel:
    id = 555

    def __init__(self):
        self.embeds = []

    async def send(self, embed=None, allowed_mentions=None, **kw):
        self.embeds.append(embed)


def _with_feedback_channel(bot) -> FeedbackChannel:
    channel = FeedbackChannel()
    registry.save(bot.store, GUILD, {"categories": {}, "channels": {"feedback": channel.id}, "roles": {},
                                     "messages": {}})
    old = bot.get_channel
    bot.get_channel = lambda cid: channel if cid == channel.id else old(cid)
    return channel


def test_history_and_feedback_post_from_wizard(ts, monkeypatch):
    bot = ts
    channel = _with_feedback_channel(bot)
    draft = flow.new_draft(bot)
    user = bot.guild.get_member(USER)
    click(bot, draft.id, "pick", "trouble_brewing")
    # Beschreibung vorbelegen: bei leerer Beschreibung fragt „Ändern“ direkt im Chat statt im Dialog
    d = bot.store.get_draft(draft.id)
    data = d.data
    data.description = "Entwurf"
    bot.store.update_draft(d.id, data, d.step, d.updated_at)
    inter = click(bot, draft.id, "edit_field", "description")
    modal = inter.response.modal
    modal.text._value = "Gemütliche Runde."
    run(modal.on_submit(FakeInteraction(bot, user)))
    entries = bot.store.get_draft(draft.id).ui[history.UI_KEY]
    assert [t for _, t in entries] == ["Basis-Skript gewählt: Trouble Brewing", "Ändern bei Beschreibung",
                                      "Beschreibung geschrieben (17 Zeichen)"]

    # Feedback-Button in der DM → Dialog → Post im Feedback-Channel
    inter = FakeInteraction(bot, SimpleNamespace(id=USER, display_name="dalyan_global"))
    run(FeedbackButton("w", draft.id, "summary").callback(inter))
    modal = inter.response.modal
    assert isinstance(modal, feedback.FeedbackModal) and modal.guild_id == GUILD
    modal.text._value = "Der rote Button ist super."
    modal.category._value = "like"
    done = FakeInteraction(bot, SimpleNamespace(id=USER, display_name="dalyan_global"))
    run(modal.on_submit(done))
    assert done.sent == [feedback.THANKS]
    embed = channel.embeds[0]
    fields = {f.name: f.value for f in embed.fields}
    assert embed.title == "Gefällt mir · Zusammenfassung" and embed.description == "Der rote Button ist super."
    assert fields["Von"] == "Dalyan"  # Name auf dem Server, als Text
    assert f"Entwurf {draft.id} (neue Runde)" in fields["Wo"] and "Trouble Brewing" in fields["Wo"]
    assert "Beschreibung geschrieben" in fields["Davor"]
    assert "<@" not in json.dumps(embed.to_dict())


def test_feedback_from_event_post_uses_user_history(ts):
    bot = ts
    channel = _with_feedback_channel(bot)
    event = _published_event(bot)
    anna = bot.guild.get_member(3)
    msg = bot.channel.messages[event.message_id]
    run(EventButton(event.id, "accept").callback(FakeInteraction(bot, anna, message=msg, guild_id=GUILD)))
    inter = FakeInteraction(bot, anna, guild_id=GUILD)
    run(FeedbackButton("e", event.id).callback(inter))
    modal = inter.response.modal
    modal.text._value = "Zusagen ging schnell."
    run(modal.on_submit(FakeInteraction(bot, anna, guild_id=GUILD)))
    fields = {f.name: f.value for f in channel.embeds[0].fields}
    assert channel.embeds[0].title == "Event-Post"
    assert f"Event {event.id}" in fields["Wo"] and f"Zusagen geklickt (Event {event.id})" in fields["Davor"]


def test_feedback_without_channel_or_on_other_server(ts, monkeypatch):
    bot = ts
    draft = flow.new_draft(bot)
    inter = FakeInteraction(bot, bot.guild.get_member(USER))
    run(FeedbackButton("w", draft.id, "summary").callback(inter))
    modal = inter.response.modal
    modal.text._value = "x"
    done = FakeInteraction(bot, bot.guild.get_member(USER))
    run(modal.on_submit(done))
    assert done.sent == [feedback.NO_CHANNEL]
    monkeypatch.setenv("TEST_GUILD_IDS", "999")
    inter = FakeInteraction(bot, bot.guild.get_member(USER))
    run(FeedbackButton("w", draft.id, "summary").callback(inter))
    assert inter.response.modal is None and "nur auf dem Testserver" in inter.sent[0]


def test_describe_texts():
    ui = {"search_results": [{"name": "Boozling"}, {"name": "Other"}]}
    assert history.describe_button("pick_result", "0", ui) == "Treffer 1 gewählt (Boozling)"
    assert history.describe_button("pick", "free") == "Freie Skriptwahl gewählt"
    assert history.describe_button("edit_field", "image") == "Bild ändern geklickt"
    assert history.describe_select("version", ["5|1.2"]) == "Version gewählt: v1.2"
    ui = history.append({}, "a", 0)
    for i in range(20):
        history.append(ui, str(i), i)
    assert len(ui[history.UI_KEY]) == history.MAX_ENTRIES and len(history.recent(ui[history.UI_KEY])) == history.SHOWN


def _published_event(bot):
    actor = Actor(USER, is_admin=True)
    from events.schema import Person
    draft = service.start_draft(bot.store, GUILD, actor, "Dalyan", EventData(start=NOW + timedelta(days=5)), NOW)
    click(bot, draft.id, "pick", "trouble_brewing")
    d = bot.store.get_draft(draft.id).data
    d.description, d.storyteller = "Test", Person("Dalyan", USER)
    bot.store.update_draft(draft.id, d, "preview", int(NOW.timestamp()))
    click(bot, draft.id, "publish")
    return bot.store.list_events(GUILD)[0]


# ── Setup, Reset, Delete All ─────────────────────────────────────────────────


_ids = itertools.count(5000)


class FakeMsg:
    def __init__(self, channel, content):
        self.id, self.channel, self.content = next(_ids), channel, content

    async def edit(self, content=None, allowed_mentions=None):
        self.content = content

    async def delete(self):
        self.channel.messages.pop(self.id, None)


class FakeTextChannel:
    def __init__(self, guild, name, category, overwrites):
        self.id, self.guild, self.name, self.category, self.overwrites = next(_ids), guild, name, category, overwrites
        self.messages, self.threads = {}, []
        guild.all_channels[self.id] = self

    @property
    def mention(self):
        return f"<#{self.id}>"

    async def edit(self, **kw):
        self.name, self.overwrites = kw.get("name", self.name), kw.get("overwrites", self.overwrites)

    async def delete(self, reason=None):
        self.guild.all_channels.pop(self.id, None)
        if self.category:
            self.category.channels.remove(self)

    async def send(self, content=None, allowed_mentions=None, **kw):
        msg = FakeMsg(self, content)
        self.messages[msg.id] = msg
        return msg

    async def fetch_message(self, mid):
        if mid not in self.messages:
            raise flow._NotFound()
        return self.messages[mid]

    async def purge(self, limit=100):
        gone = list(self.messages.values())[:limit]
        for m in gone:
            del self.messages[m.id]
        return gone

    async def archived_threads(self, limit=None):
        for t in []:
            yield t


class FakeCategory(FakeTextChannel):
    def __init__(self, guild, name, overwrites):
        super().__init__(guild, name, None, overwrites)
        self.channels = []
        guild.categories.append(self)

    async def create_text_channel(self, name, overwrites=None, position=None, reason=None):
        ch = FakeTextChannel(self.guild, name, self, overwrites)
        self.channels.append(ch)
        return ch

    async def delete(self, reason=None):
        self.guild.all_channels.pop(self.id, None)
        self.guild.categories.remove(self)


class FakeRole(SimpleNamespace):
    async def delete(self, reason=None):
        self.guild.roles.remove(self)


class Ident:
    """Hashbar wie discord.Role/Member, damit es als Schlüssel in Overwrites taugt."""

    def __init__(self, id, name):
        self.id, self.name = id, name


class FakeServer:
    def __init__(self, gid=GUILD):
        self.id, self.name = gid, "Testserver"
        self.default_role = Ident(gid, "@everyone")
        self.me = Ident(1, "Village Idiot")
        self.roles, self.categories, self.all_channels = [], [], {}

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    def get_channel(self, cid):
        return self.all_channels.get(cid)

    async def create_role(self, name, mentionable=False, reason=None):
        role = FakeRole(id=next(_ids), name=name, guild=self)
        self.roles.append(role)
        return role

    async def create_category(self, name, overwrites=None, position=None, reason=None):
        return FakeCategory(self, name, overwrites)


def test_setup_is_repeatable_and_registers_channels(ts):
    bot, guild = ts, FakeServer()
    result = run(server.setup_server(guild, bot.store))
    assert not result.failed
    reg = registry.get(bot.store, GUILD)
    assert [c.name for c in guild.categories] == ["Start", "Runden"]
    assert [[ch.name for ch in c.channels] for c in guild.categories] == [
        ["👋︱willkommen", "🗒️︱texte", "💬︱chat", "📝︱feedback"], ["📅︱events", "📋︱übersicht"]]
    assert len(guild.roles) == 2
    cfg = bot_config.get_guild_config(GUILD)
    assert cfg["event_channel_id"] == reg["channels"]["events"]
    assert cfg["overview_channel_id"] == reg["channels"]["overview"]
    access = service.get_access(bot.store, GUILD)
    assert access.storyteller_role_id == reg["roles"]["storyteller"]
    assert access.event_team_role_id == reg["roles"]["event_team"]
    welcome = guild.get_channel(reg["channels"]["welcome"])
    posts = [m.content for m in welcome.messages.values()]
    # Willkommen, dann Features (zwei Posts, weil über 2000 Zeichen); jeder Text mit Absender
    assert len(posts) == 3 and [p.startswith(texts.FROM_DALYAN) for p in posts] == [True, True, False]
    assert "**Commands**" in posts[0] and "**Was schon drin ist**" in posts[1]
    for key in ("events", "overview", "feedback", "texts", "chat"):
        assert f"<#{reg['channels'][key]}>" in posts[0], key
    assert "{" not in "".join(posts)
    assert guild.get_channel(reg["channels"]["chat"]).overwrites[guild.default_role].send_messages is True

    # Readonly-Channels: niemand außer dem Bot schreibt; im Feedback-Channel schon
    assert welcome.overwrites[guild.default_role].send_messages is False
    assert guild.get_channel(reg["channels"]["feedback"]).overwrites[guild.default_role].send_messages is True
    assert guild.get_channel(reg["channels"]["events"]).overwrites[guild.me].create_public_threads is True

    # Zweiter Lauf: nichts doppelt, Texte bearbeitet statt neu gepostet
    message_ids = registry.get(bot.store, GUILD)["messages"]
    result = run(server.setup_server(guild, bot.store))
    assert not result.created and len(guild.categories) == 2 and len(guild.roles) == 2
    assert sum(len(c.channels) for c in guild.categories) == len(server.CHANNEL_PLAN)
    assert registry.get(bot.store, GUILD)["messages"] == message_ids


def test_reset_clears_only_this_servers_events(ts):
    bot, guild = ts, FakeServer()
    run(server.setup_server(guild, bot.store))
    events_channel = guild.get_channel(registry.channel_id(bot.store, GUILD, "events"))
    for i in range(2):
        event = bot.store.insert_event(GUILD, USER, "Dalyan", EventData(start=NOW + timedelta(days=i + 1)), 0)
        msg = run(events_channel.send("post"))
        bot.store.set_event_message(event.id, events_channel.id, msg.id)
        bot.store.set_rsvp(event.id, 3, "Anna", "accepted", 0)
    flow.new_draft(bot)
    other = bot.store.insert_event(999, USER, "Dalyan", EventData(start=NOW + timedelta(days=1)), 0)

    result = run(server.reset_server(guild, bot.store))
    assert (result.events, result.drafts, result.messages) == (2, 1, 2)
    assert events_channel.messages == {} and bot.store.list_events(GUILD) == []
    assert bot.store.list_drafts(USER, GUILD) == []
    assert bot.store.get_event(other.id) is not None  # anderer Server bleibt
    assert bot.store.conn.execute("SELECT COUNT(*) FROM rsvps").fetchone()[0] == 0
    assert sum(len(c.channels) for c in guild.categories) == len(server.CHANNEL_PLAN)  # Channels bleiben


def test_delete_all_removes_everything_setup_created(ts):
    bot, guild = ts, FakeServer()
    run(server.setup_server(guild, bot.store))
    bot.store.insert_event(GUILD, USER, "Dalyan", EventData(start=NOW + timedelta(days=1)), 0)
    bot_config.save_guild_config(999, {"event_channel_id": 1})
    feedback_id = registry.channel_id(bot.store, GUILD, "feedback")
    result = run(server.delete_all(guild, bot.store))
    assert not result.failed and result.events == 1
    # Nur der Feedback-Channel bleibt, damit das Feedback nicht verloren geht
    assert list(guild.all_channels) == [feedback_id] and guild.categories == [] and guild.roles == []
    assert set(bot.store.get_guild_settings(GUILD)) == {registry.KEY}
    assert service.get_access(bot.store, GUILD).storyteller_role_id is None
    assert bot_config.load_config() == {"999": {"event_channel_id": 1}}  # andere Server unberührt

    # Setup danach nimmt den alten Feedback-Channel wieder, statt einen zweiten anzulegen
    result = run(server.setup_server(guild, bot.store))
    assert registry.channel_id(bot.store, GUILD, "feedback") == feedback_id
    assert sum(1 for c in guild.all_channels.values() if c.name == "📝︱feedback") == 1


def test_setup_turns_on_listen_mode_and_delete_all_stops_it(ts):
    """Nach Setup läuft die automatische Übersicht (Listen-Modus) für die Setup-Channels."""
    from commands.overview import Overview

    bot, guild = ts, FakeServer()
    overview = Overview(bot)
    overview.fetch_and_post = lambda *a: _done()
    bot_with_cog = SimpleNamespace(cogs={"Overview": overview})
    run(server.setup_server(guild, bot.store))
    run(server.start_overview(bot_with_cog, guild, bot.store))
    assert GUILD in overview.listening and bot_config.get_guild_config(GUILD)["auto_active"] is True

    run(server.delete_all(guild, bot.store, bot_with_cog))
    assert GUILD not in overview.listening


async def _done():
    return None


# ── Commands ─────────────────────────────────────────────────────────────────


class CommandInteraction(FakeInteraction):
    def __init__(self, bot, guild_id, admin=True):
        super().__init__(bot, SimpleNamespace(id=USER, guild_permissions=SimpleNamespace(manage_guild=admin)),
                         guild_id=guild_id)
        self.guild = FakeServer(guild_id)


@pytest.mark.parametrize("name", ["setup_cmd", "reset_cmd", "delete_all_cmd", "sample_cmd"])
def test_commands_refuse_on_real_server_and_for_non_admins(ts, monkeypatch, name):
    from commands.test_server import TestServerCog
    bot = ts
    called = []

    async def spy(*a, **kw):
        called.append(a)
    for fn in ("setup_server", "reset_server", "delete_all"):
        monkeypatch.setattr(server, fn, spy)
    cog = TestServerCog(bot)
    real = CommandInteraction(bot, 999)
    run(getattr(cog, name).callback(cog, real))
    assert real.sent == [texts.NOT_A_TEST_SERVER]
    member = CommandInteraction(bot, GUILD, admin=False)
    run(getattr(cog, name).callback(cog, member))
    assert member.sent == [texts.ADMINS_ONLY] and called == []


def test_welcome_lists_only_existing_commands(ts):
    """Der Willkommenstext nennt nur die Commands, die Tester brauchen; die muss es auch geben."""
    async def go():
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        bot.store = flow.Store(":memory:")
        for ext in ("commands.settings", "commands.overview", "commands.event_settings", "commands.botc",
                    "commands.reminder", "commands.my_events", "commands.test_server"):
            await bot.load_extension(ext)
        names = []
        for c in bot.tree.get_commands():
            names += [f"{c.name} {s.name}" for s in c.commands] if hasattr(c, "commands") else [c.name]
        await bot.unload_extension("commands.reminder")
        return names

    names = run(go())
    import re
    listed = list(dict.fromkeys(re.findall(r"`/([a-z_-]+(?: [a-z_-]+)?)`", texts.WELCOME)))
    assert listed == ["botc", "testserver beispiel-event", "meine_events", "testserver reset", "testserver setup",
                      "testserver update", "testserver delete_all"]
    assert set(listed) <= set(names)


def test_texts_follow_style():
    for text in (texts.WELCOME, texts.FEATURES, texts.FEEDBACK_INTRO, texts.CHAT_INTRO):
        assert "—" not in text and "–" not in text and text.count("!") == 0
        assert text.startswith("-# Nachricht von Dalyan\n")
        assert all(len(part) <= server.MESSAGE_LIMIT for part in server.split_message(text))
    assert server.split_message("a\n\n" + "b" * 2500) == ["a", "b" * 2000, "b" * 500]


# Diese Texte setzt der Bot erst zur Laufzeit zusammen; geprüft wird nur ihr Anfang
COMPOSED_AT_RUNTIME = {"ScriptRater antwortet nicht", "Zusammenfassung, wenn noch was fehlt",
                       "Zusammenfassung, wenn alles da ist"}


def test_texts_channel_copies_match_code():
    """#texte zeigt Kopien der Bot-Texte; ändert sich der Text im Code, fällt das hier auf."""
    import os
    import re
    from testserver import bot_texts
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for group, label, text, path in bot_texts.COPIED:
        assert group in bot_texts.GROUPS
        with open(os.path.join(root, path), encoding="utf-8") as f:
            source = f.read()
        # Aneinandergehängte String-Literale zusammenziehen, damit der ganze Text vergleichbar ist
        flat = re.sub(r'"\s*\n\s*f?"', "", source).replace("\\n", "\n")
        found = text[:25] in source if label in COMPOSED_AT_RUNTIME else text in flat
        assert found, f"{label}: Text in {path} geändert, bitte bot_texts.COPIED nachziehen"
    posts = bot_texts.posts()
    assert posts[0].startswith(texts.FROM_DALYAN) and "relevanten Texte" in posts[0]
    assert len(posts) == 1 + len(bot_texts.GROUPS)
    assert all(len(p) <= server.MESSAGE_LIMIT for p in posts[:-1])  # Academy-Text darf geteilt werden
    assert "Clocktower Academy" in posts[-1]


def test_start_message_has_feedback(ts, monkeypatch):
    from discord_ui.botc_start import StartButton, build_start_layout
    bot = ts
    channel = _with_feedback_channel(bot)
    layout = build_start_layout(bot.guild, USER)
    assert f"fb:s:{GUILD}:start" in ids(layout) and f"botc:{GUILD}:new" in ids(layout)
    monkeypatch.delenv("TEST_SERVER")
    assert not any(c.startswith("fb:") for c in ids(build_start_layout(bot.guild, USER)))
    monkeypatch.setenv("TEST_SERVER", "1")

    # Klick auf „Termin festlegen“ landet in der Historie, Feedback nennt die Startnachricht
    user = bot.guild.get_member(USER)
    run(StartButton(GUILD, "new", "Termin festlegen").callback(FakeInteraction(bot, user)))
    inter = FakeInteraction(bot, user)
    run(FeedbackButton("s", GUILD, "start").callback(inter))
    modal = inter.response.modal
    assert modal.guild_id == GUILD
    modal.text._value = "Startnachricht ist klar."
    run(modal.on_submit(FakeInteraction(bot, user)))
    fields = {f.name: f.value for f in channel.embeds[0].fields}
    assert channel.embeds[0].title == "Startnachricht" and "noch kein Entwurf" in fields["Wo"]
    assert "Termin festlegen" in fields["Davor"]


def test_sample_event_is_full_and_created_once(ts):
    from testserver.sample_event import ACCEPTED, DECLINED, TENTATIVE
    bot = ts
    owner = bot.guild.get_member(USER)
    result = server.SetupResult()
    run(server.ensure_sample_event(bot, bot.guild, bot.store, owner, result))
    assert result.created == ["Beispiel-Event"] and not result.failed
    events = bot.store.list_events(GUILD)
    assert len(events) == 1
    event = events[0]
    assert event.creator_id == USER and event.data.script.name == "Boozling" and event.data.max_players == 12
    lists = service.rsvp_lists(bot.store, event)
    assert (len(lists.players), len(lists.waitlist), len(lists.tentative), len(lists.declined)) == (12, 3, 4, 4)
    assert len(ACCEPTED + TENTATIVE + DECLINED) == 23

    msg = bot.channel.messages[event.message_id]
    fields = " ".join(f"{f.name} {f.value}" for f in msg.embed.fields)
    assert "Anna" in fields and "Olivia" in fields and "<@" not in fields
    assert msg.embed.title.endswith("Boozling mit Mara und Theo")
    assert "Dalyan" not in fields and "Rosanna" not in fields  # nur erfundene Namen

    # Zweites Setup: das Beispiel bleibt, kein zweites
    run(server.ensure_sample_event(bot, bot.guild, bot.store, owner, server.SetupResult()))
    assert len(bot.store.list_events(GUILD)) == 1


def test_text_channel_key_only_for_text_channels():
    store = flow.Store(":memory:")
    registry.save(store, 1, {"categories": {}, "channels": {"welcome": 10, "events": 20}, "roles": {}, "messages": {}})
    assert server.text_channel_key(store, 1, 10) == "welcome"
    assert server.text_channel_key(store, 1, 20) is None  # Event-Channel hat keine festen Texte
    assert server.text_channel_key(store, 1, 99) is None
