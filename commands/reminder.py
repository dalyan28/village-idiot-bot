"""Event-Reminder — erstellt Thread im Eventchannel vor Event-Start.

Ablauf:
- 15 Min vor Start: Thread erstellen, alle Zusagen pingen, Script-JSON posten
- 5 Min vor Start: Anwesenheitskontrolle mit Teilnehmerliste für den ST
"""

import io
import json
import logging
import time

import discord
from discord.ext import commands, tasks

from event_storage import load_events, save_event
from logic.botcscripts import fetch_script_json

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MINUTES = 2

# Reminder-Fenster (Sekunden vor Event-Start)
REMINDER_15_MIN = (13 * 60, 17 * 60)  # 13-17 Min → trifft ~15 Min
REMINDER_5_MIN = (3 * 60, 7 * 60)     # 3-7 Min → trifft ~5 Min


class ReminderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def check_reminders(self):
        """Prüft alle Events und sendet Reminder für bald startende."""
        events = load_events()
        now = int(time.time())

        for msg_id, event in events.items():
            if event.get("deleted_at"):
                continue

            ts = event.get("timestamp", 0)
            if not ts:
                continue

            time_until = ts - now

            # 15-Min-Reminder: Thread + Ping + Script-JSON
            if not event.get("reminded_15") and REMINDER_15_MIN[0] <= time_until <= REMINDER_15_MIN[1]:
                await self._send_15min_reminder(msg_id, event)

            # 5-Min-Reminder: Anwesenheitskontrolle
            if not event.get("reminded_5") and REMINDER_5_MIN[0] <= time_until <= REMINDER_5_MIN[1]:
                await self._send_5min_reminder(msg_id, event)

    @check_reminders.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def _get_event_channel(self, event: dict) -> discord.TextChannel | None:
        """Holt den Event-Channel."""
        channel_id = event.get("channel_id")
        if not channel_id:
            return None
        return self.bot.get_channel(channel_id)

    async def _get_or_create_thread(self, msg_id: str, event: dict) -> discord.Thread | None:
        """Holt oder erstellt den Reminder-Thread für ein Event."""
        channel = await self._get_event_channel(event)
        if not channel:
            return None

        # Thread bereits vorhanden?
        thread_id = event.get("reminder_thread_id")
        if thread_id:
            thread = channel.guild.get_thread(thread_id)
            if thread:
                return thread

        # Neuen Thread an der Event-Message erstellen
        try:
            message = await channel.fetch_message(int(msg_id))
            title = event.get("title", "Event")
            # Titel kürzen (Thread-Name max 100 Zeichen)
            thread_name = f"📢 {title}"[:100]
            thread = await message.create_thread(name=thread_name)

            # Thread-ID im Event speichern
            event["reminder_thread_id"] = thread.id
            save_event(int(msg_id), event)

            return thread
        except (discord.NotFound, discord.Forbidden) as e:
            logger.warning("Reminder: Thread erstellen fehlgeschlagen: %s", e)
            return None

    async def _send_15min_reminder(self, msg_id: str, event: dict):
        """15 Min vor Start: Thread, Pings, Script-JSON."""
        title = event.get("title", "BotC Event")
        ts = event.get("timestamp", 0)
        accepted = event.get("accepted", [])

        # Markieren (auch bei Fehlern, um Spam zu vermeiden)
        event["reminded_15"] = True
        save_event(int(msg_id), event)

        thread = await self._get_or_create_thread(msg_id, event)
        if not thread:
            logger.warning("Reminder 15min: Kein Thread für Event '%s'", title)
            return

        # Ping-Liste
        if accepted:
            pings = " ".join(f"<@{uid}>" for uid in accepted)
            await thread.send(
                f"⏰ **Erinnerung!** Das Event startet <t:{ts}:R>!\n\n{pings}"
            )
        else:
            await thread.send(f"⏰ **Erinnerung!** Das Event startet <t:{ts}:R>!")

        # Script-JSON posten
        script_json = await self._get_script_json(event)
        if script_json is not None:
            script_name = event.get("script", "script")
            safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in script_name)
            json_bytes = json.dumps(script_json, indent=2, ensure_ascii=False).encode("utf-8")
            script_file = discord.File(io.BytesIO(json_bytes), filename=f"{safe_name}.json")
            await thread.send(
                f"📜 Hier ist das Skript **{script_name}** zum Laden:",
                file=script_file,
            )
        else:
            script = event.get("script", "")
            if script and script != "Freie Skriptwahl":
                await thread.send(f"ℹ️ Für **{script}** ist kein Script-JSON hinterlegt.")

        logger.info("15-Min-Reminder gesendet für Event '%s'", title)

    async def _send_5min_reminder(self, msg_id: str, event: dict):
        """5 Min vor Start: Anwesenheitskontrolle."""
        title = event.get("title", "BotC Event")
        accepted = event.get("accepted", [])

        event["reminded_5"] = True
        save_event(int(msg_id), event)

        thread = await self._get_or_create_thread(msg_id, event)
        if not thread:
            logger.warning("Reminder 5min: Kein Thread für Event '%s'", title)
            return

        if not accepted:
            await thread.send("👨‍🏫 **Anwesenheitskontrolle!**\n\nKeine Zusagen vorhanden.")
            return

        # Teilnehmerliste mit Nummern
        lines = []
        for i, uid in enumerate(accepted, 1):
            lines.append(f"{i}. <@{uid}>")

        checklist = "\n".join(lines)
        await thread.send(
            f"👨‍🏫 **Anwesenheitskontrolle!**\n\n{checklist}\n\n"
            f"Wer fehlt, bitte melden — es geht gleich los!"
        )

        logger.info("5-Min-Reminder gesendet für Event '%s'", title)

    async def _get_script_json(self, event: dict) -> list | None:
        """Holt die Script-JSON — per API oder aus dem Event."""
        script_source = event.get("script_source", "")
        script = event.get("script", "")

        if not script or script == "Freie Skriptwahl":
            return None

        # Upload → Content ist im Event gespeichert
        if script_source == "upload":
            return event.get("script_content")

        # botcscripts.com → per API abrufen
        botcscripts_id = event.get("botcscripts_id")
        if botcscripts_id:
            try:
                content = await fetch_script_json(botcscripts_id)
                if content:
                    return content
            except Exception as e:
                logger.warning("Reminder: Script-JSON Abruf fehlgeschlagen: %s", e)

        return None


async def setup(bot: commands.Bot):
    await bot.add_cog(ReminderCog(bot))
