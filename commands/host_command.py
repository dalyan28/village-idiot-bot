"""Slash-Command /host und DM-Listener für die Event-Erstellung."""

import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from config import get_guild_config
from logic.conversation import (
    call_haiku,
    end_session,
    get_session,
    has_active_session,
    start_conversation,
    start_session,
    was_recently_expired,
)
from logic.label import (
    FREE_CHOICE_DESCRIPTION,
    LABEL_DESCRIPTION,
    LABEL_EMOJI,
    compute_label,
    get_label_emoji,
)
from logic.botcscripts import search_scripts
from logic.script_cache import cache_script, is_base_script, load_characters, lookup_script, validate_script_json
from logic.event_builder import build_event_embed

logger = logging.getLogger(__name__)

BERLIN_TZ = ZoneInfo("Europe/Berlin")
BOT_COLOR = 0x5865F2
ERROR_COLOR = 0xED4245

CANCEL_KEYWORDS = {"abbrechen", "cancel", "stop"}
CONFIRM_KEYWORDS = {"ok", "fertig", "bestätigen", "confirm", "ja", "yes"}

# Nummerierte Felder für den Review-Flow
REVIEW_FIELDS = [
    ("title", "Titel"),
    ("description", "Description"),
    ("storyteller", "Storyteller:in"),
    ("script", "Skript"),
    ("level", "Level"),
    ("start_time", "Termin"),
    ("duration_minutes", "Dauer"),
    ("camera", "Kamera"),
    ("max_players", "Max Spieler"),
    ("co_storyteller", "Co-ST"),
    ("is_casual", "Casual-Runde"),
    ("is_recorded", "Aufzeichnung"),
]


def _cost_footer(session) -> str:
    """Baut eine dezente Kosten-Fußzeile. Nur im Dev-Modus."""
    if os.getenv("ENV") != "dev":
        return ""
    return (
        f"-# 💰 Nachricht {session.call_count} · "
        f"{session.total_input_tokens} in / {session.total_output_tokens} out · "
        f"${session.total_cost_usd:.4f} (gesamt)"
    )


# ── Embed Builders ───────────────────────────────────────────────────────────


def _parse_haiku_to_embed(haiku_message: str) -> tuple[str | None, discord.Embed | None]:
    """Versucht eine strukturierte Haiku-Antwort (ERFASST:/DEFAULTS:) in ein Embed zu parsen.

    Returns:
        (plain_text, embed) — plain_text für den Teil vor ERFASST:, embed für den strukturierten Teil.
        Wenn kein ERFASST: gefunden wird, gibt (None, None) zurück.
    """
    if "ERFASST:" not in haiku_message:
        return None, None

    # Text vor ERFASST: ist der Intro-Satz
    parts = haiku_message.split("ERFASST:", 1)
    intro = parts[0].strip()
    rest = parts[1] if len(parts) > 1 else ""

    embed = discord.Embed(title=intro or "📝 Erfasst", color=BOT_COLOR)

    # ERFASST:-Felder parsen
    erfasst_text = rest
    defaults_text = ""
    fragen_text = ""

    if "DEFAULTS:" in rest:
        erfasst_text, defaults_rest = rest.split("DEFAULTS:", 1)
        defaults_text = defaults_rest
    if "Noch offen:" in (defaults_text or erfasst_text):
        target = defaults_text if defaults_text else erfasst_text
        if "Noch offen:" in target:
            before, fragen_text = target.split("Noch offen:", 1)
            if defaults_text:
                defaults_text = before
            else:
                erfasst_text = before

    # Felder in Embed-Fields umwandeln
    if erfasst_text.strip():
        embed.add_field(name="✅ Erfasst", value=erfasst_text.strip(), inline=False)
    if defaults_text.strip():
        embed.add_field(name="📋 Annahmen", value=defaults_text.strip(), inline=False)
    if fragen_text.strip():
        embed.add_field(name="❓ Noch offen", value=fragen_text.strip(), inline=False)

    return "", embed


