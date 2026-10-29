"""Tests für die Zusammenfassung und die Skript-Seite (Components V2) ohne Discord."""

import asyncio

import discord

import pytest

from discord_ui import wizard
from tests.test_wizard import FakeBot, make_draft, store  # noqa: F401  (Fixture)


def layout_for(store, draft):
    async def go():
        layout, _ = await wizard.render(FakeBot(store=store), draft)
        layout.to_components()  # muss sich serialisieren lassen
        return layout
    return asyncio.run(go())


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
    assert "**Bevor du veröffentlichen kannst, fehlt noch:** Schwierigkeit, Beschreibung" in texts
    assert "🔴" not in texts  # dezenter Balken statt rotem Kreis (Dalyan, 27.10.2026)
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
    assert [len(r.children) for r in rows] == [3, 1, 2]  # Blättern · Versionen · Zusammenfassung/Abbrechen


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
    assert "Teensyville" in texts and "⭐ Abweichung" in texts and "Seite 1 von 2" in texts
    buttons = {b.custom_id: b for b in (getattr(i, "item", i) for i in layout.walk_children()) if isinstance(b, discord.ui.Button)}
    assert buttons[f"wiz:{draft.id}:page:0"].disabled  # erste Seite: kein Zurück
    assert not buttons[f"wiz:{draft.id}:page:1"].disabled
    assert f"wiz:{draft.id}:script_dialog" in buttons  # zurück zum Skript-Dialog
    assert sum(1 for _ in layout.walk_children()) <= 40

    # Seite 2: Treffer 5–7, Indizes bleiben global
    store.set_draft_ui(draft.id, {**store.get_draft(draft.id).ui, "page": 1})
    layout = asyncio.run(go())
    sections = [i for i in layout.walk_children() if isinstance(i, discord.ui.Section)]
    assert [s.accessory.custom_id for s in sections] == [f"wiz:{draft.id}:pick_result:{i}" for i in range(5, 8)]
    buttons = {b.custom_id: b for b in (getattr(i, "item", i) for i in layout.walk_children()) if isinstance(b, discord.ui.Button)}
    assert buttons[f"wiz:{draft.id}:page:2"].disabled  # letzte Seite: kein Weiter


def _custom_ids(layout):
    return [i.custom_id for i in layout.walk_children() if getattr(i, "custom_id", None)]


@pytest.mark.parametrize("draft_kw", [{}, {"description": "", "rating": None, "rating_source": None}])
def test_no_duplicate_custom_ids_in_summary(store, draft_kw):
    """Regression: roter „Beschreibung schreiben“-Button und „Bearbeiten“ hatten dieselbe custom_id → 400."""
    layout, _ = summary_for(store, make_draft(store, "preview", **draft_kw))
    ids = _custom_ids(layout)
    assert len(ids) == len(set(ids)), ids


@pytest.mark.parametrize("step", ["script", "image", "preview"])
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


def test_sections_with_missing_items_have_red_buttons(store):
    """Fehlt eine Pflichtangabe, ist der „Ändern“-Button am Abschnitt rot (Dalyan, 20.10.2026)."""
    layout, _ = summary_for(store, make_draft(store, "preview", description="", rating=None, rating_source=None))
    styles = {s.accessory.custom_id.split(":")[3]: s.accessory.item.style
              for s in layout.walk_children() if isinstance(s, discord.ui.Section) and hasattr(s.accessory, "item")}
    assert styles["description"] == discord.ButtonStyle.danger and styles["rating"] == discord.ButtonStyle.danger
    assert styles["people"] == discord.ButtonStyle.secondary and styles["title"] == discord.ButtonStyle.secondary


def test_too_long_description_blocks_publish(store):
    """Bei Academy höchstens 3000 Zeichen zusammen mit dem Academy-Text: sonst Hinweis und „Beschreibung kürzen“
    statt Veröffentlichen (Dalyan, 29.10.2026)."""
    from events import service
    service.set_academy_template(store, make_draft(store, "preview").guild_id, "y" * 2000)
    draft = make_draft(store, "preview", is_academy=True, description="x" * 1500)
    layout = layout_for(store, draft)
    texts = " ".join(getattr(i, "content", "") for i in layout.walk_children())
    labels = [getattr(i, "item", i).label for i in layout.walk_children()
              if isinstance(getattr(i, "item", i), discord.ui.Button)]
    assert service.description_limit(store, draft.guild_id, draft.data) == 1000  # 3000 − 2000 Academy-Text
    assert "höchstens 3000 Zeichen möglich, für deine Beschreibung bleiben also 1000" in texts
    assert "Bitte kürze sie um 500 Zeichen" in texts
    assert "Beschreibung kürzen" in labels and "Veröffentlichen" not in labels


def test_description_limit_without_and_with_academy(store):
    from events import service
    from events.templates import ACADEMY_TEMPLATE_DEFAULT
    plain = make_draft(store, "preview", description="x")
    assert service.description_limit(store, plain.guild_id, plain.data) == 2000
    academy = make_draft(store, "preview", is_academy=True, description="x")
    limit = service.description_limit(store, academy.guild_id, academy.data)
    assert 3000 - len(ACADEMY_TEMPLATE_DEFAULT) - 50 <= limit <= 2000


@pytest.mark.parametrize("academy", [False, True])
def test_missing_description_mark_matches_red_button(store, academy):
    """„fehlt“ steht nur da, wo der Button auch rot ist; bei Academy ist die Beschreibung freiwillig
    (Dalyan, 29.10.2026)."""
    layout = layout_for(store, make_draft(store, "preview", is_academy=academy, description=""))
    section = next(i for i in layout.walk_children() if isinstance(i, discord.ui.Section)
                   and "**Beschreibung**" in i.children[0].content)
    button = getattr(section.accessory, "item", section.accessory)
    shows_missing = "fehlt" in section.children[0].content
    assert shows_missing == (button.style == discord.ButtonStyle.danger) == (not academy)
    if academy:
        assert "Keine eigene Beschreibung (freiwillig)" in section.children[0].content
