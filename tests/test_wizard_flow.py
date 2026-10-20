"""Durchlauf des Wizards mit einem nachgebauten Discord: Klicks, Modals, Veröffentlichen, RSVP, Bearbeiten.

Kein Netzwerk: Basis-Skript (feste Einschätzung), Bild lokal, Discord-Objekte sind Attrappen,
die nur das tun, was der Bot von ihnen braucht.
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import discord
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
        self.files = [f.filename for f in files]

    @property
    def embeds(self):
        return [self.embed] if self.embed else []

    @property
    def attachments(self):
        """Wie bei Discord: Anhänge, auf die das Embed per attachment:// zeigt, fehlen hier."""
        used = set()
        if self.embed:
            for url in (self.embed.image.url, self.embed.thumbnail.url):
                if url and url.startswith("attachment://"):
                    used.add(url.removeprefix("attachment://"))
        return [SimpleNamespace(filename=n) for n in self.files if n not in used]

    async def edit(self, embed=None, view=None, attachments=None):
        if attachments is not None:
            self.files = [f.filename for f in attachments]
        elif self.embed and embed:
            # Discord verwirft Anhänge, auf die das neue Embed nicht mehr zeigt
            def refs(e):
                return {u.removeprefix("attachment://") for u in (e.image.url, e.thumbnail.url) if u}
            self.files = [n for n in self.files if n not in refs(self.embed) or n in refs(embed)]
        self.embed, self.view = embed, view

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


class _NotFound(discord.NotFound):
    def __init__(self):  # ohne HTTP-Antwort
        Exception.__init__(self, "Unknown Member")


class FakeGuild:
    def __init__(self, members):
        self.id, self.name = GUILD, "Testserver"
        self.members = {m.id: m for m in members}

    def get_member(self, uid):
        return self.members.get(uid)

    async def fetch_member(self, uid):
        if uid not in self.members:
            raise _NotFound()  # wie Discord bei Nicht-Mitgliedern
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


def screen_text(inter) -> str:
    return " ".join(i.content for i in inter.screen["view"].walk_children() if isinstance(i, discord.ui.TextDisplay))


def new_draft(bot):
    actor = Actor(USER, is_admin=True)
    return service.start_draft(bot.store, GUILD, actor, "Dalyan", EventData(start=NOW + timedelta(days=5)), NOW)


def step(bot, draft_id):
    return bot.store.get_draft(draft_id).step


# ── Durchlauf ────────────────────────────────────────────────────────────────


