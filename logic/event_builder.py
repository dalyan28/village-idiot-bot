"""Event-Embed für BotC-Events.

Aufbau: Author → Titel → Storytelling/Kamera/Level (inline) → Co-ST → Beschreibung
→ Skript → Termin → NPCs → Demons → Spielprägend → RSVP-Listen (inline) → Image → Footer

Nutzer stehen immer als Text im Embed, nie als Mention: Discord löst Mentions in Embeds
oft nicht auf und zeigt dann die rohe User-ID.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime

import discord

from events.schema import (
    RATING_GREEN,
    RATING_GREEN_YELLOW,
    RATING_RED,
    RATING_YELLOW,
    RATING_YELLOW_RED,
    SCRIPT_BASE,
    EventData,
    Person,
)
from events.service import RsvpLists
from events.templates import BASE3_SCRIPT_URLS, camera_text, co_st_text, full_description, full_title
from logic.character_emojis import WAITLIST, ui_emoji, with_emoji
from logic.script_cache import STATIC_DIR, load_characters

logger = logging.getLogger(__name__)

# Custom Emojis (im Embed, vor den Listen)
EMOJI_ACCEPTED = "<:accept_rec:1484978213863161986>"
EMOJI_DECLINED = "<:decline_rec:1484978231957524661>"
EMOJI_TENTATIVE = "<:tent_rec:1484978258553471066>"
EMOJI_WAITLIST = "<:warteliste:1484675744389927193>"
EMOJI_FILLER = "\U0001f47c"  # 👼 — Engelchen für „Auffüller" bei Academy-Runden

RATING_FILE = os.path.join(STATIC_DIR, "character_rating.json")

FIELD_CHAR_LIMIT = 1024
HIGHLIGHTS_LIMIT = 5
HIGHLIGHT_BOLD_SCORE = 9

EMBED_COLORS = {
    "special": 0xF4900C,    # Orange (⭐ Abweichung)
    RATING_GREEN: 0x78B159,
    RATING_YELLOW: 0xFDCB58,
    RATING_RED: 0xDD2E44,
    # Bereiche: Farbe der höchsten Stufe
    RATING_GREEN_YELLOW: 0xFDCB58,
    RATING_YELLOW_RED: 0xDD2E44,
}
DEFAULT_EMBED_COLOR = 0xFDCB58  # Gelb als Fallback (z. B. freie Skriptwahl)

_ratings: dict | None = None


def _load_ratings() -> dict:
    """Character-Scores (handgepflegt, gleiche Datei wie im ScriptRater)."""
    global _ratings
    if _ratings is None:
        if os.path.exists(RATING_FILE):
            with open(RATING_FILE, "r", encoding="utf-8") as f:
                _ratings = json.load(f)
        else:
            logger.warning("character_rating.json fehlt: %s", RATING_FILE)
            _ratings = {}
    return _ratings


def embed_color(data: EventData) -> int:
    if data.is_special:
        return EMBED_COLORS["special"]
    return EMBED_COLORS.get(data.rating, DEFAULT_EMBED_COLOR)


def _name(person: Person, name_for: Callable[[Person], str] | None) -> str:
    """Anzeigename, Markdown-escaped. `name_for` liefert den aktuellen Namen (z. B. aus dem Member-Cache)."""
    name = (name_for(person) if name_for else None) or person.name
    return discord.utils.escape_markdown(name)


def _format_list(people: list[Person], name_for, prefix: str = "", limit: int = FIELD_CHAR_LIMIT) -> str:
    """Eine Zeile pro Person. Passt die Liste nicht ins Feld, endet sie mit „… und N weitere“."""
    if not people:
        return "-"
    lines: list[str] = []
    for i, p in enumerate(people):
        line = f"> {prefix}{_name(p, name_for)}"
        rest = len(people) - i
        reserve = len(f"\n> … und {rest} weitere") if rest > 1 else 0
        if len("\n".join(lines + [line])) + reserve > limit:
            lines.append(f"> … und {rest} weitere")
            break
        lines.append(line)
    return "\n".join(lines)


def _split_field(name: str, text: str, inline: bool = False) -> list[tuple[str, str, bool]]:
    """Splittet einen langen Text in mehrere Fields wenn nötig."""
    if len(text) <= FIELD_CHAR_LIMIT:
        return [(name, text, inline)]

    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > FIELD_CHAR_LIMIT - 10:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return [(name if i == 0 else "​", chunk, inline) for i, chunk in enumerate(chunks)]


def highlight_characters(char_ids: list[str], limit: int = HIGHLIGHTS_LIMIT) -> str | None:
    """Die Charaktere mit dem höchsten Score, Score 9–10 fett. Ohne Zahlen (für Spieler nicht lesbar)."""
    ratings = _load_ratings()
    characters_db = load_characters()

    scored = []
    for char_id in char_ids:
        char_info = characters_db.get(char_id)
        if not char_info:
            continue
        name = char_info.get("character_name", char_id)
        score = ratings.get(name, {}).get("score", 0)
        if score > 0:
            scored.append((char_id, name, score))
    if not scored:
        return None

    scored.sort(key=lambda x: x[2], reverse=True)
    return ", ".join(
        with_emoji(char_id, f"**{name}**" if score >= HIGHLIGHT_BOLD_SCORE else name)
        for char_id, name, score in scored[:limit]
    )


def npc_characters(char_ids: list[str]) -> str | None:
    """Fabled und Loric des Skripts."""
    characters_db = load_characters()
    npcs = [
        with_emoji(c, characters_db[c].get("character_name", c))
        for c in char_ids
        if c in characters_db and characters_db[c].get("character_type", "").lower() in ("fabled", "loric")
    ]
    return ", ".join(npcs) if npcs else None


def demon_characters(char_ids: list[str], content: list | None = None) -> str | None:
    """Dämonen des Skripts (Dalyan, 20.10.2026). Homebrew-Dämonen kommen aus dem Skript-JSON."""
    characters_db = load_characters()
    demons, seen = [], set()
    for c in char_ids:
        info = characters_db.get(c)
        if info and info.get("character_type", "").lower() == "demon" and c not in seen:
            seen.add(c)
            demons.append(with_emoji(c, info.get("character_name", c)))
    for entry in content or []:
        if (isinstance(entry, dict) and str(entry.get("team", "")).lower() == "demon"
                and entry.get("id") not in seen and entry.get("name")):
            seen.add(entry.get("id"))
            demons.append(str(entry["name"]))
    return ", ".join(demons) if demons else None


def _script_value(data: EventData) -> str:
    script = data.script
    if script is None:
        return "-"
    text = script.display_name
    if script.author and script.kind != SCRIPT_BASE:
        text += f" von {script.author}"
    if script.version and script.kind != SCRIPT_BASE:
        text += f" · v{script.version}"
    url = script.url or (BASE3_SCRIPT_URLS.get(script.base_key, "") if script.kind == SCRIPT_BASE else "")
    return f"[{text}]({url})" if url else text


def _termin(data: EventData) -> str:
    if not data.start:
        return "-"
    ts = int(data.start.timestamp())
    end_ts = int(data.end.timestamp())
    return f"<t:{ts}:F> - <t:{end_ts}:t> - <t:{ts}:R>"


def _other_event_fields(embed: discord.Embed, data: EventData, organizer: str):
    """Event ohne Clocktower: Organisation, Beschreibung, Termin (Dalyan, 20.10.2026)."""
    embed.add_field(name="Organisation", value=organizer, inline=True)
    description = full_description(data)
    if description:
        for field_name, value, inline in _split_field("Beschreibung", description):
            embed.add_field(name=field_name, value=value, inline=inline)
    embed.add_field(name="Termin", value=_termin(data), inline=False)


def _botc_fields(embed: discord.Embed, data: EventData, st: str, name_for, academy_template: str | None = None):
    embed.add_field(name="Storytelling", value=st, inline=True)
    embed.add_field(name="Kamera", value=camera_text(data), inline=True)
    embed.add_field(name="Erfahrungslevel", value=data.level or "-", inline=True)

    co = discord.utils.escape_markdown(co_st_text(data))
    embed.add_field(name="Co-Storytelling", value=co, inline=True)

    description = full_description(data, academy_template)
    if description:
        for field_name, value, inline in _split_field("Beschreibung", description):
            embed.add_field(name=field_name, value=value, inline=inline)

    embed.add_field(name="Skript", value=_script_value(data), inline=True)

    embed.add_field(name="Termin", value=_termin(data), inline=False)

    char_ids = data.script.characters if data.script else []
    if char_ids:
        npcs = npc_characters(char_ids)
        if npcs:
            embed.add_field(name="NPCs", value=npcs, inline=False)
        # Demons vor „Spielprägend“ (Dalyan, 27.10.2026; Feld hieß vorher „Highlights“); der Abstand vor den Listen hängt am letzten Feld
        demons = demon_characters(char_ids, data.script.content)
        if demons:
            embed.add_field(name="Demons", value=demons[:1024], inline=False)
        highlights = highlight_characters(char_ids)
        if highlights:
            embed.add_field(name="Spielprägend", value=highlights, inline=False)



def build_event_embed(
    data: EventData,
    creator_name: str,
    rsvps: RsvpLists,
    creator_avatar_url: str | None = None,
    thumbnail_url: str | None = None,
    name_for: Callable[[Person], str] | None = None,
    created_at: datetime | None = None,
    academy_template: str | None = None,
) -> discord.Embed:
    """Baut das Event-Embed. `thumbnail_url`/Bild setzt der Aufrufer (Attachments).

    Ersteller:in steht nur unten in der Fußzeile (Profilbild, Name, Erstellungsdatum),
    wie beim alten Event-Post (Dalyan, 20.10.2026).
    """
    embed = discord.Embed(title=full_title(data), color=embed_color(data), timestamp=created_at)

    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)

    # ── Storytelling + Kamera + Level (inline, eine Reihe) ───────────
    st = _name(data.storyteller, name_for) if data.storyteller else "-"
    if data.is_other_event:
        _other_event_fields(embed, data, st)
    else:
        _botc_fields(embed, data, st, name_for, academy_template)


    # Abstand vor den RSVP-Listen (Dalyan, 20.10.2026): leere Zeile an das letzte Feld anhängen.
    # Discord schneidet Leerzeilen am Ende ab, ein unsichtbares Zeichen (U+200B) bleibt stehen.
    last = embed.fields[-1]
    if len(last.value) <= 1024 - 2:
        embed.set_field_at(len(embed.fields) - 1, name=last.name, value=f"{last.value}\n​", inline=last.inline)

    # ── RSVP-Listen (inline, eine Reihe) ─────────────────────────────
    accepted_text = _format_list(rsvps.players, name_for)
    if rsvps.waitlist:
        header = "\n\n**Warteliste**\n"
        room = FIELD_CHAR_LIMIT - len(accepted_text) - len(header)
        if room > 40:
            # Kleinere Uhr als App-Emoji, solange es noch nicht hochgeladen ist die bisherige
            waitlist_emoji = ui_emoji(WAITLIST, EMOJI_WAITLIST)
            accepted_text += header + _format_list(rsvps.waitlist, name_for, f"{waitlist_emoji} ", room)
    embed.add_field(
        name=f"{EMOJI_ACCEPTED} Akzeptiert ({rsvps.accepted_count}/{data.max_players})",
        value=accepted_text,
        inline=True,
    )
    embed.add_field(
        name=f"{EMOJI_DECLINED} Abgelehnt",
        value=_format_list(rsvps.declined, name_for),
        inline=True,
    )
    if data.is_academy:
        tentative_label = f"{EMOJI_FILLER} Auffüller ({len(rsvps.tentative)})"
    else:
        tentative_label = f"{EMOJI_TENTATIVE} Vorläufig ({len(rsvps.tentative)})"
    embed.add_field(
        name=tentative_label,
        value=_format_list(rsvps.tentative, name_for),
        inline=True,
    )

    embed.set_footer(text=creator_name, icon_url=creator_avatar_url or None)
    return embed
