"""Reminder vor Eventbeginn (Thread am Event-Post) und Aufräumen alter Daten.

Ausgelöst wird „fällig und noch nicht gesendet“: Ein verpasster Reminder (Neustart, Event
kurz vor Beginn angelegt) wird nachgeholt, solange das Event noch nicht begonnen hat.
"""

import io
import json
import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from discord_ui.event_post import fetch_event_message
from events import guild_lock, reminders, service
from events.schema import BERLIN_TZ, SCRIPT_BASE, SCRIPT_FREE, ScriptRef
from events.store import EventRecord, Store
from events.templates import full_title
from logic.event_images import delete_custom_image

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MINUTES = 1
MESSAGE_LIMIT = 2000
ALLOWED_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True)


def now() -> datetime:
    return datetime.now(BERLIN_TZ)


def script_json(script: ScriptRef | None) -> list | None:
    """Skript-JSON zum Laden ins Grimoire. Basis-Skripte werden aus den IDs gebaut."""
    if script is None or script.kind == SCRIPT_FREE:
        return None
    if script.content:
        return script.content
    if script.characters:
        meta = {"id": "_meta", "name": script.name}
        if script.author and script.kind != SCRIPT_BASE:
            meta["author"] = script.author
        return [meta, *({"id": c} for c in script.characters)]
    return None