def _categorize_characters(char_ids: list[str]) -> dict[str, list[str]]:
    """Kategorisiert Character-IDs nach Typ (Townsfolk, Outsider, Minion, Demon, Weitere)."""
    characters_db = load_characters()
    categories = {
        "Townsfolk": [],
        "Outsider": [],
        "Minion": [],
        "Demon": [],
        "Weitere": [],
    }
    type_map = {
        "Townsfolk": "Townsfolk",
        "Outsider": "Outsider",
        "Minion": "Minion",
        "Demon": "Demon",
        "Traveller": "Weitere",
        "Fabled": "Weitere",
    }
    for char_id in char_ids:
        char_info = characters_db.get(char_id)
        if char_info:
            char_type = char_info.get("character_type", "")
            category = type_map.get(char_type, "Weitere")
            categories[category].append(char_info.get("character_name", char_id))
        else:
            categories["Weitere"].append(char_id)
    return categories


def _build_script_info_embed(script_data: dict) -> discord.Embed:
    """Baut ein Embed mit Script-Informationen und kategorisierten Charakteren."""
    name = script_data.get("name", "Unbekannt")
    embed = discord.Embed(title=f"📜 Script erkannt: {name}", color=BOT_COLOR)

    author = script_data.get("author")
    if author:
        embed.add_field(name="Autor", value=author, inline=True)

    version = script_data.get("version")
    if version:
        embed.add_field(name="Version", value=version, inline=True)

    characters = script_data.get("characters", [])
    if characters:
        embed.add_field(name="Gesamt", value=f"{len(characters)} Charaktere", inline=True)

        cats = _categorize_characters(characters)
        for cat_name, char_list in cats.items():
            if char_list:
                display = ", ".join(char_list)
                if len(display) > 1020:
                    display = display[:1017] + "..."
                embed.add_field(name=cat_name, value=f"```{display}```", inline=False)

    embed.set_footer(text="Stimmt das? Antworte mit 'ja' zum Bestätigen oder beschreibe was anders sein soll.")
    return embed


def _build_review_embed(session) -> discord.Embed:
    """Baut ein Review-Embed mit inline Fields (wie Apollo)."""
    fields = session.fields
    is_free = bool(fields.get("is_free_choice"))

    embed = discord.Embed(
        title="📋 Event-Zusammenfassung",
        color=BOT_COLOR,
    )

    embed.add_field(name="1 · Titel", value=f"```{fields.get('title') or '-'}```", inline=False)

    # Beschreibung als Code-Block (max 1024 Zeichen)
    desc = fields.get("description") or "Keine Beschreibung"
    if len(desc) > 1010:
        desc = desc[:1007] + "..."
    embed.add_field(name="2 · Beschreibung", value=f"```{desc}```", inline=False)

    # Inline-Paare
    st = fields.get("storyteller") or "-"
    script = "Freie Skriptwahl" if is_free else (fields.get("script") or "-")
    if fields.get("script_version") and not is_free:
        script += f" (v{fields['script_version']})"

    embed.add_field(name="3 · Storyteller:in", value=f"```{st}```", inline=True)
    embed.add_field(name="4 · Skript", value=f"```{script}```", inline=True)

    level = fields.get("level") or "-"
    start_time = fields.get("start_time") or "-"
    embed.add_field(name="5 · Level", value=f"```{level}```", inline=True)
    embed.add_field(name="6 · Termin", value=f"```{start_time}```", inline=True)

    duration = fields.get("duration_minutes")
    if duration:
        h, m = divmod(int(duration), 60)
        dur_str = f"{h}h {m:02d}min" if h else f"{m}min"
    else:
        dur_str = "-"
    max_p = fields.get("max_players") or "-"
    embed.add_field(name="7 · Dauer", value=f"```{dur_str}```", inline=True)
    embed.add_field(name="8 · Max Spieler", value=f"```{max_p}```", inline=True)

    camera = fields.get("camera")
    cam_str = "an" if camera is True else ("aus" if camera is False else "keine Pflicht")
    co_st = fields.get("co_storyteller") or "Nein"
    embed.add_field(name="9 · Kamera", value=f"```{cam_str}```", inline=True)
    embed.add_field(name="10 · Co-ST", value=f"```{co_st}```", inline=True)

    casual = "Ja 🕊️" if fields.get("is_casual") else "Nein"
    recorded = "Ja 🎦" if fields.get("is_recorded") else "Nein"
    embed.add_field(name="11 · Casual", value=f"```{casual}```", inline=True)
    embed.add_field(name="12 · Aufzeichnung", value=f"```{recorded}```", inline=True)

    embed.set_footer(text="Antworte mit einer Nummer (z.B. '2') zum Ändern, Freitext für Korrekturen, oder 'ok' zum Bestätigen.")
    return embed


