"""Academy-Text und Standard-Beschreibung per DM bearbeiten (Dalyan, 27.10.2026)."""

from types import SimpleNamespace

import discord

from discord_ui import text_edit
from events import service, user_settings
from events.permissions import AccessSettings
from tests.test_wizard_flow import GUILD, USER, FakeInteraction, env, run  # noqa: F401 (Fixture)


class DMChannel:
    def __init__(self):
        self.id, self.messages, self.sent = 777, {}, []

    async def fetch_message(self, mid):
        return self.messages[mid]

    async def send(self, **kw):
        self.sent.append(kw)


class Card:
    _next = 5000

    def __init__(self, channel, view):
        Card._next += 1
        self.id, self.channel, self.view = Card._next, channel, view
        channel.messages[self.id] = self

    async def edit(self, view=None, **kw):
        self.view = view


def with_dm(member, closed=False):
    channel = DMChannel()

    async def send(view=None, **kw):
        if closed:
            raise discord.Forbidden(SimpleNamespace(status=403, reason="closed"), "closed")
        return Card(channel, view)

    member.send = send
    return channel


def texts(view) -> str:
    return "\n".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))


def button_ids(view) -> list[str]:
    return [getattr(i, "item", i).custom_id for i in view.walk_children()
            if isinstance(getattr(i, "item", i), discord.ui.Button)]


def dm(bot, user_id, content="", attachments=()):
    reactions, replies = [], []

    async def react(emoji):
        reactions.append(emoji)

    async def reply(text, **kw):
        replies.append(text)

    member = bot.guild.get_member(user_id)
    msg = SimpleNamespace(guild=None, author=SimpleNamespace(id=user_id, bot=False), channel=member.dm,
                          content=content, attachments=list(attachments), add_reaction=react, reply=reply)
    taken = run(text_edit.take_text(bot, msg))
    return taken, reactions, replies


def academy_command(bot, user_id):
    from commands.event_settings import EventSettings
    cog = EventSettings(bot)
    inter = FakeInteraction(bot, bot.guild.get_member(user_id), guild_id=GUILD)
    run(cog.academy_text.callback(cog, inter))
    return inter


def test_academy_text_via_dm(env):
    bot = env
    admin = bot.guild.get_member(USER)
    admin.dm = with_dm(admin)

    inter = academy_command(bot, USER)
    assert inter.sent == [text_edit.IN_DMS] and inter.response.modal is None
    card = next(iter(admin.dm.messages.values()))
    assert "Clocktower Academy" in texts(card.view)  # aktueller Text steht in der Karte
    assert f"tedit:{GUILD}:academy:reset" in button_ids(card.view)

    # Die nächste DM ist der neue Text, mit Formatierung und Emojis
    taken, reactions, _ = dm(bot, USER, "**Neu** 🎓\n🟡 bis 99 Runden {hier}")
    assert taken and reactions == ["✅"]
    assert service.get_academy_template(bot.store, GUILD) == "**Neu** 🎓\n🟡 bis 99 Runden {hier}"
    assert "Gespeichert." in texts(card.view) and "**🟡 bis 99 Runden (hier 99)**" in texts(card.view)
    # Danach wartet der Bot nicht mehr: die nächste DM bleibt unberührt
    assert dm(bot, USER, "Hallo")[0] is False

    # Zurücksetzen über den Button
    again = FakeInteraction(bot, admin, message=card)
    run(text_edit.TextEditButton(GUILD, "academy", "reset").callback(again))
    assert "Clocktower Academy" in service.get_academy_template(bot.store, GUILD)
    assert "eingebaute Academy-Text gilt wieder" in texts(again.screen["view"])


def test_academy_text_permissions_and_closed_dms(env):
    bot = env
    anna = bot.guild.get_member(3)
    anna.dm = with_dm(anna)
    stranger = academy_command(bot, 3)
    assert "Academy-Berechtigung" in stranger.sent[0] and not anna.dm.messages

    service.set_access(bot.store, GUILD, AccessSettings(academy_user_ids=[3]))
    assert academy_command(bot, 3).sent == [text_edit.IN_DMS]

    admin = bot.guild.get_member(USER)
    admin.dm = with_dm(admin, closed=True)
    assert academy_command(bot, USER).sent == [text_edit.DM_CLOSED]


def test_too_long_text_keeps_waiting_and_cancel(env):
    bot = env
    member = bot.guild.get_member(2)
    member.dm = with_dm(member)
    assert run(text_edit.start(bot, bot.guild, member, "description"))
    taken, _, replies = dm(bot, 2, "x" * 3001)
    assert taken and "erlaubt sind 2000" in replies[0]
    assert user_settings.get(bot.store, GUILD, 2).description == ""

    card = next(iter(member.dm.messages.values()))
    inter = FakeInteraction(bot, member, message=card)
    run(text_edit.TextEditButton(GUILD, "description", "cancel").callback(inter))
    assert dm(bot, 2, "Spät")[0] is False


def test_description_default_via_dm_and_txt(env):
    bot = env
    from discord_ui.user_settings import SettingsButton
    member = bot.guild.get_member(2)
    member.dm = with_dm(member)
    inter = FakeInteraction(bot, member)
    run(SettingsButton(GUILD, "description").callback(inter))
    assert inter.response.modal is None and text_edit.IN_DMS in texts(inter.screen["view"])

    async def read():
        return "**Ablauf**\n- Begrüßung 👋".encode("utf-8")
    txt = SimpleNamespace(filename="vorlage.txt", size=40, read=read)
    taken, reactions, _ = dm(bot, 2, "", [txt])
    assert taken and reactions == ["✅"]
    assert user_settings.get(bot.store, GUILD, 2).description == "**Ablauf**\n- Begrüßung 👋"


def test_raw_text_for_copying(env):
    bot = env
    admin = bot.guild.get_member(USER)
    service.set_academy_template(bot.store, GUILD, "**Fett** 💚")
    inter = FakeInteraction(bot, admin)
    run(text_edit.TextEditButton(GUILD, "academy", "raw").callback(inter))
    assert "```\n**Fett** 💚\n```" in texts(inter.sent_kw[0]["view"])


def test_wizard_chat_input_ends_text_edit(env):
    """„Im Chat schreiben“ im Wizard beendet eine offene Textbearbeitung, sonst landet die Nachricht falsch."""
    from discord_ui import wizard
    from tests.test_wizard_flow import chat_message, new_draft
    bot = env
    admin = bot.guild.get_member(USER)
    admin.dm = with_dm(admin)
    academy_command(bot, USER)
    assert bot.store.get_text_edit(USER, 0) is not None
    draft = new_draft(bot)
    ctx = wizard.WizardContext(bot, bot.store, draft, None, admin)
    run(wizard._start_chat_input(FakeInteraction(bot, admin), ctx, "description"))
    assert bot.store.get_text_edit(USER, 0) is None
    assert run(chat_message(bot, "Beschreibung aus dem Chat"))
