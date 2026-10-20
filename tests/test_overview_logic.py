"""
Unit-Tests für die Event-Erkennung der Übersicht (commands/overview.py, logic/parser.py).
Kein Discord-Bot nötig – reine Python-Logik wird getestet.

Ausführen:
    pip install pytest
    pytest tests/
"""
from unittest.mock import MagicMock


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


def test_parse_events_reads_own_posts_from_lookup():
    """V2-Posts des eigenen Bots haben keine Embeds: die Übersicht nimmt die Daten aus der Datenbank."""
    from types import SimpleNamespace
    from logic.parser import parse_events
    own = SimpleNamespace(id=1, author=SimpleNamespace(bot=True), embeds=[], jump_url="u1")
    apollo = MagicMock(); apollo.id = 2; apollo.author.bot = True; apollo.jump_url = "u2"
    field_t = SimpleNamespace(name="Time", value="<t:1800000000:F>")
    field_a = SimpleNamespace(name="Accepted (3/8)", value="-")
    apollo.embeds = [SimpleNamespace(title="Apollo-Runde", fields=[field_t, field_a])]
    lookup = lambda m: ({"title": "Eigene", "start_ts": 1700000000, "accepted": 1, "max_players": "6",
                         "url": m.jump_url} if m.id == 1 else None)
    events = parse_events([own, apollo], lookup)
    assert [(e["title"], e["accepted"], e["max_players"]) for e in events] == [("Eigene", 1, "6"),
                                                                           ("Apollo-Runde", 3, "8")]
    assert [e["title"] for e in parse_events([own, apollo])] == ["Apollo-Runde"]  # ohne lookup wie bisher
