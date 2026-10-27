"""/testserver setup|reset|delete_all: Testserver für die Admins (nur Branch testserver).

Geladen nur mit TEST_SERVER=1 (siehe bot.py). Die Commands tun nur etwas auf Servern aus
TEST_GUILD_IDS und nur für Admins (Server verwalten). Das schützt den echten Server davor,
aus Versehen abgeräumt zu werden.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from testserver import is_test_guild, server, texts
from testserver.feedback import FeedbackButton
from testserver.test_card import TestCardButton
from testserver.sample_event import create_sample_event

logger = logging.getLogger(__name__)


async def _guard(interaction: discord.Interaction) -> bool:
    if not is_test_guild(interaction.guild_id):
        await interaction.response.send_message(texts.NOT_A_TEST_SERVER, ephemeral=True)
        return False
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(texts.ADMINS_ONLY, ephemeral=True)
        return False
    return True


async def _followup(interaction: discord.Interaction, text: str):
    try:
        await interaction.followup.send(text, ephemeral=True)
    except discord.HTTPException:
        # z. B. wenn der Channel, in dem der Command lief, gerade gelöscht wurde
        logger.info("Testserver: Antwort nicht zustellbar: %s", text)


class DeleteAllConfirmView(discord.ui.View):
    def __init__(self, cog: "TestServerCog", author_id: int):
        super().__init__(timeout=60)
        self.cog, self.author_id = cog, author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(texts.NOT_YOUR_BUTTON, ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ja, alles weg", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        if not await _guard(interaction):
            return
        await interaction.response.edit_message(content=texts.DELETE_RUNNING, view=None)
        result = await server.delete_all(interaction.guild, self.cog.bot.store, self.cog.bot)
        await _followup(interaction, result.summary())

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content=texts.DELETE_CANCELLED, view=None)


class TestServerCog(commands.Cog):
    __test__ = False  # Dateiname beginnt mit test_, pytest soll hier nichts sammeln

    testserver = app_commands.Group(
        name="testserver", description="Testserver aufsetzen, zurücksetzen oder abbauen (nur Admins)",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_dynamic_items(FeedbackButton, TestCardButton)

    async def cog_unload(self):
        self.bot.remove_dynamic_items(FeedbackButton, TestCardButton)

    @testserver.command(name="setup", description="Channels, Rollen und Texte anlegen oder auffrischen")
    async def setup_cmd(self, interaction: discord.Interaction):
        if not await _guard(interaction):
            return
        await interaction.response.send_message(texts.SETUP_RUNNING, ephemeral=True)
        result = await server.setup_server(interaction.guild, self.bot.store)
        await server.ensure_sample_event(self.bot, interaction.guild, self.bot.store, interaction.user, result)
        await server.start_overview(self.bot, interaction.guild, self.bot.store)
        await _followup(interaction, result.summary())

    @testserver.command(name="update", description="Die Texte in diesem Channel aktualisieren")
    async def update_cmd(self, interaction: discord.Interaction):
        if not await _guard(interaction):
            return
        key = server.text_channel_key(self.bot.store, interaction.guild_id, interaction.channel_id)
        if key is None:
            await interaction.response.send_message(texts.UPDATE_NO_TEXTS, ephemeral=True)
            return
        await interaction.response.send_message(texts.UPDATE_RUNNING, ephemeral=True)
        result = await server.update_texts(interaction.guild, self.bot.store, only=key)
        await _followup(interaction, result.summary())

    @testserver.command(name="beispiel-event", description="Volles Beispiel-Event mit 23 erfundenen Anmeldungen posten")
    async def sample_cmd(self, interaction: discord.Interaction):
        if not await _guard(interaction):
            return
        await interaction.response.send_message(texts.SAMPLE_RUNNING, ephemeral=True)
        try:
            event = await create_sample_event(self.bot, self.bot.store, interaction.guild, interaction.user)
        except Exception as e:
            logger.exception("Testserver: Beispiel-Event fehlgeschlagen")
            await _followup(interaction, f"Das Beispiel-Event hat nicht geklappt: {e}")
            return
        link = f"https://discord.com/channels/{event.guild_id}/{event.channel_id}/{event.message_id}"
        await _followup(interaction, f"Beispiel-Event ist da: {link}")

    @testserver.command(name="skript-bilder", description="Zehn Skript-Bilder in #skript-bilder neu posten")
    async def sheets_cmd(self, interaction: discord.Interaction):
        from testserver import registry, script_gallery

        if not await _guard(interaction):
            return
        store = self.bot.store
        reg = registry.get(store, interaction.guild_id)
        channel = interaction.guild.get_channel(reg["channels"].get(script_gallery.CHANNEL_KEY) or 0)
        if channel is None:
            await interaction.response.send_message(texts.SHEETS_NO_CHANNEL, ephemeral=True)
            return
        await interaction.response.send_message(texts.SHEETS_RUNNING, ephemeral=True)
        try:
            ids = await script_gallery.post_gallery(channel, reg["messages"].get(script_gallery.MESSAGES_KEY) or [])
        except discord.HTTPException as e:
            await _followup(interaction, f"Posten hat nicht geklappt: {e}")
            return
        reg["messages"][script_gallery.MESSAGES_KEY] = ids
        registry.save(store, interaction.guild_id, reg)
        await _followup(interaction, f"Fertig, die Bilder stehen in {channel.mention}.")

    @testserver.command(name="reset", description="Event-Channel leeren, alle Runden und Entwürfe löschen")
    async def reset_cmd(self, interaction: discord.Interaction):
        if not await _guard(interaction):
            return
        await interaction.response.send_message(texts.RESET_RUNNING, ephemeral=True)
        result = await server.reset_server(interaction.guild, self.bot.store)
        await _followup(interaction, result.summary())

    @testserver.command(name="delete_all", description="Alles entfernen, was Setup angelegt hat")
    async def delete_all_cmd(self, interaction: discord.Interaction):
        if not await _guard(interaction):
            return
        await interaction.response.send_message(texts.DELETE_CONFIRM, view=DeleteAllConfirmView(self, interaction.user.id),
                                                ephemeral=True)


async def setup(bot):
    await bot.add_cog(TestServerCog(bot))
