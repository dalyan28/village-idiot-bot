"""/botc: Einstieg in die Event-Erstellung (Modal, danach DM-Wizard)."""

import discord
from discord import app_commands
from discord.ext import commands

from config import get_guild_config
from discord_ui.botc_modal import BotcModal, ResumeOrNewView
from discord_ui.members import actor_from_member
from discord_ui.wizard import now
from events import permissions, service


def missing_create_permission_text(guild: discord.Guild, access) -> str:
    if access.storyteller_role_id is None:
        return ("Für diesen Server ist noch keine Storyteller-Rolle festgelegt. Bis dahin dürfen nur "
                "Event-Team und Admins Runden anlegen. Ein Admin kann die Rolle mit `/set_event_roles` setzen.")
    role = guild.get_role(access.storyteller_role_id)
    role_name = role.name if role else "Storyteller"
    return f"Runden anlegen dürfen nur Mitglieder mit der Rolle **{discord.utils.escape_markdown(role_name)}**."


class Botc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="botc", description="Neue Runde anlegen")
    @app_commands.guild_only()
    async def botc(self, interaction: discord.Interaction):
        await self._start(interaction, v2=False)

    @app_commands.command(name="botc2", description="Neue Runde anlegen (Test: Bearbeiten-Button je Feld)")
    @app_commands.guild_only()
    async def botc2(self, interaction: discord.Interaction):
        await self._start(interaction, v2=True)

    async def _start(self, interaction: discord.Interaction, v2: bool):
        store = self.bot.store
        member = interaction.user
        actor = actor_from_member(member)
        access = service.get_access(store, interaction.guild_id)

        if not permissions.can(actor, permissions.CREATE, access):
            await interaction.response.send_message(missing_create_permission_text(interaction.guild, access),
                                                    ephemeral=True)
            return

        event_channel_id = get_guild_config(interaction.guild_id).get("event_channel_id")
        if not event_channel_id or not interaction.guild.get_channel(event_channel_id):
            await interaction.response.send_message(
                "Es ist noch kein Event-Channel eingerichtet. Ein Admin kann ihn mit `/set_event_channel` setzen.",
                ephemeral=True,
            )
            return

        allow_academy = permissions.can(actor, permissions.CREATE_ACADEMY, access)
        draft = service.open_draft(store, interaction.guild_id, member.id, now())
        if draft is not None and not v2:  # /botc2 (Test) startet immer neu
            await interaction.response.send_message(
                "Du hast noch einen offenen Entwurf. Weitermachen oder neu beginnen?",
                view=ResumeOrNewView(store, draft, allow_academy),
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(BotcModal(store, allow_academy, v2=v2))


async def setup(bot):
    await bot.add_cog(Botc(bot))
