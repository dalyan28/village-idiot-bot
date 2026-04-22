import logging
import discord

from event_storage import get_event, save_event, delete_event
from logic.event_builder import build_event_embed

logger = logging.getLogger(__name__)


FILLER_EMOJI = "\U0001f47c"  # 👼 — Engelchen für „Auffüller" (Academy)


def _toggle_rsvp(event_data: dict, user_id: int, category: str) -> str:
    """Toggle RSVP für einen User. Gibt die Aktion zurück: 'added', 'removed', 'switched'."""
    categories = ("accepted", "declined", "tentative")

    # Bereits in dieser Kategorie → entfernen (Toggle off)
    if user_id in event_data[category]:
        event_data[category].remove(user_id)
        return "removed"

    # Aus anderer Kategorie entfernen falls vorhanden
    switched = False
    for other in categories:
        if other != category and user_id in event_data[other]:
            event_data[other].remove(user_id)
            switched = True

    # In neue Kategorie einfügen
    event_data[category].append(user_id)
    return "switched" if switched else "added"


async def _handle_rsvp(interaction: discord.Interaction, category: str):
    """Gemeinsame RSVP-Logik für alle drei Buttons."""
    message_id = interaction.message.id
    user_id = interaction.user.id

    logger.debug("Button '%s' gedrückt von %s auf msg_id=%s", category, interaction.user, message_id)

    event_data = get_event(message_id)
    if event_data is None:
        await interaction.response.send_message("Event nicht gefunden.", ephemeral=True)
        return

    action = _toggle_rsvp(event_data, user_id, category)
    save_event(message_id, event_data)

    logger.info("RSVP: %s → %s (%s) für Event '%s'", interaction.user, category, action, event_data.get("title"))

    embed = build_event_embed(event_data)

    # Bild-Referenz beibehalten: attachment:// statt CDN-URL,
    # damit Discord das Attachment nicht als verwaist behandelt.
    if event_data.get("image_url"):
        embed.set_image(url="attachment://script.png")

    await interaction.response.edit_message(embed=embed)


def _has_manage_permission(interaction: discord.Interaction, event_data: dict) -> bool:
    """Prüft ob der User das Event verwalten darf."""
    if interaction.user.id == event_data.get("creator_id"):
        return True
    if interaction.user.guild_permissions.manage_guild:
        return True
    return False


class DeleteConfirmView(discord.ui.View):
    def __init__(self, event_message: discord.Message, event_data: dict):
        super().__init__(timeout=60)
        self.event_message = event_message
        self.event_data = event_data

    @discord.ui.button(label="Ja, löschen", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        delete_event(self.event_message.id)
        logger.info(
            "Event gelöscht: '%s' (msg_id=%s) von %s",
            self.event_data.get("title"), self.event_message.id, interaction.user,
        )
        try:
            await self.event_message.delete()
        except discord.NotFound:
            pass
        await interaction.response.edit_message(content="Event wurde gelöscht.", view=None)

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Löschen abgebrochen.", view=None)


async def _handle_edit(interaction: discord.Interaction):
    event_data = get_event(interaction.message.id)
    if event_data is None:
        await interaction.response.send_message("Event nicht gefunden.", ephemeral=True)
        return

    if not _has_manage_permission(interaction, event_data):
        await interaction.response.send_message(
            "Nur der Ersteller oder Server-Admins können Events bearbeiten.",
            ephemeral=True,
        )
        return

    host_cog = interaction.client.cogs.get("HostCommand")
    if not host_cog:
        await interaction.response.send_message("Event-System nicht verfügbar.", ephemeral=True)
        return

    from logic.conversation import has_active_session
    if has_active_session(interaction.user.id):
        await interaction.response.send_message(
            "Du hast bereits eine aktive Session. Beende sie zuerst.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    session = host_cog.create_edit_session(interaction, event_data, interaction.message.id)

    try:
        dm = await interaction.user.create_dm()
        await dm.send(f"📝 **Event bearbeiten:** {event_data.get('title', 'Event')}")
        await host_cog._show_final_review(session, dm, regenerate_title=False)
        await interaction.followup.send("Schau in deine DMs — dort kannst du das Event bearbeiten.", ephemeral=True)
    except discord.Forbidden:
        from logic.conversation import end_session
        end_session(interaction.user.id)
        await interaction.followup.send("Kann keine DM senden.", ephemeral=True)


async def _handle_delete(interaction: discord.Interaction):
    event_data = get_event(interaction.message.id)
    if event_data is None:
        await interaction.response.send_message("Event nicht gefunden.", ephemeral=True)
        return

    if not _has_manage_permission(interaction, event_data):
        await interaction.response.send_message(
            "Nur der Ersteller oder Server-Admins können Events löschen.",
            ephemeral=True,
        )
        return

    logger.debug("Lösch-Bestätigung angefragt von %s für msg_id=%s", interaction.user, interaction.message.id)

    confirm_view = DeleteConfirmView(interaction.message, event_data)
    await interaction.response.send_message(
        f"Event **{event_data.get('title')}** wirklich löschen?",
        view=confirm_view,
        ephemeral=True,
    )


class EventView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        emoji=discord.PartialEmoji(name="accept_rec", id=1484978213863161986),
        style=discord.ButtonStyle.secondary,
        custom_id="event_accept",
    )
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_rsvp(interaction, "accepted")

    @discord.ui.button(
        emoji=discord.PartialEmoji(name="decline_rec", id=1484978231957524661),
        style=discord.ButtonStyle.secondary,
        custom_id="event_decline",
    )
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_rsvp(interaction, "declined")

    @discord.ui.button(
        emoji=discord.PartialEmoji(name="tent_rec", id=1484978258553471066),
        style=discord.ButtonStyle.secondary,
        custom_id="event_tentative",
    )
    async def tentative(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_rsvp(interaction, "tentative")

    @discord.ui.button(label="Bearbeiten", style=discord.ButtonStyle.primary, custom_id="event_edit")
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_edit(interaction)

    @discord.ui.button(label="Löschen", style=discord.ButtonStyle.danger, custom_id="event_delete")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_delete(interaction)


class EventViewAcademy(discord.ui.View):
    """RSVP-View für Academy-Runden: „Auffüller" (👼) statt „Vorläufig"."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        emoji=discord.PartialEmoji(name="accept_rec", id=1484978213863161986),
        style=discord.ButtonStyle.secondary,
        custom_id="event_accept_academy",
    )
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_rsvp(interaction, "accepted")

    @discord.ui.button(
        emoji=discord.PartialEmoji(name="decline_rec", id=1484978231957524661),
        style=discord.ButtonStyle.secondary,
        custom_id="event_decline_academy",
    )
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_rsvp(interaction, "declined")

    @discord.ui.button(
        emoji=FILLER_EMOJI,
        style=discord.ButtonStyle.secondary,
        custom_id="event_filler",
    )
    async def filler(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Wiederverwendung des „tentative"-Slots im Storage — semantisch
        # bei Academy: Auffüller, sonst: Vorläufig. Spart einen separaten Datentopf.
        await _handle_rsvp(interaction, "tentative")

    @discord.ui.button(label="Bearbeiten", style=discord.ButtonStyle.primary, custom_id="event_edit_academy")
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_edit(interaction)

    @discord.ui.button(label="Löschen", style=discord.ButtonStyle.danger, custom_id="event_delete_academy")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_delete(interaction)


def view_for_event(event_data: dict) -> discord.ui.View:
    """Liefert die passende RSVP-View je nach Event-Typ."""
    if event_data.get("is_academy"):
        return EventViewAcademy()
    return EventView()
