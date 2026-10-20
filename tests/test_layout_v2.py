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
    targets = [s.accessory.custom_id.split(":")[3] for s in sections]
    assert targets == ["descriptive", "script", "selection", "frame", "image"]
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
    assert buttons == [("Schwierigkeit wählen", discord.ButtonStyle.danger),
                       ("Beschreibung schreiben", discord.ButtonStyle.danger),
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
