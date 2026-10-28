"""Der Event-Post im Event-Channel: Embed, Bilder und Buttons (RSVP, Bearbeiten, Löschen).

Buttons sind DynamicItems mit der Event-ID (`evt:<event_id>:<aktion>`) und funktionieren
nach einem Neustart weiter. Bilder hängen mit festen Dateinamen an der Nachricht; beim
Neuaufbau des Embeds (z. B. nach einer Anmeldung) zeigt es per attachment:// auf sie.
"""

from __future__ import annotations

import io
import logging
import os
import re
from datetime import datetime, timezone

import discord

from config import get_guild_config
from discord_ui.members import actor_from_member, fetch_member
from events import guild_lock, service
from events.schema import BERLIN_TZ, Person
from events.store import RSVP_ACCEPTED, RSVP_DECLINED, RSVP_TENTATIVE, EventRecord, Store
from logic.event_builder import EMOJI_FILLER, build_event_embed
from logic.event_images import (
    THUMB_FILENAME,
    image_filename,
    image_name_of,
    image_signature,
    render_image,
    render_script_sheet_for,
    thumbnail_path,
)

logger = logging.getLogger(__name__)

# Graue Buttons mit den farbigen "rec"-Emojis, wie beim alten Event-Post (Dalyan, 20.10.2026)
EMOJI_ACCEPT_BUTTON = discord.PartialEmoji(name="accept_rec", id=1484978213863161986)
EMOJI_DECLINE_BUTTON = discord.PartialEmoji(name="decline_rec", id=1484978231957524661)
EMOJI_TENTATIVE_BUTTON = discord.PartialEmoji(name="tent_rec", id=1484978258553471066)

RSVP_ACTIONS = {"accept": RSVP_ACCEPTED, "decline": RSVP_DECLINED, "tentative": RSVP_TENTATIVE}


def dev_tools_enabled() -> bool:
    """Test-Hilfen wie „[Dev] Reminder testen“: nur lokal (ENV=dev) oder auf dem Testserver (TEST_SERVER=1)."""
    return os.getenv("ENV") == "dev" or os.getenv("TEST_SERVER") == "1"


def now() -> datetime:
    return datetime.now(BERLIN_TZ)


# ── Embed und Anhänge ────────────────────────────────────────────────────────


def _name_resolver(guild: discord.Guild | None):
    """Aktueller Anzeigename aus dem Member-Cache, sonst der gespeicherte."""
    def name_for(person: Person) -> str | None:
        if guild is None or person.user_id is None:
            return None
        member = guild.get_member(person.user_id)
        return member.display_name if member else None
    return name_for


async def render_post(bot: discord.Client, store: Store, event: EventRecord,
                      image_name: str | None, has_thumbnail: bool) -> dict:
    """Inhalt des Event-Posts als kwargs für send/edit: Embed + Buttons."""
    embed = await build_embed(bot, store, event, image_name, has_thumbnail)
    return {"embed": embed, "view": event_view(event)}


async def build_embed(bot: discord.Client, store: Store, event: EventRecord,
                      image_name: str | None, has_thumbnail: bool) -> discord.Embed:
    """`image_name`: Anhangsname des großen Bildes (JPEG-Skript-Blatt oder PNG), None ohne Bild."""
    guild = bot.get_guild(event.guild_id)
    # Ohne Members-Intent ist der Cache oft leer: Mitglied dann bei Discord abfragen,
    # sonst fehlt das Profilbild in der Fußzeile.
    creator = await fetch_member(bot, event.guild_id, event.creator_id)
    embed = build_event_embed(
        event.data,
        creator.display_name if creator else event.creator_name,
        service.rsvp_lists(store, event),
        creator_avatar_url=creator.display_avatar.url if creator else None,
        thumbnail_url=f"attachment://{THUMB_FILENAME}" if has_thumbnail else None,
        name_for=_name_resolver(guild),
        created_at=datetime.fromtimestamp(event.created_at, tz=timezone.utc),
        academy_template=service.get_academy_template(store, event.guild_id),
    )
    if image_name:
        embed.set_image(url=f"attachment://{image_name}")
    return embed