def test_full_flow_publish_rsvp_edit_delete(env):
    bot = env
    draft = new_draft(bot)

    # 1. Skript: Trouble Brewing → Schwierigkeit legt der Algorithmus fest (fest grün), direkt zur Zusammenfassung
    inter = click(bot, draft.id, "pick", "trouble_brewing")
    d = bot.store.get_draft(draft.id)
    assert d.step == "preview" and d.data.rating == "green" and d.data.rating_source == "fixed"
    assert not d.data.is_special
    assert isinstance(inter.screen["view"], discord.ui.LayoutView)
    assert "fehlt noch:** Beschreibung" in screen_text(inter)

    # 2. Schwierigkeit per Dialog ändern
    inter = click(bot, draft.id, "edit_field", "rating")
    modal = inter.response.modal
    modal.rating._value = "yellow"
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    assert bot.store.get_draft(draft.id).data.rating_source == "manual"

    # 3. Fehlende Beschreibung: roter Button öffnet einen Dialog NUR mit dem Beschreibungsfeld
    inter = click(bot, draft.id, "fix_field", "description")
    modal = inter.response.modal
    assert isinstance(modal, DescriptionModal) and len(modal.children) == 1
    modal.text._value = "Gemütliche Runde Trouble Brewing."
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))

    # 4. Bild-Seite aus der Zusammenfassung: „Zur Zusammenfassung“ führt zurück
    inter = click(bot, draft.id, "edit_field", "image")
    assert step(bot, draft.id) == "image:p" and [f.filename for f in inter.screen["attachments"]] == ["vorschau.png"]
    click(bot, draft.id, "next")
    assert step(bot, draft.id) == "preview"

    # 5. Standardwerte nur über die Dialoge: Co-ST als Text, Dauer, Kamera
    inter = click(bot, draft.id, "edit_field", "people")
    modal = inter.response.modal
    modal.st._value, modal.co._value = "Dalyan", "Rosanna"
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    inter = click(bot, draft.id, "edit_field", "frame")
    modal = inter.response.modal
    modal.date._value, modal.time._value = modal.prefill
    modal.duration._value, modal.players._value = "180", "12"
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    inter = click(bot, draft.id, "edit_field", "selection")
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
    assert "veröffentlicht" in screen_text(inter)
    assert bot.store.get_draft(draft.id) is None
    event = bot.store.list_events(GUILD)[0]
    msg = bot.channel.messages[event.message_id]
    assert msg.embed.title == "🟡 Trouble Brewing mit Dalyan und Rosanna"
    assert set(msg.files) == {"event_image.png", "thumbnail.png"}
    assert msg.attachments == []  # wie bei Discord: vom Embed referenzierte Anhänge fehlen hier
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
    # Regression: Bild und Thumbnail verschwanden nach Zu-/Absage
    assert embed.image.url == "attachment://event_image.png"
    assert embed.thumbnail.url == "attachment://thumbnail.png"

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

    assert isinstance(sent_dm[0]["view"], discord.ui.LayoutView)
    # Beschreibung ändern: Dialog, danach wieder die Zusammenfassung
    inter = click(bot, edit_draft.id, "edit_field", "description")
    modal = inter.response.modal
    modal.text._value = "Neue Beschreibung."
    run(modal.on_submit(FakeInteraction(bot, owner)))
    assert step(bot, edit_draft.id) == "preview"
    inter = click(bot, edit_draft.id, "publish")
    assert "gespeichert" in screen_text(inter)
    msg = bot.channel.messages[event.message_id]
    assert any("Neue Beschreibung." in f.value for f in msg.embed.fields)
    assert "Anna" in next(f.value for f in msg.embed.fields if "Akzeptiert" in f.name)  # RSVPs bleiben

    # Löschen mit Bestätigung
    delete = FakeInteraction(bot, owner, message=msg, guild_id=GUILD)
    run(EventButton(event.id, "delete").callback(delete))
    assert "wirklich" in delete.sent[0]


def test_reminders_are_not_editable_in_wizard(env):
    """Erinnerungen legen nur Admins global fest (/set_reminders), nicht der Storyteller."""
    bot = env
    draft = new_draft(bot)
    click(bot, draft.id, "pick", "trouble_brewing")
    inter = click(bot, draft.id, "rem_toggle", "first")
    assert inter.sent == ["Diese Aktion gibt es nicht mehr."]


def test_edit_title_and_rating_range(env):
    bot = env
    draft = new_draft(bot)
    click(bot, draft.id, "pick", "trouble_brewing")
    inter = click(bot, draft.id, "edit_field", "title")
    modal = inter.response.modal
    modal.text._value = "Gemütlicher Abend"
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    inter = click(bot, draft.id, "edit_field", "rating")
    modal = inter.response.modal
    modal.rating._value = "green_yellow"
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    d = bot.store.get_draft(draft.id).data
    assert d.title == "Gemütlicher Abend" and d.rating == "green_yellow" and d.rating_source == "manual"
    # Titel leeren → wieder automatisch
    inter = click(bot, draft.id, "edit_field", "title")
    modal = inter.response.modal
    modal.text._value = ""
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    assert bot.store.get_draft(draft.id).data.title == ""


