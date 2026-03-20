"""Slash-Command /host und DM-Listener für die Event-Erstellung."""

import json
import logging
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
)
from logic.label import (
    FREE_CHOICE_DESCRIPTION,
    LABEL_DESCRIPTION,
    LABEL_EMOJI,
    compute_label,
    get_label_emoji,
)
from logic.botcscripts import search_scripts
from logic.script_cache import cache_script, is_base_script, lookup_script, validate_script_json
from logic.event_builder import build_event_embed

logger = logging.getLogger(__name__)

BERLIN_TZ = ZoneInfo("Europe/Berlin")


# ── Helper Functions ─────────────────────────────────────────────────────────


def _build_preview_embed(session) -> discord.Embed:
    """Baut ein Vorschau-Embed aus den Session-Feldern."""
    fields = session.fields
    label = session.label
    is_free = bool(fields.get("is_free_choice"))
    emoji = get_label_emoji(label, is_free_choice=is_free)

    title = fields.get("title") or "BotC Event"
    if emoji:
        title = f"{emoji} {title}"

    embed = discord.Embed(title=title, description=fields.get("description") or "", color=0x5865F2)

    embed.add_field(name="Storyteller:in", value=fields.get("storyteller") or "-", inline=False)

    script_display = fields.get("script") or "-"
    if is_free:
        script_display = "Freie Skriptwahl"
    elif fields.get("script_version"):
        script_display += f" (v{fields['script_version']})"
    embed.add_field(name="Skript:", value=script_display, inline=False)

    embed.add_field(name="Level:", value=fields.get("level") or "-", inline=False)

    start_time = fields.get("start_time")
    embed.add_field(name="Termin:", value=start_time or "-", inline=False)

    # Zusatzinfos zusammenbauen
    extras = []
    if fields.get("co_storyteller"):
        extras.append(f"Co-ST: {fields['co_storyteller']}")
    if fields.get("camera") is not None:
        extras.append(f"Kamera: {'an' if fields['camera'] else 'aus'}")
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