async def build_files(event_data) -> list[discord.File]:
    files = []
    image = await render_image(event_data)
    if image:
        files.append(discord.File(io.BytesIO(image), filename=image_filename(image)))
    thumb = thumbnail_path(event_data)
    if thumb:
        files.append(discord.File(thumb, filename=THUMB_FILENAME))
    return files


def _has(files_or_attachments, filename: str) -> bool:
    return any(f.filename == filename for f in files_or_attachments)


def _shown_images(msg: discord.Message) -> tuple[str | None, bool]:
    """Welche Bilder der Post gerade zeigt (Anhangsname des Bildes, Thumbnail ja/nein).

    Discord führt Anhänge, auf die ein Embed per attachment:// zeigt, nicht in msg.attachments.
    Deshalb am Embed ablesen; wer dort fehlt, ließe Discord beim Bearbeiten verwaist fallen
    (gleiches Problem und gleiche Lösung wie auf event-creation).
    Der Name kommt aus der Bild-URL: Ältere Posts haben noch event_image.png, neue event_image.jpg.
    """
    if msg.embeds:
        embed = msg.embeds[0]
        image_name = None
        if embed.image and embed.image.url:
            # CDN-Link (https://…/event_image.jpg?ex=…) oder attachment://event_image.jpg
            image_name = embed.image.url.split("?", 1)[0].rsplit("/", 1)[-1] or None
        return image_name, bool(embed.thumbnail and embed.thumbnail.url)
    return image_name_of(msg.attachments), _has(msg.attachments, THUMB_FILENAME)


def event_view(event: EventRecord) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(EventButton(event.id, "accept", emoji=EMOJI_ACCEPT_BUTTON, style=discord.ButtonStyle.secondary))
    view.add_item(EventButton(event.id, "decline", emoji=EMOJI_DECLINE_BUTTON, style=discord.ButtonStyle.secondary))
    tentative_emoji = EMOJI_FILLER if event.data.is_academy else EMOJI_TENTATIVE_BUTTON
    view.add_item(EventButton(event.id, "tentative", emoji=tentative_emoji, style=discord.ButtonStyle.secondary))
    view.add_item(EventButton(event.id, "edit", label="Bearbeiten", style=discord.ButtonStyle.primary))
    view.add_item(EventButton(event.id, "delete", label="Löschen", style=discord.ButtonStyle.danger))
    if dev_tools_enabled():
        # Eigene Zeile unter den fünf Buttons (Dalyan, 20.10.2026)
        view.add_item(EventButton(event.id, "testreminder", label="[Dev] Reminder testen", row=1))
        # Neue Optik „plain“ neben der alten „fancy“ ansehen (Dalyan, 28.10.2026)
        view.add_item(EventButton(event.id, "comparelooks", label="[Dev] Show Fancy PNG to Compare", row=1))
    return view


def event_channel(bot: discord.Client, guild_id: int) -> discord.abc.Messageable | None:
    channel_id = get_guild_config(guild_id).get("event_channel_id")
    return bot.get_channel(channel_id) if channel_id else None


async def post_event(bot: discord.Client, store: Store, event: EventRecord) -> discord.Message:
    """Postet ein neues Event in den Event-Channel und merkt sich die Nachricht."""
    channel = event_channel(bot, event.guild_id)
    if channel is None:
        raise service.ServiceError("Es ist kein Event-Channel eingerichtet (`/set_event_channel`).")
    files = await build_files(event.data)
    content = await render_post(bot, store, event, image_name_of(files), _has(files, THUMB_FILENAME))
    msg = await channel.send(files=files, **content)
    store.set_event_message(event.id, msg.channel.id, msg.id)
    logger.info("Event %s gepostet (msg %s)", event.id, msg.id)
    return msg


async def fetch_event_message(bot: discord.Client, event: EventRecord) -> discord.Message | None:
    if not event.channel_id or not event.message_id:
        return None
    channel = bot.get_channel(event.channel_id)
    try:
        if channel is None:
            channel = await bot.fetch_channel(event.channel_id)
        return await channel.fetch_message(event.message_id)
    except (discord.NotFound, discord.Forbidden):
        return None


