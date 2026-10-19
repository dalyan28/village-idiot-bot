"""Tests für Store und Service: Entwürfe, Veröffentlichen, Bearbeiten, Anmeldungen."""

from datetime import datetime, timedelta

import pytest

from events import service
from events.permissions import AccessSettings, Actor
from events.schema import BERLIN_TZ, SCRIPT_BASE, EventData, Person, ScriptRef
from events.service import PermissionDenied, ServiceError
from events.store import RSVP_ACCEPTED, RSVP_DECLINED, RSVP_TENTATIVE, Store

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=BERLIN_TZ)
GUILD = 10
ST_ROLE, TEAM_ROLE, ACADEMY_ROLE = 100, 200, 300

st = Actor(1, frozenset({ST_ROLE}))
other_st = Actor(2, frozenset({ST_ROLE}))
team = Actor(3, frozenset({TEAM_ROLE}))
academy_st = Actor(4, frozenset({ST_ROLE, ACADEMY_ROLE}))


@pytest.fixture
def store():
    s = Store(":memory:")
    service.set_access(s, GUILD, AccessSettings(storyteller_role_id=ST_ROLE, event_team_role_id=TEAM_ROLE,
                                                academy_role_ids=[ACADEMY_ROLE]))
    yield s
    s.close()


def modal_data(**kw) -> EventData:
    d = EventData(start=NOW + timedelta(days=5))
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def complete(data: EventData) -> EventData:
    data.script = ScriptRef(kind=SCRIPT_BASE, name="Trouble Brewing", base_key="trouble_brewing")
    data.title = "Trouble Brewing mit Dalyan"
    return data


def published(store, actor=st, **kw):
    draft = service.start_draft(store, GUILD, actor, "Dalyan", modal_data(**kw), NOW)
    draft = service.update_draft(store, draft, actor, complete(draft.data), "preview", NOW)
    return service.publish_draft(store, draft, actor, "Dalyan", NOW).event


class TestAccessSettings:
    def test_roundtrip_and_other_settings_survive(self, store):
        store.set_guild_settings(GUILD, {**store.get_guild_settings(GUILD), "reminders": {"x": 1}})
        service.set_access(store, GUILD, AccessSettings(storyteller_role_id=5))
        assert service.get_access(store, GUILD).storyteller_role_id == 5
        assert store.get_guild_settings(GUILD)["reminders"] == {"x": 1}


class TestDrafts:
    def test_storyteller_defaults_to_user(self, store):
        draft = service.start_draft(store, GUILD, st, "Dalyan", modal_data(), NOW)
        assert draft.data.storyteller == Person("Dalyan", 1)
        assert draft.step == service.STEP_SCRIPT

    def test_needs_create_permission(self, store):
        with pytest.raises(PermissionDenied):
            service.start_draft(store, GUILD, Actor(9), "X", modal_data(), NOW)

    def test_academy_needs_permission(self, store):
        with pytest.raises(PermissionDenied):
            service.start_draft(store, GUILD, st, "Dalyan", modal_data(is_academy=True), NOW)
        draft = service.start_draft(store, GUILD, academy_st, "A", modal_data(is_academy=True, is_casual=True), NOW)
        assert draft.data.is_academy and not draft.data.is_casual

    def test_cannot_switch_on_academy_later(self, store):
        draft = service.start_draft(store, GUILD, st, "Dalyan", modal_data(), NOW)
        data = draft.data
        data.is_academy = True
        with pytest.raises(PermissionDenied):
            service.update_draft(store, draft, st, data, "details", NOW)

    def test_invalid_values_rejected(self, store):
        with pytest.raises(ServiceError):
            service.start_draft(store, GUILD, st, "Dalyan", modal_data(max_players=500), NOW)

    def test_open_draft_and_expiry(self, store):
        draft = service.start_draft(store, GUILD, st, "Dalyan", modal_data(), NOW)
        assert service.open_draft(store, GUILD, st.user_id, NOW).id == draft.id
        assert service.open_draft(store, GUILD, st.user_id, NOW + timedelta(hours=25)) is None
        assert service.open_draft(store, GUILD, other_st.user_id, NOW) is None

    def test_new_draft_replaces_old_one(self, store):
        old = service.start_draft(store, GUILD, st, "Dalyan", modal_data(), NOW)
        new = service.start_draft(store, GUILD, st, "Dalyan", modal_data(max_players=5), NOW)
        assert store.get_draft(old.id) is None
        assert [d.id for d in store.list_drafts(st.user_id)] == [new.id]

    def test_only_owner_updates(self, store):
        draft = service.start_draft(store, GUILD, st, "Dalyan", modal_data(), NOW)
        with pytest.raises(PermissionDenied):
            service.update_draft(store, draft, other_st, draft.data, "x", NOW)


class TestPublish:
    def test_incomplete_draft(self, store):
        draft = service.start_draft(store, GUILD, st, "Dalyan", modal_data(), NOW)
        with pytest.raises(ServiceError, match="Skript, Titel"):
            service.publish_draft(store, draft, st, "Dalyan", NOW)

    def test_creates_event_and_removes_draft(self, store):
        event = published(store)
        assert event.creator_id == st.user_id
        assert event.data.title == "Trouble Brewing mit Dalyan"
        assert store.list_drafts(st.user_id) == []
        assert store.list_log(event.id)[0]["action"] == "create"

    def test_message_lookup(self, store):
        event = published(store)
        store.set_event_message(event.id, 55, 999)
        assert store.get_event_by_message(999).id == event.id


