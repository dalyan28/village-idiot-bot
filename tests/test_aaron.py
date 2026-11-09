"""
Unit-Tests für /aaron (commands/aaron.py).

Ausführen:
    pytest tests/test_aaron.py -v
"""
from datetime import date, datetime

from commands.aaron import BERLIN_TZ, todays_lines, to_code_blocks


def _event(title, day, hour, minute=0):
    ts = int(datetime(2026, 11, day, hour, minute, tzinfo=BERLIN_TZ).timestamp())
    return {"title": title, "start_ts": ts, "url": f"https://discord.com/channels/1/2/{ts}"}


def test_only_todays_events_in_order():
    events = [
        _event("Gestern", 8, 20),
        _event("Srunde · Boozling mit Dalyan", 9, 15),
        _event("Trouble Brewing mit Conga", 9, 20),
        _event("Morgen", 10, 20),
    ]
    lines = todays_lines(events, date(2026, 11, 9))
    assert lines == [
        f"<t:{events[1]['start_ts']}:t> · [Srunde · Boozling mit Dalyan]({events[1]['url']})",
        f"<t:{events[2]['start_ts']}:t> · [Trouble Brewing mit Conga]({events[2]['url']})",
    ]


def test_berlin_date_not_utc():
    # 00:30 Berlin ist in UTC noch der Vortag
    events = [_event("Trunde", 10, 0, 30)]
    assert todays_lines(events, date(2026, 11, 9)) == []
    assert len(todays_lines(events, date(2026, 11, 10))) == 1


def test_no_events():
    assert todays_lines([], date(2026, 11, 9)) == []
    assert to_code_blocks([]) == []


def test_code_block():
    assert to_code_blocks(["a", "b"]) == ["```\na\nb\n```"]


def test_splits_at_discord_limit_without_breaking_lines():
    lines = [f"<t:1762714800:t> · [Event {i} {'x' * 60}](https://discord.com/channels/1/2/{i})" for i in range(40)]
    blocks = to_code_blocks(lines)
    assert len(blocks) > 1
    assert all(len(b) <= 2000 for b in blocks)
    joined = [line for b in blocks for line in b.removeprefix("```\n").removesuffix("\n```").split("\n")]
    assert joined == lines