def _chunks(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Teilt lange Nachrichten (viele Pings) an Leerzeichen bzw. Zeilenumbrüchen."""
    parts = []
    while len(text) > limit:
        cut = max(text.rfind("\n", 0, limit), text.rfind(" ", 0, limit))
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip(" \n")
    if text:
        parts.append(text)
    return parts


class ReminderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store: Store = bot.store
        self.check_reminders.start()
        self.cleanup.start()

    def cog_unload(self):
        self.check_reminders.cancel()
        self.cleanup.cancel()

    # ── Schleifen ────────────────────────────────────────────────────────

    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def check_reminders(self):
        t = now()
        ts = int(t.timestamp())
        horizon = ts + (reminders.MAX_MINUTES_BEFORE + 5) * 60
        for guild_id in guild_lock.allowed_guild_ids():
            settings = self.store.get_guild_settings(guild_id)
            for event in self.store.list_events(guild_id, start_from=ts, start_until=horizon):
                configs = reminders.server_defaults(settings)  # nur global, keine Anpassung je Event
                for cfg in reminders.due(configs, event.data.start, t, self.store.sent_reminders(event.id)):
                    # Erst als gesendet markieren: lieber ein Reminder zu wenig als Spam bei Fehlern
                    self.store.mark_reminder_sent(event.id, cfg.key, ts)
                    try:
                        await self.send_reminder(event, cfg)
                    except Exception:
                        logger.exception("Reminder %s für Event %s fehlgeschlagen", cfg.key, event.id)

    @check_reminders.before_loop
    async def _before_reminders(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=1)
    async def cleanup(self):
        t = now()
        cutoff = int(t.timestamp()) - service.EVENT_RETENTION_SECONDS
        # Eigene Bilder alter Events vor dem endgültigen Löschen entfernen
        for event in self.store.list_events(start_until=cutoff):
            if event.data.custom_image:
                delete_custom_image(event.data.custom_image)
        # Eigene Bilder abgelaufener Entwürfe, die kein Event benutzt (sonst bleiben sie für immer liegen)
        for draft in self.store.stale_drafts(int(t.timestamp()) - service.DRAFT_TTL_SECONDS):
            name = draft.data.custom_image
            event = self.store.get_event(draft.event_id) if draft.event_id is not None else None
            if name and not (event and event.data.custom_image == name):
                delete_custom_image(name)
        drafts, events = service.cleanup(self.store, t)
        if drafts or events:
            logger.info("Aufgeräumt: %d Entwürfe, %d Events", drafts, events)

    @cleanup.before_loop
    async def _before_cleanup(self):
        await self.bot.wait_until_ready()

    # ── Senden ───────────────────────────────────────────────────────────

    async def _thread(self, event: EventRecord) -> discord.Thread | None:
        msg = await fetch_event_message(self.bot, event)
        if msg is None:
            logger.warning("Reminder: Event-Nachricht %s nicht gefunden", event.message_id)
            return None
        if msg.thread is not None:
            return msg.thread
        try:
            return await msg.create_thread(name=full_title(event.data)[:100])
        except discord.HTTPException as e:
            logger.warning("Reminder: Thread konnte nicht erstellt werden: %s", e)
            return None

    async def send_reminder(self, event: EventRecord, cfg: reminders.ReminderConfig):
        thread = await self._thread(event)
        if thread is None:
            return
        people = reminders.recipients(cfg, service.rsvp_lists(self.store, event), event.data)
        text = reminders.message_text(cfg, event.data.start, people, event.data.is_academy)
        for part in _chunks(text):
            await thread.send(part, allowed_mentions=ALLOWED_MENTIONS)

        if cfg.post_script:
            content = script_json(event.data.script)
            if content is not None:
                name = event.data.script.display_name
                safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip() or "script"
                data = json.dumps(content, indent=2, ensure_ascii=False).encode("utf-8")
                await thread.send(f"Hier ist das Skript **{discord.utils.escape_markdown(name)}** zum Laden:",
                                  file=discord.File(io.BytesIO(data), filename=f"{safe}.json"))

        if cfg.post_attendance and any(not reminders.same_person(p, event.data.storyteller) for p in people):
            data = reminders.attendance_txt(event.data, people).encode("utf-8")
            await thread.send("Anwesenheitsliste zum Abhaken:",
                              file=discord.File(io.BytesIO(data), filename=reminders.ATTENDANCE_FILENAME))
        logger.info("Reminder %s für Event %s gesendet (%d Empfänger)", cfg.key, event.id, len(people))

    # ── Commands ─────────────────────────────────────────────────────────

    async def _check(self, interaction: discord.Interaction) -> bool:
        """Erinnerungen legen nur Server-Admins fest, global für alle Runden (Dalyan, 20.10.2026)."""
        if interaction.user.guild_permissions.manage_guild:
            return True
        await interaction.response.send_message("Das dürfen nur Admins (Server verwalten).", ephemeral=True)
        return False

    def _summary(self, guild_id: int) -> str:
        cfgs = reminders.server_defaults(self.store.get_guild_settings(guild_id))
        lines = ["**Reminder-Standard für diesen Server**"]
        lines += [f"{i}. {reminders.describe(cfgs[k])}" for i, k in enumerate(reminders.KEYS, 1)]
        lines.append("-# Gilt für alle Runden dieses Servers. Ändern können das nur Admins.")
        return "\n".join(lines)

    @app_commands.command(name="set_reminders", description="Reminder für alle Runden festlegen (nur Admins)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        reminder="Welcher Reminder",
        aktiv="Reminder senden?",
        minuten="Wie viele Minuten vor Beginn",
        benachrichtigung="Mit Ping oder nur mit Namen",
        zusagen="Zusagen benachrichtigen",
        warteliste="Warteliste benachrichtigen",
        vorlaeufig="Vorläufige bzw. Auffüller benachrichtigen",
        co_st="Co-Storyteller benachrichtigen",
        storyteller="Storyteller benachrichtigen",
        skript_json="Skript-JSON in den Thread posten",
        anwesenheitsliste="Anwesenheitsliste (anwesenheit.txt) zum Abhaken in den Thread posten",
        zuruecksetzen="Diesen Reminder auf den eingebauten Standard zurücksetzen",
    )
    @app_commands.choices(
        reminder=[app_commands.Choice(name="1. Erinnerung", value=reminders.FIRST),
                  app_commands.Choice(name="2. Anwesenheitskontrolle", value=reminders.SECOND)],
        benachrichtigung=[app_commands.Choice(name="Ping", value=reminders.MODE_PING),
                          app_commands.Choice(name="nur Namen (kein Ping)", value=reminders.MODE_NAMES)],
    )
    @app_commands.guild_only()
    async def set_reminders(self, interaction: discord.Interaction, reminder: app_commands.Choice[str],
                            aktiv: bool | None = None,
                            minuten: app_commands.Range[int, 0, reminders.MAX_MINUTES_BEFORE] | None = None,
                            benachrichtigung: app_commands.Choice[str] | None = None,
                            zusagen: bool | None = None, warteliste: bool | None = None,
                            vorlaeufig: bool | None = None, co_st: bool | None = None,
                            storyteller: bool | None = None,
                            skript_json: bool | None = None, anwesenheitsliste: bool | None = None,
                            zuruecksetzen: bool | None = None):
        if not await self._check(interaction):
            return
        settings = self.store.get_guild_settings(interaction.guild_id)
        key = reminder.value
        cfg = reminders.copy_of(reminders.DEFAULTS[key] if zuruecksetzen else reminders.server_defaults(settings)[key])
        if aktiv is not None:
            cfg.enabled = aktiv
        if minuten is not None:
            cfg.minutes_before = minuten
        if benachrichtigung is not None:
            cfg.mode = benachrichtigung.value
        to = list(cfg.recipients)
        for flag, value in ((zusagen, reminders.TO_ACCEPTED), (warteliste, reminders.TO_WAITLIST),
                            (vorlaeufig, reminders.TO_TENTATIVE), (co_st, reminders.TO_CO),
                            (storyteller, reminders.TO_ST)):
            if flag is True and value not in to:
                to.append(value)
            elif flag is False and value in to:
                to.remove(value)
        cfg.recipients = [r for r in reminders.RECIPIENTS if r in to]
        if skript_json is not None:
            cfg.post_script = skript_json
        if anwesenheitsliste is not None:
            cfg.post_attendance = anwesenheitsliste
        errors = reminders.validate(cfg)
        if errors:
            await interaction.response.send_message(" ".join(errors), ephemeral=True)
            return
        self.store.set_guild_settings(interaction.guild_id, reminders.store_server_choice(settings, cfg))
        await interaction.response.send_message(self._summary(interaction.guild_id), ephemeral=True)

    @app_commands.command(name="see_reminders", description="Zeigt die Standard-Reminder dieses Servers")
    @app_commands.guild_only()
    async def see_reminders(self, interaction: discord.Interaction):
        if not await self._check(interaction):
            return
        await interaction.response.send_message(self._summary(interaction.guild_id), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ReminderCog(bot))
