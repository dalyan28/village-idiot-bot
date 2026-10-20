"""Tests für den DM-Wizard ohne Discord: Darstellung jeder Seite (Components V2).

Jede Seite wird gerendert und gegen die Grenzen von Discord geprüft (40 Komponenten,
4000 Zeichen, custom_id-Länge). Netzwerk wird nicht gebraucht: Basis-Skripte haben eine
feste Einschätzung, das Skript-Bild wird lokal erzeugt.
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from discord_ui import wizard
from events import service
from events.permissions import AccessSettings, Actor
from events.schema import (
    BERLIN_TZ,
    IMAGE_NONE,
    SCRIPT_BASE,
    SCRIPT_BOTCSCRIPTS,
    SCRIPT_FREE,
    EventData,
    Person,
    ScriptRef,
)
from events.store import Store
from logic.script_cache import get_base_script

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=BERLIN_TZ)
GUILD = 10
st = Actor(1, is_admin=True)


class FakeBot(SimpleNamespace):
    def get_guild(self, guild_id):
        return None


@pytest.fixture
def store():
    s = Store(":memory:")
    service.set_access(s, GUILD, AccessSettings(academy_user_ids=[1]))
    yield s
    s.close()


def tb() -> ScriptRef:
    base = get_base_script("trouble_brewing")
    return ScriptRef(kind=SCRIPT_BASE, name=base["name"], base_key="trouble_brewing", characters=base["characters"])


def make_draft(store, step, **kw):
    data = EventData(start=NOW + timedelta(days=3), storyteller=Person("Dalyan", 1), script=tb(),
                     rating="green", rating_source="fixed", description="Wir spielen TB.")
    for k, v in kw.items():
        setattr(data, k, v)
    draft = service.start_draft(store, GUILD, st, "Dalyan", data, NOW)
    store.update_draft(draft.id, draft.data, step, int(NOW.timestamp()))
    return store.get_draft(draft.id)


def render(store, draft):
    async def go():
        layout, files = await wizard.render(FakeBot(store=store), draft)
        layout.to_components()  # muss sich serialisieren lassen
        return layout, files
    return asyncio.run(go())


def texts(layout) -> str:
    return " ".join(i.content for i in layout.walk_children() if isinstance(i, discord.ui.TextDisplay))


@pytest.mark.parametrize("step", ["script", "image", "preview", "script:p", "image:p"])
def test_every_page_renders_within_discord_limits(store, step):
    layout, _ = render(store, make_draft(store, step))
    assert layout.content_length() <= 4000
    assert sum(1 for _ in layout.walk_children()) <= 40
    ids = [getattr(i, "custom_id", None) for i in layout.walk_children()]
    assert all(len(c) <= 100 for c in ids if c)


def test_old_step_falls_back_to_summary(store):
    """Entwürfe aus älteren Versionen (z. B. Schritt „description“) landen in der Zusammenfassung."""
    layout, _ = render(store, make_draft(store, "description"))
    assert "BESCHREIBUNG" in texts(layout)


def test_image_page_attaches_preview(store):
    _, files = render(store, make_draft(store, "image"))
    assert [f.filename for f in files] == ["vorschau.png"]
    _, files = render(store, make_draft(store, "image", image_mode=IMAGE_NONE))
    assert files == []


def test_rating_options(store):
    modal = asyncio.run(_rating_modal(make_draft(store, "preview").data))
    assert [o.label for o in modal.rating.options] == ["💚 Grün", "🟡 Gelb", "🟥 Rot", "💚/🟡 Grün bis Gelb",
                                                       "🟡/🟥 Gelb bis Rot", "💚/🟡/🟥 Alle drei"]
    assert [o.value for o in modal.rating.options if o.default] == ["green"]


async def _rating_modal(data):
    return wizard.RatingModal(1, data)


def test_special_reasons_shown_in_summary(store):
    layout, _ = render(store, make_draft(store, "preview", is_special=True, special_reasons=["Loric: Bootlegger"]))
    assert "⭐ Loric: Bootlegger" in texts(layout) and "## ⭐ 💚 Trouble Brewing" in texts(layout)


def test_verdict_text_is_preferred(store):
    draft = make_draft(store, "preview", rating="red", rating_source="rater",
                       script=ScriptRef(kind=SCRIPT_BOTCSCRIPTS, name="X", version="1", botcscripts_id="5",
                                        characters=["imp"]))
    store.set_draft_ui(draft.id, {"rating_detail": {"verdict": "Viele Charaktere stehen auf keinem Basis-Skript.",
                                                    "tagline": "Setzt Erfahrung voraus.",
                                                    "reasons": ["Kriterium A"]}})
    layout, _ = render(store, store.get_draft(draft.id))
    assert "Viele Charaktere" in texts(layout) and "Kriterium A" not in texts(layout)
    assert "*Setzt Erfahrung voraus.*" in texts(layout)


def test_custom_title(store):
    layout, _ = render(store, make_draft(store, "preview", title="Spukige Nacht"))
    assert "## 💚 Spukige Nacht" in texts(layout) and "automatisch" not in texts(layout)


def test_base_step():
    assert wizard.base_step("image:p") == "image" and wizard.returns_to_preview("image:p")
