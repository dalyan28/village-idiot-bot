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
from events.parse import ParseError, format_start
from events.schema import LEVELS
from events.store import Store

logger = logging.getLogger(__name__)

LEVEL_DESCRIPTIONS = {
    "Neuling": "Für Leute, die das Spiel noch lernen",
    "Erfahren": "Grundregeln und gängige Charaktere sitzen",
    "Profi": "Für sehr erfahrene Spieler:innen",
    "Alle": "Jede:r ist willkommen",
}


OTHER_DATE = "other"
DATE_CHOICES = 9  # Heute, Morgen und die folgenden Tage; dazu „Anderes Datum“ (Radio: max. 10 Optionen)


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
    """Fünf Felder (Discord-Grenze): Datum, Uhrzeit, Spieler, Level, Optionen."""

    def __init__(self, store: Store, allow_academy: bool, raw: ModalInput | None = None, v2: bool = False,
                 guild: discord.Guild | None = None, member: discord.Member | None = None):
        super().__init__(title="Neue Runde anlegen", timeout=15 * 60)
        self.store = store
        # Server und Mitglied: in den DMs kennt die Interaktion beides nicht, /botc gibt sie mit
        self.guild, self.member = guild, member
        self.v2 = v2  # /botc2: Wizard mit Components V2
        raw = raw or ModalInput()

        self.date = discord.ui.TextInput(placeholder="z. B. Sa, morgen, 24.10.", default=raw.date_text or None,
                                         max_length=30)
        self.time = discord.ui.TextInput(placeholder="z. B. 20:00 oder 20 Uhr", default=raw.time_text or None,
                                         max_length=10)
        self.players = discord.ui.TextInput(default=raw.players_text, max_length=3)

        self.level = discord.ui.RadioGroup()
        for lvl in LEVELS:
            self.level.add_option(label=lvl, value=lvl, description=LEVEL_DESCRIPTIONS[lvl],
                                  default=lvl == raw.level)

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

        if v2:
            # /botc2: schlanker (Dalyan, 20.10.2026). Datum als Auswahl, Level und Spieler mit Standardwert
            # (Alle, 12 bzw. 6 bei Teensyville), änderbar in der Zusammenfassung.
            self.date_choice = date_choice_radio(raw.date_text)
            self.date.required = False
            self.date.placeholder = "nur bei „Anderes Datum“, z. B. 24.12."
            if self.date.default and any(o.value == self.date.default for o in self.date_choice.options):
                self.date.default = None
            self.time_choice = time_choice_radio(raw.time_text)
            self.time.required = False
            self.time.placeholder = "nur bei „Andere Uhrzeit“, z. B. 18:30"
            if self.time.default in TIME_CHOICES:
                self.time.default = None
            self.add_item(discord.ui.Label(text="Datum", component=self.date_choice))
            self.add_item(discord.ui.Label(text="Anderes Datum", component=self.date))
            self.add_item(discord.ui.Label(text="Uhrzeit", component=self.time_choice))
            self.add_item(discord.ui.Label(text="Andere Uhrzeit", component=self.time))
            self.add_item(discord.ui.Label(text="Optionen", component=self.options))
            return
        self.add_item(discord.ui.Label(text="Datum", component=self.date))
        self.add_item(discord.ui.Label(text="Uhrzeit", component=self.time))
        self.add_item(discord.ui.Label(text="Max. Spieler", description="1 bis 200", component=self.players))
        self.add_item(discord.ui.Label(text="Erfahrungslevel", component=self.level))
        self.add_item(discord.ui.Label(text="Optionen", component=self.options))

    def raw_input(self) -> ModalInput:
        if self.v2:
            choice = self.date_choice.value or OTHER_DATE
            time_choice = self.time_choice.value or OTHER_TIME
            return ModalInput(
                date_text=(self.date.value or "") if choice == OTHER_DATE else choice,
                time_text=(self.time.value or "") if time_choice == OTHER_TIME else time_choice,
                options=list(self.options.values),
            )
        return ModalInput(
            date_text=self.date.value or "",
            time_text=self.time.value or "",
            players_text=self.players.value or "",
            level=self.level.value or "Alle",
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
                str(e), view=RetryView(self.store, allow_academy, raw, self.v2, self.guild, self.member),
                ephemeral=True
            )
            return
        if self.v2:
            self.store.set_draft_ui(draft.id, {"v2": True})  # beginnt mit der Skriptwahl
            draft = self.store.get_draft(draft.id)

        where = "Check deine DMs, dort geht es weiter." if interaction.guild_id else "Weiter geht es hier unten."
        await interaction.response.send_message(
            f"Termin erkannt: **{format_start(draft.data.start, draft.data.duration_minutes)}**\n{where}",
            ephemeral=True,
        )
        await deliver_wizard(interaction, draft)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.exception("Fehler im /botc-Modal", exc_info=error)
        if not interaction.response.is_done():
            await interaction.response.send_message("Da ist etwas schiefgelaufen. Versuch es bitte nochmal.",
                                                    ephemeral=True)


async def deliver_wizard(interaction: discord.Interaction, draft, intro: str | None = None):
    """Wizard per DM schicken. Bei geschlossenen DMs bleibt der Entwurf erhalten."""
    try:
        await wizard.send_wizard(interaction.client, interaction.user, draft, intro)
    except discord.Forbidden:
        await interaction.followup.send(
            "Ich kann dir keine DM schicken. Erlaube DMs von Servermitgliedern "
            "(Servereinstellungen → Privatsphäre) und starte dann `/botc` erneut, "
            "dein Entwurf bleibt gespeichert.",
            ephemeral=True,
        )


class RetryView(discord.ui.View):
    """Nach einem Eingabefehler: Modal mit den alten Eingaben neu öffnen."""

    def __init__(self, store: Store, allow_academy: bool, raw: ModalInput, v2: bool = False,
                 guild: discord.Guild | None = None, member: discord.Member | None = None):
        super().__init__(timeout=15 * 60)
        self.store, self.allow_academy, self.raw, self.v2 = store, allow_academy, raw, v2
        self.guild, self.member = guild, member

    @discord.ui.button(label="Nochmal", style=discord.ButtonStyle.primary)
    async def retry(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BotcModal(self.store, self.allow_academy, self.raw, self.v2,
                                                        self.guild, self.member))


class ResumeOrNewView(discord.ui.View):
    """/botc mit offenem Entwurf: weitermachen oder neu beginnen."""

    def __init__(self, store: Store, draft, allow_academy: bool, guild: discord.Guild | None = None,
                 member: discord.Member | None = None):
        super().__init__(timeout=15 * 60)
        self.store, self.draft, self.allow_academy = store, draft, allow_academy
        self.guild, self.member = guild, member

    @discord.ui.button(label="Weitermachen", style=discord.ButtonStyle.primary)
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        draft = self.store.get_draft(self.draft.id)
        if draft is None:
            await interaction.response.edit_message(content="Der Entwurf ist inzwischen weg. Starte bitte neu.",
                                                    view=None)
            return
        await interaction.response.edit_message(content="Check deine DMs, dort geht es weiter.", view=None)
        await deliver_wizard(interaction, draft, intro="Hier geht es mit deinem Entwurf weiter:")

    @discord.ui.button(label="Neu beginnen", style=discord.ButtonStyle.secondary)
    async def new(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Der alte Entwurf wird erst ersetzt, wenn das neue Modal abgeschickt ist (service.start_draft)
        await interaction.response.send_modal(BotcModal(self.store, self.allow_academy,
                                                        guild=self.guild, member=self.member))
