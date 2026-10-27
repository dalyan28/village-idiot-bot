"""Skript-Blatt: A4 ohne lizenziertes Asset-Paket, Travellers ausgeblendet, Djinn bei Jinxes, zu große Skripte
ohne Bild, Theme nach Schwierigkeit."""

import asyncio

import pytest

from events.schema import RATING_ANY, RATING_GREEN, RATING_GREEN_YELLOW, RATING_RED, RATING_YELLOW_RED
from logic.script_cache import load_characters
from logic.script_sheet import assets, generate_script_sheet, theme_for_rating
from logic.script_sheet.model import DJINN_ID, GRID_TEAMS, build_script
from logic.script_sheet.sheet import render_sheet

TROUBLE_BREWING = ["washerwoman", "librarian", "investigator", "chef", "empath", "fortuneteller", "undertaker",
                   "monk", "ravenkeeper", "virgin", "slayer", "soldier", "mayor", "butler", "drunk", "recluse",
                   "saint", "poisoner", "spy", "scarletwoman", "baron", "imp"]


@pytest.fixture
def no_pack(tmp_path):
    """Ohne Asset-Paket rendern (so wie im Repo bzw. vor dem Einspielen aufs Volume)."""
    original = assets.PACK_DIR
    assets.set_pack_dir(str(tmp_path))
    yield
    assets.set_pack_dir(original)


def test_theme_for_rating_takes_higher_level():
    assert theme_for_rating(RATING_GREEN) == "green"
    assert theme_for_rating(RATING_GREEN_YELLOW) == "yellow"
    assert theme_for_rating(RATING_YELLOW_RED) == "red"
    assert theme_for_rating(RATING_ANY) == "red"
    assert theme_for_rating(RATING_RED) == "red"
    assert theme_for_rating(None) == "green"


def test_travellers_are_hidden():
    sc = build_script("Test", "", TROUBLE_BREWING + ["gunslinger", "bureaucrat"])
    assert "gunslinger" not in sc.first_night + sc.other_night
    assert all("Traveller" not in (a.team, b.team) for a, b, _ in sc.jinxes)
    assert all(c.team != "Traveller" for t in GRID_TEAMS for c in sc.teams.get(t, []))


def test_jinxes_bring_the_djinn():
    sc = build_script("Test", "", ["marionette", "balloonist", "imp"])
    assert sc.jinxes
    assert DJINN_ID in sc.by_id


def test_renders_a4_without_asset_pack(no_pack):
    img = render_sheet(build_script("Trouble Brewing", "TPI", TROUBLE_BREWING), theme="red")
    assert img.size == (1654, 2339)


def test_too_many_characters_give_no_image(no_pack):
    db = load_characters()
    everyone = [cid for cid, c in db.items() if c.get("character_type") in GRID_TEAMS]
    assert render_sheet(build_script("Alle", "", everyone)) is None


def test_generate_returns_jpeg(no_pack):
    buf = asyncio.run(generate_script_sheet("Trouble Brewing", "TPI", TROUBLE_BREWING, theme="green"))
    assert buf.getvalue()[:3] == b"\xff\xd8\xff"


def test_seed_varies_look_per_event_but_stays_fixed(no_pack):
    """Optik je Event zufällig, innerhalb eines Events fest (Dalyan, 27.10.2026)."""
    from logic.script_sheet import render_script_sheet

    def render(seed):
        return render_script_sheet("Trouble Brewing", "TPI", TROUBLE_BREWING, seed=seed).tobytes()
    first = render(11)
    assert render(11) == first      # gleiches Event → gleiches Bild
    assert render(12) != first      # anderes Event → andere Verzierung bzw. Kleckse


def test_new_drafts_get_an_image_seed():
    from datetime import datetime, timedelta

    from events import service
    from events.permissions import Actor
    from events.schema import BERLIN_TZ, EventData
    from events.store import Store
    from logic.event_images import image_signature

    store = Store(":memory:")
    now = datetime(2026, 10, 27, 12, 0, tzinfo=BERLIN_TZ)
    seeds = {service.start_draft(store, 1, Actor(7, is_admin=True), "Dalyan",
                                 EventData(start=now + timedelta(days=2)), now).data.image_seed for _ in range(3)}
    assert 0 not in seeds and len(seeds) == 3
    data = EventData(image_seed=5)
    other = EventData(image_seed=6)
    assert image_signature(data) != image_signature(other)  # andere Zahl → neues Bild
    assert EventData.from_dict(data.to_dict()).image_seed == 5
    assert EventData.from_dict({k: v for k, v in data.to_dict().items() if k != "image_seed"}).image_seed == 0
    store.close()
