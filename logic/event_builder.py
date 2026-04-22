"""Event-Embed-Builder für BotC-Events.

Baut das finale Event-Embed nach der vorgegebenen Struktur:
Author → Titel → Storytelling/Kamera/Level (inline) → Co-ST → Beschreibung
→ Skript → NPCs → Relevante Charaktere → RSVP-Listen (inline) → Image → Footer
"""

import json
import logging
import os

import discord

from logic.script_cache import load_characters

logger = logging.getLogger(__name__)

# Custom Emojis (im Embed, vor den Listen)
EMOJI_ACCEPTED = "<:accept_rec:1484978213863161986>"
EMOJI_DECLINED = "<:decline_rec:1484978231957524661>"
EMOJI_TENTATIVE = "<:tent_rec:1484978258553471066>"
EMOJI_WAITLIST = "<:warteliste:1484675744389927193>"
EMOJI_FILLER = "\U0001f47c"  # 👼 — Engelchen für „Auffüller" bei Academy-Runden

ACADEMY_MAX_ROUNDS = {
    "green": 100,
    "yellow": 200,
    "red": 300,
}


def build_academy_description(rating: str | None) -> str:
    """Liefert den festen Academy-Beschreibungstext.

    Die Zeile zur passenden Komplexitätsstufe (rating) wird **fett** markiert.
    Ohne Rating bleiben alle Zeilen normal.
    """
    rounds_lines_raw = [
        ("green", "💚-Angebote: maximal 100 Runden gespielt"),
        ("yellow", "🟡-Angebote: maximal 200 Runden gespielt"),
        ("red", "🟥-Angebote: maximal 300 Runden gespielt"),
    ]
    rounds_lines = [
        f"**{text}**" if key == rating else text
        for key, text in rounds_lines_raw
    ]

    max_rounds = ACADEMY_MAX_ROUNDS.get(rating)
    rounds_suffix = f"(hier {max_rounds})" if max_rounds else "(s. oben)"

    return (
        "Dies ist ein Angebot der Clocktower Academy!\n"
        "\n"
        "Das heißt, hier dreht sich alles rund ums Erlernen des Spiels. "
        "Hier findet ihr einen geschützten Rahmen, in dem ihr mit anderen "
        "Spieler:innen das Spiel entdecken könnt, die ebenfalls noch frisch sind.\n"
        "\n"
        "**Was ist der Unterschied zu einer regulären Runde?**\n"
        "\n"
        "In Academy-Runden nehmen wir besonders Rücksicht auf neue Spieler:innen. "
        "Unsere Storyteller erklären an passenden Stellen Interaktionen und "
        "mechanische Zusammenhänge mit etwas mehr Ruhe und ohne Zeitdruck. "
        "Generell geben unsere Storyteller etwas mehr Zeit. "
        "Auch ein leichtes „Unter-die-Arme-Greifen\" ist möglich, wenn ihr mal "
        "ratlos seid und einen Tipp braucht bzgl. Strategie und Taktik.\n"
        "\n"
        "**Wer kann sich anmelden?**\n"
        "\n"
        "Prinzipiell haben wir eine maximale Anzahl gespielter Runden für jede Komplexitätsstufe:\n"
        f"{rounds_lines[0]}\n"
        f"{rounds_lines[1]}\n"
        f"{rounds_lines[2]}\n"
        "\n"
        f"Leute über der Stufe {rounds_suffix} können sich gerne unter "
        "„Auffüller\" anmelden. Wenn nicht ausreichend Spieler:innen "
        "angemeldet sind, freuen wir uns immer über „Auffüller\", da sonst "
        "die Runde teilweise nicht stattfinden kann. In diesem Fall gilt "
        "aber: Rücksicht (und bisweilen etwas Zurückhaltung) ist geboten!"
    )

# Character-Rating-Datei
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
RATING_FILE = os.path.join(PROJECT_ROOT, "character_rating.json")

FIELD_CHAR_LIMIT = 1024

