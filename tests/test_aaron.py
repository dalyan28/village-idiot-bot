"""
Unit-Tests für /aaron (commands/aaron.py).

Ausführen:
    pytest tests/test_aaron.py -v
"""
from datetime import date, datetime

from commands.aaron import BERLIN_TZ, HEADER, build_messages, split_symbols, todays_lines, to_code_blocks


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
        f"`15:00` [Srunde · Boozling mit Dalyan](<{events[1]['url']}>)",
        f"`20:00` [Trouble Brewing mit Conga](<{events[2]['url']}>)",
    ]


def test_time_in_berlin_summer_and_winter():
    # sommerzeit (MESZ) und winterzeit (MEZ)
    summer = int(datetime(2026, 7, 1, 20, 0, tzinfo=BERLIN_TZ).timestamp())
    winter = int(datetime(2026, 12, 1, 9, 5, tzinfo=BERLIN_TZ).timestamp())
    assert todays_lines([{"title": "A", "start_ts": summer, "url": "u"}], date(2026, 7, 1)) == ["`20:00` [A](<u>)"]
    assert todays_lines([{"title": "B", "start_ts": winter, "url": "u"}], date(2026, 12, 1)) == ["`09:05` [B](<u>)"]


def test_emojis_before_link():
    events = [_event("🟥 Srunde Broken Circles mit Doctor", 9, 14, 30), _event("💚/🟡 🎓 🕊️ Boozling mit Dalyan", 9, 20)]
    assert todays_lines(events, date(2026, 11, 9)) == [
        f"`14:30` 🟥 [Srunde Broken Circles mit Doctor](<{events[0]['url']}>)",
        f"`20:00` 💚/🟡 🎓 🕊️ [Boozling mit Dalyan](<{events[1]['url']}>)",
    ]


def test_split_symbols():
    assert split_symbols("Trouble Brewing mit Conga") == ("", "Trouble Brewing mit Conga")
    assert split_symbols("⭐ Srunde · Boozling") == ("⭐", "Srunde · Boozling")
    assert split_symbols("🟥 🎦") == ("", "🟥 🎦")


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
    lines = [f"`20:00` [Event {i} {'x' * 60}](<https://discord.com/channels/1/2/{i}>)" for i in range(40)]
    blocks = to_code_blocks(lines)
    assert len(blocks) > 1
    assert all(len(b) <= 2000 for b in blocks)
    joined = [line for b in blocks for line in b.removeprefix("```\n").removesuffix("\n```").split("\n")]
    assert joined == lines


def test_header_only_above_first_block():
    lines = [f"`20:00` [Event {i} {'x' * 60}](<https://discord.com/channels/1/2/{i}>)" for i in range(40)]
    messages = build_messages(lines)
    assert messages[0].startswith(HEADER + "\n```\n")
    assert all(not m.startswith(HEADER) for m in messages[1:])
    assert all(len(m) <= 2000 for m in messages)
    assert build_messages([]) == []