def test_title_dialog_prefilled_and_unchanged_stays_automatic(env):
    """Der aktuelle Titel steht ausgeschrieben im Dialog; unverändert bleibt er automatisch."""
    bot = env
    draft = new_draft(bot)
    click(bot, draft.id, "pick", "trouble_brewing")
    inter = click(bot, draft.id, "edit_field", "title")
    assert inter.response.modal.text.default == "Trouble Brewing mit Dalyan"
    run(inter.response.modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    assert bot.store.get_draft(draft.id).data.title == ""


def test_free_choice_skips_rating_and_has_no_auto_image(env):
    bot = env
    draft = new_draft(bot)
    click(bot, draft.id, "pick", "free")
    d = bot.store.get_draft(draft.id)
    assert d.step == "preview" and d.data.rating == "any" and d.data.rating_source == "fixed"


def test_cancel_removes_draft(env):
    bot = env
    draft = new_draft(bot)
    inter = click(bot, draft.id, "cancel")
    assert bot.store.get_draft(draft.id) is None
    assert "abgebrochen" in screen_text(inter)


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
    assert "Event-Channel" in screen_text(inter)


def test_botc_works_in_dms(env, monkeypatch):
    """/botc in den DMs: Server über die Mitgliedschaft, Modal bekommt Server und Mitglied mit."""
    from commands import botc as botc_cmd
    bot = env
    monkeypatch.setattr(botc_cmd, "get_guild_config", lambda gid: {"event_channel_id": CHANNEL})
    bot.guild.get_channel = lambda cid: bot.channel if cid == CHANNEL else None
    cog = botc_cmd.Botc(bot)
    inter = FakeInteraction(bot, SimpleNamespace(id=USER, display_name="Dalyan"))
    inter.guild = None
    run(cog._start(inter))
    modal = inter.response.modal
    assert modal is not None and modal.guild is bot.guild and modal.member.id == USER

    # Nicht Mitglied eines freigeschalteten Servers → Hinweis statt Modal
    stranger = FakeInteraction(bot, SimpleNamespace(id=999, display_name="X"))
    stranger.guild = None
    run(cog._start(stranger))
    assert stranger.response.modal is None and "keinem Server" in stranger.sent[0]


def test_script_first_with_result_list(env, monkeypatch):
    """Skript-Karte zuerst; der Dialog sucht (Suchfeld oben), Treffer mit „Wählen“ und Blättern,
    danach direkt die Zusammenfassung. „Ändern“ beim Skript öffnet wieder den Dialog."""
    from discord_ui.wizard import ScriptModal
    from logic import botcscripts
    bot = env
    draft = new_draft(bot)
    user = bot.guild.get_member(USER)

    hits = [{"botcscripts_id": str(i), "version": "1.0", "name": f"Boo {i}", "author": "A", "likes": 10 - i,
             "characters": ["imp"], "content": [], "script_type": "Full"} for i in range(7)]

    async def fake_search(query, limit=10):
        return hits

    async def fake_download(script_id, version):
        return [{"id": "_meta", "name": f"Boo {script_id}", "author": "A"}, {"id": "imp"}, {"id": "washerwoman"}]

    async def no_rater(script):
        return None  # kein Netzwerk im Test

    monkeypatch.setattr(botcscripts, "search_scripts", fake_search)
    monkeypatch.setattr(botcscripts, "download_script", fake_download)
    monkeypatch.setattr(wizard, "rate_script", no_rater)

    inter = click(bot, draft.id, "script_dialog")
    modal = inter.response.modal
    assert isinstance(modal, ScriptModal)
    assert modal.children[0].component is modal.query  # Suche ganz oben
    modal.query._value = "boo"
    inter = FakeInteraction(bot, user)
    run(modal.on_submit(inter))
    sections = [i for i in inter.screen["view"].walk_children() if isinstance(i, discord.ui.Section)]
    assert [s.accessory.custom_id.split(":")[2] for s in sections] == ["pick_result"] * 5
    texts = " ".join(i.content for i in inter.screen["view"].walk_children() if isinstance(i, discord.ui.TextDisplay))
    assert "10 Likes" in texts and bot.store.get_draft(draft.id).data.script is None

    inter = click(bot, draft.id, "page", "1")
    sections = [i for i in inter.screen["view"].walk_children() if isinstance(i, discord.ui.Section)]
    assert [s.accessory.custom_id.split(":")[3] for s in sections] == ["5", "6"]

    click(bot, draft.id, "pick_result", "6")
    d = bot.store.get_draft(draft.id)
    assert d.data.script.name == "Boo 6" and d.step == "preview"
    assert "page" not in d.ui and "search_results" not in d.ui

    # „Ändern“ beim Skript: Dialog; Basis-Skript ohne Suchbegriff → direkt zurück zur Zusammenfassung
    inter = click(bot, draft.id, "edit_field", "script")
    modal = inter.response.modal
    assert isinstance(modal, ScriptModal)
    modal.query._value = "boo"  # Suchrest: die Auswahl geht vor (Prüfung von unten nach oben)
    modal.kind._value = "trouble_brewing"
    run(modal.on_submit(FakeInteraction(bot, user)))
    d = bot.store.get_draft(draft.id)
    assert d.data.script.name == "Trouble Brewing" and d.step == "preview"

    # Suche aus der Zusammenfassung heraus: Treffer-Karte, nach der Wahl zurück
    inter = click(bot, draft.id, "edit_field", "script")
    modal = inter.response.modal
    modal.query._value = "boo"
    run(modal.on_submit(FakeInteraction(bot, user)))
    assert step(bot, draft.id) == "script:p"
    click(bot, draft.id, "pick_result", "0")
    assert step(bot, draft.id) == "preview"


@pytest.mark.parametrize("guild_id", [GUILD, None])  # auf dem Server und in den DMs
def test_botc_modal_submit_creates_draft_and_confirms(env, guild_id):
    """Regression: die Bestätigung nach dem Absenden warf TypeError ('str' object is not callable)."""
    from discord_ui.botc_modal import BotcModal
    bot = env
    member = bot.guild.get_member(USER)
    sent_dm = []

    async def dm(**kw):
        sent_dm.append(kw)
    member.send = dm

    async def go():
        return BotcModal(bot.store, allow_academy=False, guild=bot.guild, member=member)
    modal = run(go())
    modal.date_choice._value = modal.date_choice.options[2].value  # übermorgen
    modal.time_choice._value = "20:00"
    inter = FakeInteraction(bot, member, guild_id=guild_id)
    run(modal.on_submit(inter))
    assert inter.sent and inter.sent[0].startswith("Der Termin ist gespeichert.")
    assert ("in deinen DMs" in inter.sent[0]) == (guild_id is not None)
    draft = bot.store.list_drafts(USER)[0]
    assert draft.step == "script"  # /botc beginnt mit der Skriptwahl
    assert sent_dm  # Skript-Karte per DM geschickt
    # Die erste Karte bestätigt den Termin und erklärt die nächsten Schritte
    texts = " ".join(i.content for i in sent_dm[0]["view"].walk_children() if isinstance(i, discord.ui.TextDisplay))
    assert "Neue Runde" in texts and "Der Termin steht" in texts and "Zusammenfassung" in texts


def test_script_card_intro_only_on_first_visit(env):
    """Die ausführliche Einleitung steht nur auf der ersten Skript-Karte, nicht nach Skriptwahl
    und nicht, wenn die Karte aus der Zusammenfassung heraus geöffnet wird."""
    from discord_ui.layout_v2 import script_layout
    bot = env
    draft = new_draft(bot)

    def card_text(d):
        layout, _ = run(script_layout(bot, bot.store, d))
        return " ".join(i.content for i in layout.walk_children() if isinstance(i, discord.ui.TextDisplay))

    assert "Der Termin steht" in card_text(bot.store.get_draft(draft.id))
    d = bot.store.get_draft(draft.id)
    bot.store.update_draft(d.id, d.data, "script:p", int(NOW.timestamp()))
    assert "Der Termin steht" not in card_text(bot.store.get_draft(draft.id))
    click(bot, draft.id, "pick", "trouble_brewing")
    d = bot.store.get_draft(draft.id)
    bot.store.update_draft(d.id, d.data, "script", int(NOW.timestamp()))
    text = card_text(bot.store.get_draft(draft.id))
    assert "Der Termin steht" not in text and "Aktuell: **Trouble Brewing**" in text


def test_script_dialog_attached_file_wins(env, monkeypatch):
    """Eine angehängte JSON-Datei zählt ohne Extra-Auswahl, auch vor Suchrest und Basis-Skript."""
    import json
    from discord_ui.wizard import ScriptModal

    async def no_rater(script):
        return None

    monkeypatch.setattr(wizard, "rate_script", no_rater)
    bot = env
    draft = new_draft(bot)
    payload = json.dumps([{"id": "_meta", "name": "Mein Skript", "author": "Ich"}, "imp", "washerwoman"]).encode()

    class Attachment:
        size = len(payload)

        async def read(self):
            return payload

    modal = ScriptModal(draft.id)
    assert "upload" not in [o.value for o in modal.kind.options]
    modal.query._value = "boo"
    modal.kind._value = "trouble_brewing"
    modal.file._values = [Attachment()]
    run(modal.on_submit(FakeInteraction(bot, bot.guild.get_member(USER))))
    assert bot.store.get_draft(draft.id).data.script.name == "Mein Skript"
