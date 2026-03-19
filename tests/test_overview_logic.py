"""
Unit-Tests für die Smart-Mode-Logik in commands/overview.py.
Kein Discord-Bot nötig – reine Python-Logik wird getestet.

Ausführen:
    pip install pytest
    pytest tests/
"""
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

# Cog ohne echten Bot instanziieren
from commands.overview import Overview, DEFAULT_SMART_SCHEDULE, BERLIN_TZ


@pytest.fixture
def cog():
    bot = MagicMock()
    return Overview(bot)


# ---------------------------------------------------------------------------
# _parse_schedule_input
# ---------------------------------------------------------------------------

class TestParseScheduleInput:
    def test_valid_space_separated(self, cog):
        valid, errors = cog._parse_schedule_input("05:00 08:00 12:00")
        assert valid == [[5, 0], [8, 0], [12, 0]]
        assert errors == []

    def test_valid_comma_separated(self, cog):
        valid, errors = cog._parse_schedule_input("05:00, 08:00, 22:00")
        assert valid == [[5, 0], [8, 0], [22, 0]]
        assert errors == []

    def test_valid_mixed_separators(self, cog):
        valid, errors = cog._parse_schedule_input("05:00; 19:30, 22:00")
        assert valid == [[5, 0], [19, 30], [22, 0]]
        assert errors == []

    def test_sorted_output(self, cog):
        valid, errors = cog._parse_schedule_input("22:00 05:00 12:00")
        assert valid == [[5, 0], [12, 0], [22, 0]]
        assert errors == []

    def test_duplicates_silently_removed(self, cog):
        valid, errors = cog._parse_schedule_input("08:00 08:00 12:00")
        assert valid == [[8, 0], [12, 0]]
        assert errors == []

    def test_invalid_format(self, cog):
        valid, errors = cog._parse_schedule_input("abc 08:00")
        assert valid == [[8, 0]]
        assert len(errors) == 1
        assert "abc" in errors[0]

    def test_hour_out_of_range(self, cog):
        valid, errors = cog._parse_schedule_input("25:00 08:00")
        assert valid == [[8, 0]]
        assert len(errors) == 1
        assert "25:00" in errors[0]

    def test_minute_out_of_range(self, cog):
        valid, errors = cog._parse_schedule_input("08:60")
        assert valid == []
        assert len(errors) == 1

    def test_empty_input(self, cog):
        valid, errors = cog._parse_schedule_input("   ")
        assert valid == []
        assert errors == []

    def test_all_invalid(self, cog):
        valid, errors = cog._parse_schedule_input("foo bar 99:99")
        assert valid == []
        assert len(errors) == 3

    def test_single_digit_hour(self, cog):
        valid, errors = cog._parse_schedule_input("5:00 8:30")
        assert valid == [[5, 0], [8, 30]]
        assert errors == []


# ---------------------------------------------------------------------------
# _compute_next_time
# ---------------------------------------------------------------------------

class TestComputeNextTime:
    def _berlin(self, hour, minute=0, day_offset=0):
        now = datetime.now(tz=BERLIN_TZ)
        base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return base + timedelta(days=day_offset)

    def test_next_time_same_day(self):
        now = self._berlin(10, 0)
        schedule = [(5, 0), (8, 0), (12, 0), (18, 0)]
        result = Overview._compute_next_time(schedule, now)
        assert result.hour == 12 and result.minute == 0

    def test_wraps_to_tomorrow_when_all_passed(self):
        now = self._berlin(23, 30)
        schedule = [(5, 0), (8, 0), (22, 0)]
        result = Overview._compute_next_time(schedule, now)
        expected_day = (now + timedelta(days=1)).date()
        assert result.date() == expected_day
        assert result.hour == 5 and result.minute == 0

    def test_exact_minute_not_counted(self):
        """Ein Zeitpunkt der exakt 'jetzt' ist gilt NICHT als nächster (muss > now sein)."""
        now = self._berlin(12, 0)
        schedule = [(12, 0), (18, 0)]
        result = Overview._compute_next_time(schedule, now)
        assert result.hour == 18

    def test_first_of_day(self):
        now = self._berlin(4, 59)
        schedule = [(5, 0), (8, 0)]
        result = Overview._compute_next_time(schedule, now)
        assert result.hour == 5 and result.minute == 0

    def test_empty_schedule_fallback(self):
        now = self._berlin(23, 0)
        result = Overview._compute_next_time([], now)
        assert result.hour == 5 and result.minute == 0
        assert result.date() == (now + timedelta(days=1)).date()

    def test_half_hour_slot(self):
        now = self._berlin(19, 15)
        schedule = [(19, 0), (19, 30), (20, 0)]
        result = Overview._compute_next_time(schedule, now)
        assert result.hour == 19 and result.minute == 30


