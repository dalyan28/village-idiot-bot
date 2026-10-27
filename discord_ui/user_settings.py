"""/einstellungen: Übersicht und eigene Standardwerte (Dalyan, 26.10.2026).

Die Karten sind ephemer (nur für die Person sichtbar). Buttons sind DynamicItems (`uset:<guild_id>:<aktion>`),
die Dialoge bearbeiten danach dieselbe Karte. Logik und Speicherung: events/user_settings.py.
"""

from __future__ import annotations

import re
from datetime import datetime

import discord

from events import user_settings
from events.schema import (
    BERLIN_TZ,
    CAMERA_LABELS,
    CO_ST_LABELS,
    DEFAULT_CAMERA,
    DEFAULT_DURATION_MINUTES,
    DEFAULT_LEVEL,
    DEFAULT_MAX_PLAYERS,
    DESCRIPTION_MAX_LENGTH,
    LEVELS,
    TEENSY_MAX_PLAYERS,
)
from events.user_settings import UserDefaults

CARD_COLOR = 0x5865F2


def now() -> datetime:
    return datetime.now(BERLIN_TZ)


def _value(text: str) -> str:
    return f"`{text.replace('`', 'ˋ')}`"


def _or_default(value, default, unit: str = "") -> str:
    shown = f"{value if value is not None else default}{unit}"
    return _value(shown + ("" if value is not None else " (Standard)"))


def _section(text: str, button: discord.ui.Item) -> discord.ui.Section:
    return discord.ui.Section(discord.ui.TextDisplay(text), accessory=button)


# ── Karten ───────────────────────────────────────────────────────────────────


def overview_layout(guild: discord.Guild) -> discord.ui.LayoutView:
    esc = discord.utils.escape_markdown
    container = discord.ui.Container(accent_colour=CARD_COLOR)
    container.add_item(discord.ui.TextDisplay(
        f"-# {esc(guild.name)}\n\n**Einstellungen**\nHier legst du fest, wie der Bot für dich arbeitet."))
    container.add_item(discord.ui.Separator())
    container.add_item(_section(
        "**Standardwerte**\n-# Womit deine neuen Events starten: Beschreibung, Spieler, Dauer, Level, Kamera und "
        "Co-Storytelling.", SettingsButton(guild.id, "defaults", "Öffnen", discord.ButtonStyle.primary)))
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    return layout


def defaults_layout(guild: discord.Guild, d: UserDefaults, notice: str | None = None) -> discord.ui.LayoutView:
    esc = discord.utils.escape_markdown
    container = discord.ui.Container(accent_colour=CARD_COLOR)
    head = (f"-# {esc(guild.name)}\n\n**Deine Standardwerte**\nDamit startet jedes neue Event, das du anlegst. "
            "Im Entwurf kannst du danach trotzdem alles ändern.")
    if notice:
        head += f"\n{notice}"
    container.add_item(discord.ui.TextDisplay(head))

    # Jedes Feld einzeln mit eigenem „Ändern“ (Dalyan, 26.10.2026)
    description = d.description.strip() or "`keine`"  # eigener Text mit Formatierung, nicht escapen
    camera = CAMERA_LABELS[d.camera or DEFAULT_CAMERA] + (f" · {d.camera_note}" if d.camera_note else "")
    co = CO_ST_LABELS[d.co_st_status or "no"] + (f" · {d.co_st_note}" if d.co_st_note else "")
    fields = [
        ("description", f"**Beschreibung**\n{description}"),
        ("players", f"**Max. Spieler**\n{_or_default(d.max_players, DEFAULT_MAX_PLAYERS)}\n"
                    f"-# Bei Teensyville setzt der Bot automatisch {TEENSY_MAX_PLAYERS} Spieler."),
        ("duration", f"**Dauer**\n{_or_default(d.duration_minutes, DEFAULT_DURATION_MINUTES, ' Minuten')}"),
        ("level", f"**Erfahrungslevel**\n{_or_default(d.level, DEFAULT_LEVEL)}"),
        ("camera", f"**Kamera**\n{_value(camera + ('' if d.camera or d.camera_note else ' (Standard)'))}"),
        ("cost", f"**Co-Storytelling**\n{_value(co + ('' if d.co_st_status or d.co_st_note else ' (Standard)'))}"),
    ]
    for action, text in fields:
        container.add_item(discord.ui.Separator())
        container.add_item(_section(text, SettingsButton(guild.id, action)))

    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    row = discord.ui.ActionRow()
    row.add_item(SettingsButton(guild.id, "overview", "Zurück zur Übersicht"))
    if not d.is_empty():
        row.add_item(SettingsButton(guild.id, "reset", "Alles zurücksetzen", discord.ButtonStyle.danger))
    layout.add_item(row)
    return layout


