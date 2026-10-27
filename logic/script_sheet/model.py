"""Skript aufbereiten: Charaktere nach Team, Jinxes (mit Djinn), Bootlegger-Regeln, Nachtreihenfolge,
spielprägende Charaktere. Travellers werden nicht gezeigt – weder im Raster noch im Anhang, in der
Nachtreihenfolge oder in Jinxes (Dalyan, 27.10.2026).
"""

import functools
import json
import os
from dataclasses import dataclass, field

from logic.script_cache import STATIC_DIR, VOLUME_DIR, get_jinxes_for_script, load_characters

GRID_TEAMS = ("Townsfolk", "Outsider", "Minion", "Demon")
TEAM_MAP = {"townsfolk": "Townsfolk", "outsider": "Outsider", "minion": "Minion", "demon": "Demon",
            "traveller": "Traveller", "traveler": "Traveller", "fabled": "Fabled", "loric": "Loric"}
NIGHT_SPECIALS = ("dusk", "minioninfo", "demoninfo", "dawn")
DJINN_ID = "djinn"
DEFINING_LIMIT = 5  # wie logic/event_builder.HIGHLIGHTS_LIMIT („Spielprägend“ im Event-Post)


@dataclass(frozen=True)
class Char:
    id: str
    name: str
    ability: str
    team: str
    urls: tuple = ()  # Homebrew-Icons aus dem Skript-JSON

    @property
    def evil(self):
        return self.team in ("Minion", "Demon")


@dataclass
class Script:
    name: str
    author: str = ""
    teams: dict = field(default_factory=dict)        # Team → [Char]
    jinxes: list = field(default_factory=list)       # [(Char a, Char b, Text)]
    rules: list = field(default_factory=list)        # Bootlegger-Regeln
    first_night: list = field(default_factory=list)  # [id]
    other_night: list = field(default_factory=list)
    by_id: dict = field(default_factory=dict)

    @property
    def fabled_loric(self):
        return [c for t in ("Fabled", "Loric") for c in self.teams.get(t, [])]


def _resolve(name):
    """Datendatei: Volume zuerst (dort aktualisiert), sonst der Stand im Repo."""
    path = os.path.join(VOLUME_DIR, name)
    return path if os.path.exists(path) else os.path.join(STATIC_DIR, name)


@functools.lru_cache(maxsize=1)
def _nightsheet():
    with open(_resolve("nightsheet.json"), encoding="utf-8") as f:
        return json.load(f)


@functools.lru_cache(maxsize=1)
def _ratings():
    path = os.path.join(STATIC_DIR, "character_rating.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def _norm(cid):
    return cid.lower().replace("_", "").replace("-", "")


def build_script(name, author, char_ids, meta=None, content=None):
    """Script aus den Angaben, die event_images.render_image übergibt."""
    db = load_characters()
    meta = meta or {}
    homebrew = {item["id"]: item for item in (content or [])
                if isinstance(item, dict) and item.get("id") and item["id"] != "_meta"}
    ids = [i if i in db or i in homebrew else _norm(i) for i in char_ids]
    sc = Script(name=name or "Unbenanntes Skript", author=author or "",
                rules=[r for r in meta.get("bootlegger") or [] if isinstance(r, str)])
    for cid in ids:
        info, hw = db.get(cid, {}), homebrew.get(cid, {})
        team = info.get("character_type") or TEAM_MAP.get(str(hw.get("team", "")).lower()) or "Townsfolk"
        urls = hw.get("image") or ()
        urls = (urls,) if isinstance(urls, str) else tuple(u for u in urls if isinstance(u, str))
        ch = Char(cid, info.get("character_name") or hw.get("name") or cid,
                  info.get("ability") or hw.get("ability") or "", team, urls)
        sc.teams.setdefault(team, []).append(ch)
        sc.by_id[cid] = ch

    for j in get_jinxes_for_script(ids):
        a, b = sc.by_id.get(j["char_a"]), sc.by_id.get(j["char_b"])
        if a and b and "Traveller" not in (a.team, b.team):
            sc.jinxes.append((a, b, j["reason"]))
    if sc.jinxes and DJINN_ID not in sc.by_id:  # Jinxes setzen den Djinn voraus
        info = db.get(DJINN_ID, {})
        djinn = Char(DJINN_ID, info.get("character_name", "Djinn"),
                     info.get("ability", "Use the Djinn's special rule. All players know what it is."), "Fabled")
        sc.teams.setdefault("Fabled", []).insert(0, djinn)
        sc.by_id[DJINN_ID] = djinn

    # Nachtreihenfolge: eigene des Autors (_meta) vor der offiziellen; Homebrew-Charaktere bringen ihre Position
    # als Zahl mit und werden in die offizielle Reihenfolge einsortiert
    present = {i for i in ids if sc.by_id[i].team != "Traveller"}
    for key, target in (("firstNight", sc.first_night), ("otherNight", sc.other_night)):
        if isinstance(meta.get(key), list) and meta[key]:
            target.extend(x for x in meta[key] if x in NIGHT_SPECIALS or x in present)
            continue
        sheet = _nightsheet()[key]
        pos = {x: i for i, x in enumerate(sheet)}
        items = [(pos[x], x) for x in sheet if x in NIGHT_SPECIALS or x in present]
        for cid in ids:
            n = homebrew.get(cid, {}).get(key)
            if cid in present and cid not in pos and isinstance(n, (int, float)) and n > 0:
                items.append((min(n - 0.5, len(sheet) - 1.5), cid))
        target.extend(x for _, x in sorted(items))
    return sc


def from_script_json(data, name=None, author=None):
    """Script direkt aus einem Skript-JSON (Liste aus _meta und Charakteren)."""
    meta = next((x for x in data if isinstance(x, dict) and x.get("id") == "_meta"), {})
    ids = [x if isinstance(x, str) else x["id"] for x in data
           if isinstance(x, str) or (isinstance(x, dict) and x.get("id") and x["id"] != "_meta")]
    return build_script(name or meta.get("name"), author if author is not None else meta.get("author", ""), ids,
                        meta=meta, content=data)


def defining(sc):
    """Spielprägende Charaktere {id: Score}: die DEFINING_LIMIT mit dem höchsten Score aus
    static/character_rating.json (gleiche Logik wie logic/event_builder.highlight_characters)."""
    ratings = _ratings()
    scored = [(c.id, ratings.get(c.name, {}).get("score", 0)) for t in GRID_TEAMS for c in sc.teams.get(t, [])]
    scored = sorted((x for x in scored if x[1] > 0), key=lambda x: x[1], reverse=True)
    return dict(scored[:DEFINING_LIMIT])