def _build_script_choice_embed(results: list[dict]) -> discord.Embed:
    """Baut ein Embed mit nummerierten Script-Suchergebnissen."""
    count = len(results)
    embed = discord.Embed(
        title="🔍 Skript-Suche",
        description=f"Ich habe folgende Skripte gefunden:",
        color=BOT_COLOR,
    )
    for i, result in enumerate(results, 1):
        author = result.get("author") or "Unbekannt"
        version = result.get("version") or "?"
        chars = result.get("characters", [])
        char_count = f" · {len(chars)} Charaktere" if chars else ""
        embed.add_field(
            name=f"{i}. {result['name']}",
            value=f"von {author} · v{version}{char_count}",
            inline=False,
        )
    embed.set_footer(text=f"Antworte mit 1-{count} oder 'skip' zum Überspringen.")
    return embed


def _build_preview_embed(session) -> discord.Embed:
    """Baut das finale Vorschau-Embed (wie es im Event-Channel aussehen wird)."""
    fields = session.fields
    label = session.label
    is_free = bool(fields.get("is_free_choice"))
    emoji = get_label_emoji(label, is_free_choice=is_free)

    title = fields.get("title") or "BotC Event"
    if emoji:
        title = f"{emoji} {title}"

    embed = discord.Embed(title=title, description=fields.get("description") or "", color=BOT_COLOR)

    embed.add_field(name="Storyteller:in", value=fields.get("storyteller") or "-", inline=False)

    script_display = fields.get("script") or "-"
    if is_free:
        script_display = "Freie Skriptwahl"
    elif fields.get("script_version"):
        script_display += f" (v{fields['script_version']})"
    embed.add_field(name="Skript:", value=script_display, inline=False)

    embed.add_field(name="Level:", value=fields.get("level") or "-", inline=False)

    embed.add_field(name="Termin:", value=fields.get("start_time") or "-", inline=False)

    extras = []
    if fields.get("co_storyteller"):
        extras.append(f"Co-ST: {fields['co_storyteller']}")
    if fields.get("camera") is not None:
        cam = "an" if fields["camera"] is True else ("aus" if fields["camera"] is False else "keine Pflicht")
        extras.append(f"Kamera: {cam}")
    if fields.get("max_players"):
        extras.append(f"Max Spieler: {fields['max_players']}")
    if fields.get("duration_minutes"):
        h, m = divmod(fields["duration_minutes"], 60)
        extras.append(f"Dauer: {h}h {m:02d}min" if h else f"Dauer: {m}min")
    if extras:
        embed.add_field(name="Weitere Informationen:", value="\n".join(extras), inline=False)

    if is_free:
        embed.add_field(name="Label:", value=f"{emoji} {FREE_CHOICE_DESCRIPTION}", inline=False)
    elif label:
        label_desc = LABEL_DESCRIPTION.get(label, label)
        label_emoji = LABEL_EMOJI.get(label, "")
        embed.add_field(name="Label:", value=f"{label_emoji} {label_desc}", inline=False)

    embed.set_footer(text=f"Vorschau — Server: {session.guild_name}")
    return embed


def _parse_start_time(time_str: str) -> int | None:
    """Parst einen ISO-Zeitstring in einen Unix-Timestamp."""
    formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"]
    for fmt in formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            dt = dt.replace(tzinfo=BERLIN_TZ)
            return int(dt.timestamp())
        except ValueError:
            continue
    logger.warning("Kann Zeitformat nicht parsen: '%s'", time_str)
    return None


# ── Script Resolution ────────────────────────────────────────────────────────


