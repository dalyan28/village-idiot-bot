"""Event-Embed für BotC-Events.

Aufbau: Author → Titel → Storytelling/Kamera/Level (inline) → Co-ST → Beschreibung
→ Skript → Termin → NPCs → RSVP-Listen (inline) → Image → Footer

Nutzer stehen immer als Text im Embed, nie als Mention: Discord löst Mentions in Embeds
oft nicht auf und zeigt dann die rohe User-ID.
"""

from __future__ import annotations

import logging
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
from logic.script_cache import load_characters

logger = logging.getLogger(__name__)

# Custom Emojis (im Embed, vor den Listen)
EMOJI_ACCEPTED = "<:accept_rec:1484978213863161986>"
EMOJI_DECLINED = "<:decline_rec:1484978231957524661>"
EMOJI_TENTATIVE = "<:tent_rec:1484978258553471066>"
EMOJI_WAITLIST = "<:warteliste:1484675744389927193>"
EMOJI_FILLER = "\U0001f47c"  # 👼 — Engelchen für „Auffüller" bei Academy-Runden

FIELD_CHAR_LIMIT = 1024
# Discord lehnt Embeds über 6000 Zeichen ab (Titel, Felder, Fußzeile zusammen). Für die Anmeldelisten bleibt beim
# Anlegen LIST_RESERVE frei; reicht der Platz später nicht, enden die Listen mit „… und N weitere“.
EMBED_LIMIT = 6000
LIST_RESERVE = 1000
CREATOR_NAME_MAX = 32  # Discord-Anzeigenamen haben höchstens 32 Zeichen

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


def _pieces(line: str, size: int) -> list[str]:
    """Eine Zeile in Stücke bis `size` Zeichen, getrennt an Leerzeichen (notfalls mitten im Wort)."""
    pieces = []
    while len(line) > size:
        cut = line.rfind(" ", 0, size)
        cut = cut if cut > size // 2 else size
        pieces.append(line[:cut].rstrip())
        line = line[cut:].lstrip()
    return pieces + [line]


def _split_field(name: str, text: str, inline: bool = False) -> list[tuple[str, str, bool]]:
    """Splittet einen langen Text in mehrere Fields wenn nötig, bevorzugt an Zeilenumbrüchen. Zu lange Absätze
    werden an Wortgrenzen geteilt, damit kein Feld über 1024 Zeichen kommt (Dalyan, 29.10.2026)."""
    if len(text) <= FIELD_CHAR_LIMIT:
        return [(name, text, inline)]

    chunks = []
    current = ""
    lines = [piece for line in text.split("\n") for piece in _pieces(line, FIELD_CHAR_LIMIT - 10)]
    for line in lines:
        if len(current) + len(line) + 1 > FIELD_CHAR_LIMIT - 10:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return [(name if i == 0 else "​", chunk, inline) for i, chunk in enumerate(chunks)]


def npc_characters(char_ids: list[str]) -> str | None:
    """Fabled und Loric des Skripts."""
    characters_db = load_characters()
    npcs = [
        with_emoji(c, characters_db[c].get("character_name", c))
        for c in char_ids
        if c in characters_db and characters_db[c].get("character_type", "").lower() in ("fabled", "loric")
    ]
    return ", ".join(npcs) if npcs else None


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
    accepted_name = f"{EMOJI_ACCEPTED} Akzeptiert ({rsvps.accepted_count}/{data.max_players})"
    declined_name = f"{EMOJI_DECLINED} Abgelehnt"
    if data.is_academy:
        tentative_name = f"{EMOJI_FILLER} Auffüller ({len(rsvps.tentative)})"
    else:
        tentative_name = f"{EMOJI_TENTATIVE} Vorläufig ({len(rsvps.tentative)})"
    # Platz je Liste: was vom Embed übrig ist, gleichmäßig verteilt, höchstens ein volles Feld
    used = len(embed) + len(creator_name or "") + len(accepted_name + declined_name + tentative_name)
    limit = max(60, min(FIELD_CHAR_LIMIT, (EMBED_LIMIT - used) // 3))

    accepted_text = _format_list(rsvps.players, name_for, limit=limit)
    if rsvps.waitlist:
        header = "\n\n**Warteliste**\n"
        room = limit - len(accepted_text) - len(header)
        if room > 40:
            # Kleinere Uhr als App-Emoji, solange es noch nicht hochgeladen ist die bisherige
            waitlist_emoji = ui_emoji(WAITLIST, EMOJI_WAITLIST)
            accepted_text += header + _format_list(rsvps.waitlist, name_for, f"{waitlist_emoji} ", room)
    embed.add_field(name=accepted_name, value=accepted_text, inline=True)
    embed.add_field(name=declined_name, value=_format_list(rsvps.declined, name_for, limit=limit), inline=True)
    embed.add_field(name=tentative_name, value=_format_list(rsvps.tentative, name_for, limit=limit), inline=True)

    embed.set_footer(text=creator_name, icon_url=creator_avatar_url or None)
    _fit_embed(embed)
    return embed


def _fit_embed(embed: discord.Embed):
    """Letzte Sicherung, falls das Embed trotz Prüfung beim Anlegen zu lang ist (z. B. nachdem der Academy-Text
    des Servers geändert wurde): Die Beschreibung wird von hinten gekürzt, damit Discord den Post nicht ablehnt."""
    over = len(embed) - EMBED_LIMIT
    for i in reversed(range(len(embed.fields))):
        if over <= 0:
            return
        f = embed.fields[i]
        if f.name not in ("Beschreibung", "\u200b"):
            continue
        keep = len(f.value) - over - 2
        if keep < 20:  # Feld ganz weglassen
            over -= len(f.name) + len(f.value)
            embed.remove_field(i)
        else:
            embed.set_field_at(i, name=f.name, value=f.value[:keep] + " …", inline=f.inline)
            over = 0


def description_overflow(data: EventData, academy_template: str | None = None) -> int:
    """Um wie viele Zeichen die Beschreibung (samt Academy-Text) zu lang für den Event-Post ist; 0 = passt.
    Gerechnet mit leeren Listen, längstem Anzeigenamen und LIST_RESERVE frei für die Anmeldungen."""
    empty = RsvpLists(players=[], waitlist=[], tentative=[], declined=[])
    embed = build_event_embed(data, "W" * CREATOR_NAME_MAX, empty, academy_template=academy_template)
    lists = sum(len(f.name) + len(f.value) for f in embed.fields[-3:])
    return max(0, len(embed) - lists + LIST_RESERVE - EMBED_LIMIT)
