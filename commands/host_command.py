"""Slash-Command /host — Event-Erstellung via DM.

3-Phasen-Flow:
A) Eingabe: Plain-Text Chat mit Haiku (max 1-2 Nachrichten)
B) Script-Validierung: 1 Embed wenn Script nicht im Cache (isoliert)
C) Zusammenfassung: 1 Embed mit allem + Buttons (Erstellen/Abbrechen)
"""

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
    generate_description,
    get_session,
    has_active_session,
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
from logic.script_cache import (
    cache_script,
    is_base_script,
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
CONFIRM_KEYWORDS = {"ok", "fertig", "bestätigen", "confirm", "ja", "yes"}

# Felder für den Summary-Review (Nummer → Key → Label)
SUMMARY_FIELDS = [
    ("title", "Titel"),
    ("description", "Beschreibung"),
    ("storyteller", "Storyteller:in"),
    ("script", "Skript"),
    ("level", "Level"),
    ("start_time", "Termin"),
    ("duration_minutes", "Dauer"),
    ("max_players", "Max Spieler"),
    ("camera", "Kamera"),
    ("co_storyteller", "Co-ST"),
    ("is_casual", "Casual 🕊️"),
]


def _cost_footer(session) -> str:
    if os.getenv("ENV") != "dev":
        return ""
    return (
        f"💰 Nachricht {session.call_count} · "
        f"{session.total_input_tokens} in / {session.total_output_tokens} out · "
        f"${session.total_cost_usd:.4f}"
    )


def _format_field_value(key: str, value) -> str:
    if value is None:
        if key == "camera":
            return "keine Pflicht"
        if key == "co_storyteller":
            return "Nicht möglich"
        if key == "is_casual":
            return "Nein"
        return "-"
    if key == "camera":
        return "Pflicht" if value is True else ("Aus" if value is False else "keine Pflicht")
    if key == "is_casual":
        return "Ja 🕊️" if value else "Nein"
    if key == "duration_minutes":
        h, m = divmod(int(value), 60)
        return f"{h}h {m:02d}min" if h else f"{m}min"
    return str(value)


def _parse_start_time(time_str: str) -> int | None:
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"]:
        try:
            dt = datetime.strptime(time_str, fmt).replace(tzinfo=BERLIN_TZ)
            return int(dt.timestamp())
        except ValueError:
            continue
    return None


def _categorize_characters(char_ids: list[str]) -> dict[str, list[str]]:
    characters_db = load_characters()
    categories = {"Townsfolk": [], "Outsider": [], "Minion": [], "Demon": [],
                  "Traveller": [], "Fabled": [], "Loric": [], "Weitere": []}
    type_map = {"Townsfolk": "Townsfolk", "Outsider": "Outsider", "Minion": "Minion",
                "Demon": "Demon", "Traveller": "Traveller", "Fabled": "Fabled", "Loric": "Loric"}
    for char_id in char_ids:
        char_info = characters_db.get(char_id)
        if char_info:
            cat = type_map.get(char_info.get("character_type", ""), "Weitere")
            categories[cat].append(char_info.get("character_name", char_id))
        else:
            categories["Weitere"].append(char_id)
    return categories


# ── Summary Embed (Phase C) ─────────────────────────────────────────────────


def _build_summary_embed(session, script_data: dict | None = None) -> discord.Embed:
    """Baut DAS eine Summary-Embed mit Script-Info + allen Feldern + Description."""
    fields = session.fields
    is_free = bool(fields.get("is_free_choice"))

    embed = discord.Embed(title="📋 Event-Zusammenfassung", color=BOT_COLOR)

    # Script-Info (wenn verfügbar)
    if script_data and not is_free:
        script_name = script_data.get("name", fields.get("script", ""))
        author = script_data.get("author", "")
        version = script_data.get("version", "")
        chars = script_data.get("characters", [])

        script_info = f"**📜 {script_name}**"
        if author:
            script_info += f" von {author}"
        if version:
            script_info += f" · v{version}"
        if chars:
            script_info += f" · {len(chars)} Charaktere"
        embed.description = script_info

        # Kurze Charakter-Zusammenfassung
        cats = _categorize_characters(chars)
        char_lines = []
        for cat_name, char_list in cats.items():
            if char_list:
                char_lines.append(f"**{cat_name}:** {', '.join(char_list[:8])}")
                if len(char_list) > 8:
                    char_lines[-1] += f" (+{len(char_list) - 8})"
        if char_lines:
            embed.add_field(name="Charaktere", value="\n".join(char_lines), inline=False)

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    # Event-Felder als inline 3er-Reihen
    embed.add_field(name="1 · Titel", value=f"```{fields.get('title') or '-'}```", inline=True)
    embed.add_field(name="3 · Storyteller:in", value=f"```{fields.get('storyteller') or '-'}```", inline=True)
    embed.add_field(name="5 · Level", value=f"```{fields.get('level') or '-'}```", inline=True)

    embed.add_field(name="6 · Termin", value=f"```{fields.get('start_time') or '-'}```", inline=True)
    dur = _format_field_value("duration_minutes", fields.get("duration_minutes"))
    embed.add_field(name="7 · Dauer", value=f"```{dur}```", inline=True)
    embed.add_field(name="8 · Max Spieler", value=f"```{fields.get('max_players') or 12}```", inline=True)

    cam = _format_field_value("camera", fields.get("camera"))
    co_st = _format_field_value("co_storyteller", fields.get("co_storyteller"))
    casual = _format_field_value("is_casual", fields.get("is_casual"))
    embed.add_field(name="9 · Kamera", value=f"```{cam}```", inline=True)
    embed.add_field(name="10 · Co-ST", value=f"```{co_st}```", inline=True)
    embed.add_field(name="11 · Casual 🕊️", value=f"```{casual}```", inline=True)

    # Beschreibung
    desc = fields.get("description") or "*Wird automatisch generiert*"
    if len(desc) > 1010:
        desc = desc[:1007] + "..."
    embed.add_field(name="2 · Beschreibung", value=f"```{desc}```", inline=False)

    # Footer
    footer = _cost_footer(session)
    footer_text = "Antworte mit einer Nummer zum Ändern oder drücke ✅"
    if footer:
        footer_text = f"{footer_text}\n{footer}"
    embed.set_footer(text=footer_text)

    return embed


# ── Script Choice Embed (Phase B) ───────────────────────────────────────────


def _build_script_choice_embed(script_name: str, results: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title=f"🔍 Skript-Suche: \"{script_name}\"",
        color=BOT_COLOR,
    )
    for i, result in enumerate(results, 1):
        author = result.get("author") or "?"
        version = result.get("version") or "?"
        chars = result.get("characters", [])
        count = f" · {len(chars)} Chars" if chars else ""
        embed.add_field(
            name=f"{i}. {result['name']}",
            value=f"von {author} · v{version}{count}",
            inline=False,
        )
    embed.set_footer(text="Antworte mit 1-5, 'custom' für eigenes Script, oder 'skip'.")
    return embed


# ── Views ────────────────────────────────────────────────────────────────────


class SummaryView(discord.ui.View):
    """Erstellen/Abbrechen Buttons im Summary-Embed."""

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
        is_free = bool(fields.get("is_free_choice"))

        # Label berechnen
        self.session.label = compute_label(fields)
        label = self.session.label
        emoji = get_label_emoji(label, is_free_choice=is_free)

        # Zeitstempel
        start_ts = _parse_start_time(fields.get("start_time") or "")
        if start_ts is None:
            await interaction.followup.send("Fehler: Termin konnte nicht verarbeitet werden.")
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

        # Script-Daten für Embed
        script_characters = []
        script_url = None
        if not is_free and fields.get("script"):
            sd, _ = lookup_script(fields["script"])
            if sd:
                script_characters = sd.get("characters", [])
                bid = sd.get("botcscripts_id")
                ver = sd.get("version")
                if bid and ver:
                    script_url = f"https://www.botcscripts.com/script/{bid}/{ver}"

        event_data = {
            "title": title,
            "description": fields.get("description"),
            "storyteller": fields.get("storyteller") or "-",
            "co_storyteller": fields.get("co_storyteller"),
            "script": script_display,
            "script_url": script_url,
            "script_characters": script_characters,
            "level": fields.get("level") or "Alle",
            "camera": fields.get("camera"),
            "max_players": fields.get("max_players") or 12,
            "timestamp": start_ts,
            "end_timestamp": end_ts,
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

        # Script-Bild generieren
        script_file = None
        if script_characters and not is_free:
            try:
                sd, _ = lookup_script(fields["script"])
                img = await generate_script_image(
                    fields.get("script", ""), (sd or {}).get("author", ""),
                    script_characters, (sd or {}).get("version", ""),
                )
                script_file = discord.File(img, filename="script.png")
            except Exception as e:
                logger.warning("Script-Bild Fehler: %s", e)

        try:
            msg = await event_cog.post_event(event_channel, event_data, script_image=script_file)
            await interaction.followup.send(f"Event erstellt! 🎉\n{msg.jump_url}")
            logger.info("Event erstellt: '%s' (msg_id=%s)", title, msg.id)
        except Exception as e:
            logger.error("Fehler: %s", e)
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
            await self.dm_channel.send("⏰ Abgelaufen. Starte mit `/host` neu.")
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
                "Kein Event-Channel konfiguriert (`/set_event_channel`).", ephemeral=True)
            return

        if not self.bot.get_channel(event_channel_id):
            await interaction.response.send_message("Event-Channel nicht gefunden.", ephemeral=True)
            return

        if has_active_session(interaction.user.id):
            await interaction.response.send_message(
                "Du hast bereits eine aktive Session. Schreibe **abbrechen** in den DMs.", ephemeral=True)
            return

        session = start_session(
            user_id=interaction.user.id,
            guild_id=guild.id,
            guild_name=guild.name,
            event_channel_id=event_channel_id,
            user_display_name=interaction.user.display_name,
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
            await interaction.followup.send("Kann keine DM senden. Aktiviere DMs.", ephemeral=True)
            end_session(interaction.user.id)

    # ── Phase C: Summary anzeigen ────────────────────────────────────

    async def _show_summary(self, session, channel):
        """Zeigt das Summary-Embed mit Buttons. Generiert Description wenn nötig."""
        # Description generieren wenn noch nicht vorhanden
        if not session.fields.get("description"):
            async with channel.typing():
                desc = await generate_description(session)
            if desc:
                session.fields["description"] = desc

        # Script-Daten laden
        script_data = None
        script_name = session.fields.get("script")
        if script_name and not session.fields.get("is_free_choice"):
            script_data, _ = lookup_script(script_name)

        # Defaults setzen wenn nicht vorhanden
        session.fields.setdefault("max_players", 12)
        session.fields.setdefault("duration_minutes", 150)

        embed = _build_summary_embed(session, script_data)
        view = SummaryView(self, session, channel)

        session.pending_summary = True
        await channel.send(embed=embed, view=view)

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
            await self._process_message(session, message)

    async def _process_message(self, session, message: discord.Message):
        channel = message.channel

        # ── Feld-Edit ausstehend (aus Summary) ──────────────────────
        if getattr(session, "pending_field_edit", None):
            key = session.pending_field_edit
            session.pending_field_edit = None
            value = message.content.strip()

            # Typ-Konvertierung
            if key == "camera":
                if value.lower() in ("keine pflicht", "optional", "egal"):
                    value = None
                else:
                    value = value.lower() in ("an", "ja", "on", "true", "pflicht")
            elif key == "is_casual":
                value = value.lower() in ("ja", "yes", "true")
            elif key in ("duration_minutes", "max_players"):
                try:
                    value = int(value)
                except ValueError:
                    pass

            session.fields[key] = value
            await self._show_summary(session, channel)
            return

        # ── Script-Upload ausstehend ─────────────────────────────────
        if getattr(session, "pending_script_upload", False):
            session.touch()
            text = message.content.strip().lower()

            if text in ("skip", "überspringen", "s"):
                session.pending_script_upload = False
                await self._show_summary(session, channel)
                return

            if not message.attachments:
                await channel.send("Sende die Script-JSON als Datei (.json) oder 'skip'.")
                return

            att = message.attachments[0]
            if not att.filename.endswith(".json"):
                await channel.send(f"**{att.filename}** ist keine JSON-Datei.")
                return

            try:
                data = json.loads((await att.read()).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                await channel.send("Ungültiges JSON.")
                return

            parsed, error = validate_script_json(data)
            if error:
                await channel.send(error)
                return

            name = parsed["name"]
            if name == "Custom Script" and session.fields.get("script"):
                name = session.fields["script"]
                parsed["name"] = name
            session.fields["script"] = name
            cache_script(name, parsed)
            session.pending_script_upload = False
            await channel.send(f"✅ **{name}** hochgeladen!")
            await self._show_summary(session, channel)
            return

        # ── Script-Auswahl ausstehend (Phase B) ─────────────────────
        if getattr(session, "pending_script_choices", None):
            choices = session.pending_script_choices
            text = message.content.strip().lower()

            if text in ("skip", "überspringen", "s"):
                session.pending_script_choices = None
                await self._show_summary(session, channel)
                return

            if text in ("custom", "homebrew", "eigenes"):
                session.pending_script_choices = None
                session.pending_script_upload = True
                await channel.send("Sende die **Script-JSON als Datei** (.json) oder 'skip'.")
                return

            try:
                idx = int(text) - 1
                if 0 <= idx < len(choices):
                    chosen = choices[idx]
                    session.fields["script"] = chosen["name"]
                    cache_script(chosen["name"], {
                        "name": chosen["name"],
                        "author": chosen.get("author", ""),
                        "version": chosen.get("version", ""),
                        "botcscripts_id": chosen.get("botcscripts_id", ""),
                        "characters": chosen.get("characters", []),
                        "url": chosen.get("url", ""),
                        "source": "botcscripts",
                    })
                    session.pending_script_choices = None
                    await channel.send(f"✅ **{chosen['name']}** ausgewählt!")
                    await self._show_summary(session, channel)
                    return
                else:
                    await channel.send(f"Bitte wähle 1-{len(choices)}.")
                    return
            except ValueError:
                await channel.send(f"Antworte mit 1-{len(choices)}, 'custom' oder 'skip'.")
                return

        # ── Summary-Review ausstehend (Phase C) ─────────────────────
        if getattr(session, "pending_summary", False):
            text = message.content.strip()
            text_lower = text.lower()

            # Nummer → Feld editieren
            try:
                number = int(text_lower)
                for i, (key, label) in enumerate(SUMMARY_FIELDS, 1):
                    if i == number:
                        session.pending_field_edit = key
                        await channel.send(f"Was soll der neue Wert für **{label}** sein?")
                        return
                await channel.send(f"Bitte wähle 1-{len(SUMMARY_FIELDS)}.")
                return
            except ValueError:
                pass

            # Freitext-Korrektur → an Haiku senden
            async with channel.typing():
                response = await call_haiku(
                    session, f"Der User möchte ändern: {text}\nPasse die Felder an, action='done'."
                )
            if response and response.get("action") == "done":
                session.pending_summary = False
                await self._show_summary(session, channel)
            elif response:
                haiku_msg = response.get("message", "")
                if haiku_msg:
                    await channel.send(haiku_msg)
            return

        # ── Phase A: Normaler Haiku-Chat ─────────────────────────────
        async with channel.typing():
            response = await call_haiku(session, message.content)

        if response is None:
            await channel.send("Fehler bei der Verarbeitung. Versuche es nochmal oder `/host` neu.")
            return

        action = response.get("action", "ask")
        haiku_message = response.get("message", "")
        footer = _cost_footer(session)

        if action == "done":
            # Phase A fertig → Phase B (Script) → Phase C (Summary)
            if haiku_message:
                msg = f"{haiku_message}\n-# {footer}" if footer else haiku_message
                await channel.send(msg)

            # Script validieren (Phase B)
            script_name = session.fields.get("script")
            if script_name and not session.fields.get("is_free_choice"):
                _, source = lookup_script(script_name)
                if source == "miss":
                    # Nicht im Cache → botcscripts.com suchen
                    async with channel.typing():
                        results = await search_scripts(script_name, limit=5)
                    session.touch()

                    if results:
                        session.pending_script_choices = results
                        embed = _build_script_choice_embed(script_name, results)
                        await channel.send(embed=embed)
                        return
                    else:
                        session.pending_script_upload = True
                        await channel.send(
                            f"**{script_name}** nicht gefunden.\n"
                            "Sende die **Script-JSON als Datei** oder 'skip'."
                        )
                        return

            # Script OK oder nicht nötig → Summary (Phase C)
            await self._show_summary(session, channel)

        elif action == "refuse":
            embed = discord.Embed(title="⚠️", description=haiku_message, color=0xED4245)
            await channel.send(embed=embed)

        else:
            # ask
            if haiku_message:
                msg = f"{haiku_message}\n-# {footer}" if footer else haiku_message
                await channel.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(HostCommand(bot))