async def _validate_script_inline(session, channel: discord.DMChannel) -> None:
    """Validiert das Script inline während der Konversation und zeigt Info-Embed.

    Wird nach jedem Haiku-Call aufgerufen. Zeigt Script-Details wenn ein neues Script erkannt wurde.
    Bei Cache-Miss wird sofort die API durchsucht und die Auswahl gestartet.
    """
    script_name = session.fields.get("script")
    if not script_name or session.fields.get("is_free_choice"):
        return

    # Schon validiert?
    last_validated = getattr(session, "_last_validated_script", None)
    if last_validated == script_name:
        return

    session.touch()
    script_data, source = lookup_script(script_name)

    if script_data and source in ("base", "cache", "cache_stale"):
        session._last_validated_script = script_name
        embed = _build_script_info_embed(script_data)
        await channel.send(embed=embed)
        logger.info("Script inline validiert: '%s' via %s", script_name, source)
        return

    # Cache-Miss → API-Suche starten
    logger.info("Script '%s' inline nicht gefunden, suche auf botcscripts.com", script_name)
    async with channel.typing():
        results = await search_scripts(script_name, limit=5)

    session.touch()

    if results:
        session.pending_script_choices = results
        embed = _build_script_choice_embed(results)
        await channel.send(
            f"Ich habe **{script_name}** in der Datenbank gesucht:",
            embed=embed,
        )
    else:
        session.pending_script_upload = True
        await channel.send(
            f"**{script_name}** wurde nicht in der Datenbank gefunden.\n"
            "Du kannst die **Script-JSON als Datei** hochladen oder **'skip'** schreiben."
        )


async def _resolve_script(session, channel: discord.DMChannel) -> bool:
    """Resolved das Script via Cache/API. Gibt True zurück wenn bereit."""
    if session.fields.get("is_free_choice"):
        return True

    script_name = session.fields.get("script")
    if not script_name:
        return True

    session.touch()
    script_data, source = lookup_script(script_name)

    if source in ("base", "cache", "cache_stale"):
        return True

    logger.info("Script '%s' nicht im Cache, suche auf botcscripts.com", script_name)

    async with channel.typing():
        results = await search_scripts(script_name, limit=5)

    session.touch()

    if not results:
        session.pending_script_upload = True
        await channel.send(
            f"Ich konnte **{script_name}** nicht auf botcscripts.com finden.\n\n"
            "Du kannst:\n"
            "• Die **Script-JSON als Datei** hochladen (Anhang senden)\n"
            "• **'skip'** schreiben um ohne Script-Details fortzufahren"
        )
        return False

    session.pending_script_choices = results
    embed = _build_script_choice_embed(results)
    await channel.send(embed=embed)
    return False


def _select_script_choice(session, idx: int) -> dict:
    """Wählt ein Script aus den Suchergebnissen und cached es. Returns das Script-Data dict."""
    choices = session.pending_script_choices
    chosen = choices[idx]
    session.fields["script"] = chosen["name"]
    data = {
        "name": chosen["name"],
        "author": chosen.get("author", ""),
        "version": chosen.get("version", ""),
        "botcscripts_id": chosen.get("botcscripts_id", ""),
        "characters": chosen.get("characters", []),
        "url": chosen.get("url", ""),
        "source": "botcscripts",
    }
    cache_script(chosen["name"], data)
    session.pending_script_choices = None
    logger.info("Script ausgewählt: '%s'", chosen["name"])
    return data


async def _handle_script_choice(session, message: discord.Message, channel) -> str | None:
    """Verarbeitet Input im Script-Auswahl-Modus.

    Unterstützt:
    - Nummer (1-5) → Script auswählen
    - "custom"/"homebrew" → Upload-Flow
    - "skip" → Überspringen
    - Natürliche Sprache ("ich möchte die von Lau", "mehr infos zu 3") → Haiku hilft
    - Fragen zu den Ergebnissen → Info anzeigen

    Returns: Fehlertext, oder None bei Erfolg (Script ausgewählt).
    """
    choices = getattr(session, "pending_script_choices", None)
    if not choices:
        return "Keine Skript-Auswahl ausstehend."

    text = message.content.strip()
    text_lower = text.lower()

    # Skip
    if text_lower in ("skip", "überspringen", "s"):
        session.pending_script_choices = None
        return None

    # Custom/Homebrew → Upload
    if text_lower in ("custom", "homebrew", "eigenes", "custom script", "homebrew script"):
        session.pending_script_choices = None
        session.pending_script_upload = True
        return "upload_requested"

    # Direkte Nummer
    try:
        idx = int(text_lower) - 1
        if 0 <= idx < len(choices):
            return None  # Erfolg, wird vom Caller mit _select_script_choice behandelt
        else:
            return f"Bitte wähle 1-{len(choices)}."
    except ValueError:
        pass

    # Natürliche Sprache → prüfe ob eine Auswahl oder Frage gemeint ist
    # Infos zu einer bestimmten Nummer?
    for i, choice in enumerate(choices):
        markers = [str(i + 1), choice["name"].lower()]
        author = (choice.get("author") or "").lower()
        if author:
            markers.append(author)

        if any(m in text_lower for m in markers):
            if any(w in text_lower for w in ("info", "mehr", "detail", "charakter", "demon", "zeig", "was ist")):
                # User will Infos zu diesem Script → Embed zeigen
                embed = _build_script_info_embed(choice)
                await channel.send(embed=embed)
                return "info_shown"  # Bleibt im Auswahl-Modus

            if any(w in text_lower for w in ("möchte", "nehme", "wähle", "das", "diese", "von ")):
                # User wählt dieses Script
                _select_script_choice(session, i)
                return None  # Erfolg

    return f"Antworte mit 1-{len(choices)}, 'custom' für eigenes Script, oder 'skip'.\nDu kannst auch fragen: 'Mehr Infos zu 3?' oder 'Welche Demons sind in 2?'"


