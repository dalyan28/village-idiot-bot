"""Slash-Command /host — Event-Erstellung via DM.

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
from datetime import datetime
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
    interpret_script_choice,
    start_session,
    update_title_description,
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

CANCEL_KEYWORDS = {"abbrechen", "cancel", "stop"}
CONFIRM_KEYWORDS = {"ok", "fertig", "bestätigen", "confirm", "ja", "yes", "passt", "gut"}

SUMMARY_FIELDS = [
    ("title", "Titel"),
    ("description", "Beschreibung"),
    ("script", "Skript"),
    ("storyteller", "Storyteller:in"),
    ("co_storyteller", "Co-Storyteller:in"),
    ("level", "Level"),
    ("_labels", "Labels"),
    ("camera", "Kamera"),
    ("max_players", "Max Spieler"),
    ("start_time", "Termin & Dauer"),
    ("_image", "Bild"),
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


def _build_summary_embed(session, script_data=None):
    """Summary-Embed: Titel #1 (not inline), Beschreibung #2 (not inline), Rest inline."""
    f = session.fields
    is_free = bool(f.get("is_free_choice"))

    embed = discord.Embed(title="Event-Zusammenfassung", color=BOT_COLOR)

    # Script-Info als Description
    if script_data and not is_free:
        sn = script_data.get("name", f.get("script", ""))
        au = script_data.get("author", "")
        ve = script_data.get("version", "")
        ch = script_data.get("characters", [])
        info = f"**📜 {sn}**"
        if au: info += f" von {au}"
        if ve: info += f" · v{ve}"
        if ch: info += f" · {len(ch)} Charaktere"
        embed.description = info

    # 1. Titel (not inline) — mit Label-Prefix
    prefix = build_title_prefix(f)
    title_display = f"{prefix} {f.get('title') or '-'}" if prefix else (f.get('title') or '-')
    embed.add_field(name="1 · Titel", value=f"```{title_display}```", inline=False)

    # 2. Beschreibung (not inline)
    desc = f.get("description") or "*Wird generiert*"
    if len(desc) > 1010: desc = desc[:1007] + "..."
    embed.add_field(name="2 · Beschreibung", value=f"```{desc}```", inline=False)

    # 3. Skript (inline)
    script_display = f.get('script') or '-'
    if script_data:
        au = script_data.get("author", "")
        ve = script_data.get("version", "")
        if au:
            script_display += f" von {au}"
        if ve:
            script_display += f" · v{ve}"
    embed.add_field(name="3 · Skript", value=f"```{script_display}```", inline=True)

    # 4-5 inline
    embed.add_field(name="4 · Storyteller:in", value=f"```{f.get('storyteller') or '-'}```", inline=True)
    embed.add_field(name="5 · Co-Storyteller:in", value=f"```{_fmt('co_storyteller', f.get('co_storyteller'))}```", inline=True)

    # 6. Level (inline)
    embed.add_field(name="6 · Level", value=f"```{f.get('level') or '-'}```", inline=True)

    # 7. Labels (Casual/Academy/Homebrew etc.)
    labels = []
    if f.get("is_academy"):
        labels.append("🎓 Academy")
    if f.get("is_casual"):
        labels.append("🕊️ Casual")
    analysis = f.get("complexity_analysis") or {}
    if analysis.get("is_homebrew"):
        labels.append("⚒️ Homebrew")
    label_display = ", ".join(labels) if labels else "Keine"
    embed.add_field(name="7 · Labels", value=f"```{label_display}```", inline=True)

    # 8-9 inline
    embed.add_field(name="8 · Kamera", value=f"```{_fmt('camera', f.get('camera'))}```", inline=True)
    embed.add_field(name="9 · Max Spieler", value=f"```{f.get('max_players') or 12}```", inline=True)

    # 10. Termin & Dauer (zusammengefasst)
    termin = f.get('start_time') or '-'
    dauer = _fmt('duration_minutes', f.get('duration_minutes'))
    embed.add_field(name="10 · Termin & Dauer", value=f"```{termin} · {dauer}```", inline=False)

    # 11 · Bild
    if session._summary_has_image:
        embed.add_field(name="11 · Bild", value="```Skript-Bild (automatisch)```", inline=False)
        embed.set_image(url="attachment://script_preview.png")
    elif getattr(session, "_custom_image_url", None):
        embed.add_field(name="11 · Bild", value="```Eigenes Bild```", inline=False)
        embed.set_image(url=session._custom_image_url)
    else:
        embed.add_field(name="11 · Bild", value="```Kein Bild```", inline=False)

    footer = _cost_footer(session)
    ft = "Antworte mit einer Nummer zum Ändern oder drücke Erstellen"
    if footer: ft = f"{ft}\n{footer}"
    embed.set_footer(text=ft)

    return embed


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
    "Ist dein Skript dabei? Du kannst auch einen anderen Suchbegriff eingeben, "
    "eine Script-JSON (.json) hochladen, oder den Schritt überspringen."
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
        await interaction.response.defer()
        self.stop()

        f = self.session.fields
        is_free = bool(f.get("is_free_choice"))
        self.session.label = compute_label(f)
        emoji = get_label_emoji(self.session.label, is_free_choice=is_free)

        start_ts = _parse_start_time(f.get("start_time") or "")
        if not start_ts:
            await interaction.followup.send("Fehler: Termin konnte nicht verarbeitet werden.")
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
        if not is_free and f.get("script"):
            sd, _ = lookup_script(f["script"])
            if sd:
                script_characters = sd.get("characters", [])
                script_author = sd.get("author", "")
                script_version = sd.get("version", "")
                bid = sd.get("botcscripts_id")
                if bid and script_version:
                    script_url = f"https://www.botcscripts.com/script/{bid}/{script_version}"

        event_data = {
            "title": title, "description": f.get("description"),
            "storyteller": f.get("storyteller") or "-",
            "co_storyteller": f.get("co_storyteller"),
            "script": script_display, "script_url": script_url,
            "script_author": script_author, "script_version": script_version,
            "script_characters": script_characters,
            "level": f.get("level") or "Alle",
            "camera": f.get("camera"), "max_players": f.get("max_players") or 12,
            "timestamp": start_ts, "end_timestamp": start_ts + duration * 60,
            "creator_id": self.session.user_id,
            "creator_name": self.session.user_display_name,
            "creator_avatar_url": self.session.user_avatar_url,
            "label": self.session.label,
        }

        event_cog = self.cog.bot.cogs.get("EventCommands")
        event_channel = self.cog.bot.get_channel(self.session.event_channel_id)
        if not event_cog or not event_channel:
            await interaction.followup.send("Fehler: Event-System nicht verfügbar.")
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
        elif script_characters and not is_free:
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

                await interaction.followup.send(f"Event aktualisiert! ✏️\n{edit_msg.jump_url}")
            except Exception as e:
                logger.error("Edit-Fehler: %s", e)
                await interaction.followup.send(f"Fehler beim Bearbeiten: {e}")
        else:
            # Neues Event erstellen
            try:
                msg = await event_cog.post_event(event_channel, event_data, script_image=script_file)
                await interaction.followup.send(f"Event erstellt! 🎉\n{msg.jump_url}")
            except Exception as e:
                logger.error("Fehler: %s", e)
                await interaction.followup.send(f"Fehler: {e}")

        end_session(self.session.user_id)

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        end_session(self.session.user_id)
        await interaction.response.send_message("Event-Erstellung abgebrochen.")

    async def on_timeout(self):
        end_session(self.session.user_id)
        try:
            await self.dm_channel.send("⏰ Abgelaufen. Starte mit `/host` neu.")
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
                f"Lass uns ein Event für **{guild.name}** erstellen.\n\n"
                f"Beschreib mir dein Event in einer Nachricht — z.B.:\n"
                f"*\"Morgen 20 Uhr Boozling, ich bin ST, Level Erfahren\"*\n\n"
                f"-# Session läuft 5 Min · 'abbrechen' zum Beenden"
            )
        except discord.Forbidden:
            await interaction.followup.send("Kann keine DM senden.", ephemeral=True)
            end_session(interaction.user.id)

    async def _select_script(self, session, channel, chosen):
        """Wählt ein Script aus den Suchergebnissen, cached es, und geht zu Schritt 3."""
        session.fields["script"] = chosen["name"]
        cache_script(chosen["name"], {
            "name": chosen["name"], "author": chosen.get("author", ""),
            "version": chosen.get("version", ""),
            "botcscripts_id": chosen.get("botcscripts_id", ""),
            "characters": chosen.get("characters", []),
            "content": chosen.get("content", []),
            "script_type": chosen.get("script_type", ""),
            "url": chosen.get("url", ""), "source": "botcscripts",
        })
        session.pending_script_choices = None
        return_to_summary = getattr(session, "_script_choice_return_to_summary", False)
        session._script_choice_return_to_summary = False

        # Komplexitäts-Analyse
        chars = chosen.get("characters", [])
        if chars:
            analysis = analyze_script_complexity(chars)
            session.fields["complexity_analysis"] = analysis
            session.label = compute_label(session.fields)

        await channel.send(f"✅ **{chosen['name']}** ausgewählt!")

        if return_to_summary:
            await self._show_summary(session, channel)
        else:
            await self._show_title_description_proposal(session, channel)

    # ── Schritt 3: Titel & Beschreibung ──────────────────────────────

    async def _show_title_description_proposal(self, session, channel):
        """Analysiert Skript-Komplexität, generiert Titel/Beschreibung-Vorschlag."""
        session.pending_title_description = True

        # Skript-Komplexitätsanalyse
        script_name = session.fields.get("script")
        if script_name and not session.fields.get("is_free_choice"):
            sd, _ = lookup_script(script_name)
            chars = sd.get("characters", []) if sd else []
            if chars:
                analysis = analyze_script_complexity(chars)
                session.fields["complexity_analysis"] = analysis
                session.label = compute_label(session.fields)

        async with channel.typing():
            result = await generate_title_and_description(session)

        reasoning = ""
        if result:
            title, desc, reasoning = result
            session.fields["title"] = title
            session.fields["description"] = desc
        else:
            # Fallback
            script = session.fields.get("script") or "Event"
            st = session.fields.get("storyteller") or session.user_display_name
            co = session.fields.get("co_storyteller")
            title = f"{script} mit {st}" + (f" und {co}" if co else "")
            desc = f"Wir spielen eine Runde {script}!"
            session.fields["title"] = title
            session.fields["description"] = desc

        # Titel-Prefix bauen
        prefix = build_title_prefix(session.fields)
        title_display = f"{prefix} {session.fields['title']}" if prefix else session.fields['title']

        # Rating-Emoji für Einschätzung
        analysis = session.fields.get("complexity_analysis") or {}
        rating = analysis.get("rating")
        rating_emoji = LABEL_EMOJI.get(rating, "") if rating else ""

        footer = _cost_footer(session)
        lines = []

        if reasoning:
            lines.append(f"{rating_emoji} **Skript-Einschätzung:** {reasoning}")

        lines.append(
            "\nJetzt brauchen wir noch einen Titel und eine Beschreibung für das Event. "
            "Ich hab mir mal was ausgedacht — aber ich bin nur ein Village Idiot "
            "und hab keine Ahnung, ob ich sober bin. Also schau lieber nochmal drüber:"
        )
        lines.append(f"\n**1 · Titel**\n```{title_display}```")
        lines.append(f"**2 · Beschreibung**\n```{session.fields['description']}```")
        lines.append(
            "Du kannst alles übernehmen, anpassen, oder eigenen Text schreiben. "
            "Auch die Einschätzung kannst du korrigieren, falls ich daneben liege.\n"
            "Schreibe **ok** wenn alles passt."
        )

        msg = "\n".join(lines)
        if footer:
            msg += f"\n-# {footer}"
        await channel.send(msg)

    # ── Schritt 4: Summary ───────────────────────────────────────────

    async def _show_summary(self, session, channel):
        """Zeigt das Summary-Embed mit Buttons und Script-Bild."""
        session.pending_summary = True
        session.pending_title_description = False

        # Defaults setzen
        session.fields.setdefault("max_players", 12)
        session.fields.setdefault("duration_minutes", 150)

        script_data = None
        is_free = bool(session.fields.get("is_free_choice"))
        sn = session.fields.get("script")
        if sn and not is_free:
            script_data, _ = lookup_script(sn)

        # Script-Bild generieren
        script_file = None
        session._summary_has_image = False
        if script_data and not is_free:
            chars = script_data.get("characters", [])
            if chars:
                try:
                    img = await generate_script_image(
                        sn, script_data.get("author", ""),
                        chars, script_data.get("version", ""),
                        content=script_data.get("content"),
                    )
                    script_file = discord.File(img, filename="script_preview.png")
                    session._summary_has_image = True
                except Exception as e:
                    logger.warning("Script-Bild für Summary: %s", e)

        embed = _build_summary_embed(session, script_data)
        view = SummaryView(self, session, channel)

        kwargs = {"embed": embed, "view": view}
        if script_file:
            kwargs["file"] = script_file
        await channel.send(**kwargs)

    # ── DM Listener ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not isinstance(message.channel, discord.DMChannel) or message.author.bot:
            return

        session = get_session(message.author.id)
        if session is None:
            if was_recently_expired(message.author.id):
                await message.channel.send("⏰ Session abgelaufen. Starte mit `/host` neu.")
            return

        session.touch()

        if message.content.strip().lower() in CANCEL_KEYWORDS:
            end_session(session.user_id)
            await message.channel.send("Event-Erstellung abgebrochen. ✌️")
            return

        async with session._lock:
            await self._process(session, message)

    async def _process(self, session, message):
        ch = message.channel
        text = message.content.strip()

        # ── Skript-Edit: DB-Suche oder manuell ────────────────────────
        if getattr(session, "pending_script_edit_mode", False):
            session.pending_script_edit_mode = False
            tl = text.lower().strip()
            if tl in ("1", "suchen", "datenbank", "db"):
                session.pending_script_search = True
                await ch.send("Gib den **Skriptnamen** ein, nach dem ich suchen soll:")
                return
            elif tl in ("2", "eingeben", "manuell", "selbst"):
                session.pending_field_edit = "script"
                await ch.send("Gib den **neuen Skriptnamen** ein:")
                return
            else:
                await ch.send("Bitte wähle **1** (Datenbank suchen) oder **2** (selbst eingeben).")
                session.pending_script_edit_mode = True
                return

        # ── Skript-Edit: DB-Suche läuft ──────────────────────────────
        if getattr(session, "pending_script_search", False):
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
                await ch.send(f"**{text}** nicht gefunden. Gib einen anderen Suchbegriff ein oder 'abbrechen'.")
                session.pending_script_search = True
            return

        # ── Feld-Edit (aus Summary) ──────────────────────────────────
        if getattr(session, "pending_field_edit", None):
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
                        await ch.send("Das ist kein Bild. Sende eine Bilddatei oder schreibe `auto`.")
                        session.pending_field_edit = "_image"
                        return
                else:
                    await ch.send("Sende ein **Bild als Datei** oder schreibe `auto`.")
                    session.pending_field_edit = "_image"
                    return
                await self._show_summary(session, ch)
                return

            if key == "_labels":
                # Labels: "casual ja", "academy nein", etc.
                if "casual" in tl:
                    session.fields["is_casual"] = any(w in tl for w in ("ja", "yes", "true", "an"))
                elif "academy" in tl:
                    session.fields["is_academy"] = any(w in tl for w in ("ja", "yes", "true", "an"))
                else:
                    await ch.send("Nicht erkannt. Schreibe z.B. `casual ja` oder `academy nein`.")
                    session.pending_field_edit = "_labels"
                    return
                await self._show_summary(session, ch)
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
                await self._show_summary(session, ch)
                return

            val = text
            if key == "camera":
                val = None if tl in ("keine pflicht", "optional", "egal", "nein", "no") else tl in ("an", "ja", "pflicht")
            elif key == "is_casual":
                val = tl in ("ja", "yes", "true")
            elif key == "max_players":
                try: val = int(val)
                except ValueError: pass
            session.fields[key] = val

            # Bei Skript-Änderung: Komplexitäts-Analyse neu laufen
            if key == "script":
                sd, _ = lookup_script(val)
                chars = sd.get("characters", []) if sd else []
                if chars:
                    analysis = analyze_script_complexity(chars)
                    session.fields["complexity_analysis"] = analysis
                    session.label = compute_label(session.fields)

            await self._show_summary(session, ch)
            return

        # ── Script-Upload ────────────────────────────────────────────
        if getattr(session, "pending_script_upload", False):
            session.touch()
            if text.lower() in ("skip", "überspringen", "s"):
                session.pending_script_upload = False
                await self._show_title_description_proposal(session, ch)
                return
            if not message.attachments:
                await ch.send("Sende die Script-JSON als Datei (.json) oder 'skip'.")
                return
            att = message.attachments[0]
            if not att.filename.endswith(".json"):
                await ch.send(f"**{att.filename}** ist keine JSON-Datei.")
                return
            try:
                data = json.loads((await att.read()).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                await ch.send("Ungültiges JSON.")
                return
            parsed, error = validate_script_json(data)
            if error:
                await ch.send(error)
                return
            name = parsed["name"]
            if name == "Custom Script" and session.fields.get("script"):
                name = session.fields["script"]
                parsed["name"] = name
            session.fields["script"] = name
            cache_script(name, parsed)
            session.pending_script_upload = False
            await ch.send(f"✅ **{name}** hochgeladen!")
            await self._show_title_description_proposal(session, ch)
            return

        # ── Script-Auswahl (Nummer ODER natürliche Sprache) ────────────
        if getattr(session, "pending_script_choices", None):
            choices = session.pending_script_choices
            tl = text.lower()

            if tl in ("skip", "überspringen", "s"):
                session.pending_script_choices = None
                await self._show_title_description_proposal(session, ch)
                return

            if tl in ("custom", "homebrew", "eigenes", "keines", "keins davon", "nichts davon"):
                session.pending_script_choices = None
                session.pending_script_upload = True
                await ch.send("Sende die **Script-JSON als Datei** (.json) oder 'skip'.")
                return

            # Direkte Nummer
            try:
                idx = int(tl) - 1
                if 0 <= idx < len(choices):
                    await self._select_script(session, ch, choices[idx])
                    return
                await ch.send(f"Bitte wähle 1-{len(choices)}.")
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

            # JSON-Upload direkt in der Script-Auswahl
            if message.attachments and message.attachments[0].filename.endswith(".json"):
                session.pending_script_choices = None
                session.pending_script_upload = True
                await self._process(session, message)
                return

            # Kein deterministischer Match → Haiku als Fallback
            async with ch.typing():
                result = await interpret_script_choice(session, text, choices)

            if not result:
                await ch.send("Das konnte ich nicht verarbeiten. Versuch es nochmal.")
                return

            action = result.get("action")

            if action == "select":
                idx = (result.get("index") or 1) - 1
                if 0 <= idx < len(choices):
                    await self._select_script(session, ch, choices[idx])
                else:
                    await ch.send(f"Nummer {idx+1} gibt es nicht. Wähle 1-{len(choices)}.")
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
                    await ch.send(f"**{term}** nicht gefunden. Versuch einen anderen Suchbegriff.")
                    session.pending_script_choices = choices
                return

            if action == "upload":
                session.pending_script_choices = None
                session.pending_script_upload = True
                await ch.send("Lade deine **Script-JSON** (.json) hoch.")
                return

            if action == "skip":
                session.pending_script_choices = None
                await self._show_title_description_proposal(session, ch)
                return

            # unclear → Haiku erklärt die Möglichkeiten
            msg = result.get("message", "")
            if msg:
                footer = _cost_footer(session)
                if footer:
                    msg += f"\n-# {footer}"
                await ch.send(msg)
            return

        # ── Titel/Beschreibung Bestätigung (Schritt 3) ───────────────
        if getattr(session, "pending_title_description", False):
            if text.lower() in CONFIRM_KEYWORDS:
                await self._show_summary(session, ch)
                return

            # Freitext → Haiku versteht was geändert werden soll
            async with ch.typing():
                result = await update_title_description(session, text)

            footer = _cost_footer(session)

            if result:
                new_title, new_desc, accepted = result
                session.fields["title"] = new_title
                session.fields["description"] = new_desc

                if accepted:
                    await self._show_summary(session, ch)
                    return

                msg = (
                    f"Aktualisiert:\n\n"
                    f"> **Titel:** {new_title}\n"
                    f"> **Beschreibung:** {new_desc}\n\n"
                    f"Passt das so? Schreibe **ok** oder passe weiter an."
                )
                if footer: msg += f"\n-# {footer}"
                await ch.send(msg)
            else:
                await ch.send("Konnte die Änderung nicht verarbeiten. Versuche es nochmal.")
            return

        # ── Summary Review (Schritt 4) ───────────────────────────────
        if getattr(session, "pending_summary", False):
            # 1. Nummer → Feld-Edit
            try:
                num = int(text)
                for i, (key, label) in enumerate(SUMMARY_FIELDS, 1):
                    if i == num:
                        if key == "script":
                            session.pending_script_edit_mode = True
                            await ch.send(
                                "Möchtest du:\n"
                                "**1** — In der Datenbank suchen\n"
                                "**2** — Selbst einen Namen eingeben"
                            )
                        elif key == "_labels":
                            await ch.send(
                                "Welches Label möchtest du ändern?\n"
                                "• `casual ja/nein`\n"
                                "• `academy ja/nein`"
                            )
                            session.pending_field_edit = "_labels"
                        elif key == "start_time":
                            await ch.send(
                                "Was möchtest du ändern?\n"
                                "• Nur Termin: z.B. `2026-03-25 20:00`\n"
                                "• Nur Dauer: z.B. `180`\n"
                                "• Beides: z.B. `2026-03-25 20:00 180min`"
                            )
                            session.pending_field_edit = "start_time"
                        elif key == "_image":
                            await ch.send(
                                "Sende ein **eigenes Bild** als Datei oder schreibe `auto` "
                                "für das automatische Skript-Bild."
                            )
                            session.pending_field_edit = "_image"
                        else:
                            session.pending_field_edit = key
                            await ch.send(f"Was soll der neue Wert für **{label}** sein?")
                        return
                await ch.send(f"Bitte wähle 1-{len(SUMMARY_FIELDS)}.")
                return
            except ValueError:
                pass

            # 2. NL-Keyword-Erkennung
            tl = text.lower()
            matched_key = None
            matched_value = None
            for keyword, field_key in FIELD_KEYWORDS.items():
                if keyword in tl:
                    matched_key = field_key
                    # Versuche einen Wert zu extrahieren (nach "in", "zu", "auf", ":")
                    import re
                    for pattern in [
                        rf'{keyword}\s+(?:in|zu|auf|:)\s+(.+)',
                        rf'(?:in|zu|auf|:)\s+(.+?)\s+{keyword}',
                        rf'{keyword}\s+ändern\s+(?:in|zu|auf|:)\s+(.+)',
                    ]:
                        m = re.search(pattern, tl)
                        if m:
                            matched_value = text[m.start(1):m.end(1)].strip()
                            break
                    break

            if matched_key:
                label = FIELD_LABELS.get(matched_key, matched_key)
                if matched_key == "script":
                    if matched_value:
                        # "Skript in XYZ ändern" → direkt setzen
                        session.fields["script"] = matched_value
                        sd, _ = lookup_script(matched_value)
                        chars = sd.get("characters", []) if sd else []
                        if chars:
                            analysis = analyze_script_complexity(chars)
                            session.fields["complexity_analysis"] = analysis
                            session.label = compute_label(session.fields)
                        await self._show_summary(session, ch)
                    else:
                        session.pending_script_edit_mode = True
                        await ch.send(
                            "Möchtest du:\n"
                            "**1** — In der Datenbank suchen\n"
                            "**2** — Selbst einen Namen eingeben"
                        )
                    return
                elif matched_value:
                    # Wert direkt setzen
                    val = matched_value
                    if matched_key == "is_casual":
                        val = val.lower() in ("ja", "yes", "true")
                    elif matched_key == "camera":
                        val = None if val.lower() in ("keine pflicht", "optional", "egal") else val.lower() in ("an", "ja", "pflicht")
                    elif matched_key in ("duration_minutes", "max_players"):
                        try: val = int(val)
                        except ValueError: pass
                    session.fields[matched_key] = val
                    await self._show_summary(session, ch)
                    return
                else:
                    # Nur Keyword erkannt, kein Wert → nachfragen
                    session.pending_field_edit = matched_key
                    await ch.send(f"Was soll der neue Wert für **{label}** sein?")
                    return

            # 3. Fallback: An Haiku senden
            async with ch.typing():
                response = await call_haiku(session, f"Der User möchte ändern: {text}\nPasse Felder an, action='done'.")
            if response and response.get("action") == "done":
                session.pending_summary = False
                await self._show_summary(session, ch)
            elif response:
                m = response.get("message", "")
                if m: await ch.send(m)
            return

        # ── Schritt 1: Haiku-Chat ────────────────────────────────────
        async with ch.typing():
            response = await call_haiku(session, text)

        if not response:
            await ch.send("Fehler. Versuche es nochmal oder `/host` neu.")
            return

        action = response.get("action", "ask")
        haiku_msg = response.get("message", "")
        footer = _cost_footer(session)

        if action == "done":
            # Schritt 1 fertig → Schritt 2 (Script)
            # Haiku-Message ignorieren — wir steuern den Flow ab hier selbst
            done_msg = f"Alles klar, Event-Daten sind komplett."
            if footer:
                done_msg += f"\n-# {footer}"
            await ch.send(done_msg)

            script_name = session.fields.get("script")
            if script_name and not session.fields.get("is_free_choice"):
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
                        await ch.send(
                            f"**{script_name}** nicht in der Datenbank gefunden.\n"
                            "Sende die **Script-JSON als Datei** (.json) hoch oder schreibe **skip**."
                        )
                        return

            # Script OK → Schritt 3 (Titel/Beschreibung)
            await self._show_title_description_proposal(session, ch)

        elif action == "refuse":
            embed = discord.Embed(description=haiku_msg, color=0xED4245)
            await ch.send(embed=embed)

        else:
            # ask
            m = f"{haiku_msg}\n-# {footer}" if footer else haiku_msg
            await ch.send(m)


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