# ── Dialoge ──────────────────────────────────────────────────────────────────


class _DefaultsModal(discord.ui.Modal):
    def __init__(self, guild: discord.Guild, defaults: UserDefaults, title: str):
        super().__init__(title=title, timeout=15 * 60)
        self.guild, self.defaults = guild, defaults

    def apply(self, d: UserDefaults) -> str | None:
        """Übernimmt die Eingaben; gibt bei ungültigen Werten eine Meldung zurück."""
        raise NotImplementedError

    async def on_submit(self, interaction: discord.Interaction):
        store = interaction.client.store
        d = user_settings.get(store, self.guild.id, interaction.user.id)
        error = self.apply(d)
        if error is None:
            user_settings.save(store, self.guild.id, interaction.user.id, d, int(now().timestamp()))
            d = user_settings.get(store, self.guild.id, interaction.user.id)
        await interaction.response.edit_message(view=defaults_layout(self.guild, d, error or "Gespeichert."))


def _number(raw: str | None, low: int, high: int, label: str) -> tuple[int | None, str | None]:
    """Leer = eingebauter Standard (None); sonst Zahl im Bereich oder eine Fehlermeldung."""
    raw = (raw or "").strip()
    if not raw:
        return None, None
    if not raw.isdigit() or not low <= int(raw) <= high:
        return None, f"{label} muss eine Zahl zwischen {low} und {high} sein. Nichts geändert."
    return int(raw), None


class PlayersDefaultModal(_DefaultsModal):
    def __init__(self, guild, defaults: UserDefaults):
        super().__init__(guild, defaults, "Max. Spieler")
        self.players = discord.ui.TextInput(required=False, max_length=3, placeholder=str(DEFAULT_MAX_PLAYERS),
                                            default=str(defaults.max_players) if defaults.max_players else None)
        self.add_item(discord.ui.Label(text="Max. Spieler", description="1 bis 200, leer = 12", component=self.players))

    def apply(self, d):
        value, error = _number(self.players.value, *user_settings.MAX_PLAYERS_RANGE, "Die Spielerzahl")
        if error:
            return error
        d.max_players = value
        return None


class DurationDefaultModal(_DefaultsModal):
    def __init__(self, guild, defaults: UserDefaults):
        super().__init__(guild, defaults, "Dauer")
        self.duration = discord.ui.TextInput(required=False, max_length=4, placeholder=str(DEFAULT_DURATION_MINUTES),
                                             default=str(defaults.duration_minutes) if defaults.duration_minutes
                                             else None)
        self.add_item(discord.ui.Label(text="Dauer in Minuten", description="15 bis 1440, leer = 150",
                                       component=self.duration))

    def apply(self, d):
        value, error = _number(self.duration.value, *user_settings.DURATION_RANGE, "Die Dauer")
        if error:
            return error
        d.duration_minutes = value
        return None


class LevelDefaultModal(_DefaultsModal):
    def __init__(self, guild, defaults: UserDefaults):
        super().__init__(guild, defaults, "Erfahrungslevel")
        self.level = discord.ui.RadioGroup()
        for lvl in LEVELS:
            self.level.add_option(label=lvl, value=lvl, default=lvl == (defaults.level or DEFAULT_LEVEL))
        self.add_item(discord.ui.Label(text="Erfahrungslevel", component=self.level))

    def apply(self, d):
        level = self.level.value or DEFAULT_LEVEL
        d.level = None if level == DEFAULT_LEVEL else level