async def _handle_script_upload(session, message: discord.Message) -> tuple[bool, str]:
    """Verarbeitet Script-JSON-Upload. Returns (success, response_text)."""
    session.touch()
    text = message.content.strip().lower()

    if text in ("skip", "überspringen", "s"):
        session.pending_script_upload = False
        return True, ""

    if not message.attachments:
        return False, "Bitte sende die Script-JSON als Datei (.json) oder 'skip'."

    attachment = message.attachments[0]
    if not attachment.filename.endswith(".json"):
        return False, f"**{attachment.filename}** ist keine JSON-Datei."

    try:
        raw_bytes = await attachment.read()
        data = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Script-Upload JSON-Fehler: %s", e)
        return False, "Die Datei enthält kein gültiges JSON."

    parsed, error = validate_script_json(data)
    if error:
        return False, error

    script_name = parsed["name"]
    if script_name == "Custom Script" and session.fields.get("script"):
        script_name = session.fields["script"]
        parsed["name"] = script_name

    session.fields["script"] = script_name
    cache_script(script_name, parsed)
    session.pending_script_upload = False
    return True, f"✅ **{script_name}** hochgeladen ({len(parsed['characters'])} Charaktere)!"


# ── Review Input ─────────────────────────────────────────────────────────────


def _get_field_by_number(number: int) -> tuple[str, str] | None:
    if 1 <= number <= len(REVIEW_FIELDS):
        return REVIEW_FIELDS[number - 1]
    return None


async def _handle_review_input(session, message: discord.Message, channel) -> str | None:
    """Verarbeitet Input im Review. Returns: None=Übersicht neu, 'confirm', 'waiting_edit', 'back_to_conversation', oder Fehlertext."""
    session.touch()
    text = message.content.strip()
    text_lower = text.lower()

    if text_lower in CONFIRM_KEYWORDS:
        session.pending_review = False
        return "confirm"

    # Nummer → Feld-Edit
    try:
        number = int(text_lower)
        field_info = _get_field_by_number(number)
        if field_info:
            key, label = field_info
            session.pending_field_edit = key
            await channel.send(f"Was soll der neue Wert für **{label}** sein?")
            return "waiting_edit"
        else:
            return f"Bitte wähle 1-{len(REVIEW_FIELDS)}."
    except ValueError:
        pass

    # Freitext → Haiku-Korrektur
    async with channel.typing():
        response = await call_haiku(session, f"Der User möchte ändern: {text}\nPasse die Felder an, action='done'.")

    footer = _cost_footer(session)
    if response is None:
        return "Fehler bei der Verarbeitung."

    haiku_msg = response.get("message", "")
    action = response.get("action", "ask")

    if haiku_msg:
        msg = f"{haiku_msg}\n{footer}" if footer else haiku_msg
        await channel.send(msg)

    if action == "ask":
        session.pending_review = False
        return "back_to_conversation"

    return None  # done → Übersicht erneut


