"""Slash-Command /botc — Event-Erstellung via DM.

5-Schritte-Flow:
1) Eingabe: Haiku sammelt 5 Pflichtfelder (script, time, ST, level, casual)
2) Script-Validierung: Cache/Base oder botcscripts.com Suche
3) Titel & Beschreibung: Haiku generiert, User kann per Freitext anpassen
4) Summary: 1 Embed mit allem + Buttons (Erstellen/Abbrechen)
5) Event erstellen
"""

import io
import json
import logging
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from config import get_guild_config
from logic.conversation import (
    call_haiku,
    end_session,
    generate_title_and_description,
    get_session,
    has_active_session,
    interpret_final_review,
    interpret_script_choice,
    interpret_script_preview,
    start_session,
    was_recently_expired,
)
from logic.label import (
    FREE_CHOICE_DESCRIPTION,
    LABEL_DESCRIPTION,
    LABEL_EMOJI,
    analyze_script_complexity,
    build_title_prefix,
    compute_label,
    get_label_emoji,
)
from logic.botcscripts import search_scripts
from logic.script_cache import (
    cache_script,
    load_characters,
    lookup_script,
    validate_script_json,
)
from logic.event_builder import build_event_embed
from logic.script_image import generate_script_image

logger = logging.getLogger(__name__)

BERLIN_TZ = ZoneInfo("Europe/Berlin")
BOT_COLOR = 0x5865F2

# Base3 Sonderbehandlung
BASE3_THUMBNAILS = {
    "trouble_brewing": "https://wiki.bloodontheclocktower.com/images/a/a1/Logo_trouble_brewing.png",
    "bad_moon_rising": "https://wiki.bloodontheclocktower.com/images/1/10/Logo_bad_moon_rising.png",
    "sects_and_violets": "https://wiki.bloodontheclocktower.com/images/4/43/Logo_sects_and_violets.png",
}
BASE3_SCRIPT_URLS = {
    "trouble_brewing": "https://www.botcscripts.com/script/133/1.0.0",
    "bad_moon_rising": "https://www.botcscripts.com/script/135/1.0.0",
    "sects_and_violets": "https://www.botcscripts.com/script/134/1.0.0",
}
BASE3_FULL_NAMES = {
    "trouble_brewing": "Trouble Brewing",
    "bad_moon_rising": "Bad Moon Rising",
    "sects_and_violets": "Sects and Violets",
}

GERMAN_DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _format_termin_german(start_time_str: str, duration_minutes: int) -> str:
    """Formatiert start_time + duration als deutsches Datum.

    z.B. 'Dienstag, der 24.03.2026, 15:00 Uhr – 17:30 Uhr'
    """
    ts = _parse_start_time(start_time_str) if start_time_str else None
    if not ts:
        return start_time_str or "-"
    dt = datetime.fromtimestamp(ts, tz=BERLIN_TZ)
    day_name = GERMAN_DAYS[dt.weekday()]
    date_str = dt.strftime("%d.%m.%Y")
    start_str = dt.strftime("%H:%M")
    end_dt = dt + timedelta(minutes=duration_minutes)
    end_str = end_dt.strftime("%H:%M")
    return f"{day_name}, der {date_str}, {start_str} Uhr \u2013 {end_str} Uhr"

CANCEL_KEYWORDS = {"abbrechen", "cancel", "stop"}
CONFIRM_KEYWORDS = {"ok", "fertig", "bestätigen", "confirm", "ja", "yes", "passt", "gut"}

# ── Hilfszeilen (klein + kursiv) ──────────────────────────────────────────────
# Discord: "-#" = Subtext (klein), "*...*" = kursiv.
# Werden unter Bot-Nachrichten angehängt, damit der User weiß, was möglich ist.

HINT_HAIKU_CHAT = (
    "-# *Schreib frei in eigenen Worten — ich ziehe die Details selbst raus. "
    "Beispiel: \"Samstag 19 Uhr BMR, Level Erfahren, casual\".*"
)
HINT_SCRIPT_CHOICE = (
    "-# *Antworte mit einer **Nummer** (1–5), einem **Skriptnamen**, `preview N` "
    "für Details, einem neuen **Suchbegriff**, einer **Script-JSON** als Anhang, "
    "oder `skip`.*"
)
HINT_SCRIPT_PREVIEW = (
    "-# *Wähle eine **Nummer**, schreibe `zurück` für die Suchergebnisse, oder "
    "nenne den Skriptnamen frei.*"
)
HINT_SCRIPT_UPLOAD = (
    "-# *Hänge die **.json-Datei** als Anhang an — oder schreibe `skip`.*"
)
HINT_SCRIPT_SEARCH_RETRY = (
    "-# *Versuch einen anderen **Suchbegriff** — oder schreibe `abbrechen`.*"
)
HINT_MANUAL_RATING = (
    "-# *Schreib einfach `grün`, `gelb` oder `rot` — oder nutze das passende Emoji.*"
)
HINT_SCRIPT_EDIT_MODE = (
    "-# *Antworte mit einer **Nummer** (1–4) oder tippe direkt einen **Suchbegriff** "
    "ein — freie Sprache geht auch.*"
)
HINT_VERSION_CHOICES = (
    "-# *Gib die **Nummer** der gewünschten Version ein.*"
)
HINT_FINAL_REVIEW = (
    "-# *Du kannst frei sprechen — z.B. \"Kamera aus, Level Profi\" oder "
    "\"Termin Samstag 20 Uhr\". Einzelne Felder auch per **Nummer**.*"
)
HINT_FIELD_EDIT_GENERIC = (
    "-# *Schreib einfach den neuen Wert in eigenen Worten.*"
)
HINT_FIELD_EDIT_LEVEL = "-# *Erlaubt: `Neuling`, `Erfahren`, `Profi`, `Alle`.*"
HINT_FIELD_EDIT_CAMERA = "-# *Erlaubt: `Pflicht`, `Aus`, `Keine Pflicht`.*"
HINT_FIELD_EDIT_MAX_PLAYERS = "-# *Gib eine **Zahl** ein, z.B. `12`.*"
HINT_FIELD_EDIT_CO_ST = "-# *Name frei eingeben — oder `keiner` um zu entfernen.*"
HINT_FIELD_EDIT_LABELS = (
    "-# *Beispiele: `casual ja`, `academy nein`. Mehrere auch kombinierbar.*"
)
HINT_FIELD_EDIT_START_TIME = (
    "-# *Beispiele: `Samstag 20 Uhr`, `2026-03-25 20:00`, `180` (nur Dauer in Min), "
    "`2026-03-25 20:00 180min` (beides).*"
)
HINT_ALT_RESTORE = (
    "-# *`alt` stellt deinen vorherigen Titel und deine Beschreibung wieder her.*"
)
HINT_ERROR_RETRY = (
    "-# *Versuch es nochmal — oder schreibe `abbrechen` zum Beenden.*"
)

# ── Einheitliche Error-Messages ──────────────────────────────────────────────
# Wir nutzen \u26a0\ufe0f als konsistentes Error-Prefix, damit User Fehler auf
# einen Blick erkennen. Fettdruck nur auf Schlüsselwörter.

ERR_PREFIX = "\u26a0\ufe0f"  # ⚠️

def _err(msg: str, hint: str | None = None) -> str:
    """Baut eine einheitliche Fehlermeldung mit optionalem Hint darunter."""
    text = f"{ERR_PREFIX} {msg}"
    if hint:
        text += f"\n{hint}"
    return text

# Zentraler Refuse-Text — identisch bei Off-Topic UND Injection-/Tricksversuchen.
REFUSE_MESSAGE = (
    "Das hat nichts mit der Event-Erstellung zu tun. Bleib bitte beim Thema: "
    "Beschreibe dein Event (Skript, Termin, Level, casual ja/nein) oder "
    "schreibe `abbrechen`, um die Session zu beenden."
)

SCRIPT_CHANGE_PROMPT = (
    "Du willst ein anderes Skript spielen. Sag mir gerne, nach welchem Suchbegriff "
    "ich in der Datenbank suchen soll. Alternativ:\n"
    "**1** \u2014 In der Datenbank suchen\n"
    "**2** \u2014 Selbst einen Namen eingeben\n"
    "**3** \u2014 Script-JSON hochladen\n"
    "**4** \u2014 Freie Skriptwahl\n"
    f"{HINT_SCRIPT_EDIT_MODE}"
)

MAX_CALLS = 20


def _get_base3_key(script_name: str) -> str | None:
    """Gibt den Base3-Key ('trouble_brewing' etc.) zurück oder None."""
    from logic.script_cache import lookup_base_script
    base = lookup_base_script(script_name or "")
    if not base:
        return None
    # Key aus dem Namen ableiten
    name = base.get("name", "")
    for key, full in BASE3_FULL_NAMES.items():
        if full == name:
            return key
    return None

