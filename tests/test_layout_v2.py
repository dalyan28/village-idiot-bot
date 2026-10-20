"""Tests für die /botc2-Darstellung (Components V2) ohne Discord: jede Seite, Grenzen, Bearbeiten-Buttons."""

import asyncio

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


def test_summary_has_edit_button_per_section(store):
    layout = layout_for(store, make_draft(store, "preview"))
    targets = [b.custom_id.split(":")[3] for b in edit_buttons(layout)]
    assert targets == ["title", "script", "rating", "description", "people", "basics", "labels", "image"]
    # Das „Feld ändern“-Select gibt es in V2 nicht, Veröffentlichen schon
    ids = [getattr(i, "custom_id", "") for i in layout.walk_children()]
    assert not any(c.endswith(":edit") for c in ids)
    assert any(c.endswith(":publish") for c in ids)


def test_long_academy_description_is_shortened(store):
    layout = layout_for(store, make_draft(store, "preview", is_academy=True, description="x" * 1000,
                                          title="T" * 200))
    assert layout.content_length() <= 4000
