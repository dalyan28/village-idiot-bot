"""Tests für Reminder: Standard/Anpassung, Fälligkeit, Empfänger, Text, Wizard-Unterseite, Senden."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from commands.reminder import ReminderCog, _chunks, script_json
from events import reminders
from events.reminders import FIRST, SECOND, MODE_NAMES, TO_CO, TO_TENTATIVE, TO_WAITLIST
from events.schema import BERLIN_TZ, SCRIPT_BASE, SCRIPT_FREE, SCRIPT_UPLOAD, EventData, Person, ScriptRef
from events.service import RsvpLists

START = datetime(2026, 10, 24, 20, 0, tzinfo=BERLIN_TZ)


def lists():
    return RsvpLists(players=[Person("Anna", 1), Person("Ben", 2)], waitlist=[Person("Cleo", 3)],
                     tentative=[Person("Dan", 4)], declined=[Person("Eva", 5)])


class TestSettings:
    def test_defaults_like_before(self):
        cfgs = reminders.effective({}, EventData())
        assert cfgs[FIRST].minutes_before == 15 and cfgs[FIRST].post_script and cfgs[FIRST].mode == "ping"
        assert cfgs[SECOND].minutes_before == 5 and cfgs[SECOND].kind == "attendance"
        assert cfgs[FIRST].recipients == ["accepted", "storyteller"]  # Warteliste nicht, ST schon
        # Anwesenheitsliste kommt mit der ersten Erinnerung, die zweite ist standardmäßig aus
        assert cfgs[FIRST].post_attendance and not cfgs[SECOND].post_attendance
        assert not cfgs[SECOND].enabled
        assert "mit Anwesenheitsliste" in reminders.describe(cfgs[FIRST])

    def test_server_default_then_event_override(self):
        cfg = reminders.copy_of(reminders.DEFAULTS[FIRST])
        cfg.minutes_before = 30
        settings = reminders.store_server_choice({"access": {"x": 1}}, cfg)
        assert settings["access"] == {"x": 1}
        assert settings["reminders"] == {FIRST: {"minutes_before": 30}}

        data = EventData()
        mine = reminders.copy_of(reminders.effective(settings, data)[FIRST])
        mine.mode = MODE_NAMES
        reminders.store_event_choice(settings, data, mine)
        assert data.reminder_overrides == {FIRST: {"mode": "names"}}  # nur die Abweichung
        eff = reminders.effective(settings, data)[FIRST]
        assert eff.minutes_before == 30 and eff.mode == MODE_NAMES

        # Server ändert später die Minuten → greift auch beim Event mit eigener Anpassung
        cfg.minutes_before = 45
        settings = reminders.store_server_choice(settings, cfg)
        assert reminders.effective(settings, data)[FIRST].minutes_before == 45

    def test_override_equal_to_default_is_removed(self):
        data = EventData(reminder_overrides={FIRST: {"mode": "names"}})
        reminders.store_event_choice({}, data, reminders.copy_of(reminders.DEFAULTS[FIRST]))
        assert data.reminder_overrides == {}

    def test_defaults_are_never_mutated(self):
        cfg = reminders.effective({}, EventData())[FIRST]
        cfg.recipients.append(TO_CO)
        assert reminders.DEFAULTS[FIRST].recipients == ["accepted", "storyteller"]

    def test_validate(self):
        bad = reminders.copy_of(reminders.DEFAULTS[FIRST])
        bad.minutes_before = -1
        bad.recipients = ["alle"]
        assert len(reminders.validate(bad)) == 2


class TestDue:
    # beide Erinnerungen an (die zweite ist standardmäßig aus)
    cfgs = reminders.effective({}, EventData(reminder_overrides={SECOND: {"enabled": True}}))

    def test_not_yet(self):
        assert reminders.due(self.cfgs, START, START - timedelta(minutes=16), set()) == []

    def test_first_due(self):
        assert [c.key for c in reminders.due(self.cfgs, START, START - timedelta(minutes=15), set())] == [FIRST]

    def test_missed_ones_are_caught_up_until_start(self):
        due = reminders.due(self.cfgs, START, START - timedelta(minutes=2), set())
        assert [c.key for c in due] == [FIRST, SECOND]
        assert reminders.due(self.cfgs, START, START, set()) == []

    def test_sent_and_disabled_are_skipped(self):
        assert reminders.due(self.cfgs, START, START - timedelta(minutes=1), {FIRST, SECOND}) == []
        cfgs = reminders.effective({}, EventData())  # Standard: zweite Erinnerung aus
        assert [c.key for c in reminders.due(cfgs, START, START - timedelta(minutes=1), {FIRST})] == []


class TestText:
    def test_recipients(self):
        cfg = reminders.copy_of(reminders.DEFAULTS[FIRST])
        data = EventData(co_storyteller=Person("Rosa", 9))
        assert [p.name for p in reminders.recipients(cfg, lists(), data)] == ["Anna", "Ben"]
        cfg.recipients = ["accepted", TO_WAITLIST, TO_TENTATIVE, TO_CO]
        assert [p.name for p in reminders.recipients(cfg, lists(), data)] == ["Anna", "Ben", "Cleo", "Dan", "Rosa"]

    def test_ping_vs_names(self):
        cfg = reminders.copy_of(reminders.DEFAULTS[FIRST])
        people = [Person("An_na", 1), Person("Freitext")]
        assert "<@1>" in reminders.message_text(cfg, START, people)
        cfg.mode = MODE_NAMES
        text = reminders.message_text(cfg, START, people)
        assert "<@" not in text and "An\\_na" in text and "Freitext" in text

    def test_attendance(self):
        cfg = reminders.copy_of(reminders.DEFAULTS[SECOND])
        assert "1. <@1>" in reminders.message_text(cfg, START, [Person("Anna", 1)])
        assert "keine Zusagen" in reminders.message_text(cfg, START, [])


def test_attendance_txt():
    data = EventData(start=START, storyteller=Person("Dalyan", 7), script=ScriptRef(kind="botcscripts",
                                                                                     name="Boozling"))
    text = reminders.attendance_txt(data, [Person("Anna", 1), Person("Rosanna", 2)])
    assert text == "Boozling mit Dalyan\nSamstag, 24.10.2026, 20:00\n\n[ ] Anna\n[ ] Rosanna\n"
    assert "<@" not in text


def test_script_json_variants():
    assert script_json(ScriptRef(kind=SCRIPT_FREE)) is None
    tb = script_json(ScriptRef(kind=SCRIPT_BASE, name="Trouble Brewing", characters=["imp"]))
    assert tb == [{"id": "_meta", "name": "Trouble Brewing"}, {"id": "imp"}]
    content = [{"id": "_meta", "name": "X"}, {"id": "imp"}]
    assert script_json(ScriptRef(kind=SCRIPT_UPLOAD, name="X", characters=["imp"], content=content)) is content


def test_chunks_split_long_ping_lists():
    text = " ".join(f"<@{10**17 + i}>" for i in range(200))
    parts = _chunks(text)
    assert all(len(p) <= 2000 for p in parts) and len(parts) > 1
    assert " ".join(parts).split() == text.split()


def test_send_reminder_posts_into_thread():
    sent = []

    class Thread:
        async def send(self, content=None, file=None, allowed_mentions=None):
            sent.append((content, file.filename if file else None, allowed_mentions))

    async def go():
        cog = ReminderCog.__new__(ReminderCog)  # ohne Schleifen-Start
        cog.store = SimpleNamespace()
        cog.bot = None

        async def thread(event):
            return Thread()
        cog._thread = thread
        import events.service as svc
        orig = svc.rsvp_lists
        svc.rsvp_lists = lambda store, event: lists()
        try:
            event = SimpleNamespace(id=1, data=EventData(start=START, script=ScriptRef(
                kind=SCRIPT_BASE, name="Trouble Brewing", characters=["imp"])))
            await cog.send_reminder(event, reminders.copy_of(reminders.DEFAULTS[FIRST]))
        finally:
            svc.rsvp_lists = orig

    asyncio.run(go())
    assert "<@1> <@2>" in sent[0][0] and "<@3>" not in sent[0][0]
    assert sent[0][2].everyone is False and sent[0][2].roles is False
    assert sent[1][1] == "Trouble Brewing.json"
    assert sent[2][1] == "anwesenheit.txt"  # Ping, Skript, Anwesenheitsliste: alles auf einmal


def test_no_attendance_file_without_recipients():
    sent = []

    class Thread:
        async def send(self, content=None, file=None, allowed_mentions=None):
            sent.append(file.filename if file else None)

    async def go():
        cog = ReminderCog.__new__(ReminderCog)
        cog.store = SimpleNamespace()
        cog.bot = None

        async def thread(event):
            return Thread()
        cog._thread = thread
        import events.service as svc
        orig = svc.rsvp_lists
        svc.rsvp_lists = lambda store, event: RsvpLists(players=[], waitlist=[], tentative=[], declined=[])
        try:
            event = SimpleNamespace(id=1, data=EventData(start=START, script=ScriptRef(kind=SCRIPT_FREE)))
            await cog.send_reminder(event, reminders.copy_of(reminders.DEFAULTS[FIRST]))
        finally:
            svc.rsvp_lists = orig

    asyncio.run(go())
    assert "anwesenheit.txt" not in sent


def test_storyteller_is_pinged_but_not_on_attendance_list():
    cfg = reminders.copy_of(reminders.DEFAULTS[FIRST])
    data = EventData(start=START, storyteller=Person("Dalyan", 7), script=ScriptRef(kind="botcscripts", name="X"))
    people = reminders.recipients(cfg, lists(), data)
    assert [p.name for p in people] == ["Anna", "Ben", "Dalyan"]
    assert "<@7>" in reminders.message_text(cfg, START, people)
    txt = reminders.attendance_txt(data, people)
    assert "[ ] Anna" in txt and "Dalyan\n" not in txt.split("\n\n", 1)[1]