class TestEdit:
    def test_edit_keeps_rsvps_and_logs_changes(self, store):
        event = published(store)
        service.toggle_rsvp(store, event, 50, "Anna", RSVP_ACCEPTED, NOW)
        draft = service.draft_for_edit(store, event, st, NOW)
        data = draft.data
        data.title = "Neu"
        draft = service.update_draft(store, draft, st, data, "preview", NOW)
        result = service.publish_draft(store, draft, st, "Dalyan", NOW)
        assert not result.created and not result.start_changed
        assert result.event.data.title == "Neu"
        assert result.changes["title"] == ["Trouble Brewing mit Dalyan", "Neu"]
        assert [p.name for p in service.rsvp_lists(store, result.event).players] == ["Anna"]

    def test_start_change_resets_reminders(self, store):
        event = published(store)
        store.mark_reminder_sent(event.id, "first", 1)
        draft = service.draft_for_edit(store, event, st, NOW)
        data = draft.data
        data.start = data.start + timedelta(hours=1)
        draft = service.update_draft(store, draft, st, data, "preview", NOW)
        result = service.publish_draft(store, draft, st, "Dalyan", NOW)
        assert result.start_changed
        assert store.sent_reminders(event.id) == set()

    def test_running_event_can_be_edited_without_changing_start(self, store):
        event = published(store)
        later = event.data.start + timedelta(minutes=30)  # Event läuft schon
        draft = service.draft_for_edit(store, event, st, later)
        data = draft.data
        data.description = "Korrektur"
        draft = service.update_draft(store, draft, st, data, "preview", later)
        assert service.publish_draft(store, draft, st, "Dalyan", later).event.data.description == "Korrektur"

    def test_other_storyteller_cannot_edit_but_team_can(self, store):
        event = published(store)
        with pytest.raises(PermissionDenied):
            service.draft_for_edit(store, event, other_st, NOW)
        draft = service.draft_for_edit(store, event, team, NOW)
        result = service.publish_draft(store, draft, team, "Team", NOW)
        assert result.event.creator_id == st.user_id  # Ersteller bleibt

    def test_delete(self, store):
        event = published(store)
        with pytest.raises(PermissionDenied):
            service.delete_event(store, event, other_st, NOW)
        service.delete_event(store, event, st, NOW)
        assert store.get_event(event.id) is None
        assert store.get_event(event.id, include_deleted=True).deleted_at is not None


class TestRsvp:
    def test_toggle(self, store):
        event = published(store)
        assert service.toggle_rsvp(store, event, 50, "Anna", RSVP_ACCEPTED, NOW) == RSVP_ACCEPTED
        assert service.toggle_rsvp(store, event, 50, "Anna", RSVP_ACCEPTED, NOW) is None
        assert service.rsvp_lists(store, event).accepted_count == 0

    def test_waitlist_by_order(self, store):
        event = published(store, max_players=2)
        for i, name in enumerate(["A", "B", "C", "D"]):
            service.toggle_rsvp(store, event, 50 + i, name, RSVP_ACCEPTED, NOW + timedelta(seconds=i))
        lists = service.rsvp_lists(store, event)
        assert [p.name for p in lists.players] == ["A", "B"]
        assert [p.name for p in lists.waitlist] == ["C", "D"]

        # A sagt ab → C rückt nach
        service.toggle_rsvp(store, event, 50, "A", RSVP_DECLINED, NOW + timedelta(seconds=10))
        lists = service.rsvp_lists(store, event)
        assert [p.name for p in lists.players] == ["B", "C"]
        assert [p.name for p in lists.waitlist] == ["D"]
        assert [p.name for p in lists.declined] == ["A"]

    def test_switching_back_goes_to_end_of_queue(self, store):
        event = published(store, max_players=1)
        service.toggle_rsvp(store, event, 1, "A", RSVP_ACCEPTED, NOW)
        service.toggle_rsvp(store, event, 2, "B", RSVP_ACCEPTED, NOW + timedelta(seconds=1))
        service.toggle_rsvp(store, event, 1, "A", RSVP_TENTATIVE, NOW + timedelta(seconds=2))
        service.toggle_rsvp(store, event, 1, "A", RSVP_ACCEPTED, NOW + timedelta(seconds=3))
        lists = service.rsvp_lists(store, event)
        assert [p.name for p in lists.players] == ["B"]
        assert [p.name for p in lists.waitlist] == ["A"]

    def test_name_is_updated(self, store):
        event = published(store)
        service.toggle_rsvp(store, event, 1, "Alt", RSVP_TENTATIVE, NOW)
        service.toggle_rsvp(store, event, 1, "Neu", RSVP_ACCEPTED, NOW)
        assert service.rsvp_lists(store, event).players[0] == Person("Neu", 1)


def test_cleanup(store):
    event = published(store)
    service.start_draft(store, GUILD, other_st, "X", modal_data(), NOW)
    later = event.data.start + timedelta(days=31)
    drafts, events = service.cleanup(store, later)
    assert (drafts, events) == (1, 1)
