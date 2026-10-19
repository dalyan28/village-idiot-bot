"""Tests für Feldschema, Validierung und Vorlagen."""

from datetime import datetime, timedelta

from events.schema import (
    BERLIN_TZ,
    CAMERA_OFF,
    DEFAULT_DURATION_MINUTES,
    DEFAULT_LEVEL,
    DEFAULT_MAX_PLAYERS,
    SCRIPT_BASE,
    SCRIPT_BOTCSCRIPTS,
    SCRIPT_FREE,
    EventData,
    Person,
    ScriptRef,
    missing_for_publish,
    normalize,
    validate,
)
from events.templates import (
    academy_description,
    default_description,
    default_title,
    full_title,
    title_prefix,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=BERLIN_TZ)


def make(**kw) -> EventData:
    base = dict(
        start=NOW + timedelta(days=5),
        storyteller=Person("Dalyan", 1),
        script=ScriptRef(kind=SCRIPT_BOTCSCRIPTS, name="Boozling", author="Lau", version="9.0.0",
                         botcscripts_id="173", characters=["noble", "imp"]),
        title="Boozling mit Dalyan",
    )
    base.update(kw)
    return EventData(**base)


class TestDefaults:
    def test_defaults_from_event_creation(self):
        d = EventData()
        assert d.max_players == DEFAULT_MAX_PLAYERS == 12
        assert d.duration_minutes == DEFAULT_DURATION_MINUTES == 150
        assert d.level == DEFAULT_LEVEL == "Alle"
        assert d.camera == "optional"
        assert not (d.is_casual or d.is_academy or d.is_recorded)
        assert d.co_storyteller is None


class TestSerialization:
    def test_roundtrip(self):
        d = make(co_storyteller=Person("Rosanna"), rating="red", is_homebrew=True,
                 reminder_overrides={"r1": {"mode": "names"}})
        again = EventData.from_dict(d.to_dict())
        assert again == d
        assert again.start.tzinfo is not None

    def test_unknown_keys_are_ignored(self):
        d = make().to_dict()
        d["old_field"] = 1
        assert EventData.from_dict(d).title == "Boozling mit Dalyan"


class TestValidate:
    def test_valid(self):
        assert validate(make(), NOW) == []

    def test_player_range(self):
        assert validate(make(max_players=1), NOW) == []
        assert validate(make(max_players=200), NOW) == []
        assert validate(make(max_players=0), NOW)
        assert validate(make(max_players=201), NOW)

    def test_start_in_past(self):
        assert validate(make(start=NOW - timedelta(minutes=1)), NOW)

    def test_start_check_can_be_skipped(self):
        assert validate(make(start=NOW - timedelta(days=1)), NOW, check_start=False) == []

    def test_academy_and_casual_conflict(self):
        assert validate(make(is_academy=True, is_casual=True), NOW)

    def test_normalize_academy_wins(self):
        d = normalize(make(is_academy=True, is_casual=True))
        assert d.is_academy and not d.is_casual

    def test_unknown_values(self):
        assert validate(make(level="Gott"), NOW)
        assert validate(make(camera="maybe"), NOW)
        assert validate(make(rating="purple"), NOW)

    def test_missing_for_publish(self):
        assert missing_for_publish(make()) == []
        assert missing_for_publish(EventData()) == ["Termin", "Skript", "Storyteller", "Titel"]


class TestTemplates:
    def test_title_with_co_st(self):
        d = make(co_storyteller=Person("Rosanna"))
        assert default_title(d) == "Boozling mit Dalyan und Rosanna"

    def test_title_base_script_full_name(self):
        d = make(script=ScriptRef(kind=SCRIPT_BASE, name="tb", base_key="trouble_brewing"))
        assert default_title(d) == "Trouble Brewing mit Dalyan"

    def test_free_choice(self):
        d = make(script=ScriptRef(kind=SCRIPT_FREE))
        assert default_title(d) == "Freie Skriptwahl mit Dalyan"
        assert "Freie Skriptwahl" in default_description(d)
        assert title_prefix(d) == "💚/🟡/🟥"

    def test_prefix_order(self):
        d = make(is_recorded=True, is_academy=True, rating="red", is_homebrew=True)
        assert title_prefix(d) == "🎦 🎓 ⚒️ 🟥"
        assert full_title(d) == "🎦 🎓 ⚒️ 🟥 Boozling mit Dalyan"

    def test_casual_prefix(self):
        assert title_prefix(make(is_casual=True, rating="green")) == "🕊️ 💚"

    def test_no_prefix(self):
        assert full_title(make()) == "Boozling mit Dalyan"

    def test_academy_description_bolds_rating_line(self):
        text = academy_description("yellow")
        assert "**🟡-Angebote: maximal 200 Runden gespielt**" in text
        assert "(hier 200)" in text
        assert "**💚" not in text

    def test_academy_uses_fixed_description(self):
        d = make(is_academy=True, rating="green")
        assert default_description(d) == academy_description("green")

    def test_camera_off_is_valid(self):
        assert validate(make(camera=CAMERA_OFF), NOW) == []
