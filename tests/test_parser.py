"""Tests für die Wochenplan-Zeilen in logic/parser.py"""
from datetime import datetime

from logic.parser import BERLIN_TZ, build_footer, build_overviews


def _event(title, month, day, hour, minute=0, accepted=3):
    ts = int(datetime(2026, month, day, hour, minute, tzinfo=BERLIN_TZ).timestamp())
    return {"title": title, "start_ts": ts, "accepted": accepted, "max_players": "12",
            "url": f"https://discord.com/channels/1/2/{ts}"}


def test_time_as_code_in_berlin_time():
    e = _event("Trouble Brewing", 11, 13, 20)
    value = build_overviews([e])[0].fields[0].value
    assert value == f"> `20:00` [Trouble Brewing]({e['url']}) **(3/12)** <t:{e['start_ts']}:R>"


def test_berlin_time_in_summer():
    e = _event("Sommer", 7, 1, 19, 45)
    assert build_overviews([e])[0].fields[0].value.startswith("> `19:45` ")


def test_days_grouped_by_berlin_date():
    # 00:30 Berlin ist in UTC noch der Vortag
    embed = build_overviews([_event("Spät", 11, 10, 0, 30)])[0]
    assert embed.fields[0].name == "Dienstag · November 10"
    assert embed.fields[0].value.startswith("> `00:30` ")


def test_footer_with_winter_and_summer_time():
    assert build_footer([_event("A", 11, 13, 20)]) == "Alle Zeiten und Daten in deutscher Zeit (MEZ)."
    assert build_footer([_event("A", 7, 1, 20)]) == "Alle Zeiten und Daten in deutscher Zeit (MESZ)."


def test_footer_around_time_change():
    # zeitumstellung am 25.10.2026
    events = [_event("Vorher", 10, 24, 20), _event("Nachher", 10, 26, 20)]
    assert build_footer(events) == "Alle Zeiten und Daten in deutscher Zeit (MEZ/MESZ)."


def test_footer_without_events():
    assert build_overviews([])[0].footer.text.startswith("Alle Zeiten und Daten in deutscher Zeit (ME")


def test_footer_on_every_page():
    events = [_event(f"Event {i} {'x' * 30}", 11, 13 + i % 7, 20) for i in range(80)]
    embeds = build_overviews(events)
    assert len(embeds) > 1
    assert all(e.footer.text == build_footer(events) for e in embeds)