# Embed-Farben nach Script-Complexity (Prioritätsreihenfolge)
EMBED_COLORS = {
    "hammer":  0xF4900C,  # Orange — Homebrew
    "yellow":  0xFDCB58,  # Gelb
    "red":     0xDD2E44,  # Rot
    "green":   0x78B159,  # Grün
    "dove":    0x78B159,  # Grün (Casual)
    "camera":  0xFDCB58,  # Gelb (Default für Aufzeichnung)
}
DEFAULT_EMBED_COLOR = 0xFDCB58  # Gelb als Fallback

# Rating-Cache
_ratings: dict | None = None


def _load_ratings() -> dict:
    """Lädt die Character-Ratings."""
    global _ratings
    if _ratings is not None:
        return _ratings
    if not os.path.exists(RATING_FILE):
        _ratings = {}
        return _ratings
    with open(RATING_FILE, "r", encoding="utf-8") as f:
        _ratings = json.load(f)
    return _ratings


def _format_user_list_quoted(user_ids: list[int]) -> str:
    """Formatiert User-IDs als zitierte Mentions (> <@id>)."""
    if not user_ids:
        return "-"
    return "\n".join(f"> <@{uid}>" for uid in user_ids)


def _split_field(name: str, text: str, inline: bool = False) -> list[tuple[str, str, bool]]:
    """Splittet einen langen Text in mehrere Fields wenn nötig."""
    if len(text) <= FIELD_CHAR_LIMIT:
        return [(name, text, inline)]

    fields = []
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

    for i, chunk in enumerate(chunks):
        field_name = name if i == 0 else "\u200b"
        fields.append((field_name, chunk, inline))
    return fields


def _get_relevant_characters(char_ids: list[str], limit: int = 5) -> str | None:
    """Findet die relevantesten Charaktere basierend auf character_rating.json.

    Charaktere mit Score 9-10 werden **fett** hervorgehoben.
    """
    ratings = _load_ratings()
    characters_db = load_characters()

    scored = []
    for char_id in char_ids:
        char_info = characters_db.get(char_id)
        if not char_info:
            continue
        name = char_info.get("character_name", char_id)
        rating = ratings.get(name, {})
        score = rating.get("score", 0)
        if score > 0:
            scored.append((name, score))

    if not scored:
        return None

    # Nach Score sortieren (höchste zuerst)
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:limit]

    parts = []
    for name, score in top:
        if score >= 9:
            parts.append(f"**{name}** ({score})")
        else:
            parts.append(f"{name} ({score})")

    return ", ".join(parts)


def _get_npcs(char_ids: list[str]) -> str | None:
    """Extrahiert Fabled und Loric Characters."""
    characters_db = load_characters()
    npcs = []
    for char_id in char_ids:
        char_info = characters_db.get(char_id)
        if char_info and char_info.get("character_type", "").lower() in ("fabled", "loric"):
            npcs.append(char_info.get("character_name", char_id))
    if not npcs:
        return None
    return ", ".join(npcs)


