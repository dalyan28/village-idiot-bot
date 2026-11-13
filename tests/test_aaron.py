"""
Unit-Tests für /aaron (commands/aaron.py).

Ausführen:
    pytest tests/test_aaron.py -v
"""
from datetime import date, datetime

from commands.aaron import BERLIN_TZ, HEADER, build_messages, link_title, todays_lines, to_code_blocks


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


def test_link_title_keeps_emojis_out_of_links():
    u = "<url>"
    assert link_title("Trouble Brewing mit Conga", u) == "[Trouble Brewing mit Conga](<url>)"
    assert link_title("⭐ Srunde · Boozling", u) == "⭐ [Srunde · Boozling](<url>)"
    assert link_title("Srunde 🟥 Broken Circles", u) == "[Srunde](<url>) 🟥 [Broken Circles](<url>)"
    assert link_title("Boozling 🎉", u) == "[Boozling](<url>) 🎉"
    assert link_title("👨‍👩‍👧 Familienrunde", u) == "👨‍👩‍👧 [Familienrunde](<url>)"


def test_link_title_without_link_between_emojis():
    assert link_title("💚/🟡 🎓 🕊️ Boozling mit Dalyan", "u") == "💚/🟡 🎓 🕊️ [Boozling mit Dalyan](u)"
    assert link_title("Srunde 🟥 - 🟡 Broken", "u") == "[Srunde](u) 🟥 - 🟡 [Broken](u)"
    assert link_title("Runde 🟥 2 🟡 Finale", "u") == "[Runde](u) 🟥 2 🟡 [Finale](u)"
    # nur emojis, dann der ganze titel als link
    assert link_title("🟥 🎦", "u") == "[🟥 🎦](u)"


def test_link_title_emoji_codes_and_glued_emojis():
    assert link_title("💚 :yellow_circle:Visitors - Besuch", "u") == "💚 :yellow_circle: [Visitors - Besuch](u)"
    assert link_title("<:boozle:1234567> <a:wink:42>Boozling", "u") == "<:boozle:1234567> <a:wink:42> [Boozling](u)"
    assert link_title("🟡Visitors mit Dan", "u") == "🟡 [Visitors mit Dan](u)"
    assert link_title("Srunde: Boozling um 20:30:00", "u") == "[Srunde: Boozling um 20:30:00](u)"
    assert link_title("„Zitat“ Runde™", "u") == "[„Zitat“ Runde](u) ™"


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