class CameraDefaultModal(_DefaultsModal):
    def __init__(self, guild, defaults: UserDefaults):
        super().__init__(guild, defaults, "Kamera")
        self.camera = discord.ui.RadioGroup()
        for key, label in CAMERA_LABELS.items():
            self.camera.add_option(label=label, value=key, default=key == (defaults.camera or DEFAULT_CAMERA))
        self.camera_note = discord.ui.TextInput(required=False, max_length=user_settings.NOTE_MAX_LENGTH,
                                                default=defaults.camera_note or None,
                                                placeholder="z. B. „gern mit Kamera“")
        self.add_item(discord.ui.Label(text="Kamera", component=self.camera))
        self.add_item(discord.ui.Label(text="Hinweis zur Kamera", description="Optional", component=self.camera_note))

    def apply(self, d):
        camera = self.camera.value or DEFAULT_CAMERA
        d.camera = None if camera == DEFAULT_CAMERA else camera
        d.camera_note = (self.camera_note.value or "").strip()


class CoStDefaultModal(_DefaultsModal):
    def __init__(self, guild, defaults: UserDefaults):
        super().__init__(guild, defaults, "Co-Storytelling")
        self.status = discord.ui.RadioGroup()
        for value, label in CO_ST_LABELS.items():
            self.status.add_option(label=label, value=value, default=value == (defaults.co_st_status or "no"))
        self.note = discord.ui.TextInput(required=False, max_length=user_settings.NOTE_MAX_LENGTH,
                                         default=defaults.co_st_note or None, placeholder="z. B. „gern Neulinge“")
        self.add_item(discord.ui.Label(text="Co-Storytellen möglich?", component=self.status))
        self.add_item(discord.ui.Label(text="Hinweis zum Co-Storytelling", description="Optional",
                                       component=self.note))

    def apply(self, d):
        status = self.status.value or "no"
        d.co_st_status = None if status == "no" else status
        d.co_st_note = (self.note.value or "").strip()


MODALS = {"players": PlayersDefaultModal, "duration": DurationDefaultModal,
          "level": LevelDefaultModal, "camera": CameraDefaultModal, "cost": CoStDefaultModal}

class SettingsButton(discord.ui.DynamicItem[discord.ui.Button],
                     template=r"uset:(?P<guild_id>\d+):(?P<action>[a-z]+)"):
    def __init__(self, guild_id: int, action: str, label: str = "Ändern", style=discord.ButtonStyle.secondary):
        super().__init__(discord.ui.Button(label=label, style=style, custom_id=f"uset:{guild_id}:{action}"))
        self.guild_id, self.action = guild_id, action

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["guild_id"]), match["action"], item.label or "Ändern", item.style)

    async def callback(self, interaction: discord.Interaction):
        store = interaction.client.store
        guild = interaction.client.get_guild(self.guild_id)
        if guild is None:
            await interaction.response.send_message("Diesen Server kenne ich gerade nicht.", ephemeral=True)
            return
        d = user_settings.get(store, guild.id, interaction.user.id)
        if self.action == "description":
            # Per DM, damit Formatierung und Emojis gehen (Dalyan, 27.10.2026)
            from discord_ui import text_edit

            sent = await text_edit.start(interaction.client, guild, interaction.user, "description")
            await interaction.response.edit_message(
                view=defaults_layout(guild, d, text_edit.IN_DMS if sent else text_edit.DM_CLOSED))
        elif self.action in MODALS:
            await interaction.response.send_modal(MODALS[self.action](guild, d))
        elif self.action == "defaults":
            await interaction.response.edit_message(view=defaults_layout(guild, d))
        elif self.action == "overview":
            await interaction.response.edit_message(view=overview_layout(guild))
        elif self.action == "reset":
            user_settings.save(store, guild.id, interaction.user.id, UserDefaults(), int(now().timestamp()))
            await interaction.response.edit_message(
                view=defaults_layout(guild, UserDefaults(), "Alles auf die eingebauten Standards zurückgesetzt."))