def build_event_embed(event_data: dict) -> discord.Embed:
    """Baut das Event-Embed nach der spezifizierten Struktur."""
    title = event_data.get("title", "Event")
    label = event_data.get("label")
    embed_color = EMBED_COLORS.get(label, DEFAULT_EMBED_COLOR)

    embed = discord.Embed(
        title=title,
        color=embed_color,
        timestamp=discord.utils.utcnow(),
    )

    # ── Thumbnail (z.B. Base3 Script-Logo) ────────────────────────────────
    thumbnail_url = event_data.get("thumbnail_url")
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)

    # ── Author (oben) ────────────────────────────────────────────────────
    creator = event_data.get("creator_name", "Unbekannt")
    avatar_url = event_data.get("creator_avatar_url")
    if avatar_url:
        embed.set_author(name=creator, icon_url=avatar_url)
    else:
        embed.set_author(name=creator)

    # ── Storytelling + Kamera + Level (inline, eine Reihe) ───────────
    storyteller = event_data.get("storyteller") or "-"
    embed.add_field(name="Storytelling", value=storyteller, inline=True)

    camera = event_data.get("camera")
    if camera is True:
        cam_str = "Pflicht"
    elif camera is False:
        cam_str = "Aus"
    else:
        cam_str = "Keine Pflicht"
    embed.add_field(name="Kamera", value=cam_str, inline=True)

    level = event_data.get("level") or "-"
    embed.add_field(name="Erfahrungslevel", value=level, inline=True)

    # ── Co-Storytelling ──────────────────────────────────────────────
    co_st = event_data.get("co_storyteller")
    embed.add_field(name="Co-Storytelling", value=co_st or "Nicht möglich", inline=True)

    # ── Beschreibung ─────────────────────────────────────────────────
    description = event_data.get("description")
    if description:
        for field_name, value, inline in _split_field("Beschreibung", description, inline=False):
            embed.add_field(name=field_name, value=value, inline=inline)

    # ── Skript (verlinkt zu botcscripts, mit Autor + Version) ────────
    script = event_data.get("script") or "-"
    script_author = event_data.get("script_author", "")
    script_version = event_data.get("script_version", "")
    script_val = script
    if script_author:
        script_val += f" von {script_author}"
    if script_version:
        script_val += f" · v{script_version}"
    script_url = event_data.get("script_url")
    if script_url:
        embed.add_field(name="Skript", value=f"[{script_val}]({script_url})", inline=True)
    else:
        embed.add_field(name="Skript", value=script_val, inline=True)

    # ── Termin ────────────────────────────────────────────────────────
    ts = event_data.get("timestamp")
    end_ts = event_data.get("end_timestamp")
    if ts:
        if end_ts:
            termin_value = f"<t:{ts}:F> - <t:{end_ts}:t> - <t:{ts}:R>"
        else:
            termin_value = f"<t:{ts}:F> - <t:{ts}:R>"
    else:
        termin_value = "-"
    embed.add_field(name="Termin", value=termin_value, inline=False)

    # ── NPCs (Fabled/Loric) — deaktiviert, ggf. später wieder nutzen ──
    char_ids = event_data.get("script_characters", [])
    # if char_ids:
    #     npcs = _get_npcs(char_ids)
    #     if npcs:
    #         embed.add_field(name="NPCs", value=npcs, inline=False)

    # ── Relevante Charaktere — deaktiviert, ggf. später wieder nutzen ──
    # if char_ids:
    #     relevant = _get_relevant_characters(char_ids)
    #     if relevant:
    #         embed.add_field(name="Relevante Charaktere", value=relevant, inline=False)

    # ── RSVP-Listen (inline, eine Reihe) ─────────────────────────────
    accepted = event_data.get("accepted", [])
    declined = event_data.get("declined", [])
    tentative = event_data.get("tentative", [])
    max_players = event_data.get("max_players", 12)

    # Akzeptiert mit Warteliste
    if len(accepted) > max_players:
        main = accepted[:max_players]
        waitlist = accepted[max_players:]
        accepted_text = _format_user_list_quoted(main)
        waitlist_text = "\n".join(f"> {EMOJI_WAITLIST} <@{uid}>" for uid in waitlist)
        accepted_text += f"\n\n**Warteliste**\n{waitlist_text}"
    else:
        accepted_text = _format_user_list_quoted(accepted)

    embed.add_field(
        name=f"{EMOJI_ACCEPTED} Akzeptiert ({len(accepted)}/{max_players})",
        value=accepted_text,
        inline=True,
    )
    embed.add_field(
        name=f"{EMOJI_DECLINED} Abgelehnt",
        value=_format_user_list_quoted(declined),
        inline=True,
    )
    if event_data.get("is_academy"):
        tentative_label = f"{EMOJI_FILLER} Auffüller ({len(tentative)})"
    else:
        tentative_label = f"{EMOJI_TENTATIVE} Vorläufig ({len(tentative)})"
    embed.add_field(
        name=tentative_label,
        value=_format_user_list_quoted(tentative),
        inline=True,
    )

    # ── Footer (unten) ───────────────────────────────────────────────
    footer_icon = avatar_url if avatar_url else discord.Embed.Empty
    embed.set_footer(text=creator, icon_url=footer_icon)

    logger.debug("Embed gebaut für Event '%s'", title)
    return embed