async def update_event_message(bot: discord.Client, store: Store, event: EventRecord,
                               images_changed: bool) -> discord.Message | None:
    """Bringt den Event-Post auf den Stand der Datenbank. Fehlt die Nachricht, wird neu gepostet
    (außer das Event ist schon vorbei: dessen Post hat das nächtliche Aufräumen entfernt)."""
    msg = await fetch_event_message(bot, event)
    if msg is None:
        if event.data.end is not None and event.data.end <= now():
            return None
        return await post_event(bot, store, event)
    if images_changed:
        files = await build_files(event.data)
        content = await render_post(bot, store, event, image_name_of(files), _has(files, THUMB_FILENAME))
        await msg.edit(attachments=files, **content)
    else:
        content = await render_post(bot, store, event, *_shown_images(msg))
        await msg.edit(**content)
    return msg


async def remove_post(bot: discord.Client, store: Store, event: EventRecord) -> bool:
    """Löscht den Event-Post samt Erinnerungs-Thread. Das Event bleibt in der Datenbank (30 Tage)."""
    msg = await fetch_event_message(bot, event)
    if msg is not None:
        thread = msg.thread
        if thread is not None:
            try:
                await thread.delete()
            except discord.HTTPException as e:
                logger.warning("Thread von Event %s nicht gelöscht: %s", event.id, e)
        try:
            await msg.delete()
        except discord.NotFound:
            pass
        except discord.HTTPException as e:
            logger.warning("Post von Event %s nicht gelöscht: %s", event.id, e)
            return False
    store.clear_event_message(event.id)
    return True


async def remove_ended_posts(bot: discord.Client, store: Store, guild_id: int, t: datetime) -> int:
    """Posts aller beendeten Events dieses Servers entfernen (Ende vor `t`)."""
    removed = 0
    for event in store.list_events(guild_id, start_until=int(t.timestamp())):
        if event.message_id is None or event.data.end is None or event.data.end > t:
            continue
        if await remove_post(bot, store, event):
            removed += 1
    return removed


def images_changed(old_data, new_data) -> bool:
    return image_signature(old_data) != image_signature(new_data)


# ── Buttons ──────────────────────────────────────────────────────────────────


class EventButton(discord.ui.DynamicItem[discord.ui.Button], template=r"evt:(?P<event_id>\d+):(?P<name>[a-z]+)"):
    def __init__(self, event_id: int, name: str, label: str | None = None,
                 emoji=None, style=discord.ButtonStyle.secondary, row: int | None = None):
        super().__init__(discord.ui.Button(label=label, emoji=emoji, style=style,
                                           custom_id=f"evt:{event_id}:{name}"), row=row)
        self.event_id, self.name = event_id, name

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["event_id"]), match["name"], item.label, item.emoji, item.style)

    async def callback(self, interaction: discord.Interaction):
        if not guild_lock.is_allowed(interaction.guild_id):
            await interaction.response.send_message("Dieser Bot ist auf diesem Server nicht freigeschaltet.",
                                                    ephemeral=True)
            return
        store: Store = interaction.client.store
        event = store.get_event(self.event_id)
        if event is None:
            await interaction.response.send_message("Dieses Event gibt es nicht mehr.", ephemeral=True)
            return
        if self.name in RSVP_ACTIONS:
            await handle_rsvp(interaction, store, event, RSVP_ACTIONS[self.name])
        elif self.name == "edit":
            await handle_edit(interaction, store, event)
        elif self.name == "delete":
            await handle_delete(interaction, store, event)
        elif self.name == "testreminder":
            await handle_test_reminder(interaction, store, event)
        elif self.name == "comparelooks":
            await handle_compare_looks(interaction, event)


async def handle_rsvp(interaction: discord.Interaction, store: Store, event: EventRecord, status: str):
    new_status = service.toggle_rsvp(store, event, interaction.user.id, interaction.user.display_name, status, now())
    content = await render_post(interaction.client, store, event, *_shown_images(interaction.message))
    # Buttons mitschicken, damit ältere Posts beim nächsten Klick die aktuellen Buttons bekommen
    await interaction.response.edit_message(**content)
    if new_status == RSVP_ACCEPTED:
        # Zeitgleich schon woanders zugesagt? Hinweis mit Verweis auf die Anmelderegeln (Dalyan, 26.10.2026)
        from discord_ui.conflicts import signup_hint
        from events.conflicts import conflict_group

        group = conflict_group(store, event, interaction.user.id, now())
        if len(group) > 1:
            await interaction.followup.send(signup_hint(event, group), ephemeral=True, suppress_embeds=True)