async def _handle_field_edit(session, message: discord.Message) -> None:
    """Verarbeitet direkte Feld-Eingabe."""
    session.touch()
    key = session.pending_field_edit
    session.pending_field_edit = None
    value = message.content.strip()

    if key == "camera":
        if value.lower() in ("keine pflicht", "optional", "egal"):
            value = None
        else:
            value = value.lower() in ("an", "ja", "on", "true", "yes", "pflicht")
    elif key == "is_casual" or key == "is_recorded":
        value = value.lower() in ("ja", "yes", "true", "an")
    elif key == "duration_minutes":
        try:
            value = int(float(value.replace("h", "").replace("std", "").strip()) * 60)
        except ValueError:
            try:
                value = int(value)
            except ValueError:
                pass
    elif key == "max_players":
        try:
            value = int(value)
        except ValueError:
            pass

    session.fields[key] = value


# ── Views ────────────────────────────────────────────────────────────────────


class ConfirmEventView(discord.ui.View):
    """Erstellen/Abbrechen Buttons nach der finalen Vorschau."""

    def __init__(self, cog: "HostCommand", session, dm_channel):
        super().__init__(timeout=300)
        self.cog = cog
        self.session = session
        self.dm_channel = dm_channel

    @discord.ui.button(label="Erstellen", emoji="✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()

        fields = self.session.fields
        label = self.session.label
        is_free = bool(fields.get("is_free_choice"))
        emoji = get_label_emoji(label, is_free_choice=is_free)

        start_ts = _parse_start_time(fields.get("start_time") or "")
        if start_ts is None:
            await interaction.followup.send("Fehler: Termin konnte nicht verarbeitet werden. Starte mit `/host` neu.")
            end_session(self.session.user_id)
            return

        duration = fields.get("duration_minutes") or 150
        end_ts = start_ts + (duration * 60)

        title = fields.get("title") or "BotC Event"
        if emoji:
            title = f"{emoji} {title}"

        script_display = fields.get("script") or "-"
        if is_free:
            script_display = "Freie Skriptwahl"
        elif fields.get("script_version"):
            script_display += f" (v{fields['script_version']})"

        extras = []
        if fields.get("co_storyteller"):
            extras.append(f"Co-ST: {fields['co_storyteller']}")
        if fields.get("camera") is not None:
            cam = "an" if fields["camera"] is True else "aus"
            extras.append(f"Kamera: {cam}")
        elif fields.get("camera") is None:
            extras.append("Kamera: keine Pflicht")
        if fields.get("max_players"):
            extras.append(f"Max Spieler: {fields['max_players']}")
        if fields.get("duration_minutes"):
            h, m = divmod(fields["duration_minutes"], 60)
            extras.append(f"Dauer: {h}h {m:02d}min" if h else f"Dauer: {m}min")

        event_data = {
            "title": title,
            "description": fields.get("description"),
            "storyteller": fields.get("storyteller") or "-",
            "script": script_display,
            "level": fields.get("level") or "Alle",
            "timestamp": start_ts,
            "end_timestamp": end_ts,
            "additional_info": "\n".join(extras) if extras else None,
            "creator_id": self.session.user_id,
            "creator_name": self.session.user_display_name,
        }

        event_cog = self.cog.bot.cogs.get("EventCommands")
        if not event_cog:
            await interaction.followup.send("Fehler: EventCommands-Cog nicht geladen.")
            end_session(self.session.user_id)
            return

        event_channel = self.cog.bot.get_channel(self.session.event_channel_id)
        if not event_channel:
            await interaction.followup.send("Fehler: Event-Channel nicht gefunden.")
            end_session(self.session.user_id)
            return

        try:
            msg = await event_cog.post_event(event_channel, event_data)
            await interaction.followup.send(f"Event erstellt! 🎉\n{msg.jump_url}")
            logger.info("Event via /host erstellt: '%s' (msg_id=%s)", title, msg.id)
        except Exception as e:
            logger.error("Fehler beim Event-Posten: %s", e)
            await interaction.followup.send(f"Fehler: {e}")

        end_session(self.session.user_id)

    @discord.ui.button(label="Abbrechen", emoji="❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        end_session(self.session.user_id)
        await interaction.response.send_message("Event-Erstellung abgebrochen.")

    async def on_timeout(self):
        end_session(self.session.user_id)
        try:
            await self.dm_channel.send("⏰ Bestätigung abgelaufen. Starte mit `/host` neu.")
        except Exception:
            pass


# ── Cog ──────────────────────────────────────────────────────────────────────


class HostCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="host",
        description="Starte die Event-Erstellung — der Bot führt dich per DM durch den Prozess"
    )
    async def host(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Nur in Servern nutzbar.", ephemeral=True)
            return

        cfg = get_guild_config(guild.id)
        event_channel_id = cfg.get("event_channel_id")
        if not event_channel_id:
            await interaction.response.send_message(
                "Kein Event-Channel konfiguriert. Ein Admin muss `/set_event_channel` ausführen.",
                ephemeral=True,
            )
            return

        event_channel = self.bot.get_channel(event_channel_id)
        if not event_channel:
            await interaction.response.send_message("Event-Channel nicht gefunden.", ephemeral=True)
            return

        if has_active_session(interaction.user.id):
            await interaction.response.send_message(
                "Du hast bereits eine aktive Event-Erstellung. "
                "Schreibe **abbrechen** in den DMs um sie zu beenden.",
                ephemeral=True,
            )
            return

        session = start_session(
            user_id=interaction.user.id,
            guild_id=guild.id,
            guild_name=guild.name,
            event_channel_id=event_channel_id,
            user_display_name=interaction.user.display_name,
        )

        await interaction.response.send_message(
            "Check deine DMs! 📩",
            ephemeral=True,
        )

        try:
            dm_channel = await interaction.user.create_dm()
            await dm_channel.send(
                f"Hey {interaction.user.display_name}! 👋\n"
                f"Lass uns ein Event für **{guild.name}** erstellen.\n"
                f"Beschreib mir dein Event — z.B. Skript, Termin, Level, ob du ST bist, etc.\n"
                f"Du kannst alles in einer Nachricht schreiben oder Stück für Stück.\n"
                f"-# Session läuft 5 Minuten · 'abbrechen' zum Beenden"
            )
            logger.info("/host: user=%s, guild=%s", interaction.user, guild.name)
        except discord.Forbidden:
            await interaction.followup.send(
                "Ich kann dir keine DM senden. Aktiviere DMs von Server-Mitgliedern.",
                ephemeral=True,
            )
            end_session(interaction.user.id)

    async def _show_review(self, session, channel, haiku_message: str = ""):
        """Zeigt das Review-Embed."""
        session.pending_review = True
        footer = _cost_footer(session)

        if haiku_message:
            msg = f"{haiku_message}\n{footer}" if footer else haiku_message
            await channel.send(msg)

        embed = _build_review_embed(session)
        await channel.send(embed=embed)

    async def _show_final_preview(self, session, channel):
        """Zeigt die finale Vorschau mit Buttons."""
        session.label = compute_label(session.fields)
        preview = _build_preview_embed(session)
        view = ConfirmEventView(self, session, channel)
        footer = _cost_footer(session)

        content = "**Finale Vorschau:**"
        if footer:
            content = f"{content}\n{footer}"
        await channel.send(content=content, embed=preview, view=view)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not isinstance(message.channel, discord.DMChannel):
            return
        if message.author.bot:
            return

        session = get_session(message.author.id)

        if session is None:
            if was_recently_expired(message.author.id):
                await message.channel.send(
                    "⏰ Deine Session ist abgelaufen (5 Min Inaktivität). "
                    "Starte mit `/host` in einem Server-Channel neu."
                )
            return

        session.touch()

        # Abbrechen
        if message.content.strip().lower() in CANCEL_KEYWORDS:
            end_session(session.user_id)
            await message.channel.send("Event-Erstellung abgebrochen. ✌️")
            return

        async with session._lock:
            await self._process_message(session, message)

    async def _process_message(self, session, message: discord.Message):
        channel = message.channel

        # Feld-Edit ausstehend?
        if getattr(session, "pending_field_edit", None):
            await _handle_field_edit(session, message)
            embed = _build_review_embed(session)
            await channel.send(content="✅ Aktualisiert!", embed=embed)
            return

        # Script-Upload ausstehend?
        if getattr(session, "pending_script_upload", False):
            success, text = await _handle_script_upload(session, message)
            if not success:
                await channel.send(text)
                return
            if text:
                await channel.send(text)
            # Script-Info anzeigen
            name = session.fields.get("script", "")
            script_data, _ = lookup_script(name)
            if script_data:
                await channel.send(embed=_build_script_info_embed(script_data))
            if getattr(session, "_pending_done_after_script", False):
                session._pending_done_after_script = False
                await self._show_review(session, channel)
            else:
                await channel.send("Skript validiert! Lass uns mit den restlichen Details weitermachen.")
            return

        # Script-Auswahl ausstehend?
        if getattr(session, "pending_script_choices", None):
            result = await _handle_script_choice(session, message, channel)

            if result == "info_shown":
                return  # Bleibt im Auswahl-Modus

            if result == "upload_requested":
                await channel.send(
                    "Kein Problem! Sende mir die **Script-JSON als Datei** (.json) oder 'skip'."
                )
                return

            if result is not None:
                # Fehlertext
                await channel.send(result)
                return

            # Erfolg → direkte Nummer oder natürliche Sprache
            # Wenn _select_script_choice noch nicht aufgerufen wurde (direkte Nummer)
            choices = getattr(session, "pending_script_choices", None)
            if choices:
                try:
                    idx = int(message.content.strip()) - 1
                    _select_script_choice(session, idx)
                except (ValueError, IndexError):
                    pass

            name = session.fields.get("script", "")
            script_data, _ = lookup_script(name)
            if script_data:
                await channel.send(f"✅ **{name}** ausgewählt!")
                embed = _build_script_info_embed(script_data)
                await channel.send(embed=embed)

            # Wenn wir aus dem done-Flow kamen → Review zeigen, sonst weiter mit Konversation
            if getattr(session, "_pending_done_after_script", False):
                session._pending_done_after_script = False
                await self._show_review(session, channel)
            else:
                await channel.send("Skript validiert! Lass uns mit den restlichen Details weitermachen.")
            return

        # Review-Modus?
        if getattr(session, "pending_review", False):
            result = await _handle_review_input(session, message, channel)
            if result == "confirm":
                ready = await _resolve_script(session, channel)
                if ready:
                    await self._show_final_preview(session, channel)
                return
            elif result == "waiting_edit":
                return
            elif result == "back_to_conversation":
                return
            elif result is None:
                embed = _build_review_embed(session)
                await channel.send(embed=embed)
                return
            else:
                await channel.send(result)
                return

        # Normaler Konversations-Flow
        async with channel.typing():
            response = await call_haiku(session, message.content)

        if response is None:
            await channel.send("Fehler bei der Verarbeitung. Versuche es nochmal oder `/host` neu.")
            return

        action = response.get("action", "ask")
        haiku_message = response.get("message", "")
        footer = _cost_footer(session)

        if action == "done":
            # Haiku-Nachricht senden
            if haiku_message:
                plain, embed = _parse_haiku_to_embed(haiku_message)
                if embed:
                    if footer:
                        embed.set_footer(text=footer.replace("-# 💰 ", "💰 "))
                    await channel.send(embed=embed)
                else:
                    msg = f"{haiku_message}\n{footer}" if footer else haiku_message
                    await channel.send(msg)

            # Script inline validieren bevor Review
            await _validate_script_inline(session, channel)
            # Wenn Script-Auswahl/Upload gestartet → merken dass Review danach kommen soll
            if getattr(session, "pending_script_choices", None) or getattr(session, "pending_script_upload", False):
                session._pending_done_after_script = True
                return
            # Alle Felder komplett + Script validiert → Review
            await self._show_review(session, channel)

        elif action == "refuse":
            embed = discord.Embed(
                title="⚠️ Off-Topic",
                description=haiku_message,
                color=ERROR_COLOR,
            )
            embed.set_footer(text="Ich kann dir nur bei der Event-Erstellung helfen.")
            await channel.send(embed=embed)

        else:
            # ask / explain
            if haiku_message:
                # Versuche strukturierte Antwort als Embed zu parsen
                plain, embed = _parse_haiku_to_embed(haiku_message)
                if embed:
                    if footer:
                        embed.set_footer(text=footer.replace("-# 💰 ", "💰 "))
                    await channel.send(embed=embed)
                else:
                    msg = f"{haiku_message}\n{footer}" if footer else haiku_message
                    await channel.send(msg)

            # Inline Script-Validierung nach jedem Haiku-Call
            await _validate_script_inline(session, channel)


async def setup(bot: commands.Bot):
    await bot.add_cog(HostCommand(bot))
