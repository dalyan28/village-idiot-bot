"""Tests für Rechte und Server-Lock."""

import pytest

from events import guild_lock
from events.permissions import (
    CONFIGURE,
    CREATE,
    CREATE_ACADEMY,
    DELETE,
    EDIT,
    MANAGE_PARTICIPANTS,
    TAKE_OVER,
    AccessSettings,
    Actor,
    can,
)

ST_ROLE, TEAM_ROLE, ACADEMY_ROLE = 100, 200, 300
SETTINGS = AccessSettings(storyteller_role_id=ST_ROLE, event_team_role_id=TEAM_ROLE,
                          academy_role_ids=[ACADEMY_ROLE], academy_user_ids=[42])

nobody = Actor(1)
storyteller = Actor(2, frozenset({ST_ROLE}))
team = Actor(3, frozenset({TEAM_ROLE}))
admin = Actor(4, is_admin=True)
academy_st = Actor(5, frozenset({ST_ROLE, ACADEMY_ROLE}))
academy_user = Actor(42, frozenset({ST_ROLE}))


class TestCreate:
    def test_needs_storyteller_role_or_team(self):
        assert not can(nobody, CREATE, SETTINGS)
        assert can(storyteller, CREATE, SETTINGS)
        assert can(team, CREATE, SETTINGS)
        assert can(admin, CREATE, SETTINGS)

    def test_without_configured_role_only_team_and_admins(self):
        empty = AccessSettings()
        assert not can(Actor(2, frozenset({ST_ROLE})), CREATE, empty)
        assert can(admin, CREATE, empty)


class TestAcademy:
    def test_by_role_user_or_team(self):
        assert not can(storyteller, CREATE_ACADEMY, SETTINGS)
        assert can(academy_st, CREATE_ACADEMY, SETTINGS)
        assert can(academy_user, CREATE_ACADEMY, SETTINGS)
        assert can(team, CREATE_ACADEMY, SETTINGS)
        assert can(admin, CREATE_ACADEMY, SETTINGS)


class TestEventActions:
    @pytest.mark.parametrize("action", [EDIT, DELETE, MANAGE_PARTICIPANTS])
    def test_creator_and_team(self, action):
        assert can(storyteller, action, SETTINGS, creator_id=storyteller.user_id)
        assert not can(storyteller, action, SETTINGS, creator_id=999)
        assert can(team, action, SETTINGS, creator_id=999)
        assert can(admin, action, SETTINGS, creator_id=999)
        assert not can(nobody, action, SETTINGS, creator_id=999)

    def test_creator_keeps_rights_without_role(self):
        former = Actor(7)
        assert can(former, EDIT, SETTINGS, creator_id=7)
        assert not can(former, CREATE, SETTINGS)

    def test_take_over_and_configure_only_team(self):
        for action in (TAKE_OVER, CONFIGURE):
            assert not can(storyteller, action, SETTINGS, creator_id=storyteller.user_id)
            assert can(team, action, SETTINGS)
            assert can(admin, action, SETTINGS)

    def test_unknown_action(self):
        with pytest.raises(ValueError):
            can(admin, "fly", SETTINGS)


class TestGuildLock:
    def test_parse(self):
        assert guild_lock.parse_guild_ids(None) == frozenset()
        assert guild_lock.parse_guild_ids(" ") == frozenset()
        assert guild_lock.parse_guild_ids("1, 2;3,") == frozenset({1, 2, 3})
        with pytest.raises(ValueError):
            guild_lock.parse_guild_ids("123,abc")

    def test_allowed(self, monkeypatch):
        monkeypatch.setenv(guild_lock.ENV_VAR, "111,222")
        assert guild_lock.is_allowed(111)
        assert not guild_lock.is_allowed(333)
        assert not guild_lock.is_allowed(None)
        assert guild_lock.should_leave(333)
        assert not guild_lock.should_leave(111)

    def test_unconfigured_denies_but_never_leaves(self, monkeypatch):
        monkeypatch.delenv(guild_lock.ENV_VAR, raising=False)
        assert not guild_lock.is_allowed(111)
        assert not guild_lock.should_leave(111)