def _build_script_choice_embed(results: list[dict]) -> discord.Embed:
    """Baut ein Embed mit nummerierten Script-Suchergebnissen."""
    count = len(results)
    embed = discord.Embed(
        title="Skript-Suche",
        description=f"Ich habe folgende Skripte gefunden. Antworte mit der Nummer (1-{count}):",
        color=0x5865F2,
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
    embed.set_footer(text=f"Antworte mit 1-{count} um ein Skript auszuwählen, oder 'skip' zum Überspringen.")
    return embed


def _parse_start_time(time_str: str) -> int | None:
    """Parst einen ISO-Zeitstring (YYYY-MM-DD HH:MM) in einen Unix-Timestamp."""
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


async def _resolve_script(session, channel: discord.DMChannel) -> bool:
    """Resolved das Script via Cache/API. Gibt True zurück wenn bereit für Vorschau.

    Bei Cache-Miss wird der Script-Auswahl-Flow oder Upload-Flow gestartet
    und False zurückgegeben (der on_message Handler übernimmt dann).
    """
    # Freie Skriptwahl → kein Lookup nötig
    if session.fields.get("is_free_choice"):
        logger.info("Freie Skriptwahl — Script-Lookup übersprungen")
        return True

    script_name = session.fields.get("script")
    if not script_name:
        return True  # Kein Script → direkt weiter

    script_data, source = lookup_script(script_name)

    if source in ("base", "cache", "cache_stale"):
        logger.info("Script '%s' aufgelöst via %s", script_name, source)
        return True

    # Cache Miss → botcscripts.com durchsuchen
    logger.info("Script '%s' nicht im Cache, suche auf botcscripts.com", script_name)

    async with channel.typing():
        results = await search_scripts(script_name, limit=5)

    if not results:
        # Nichts gefunden → Upload anbieten
        session.pending_script_upload = True
        await channel.send(
            f"Ich konnte **{script_name}** nicht auf botcscripts.com finden.\n\n"
            "Du kannst:\n"
            "• Die **Script-JSON als Datei** hochladen (Anhang senden)\n"
            "• **'skip'** schreiben um ohne Script-Details fortzufahren"
        )
        return False

    # Ergebnisse speichern für die Auswahl
    session.pending_script_choices = results
    embed = _build_script_choice_embed(results)
    await channel.send(embed=embed)
    return False  # Warte auf User-Auswahl


def _handle_script_choice(session, choice_text: str) -> str | None:
    """Verarbeitet die Script-Auswahl des Users.

    Returns:
        Antwort-Text für die DM, oder None wenn die Auswahl erfolgreich war.
    """
    choices = getattr(session, "pending_script_choices", None)
    if not choices:
        return "Keine Skript-Auswahl ausstehend."

    text = choice_text.strip().lower()

    if text in ("skip", "überspringen", "s"):
        session.pending_script_choices = None
        logger.info("Script-Auswahl übersprungen")
        return None  # Erfolgreich (übersprungen)

    try:
        idx = int(text) - 1
    except ValueError:
        return f"Bitte antworte mit einer Zahl von 1 bis {len(choices)}, oder 'skip' zum Überspringen."

    if not (0 <= idx < len(choices)):
        return f"Bitte wähle eine Nummer von 1 bis {len(choices)}."

    chosen = choices[idx]
    session.fields["script"] = chosen["name"]

    # Im Cache speichern
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
    logger.info("Script ausgewählt: '%s' (id=%s)", chosen["name"], chosen.get("botcscripts_id"))
    return None  # Erfolgreich


async def _handle_script_upload(session, message: discord.Message) -> tuple[bool, str]:
    """Verarbeitet einen Script-JSON-Upload.

    Returns:
        (success, response_text)
    """
    text = message.content.strip().lower()

    # Skip
    if text in ("skip", "überspringen", "s"):
        session.pending_script_upload = False
        return True, ""

    # Attachment prüfen
    if not message.attachments:
        return False, (
            "Bitte sende die Script-JSON als Datei-Anhang (.json), "
            "oder schreibe 'skip' um fortzufahren."
        )

    attachment = message.attachments[0]

    # Dateiformat prüfen
    if not attachment.filename.endswith(".json"):
        return False, (
            f"**{attachment.filename}** ist keine JSON-Datei. "
            "Bitte sende eine Datei mit `.json`-Endung."
        )

    # Datei lesen und parsen
    try:
        raw_bytes = await attachment.read()
        data = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Script-Upload JSON-Fehler: %s", e)
        return False, "Die Datei enthält kein gültiges JSON. Bitte prüfe das Format."

    # Validieren
    parsed, error = validate_script_json(data)
    if error:
        return False, error

    # Script-Name aus Meta oder Session übernehmen
    script_name = parsed["name"]
    if script_name == "Custom Script" and session.fields.get("script"):
        script_name = session.fields["script"]
        parsed["name"] = script_name

    session.fields["script"] = script_name

    # Im Cache speichern
    cache_script(script_name, parsed)

    session.pending_script_upload = False
    logger.info("Script hochgeladen: '%s' (%d Charaktere)", script_name, len(parsed["characters"]))
    return True, f"✅ **{script_name}** hochgeladen ({len(parsed['characters'])} Charaktere)!"


# ── Views ────────────────────────────────────────────────────────────────────


class ConfirmEventView(discord.ui.View):
    """Bestätigungs-Buttons nach dem Vorschau-Embed in der DM."""

    def __init__(self, cog: "HostCommand", session):
        super().__init__(timeout=300)  # 5 Minuten Timeout
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Erstellen", emoji="✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()

        fields = self.session.fields
        label = self.session.label
        is_free = bool(fields.get("is_free_choice"))
        emoji = get_label_emoji(label, is_free_choice=is_free)

        # Zeitstempel parsen
        start_ts = _parse_start_time(fields.get("start_time") or "")
        if start_ts is None:
            await interaction.followup.send(
                "Fehler: Konnte den Termin nicht verarbeiten. "
                "Bitte starte den Vorgang erneut mit `/host`."
            )
            end_session(self.session.user_id)
            return

        # End-Timestamp berechnen
        duration = fields.get("duration_minutes") or 180  # Default: 3 Stunden
        end_ts = start_ts + (duration * 60)

        # Titel mit Label-Emoji
        title = fields.get("title") or "BotC Event"
        if emoji:
            title = f"{emoji} {title}"

        # Script-Anzeige
        script_display = fields.get("script") or "-"
        if is_free:
            script_display = "Freie Skriptwahl"
        elif fields.get("script_version"):
            script_display += f" (v{fields['script_version']})"

        # Zusatzinfos
        extras = []
        if fields.get("co_storyteller"):
            extras.append(f"Co-ST: {fields['co_storyteller']}")
        if fields.get("camera") is not None:
            extras.append(f"Kamera: {'an' if fields['camera'] else 'aus'}")
        if fields.get("max_players"):
            extras.append(f"Max Spieler: {fields['max_players']}")
        if fields.get("duration_minutes"):
            h, m = divmod(fields["duration_minutes"], 60)
            extras.append(f"Dauer: {h}h {m:02d}min" if h else f"Dauer: {m}min")

        # Event-Daten für post_event()
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

        # Event posten
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
            await interaction.followup.send(
                f"Event erstellt! 🎉\n{msg.jump_url}"
            )
            logger.info(
                "Event via /host erstellt: '%s' von %s (msg_id=%s)",
                title, self.session.user_display_name, msg.id,
            )
        except Exception as e:
            logger.error("Fehler beim Event-Posten: %s", e)
            await interaction.followup.send(f"Fehler beim Erstellen des Events: {e}")

        end_session(self.session.user_id)

    @discord.ui.button(label="Ändern", emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        # Weiter im Konversations-Flow
        response = await call_haiku(
            self.session,
            "Ich möchte etwas ändern. Was kann ich anpassen?",
        )
        if response:
            await interaction.response.send_message(response.get("message", "Was möchtest du ändern?"))
        else:
            await interaction.response.send_message("Was möchtest du ändern? Schreib mir einfach.")

    @discord.ui.button(label="Abbrechen", emoji="❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        end_session(self.session.user_id)
        await interaction.response.send_message("Event-Erstellung abgebrochen.")

    async def on_timeout(self):
        end_session(self.session.user_id)


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
            await interaction.response.send_message(
                "Dieser Befehl kann nur in einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        # Event-Channel prüfen
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
            await interaction.response.send_message(
                "Der konfigurierte Event-Channel wurde nicht gefunden.",
                ephemeral=True,
            )
            return

        # Aktive Session prüfen
        if has_active_session(interaction.user.id):
            await interaction.response.send_message(
                "Du hast bereits eine aktive Event-Erstellung. "
                "Schau in deine DMs oder warte 30 Minuten bis die Session abläuft.",
                ephemeral=True,
            )
            return

        # Session erstellen
        session = start_session(
            user_id=interaction.user.id,
            guild_id=guild.id,
            guild_name=guild.name,
            event_channel_id=event_channel_id,
            user_display_name=interaction.user.display_name,
        )

        # Ephemeral-Bestätigung im Channel
        await interaction.response.send_message(
            "Check deine DMs! 📩 Ich führe dich dort durch die Event-Erstellung.",
            ephemeral=True,
        )

        # DM senden + Konversation starten
        try:
            dm_channel = await interaction.user.create_dm()

            await dm_channel.send(
                f"Hey {interaction.user.display_name}! 👋\n"
                f"Lass uns ein Event für **{guild.name}** erstellen.\n"
                f"Beschreib mir dein Event — z.B. Skript, Termin, Level, ob du ST bist, etc.\n"
                f"Du kannst alles in einer Nachricht schreiben oder Stück für Stück."
            )

            logger.info("/host ausgeführt: user=%s, guild=%s", interaction.user, guild.name)

        except discord.Forbidden:
            await interaction.followup.send(
                "Ich kann dir keine DM senden. "
                "Bitte aktiviere DMs von Server-Mitgliedern in deinen Einstellungen.",
                ephemeral=True,
            )
            end_session(interaction.user.id)

    async def _show_preview(self, session, channel: discord.DMChannel, haiku_message: str = ""):
        """Zeigt die Event-Vorschau mit Bestätigungs-Buttons."""
        session.label = compute_label(session.fields)
        preview = _build_preview_embed(session)
        confirm_view = ConfirmEventView(self, session)

        if haiku_message:
            await channel.send(content=haiku_message)
        await channel.send(
            content="**Hier ist die Vorschau deines Events:**",
            embed=preview,
            view=confirm_view,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Lauscht auf DMs von Usern mit aktiver Session."""
        # Nur DMs verarbeiten
        if not isinstance(message.channel, discord.DMChannel):
            return

        # Eigene Nachrichten ignorieren
        if message.author.bot:
            return

        # Session suchen
        session = get_session(message.author.id)
        if session is None:
            return  # Keine aktive Session → ignorieren

        logger.debug("DM von %s: %s", message.author, message.content[:100])

        # Script-Upload ausstehend?
        if getattr(session, "pending_script_upload", False):
            success, response_text = await _handle_script_upload(session, message)
            if not success:
                await message.channel.send(response_text)
                return

            # Upload erfolgreich → Vorschau zeigen
            if response_text:
                await message.channel.send(response_text)
            await self._show_preview(session, message.channel)
            return

        # Script-Auswahl ausstehend?
        if getattr(session, "pending_script_choices", None):
            error_msg = _handle_script_choice(session, message.content)
            if error_msg:
                await message.channel.send(error_msg)
                return

            # Auswahl erfolgreich → Vorschau zeigen
            chosen_name = session.fields.get("script", "")
            await message.channel.send(f"✅ **{chosen_name}** ausgewählt!")
            await self._show_preview(session, message.channel)
            return

        # Normaler Konversations-Flow
        async with message.channel.typing():
            response = await call_haiku(session, message.content)

        if response is None:
            await message.channel.send(
                "Entschuldigung, es gab einen Fehler bei der Verarbeitung. "
                "Bitte versuche es nochmal oder starte mit `/host` neu."
            )
            return

        action = response.get("action", "ask")
        haiku_message = response.get("message", "")

        if action == "done":
            # Script resolven bevor Vorschau gezeigt wird
            ready = await _resolve_script(session, message.channel)
            if ready:
                await self._show_preview(session, message.channel, haiku_message)
            else:
                # Script-Auswahl/Upload läuft → haiku_message trotzdem senden
                if haiku_message:
                    await message.channel.send(haiku_message)

        elif action == "refuse":
            await message.channel.send(
                f"{haiku_message}\n\n"
                "💡 Ich kann dir nur bei der Event-Erstellung helfen. "
                "Beschreib mir dein BotC-Event!"
            )

        else:
            # ask / explain
            if haiku_message:
                await message.channel.send(haiku_message)


async def setup(bot: commands.Bot):
    await bot.add_cog(HostCommand(bot))