_SEARCH_PREFIXES = re.compile(
    r"^(?:such(?:e|t)?\s*(?:mal\s+)?(?:nach|für|lieber\s+nach)?|"
    r"zeig(?:\s+mir)?|find(?:e)?|gib\s+mir|ich\s+will|ich\s+möchte|"
    r"nimm|wähle?|nehme?)\s+",
    re.IGNORECASE,
)


def _extract_search_term(text: str) -> str:
    """Entfernt natürliche Sprach-Präfixe und gibt den reinen Suchbegriff zurück."""
    clean = _SEARCH_PREFIXES.sub("", text.strip())
    return clean.strip() or text.strip()
REQUIRED_FIELDS = ["script", "start_time", "storyteller", "level", "is_casual"]

SUMMARY_FIELDS = [
    ("title", "Titel"),                    # 1
    ("script", "Skript"),                  # 2
    ("description", "Beschreibung"),       # 3
    ("storyteller", "Storyteller:in"),      # 4
    ("co_storyteller", "Co-Storyteller:in"),# 5
    ("level", "Level"),                    # 6
    ("_labels", "Labels"),                 # 7
    ("camera", "Kamera"),                  # 8
    ("max_players", "Max Spieler"),        # 9
    ("start_time", "Termin"),              # 10
]

# Keywords für natürliche Sprache → Feld-Erkennung
FIELD_KEYWORDS = {
    "titel": "title", "title": "title",
    "beschreibung": "description", "desc": "description",
    "storyteller": "storyteller",
    "skript": "script", "script": "script",
    "level": "level",
    "termin": "start_time", "zeit": "start_time", "uhrzeit": "start_time", "datum": "start_time",
    "dauer": "duration_minutes",
    "spieler": "max_players", "max": "max_players",
    "kamera": "camera", "cam": "camera",
    "co-st": "co_storyteller", "cost": "co_storyteller", "co st": "co_storyteller",
    "casual": "is_casual",
}

# Reverse: field key → label
FIELD_LABELS = {key: label for key, label in SUMMARY_FIELDS}


def _cost_footer(session) -> str:
    if os.getenv("ENV") != "dev":
        return ""
    return (
        f"💰 {session.call_count} Calls · "
        f"{session.total_input_tokens} in / {session.total_output_tokens} out · "
        f"${session.total_cost_usd:.4f}"
    )


def _fmt(key, value):
    if value is None:
        return {"camera": "keine Pflicht", "co_storyteller": "Nicht möglich", "is_casual": "Nein"}.get(key, "-")
    if key == "camera":
        return "Pflicht" if value is True else ("Aus" if value is False else "keine Pflicht")
    if key == "is_casual":
        return "Ja 🕊️" if value else "Nein"
    if key == "duration_minutes":
        h, m = divmod(int(value), 60)
        return f"{h}h {m:02d}min" if h else f"{m}min"
    return str(value)



def _parse_start_time(s):
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"]:
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=BERLIN_TZ).timestamp())
        except ValueError:
            continue
    return None


# ── Embeds ───────────────────────────────────────────────────────────────────




def _build_script_choice_embed(script_name, results):
    embed = discord.Embed(
        title=f"Skript-Suche: \"{script_name}\"",
        color=BOT_COLOR,
    )
    for i, r in enumerate(results, 1):
        au = r.get("author") or "?"
        ve = r.get("version") or "?"
        ch = r.get("characters", [])
        cnt = f" · {len(ch)} Chars" if ch else ""
        stype = r.get("script_type", "")
        tag = f" · {stype}" if stype and stype != "Full" else ""
        embed.add_field(name=f"{i}. {r['name']}", value=f"von {au} · v{ve}{cnt}{tag}", inline=False)
    embed.set_footer(text="Quelle: botcscripts.com")
    return embed


SCRIPT_CHOICE_HELP = (
    "Ist dein Skript dabei?\n"
    f"{HINT_SCRIPT_CHOICE}"
)


# ── View ─────────────────────────────────────────────────────────────────────


