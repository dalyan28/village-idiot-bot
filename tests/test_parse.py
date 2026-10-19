"""Tests für den Datums- und Uhrzeit-Parser des /botc-Modals."""

from datetime import date, datetime, time

import pytest

from events.parse import ParseError, format_start, parse_date, parse_start, parse_time
from events.schema import BERLIN_TZ

# Montag, 19.10.2026, 12:00
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=BERLIN_TZ)
TODAY = NOW.date()


class TestParseDate:
    @pytest.mark.parametrize("text, expected", [
        ("heute", date(2026, 10, 19)),
        ("Morgen", date(2026, 10, 20)),
        ("übermorgen", date(2026, 10, 21)),
        ("uebermorgen", date(2026, 10, 21)),
        ("in 3 Tagen", date(2026, 10, 22)),
        ("in einer Woche", date(2026, 10, 26)),
        ("in 2 Wochen", date(2026, 11, 2)),
    ])
    def test_relative(self, text, expected):
        assert parse_date(text, TODAY)[0] == expected

    @pytest.mark.parametrize("text, expected", [
        ("Samstag", date(2026, 10, 24)),
        ("sa", date(2026, 10, 24)),
        ("Sa.", date(2026, 10, 24)),
        ("am Samstag", date(2026, 10, 24)),
        ("Sonntag", date(2026, 10, 25)),
        ("Dienstag", date(2026, 10, 20)),
        ("Montag", date(2026, 10, 19)),           # heute, flexibel
        ("nächsten Montag", date(2026, 10, 26)),  # ausdrücklich nicht heute
        ("naechsten Samstag", date(2026, 10, 24)),
        ("kommenden Freitag", date(2026, 10, 23)),
    ])
    def test_weekdays(self, text, expected):
        assert parse_date(text, TODAY)[0] == expected

    def test_weekday_is_flexible_only_without_next(self):
        assert parse_date("Montag", TODAY)[1] is True
        assert parse_date("nächsten Montag", TODAY)[1] is False
        assert parse_date("24.10.", TODAY)[1] is False

    @pytest.mark.parametrize("text, expected", [
        ("24.10.", date(2026, 10, 24)),
        ("24.10", date(2026, 10, 24)),
        ("24.10.26", date(2026, 10, 24)),
        ("24.10.2026", date(2026, 10, 24)),
        ("2026-10-24", date(2026, 10, 24)),
        ("24/10", date(2026, 10, 24)),
        ("1.1.", date(2027, 1, 1)),          # ohne Jahr: nächstes Vorkommen
        ("19.10.", date(2026, 10, 19)),      # heute zählt noch als dieses Jahr
        ("18.10.", date(2027, 10, 18)),      # gestern → nächstes Jahr
        ("24. Oktober", date(2026, 10, 24)),
        ("24 okt", date(2026, 10, 24)),
        ("3. Jan 2027", date(2027, 1, 3)),
        ("  24.10.  ", date(2026, 10, 24)),
    ])
    def test_absolute(self, text, expected):
        assert parse_date(text, TODAY)[0] == expected

    def test_feb_29_without_year_finds_leap_year_or_fails(self):
        # 2027 ist kein Schaltjahr, 2026 auch nicht → Fehler statt falschem Datum
        with pytest.raises(ParseError):
            parse_date("29.02.", TODAY)

    @pytest.mark.parametrize("text", ["", "   ", "irgendwann", "31.02.2027", "32.1.", "letzten Samstag", "13.13."])
    def test_invalid(self, text):
        with pytest.raises(ParseError):
            parse_date(text, TODAY)


class TestParseTime:
    @pytest.mark.parametrize("text, expected", [
        ("20", time(20, 0)),
        ("20:00", time(20, 0)),
        ("20.30", time(20, 30)),
        ("2000", time(20, 0)),
        ("830", time(8, 30)),
        ("8:05", time(8, 5)),
        ("20 Uhr", time(20, 0)),
        ("20:30 uhr", time(20, 30)),
        ("20h", time(20, 0)),
        ("0", time(0, 0)),
    ])
    def test_valid(self, text, expected):
        assert parse_time(text) == expected

    @pytest.mark.parametrize("text", ["", "24", "20:60", "abends", "8pm", "20:5", "12345"])
    def test_invalid(self, text):
        with pytest.raises(ParseError):
            parse_time(text)


class TestParseStart:
    def test_combines_in_berlin_time(self):
        start = parse_start("24.10.", "20:00", NOW)
        assert start == datetime(2026, 10, 24, 20, 0, tzinfo=BERLIN_TZ)

    def test_today_later(self):
        assert parse_start("heute", "20", NOW) == datetime(2026, 10, 19, 20, 0, tzinfo=BERLIN_TZ)

    def test_today_earlier_is_past(self):
        with pytest.raises(ParseError, match="Vergangenheit"):
            parse_start("heute", "10", NOW)

    def test_weekday_today_but_time_passed_jumps_a_week(self):
        assert parse_start("Montag", "10:00", NOW) == datetime(2026, 10, 26, 10, 0, tzinfo=BERLIN_TZ)

    def test_explicit_date_today_but_time_passed_is_error(self):
        with pytest.raises(ParseError):
            parse_start("19.10.2026", "10:00", NOW)

    def test_too_far_ahead(self):
        with pytest.raises(ParseError, match="365"):
            parse_start("20.10.2027", "20:00", NOW)

    def test_dst_change_keeps_wall_clock(self):
        # Zeitumstellung am 25.10.2026: 20:00 bleibt 20:00 Ortszeit
        start = parse_start("26.10.", "20:00", NOW)
        assert start.hour == 20 and start.utcoffset().total_seconds() == 3600


def test_format_start():
    start = datetime(2026, 10, 24, 20, 0, tzinfo=BERLIN_TZ)
    assert format_start(start) == "Samstag, 24.10.2026, 20:00"
    assert format_start(start, 150) == "Samstag, 24.10.2026, 20:00–22:30"
