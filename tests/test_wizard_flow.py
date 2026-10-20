"""Durchlauf des Wizards mit einem nachgebauten Discord: Klicks, Modals, Veröffentlichen, RSVP, Bearbeiten.

Kein Netzwerk: Basis-Skript (feste Einschätzung), Bild lokal, Discord-Objekte sind Attrappen,
die nur das tun, was der Bot von ihnen braucht.
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from discord_ui import event_post, wizard
from discord_ui.event_post import EventButton
from discord_ui.wizard import DescriptionModal, WizardButton, WizardSelect
from events import service
from events.permissions import AccessSettings, Actor
from events.schema import BERLIN_TZ, EventData
from events.store import Store

GUILD, CHANNEL, USER = 10, 20, 1
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=BERLIN_TZ)


# ── Attrappen ────────────────────────────────────────────────────────────────


class FakeMember(SimpleNamespace):
    def __init__(self, uid, name, admin=False):
        super().__init__(id=uid, display_name=name, roles=[], bot=False,
                         guild_permissions=SimpleNamespace(manage_guild=admin),
                         display_avatar=SimpleNamespace(url="https://cdn/avatar.png"))


class FakeMessage:
    _next_id = 1000

    def __init__(self, channel, embed=None, files=(), view=None):
        FakeMessage._next_id += 1
        self.id = FakeMessage._next_id
        self.channel = channel
        self.jump_url = f"https://discord.com/channels/{GUILD}/{CHANNEL}/{self.id}"
        self.embed, self.view = embed, view
        self.attachments = [SimpleNamespace(filename=f.filename) for f in files]

    async def edit(self, embed=None, view=None, attachments=None):
        self.embed, self.view = embed, view
        if attachments is not None:
            self.attachments = [SimpleNamespace(filename=f.filename) for f in attachments]

    async def delete(self):
        self.channel.messages.pop(self.id, None)


class FakeChannel:
    def __init__(self):
        self.id = CHANNEL
        self.messages = {}

    async def send(self, embed=None, files=(), view=None):
        msg = FakeMessage(self, embed, files, view)
        self.messages[msg.id] = msg
        return msg

    async def fetch_message(self, mid):
        return self.messages[mid]


class FakeGuild:
    def __init__(self, members):
        self.id, self.name = GUILD, "Testserver"
        self.members = {m.id: m for m in members}

    def get_member(self, uid):
        return self.members.get(uid)

    async def fetch_member(self, uid):
        return self.members[uid]

    async def query_members(self, query, limit):
        return [m for m in self.members.values() if m.display_name.lower().startswith(query.lower())][:limit]


class FakeBot:
    def __init__(self, store):
        self.store = store
        self.channel = FakeChannel()
        self.guild = FakeGuild([FakeMember(USER, "Dalyan", admin=True), FakeMember(2, "Rosanna"),
                                FakeMember(3, "Anna")])

    def get_guild(self, gid):
        return self.guild if gid == GUILD else None

    def get_channel(self, cid):
        return self.channel if cid == CHANNEL else None


class FakeResponse:
    def __init__(self, inter):
        self.inter, self.done, self.modal = inter, False, None

    def is_done(self):
        return self.done

    async def defer(self, **kw):
        self.done = True

    async def send_modal(self, modal):
        self.done, self.modal = True, modal

    async def edit_message(self, **kw):
        self.done = True
        self.inter.screen = kw

    async def send_message(self, content=None, **kw):
        self.done = True
        self.inter.sent.append(content)


class FakeInteraction:
    def __init__(self, bot, user, values=None, message=None, guild_id=None):
        self.client, self.user = bot, user
        self.data = {"values": values or []}
        self.message = message
        self.guild_id = guild_id
        self.response = FakeResponse(self)
        self.followup = SimpleNamespace(send=self._followup)
        self.screen, self.sent = None, []

    async def _followup(self, content=None, **kw):
        self.sent.append(content)

    async def edit_original_response(self, **kw):
        self.screen = kw


# ── Hilfen ───────────────────────────────────────────────────────────────────


@pytest.fixture
def env(monkeypatch):
    store = Store(":memory:")
    service.set_access(store, GUILD, AccessSettings())
    bot = FakeBot(store)
    monkeypatch.setenv("ALLOWED_GUILD_IDS", str(GUILD))
    monkeypatch.setattr(event_post, "get_guild_config", lambda gid: {"event_channel_id": CHANNEL})
    monkeypatch.setattr(wizard, "now", lambda: NOW)
    monkeypatch.setattr(event_post, "now", lambda: NOW)
    yield bot
    store.close()


def run(coro):
    return asyncio.run(coro)


def click(bot, draft_id, name, arg=None, user_id=USER):
    inter = FakeInteraction(bot, bot.guild.get_member(user_id))
    run(WizardButton(draft_id, name, "x", arg=arg).callback(inter))
    return inter


def choose(bot, draft_id, name, value):
    inter = FakeInteraction(bot, bot.guild.get_member(USER), values=[value])
    run(WizardSelect(draft_id, name, [], "x").callback(inter))
    return inter


def new_draft(bot):
    actor = Actor(USER, is_admin=True)
    return service.start_draft(bot.store, GUILD, actor, "Dalyan", EventData(start=NOW + timedelta(days=5)), NOW)


def step(bot, draft_id):
    return bot.store.get_draft(draft_id).step


# ── Durchlauf ────────────────────────────────────────────────────────────────


def test_full_flow_publish_rsvp_edit_delete(env):
    bot = env
    draft = new_draft(bot)

    # 1. Skript: Trouble Brewing → Einschätzung fest grün
    click(bot, draft.id, "pick", "trouble_brewing")
    d = bot.store.get_draft(draft.id)
    assert d.step == "rating" and d.data.rating == "green" and d.data.rating_source == "fixed"

    # 2. Einschätzung manuell überschreiben, weiter
    click(bot, draft.id, "rate", "yellow")
    assert bot.store.get_draft(draft.id).data.rating_source == "manual"
    click(bot, draft.id, "next")
    assert step(bot, draft.id) == "description"

    # 3. Beschreibung: Weiter ohne Text geht nicht, mit Text schon
    inter = click(bot, draft.id, "next")
    assert step(bot, draft.id) == "description"
    modal = DescriptionModal(draft.id, "")
    modal.text._value = "Gemütliche Runde Trouble Brewing."
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    click(bot, draft.id, "next")
    assert step(bot, draft.id) == "image"

    # 4. Bild: automatisch, weiter zur Zusammenfassung
    click(bot, draft.id, "next")
    assert step(bot, draft.id) == "preview"

    # 5. Standardwerte nur über „Feld ändern“: Co-ST als Text, Dauer, Kamera
    inter = choose(bot, draft.id, "edit", "people")
    modal = inter.response.modal
    modal.st._value, modal.co._value = "Dalyan", "Rosanna"
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    inter = choose(bot, draft.id, "edit", "basics")
    modal = inter.response.modal
    modal.duration._value = "180"
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    inter = choose(bot, draft.id, "edit", "labels")
    modal = inter.response.modal
    assert "academy" in [o.value for o in modal.options.options]  # Server-Admin: Academy automatisch
    modal.camera._value = "required"
    modal.options._values = []
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    d = bot.store.get_draft(draft.id)
    assert d.step == "preview"
    assert d.data.co_storyteller.name == "Rosanna" and d.data.co_storyteller.user_id is None
    assert d.data.storyteller.user_id == USER  # Name unverändert → ID bleibt
    assert d.data.duration_minutes == 180 and d.data.camera == "required"
    assert d.data.start == NOW + timedelta(days=5)  # Termin unverändert

    # 6. Veröffentlichen
    inter = click(bot, draft.id, "publish")
    assert "online" in inter.screen["content"]
    assert bot.store.get_draft(draft.id) is None
    event = bot.store.list_events(GUILD)[0]
    msg = bot.channel.messages[event.message_id]
    assert msg.embed.title == "🟡 Trouble Brewing mit Dalyan und Rosanna"
    assert {a.filename for a in msg.attachments} == {"event_image.png", "thumbnail.png"}
    # Ersteller:in nur unten: Profilbild, Name, Erstellungsdatum
    assert msg.embed.author.name is None
    assert msg.embed.footer.text == "Dalyan" and msg.embed.footer.icon_url == "https://cdn/avatar.png"
    assert msg.embed.timestamp is not None

    # RSVP: Anna sagt zu, Name als Text im Embed, Bilder bleiben referenziert
    rsvp = FakeInteraction(bot, bot.guild.get_member(3), message=msg, guild_id=GUILD)
    run(EventButton(event.id, "accept").callback(rsvp))
    embed = rsvp.screen["embed"]
    accepted = next(f.value for f in embed.fields if "Akzeptiert" in f.name)
    assert "Anna" in accepted and "<@" not in accepted
    assert embed.image.url == "attachment://event_image.png"

    # Bearbeiten durch Fremde verboten, durch Ersteller per DM-Wizard (Start in der Vorschau)
    foreign = FakeInteraction(bot, bot.guild.get_member(3), message=msg, guild_id=GUILD)
    run(EventButton(event.id, "edit").callback(foreign))
    assert "nur der Ersteller" in foreign.sent[0]

    sent_dm = []

    async def fake_send(**kw):
        sent_dm.append(kw)

    owner = bot.guild.get_member(USER)
    owner.send = fake_send
    edit = FakeInteraction(bot, owner, message=msg, guild_id=GUILD)
    run(EventButton(event.id, "edit").callback(edit))
    edit_draft = bot.store.list_drafts(USER)[0]
    assert edit_draft.event_id == event.id and edit_draft.step == "preview" and sent_dm

    # In der Zusammenfassung „4 · Beschreibung“ ändern: Modal, danach wieder die Zusammenfassung
    inter = choose(bot, edit_draft.id, "edit", "description")
    modal = inter.response.modal
    modal.text._value = "Neue Beschreibung."
    run(modal.on_submit(FakeInteraction(bot, owner)))
    assert step(bot, edit_draft.id) == "preview"
    # Skript-Schritt aus der Zusammenfassung: „Weiter“ führt zurück
    choose(bot, edit_draft.id, "edit", "rating")
    assert step(bot, edit_draft.id) == "rating:p"
    click(bot, edit_draft.id, "next")
    assert step(bot, edit_draft.id) == "preview"
    inter = click(bot, edit_draft.id, "publish")
    assert "gespeichert" in inter.screen["content"]
    msg = bot.channel.messages[event.message_id]
    assert any("Neue Beschreibung." in f.value for f in msg.embed.fields)
    assert "Anna" in next(f.value for f in msg.embed.fields if "Akzeptiert" in f.name)  # RSVPs bleiben

    # Löschen mit Bestätigung
    delete = FakeInteraction(bot, owner, message=msg, guild_id=GUILD)
    run(EventButton(event.id, "delete").callback(delete))
    assert "wirklich" in delete.sent[0]


def test_reminder_subpage(env):
    bot = env
    draft = new_draft(bot)
    click(bot, draft.id, "pick", "trouble_brewing")
    choose(bot, draft.id, "edit", "reminders")
    assert step(bot, draft.id) == "reminders"
    choose(bot, draft.id, "rem_to_first", "accepted")
    inter = FakeInteraction(bot, bot.guild.get_member(USER), values=["accepted", "waitlist"])
    run(WizardSelect(draft.id, "rem_to_second", [], "x").callback(inter))
    click(bot, draft.id, "rem_mode", "first")
    click(bot, draft.id, "rem_toggle", "second")
    d = bot.store.get_draft(draft.id).data
    assert d.reminder_overrides == {"first": {"mode": "names"},
                                    "second": {"enabled": False, "recipients": ["accepted", "waitlist"]}}
    # Leere Auswahl = niemand benachrichtigen
    inter = FakeInteraction(bot, bot.guild.get_member(USER), values=[])
    run(WizardSelect(draft.id, "rem_to_first", [], "x").callback(inter))
    assert bot.store.get_draft(draft.id).data.reminder_overrides["first"]["recipients"] == []
    click(bot, draft.id, "rem_reset")
    assert bot.store.get_draft(draft.id).data.reminder_overrides == {}
    click(bot, draft.id, "rem_done")
    assert step(bot, draft.id) == "preview"


def test_edit_title_and_rating_range(env):
    bot = env
    draft = new_draft(bot)
    click(bot, draft.id, "pick", "trouble_brewing")
    choose(bot, draft.id, "edit", "title")  # aus jeder Seite heraus möglich
    inter = choose(bot, draft.id, "edit", "title")
    modal = inter.response.modal
    modal.text._value = "Gemütlicher Abend"
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    click(bot, draft.id, "rate", "green_yellow")
    d = bot.store.get_draft(draft.id).data
    assert d.title == "Gemütlicher Abend" and d.rating == "green_yellow" and d.rating_source == "manual"
    # Titel leeren → wieder automatisch
    inter = choose(bot, draft.id, "edit", "title")
    modal = inter.response.modal
    modal.text._value = ""
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    assert bot.store.get_draft(draft.id).data.title == ""


def test_free_choice_skips_rating_and_has_no_auto_image(env):
    bot = env
    draft = new_draft(bot)
    click(bot, draft.id, "pick", "free")
    d = bot.store.get_draft(draft.id)
    assert d.step == "description" and d.data.rating == "any" and d.data.rating_source == "fixed"


def test_cancel_removes_draft(env):
    bot = env
    draft = new_draft(bot)
    inter = click(bot, draft.id, "cancel")
    assert bot.store.get_draft(draft.id) is None
    assert "abgebrochen" in inter.screen["content"]


def test_foreign_user_cannot_use_draft(env):
    bot = env
    draft = new_draft(bot)
    inter = click(bot, draft.id, "pick", "trouble_brewing", user_id=3)
    assert inter.sent == ["Das ist nicht dein Entwurf."]
    assert bot.store.get_draft(draft.id).data.script is None


def test_locked_guild_blocks_wizard(env, monkeypatch):
    bot = env
    draft = new_draft(bot)
    monkeypatch.setenv("ALLOWED_GUILD_IDS", "999")
    inter = click(bot, draft.id, "pick", "trouble_brewing")
    assert "nicht freigeschaltet" in inter.sent[0]


def test_publish_without_event_channel_keeps_draft(env, monkeypatch):
    bot = env
    draft = new_draft(bot)
    click(bot, draft.id, "pick", "trouble_brewing")
    d = bot.store.get_draft(draft.id)
    data = d.data
    data.description = "x"
    bot.store.update_draft(d.id, data, "preview", int(NOW.timestamp()))
    monkeypatch.setattr(event_post, "get_guild_config", lambda gid: {})
    inter = click(bot, draft.id, "publish")
    assert bot.store.get_draft(draft.id) is not None
    assert bot.store.list_events(GUILD) == []
    assert "Event-Channel" in inter.screen["embeds"][0].description
