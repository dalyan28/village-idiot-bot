"""Tests für die /botc2-Darstellung (Components V2) ohne Discord: jede Seite, Grenzen, Bearbeiten-Buttons."""

import asyncio

import discord

import pytest

from discord_ui import wizard
from discord_ui.layout_v2 import to_layout
from tests.test_wizard import FakeBot, make_draft, store  # noqa: F401  (Fixture)


def layout_for(store, draft):
    async def go():
        screen = await wizard.build_screen(FakeBot(store=store), store, draft)
        layout = to_layout(screen.embeds, screen.view, draft.id, wizard.base_step(draft.step) == "preview")
        layout.to_components()  # muss sich serialisieren lassen
        return layout
    return asyncio.run(go())


def edit_buttons(layout):
    return [i for i in layout.walk_children() if getattr(i, "custom_id", "").split(":")[2:3] == ["edit_field"]]


@pytest.mark.parametrize("step", wizard.STEPS)
def test_every_step_fits_components_v2(store, step):
    layout = layout_for(store, make_draft(store, step))
    assert layout.content_length() <= 4000
    assert sum(1 for _ in layout.walk_children()) <= 40


def summary_for(store, draft):
    from discord_ui.layout_v2 import summary_layout

    async def go():
        layout, files = await summary_layout(FakeBot(store=store), store, draft)
        layout.to_components()
        return layout, files
    return asyncio.run(go())


def test_summary_has_five_grouped_sections(store):
    layout, files = summary_for(store, make_draft(store, "preview"))
    sections = [i for i in layout.walk_children() if isinstance(i, discord.ui.Section)]
    targets = [s.accessory.custom_id.split(":")[3] for s in sections if isinstance(s.accessory, discord.ui.Button)
               or hasattr(s.accessory, "item")]
    assert targets == ["title", "description", "script", "rating", "people", "selection", "frame"]
    assert isinstance(sections[-1].accessory, discord.ui.Thumbnail)  # Bild als kleine Vorschau
    ids = [getattr(i, "custom_id", "") for i in layout.walk_children()]
    assert any(c.endswith(":publish") for c in ids)  # alles da → Veröffentlichen
    assert [f.filename for f in files] == ["event_image.png"]
    assert layout.content_length() <= 4000 and sum(1 for _ in layout.walk_children()) <= 40


def test_missing_items_replace_publish_with_red_buttons(store):
    layout, _ = summary_for(store, make_draft(store, "preview", description="", rating=None, rating_source=None))
    texts = " ".join(i.content for i in layout.walk_children() if isinstance(i, discord.ui.TextDisplay))
    assert "🔴 **Bevor du veröffentlichen kannst, fehlt noch:** Schwierigkeit, Beschreibung" in texts
    row = [c for c in layout.children if isinstance(c, discord.ui.ActionRow)][0]
    buttons = [(b.item.label, b.item.style) for b in row.children]
    assert [b.custom_id.split(":")[2] for b in row.children][:2] == ["fix_field", "fix_field"]
    assert buttons == [("Schwierigkeit wählen", discord.ButtonStyle.danger),
                       ("Beschreibung schreiben", discord.ButtonStyle.danger),
                       ("Bild ändern", discord.ButtonStyle.secondary),
                       ("Abbrechen", discord.ButtonStyle.secondary)]
    ids = [getattr(i, "custom_id", "") for i in layout.walk_children()]
    assert not any(c.endswith(":publish") for c in ids)


def test_script_step_with_search_results_and_versions(store):
    """Regression: Selects landeten in Zeile 0 bei den Skript-Buttons → ActionRow lief über."""
    from events.schema import ScriptRef
    draft = make_draft(store, "script", script=ScriptRef(kind="botcscripts", name="Boozling", version="9.0.0",
                                                         botcscripts_id="173", characters=["imp"]))
    store.set_draft_ui(draft.id, {"query": "boo", "search_results": [
        {"id": str(i), "version": "1", "name": f"Skript {i}", "author": "A"} for i in range(10)],
        "versions": [{"id": "173", "version": "9.0.0"}]})
    layout = layout_for(store, store.get_draft(draft.id))
    rows = [c for c in layout.children if isinstance(c, discord.ui.ActionRow)]
    assert [len(r.children) for r in rows] == [4, 4, 1, 1, 1]


