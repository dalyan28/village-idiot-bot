import asyncio
import re
import time as time_module
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from config import get_guild_config, save_guild_config
from logic.parser import parse_events, build_overviews

BERLIN_TZ = ZoneInfo("Europe/Berlin")

DEFAULT_SMART_SCHEDULE: list[list[int]] = [
    [5, 0], [8, 0], [12, 0], [16, 0], [18, 0], [19, 0], [19, 30], [20, 0], [22, 0]
]


class Overview(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_tasks: dict[int, tasks.Loop | asyncio.Task] = {}
        self.smart_dynamic_times: dict[int, set[tuple[int, int]]] = {}
        self.last_smart_run: dict[int, datetime] = {}
        self._fetch_locks: dict[int, asyncio.Lock] = {}

    async def fetch_and_post(self, guild_id: int, event_channel: discord.TextChannel, target_channel: discord.TextChannel):
        lock = self._fetch_locks.setdefault(guild_id, asyncio.Lock())
        if lock.locked():
            print(f"[fetch_and_post] Guild {guild_id}: Update bereits aktiv, überspringe")
            return
        async with lock:
            await self._fetch_and_post_locked(guild_id, event_channel, target_channel)

    async def _fetch_and_post_locked(self, guild_id: int, event_channel: discord.TextChannel, target_channel: discord.TextChannel):
        messages = [msg async for msg in event_channel.history(limit=100)]
        cfg = get_guild_config(guild_id)

        events = parse_events(messages)
        self._update_smart_dynamic_times(guild_id, events, cfg.get("smart_dynamic", True))
        embeds = build_overviews(events)

        # debug
        for embed in embeds:
            print(f"Embed fields: {len(embed.fields)}")
            for field in embed.fields:
                print(f"  Field '{field.name}': {len(field.value)} Zeichen")

        # alte nachrichten löschen
        old_ids = cfg.get("last_overview_message_ids", [])
        print(f"Lösche alte Nachrichten: {old_ids}")
        for msg_id in old_ids:
            try:
                old_msg = await target_channel.fetch_message(msg_id)
                await old_msg.delete()
                print(f"Gelöscht: {msg_id}")
            except discord.NotFound:
                print(f"Nicht gefunden: {msg_id}")
            except Exception as e:
                print(f"Fehler beim Löschen {msg_id}: {e}")

        # neue nachrichten posten
        new_ids = []
        for embed in embeds:
            new_msg = await target_channel.send(embed=embed)
            new_ids.append(new_msg.id)

        cfg["last_overview_message_ids"] = new_ids
        save_guild_config(guild_id, cfg)

    def _update_smart_dynamic_times(self, guild_id: int, events: list[dict], enabled: bool) -> None:
        if not enabled:
            self.smart_dynamic_times[guild_id] = set()
            return

        now_berlin = datetime.now(tz=BERLIN_TZ)
        today = now_berlin.date()
        now_ts = time_module.time()

        future_today = [
            e for e in events
            if e["start_ts"] > now_ts
            and datetime.fromtimestamp(e["start_ts"], tz=BERLIN_TZ).date() == today
        ]

        dynamic: set[tuple[int, int]] = set()
        for e in future_today:
            start = datetime.fromtimestamp(e["start_ts"], tz=BERLIN_TZ)
            for delta_min in (30, 20, 10):
                trigger = start - timedelta(minutes=delta_min)
                if trigger > now_berlin:
                    dynamic.add((trigger.hour, trigger.minute))

        self.smart_dynamic_times[guild_id] = dynamic
        if dynamic:
            print(f"[Smart] Dynamische Zeiten für Guild {guild_id}: {sorted(dynamic)}")

    def resolve_channels(self, guild_id: int, cfg: dict, event_channel=None, overview_channel=None):
        resolved_event = event_channel or (
            self.bot.get_channel(cfg["event_channel_id"]) if cfg.get("event_channel_id") else None
        )
        resolved_overview = overview_channel or (
            self.bot.get_channel(cfg["overview_channel_id"]) if cfg.get("overview_channel_id") else None
        )
        return resolved_event, resolved_overview

    def _get_guild_schedule(self, guild_id: int) -> set[tuple[int, int]]:
        cfg = get_guild_config(guild_id)
        raw = cfg.get("smart_schedule", DEFAULT_SMART_SCHEDULE)
        return {(entry[0], entry[1]) for entry in raw}

    @staticmethod
    def _compute_next_time(all_times: list[tuple[int, int]], now: datetime) -> datetime:
        """Berechnet den nächsten geplanten Zeitpunkt nach 'now' (Berlin-Zeit)."""
        for h, m in all_times:
            candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate > now:
                return candidate
        # Alle Zeiten heute bereits verstrichen → morgen erster Termin
        first_h, first_m = all_times[0] if all_times else (5, 0)
        return (now + timedelta(days=1)).replace(
            hour=first_h, minute=first_m, second=0, microsecond=0
        )

    async def _run_smart_scheduler(self, guild_id: int, event_channel: discord.TextChannel, overview_channel: discord.TextChannel):
        try:
            # Sofort beim Start einmal aktualisieren
            await self.fetch_and_post(guild_id, event_channel, overview_channel)
            self.last_smart_run[guild_id] = datetime.now(tz=timezone.utc)

            while True:
                now = datetime.now(tz=BERLIN_TZ)
                fixed = self._get_guild_schedule(guild_id)
                dynamic = self.smart_dynamic_times.get(guild_id, set())
                all_times = sorted(fixed | dynamic)
                next_run = self._compute_next_time(all_times, now)

                sleep_seconds = (next_run - now).total_seconds()
                print(f"[Smart] Guild {guild_id}: nächstes Update {next_run.strftime('%H:%M')} ({sleep_seconds:.0f}s)")

                await asyncio.sleep(sleep_seconds)

                now_utc = datetime.now(tz=timezone.utc)
                last = self.last_smart_run.get(guild_id)
                seconds_since_last = (now_utc - last).total_seconds() if last else float("inf")

                # 90-Sekunden-Debounce: verhindert Doppelpost wenn on_message und Scheduler gleichzeitig feuern
                if seconds_since_last < 90:
                    continue

                # 15-Minuten-Skip-Regel: nur für feste Zeiten, nicht für dynamische
                now_berlin = datetime.now(tz=BERLIN_TZ)
                current_hm = (now_berlin.hour, now_berlin.minute)
                is_dynamic = current_hm in self.smart_dynamic_times.get(guild_id, set())
                if not is_dynamic and seconds_since_last < 15 * 60:
                    print(f"[Smart] Skip {now_berlin.strftime('%H:%M')}: letzte Aktu. erst {seconds_since_last / 60:.1f} Min her")
                    continue

                self.last_smart_run[guild_id] = now_utc
                await self.fetch_and_post(guild_id, event_channel, overview_channel)

        except asyncio.CancelledError:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.author.bot or not message.guild:
            return

        cfg = get_guild_config(message.guild.id)

        if not cfg.get("on_new_event", False):
            return
        if message.guild.id not in self.auto_tasks:
            return
        if message.channel.id != cfg.get("event_channel_id"):
            return

        # Nur echte Events abfangen: Bot-Nachricht mit Embed das ein Time/Termin-Feld hat
        if not message.embeds:
            return
        embed = message.embeds[0]
        if not embed.title or not embed.fields:
            return
        if not any(f.name in ("Time", "Termin") for f in embed.fields):
            return

        overview_id = cfg.get("overview_channel_id")
        overview_channel = self.bot.get_channel(overview_id) if overview_id else None
        if not overview_channel:
            return

        await self.fetch_and_post(message.guild.id, message.channel, overview_channel)

        if cfg.get("auto_interval_hours") == -1:
            # Smart Mode: alten Sleep canceln, Zeitplan mit neuen Events neu berechnen
            old = self.auto_tasks.get(message.guild.id)
            if isinstance(old, asyncio.Task) and not old.done():
                old.cancel()
            self.last_smart_run[message.guild.id] = datetime.now(tz=timezone.utc)
            event_channel = self.bot.get_channel(cfg.get("event_channel_id"))
            new_task = asyncio.create_task(
                self._run_smart_scheduler(message.guild.id, event_channel, overview_channel)
            )
            self.auto_tasks[message.guild.id] = new_task
        else:
            # Intervall-Modus: Timer neu starten
            existing = self.auto_tasks.get(message.guild.id)
            if isinstance(existing, tasks.Loop) and existing.is_running():
                existing.restart()

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if not payload.guild_id:
            return

        cfg = get_guild_config(payload.guild_id)

        if payload.channel_id != cfg.get("event_channel_id"):
            return
        if payload.guild_id not in self.auto_tasks:
            return

        event_channel = self.bot.get_channel(payload.channel_id)
        overview_id = cfg.get("overview_channel_id")
        overview_channel = self.bot.get_channel(overview_id) if overview_id else None

        if not event_channel or not overview_channel:
            return

        print(f"[Delete] Nachricht in Event-Channel gelöscht, aktualisiere Übersicht...")
        await self.fetch_and_post(payload.guild_id, event_channel, overview_channel)

        if cfg.get("auto_interval_hours") == -1:
            old = self.auto_tasks.get(payload.guild_id)
            if isinstance(old, asyncio.Task) and not old.done():
                old.cancel()
            self.last_smart_run[payload.guild_id] = datetime.now(tz=timezone.utc)
            new_task = asyncio.create_task(
                self._run_smart_scheduler(payload.guild_id, event_channel, overview_channel)
            )
            self.auto_tasks[payload.guild_id] = new_task
        else:
            existing = self.auto_tasks.get(payload.guild_id)
            if isinstance(existing, tasks.Loop) and existing.is_running():
                existing.restart()

    @app_commands.command(name="overview_events", description="Erstellt eine Übersicht der Events")
    async def overview_events(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        cfg = get_guild_config(interaction.guild_id)

        if channel is None:
            overview_id = cfg.get("overview_channel_id")
            channel = self.bot.get_channel(overview_id) if overview_id else interaction.channel

        event_channel_id = cfg.get("event_channel_id")
        event_channel = self.bot.get_channel(event_channel_id) if event_channel_id else None

        if not event_channel:
            await interaction.response.send_message(
                "Kein Event-Channel gesetzt. Bitte erst `/set_event_channel` nutzen.", ephemeral=True
            )
            return

        await interaction.response.send_message(f"Erstelle Übersicht in {channel.mention}...", ephemeral=True)
        await self.fetch_and_post(interaction.guild_id, event_channel, channel)

    @app_commands.command(name="automate_overview", description="Automatisiert die Übersicht in einem Intervall")
    @app_commands.choices(frequenz=[
        app_commands.Choice(name="Smart (automatisch)", value=-1),
        app_commands.Choice(name="1 Stunde",          value=1),
        app_commands.Choice(name="2 Stunden",         value=2),
        app_commands.Choice(name="4 Stunden",         value=4),
        app_commands.Choice(name="8 Stunden",         value=8),
        app_commands.Choice(name="12 Stunden",        value=12),
        app_commands.Choice(name="24 Stunden",        value=24),
    ])
    async def automate_overview(
        self,
        interaction: discord.Interaction,
        frequenz: int,
        event_channel: discord.TextChannel = None,
        overview_channel: discord.TextChannel = None,
        on_new_event: bool = True,
        dynamic: bool = True,
    ):
        guild_id = interaction.guild_id
        cfg = get_guild_config(guild_id)
        resolved_event, resolved_overview = self.resolve_channels(guild_id, cfg, event_channel, overview_channel)

        missing = []
        if not resolved_event:
            missing.append("`event_channel` (oder `/set_event_channel` nutzen)")
        if not resolved_overview:
            missing.append("`overview_channel` (oder `/set_overview_channel` nutzen)")

        if missing:
            await interaction.response.send_message(
                "Folgende Channel fehlen noch:\n" + "\n".join(f"- {m}" for m in missing),
                ephemeral=True
            )
            return

        # Bestehenden Task/Loop stoppen
        existing = self.auto_tasks.get(guild_id)
        if isinstance(existing, asyncio.Task):
            existing.cancel()
        elif isinstance(existing, tasks.Loop) and existing.is_running():
            existing.stop()

        cfg["auto_interval_hours"] = frequenz
        cfg["on_new_event"] = on_new_event
        cfg["auto_active"] = True

        if frequenz == -1:
            cfg["smart_dynamic"] = dynamic
            save_guild_config(guild_id, cfg)
            task = asyncio.create_task(
                self._run_smart_scheduler(guild_id, resolved_event, resolved_overview)
            )
            self.auto_tasks[guild_id] = task
            label = "Smart Mode"
        else:
            save_guild_config(guild_id, cfg)
            @tasks.loop(hours=frequenz)
            async def auto_job():
                await self.fetch_and_post(guild_id, resolved_event, resolved_overview)
            self.auto_tasks[guild_id] = auto_job
            self.auto_tasks[guild_id].start()
            label = f"{frequenz} Stunden"

        on_new_event_label = "aktiv" if on_new_event else "inaktiv"
        await interaction.response.send_message(
            f"Automatische Übersicht: {label}.\n"
            f"Events aus: {resolved_event.mention} -> Übersicht in: {resolved_overview.mention}\n"
            f"Aktualisierung bei neuem Event: {on_new_event_label}",
            ephemeral=True
        )

    @app_commands.command(name="stop_automate", description="Stoppt alle laufenden automatischen Übersichten")
    async def stop_automate(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        existing = self.auto_tasks.get(guild_id)

        is_running = (
            (isinstance(existing, asyncio.Task) and not existing.done())
            or (isinstance(existing, tasks.Loop) and existing.is_running())
        )

        if is_running:
            if isinstance(existing, asyncio.Task):
                existing.cancel()
            else:
                existing.stop()
            del self.auto_tasks[guild_id]
            self.smart_dynamic_times.pop(guild_id, None)
            self.last_smart_run.pop(guild_id, None)

            cfg = get_guild_config(guild_id)
            cfg["auto_active"] = False
            save_guild_config(guild_id, cfg)

            await interaction.response.send_message("Automatische Übersicht gestoppt.", ephemeral=True)
        else:
            await interaction.response.send_message("Es läuft gerade keine automatische Übersicht.", ephemeral=True)


    def _parse_schedule_input(self, raw: str) -> tuple[list[list[int]], list[str]]:
        tokens = re.split(r"[\s,;]+", raw.strip())
        valid, errors = [], []
        seen: set[tuple[int, int]] = set()
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", token)
            if not m:
                errors.append(f"`{token}` – kein gültiges Format (erwartet HH:MM)")
                continue
            h, mi = int(m.group(1)), int(m.group(2))
            if not (0 <= h <= 23 and 0 <= mi <= 59):
                errors.append(f"`{token}` – Stunde/Minute außerhalb des gültigen Bereichs")
                continue
            key = (h, mi)
            if key in seen:
                continue
            seen.add(key)
            valid.append([h, mi])
        valid.sort()
        return valid, errors

    @app_commands.command(name="set_schedule", description="Legt den Smart-Mode-Zeitplan fest (z.B. '05:00 08:00 12:00') oder 'default'")
    async def set_schedule(self, interaction: discord.Interaction, zeiten: str):
        if zeiten.strip().lower() == "default":
            valid = DEFAULT_SMART_SCHEDULE
        else:
            valid, errors = self._parse_schedule_input(zeiten)

            if errors:
                msg = "Folgende Eingaben konnten nicht erkannt werden:\n" + "\n".join(f"- {e}" for e in errors)
                if valid:
                    msg += "\n\nGültige Zeiten: " + ", ".join(f"{h:02d}:{m:02d}" for h, m in valid)
                await interaction.response.send_message(msg, ephemeral=True)
                return

            if not valid:
                await interaction.response.send_message("Keine gültigen Zeiten erkannt.", ephemeral=True)
                return

        preview = ", ".join(f"{h:02d}:{m:02d}" for h, m in valid)

        class ConfirmView(discord.ui.View):
            def __init__(self_inner):
                super().__init__(timeout=60)

            @discord.ui.button(label="Ja, speichern", style=discord.ButtonStyle.green)
            async def confirm(self_inner, btn_interaction: discord.Interaction, _button: discord.ui.Button):
                cfg = get_guild_config(interaction.guild_id)
                cfg["smart_schedule"] = valid
                save_guild_config(interaction.guild_id, cfg)
                # Kein Neustart nötig – _get_guild_schedule liest Config bei jeder
                # Loop-Iteration frisch, neuer Schedule gilt ab nächstem Aufwachen
                await btn_interaction.response.edit_message(
                    content=f"Zeitplan gespeichert: **{preview}**", view=None
                )

            @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.red)
            async def cancel(self_inner, btn_interaction: discord.Interaction, _button: discord.ui.Button):
                await btn_interaction.response.edit_message(content="Abgebrochen.", view=None)

        await interaction.response.send_message(
            f"Erkannter Zeitplan ({len(valid)} Zeiten):\n**{preview}**\n\nStimmt das so?",
            view=ConfirmView(),
            ephemeral=True
        )

    @app_commands.command(name="see_schedule", description="Zeigt den aktuellen Smart-Mode-Zeitplan")
    async def see_schedule(self, interaction: discord.Interaction):
        cfg = get_guild_config(interaction.guild_id)
        raw = cfg.get("smart_schedule", DEFAULT_SMART_SCHEDULE)
        times_str = ", ".join(f"{h:02d}:{m:02d}" for h, m in raw)

        dynamic_on = cfg.get("smart_dynamic", True)
        dynamic_times = self.smart_dynamic_times.get(interaction.guild_id, set())
        dynamic_str = (
            ", ".join(f"{h:02d}:{m:02d}" for h, m in sorted(dynamic_times))
            if dynamic_times else "keine (noch keine zukünftigen Events heute)"
        )

        active = cfg.get("auto_interval_hours") == -1 and cfg.get("auto_active")

        lines = [
            f"**Smart Mode:** {'aktiv' if active else 'inaktiv'}",
            f"**Feste Zeiten:** {times_str}",
            f"**Dynamische Zeiten:** {'an' if dynamic_on else 'aus'}",
        ]
        if dynamic_on:
            lines.append(f"**Heute dynamisch:** {dynamic_str}")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Overview(bot))