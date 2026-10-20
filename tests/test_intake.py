"""Tests für die Auswertung der /botc-Modal-Eingaben."""

from datetime import datetime

import pytest

from events.intake import ModalInput, parse_modal_input, parse_players
from events.parse import ParseError
from events.schema import BERLIN_TZ, CAMERA_OPTIONAL, CAMERA_REQUIRED

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=BERLIN_TZ)


def test_full_input():
    d = parse_modal_input(ModalInput("Sa", "20 Uhr", "15", "Profi", ["casual", "recorded", "camera"]), NOW)
    assert d.start == datetime(2026, 10, 24, 20, 0, tzinfo=BERLIN_TZ)
    assert d.max_players == 15
    assert d.level == "Profi"
    assert d.is_casual and d.is_recorded and not d.is_academy
    assert d.camera == CAMERA_REQUIRED


def test_defaults():
    d = parse_modal_input(ModalInput("morgen", "19:30"), NOW)
    assert d.max_players == 12 and d.level == "Alle" and d.camera == CAMERA_OPTIONAL
    assert not (d.is_casual or d.is_academy or d.is_recorded)


def test_academy_and_casual_together():
    d = parse_modal_input(ModalInput("morgen", "20", options=["casual", "academy"]), NOW)
    assert d.is_academy and d.is_casual


@pytest.mark.parametrize("text, expected", [("", 12), (" 7 ", 7), ("1", 1), ("200", 200)])
def test_players(text, expected):
    assert parse_players(text) == expected


@pytest.mark.parametrize("text", ["0", "201", "zwölf", "-3", "1.5"])
def test_players_invalid(text):
    with pytest.raises(ParseError):
        parse_players(text)


def test_unknown_option():
    with pytest.raises(ParseError):
        parse_modal_input(ModalInput("morgen", "20", options=["vip"]), NOW)


def test_bad_date_bubbles_up():
    with pytest.raises(ParseError, match="Datum"):
        parse_modal_input(ModalInput("irgendwann", "20"), NOW)
