import logging
import discord

from event_storage import get_event, save_event, delete_event
from logic.event_builder import build_event_embed

logger = logging.getLogger(__name__)


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


class EventView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        emoji=discord.PartialEmoji(name="angenommen", id=1484616708558815282),
        style=discord.ButtonStyle.success,
        custom_id="event_accept",
    )
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_rsvp(interaction, "accepted")

    @discord.ui.button(
        emoji=discord.PartialEmoji(name="abgelehnt", id=1484616609313325227),
        style=discord.ButtonStyle.danger,
        custom_id="event_decline",
    )
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_rsvp(interaction, "declined")

    @discord.ui.button(
        emoji=discord.PartialEmoji(name="vorlaeufig", id=1484616662073212989),
        style=discord.ButtonStyle.secondary,
        custom_id="event_tentative",
    )
    async def tentative(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_rsvp(interaction, "tentative")

    @discord.ui.button(label="Bearbeiten", style=discord.ButtonStyle.primary, custom_id="event_edit")
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
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

        await interaction.response.send_message(
            "Diese Funktion wird in einer zukünftigen Version verfügbar.",
            ephemeral=True,
        )

    @discord.ui.button(label="Löschen", style=discord.ButtonStyle.danger, custom_id="event_delete")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
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