async def handle_test_reminder(interaction: discord.Interaction, store: Store, event: EventRecord):
    """Schickt die erste Erinnerung einmal sofort in den Thread, so wie sie vor Beginn käme.
    Zählt nicht als gesendet: Die echte Erinnerung kommt trotzdem."""
    from events import reminders

    cog = interaction.client.get_cog("ReminderCog")
    if not dev_tools_enabled() or cog is None:
        await interaction.response.send_message("Diese Test-Funktion ist hier nicht aktiv.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    cfg = reminders.copy_of(reminders.effective(store.get_guild_settings(event.guild_id), event.data)[reminders.FIRST])
    cfg.enabled = True
    await cog.send_reminder(event, cfg)
    await interaction.followup.send("Die Test-Erinnerung steht im Thread unter dem Event.", ephemeral=True)


async def handle_compare_looks(interaction: discord.Interaction, event: EventRecord):
    """Schickt nur der klickenden Person das Skript-Blatt in der neuen Optik „plain“ und der alten „fancy“."""
    if not dev_tools_enabled():
        await interaction.response.send_message("Diese Test-Funktion ist hier nicht aktiv.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    files = []
    for look in ("plain", "fancy"):
        image = await render_script_sheet_for(event.data, look)
        if image is not None:
            files.append(discord.File(io.BytesIO(image), filename=f"{look}.jpg"))
    if not files:
        await interaction.followup.send("Für dieses Event gibt es kein Skript-Blatt (kein Skript oder zu groß).",
                                        ephemeral=True)
        return
    await interaction.followup.send("Links die neue Optik (plain, Standard), rechts die alte (fancy).",
                                    files=files, ephemeral=True)


async def handle_edit(interaction: discord.Interaction, store: Store, event: EventRecord):
    from discord_ui import wizard  # zirkulären Import vermeiden

    actor = actor_from_member(interaction.user)
    try:
        draft = service.draft_for_edit(store, event, actor, now())
    except service.PermissionDenied:
        await interaction.response.send_message("Bearbeiten dürfen nur der Ersteller und das Event-Team.",
                                                ephemeral=True)
        return
    await interaction.response.send_message("Du kannst das Event in deinen DMs bearbeiten.",
                                            ephemeral=True)
    try:
        await wizard.send_wizard(interaction.client, interaction.user, draft)
    except discord.Forbidden:
        store.delete_draft(draft.id)
        await interaction.followup.send("Ich kann dir keine DM schicken. Erlaube DMs von Servermitgliedern "
                                        "und versuch es dann erneut.", ephemeral=True)


async def handle_delete(interaction: discord.Interaction, store: Store, event: EventRecord):
    from events import permissions

    actor = actor_from_member(interaction.user)
    if not permissions.can(actor, permissions.DELETE, service.get_access(store, event.guild_id), event.creator_id):
        await interaction.response.send_message("Löschen dürfen nur der Ersteller und das Event-Team.",
                                                ephemeral=True)
        return
    await interaction.response.send_message("Soll dieses Event wirklich gelöscht werden?",
                                            view=DeleteConfirmView(store, event.id, interaction.message), ephemeral=True)


class DeleteConfirmView(discord.ui.View):
    def __init__(self, store: Store, event_id: int, message: discord.Message):
        super().__init__(timeout=120)
        self.store, self.event_id, self.message = store, event_id, message

    @discord.ui.button(label="Ja, löschen", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        event = self.store.get_event(self.event_id)
        if event is None:
            await interaction.response.edit_message(content="Das Event wurde bereits gelöscht.", view=None)
            return
        try:
            service.delete_event(self.store, event, actor_from_member(interaction.user), now())
        except service.PermissionDenied:
            await interaction.response.edit_message(content="Dafür fehlt dir die Berechtigung.", view=None)
            return
        try:
            await self.message.delete()
        except discord.HTTPException:
            logger.warning("Event-Nachricht %s konnte nicht gelöscht werden", self.message.id)
        await interaction.response.edit_message(content="Event gelöscht.", view=None)

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Löschen abgebrochen.", view=None)