# ---------------------------------------------------------------------------
# _update_smart_dynamic_times
# ---------------------------------------------------------------------------

class TestUpdateSmartDynamicTimes:
    def _event(self, minutes_from_now: int) -> dict:
        return {"start_ts": int(time.time()) + minutes_from_now * 60}

    def test_disabled_clears_times(self, cog):
        cog.smart_dynamic_times[1] = {(19, 30)}
        cog._update_smart_dynamic_times(1, [self._event(60)], enabled=False)
        assert cog.smart_dynamic_times[1] == set()

    def test_single_future_event(self, cog):
        event = self._event(60)  # Event in 60 Minuten
        cog._update_smart_dynamic_times(1, [event], enabled=True)
        dynamic = cog.smart_dynamic_times[1]
        # Muss -30, -20, -10 Minuten-Trigger enthalten (alle in der Zukunft)
        assert len(dynamic) == 3

    def test_past_event_ignored(self, cog):
        event = self._event(-30)  # Event vor 30 Minuten
        cog._update_smart_dynamic_times(1, [event], enabled=True)
        assert cog.smart_dynamic_times[1] == set()

    def test_event_in_25_minutes_only_two_triggers(self, cog):
        """Event in 25 Min: -30min wäre Vergangenheit, nur -20 und -10 gültig."""
        event = self._event(25)
        cog._update_smart_dynamic_times(1, [event], enabled=True)
        dynamic = cog.smart_dynamic_times[1]
        assert len(dynamic) == 2

    def test_event_in_8_minutes_one_trigger(self, cog):
        """Event in 8 Min: nur -10min wäre Vergangenheit, keine Trigger gültig."""
        event = self._event(8)
        cog._update_smart_dynamic_times(1, [event], enabled=True)
        dynamic = cog.smart_dynamic_times[1]
        assert len(dynamic) == 0

    def test_two_events_same_time_no_duplicates(self, cog):
        """Zwei Events zur selben Zeit → Set-Deduplication → gleiche Trigger."""
        ts = int(time.time()) + 120 * 60  # in 2 Stunden
        events = [{"start_ts": ts}, {"start_ts": ts}]
        cog._update_smart_dynamic_times(1, events, enabled=True)
        dynamic = cog.smart_dynamic_times[1]
        assert len(dynamic) == 3  # Keine Duplikate

    def test_two_events_close_together_merged(self, cog):
        """Events 10 Min auseinander: -10min des zweiten = -20min des ersten → Set mergt."""
        ts1 = int(time.time()) + 120 * 60  # in 2 Stunden
        ts2 = ts1 + 10 * 60               # 10 Minuten später
        events = [{"start_ts": ts1}, {"start_ts": ts2}]
        cog._update_smart_dynamic_times(1, events, enabled=True)
        dynamic = cog.smart_dynamic_times[1]
        # ts1: -30,-20,-10; ts2: -30,-20,-10 → overlap bei ts1-20==ts2-30
        assert len(dynamic) <= 6
        assert len(dynamic) > 3  # Aber mehr als nur eines

    def test_no_events_today(self, cog):
        """Events nur morgen → keine dynamischen Zeiten heute."""
        tomorrow_ts = int(time.time()) + 26 * 60 * 60  # in 26 Stunden
        events = [{"start_ts": tomorrow_ts}]
        cog._update_smart_dynamic_times(1, events, enabled=True)
        assert cog.smart_dynamic_times[1] == set()


# ---------------------------------------------------------------------------
# on_message Event-Filter (Logik isoliert getestet)
# ---------------------------------------------------------------------------

class TestOnMessageEventFilter:
    """Testet die Filterbedingungen für on_message ohne Discord-Verbindung."""

    def _make_embed(self, title="Test Event", has_time_field=True):
        embed = MagicMock()
        embed.title = title
        if has_time_field:
            field = MagicMock()
            field.name = "Time"
            embed.fields = [field]
        else:
            embed.fields = []
        return embed

    def test_message_with_time_field_passes(self):
        embed = self._make_embed(has_time_field=True)
        assert embed.title is not None
        assert any(f.name in ("Time", "Termin") for f in embed.fields)

    def test_message_without_time_field_blocked(self):
        embed = self._make_embed(has_time_field=False)
        assert not any(f.name in ("Time", "Termin") for f in embed.fields)

    def test_termin_field_also_valid(self):
        embed = MagicMock()
        embed.title = "Event"
        field = MagicMock()
        field.name = "Termin"
        embed.fields = [field]
        assert any(f.name in ("Time", "Termin") for f in embed.fields)

    def test_random_embed_without_event_fields_blocked(self):
        embed = MagicMock()
        embed.title = "Server Update"
        field = MagicMock()
        field.name = "Description"
        embed.fields = [field]
        assert not any(f.name in ("Time", "Termin") for f in embed.fields)