class SummaryView(discord.ui.View):
    def __init__(self, cog, session, dm_channel):
        super().__init__(timeout=300)
        self.cog = cog
        self.session = session
        self.dm_channel = dm_channel

    @discord.ui.button(label="Erstellen", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction:
            await interaction.response.defer()
        self.stop()

        # reply helper: works with interaction or DM channel
        async def _reply(msg):
            if interaction:
                await interaction.followup.send(msg)
            else:
                await self.dm_channel.send(msg)

        f = self.session.fields
        is_free = bool(f.get("is_free_choice"))
        self.session.label = compute_label(f)
        emoji = get_label_emoji(self.session.label, is_free_choice=is_free)

        start_ts = _parse_start_time(f.get("start_time") or "")
        if not start_ts:
            await _reply(_err("Der Termin konnte nicht verarbeitet werden."))
            end_session(self.session.user_id)
            return

        duration = f.get("duration_minutes") or 150
        title = f.get("title") or "BotC Event"
        prefix = build_title_prefix(f)
        if prefix:
            title = f"{prefix} {title}"

        script_display = "Freie Skriptwahl" if is_free else (f.get("script") or "-")

        # Script-Daten
        script_characters, script_url = [], None
        script_author, script_version = "", ""
        botcscripts_id = ""
        script_source = "base"
        script_content = None
        selected_sd = getattr(self.session, "_selected_script_data", None)
        if not is_free and f.get("script"):
            sd, src = lookup_script(f["script"])
            # Bevorzuge _selected_script_data (frisch von botcscripts.com)
            sd = selected_sd or sd
            if sd:
                script_characters = sd.get("characters", [])
                script_author = sd.get("author", "")
                script_version = sd.get("version", "")
                botcscripts_id = sd.get("botcscripts_id", "")
                script_source = sd.get("source", src)
                bid = botcscripts_id or sd.get("botcscripts_id")
                if bid and script_version:
                    script_url = f"https://www.botcscripts.com/script/{bid}/{script_version}"
                # Bei Uploads: Content im Event speichern (existiert sonst nirgends)
                if script_source == "upload":
                    script_content = sd.get("content")

        # Base3 Thumbnail
        b3key = _get_base3_key(f.get("script") or "")
        thumbnail_url = BASE3_THUMBNAILS.get(b3key, "") if b3key else ""
        if b3key and not script_url:
            script_url = BASE3_SCRIPT_URLS.get(b3key, "")

        event_data = {
            "title": title, "description": f.get("description"),
            "storyteller": f.get("storyteller") or "-",
            "co_storyteller": f.get("co_storyteller"),
            "script": script_display, "script_url": script_url,
            "script_author": script_author, "script_version": script_version,
            "script_characters": script_characters,
            "botcscripts_id": botcscripts_id,
            "script_source": script_source,
            "level": f.get("level") or "Alle",
            "camera": f.get("camera"), "max_players": f.get("max_players") or 12,
            "timestamp": start_ts, "end_timestamp": start_ts + duration * 60,
            "creator_id": self.session.user_id,
            "creator_name": self.session.user_display_name,
            "creator_avatar_url": self.session.user_avatar_url,
            "label": self.session.label,
            "thumbnail_url": thumbnail_url,
        }
        if script_content:
            event_data["script_content"] = script_content

        event_cog = self.cog.bot.cogs.get("EventCommands")
        event_channel = self.cog.bot.get_channel(self.session.event_channel_id)
        if not event_cog or not event_channel:
            await _reply(_err("Event-System ist gerade nicht verfügbar."))
            end_session(self.session.user_id)
            return

        # Bild: Custom oder Auto-Skript-Bild
        script_file = None
        custom_image_url = getattr(self.session, "_custom_image_url", None)
        if custom_image_url:
            import aiohttp
            try:
                async with aiohttp.ClientSession() as http:
                    async with http.get(custom_image_url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            script_file = discord.File(io.BytesIO(data), filename="event_image.png")
            except Exception as e:
                logger.warning("Custom-Bild Fehler: %s", e)
        elif script_characters and not is_free and not b3key:
            try:
                sd, _ = lookup_script(f["script"])
                img = await generate_script_image(
                    f.get("script", ""), (sd or {}).get("author", ""),
                    script_characters, (sd or {}).get("version", ""),
                    content=(sd or {}).get("content"),
                )
                script_file = discord.File(img, filename="script.png")
            except Exception as e:
                logger.warning("Script-Bild Fehler: %s", e)

        # Edit-Modus: bestehendes Event updaten
        editing_msg_id = getattr(self.session, "editing_message_id", None)
        editing_ch_id = getattr(self.session, "editing_channel_id", None)

        if editing_msg_id and editing_ch_id:
            try:
                edit_channel = self.cog.bot.get_channel(editing_ch_id)
                if not edit_channel:
                    edit_channel = await self.cog.bot.fetch_channel(editing_ch_id)
                edit_msg = await edit_channel.fetch_message(editing_msg_id)

                # RSVP-Daten beibehalten
                from event_storage import get_event
                old_event = get_event(editing_msg_id) or {}
                event_data["accepted"] = old_event.get("accepted", [])
                event_data["declined"] = old_event.get("declined", [])
                event_data["tentative"] = old_event.get("tentative", [])

                # Termin geändert → Reminder zurücksetzen
                if start_ts != old_event.get("timestamp"):
                    event_data["reminded_15"] = False
                    event_data["reminded_5"] = False
                event_data["_event_channel_id"] = editing_ch_id

                # Embed + Bild updaten
                new_embed = build_event_embed(event_data)
                kwargs = {"embed": new_embed}
                if script_file:
                    kwargs["attachments"] = [script_file]
                await edit_msg.edit(**kwargs)

                # Storage updaten
                from event_storage import save_event
                save_event(editing_msg_id, event_data)

                await _reply(f"Event aktualisiert! ✏️\n{edit_msg.jump_url}")
            except Exception as e:
                logger.error("Edit-Fehler: %s", e)
                await _reply(_err(f"Beim Bearbeiten ist etwas schiefgelaufen: {e}"))
        else:
            # Neues Event erstellen
            try:
                msg = await event_cog.post_event(event_channel, event_data, script_image=script_file)
                await _reply(f"Event erstellt! 🎉\n{msg.jump_url}")
            except Exception as e:
                logger.error("Fehler: %s", e)
                await _reply(_err(f"Beim Erstellen ist etwas schiefgelaufen: {e}"))

        end_session(self.session.user_id)

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        end_session(self.session.user_id)
        await interaction.response.send_message("Event-Erstellung abgebrochen. ✌️")

    async def on_timeout(self):
        # Nur senden wenn Session noch aktiv ist (sonst wurde sie schon anderswo beendet)
        if get_session(self.session.user_id) is not None:
            end_session(self.session.user_id)
            try:
                await self.dm_channel.send(
                    "\u23f0 Session abgelaufen. Starte mit `/botc` neu."
                )
            except Exception:
                pass


# ── Cog ──────────────────────────────────────────────────────────────────────


class HostCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def create_edit_session(self, interaction, event_data, message_id):
        """Erstellt eine Edit-Session aus bestehenden Event-Daten."""
        guild = interaction.guild
        session = start_session(
            interaction.user.id, guild.id, guild.name,
            event_data.get("_event_channel_id") or interaction.channel_id,
            interaction.user.display_name,
            getattr(interaction.user.display_avatar, "url", ""),
        )
        # Event-Daten in Session-Felder übertragen
        session.fields["title"] = event_data.get("title", "")
        session.fields["description"] = event_data.get("description", "")
        session.fields["storyteller"] = event_data.get("storyteller", "")
        session.fields["co_storyteller"] = event_data.get("co_storyteller")
        session.fields["script"] = event_data.get("script", "")
        session.fields["level"] = event_data.get("level", "")
        session.fields["camera"] = event_data.get("camera")
        session.fields["max_players"] = event_data.get("max_players", 12)
        session.fields["is_casual"] = event_data.get("is_casual")
        session.fields["is_recorded"] = event_data.get("is_recorded")
        session.fields["is_academy"] = event_data.get("is_academy")
        session.fields["is_free_choice"] = event_data.get("is_free_choice")

        # Timestamp zurück in String konvertieren
        ts = event_data.get("timestamp")
        if ts:
            from datetime import datetime
            dt = datetime.fromtimestamp(ts, tz=BERLIN_TZ)
            session.fields["start_time"] = dt.strftime("%Y-%m-%d %H:%M")

        # Duration aus Timestamps berechnen
        end_ts = event_data.get("end_timestamp")
        if ts and end_ts:
            session.fields["duration_minutes"] = (end_ts - ts) // 60

        # Edit-Modus
        session.editing_message_id = message_id
        session.editing_channel_id = interaction.channel_id
        session.label = event_data.get("label")
        return session

    @app_commands.command(name="botc", description="Starte die Event-Erstellung per DM")
    async def host(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Nur in Servern nutzbar.", ephemeral=True)
            return

        cfg = get_guild_config(guild.id)
        eci = cfg.get("event_channel_id")
        if not eci or not self.bot.get_channel(eci):
            await interaction.response.send_message("Event-Channel nicht konfiguriert (`/set_event_channel`).", ephemeral=True)
            return

        if has_active_session(interaction.user.id):
            await interaction.response.send_message("Aktive Session läuft. Schreibe **abbrechen** in den DMs.", ephemeral=True)
            return

        session = start_session(
            user_id=interaction.user.id, guild_id=guild.id, guild_name=guild.name,
            event_channel_id=eci, user_display_name=interaction.user.display_name,
            user_avatar_url=interaction.user.display_avatar.url,
        )

        await interaction.response.send_message("Check deine DMs! 📩", ephemeral=True)

        try:
            dm = await interaction.user.create_dm()
            await dm.send(
                f"Hey {interaction.user.display_name}! 👋\n"
                f"Ich helfe dir, ein **BotC-Event** für **{guild.name}** zu erstellen. "
                f"Am Ende wird das Event im Event-Channel gepostet, und andere können sich anmelden.\n\n"
                f"Bevor es losgeht: Schau kurz in die **Serverregeln**, damit dein Event dazu passt.\n\n"
                f"Ich brauche von dir: **Skript**, **Termin**, **Storyteller**, **Level** und "
                f"ob die Runde **casual** ist. Alles andere (Dauer, Max. Spieler, Kamera, Co-ST …) "
                f"kannst du hinterher ergänzen.\n\n"
                f"Leg einfach los — erzähl mir in eigenen Worten, was du planst.\n"
                f"{HINT_HAIKU_CHAT}\n"
                f"-# *Session läuft 5 Min · schreibe `abbrechen` zum Beenden.*"
            )
        except discord.Forbidden:
            await interaction.followup.send("Kann keine DM senden.", ephemeral=True)
            end_session(interaction.user.id)

    async def _select_script(self, session, channel, chosen):
        """Wählt ein Script aus den Suchergebnissen, cached es, und geht zu Schritt 3."""
        had_title = bool(session.fields.get("title"))
        session.fields["script"] = chosen["name"]
        cache_data = {
            "name": chosen["name"], "author": chosen.get("author", ""),
            "version": chosen.get("version", ""),
            "botcscripts_id": chosen.get("botcscripts_id", ""),
            "characters": chosen.get("characters", []),
            "script_type": chosen.get("script_type", ""),
            "url": chosen.get("url", ""),
            "source": chosen.get("source", "botcscripts"),
        }
        # Content nur bei Uploads/Homebrews im Cache (botcscripts → per API neu holbar)
        if chosen.get("source") == "upload":
            cache_data["content"] = chosen.get("content", [])
        cache_script(chosen["name"], cache_data)

        session.pending_script_choices = None
        session._script_choice_return_to_summary = False

        # Komplexitäts-Analyse
        chars = chosen.get("characters", [])
        if chars:
            analysis = analyze_script_complexity(chars)
            session.fields["complexity_analysis"] = analysis
            session.label = compute_label(session.fields)

        # Skript-Info für Titel/Beschreibung-Step merken
        session._selected_script_data = chosen

        # Immer Titel/Beschreibung neu generieren — bei Retrigger mit Rückfrage
        if had_title:
            session._retrigger_proposal = True
        await self._show_final_review(session, channel)

    # ── Schritt 3: Titel & Beschreibung ──────────────────────────────

    def _build_char_list_by_team(self, char_ids: list[str], content_data: list | None = None) -> dict[str, list[str]]:
        """Gruppiert Charaktere nach Team und gibt {team: [namen]} zurück."""
        chars_db = load_characters()
        # Content-Daten als dict aufbereiten (id → entry)
        content_map = {}
        if content_data:
            for entry in content_data:
                if isinstance(entry, dict) and entry.get("id") and entry["id"] != "_meta":
                    content_map[entry["id"]] = entry

        teams = {"Townsfolk": [], "Outsider": [], "Minion": [], "Demon": []}
        for cid in char_ids:
            info = chars_db.get(cid, {})
            hw = content_map.get(cid, {})
            name = info.get("character_name") or hw.get("name") or cid
            team = info.get("character_type") or ""
            if not team and hw.get("team"):
                team = hw["team"].capitalize()
            if team not in teams:
                team = "Townsfolk"
            teams[team].append(name)
        return teams

    async def _show_script_preview(self, session, channel, scripts: list[dict], indices: list[int] = None):
        """Zeigt Script-Details als Embeds (Charaktere nach Teams).

        Args:
            indices: Original-Indizes (1-basiert) aus der Suchergebnis-Liste.
        """
        session._preview_scripts = scripts
        session._preview_indices = indices or list(range(1, len(scripts) + 1))
        session._pending_script_preview = True

        for i, script in enumerate(scripts):
            display_num = session._preview_indices[i] if i < len(session._preview_indices) else i + 1
            name = script.get("name", "?")
            author = script.get("author", "?")
            version = script.get("version", "?")
            chars = script.get("characters", [])
            content = script.get("content")

            embed = discord.Embed(title=f"{display_num} \u00b7 {name}", color=0xFDCB58)
            embed.add_field(name="Info", value=f"von {author} \u00b7 v{version} \u00b7 {len(chars)} Charaktere", inline=False)

            teams = self._build_char_list_by_team(chars, content)
            for team_name in ("Townsfolk", "Outsider", "Minion", "Demon"):
                names = teams.get(team_name, [])
                if names:
                    embed.add_field(name=team_name, value=f"```{', '.join(names)}```", inline=False)

            await channel.send(embed=embed)

        await channel.send(
            "W\u00e4hle ein Skript aus oder geh **zur\u00fcck** zur Liste.\n"
            f"{HINT_SCRIPT_PREVIEW}"
        )

    async def _show_final_review(self, session, channel, regenerate_title=True):
        """Zeigt den kombinierten Abschluss-Screen: Skript-Details + Event-Zusammenfassung."""
        session.pending_final_review = True
        # Clear ALL other states — wir sind jetzt im Final Review
        session.pending_title_description = False
        session.pending_summary = False
        session.pending_script_choices = None
        session.pending_script_upload = False
        session.pending_script_search = False
        session.pending_script_edit_mode = False
        session.pending_field_edit = None
        session._pending_script_preview = False
        session._preview_scripts = None
        session._pending_version_choices = None
        session._pending_manual_rating = False

        # Defaults setzen
        session.fields.setdefault("max_players", 12)
        session.fields.setdefault("duration_minutes", 150)

        # Script data
        script_name = session.fields.get("script")
        is_free = bool(session.fields.get("is_free_choice"))
        sd = getattr(session, "_selected_script_data", None)
        sd_lookup = None

        if script_name and not is_free:
            sd_lookup, _ = lookup_script(script_name)
            sd = sd or sd_lookup
            chars = (sd or {}).get("characters", [])
            if chars:
                analysis = analyze_script_complexity(chars)
                session.fields["complexity_analysis"] = analysis
                session.label = compute_label(session.fields)

        # Base3-Check
        base3_key = _get_base3_key(script_name) if script_name else None

        # Generate title/description if needed
        is_retrigger = getattr(session, "_retrigger_proposal", False)
        session._retrigger_proposal = False
        old_title = session.fields.get("title") if is_retrigger else None
        old_desc = session.fields.get("description") if is_retrigger else None

        if regenerate_title and (not session.fields.get("title") or is_retrigger):
            if base3_key:
                # Base3: Hardcoded title + description, kein LLM-Call
                full_name = BASE3_FULL_NAMES[base3_key]
                st = session.fields.get("storyteller") or session.user_display_name
                co = session.fields.get("co_storyteller")
                session.fields["title"] = f"{full_name} mit {st}" + (f" und {co}" if co else "")
                session.fields["description"] = f"Wir spielen klassisches {full_name} \U0001f60c Meldet euch an!"
                session._last_reasoning = ""
            else:
                async with channel.typing():
                    result = await generate_title_and_description(session)
                if result:
                    title, desc, reasoning = result
                    session.fields["title"] = title
                    session.fields["description"] = desc
                    session._last_reasoning = reasoning
                else:
                    script = session.fields.get("script") or "Event"
                    st = session.fields.get("storyteller") or session.user_display_name
                    co = session.fields.get("co_storyteller")
                    session.fields["title"] = f"{script} mit {st}" + (f" und {co}" if co else "")
                    session.fields["description"] = f"Wir spielen eine Runde {script}!"
                    session._last_reasoning = ""

        if is_retrigger:
            session._old_title = old_title
            session._old_desc = old_desc

        reasoning = getattr(session, "_last_reasoning", "")

        # Prefix + display
        prefix = build_title_prefix(session.fields)
        title_display = f"{prefix} {session.fields['title']}" if prefix else session.fields['title']

        analysis = session.fields.get("complexity_analysis") or {}
        rating = analysis.get("rating")
        rating_emoji = LABEL_EMOJI.get(rating, "") if rating else ""

        # Bei manuellem Script (nur Rating, keine Analyse): hardcoded Reasoning
        if analysis and len(analysis) == 1 and "rating" in analysis:
            rating_word_full = {"green": "gr\u00fcn", "yellow": "gelb", "red": "rot"}.get(rating, "")
            reasoning = f"Der Storyteller hat das Skript {rating_emoji} {rating_word_full} eingesch\u00e4tzt."

        EMBED_COLORS = {
            "green": 0x78B159, "yellow": 0xFDCB58, "red": 0xDD2E44,
            "hammer": 0xF4900C, "dove": 0x78B159,
        }
        embed_color = EMBED_COLORS.get(rating, 0xFDCB58)

        # -- Intro text --
        script_author = (sd or {}).get("author", "")
        script_version = (sd or {}).get("version", "")
        rating_word = {"green": "gr\u00fcn", "yellow": "gelb", "red": "rot", "hammer": "homebrew"}.get(rating, "")

        if base3_key:
            full_name = BASE3_FULL_NAMES[base3_key]
            intro_parts = [
                f"Klassisches **{full_name}** \u2014 da brauch ich nicht lange \u00fcberlegen. "
                "Schau trotzdem kurz dr\u00fcber:"
            ]
        else:
            intro_parts = [f"Ich hab das Skript f\u00fcr dich ausgew\u00e4hlt: **{script_name}**"]
            if script_author:
                intro_parts[0] += f" von **{script_author}**"
            if script_version:
                intro_parts[0] += f" **v{script_version}**"
            intro_parts[0] += "."
            if rating_word:
                intro_parts.append(f"Ich sch\u00e4tze das Skript {rating_emoji} **{rating_word}** ein.")
            intro_parts.append(
                "Ebenfalls habe ich einen Titel und eine Beschreibung f\u00fcr deine Veranstaltung erstellt. "
                "Aber ich bin nur ein Village Idiot und hab keine Ahnung, ob ich sober bin. "
                "Also schau lieber nochmal dr\u00fcber:"
            )

        if is_retrigger:
            intro_parts = [
                f"Neues Skript: **{script_name}**.",
                "Ich habe Titel und Beschreibung neu generiert. "
                "Du kannst die neuen \u00fcbernehmen oder **alt** schreiben, um bei den bisherigen zu bleiben:",
            ]

        intro_text = " ".join(intro_parts)

        # ── Single Embed: Event-Zusammenfassung ──
        char_ids = (sd or {}).get("characters", [])
        embed = discord.Embed(title="\U0001f4cb Event-Zusammenfassung", color=embed_color)

        # 1 · Titel (NOT inline)
        embed.add_field(name="1 \u00b7 Titel", value=f"```{title_display}```", inline=False)

        # 2 · Skript (inline)
        if base3_key:
            full_name = BASE3_FULL_NAMES[base3_key]
            script_url = BASE3_SCRIPT_URLS[base3_key]
            embed.add_field(
                name="2 \u00b7 Skript",
                value=f"[{full_name}]({script_url})",
                inline=True,
            )
        else:
            script_info = script_name or "Freie Wahl"
            if script_author:
                script_info += f" von {script_author}"
            if script_version:
                script_info += f" \u00b7 v{script_version}"
            if char_ids:
                script_info += f" \u00b7 {len(char_ids)} Charaktere"
            embed.add_field(name="2 \u00b7 Skript", value=f"```{script_info}```", inline=True)

        # Einschätzung (inline, als Zitat) — bei Base3 nicht anzeigen
        if reasoning and not base3_key:
            quote_lines = "\n".join(f"> {line}" for line in reasoning.split("\n"))
            embed.add_field(
                name=f"{rating_emoji} Einsch\u00e4tzung",
                value=quote_lines,
                inline=True,
            )

        # 3 · Beschreibung (NOT inline — zu lang für Inline)
        embed.add_field(name="3 \u00b7 Beschreibung", value=f"```{session.fields.get('description', '-')}```", inline=False)

        # 4 · Storyteller:in (inline)
        st = session.fields.get("storyteller") or "-"
        embed.add_field(name="4 \u00b7 Storyteller:in", value=f"```{st}```", inline=True)

        # 5 · Co-Storyteller:in (inline)
        co_st = session.fields.get("co_storyteller") or "\u2014"
        embed.add_field(name="5 \u00b7 Co-Storyteller:in", value=f"```{co_st}```", inline=True)

        # 6 · Level (inline)
        level = session.fields.get("level") or "Alle"
        embed.add_field(name="6 \u00b7 Level", value=f"```{level}```", inline=True)

        # 7 · Labels (inline)
        label_parts = []
        if session.fields.get("is_casual"):
            label_parts.append("\U0001f54a\ufe0f Casual")
        if session.fields.get("is_academy"):
            label_parts.append("\U0001f393 Academy")
        if session.fields.get("is_recorded"):
            label_parts.append("\U0001f3a6 Aufzeichnung")
        labels_val = ", ".join(label_parts) if label_parts else "\u2014"
        embed.add_field(name="7 \u00b7 Labels", value=f"```{labels_val}```", inline=True)

        # 8 · Kamera (inline)
        cam = session.fields.get("camera")
        if cam is True:
            cam_str = "Pflicht"
        elif cam is False:
            cam_str = "Aus"
        else:
            cam_str = "Keine Pflicht"
        embed.add_field(name="8 \u00b7 Kamera", value=f"```{cam_str}```", inline=True)

        # 9 · Max Spieler (inline)
        max_p = session.fields.get("max_players") or 12
        embed.add_field(name="9 \u00b7 Max Spieler", value=f"```{max_p}```", inline=True)

        # 10 · Termin (inline) — deutsches Datumsformat
        start_time = session.fields.get("start_time") or "-"
        duration = session.fields.get("duration_minutes") or 150
        termin_val = _format_termin_german(start_time, duration)
        embed.add_field(name="10 \u00b7 Termin", value=f"```{termin_val}```", inline=True)

        # 11 · Skriptbild / Thumbnail
        script_file = None
        if base3_key:
            # Base3: Thumbnail statt Script-Bild
            embed.set_thumbnail(url=BASE3_THUMBNAILS[base3_key])
        elif script_name and not is_free and sd_lookup:
            chars = sd_lookup.get("characters", [])
            if chars:
                try:
                    img = await generate_script_image(
                        script_name, sd_lookup.get("author", ""),
                        chars, sd_lookup.get("version", ""),
                        content=sd_lookup.get("content"),
                    )
                    script_file = discord.File(img, filename="script_preview.png")
                    embed.set_image(url="attachment://script_preview.png")
                except Exception as e:
                    logger.warning("Script-Bild: %s", e)

        footer = _cost_footer(session)
        if footer:
            embed.set_footer(text=footer)

        # Buttons
        view = SummaryView(self, session, channel)

        outro_lines = [
            "Schau dir die Zusammenfassung in Ruhe an. Wenn alles passt, drücke **Erstellen** "
            "(oder schreib `ok`). Zum Ändern:",
            "• **Nummer** (1–10) für ein einzelnes Feld",
            "• **Freitext** für mehrere Felder gleichzeitig (z.B. \"Kamera aus, Level Profi\")",
            "• `anderes Skript` · `andere Version`",
        ]
        if is_retrigger:
            outro_lines.append("• `alt` um deinen vorherigen Titel und deine Beschreibung wiederherzustellen")
        outro_lines.append(HINT_FINAL_REVIEW)
        outro = "\n".join(outro_lines)

        kwargs = {"content": intro_text, "embed": embed, "view": view}
        if script_file:
            kwargs["file"] = script_file
        await channel.send(**kwargs)
        await channel.send(outro)

    async def _show_version_choices(self, session, channel):
        """Sucht alle Versionen des aktuellen Scripts und zeigt sie zur Auswahl."""
        from logic.botcscripts import search_versions

        sd = getattr(session, "_selected_script_data", None) or {}
        script_name = session.fields.get("script") or ""
        author = sd.get("author", "")

        async with channel.typing():
            versions = await search_versions(script_name, author)

        if not versions:
            # Ohne Author-Filter nochmal versuchen
            async with channel.typing():
                versions = await search_versions(script_name)

        if not versions:
            await channel.send(_err(f"Keine Versionen von **{script_name}** gefunden."))
            return

        # Sortieren nach Version (absteigend)
        versions.sort(key=lambda v: v.get("version", ""), reverse=True)

        session._pending_version_choices = versions
        session.pending_title_description = False
        session.pending_final_review = False

        lines = [f"**Verfügbare Versionen von {script_name}:**\n"]
        for i, v in enumerate(versions, 1):
            char_count = len(v.get("characters", []))
            lines.append(f"**{i}** — v{v.get('version', '?')} ({char_count} Charaktere)")

        lines.append(f"\nWähle eine Version.\n{HINT_VERSION_CHOICES}")
        await channel.send("\n".join(lines))

    # ── DM Listener ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not isinstance(message.channel, discord.DMChannel) or message.author.bot:
            return

        session = get_session(message.author.id)
        if session is None:
            if was_recently_expired(message.author.id):
                await message.channel.send("⏰ Session abgelaufen. Starte mit `/botc` neu.")
            return
        # Hinweis: Timeout/Max-Calls-Meldungen bleiben konsistent "⏰ …" — klar als
        # System-Ereignis erkennbar (nicht als User-Fehler).

        session.touch()

        # Max-Call-Limit
        if session.call_count >= MAX_CALLS:
            end_session(session.user_id)
            await message.channel.send(
                f"\u23f0 Session nach {MAX_CALLS} Nachrichten automatisch beendet. "
                "Starte mit `/botc` neu."
            )
            return

        if message.content.strip().lower() in CANCEL_KEYWORDS:
            end_session(session.user_id)
            await message.channel.send("Event-Erstellung abgebrochen. ✌️")
            return

        async with session._lock:
            await self._process(session, message)

    # ── State handlers (extracted from _process) ───────────────────

    async def _process_manual_rating(self, session, ch, text):
        """Handles _pending_manual_rating: User gibt Einschätzung für manuelles Script."""
        session._pending_manual_rating = False
        tl = text.lower().strip()
        rating_map = {
            "grün": "green", "gruen": "green", "green": "green", "💚": "green",
            "gelb": "yellow", "yellow": "yellow", "🟡": "yellow",
            "rot": "red", "red": "red", "🟥": "red",
        }
        rating = None
        for keyword, val in rating_map.items():
            if keyword in tl:
                rating = val
                break
        if not rating:
            session._pending_manual_rating = True
            await ch.send(
                _err("Bitte wähle eine Farbe: **grün**, **gelb** oder **rot**.", HINT_MANUAL_RATING)
            )
            return
        session.fields["complexity_analysis"] = {"rating": rating}
        session.label = compute_label(session.fields)
        session._retrigger_proposal = True
        await self._show_final_review(session, ch)

    async def _process_script_edit_mode(self, session, ch, text):
        """Handles pending_script_edit_mode: DB search, manual entry, upload, free choice."""
        session.pending_script_edit_mode = False
        tl = text.lower().strip()
        if tl in ("1", "suchen", "datenbank", "db"):
            session.pending_script_search = True
            await ch.send(f"Gib den **Skriptnamen** ein, nach dem ich suchen soll.\n{HINT_SCRIPT_SEARCH_RETRY}")
            return
        if tl in ("2", "eingeben", "manuell", "selbst"):
            session.pending_field_edit = "script"
            await ch.send(f"Gib den **neuen Skriptnamen** ein.\n{HINT_FIELD_EDIT_GENERIC}")
            return
        if tl in ("3", "hochladen", "upload", "json"):
            session.pending_script_upload = True
            await ch.send(f"Sende die **Script-JSON** als Datei (.json) oder schreibe `skip`.\n{HINT_SCRIPT_UPLOAD}")
            return
        if tl in ("4", "frei", "freie wahl", "free choice", "offen"):
            session.fields["script"] = "Freie Skriptwahl"
            session.fields["is_free_choice"] = True
            session.fields["complexity_analysis"] = None
            session.label = compute_label(session.fields)
            await self._show_final_review(session, ch, regenerate_title=True)
            return
        # Haiku-Fallback: Natürliche Sprache → als Suchbegriff interpretieren
        if len(tl) > 2 and not tl.isdigit():
            search_term = _extract_search_term(text)
            session.pending_script_search = True
            await self._process_script_search(session, ch, search_term)
            return
        await ch.send(SCRIPT_CHANGE_PROMPT)
        session.pending_script_edit_mode = True
        return

    async def _process_script_search(self, session, ch, text):
        """Handles pending_script_search: running DB search."""
        session.pending_script_search = False
        await ch.send(f"Ich suche **{text}** in der Datenbank...")
        async with ch.typing():
            results = await search_scripts(text, limit=5)
        session.touch()
        if results:
            session.pending_script_choices = results
            session._script_choice_return_to_summary = True
            embed = _build_script_choice_embed(text, results)
            await ch.send(embed=embed)
            await ch.send(SCRIPT_CHOICE_HELP)
        else:
            await ch.send(_err(f"**{text}** nicht gefunden.", HINT_SCRIPT_SEARCH_RETRY))
            session.pending_script_search = True
        return

    async def _process_field_edit(self, session, ch, text, message):
        """Handles pending_field_edit: editing a single field from summary."""
        key = session.pending_field_edit
        session.pending_field_edit = None
        tl = text.lower().strip()

        if key == "_image":
            if tl in ("auto", "automatisch", "standard", "reset"):
                session._custom_image_url = None
                await ch.send("Bild auf automatisches Skript-Bild zurückgesetzt.")
            elif message.attachments:
                att = message.attachments[0]
                if att.content_type and att.content_type.startswith("image/"):
                    session._custom_image_url = att.url
                    session._summary_has_image = False  # Custom ersetzt Auto
                    await ch.send(f"Eigenes Bild gesetzt.")
                else:
                    await ch.send(_err(
                        "Das ist kein Bild.",
                        "-# *Sende eine **Bilddatei** als Anhang oder schreibe `auto` für das Standard-Bild.*",
                    ))
                    session.pending_field_edit = "_image"
                    return
            else:
                await ch.send(
                    "Sende ein **Bild als Datei** oder schreibe `auto`.\n"
                    "-# *Hänge eine Bilddatei als Anhang an — oder `auto` für das Standard-Bild.*"
                )
                session.pending_field_edit = "_image"
                return
            await self._show_final_review(session, ch, regenerate_title=False)
            return

        if key == "_labels":
            # Labels: "casual ja", "academy nein", etc.
            if "casual" in tl:
                session.fields["is_casual"] = any(w in tl for w in ("ja", "yes", "true", "an"))
            elif "academy" in tl:
                session.fields["is_academy"] = any(w in tl for w in ("ja", "yes", "true", "an"))
            else:
                await ch.send(_err("Das habe ich nicht verstanden.", HINT_FIELD_EDIT_LABELS))
                session.pending_field_edit = "_labels"
                return
            await self._show_final_review(session, ch, regenerate_title=False)
            return

        if key == "start_time":
            # Termin & Dauer zusammen: "2026-03-25 20:00 180min" oder nur eins
            import re
            # Dauer extrahieren (z.B. "180min", "180", "2h")
            dur_match = re.search(r'(\d+)\s*(?:min|m\b)', tl)
            hour_match = re.search(r'(\d+)\s*(?:h|std)', tl)
            # Termin extrahieren (YYYY-MM-DD HH:MM)
            time_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})', text)

            if time_match:
                session.fields["start_time"] = time_match.group(1)
            if dur_match:
                session.fields["duration_minutes"] = int(dur_match.group(1))
            elif hour_match:
                session.fields["duration_minutes"] = int(hour_match.group(1)) * 60
            elif not time_match:
                # Nur eine Zahl → Dauer in Minuten
                try:
                    session.fields["duration_minutes"] = int(text)
                except ValueError:
                    # Vielleicht ein Termin ohne erkanntes Format
                    session.fields["start_time"] = text
            await self._show_final_review(session, ch, regenerate_title=False)
            return

        old_script = session.fields.get("script")
        val = text
        if key == "camera":
            val = None if tl in ("keine pflicht", "optional", "egal", "nein", "no") else tl in ("an", "ja", "pflicht")
        elif key == "is_casual":
            val = tl in ("ja", "yes", "true")
        elif key == "max_players":
            try: val = int(val)
            except ValueError: pass
        session.fields[key] = val

        # Bei Skript-Änderung: Titel/Beschreibung neu generieren
        if key == "script" and val != old_script:
            sd, source = lookup_script(val)
            if sd and sd.get("characters"):
                # Bekanntes Script mit Daten → Analyse
                analysis = analyze_script_complexity(sd["characters"])
                session.fields["complexity_analysis"] = analysis
                session.label = compute_label(session.fields)
                session._retrigger_proposal = True
                await self._show_final_review(session, ch)
            else:
                # Unbekanntes Script (manuell eingegeben) → alte Metadaten löschen
                session._selected_script_data = None
                session.fields["complexity_analysis"] = None
                session.fields["script_version"] = None
                session.label = compute_label(session.fields)
                # User nach Einschätzung fragen
                session._pending_manual_rating = True
                await ch.send(
                    f"Skript auf **{val}** gesetzt. Wie sch\u00e4tzt du die Komplexit\u00e4t ein?\n"
                    "\U0001f49a **gr\u00fcn** \u2014 Einsteiger-freundlich\n"
                    "\U0001f7e1 **gelb** \u2014 Mittel\n"
                    "\U0001f7e5 **rot** \u2014 F\u00fcr Erfahrene"
                )
            return

        await self._show_final_review(session, ch, regenerate_title=False)
        return

    async def _process_script_upload(self, session, ch, text, message):
        """Handles pending_script_upload: JSON file upload."""
        session.touch()
        if text.lower() in ("skip", "überspringen", "s"):
            session.pending_script_upload = False
            await self._show_final_review(session, ch)
            return
        if not message.attachments:
            await ch.send(f"Sende die **Script-JSON** als Datei (.json) oder schreibe `skip`.\n{HINT_SCRIPT_UPLOAD}")
            return
        att = message.attachments[0]
        if not att.filename.endswith(".json"):
            await ch.send(_err(f"**{att.filename}** ist keine JSON-Datei.", HINT_SCRIPT_UPLOAD))
            return
        try:
            data = json.loads((await att.read()).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            await ch.send(_err("Die Datei enthält kein gültiges JSON.", HINT_SCRIPT_UPLOAD))
            return
        parsed, error = validate_script_json(data)
        if error:
            await ch.send(_err(error, HINT_SCRIPT_UPLOAD))
            return
        name = parsed["name"]
        if name == "Custom Script" and session.fields.get("script"):
            name = session.fields["script"]
            parsed["name"] = name
        had_title = bool(session.fields.get("title"))
        session.fields["script"] = name
        cache_script(name, parsed)
        session.pending_script_upload = False
        await ch.send(f"✅ **{name}** hochgeladen!")
        if had_title:
            session._retrigger_proposal = True
        await self._show_final_review(session, ch)
        return

    async def _process_script_choices(self, session, ch, text, message):
        """Handles pending_script_choices: script selection from search results."""
        choices = session.pending_script_choices
        tl = text.lower()

        # JSON-Upload hat HÖCHSTE Priorität — vor allem anderen prüfen
        if message.attachments and message.attachments[0].filename.endswith(".json"):
            session.pending_script_choices = None
            session.pending_script_upload = True
            await self._process_script_upload(session, ch, text, message)
            return

        if tl in ("skip", "überspringen", "s"):
            session.pending_script_choices = None
            await self._show_final_review(session, ch)
            return

        if tl in ("custom", "homebrew", "eigenes", "keines", "keins davon", "nichts davon"):
            session.pending_script_choices = None
            session.pending_script_upload = True
            await ch.send(f"Sende die **Script-JSON** (.json) als Anhang — oder schreibe `skip`.\n{HINT_SCRIPT_UPLOAD}")
            return

        # Nach einer Haiku-Rückfrage: direkt an Haiku weiterleiten
        # (keine deterministische Nummern-Auswertung, weil "3" die Rückfrage-Option meinen könnte)
        haiku_clarification = getattr(session, "_haiku_clarification_pending", False)
        if haiku_clarification:
            session._haiku_clarification_pending = False

        if not haiku_clarification:
            # Direkte Nummer
            try:
                idx = int(tl) - 1
                if 0 <= idx < len(choices):
                    await self._select_script(session, ch, choices[idx])
                    return
                await ch.send(_err(f"Bitte wähle **1–{len(choices)}**.", HINT_SCRIPT_CHOICE))
                return
            except ValueError:
                pass

            # Natürliche Sprache: "das erste", "von Viva La Sam", "Extension Cord", etc.
            ordinals = {"erste": 0, "ersten": 0, "zweite": 1, "zweiten": 1,
                        "dritte": 2, "dritten": 2, "vierte": 3, "vierten": 3,
                        "fünfte": 4, "fünften": 4, "letzte": len(choices) - 1, "letzten": len(choices) - 1}

            # Ordinalzahl-Match
            for word, idx in ordinals.items():
                if word in tl and idx < len(choices):
                    await self._select_script(session, ch, choices[idx])
                    return

            # Name- oder Autor-Match
            best_match = None
            best_score = 0
            for i, choice in enumerate(choices):
                score = 0
                name_lower = choice["name"].lower()
                author_lower = (choice.get("author") or "").lower()

                if name_lower in tl or tl in name_lower:
                    score = 10
                elif author_lower and author_lower in tl:
                    score = 8

                # Teilwort-Match
                for word in tl.split():
                    if len(word) > 2:
                        if word in name_lower: score = max(score, 5)
                        if author_lower and word in author_lower: score = max(score, 4)

                if score > best_score:
                    best_score = score
                    best_match = i

            if best_match is not None and best_score >= 4:
                await self._select_script(session, ch, choices[best_match])
                return

        # Haiku als Fallback (oder nach Clarification)
        async with ch.typing():
            result = await interpret_script_choice(session, text, choices)

        if not result:
            await ch.send(_err("Das konnte ich nicht verarbeiten.", HINT_SCRIPT_CHOICE))
            return

        action = result.get("action")

        if action == "select":
            idx = (result.get("index") or 1) - 1
            if 0 <= idx < len(choices):
                await self._select_script(session, ch, choices[idx])
            else:
                await ch.send(_err(f"Nummer **{idx+1}** gibt es nicht. Wähle **1–{len(choices)}**.", HINT_SCRIPT_CHOICE))
            return

        if action == "search":
            term = result.get("search_term") or text
            session.pending_script_choices = None
            await ch.send(f"Ich suche **{term}** in der Datenbank...")
            async with ch.typing():
                new_results = await search_scripts(term, limit=5)
            session.touch()
            if new_results:
                session.pending_script_choices = new_results
                embed = _build_script_choice_embed(term, new_results)
                await ch.send(embed=embed)
                await ch.send(SCRIPT_CHOICE_HELP)
            else:
                await ch.send(_err(f"**{term}** nicht gefunden.", HINT_SCRIPT_SEARCH_RETRY))
                session.pending_script_choices = choices
            return

        if action == "upload":
            session.pending_script_choices = None
            session.pending_script_upload = True
            await ch.send(f"Lade deine **Script-JSON** (.json) als Anhang hoch.\n{HINT_SCRIPT_UPLOAD}")
            return

        if action == "skip":
            session.pending_script_choices = None
            await self._show_final_review(session, ch)
            return

        if action == "preview":
            indices = result.get("indices", [])
            if indices:
                preview_list = []
                valid_indices = []
                for idx in indices:
                    i = idx - 1
                    if 0 <= i < len(choices):
                        preview_list.append(choices[i])
                        valid_indices.append(idx)
                if preview_list:
                    await self._show_script_preview(session, ch, preview_list, valid_indices)
                    return

        # unclear → Haiku erklärt die Möglichkeiten
        # Nächste Eingabe geht wieder an Haiku (nicht an deterministische Nummern-Auswertung)
        session._haiku_clarification_pending = True
        msg = result.get("message", "")
        if msg:
            footer = _cost_footer(session)
            if footer:
                msg += f"\n-# {footer}"
            await ch.send(msg)
        return

    async def _process_version_choices(self, session, ch, text):
        """Handles _pending_version_choices: version selection."""
        version_choices = session._pending_version_choices
        try:
            idx = int(text) - 1
            if 0 <= idx < len(version_choices):
                chosen = version_choices[idx]
                session._pending_version_choices = None
                session._retrigger_proposal = True
                await self._select_script(session, ch, chosen)
                return
            else:
                await ch.send(_err(f"Wähle eine **Nummer** von **1 bis {len(version_choices)}**.", HINT_VERSION_CHOICES))
                return
        except ValueError:
            await ch.send(_err(f"Das war keine Nummer. Wähle **1 bis {len(version_choices)}**.", HINT_VERSION_CHOICES))
            return

    async def _process_script_preview(self, session, ch, text):
        """Handles _pending_script_preview: script detail preview."""
        preview_scripts = session._preview_scripts
        tl = text.lower()

        # "zurück" → back to choices list
        if tl in ("zurück", "back", "liste"):
            session._pending_script_preview = False
            session._preview_scripts = None
            choices = getattr(session, "pending_script_choices", None)
            if choices:
                embed = _build_script_choice_embed(session.fields.get("script", ""), choices)
                await ch.send(embed=embed)
                await ch.send(SCRIPT_CHOICE_HELP)
            return

        # Number → select from preview list
        try:
            idx = int(text) - 1
            if 0 <= idx < len(preview_scripts):
                session._pending_script_preview = False
                session._preview_scripts = None
                await self._select_script(session, ch, preview_scripts[idx])
                return
        except ValueError:
            pass

        # Haiku fallback
        script_names = "\n".join(f"{i+1}. {s.get('name', '?')}" for i, s in enumerate(preview_scripts))
        result = await interpret_script_preview(session, text, script_names)
        if result:
            action = result.get("action")
            if action == "select":
                idx = (result.get("index") or 1) - 1
                if 0 <= idx < len(preview_scripts):
                    session._pending_script_preview = False
                    session._preview_scripts = None
                    await self._select_script(session, ch, preview_scripts[idx])
                    return
            elif action == "back":
                session._pending_script_preview = False
                session._preview_scripts = None
                choices = getattr(session, "pending_script_choices", None)
                if choices:
                    embed = _build_script_choice_embed(session.fields.get("script", ""), choices)
                    await ch.send(embed=embed)
                    await ch.send(SCRIPT_CHOICE_HELP)
                return
            elif action == "unclear" and result.get("message"):
                await ch.send(result["message"])
                return

        await ch.send(_err("Wähle eine **Nummer** oder geh `zurück` zur Liste.", HINT_SCRIPT_PREVIEW))
        return

    async def _process_final_review(self, session, ch, text):
        """Handles pending_final_review: final review with field editing."""
        tl = text.lower().strip()

        # 1. Confirm → Event erstellen
        if tl in CONFIRM_KEYWORDS:
            # Trigger SummaryView confirm logic
            session.pending_final_review = False
            view = SummaryView(self, session, ch)
            # Simulate button press
            await view.confirm(None, None)
            return

        # 2. "anderes skript" → script edit mode
        if any(kw in tl for kw in ("anderes skript", "skript ändern", "anderes script", "script ändern")):
            session.pending_final_review = False
            session.pending_script_edit_mode = True
            await ch.send(SCRIPT_CHANGE_PROMPT)
            return

        # 3. "andere version" → version choices
        if any(kw in tl for kw in ("andere version", "version ändern", "version wechseln")):
            await self._show_version_choices(session, ch)
            return

        # 4. "alt" → restore old title/desc
        if tl in ("alt", "alte", "bisherige", "vorherige"):
            old_t = getattr(session, "_old_title", None)
            old_d = getattr(session, "_old_desc", None)
            if old_t and old_d:
                session.fields["title"] = old_t
                session.fields["description"] = old_d
                await ch.send("Bisherige Titel und Beschreibung wiederhergestellt.")
                await self._show_final_review(session, ch, regenerate_title=False)
                return
            else:
                await ch.send(_err("Keine bisherigen Werte vorhanden.", HINT_FINAL_REVIEW))
                return

        # 5. Number input (1-10) → field edit
        try:
            num = int(text)
            if 1 <= num <= len(SUMMARY_FIELDS):
                key, label = SUMMARY_FIELDS[num - 1]
                if key == "script":
                    session.pending_final_review = False
                    session.pending_script_edit_mode = True
                    await ch.send(SCRIPT_CHANGE_PROMPT)
                elif key == "_labels":
                    await ch.send(
                        "Welches Label möchtest du ändern?\n"
                        "• `casual ja/nein`\n"
                        "• `academy ja/nein`\n"
                        f"{HINT_FIELD_EDIT_LABELS}"
                    )
                    session.pending_field_edit = "_labels"
                elif key == "start_time":
                    await ch.send(
                        "Was möchtest du ändern?\n"
                        "• Nur Termin: z.B. `2026-03-25 20:00`\n"
                        "• Nur Dauer: z.B. `180`\n"
                        "• Beides: z.B. `2026-03-25 20:00 180min`\n"
                        f"{HINT_FIELD_EDIT_START_TIME}"
                    )
                    session.pending_field_edit = "start_time"
                else:
                    session.pending_field_edit = key
                    # State-spezifischen Hint passend zum Feld auswählen
                    field_hints = {
                        "title": HINT_FIELD_EDIT_GENERIC,
                        "description": HINT_FIELD_EDIT_GENERIC,
                        "storyteller": HINT_FIELD_EDIT_GENERIC,
                        "co_storyteller": HINT_FIELD_EDIT_CO_ST,
                        "level": HINT_FIELD_EDIT_LEVEL,
                        "camera": HINT_FIELD_EDIT_CAMERA,
                        "max_players": HINT_FIELD_EDIT_MAX_PLAYERS,
                    }
                    hint = field_hints.get(key, HINT_FIELD_EDIT_GENERIC)
                    await ch.send(f"Was soll der neue Wert für **{label}** sein?\n{hint}")
                return
            else:
                await ch.send(_err(f"Bitte wähle **1–{len(SUMMARY_FIELDS)}**.", HINT_FINAL_REVIEW))
                return
        except ValueError:
            pass

        # 6. Haiku fallback via interpret_final_review
        fields_summary = (
            f"1. Titel: {session.fields.get('title', '-')}\n"
            f"2. Skript: {session.fields.get('script', '-')}\n"
            f"3. Beschreibung: {session.fields.get('description', '-')}\n"
            f"4. Storyteller: {session.fields.get('storyteller', '-')}\n"
            f"5. Co-Storyteller: {session.fields.get('co_storyteller', '-')}\n"
            f"6. Level: {session.fields.get('level', '-')}\n"
            f"7. Labels: casual={session.fields.get('is_casual')}, academy={session.fields.get('is_academy')}, recorded={session.fields.get('is_recorded')}\n"
            f"8. Kamera: {session.fields.get('camera')}\n"
            f"9. Max Spieler: {session.fields.get('max_players', 12)}\n"
            f"10. Termin: {session.fields.get('start_time', '-')}, Dauer: {session.fields.get('duration_minutes', 150)} Min"
        )
        async with ch.typing():
            result = await interpret_final_review(session, text, fields_summary)

        if result:
            action = result.get("action")

            if action == "edit":
                # Apply field changes
                edits = result.get("fields", {})
                for field_key, field_val in edits.items():
                    if field_key in ("is_casual", "is_academy", "is_recorded"):
                        session.fields[field_key] = bool(field_val)
                    elif field_key == "camera":
                        if field_val is None or (isinstance(field_val, str) and field_val.lower() in ("keine pflicht", "optional", "egal")):
                            session.fields["camera"] = None
                        elif isinstance(field_val, bool):
                            session.fields["camera"] = field_val
                        elif isinstance(field_val, str):
                            session.fields["camera"] = field_val.lower() in ("an", "ja", "pflicht", "true")
                    elif field_key in ("max_players", "duration_minutes"):
                        try:
                            session.fields[field_key] = int(field_val)
                        except (ValueError, TypeError):
                            pass
                    else:
                        session.fields[field_key] = field_val
                # Recompute label after edits
                session.label = compute_label(session.fields)
                await self._show_final_review(session, ch, regenerate_title=False)
                return

            if action == "confirm":
                session.pending_final_review = False
                view = SummaryView(self, session, ch)
                await view.confirm(None, None)
                return

            if action == "change_script":
                session.pending_final_review = False
                session.pending_script_edit_mode = True
                await ch.send(SCRIPT_CHANGE_PROMPT)
                return

            if action == "change_version":
                await self._show_version_choices(session, ch)
                return

            if action == "unclear" and result.get("message"):
                await ch.send(result["message"])
                return

        await ch.send(_err(
            "Das konnte ich nicht zuordnen.",
            HINT_FINAL_REVIEW,
        ))
        return

    async def _process_haiku_chat(self, session, ch, text):
        """Handles Step 1: Haiku conversation to collect event fields."""
        async with ch.typing():
            response = await call_haiku(session, text)

        if not response:
            await ch.send(_err(
                "Da ist etwas schiefgelaufen.",
                "-# *Versuch es nochmal — oder starte mit `/botc` neu.*",
            ))
            return

        action = response.get("action", "ask")
        haiku_msg = response.get("message", "")
        footer = _cost_footer(session)

        # Override: Wenn alle Pflichtfelder da → done erzwingen, egal was Haiku sagt
        if action == "ask":
            all_present = all(session.fields.get(f) is not None for f in REQUIRED_FIELDS)
            if all_present:
                logger.info("Alle Pflichtfelder vorhanden — action override: ask → done")
                action = "done"

        if action == "done":
            # Schritt 1 fertig → Schritt 2 (Script)
            # Haiku-Message ignorieren — wir steuern den Flow ab hier selbst
            done_msg = f"Alles klar, Event-Daten sind komplett."
            if footer:
                done_msg += f"\n-# {footer}"
            await ch.send(done_msg)

            script_name = session.fields.get("script")
            if script_name and not session.fields.get("is_free_choice"):
                # Homebrew/Custom/eigenes → direkt Upload anbieten, nicht DB-Suche
                is_custom_intent = script_name.lower() in (
                    "homebrew", "custom", "custom script", "eigenes", "eigenes skript",
                    "mein skript", "mein eigenes", "mein eigenes skript",
                    "custom skript", "homebrew skript",
                )
                if is_custom_intent:
                    session.pending_script_upload = True
                    await ch.send(
                        "Sende dein **Skript als JSON-Datei** (.json) hoch.\n"
                        "Du kannst auch in der Datenbank **suchen** oder `skip` schreiben.\n"
                        f"{HINT_SCRIPT_UPLOAD}"
                    )
                    return

                _, source = lookup_script(script_name)
                if source == "miss":
                    await ch.send(f"Ich suche **{script_name}** in der Datenbank...")
                    async with ch.typing():
                        results = await search_scripts(script_name, limit=5)
                    session.touch()

                    if results:
                        session.pending_script_choices = results
                        embed = _build_script_choice_embed(script_name, results)
                        await ch.send(embed=embed)
                        await ch.send(SCRIPT_CHOICE_HELP)
                        return
                    else:
                        session.pending_script_upload = True
                        await ch.send(_err(
                            f"**{script_name}** ist nicht in der Datenbank.",
                            f"*Sende die **Script-JSON** (.json) als Anhang — oder schreibe `skip`.*\n{HINT_SCRIPT_UPLOAD}",
                        ))
                        return

            # Script OK → Final Review
            await self._show_final_review(session, ch)

        elif action == "refuse":
            # Zentraler Refuse-Text — identisch bei Off-Topic und Injection-/Tricksversuchen.
            # Haiku's eigene Message wird verworfen, damit der User konsistent dasselbe sieht.
            embed = discord.Embed(description=REFUSE_MESSAGE, color=0xED4245)
            if footer:
                embed.set_footer(text=footer)
            await ch.send(embed=embed)

        else:
            # ask — Haiku-Rückfrage + Hint zur freien Sprache
            parts = [haiku_msg, HINT_HAIKU_CHAT]
            if footer:
                parts.append(f"-# {footer}")
            await ch.send("\n".join(parts))

    # ── Dispatcher ────────────────────────────────────────────────────

    async def _process(self, session, message):
        ch = message.channel
        text = message.content.strip()

        # ── Manuelle Rating-Eingabe ────────────────────────────────────
        if getattr(session, "_pending_manual_rating", False):
            return await self._process_manual_rating(session, ch, text)

        # ── Skript-Edit: DB-Suche oder manuell ────────────────────────
        if getattr(session, "pending_script_edit_mode", False):
            return await self._process_script_edit_mode(session, ch, text)

        # ── Skript-Edit: DB-Suche läuft ──────────────────────────────
        if getattr(session, "pending_script_search", False):
            return await self._process_script_search(session, ch, text)

        # ── Feld-Edit (aus Summary) ──────────────────────────────────
        if getattr(session, "pending_field_edit", None):
            return await self._process_field_edit(session, ch, text, message)

        # ── Script-Upload ────────────────────────────────────────────
        if getattr(session, "pending_script_upload", False):
            return await self._process_script_upload(session, ch, text, message)

        # ── Script-Auswahl (Nummer ODER natürliche Sprache) ────────────
        if getattr(session, "pending_script_choices", None):
            return await self._process_script_choices(session, ch, text, message)

        # ── Versions-Auswahl ───────────────────────────────────────────
        if getattr(session, "_pending_version_choices", None):
            return await self._process_version_choices(session, ch, text)

        # ── Script-Preview ───────────────────────────────────────────
        if getattr(session, "_pending_script_preview", False) and getattr(session, "_preview_scripts", None):
            return await self._process_script_preview(session, ch, text)

        # ── Final Review (Schritt 3+4 kombiniert) ─────────────────────
        if getattr(session, "pending_final_review", False):
            return await self._process_final_review(session, ch, text)

        # ── Schritt 1: Haiku-Chat ────────────────────────────────────
        return await self._process_haiku_chat(session, ch, text)


    @app_commands.command(name="wipecache", description="Löscht die Script-Cache-Datenbank (zum Testen)")
    async def wipecache(self, interaction: discord.Interaction):
        from logic.script_cache import CACHE_FILE
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
            await interaction.response.send_message("Script-Cache gelöscht.", ephemeral=True)
        else:
            await interaction.response.send_message("Kein Cache vorhanden.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(HostCommand(bot))
