"""Tests für das Event-Embed: Namen als Text, NPCs, Highlights, lange Listen."""

from datetime import datetime

from events.schema import BERLIN_TZ, SCRIPT_BOTCSCRIPTS, SCRIPT_FREE, EventData, Person, ScriptRef
from events.service import RsvpLists
from logic.event_builder import build_event_embed, highlight_characters, npc_characters

START = datetime(2026, 10, 24, 20, 0, tzinfo=BERLIN_TZ)


def data(**kw) -> EventData:
    base = dict(
        start=START,
        storyteller=Person("Dalyan", 1),
        script=ScriptRef(kind=SCRIPT_BOTCSCRIPTS, name="Boozling", author="Lau", version="9.0.0",
                         botcscripts_id="173", characters=["noble", "pixie", "imp", "fanggu", "djinn", "bootlegger"]),
        description="Wir spielen Boozling.",
        rating="red",
    )
    base.update(kw)
    return EventData(**base)


def lists(players=(), waitlist=(), tentative=(), declined=()):
    return RsvpLists(players=list(players), waitlist=list(waitlist), tentative=list(tentative), declined=list(declined))


def fields(embed) -> dict:
    return {f.name: f.value for f in embed.fields}


def test_names_are_text_not_mentions():
    embed = build_event_embed(
        data(co_storyteller=Person("Ro_sa", 9)), "Dalyan",
        lists(players=[Person("Anna", 50)], tentative=[Person("*Bob*", 51)]),
    )
    text = " ".join(f.value for f in embed.fields)
    assert "<@" not in text
    f = fields(embed)
    assert f["Storytelling"] == "Dalyan"
    assert f["Co-Storytelling"] == "Ro\\_sa"           # Markdown escaped
    assert any("\\*Bob\\*" in v for v in f.values())


def test_name_resolver_overrides_stored_name():
    embed = build_event_embed(data(), "Dalyan", lists(players=[Person("Alt", 50)]),
                              name_for=lambda p: "Neu" if p.user_id == 50 else None)
    assert "> Neu" in next(v for k, v in fields(embed).items() if "Akzeptiert" in k)


def test_title_has_prefix_and_link():
    embed = build_event_embed(data(), "Dalyan", lists())
    assert embed.title == "🟥 Boozling mit Dalyan"
    assert "https://www.botcscripts.com/script/173/9.0.0" in fields(embed)["Skript"]


def test_npcs_and_highlights():
    f = fields(build_event_embed(data(), "Dalyan", lists()))
    assert "Djinn" in f["NPCs"] and "Bootlegger" in f["NPCs"]
    assert "Highlights" in f and "Relevante Charaktere" not in f
    assert "(" not in f["Highlights"]  # keine Score-Zahlen


def test_free_choice_has_no_character_fields():
    f = fields(build_event_embed(data(script=ScriptRef(kind=SCRIPT_FREE), rating=None), "Dalyan", lists()))
    assert "NPCs" not in f and "Highlights" not in f
    assert f["Skript"] == "Freie Skriptwahl"


def test_waitlist_and_academy_label():
    embed = build_event_embed(data(is_academy=True, max_players=1), "Dalyan",
                              lists(players=[Person("A", 1)], waitlist=[Person("B", 2)], tentative=[Person("C", 3)]))
    f = fields(embed)
    accepted = next(v for k, v in f.items() if "Akzeptiert (2/1)" in k)
    assert "**Warteliste**" in accepted and "B" in accepted
    assert any("Auffüller (1)" in k for k in f)


def test_long_lists_fit_into_field():
    many = [Person(f"Spieler mit langem Namen {i}", i) for i in range(200)]
    embed = build_event_embed(data(max_players=200), "Dalyan", lists(players=many, declined=many))
    for f in embed.fields:
        assert len(f.value) <= 1024
    assert "weitere" in next(v for k, v in fields(embed).items() if "Abgelehnt" in k)


def test_helpers_ignore_unknown_characters():
    assert npc_characters(["unknown"]) is None
    assert highlight_characters(["unknown"]) is None


def test_demons_field_lists_demons_including_homebrew():
    """Eigenes Feld „Dämonen“ (Dalyan, 20.10.2026); Homebrew-Dämonen kommen aus dem Skript-JSON."""
    content = [{"id": "_meta", "name": "Boozling"}, "imp", {"id": "boo", "name": "Boo", "team": "demon"},
               {"id": "x", "name": "Kein Dämon", "team": "townsfolk"}]
    d = data()
    d.script.content = content
    f = fields(build_event_embed(d, "Dalyan", lists()))
    assert f["Dämonen"] == "Imp, Fang Gu, Boo"


def test_character_emojis_prefix_names(monkeypatch):
    """Mit hochgeladenen App-Emojis steht das Icon vor jedem Charakternamen."""
    from types import SimpleNamespace
    from logic import character_emojis

    class E(SimpleNamespace):
        def __str__(self):
            return f"<:{self.name}:1>"
    character_emojis.set_emojis([E(name="imp"), E(name="fanggu"), E(name="unbekannt")])
    try:
        assert character_emojis.emoji_for("unbekannt") == ""  # nur bekannte Charaktere
        f = fields(build_event_embed(data(), "Dalyan", lists()))
        assert f["Dämonen"] == "<:imp:1> Imp, <:fanggu:1> Fang Gu"
        assert "<:imp:1> **Imp**" in f["Highlights"] or "<:imp:1> Imp" in f["Highlights"]
    finally:
        character_emojis.set_emojis([])


def test_emoji_name_is_valid():
    from logic.character_emojis import emoji_name
    assert emoji_name("fortune_teller") == "fortune_teller"
    assert emoji_name("x") is None