def test_long_academy_description_is_shortened(store):
    layout = layout_for(store, make_draft(store, "preview", is_academy=True, description="x" * 1000,
                                          title="T" * 200))
    assert layout.content_length() <= 4000


def test_search_results_as_sections_with_choose_button(store):
    from discord_ui.layout_v2 import script_layout
    draft = make_draft(store, "script")
    store.set_draft_ui(draft.id, {"query": "teensy", "search_results": [
        {"id": str(i), "version": "1.0", "name": f"Skript {i}", "author": "A",
         "type": "Teensyville" if i == 0 else "Full", "special": i == 1} for i in range(8)]})

    async def go():
        layout, _ = await script_layout(FakeBot(store=store), store, store.get_draft(draft.id))
        layout.to_components()
        return layout
    layout = asyncio.run(go())
    sections = [i for i in layout.walk_children() if isinstance(i, discord.ui.Section)]
    assert [s.accessory.custom_id for s in sections] == [f"wiz:{draft.id}:pick_result:{i}" for i in range(5)]
    texts = " ".join(i.content for i in layout.walk_children() if isinstance(i, discord.ui.TextDisplay))
    assert "Teensyville" in texts and "⭐ Abweichung" in texts and "3 weitere Treffer" in texts
    assert sum(1 for _ in layout.walk_children()) <= 40


def test_event_card_v2_within_limits():
    from datetime import datetime, timezone
    from discord_ui.layout_v2 import event_layout
    from events.schema import Person, ScriptRef, EventData
    from events.service import RsvpLists
    data = EventData(start=datetime(2026, 10, 24, 18, tzinfo=timezone.utc), storyteller=Person("Dalyan"),
                     script=ScriptRef(kind="botcscripts", name="Boozling", author="Lau", version="9.0.0",
                                      botcscripts_id="173", characters=["noble", "imp", "djinn"]),
                     description="x" * 1000, rating="yellow", is_academy=True, max_players=2)
    people = [Person(f"Spieler {i}", i) for i in range(60)]
    rsvps = RsvpLists(players=people[:2], waitlist=people[2:30], tentative=people[30:45], declined=people[45:])

    async def go():
        buttons = [discord.ui.Button(label=str(i), custom_id=f"b{i}") for i in range(5)]
        layout = event_layout(data, "Dalyan", "https://cdn/a.png", rsvps, buttons, True, True, 1792459044)
        layout.to_components()
        return layout
    layout = asyncio.run(go())
    texts = " ".join(i.content for i in layout.walk_children() if isinstance(i, discord.ui.TextDisplay))
    assert "Zusagen (30/2)" in texts and "Warteliste" in texts and "Auffüller" in texts and "<@" not in texts
    assert layout.content_length() <= 4000 and sum(1 for _ in layout.walk_children()) <= 40


def _custom_ids(layout):
    return [i.custom_id for i in layout.walk_children() if getattr(i, "custom_id", None)]


@pytest.mark.parametrize("draft_kw", [{}, {"description": "", "rating": None, "rating_source": None}])
def test_no_duplicate_custom_ids_in_summary(store, draft_kw):
    """Regression: roter „Beschreibung schreiben“-Button und „Bearbeiten“ hatten dieselbe custom_id → 400."""
    layout, _ = summary_for(store, make_draft(store, "preview", **draft_kw))
    ids = _custom_ids(layout)
    assert len(ids) == len(set(ids)), ids


@pytest.mark.parametrize("step", wizard.STEPS)
def test_no_duplicate_custom_ids_on_any_page(store, step):
    ids = _custom_ids(layout_for(store, make_draft(store, step)))
    assert len(ids) == len(set(ids)), ids


def test_worst_case_missing_items_fit(store):
    """Alle Pflichtangaben fehlen: Grenze von 40 Komponenten einhalten, keine doppelten IDs."""
    draft = make_draft(store, "preview", script=None, description="", rating=None, rating_source=None)
    layout, _ = summary_for(store, store.get_draft(draft.id))
    assert sum(1 for _ in layout.walk_children()) <= 40
    ids = _custom_ids(layout)
    assert len(ids) == len(set(ids))
