"""Das /botc-Modal: Eckdaten der Runde (kein Titel, keine Beschreibung)."""

from __future__ import annotations

import logging
from datetime import timedelta

import discord

from discord_ui import wizard
from discord_ui.members import actor_from_member, display_name
from events import service
from events.intake import (
    OPTION_ACADEMY,
    OPTION_CAMERA,
    OPTION_CASUAL,
    OPTION_RECORDED,
    ModalInput,
    parse_modal_input,
)
from events.parse import ParseError
from events.store import Store

logger = logging.getLogger(__name__)


OTHER_DATE = "other"
DATE_CHOICES = 5  # Heute, Morgen und drei weitere Tage, dazu „Anderes Datum“ (Dalyan, 20.10.2026)


def date_choice_radio(previous: str = "") -> discord.ui.RadioGroup:
    """Datum als Auswahl: Heute, Morgen, die nächsten Tage, Anderes Datum. Werte im ISO-Format."""
    from events.parse import WEEKDAY_NAMES

    today = wizard.now().date()
    radio = discord.ui.RadioGroup()
    for i in range(DATE_CHOICES):
        day = today + timedelta(days=i)
        name = {0: "Heute", 1: "Morgen"}.get(i, WEEKDAY_NAMES[day.weekday()])
        radio.add_option(label=f"{name} · {day:%d.%m.}", value=day.isoformat(), default=previous == day.isoformat())
    is_other = bool(previous) and previous not in {o.value for o in radio.options}
    radio.add_option(label="Anderes Datum (unten eintragen)", value=OTHER_DATE, default=is_other)
    return radio


OTHER_TIME = "other"
TIME_CHOICES = ("13:00", "14:00", "19:00", "20:00")  # häufigste Startzeiten (Dalyan, 20.10.2026)


def time_choice_radio(previous: str = "") -> discord.ui.RadioGroup:
    """Uhrzeit als Auswahl: die häufigsten Startzeiten oder „Andere Uhrzeit“."""
    radio = discord.ui.RadioGroup()
    for t in TIME_CHOICES:
        radio.add_option(label=f"{t} Uhr", value=t, default=previous == t)
    radio.add_option(label="Andere Uhrzeit (unten eintragen)", value=OTHER_TIME,
                     default=bool(previous) and previous not in TIME_CHOICES)
    return radio


class BotcModal(discord.ui.Modal):
    """Eckdaten der Runde: Datum und Uhrzeit als Auswahl (mit Feld für Sonderfälle), Optionen.

    Level (Alle) und Spieler (12 bzw. 6 bei Teensyville) haben Standardwerte und werden in der
    Zusammenfassung geändert (Dalyan, 20.10.2026).
    """

    def __init__(self, store: Store, allow_academy: bool, raw: ModalInput | None = None,
                 guild: discord.Guild | None = None, member: discord.Member | None = None,
                 origin: discord.Message | None = None):
        super().__init__(title="Termin und Optionen", timeout=15 * 60)
        self.store = store
        # Server und Mitglied: in den DMs kennt die Interaktion beides nicht, /botc gibt sie mit
        self.guild, self.member = guild, member
        # Startnachricht in den DMs; sie wird nach dem Absenden zur Skript-Karte
        self.origin = origin
        raw = raw or ModalInput()

        self.date_choice = date_choice_radio(raw.date_text)
        is_listed_date = any(o.value == raw.date_text for o in self.date_choice.options)
        self.date = discord.ui.TextInput(required=False, max_length=30,
                                         placeholder="nur bei „Anderes Datum“, z. B. 24.12.",
                                         default=None if is_listed_date else (raw.date_text or None))
        self.time_choice = time_choice_radio(raw.time_text)
        self.time = discord.ui.TextInput(required=False, max_length=10,
                                         placeholder="nur bei „Andere Uhrzeit“, z. B. 18:30",
                                         default=None if raw.time_text in TIME_CHOICES else (raw.time_text or None))

        self.options = discord.ui.CheckboxGroup(required=False, min_values=0)
        choices = [
            (OPTION_ACADEMY, "🎓 Academy", "Lernrunde der Clocktower Academy"),
            (OPTION_CASUAL, "🕊️ Casual", "Mehr Zeit, besonders rücksichtsvoll"),
            (OPTION_RECORDED, "🎦 Aufzeichnung", "Die Runde wird aufgezeichnet"),
            (OPTION_CAMERA, "Kamera-Pflicht", "Alle spielen mit Kamera"),
        ]
        for value, label, desc in choices:
            if value == OPTION_ACADEMY and not allow_academy:
                continue
            self.options.add_option(label=label, value=value, description=desc, default=value in raw.options)
        self.options.max_values = len(self.options.options)

        self.add_item(discord.ui.Label(text="Datum", component=self.date_choice))
        self.add_item(discord.ui.Label(text="Anderes Datum", component=self.date))
        self.add_item(discord.ui.Label(text="Uhrzeit", component=self.time_choice))
        self.add_item(discord.ui.Label(text="Andere Uhrzeit", component=self.time))
        self.add_item(discord.ui.Label(text="Optionen", component=self.options))

    def raw_input(self) -> ModalInput:
        choice = self.date_choice.value or OTHER_DATE
        time_choice = self.time_choice.value or OTHER_TIME
        return ModalInput(
            date_text=(self.date.value or "") if choice == OTHER_DATE else choice,
            time_text=(self.time.value or "") if time_choice == OTHER_TIME else time_choice,
            options=list(self.options.values),
        )

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.raw_input()
        member = self.member or interaction.user
        guild_id = self.guild.id if self.guild else interaction.guild_id
        actor = actor_from_member(member)
        try:
            data = parse_modal_input(raw, wizard.now())
            draft = service.start_draft(self.store, guild_id, actor, display_name(member), data, wizard.now())
        except (ParseError, service.ServiceError) as e:
            allow_academy = OPTION_ACADEMY in [o.value for o in self.options.options]
            await interaction.response.send_message(
                str(e), view=RetryView(self.store, allow_academy, raw, self.guild, self.member, self.origin),
                ephemeral=True
            )
            return
        # Die Startnachricht wird zur Skript-Karte (sie bestätigt den Termin und sagt, was jetzt kommt)
        layout, files = await wizard.render(interaction.client, draft)
        if self.origin is not None and interaction.message is not None and interaction.message.id == self.origin.id:
            await interaction.response.edit_message(view=layout, attachments=files)
        elif self.origin is not None:  # abgeschickt über „Eingaben korrigieren“
            await interaction.response.defer()
            await self.origin.edit(view=layout, attachments=files)
        else:
            await interaction.response.defer()
            await wizard.send_wizard(interaction.client, interaction.user, draft)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.exception("Fehler im /botc-Modal", exc_info=error)
        if not interaction.response.is_done():
            await interaction.response.send_message("Ein Fehler ist aufgetreten. Bitte versuch es erneut.",
                                                    ephemeral=True)


class RetryView(discord.ui.View):
    """Nach einem Eingabefehler: Modal mit den alten Eingaben neu öffnen."""

    def __init__(self, store: Store, allow_academy: bool, raw: ModalInput,
                 guild: discord.Guild | None = None, member: discord.Member | None = None,
                 origin: discord.Message | None = None):
        super().__init__(timeout=15 * 60)
        self.store, self.allow_academy, self.raw = store, allow_academy, raw
        self.guild, self.member, self.origin = guild, member, origin

    @discord.ui.button(label="Eingaben korrigieren", style=discord.ButtonStyle.primary)
    async def retry(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BotcModal(self.store, self.allow_academy, self.raw,
                                                        self.guild, self.member, self.origin))
