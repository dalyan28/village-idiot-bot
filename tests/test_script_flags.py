"""Tests für die ⭐-Erkennung (Abweichung vom klassischen Clocktower)."""

from events.schema import SCRIPT_BASE, SCRIPT_FREE, SCRIPT_UPLOAD, ScriptRef
from logic.script_cache import get_base_script
from logic.script_flags import special_reasons


def test_base_script_is_classic():
    tb = get_base_script("trouble_brewing")
    assert special_reasons(ScriptRef(kind=SCRIPT_BASE, name="TB", characters=tb["characters"])) == []


def test_free_choice_has_no_flag():
    assert special_reasons(ScriptRef(kind=SCRIPT_FREE), is_amnesiac=True) == []


def test_loric_is_detected():
    reasons = special_reasons(ScriptRef(kind=SCRIPT_UPLOAD, name="X", characters=["imp", "bootlegger"]))
    assert reasons == ["Loric: Bootlegger"]


def test_homebrew_uses_names_from_content():
    content = [{"id": "_meta", "name": "X"}, {"id": "imp"}, {"id": "zz_hund", "name": "Höllenhund"}]
    script = ScriptRef(kind=SCRIPT_UPLOAD, name="X", characters=["imp", "zz_hund"], content=content)
    assert special_reasons(script) == ["Homebrew-Charaktere: Höllenhund"]


def test_amnesiac_and_rater_homebrew_flags():
    script = ScriptRef(kind=SCRIPT_UPLOAD, name="X", characters=["imp"])
    assert special_reasons(script, is_amnesiac=True, rater_homebrew=True) == [
        "Enthält Homebrew-Charaktere", "Überwiegend Amnesiac (All-Amnesiac-Skript)"]


def test_long_lists_are_shortened():
    ids = [f"hb{i}" for i in range(8)]
    reasons = special_reasons(ScriptRef(kind=SCRIPT_UPLOAD, name="X", characters=ids))
    assert reasons == ["Homebrew-Charaktere: hb0, hb1, hb2, hb3, hb4 und 3 weitere"]


def test_teensy_from_botcscripts_type_and_heuristic():
    from logic.script_flags import is_teensy
    tb = get_base_script("trouble_brewing")
    script = ScriptRef(kind=SCRIPT_UPLOAD, name="X", characters=tb["characters"])
    assert not is_teensy(script)  # 13 Townsfolk
    small = ScriptRef(kind=SCRIPT_UPLOAD, name="X", characters=tb["characters"][:6] + ["imp"])
    assert is_teensy(small)  # Faustregel: höchstens 6 Townsfolk
    assert is_teensy(script, "Teensyville") and not is_teensy(small, "Full")  # Angabe von botcscripts gewinnt
    assert not is_teensy(ScriptRef(kind=SCRIPT_FREE))


def test_teensy_title():
    from events.schema import EventData, Person
    from events.templates import base_title
    d = EventData(storyteller=Person("Dalyan"), script=ScriptRef(kind=SCRIPT_UPLOAD, name="Boozling", teensy=True))
    assert base_title(d) == "Teensy Boozling mit Dalyan"
    d.script.name = "Teensy Brewing"
    assert base_title(d) == "Teensy Brewing mit Dalyan"  # nicht doppelt
