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
    base_title,
    full_description,
    full_title,
    time_name,
    title_prefix,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=BERLIN_TZ)


def make(**kw) -> EventData:
    base = dict(
        start=NOW + timedelta(days=5, hours=8),  # 20:00, keine Srunde
        storyteller=Person("Dalyan", 1),
        script=ScriptRef(kind=SCRIPT_BOTCSCRIPTS, name="Boozling", author="Lau", version="9.0.0",
                         botcscripts_id="173", characters=["noble", "imp"]),
        description="Wir spielen Boozling.",
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
        assert d.co_st_status == "no" and d.co_st_note == ""


class TestSerialization:
    def test_roundtrip(self):
        d = make(co_st_status="open", co_st_note="gern Neulinge", rating="red", is_special=True, special_reasons=["Loric: Bootlegger"],
                 reminder_overrides={"r1": {"mode": "names"}})
        again = EventData.from_dict(d.to_dict())
        assert again == d
        assert again.start.tzinfo is not None

    def test_unknown_keys_are_ignored(self):
        d = make().to_dict()
        d["old_field"] = 1
        assert EventData.from_dict(d).description == "Wir spielen Boozling."


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

    def test_academy_and_casual_together(self):
        d = normalize(make(is_academy=True, is_casual=True))
        assert validate(d, NOW) == [] and d.is_academy and d.is_casual
        assert title_prefix(make(is_academy=True, is_casual=True, rating="green")) == "💚 🎓 🕊️"

    def test_unknown_values(self):
        assert validate(make(level="Gott"), NOW)
        assert validate(make(camera="maybe"), NOW)
        assert validate(make(rating="purple"), NOW)

    def test_missing_for_publish(self):
        assert missing_for_publish(make(rating="green")) == []
        assert missing_for_publish(EventData()) == ["Termin", "Skript", "Storyteller", "Schwierigkeit",
                                                    "Beschreibung"]

    def test_legacy_homebrew_flag_becomes_special(self):
        d = make().to_dict()
        d.pop("is_special"); d["is_homebrew"] = True
        assert EventData.from_dict(d).is_special
        assert "Beschreibung" not in missing_for_publish(EventData(is_academy=True))


class TestTemplates:
    def test_title_without_co_st(self):
        """Co-Storytelling steht nicht im Titel (Dalyan, 26.10.2026)."""
        d = make(co_st_status="taken", co_st_note="Rosanna")
        assert base_title(d) == "Boozling mit Dalyan"

    def test_title_base_script_full_name(self):
        d = make(script=ScriptRef(kind=SCRIPT_BASE, name="tb", base_key="trouble_brewing"))
        assert base_title(d) == "Trouble Brewing mit Dalyan"

    def test_free_choice(self):
        d = make(script=ScriptRef(kind=SCRIPT_FREE))
        assert base_title(d) == "Freie Skriptwahl mit Dalyan"
        assert title_prefix(d) == "💚/🟡/🟥"

    def test_prefix_order(self):
        d = make(is_recorded=True, is_academy=True, rating="red", is_special=True)
        assert title_prefix(d) == "🟥 🎦 🎓 ⭐"
        assert full_title(d) == "🟥 🎦 🎓 ⭐ Boozling mit Dalyan"

    def test_rating_ranges(self):
        assert title_prefix(make(rating="green_yellow")) == "💚/🟡"
        assert title_prefix(make(rating="yellow_red", is_special=True)) == "🟡/🟥 ⭐"
        assert title_prefix(make(rating="any")) == "💚/🟡/🟥"
        assert validate(make(rating="green_yellow"), NOW) == []
        text = academy_description("green_yellow")
        assert "**💚-Angebote" in text and "**🟡-Angebote" in text and "**🟥" not in text
        assert "(hier 200)" in text

    def test_custom_title_keeps_symbols(self):
        assert full_title(make(title="  Spukige Nacht ", rating="red")) == "🟥 Spukige Nacht"
        assert validate(make(title="x" * 201), NOW)

    def test_casual_prefix(self):
        assert title_prefix(make(is_casual=True, rating="green")) == "💚 🕊️"

    def test_no_prefix(self):
        assert full_title(make()) == "Boozling mit Dalyan"

    def test_academy_description_bolds_rating_line(self):
        text = academy_description("yellow")
        assert "**🟡-Angebote: maximal 200 Runden gespielt**" in text
        assert "(hier 200)" in text
        assert "**💚" not in text

    def test_academy_appends_fixed_text(self):
        d = make(is_academy=True, rating="green")
        assert full_description(d) == "Wir spielen Boozling.\n\n" + academy_description("green")
        assert full_description(make(is_academy=True, description="")) == academy_description(None)

    def test_description_without_academy_is_own_text(self):
        assert full_description(make(description="  Hallo  ")) == "Hallo"

    def test_long_description_rejected(self):
        assert validate(make(description="x" * 2001), NOW)

    def test_camera_off_is_valid(self):
        assert validate(make(camera=CAMERA_OFF), NOW) == []


def test_custom_academy_template():
    """Eigener Academy-Text (Dalyan, 26.10.2026): Stufen-Zeilen werden fett, {hier} nimmt die Zahl daraus."""
    template = "Hallo Academy!\n💚 bis 50 Runden\n🟡 bis 120 Runden\nDarüber {hier} als Auffüller."
    text = academy_description("yellow", template)
    assert "**🟡 bis 120 Runden**" in text and "**💚" not in text and "(hier 120)" in text
    assert "(s. oben)" in academy_description(None, template)
    assert full_description(make(is_academy=True, rating="green", description=""), template).startswith("Hallo")


def test_time_name_by_start_hour():
    """Nachmittag „Srunde“, um Mitternacht „Trunde“, getrennt mit „·“ (Dalyan, 29.10.2026)."""
    day = datetime(2026, 10, 24, tzinfo=BERLIN_TZ)
    cases = {12: "Srunde", 15: "Srunde", 16: "Srunde", 17: "", 18: "", 20: "", 22: "", 23: "Trunde", 0: "Trunde",
             1: "Trunde", 2: ""}
    for hour, name in cases.items():
        assert time_name(make(start=day + timedelta(hours=hour))) == name, hour
    d = make(start=day + timedelta(hours=15), rating="green", is_academy=True)
    assert full_title(d) == "💚 🎓 Srunde · Boozling mit Dalyan"
    assert full_title(make(start=day + timedelta(hours=23, minutes=30), title="Geisterstunde")) == \
        "Trunde · Geisterstunde"
    assert time_name(make(start=day + timedelta(hours=15), is_other_event=True)) == ""  # nur Runden
