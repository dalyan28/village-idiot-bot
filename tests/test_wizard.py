"""Tests für den DM-Wizard ohne Discord: Navigation und Darstellung jedes Schritts.

Jeder Schritt wird gerendert und gegen die Grenzen von Discord geprüft (Zeilen, custom_id-
Länge, Select-Optionen, Embed-Größe). Netzwerk wird nicht gebraucht: Basis-Skripte haben eine
feste Einschätzung, das Skript-Bild wird lokal erzeugt.
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

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


def check_limits(screen):
    rows = {}
    for wrapper in screen.view.children:
        item = getattr(wrapper, "item", wrapper)
        rows.setdefault(item.row, 0)
        rows[item.row] += item.width
        cid = getattr(item, "custom_id", None)
        assert cid is None or len(cid) <= 100
        for opt in getattr(item, "options", []) or []:
            assert len(opt.label) <= 100 and len(opt.value) <= 100
        if hasattr(item, "options"):
            assert 1 <= len(item.options) <= 25
    assert None not in rows, rows  # jede Komponente hat eine feste Zeile
    assert all(w <= 5 for w in rows.values()), rows
    assert len({r for r in rows if r is not None}) <= 5
    assert sum(len(e) for e in screen.embeds) <= 6000
    for e in screen.embeds:
        for f in e.fields:
            assert len(f.value) <= 1024 and len(f.name) <= 256


def render(store, draft):
    return asyncio.run(wizard.build_screen(FakeBot(store=store), store, draft))


@pytest.mark.parametrize("step", [*wizard.STEPS, wizard.STEP_REMINDERS])
def test_every_step_renders_within_discord_limits(store, step):
    screen = render(store, make_draft(store, step))
    check_limits(screen)
    assert screen.embeds[0].title == "Event-Zusammenfassung"  # auf jeder Seite oben
    if step != "preview":
        assert wizard.STEP_LABELS[step] in screen.embeds[1].title


def test_script_step_with_search_results(store):
    draft = make_draft(store, "script", script=None)
    store.set_draft_ui(draft.id, {"query": "boo", "search_results": [
        {"id": str(i), "version": "1.0.0", "name": "N" * 120, "author": "A" * 120} for i in range(10)
    ]})
    screen = render(store, store.get_draft(draft.id))
    check_limits(screen)
    assert any(getattr(i, "custom_id", "") == f"wizs:{draft.id}:result" for i in screen.view.children)


def test_rating_step_without_rating_disables_next(store):
    draft = make_draft(store, "rating", rating=None, rating_source=None,
                       script=ScriptRef(kind=SCRIPT_BOTCSCRIPTS, name="X", version="1", botcscripts_id="5",
                                        characters=["imp"]))
    screen = render(store, draft)
    nxt = next(i for i in screen.view.children if i.custom_id.endswith(":next"))
    assert nxt.item.disabled
    assert any("nicht automatisch einschätzen" in f.value for f in screen.embeds[1].fields)
    assert next(f.value for f in screen.embeds[0].fields if "Einschätzung" in f.name) == "> offen"


def test_description_required_unless_academy(store):
    screen = render(store, make_draft(store, "description", description=""))
    assert next(i for i in screen.view.children if i.custom_id.endswith(":next")).item.disabled
    screen = render(store, make_draft(store, "description", description="", is_academy=True))
    assert not next(i for i in screen.view.children if i.custom_id.endswith(":next")).item.disabled


def test_image_step_attaches_preview_and_preview_step_attaches_post_files(store):
    screen = render(store, make_draft(store, "image"))
    assert [f.filename for f in screen.files] == [wizard.PREVIEW_IMAGE]
    screen = render(store, make_draft(store, "preview"))
    assert {f.filename for f in screen.files} == {"event_image.png", "thumbnail.png"}
    screen = render(store, make_draft(store, "image", image_mode=IMAGE_NONE))
    assert screen.files == []


def test_preview_disables_publish_when_incomplete(store):
    screen = render(store, make_draft(store, "preview", description=""))
    publish = next(i for i in screen.view.children if i.custom_id.endswith(":publish"))
    assert publish.item.disabled
    assert "**Es fehlt noch:** Beschreibung" in screen.embeds[0].description


class TestNavigation:
    def data(self, kind=SCRIPT_BASE):
        return EventData(script=ScriptRef(kind=kind))

    def test_linear_order(self):
        d = self.data()
        assert wizard.next_step(d, "script") == "rating"
        assert wizard.next_step(d, "rating") == "description"
        assert wizard.next_step(d, "description") == "image"
        assert wizard.next_step(d, "image") == "preview"
        assert wizard.previous_step(d, "description") == "rating"
        assert wizard.previous_step(d, "script") == "script"

    def test_free_choice_skips_rating(self):
        d = self.data(SCRIPT_FREE)
        assert wizard.next_step(d, "script") == "description"
        assert wizard.previous_step(d, "description") == "script"
        assert wizard.step_number(d, "description") == (2, 4)

    def test_jump_from_preview_returns_to_preview(self):
        d = self.data()
        assert wizard.next_step(d, "rating:p") == "preview"
        assert wizard.previous_step(d, "rating:p") == "preview"
        assert wizard.base_step("rating:p") == "rating"


def test_summary_is_numbered_with_code_blocks(store):
    screen = render(store, make_draft(store, "preview"))
    embed = screen.embeds[0]
    names = [f.name for f in embed.fields]
    assert names[0] == "1 · Titel (automatisch)" and "11 · Termin" in names and "13 · Erinnerungen" in names
    assert embed.fields[0].value == "```💚 Trouble Brewing mit Dalyan```"
    termin = next(f.value for f in embed.fields if f.name == "11 · Termin")
    assert termin == "```Donnerstag, der 22.10.2026, 12:00 Uhr – 14:30 Uhr```"
    edit = next(i for i in screen.view.children if i.custom_id.endswith(":edit"))
    assert [o.value for o in edit.item.options][:4] == ["title", "script", "rating", "description"]


def test_open_fields_and_rating_options(store):
    screen = render(store, make_draft(store, "description", description=""))
    summary = {f.name: f.value for f in screen.embeds[0].fields}
    assert summary["4 · Beschreibung"] == "```offen```"
    screen = render(store, make_draft(store, "rating"))
    rates = [i.item.label for i in screen.view.children if i.custom_id.split(":")[2] == "rate"]
    assert rates == ["Grün", "Gelb", "Rot", "Grün bis Gelb", "Gelb bis Rot", "Alle drei"]


def test_verdict_text_is_preferred(store):
    draft = make_draft(store, "rating", rating="red", rating_source="rater",
                       script=ScriptRef(kind=SCRIPT_BOTCSCRIPTS, name="X", version="1", botcscripts_id="5",
                                        characters=["imp"]))
    store.set_draft_ui(draft.id, {"rating_detail": {"verdict": "Viele Charaktere stehen auf keinem Basis-Skript.",
                                                    "tagline": "Setzt Erfahrung voraus.",
                                                    "reasons": ["Kriterium A"]}})
    screen = render(store, store.get_draft(draft.id))
    rating = next(f.value for f in screen.embeds[0].fields if "Einschätzung" in f.name)
    assert "Viele Charaktere" in rating and "Kriterium A" not in rating
    assert "> *Setzt Erfahrung voraus.*" in rating


def test_custom_title(store):
    screen = render(store, make_draft(store, "preview", title="Spukige Nacht"))
    assert screen.embeds[0].fields[0].name == "1 · Titel"
    assert screen.embeds[0].fields[0].value == "```💚 Spukige Nacht```"
