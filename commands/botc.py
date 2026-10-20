"""/botc: Einstieg in die Event-Erstellung (Modal, danach DM-Wizard)."""

import discord
from discord import app_commands
from discord.ext import commands

from config import get_guild_config
from discord_ui.botc_modal import BotcModal, ResumeOrNewView
from discord_ui.members import actor_from_member, fetch_member
from discord_ui.wizard import now
from events import guild_lock, permissions, service


def missing_create_permission_text(guild: discord.Guild, access) -> str:
    if access.storyteller_role_id is None:
        return ("Für diesen Server ist noch keine Storyteller-Rolle festgelegt. Bis dahin dürfen nur "
                "Event-Team und Admins Runden anlegen. Ein Admin kann die Rolle mit `/set_event_roles` setzen.")
    role = guild.get_role(access.storyteller_role_id)
    role_name = role.name if role else "Storyteller"
    return f"Runden anlegen dürfen nur Mitglieder mit der Rolle **{discord.utils.escape_markdown(role_name)}**."


# Diese Commands gibt es auf den Servern UND in den DMs mit dem Bot. bot.py registriert sie deshalb
# global statt nur je Server (siehe sync_commands).
DM_COMMANDS = ("botc", "botc2")


async def member_guilds(bot, user: discord.abc.User) -> list[tuple[discord.Guild, discord.Member]]:
    """Freigeschaltete Server, auf denen der User Mitglied ist (für /botc in den DMs)."""
    found = []
    for guild_id in sorted(guild_lock.allowed_guild_ids()):
        guild = bot.get_guild(guild_id)
        member = await fetch_member(bot, guild_id, user.id) if guild else None
        if member is not None:
            found.append((guild, member))
    return found


class GuildPickView(discord.ui.View):
    """/botc in den DMs bei mehreren Servern: für welchen Server ist die Runde?"""

    def __init__(self, cog: "Botc", choices: list[tuple[discord.Guild, discord.Member]], v2: bool):
        super().__init__(timeout=15 * 60)
        self.cog, self.choices, self.v2 = cog, {str(g.id): (g, m) for g, m in choices}, v2
        select = discord.ui.Select(placeholder="Server wählen", options=[
            discord.SelectOption(label=g.name[:100], value=str(g.id)) for g, _ in choices[:25]])
        select.callback = self._picked
        self.add_item(select)

    async def _picked(self, interaction: discord.Interaction):
        guild, member = self.choices[interaction.data["values"][0]]
        await self.cog._start_for(interaction, guild, member, self.v2)


class Botc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="botc", description="Neue Runde anlegen")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=False)
    @app_commands.allowed_installs(guilds=True, users=False)
    async def botc(self, interaction: discord.Interaction):
        await self._start(interaction, v2=False)

    @app_commands.command(name="botc2", description="Neue Runde anlegen (Test: Bearbeiten-Button je Feld)")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=False)
    @app_commands.allowed_installs(guilds=True, users=False)
    async def botc2(self, interaction: discord.Interaction):
        await self._start(interaction, v2=True)

    async def _start(self, interaction: discord.Interaction, v2: bool):
        if interaction.guild is not None:
            await self._start_for(interaction, interaction.guild, interaction.user, v2)
            return
        # In den DMs: Server über die Mitgliedschaft bestimmen
        choices = await member_guilds(self.bot, interaction.user)
        if not choices:
            await interaction.response.send_message(
                "Du bist auf keinem Server Mitglied, für den dieser Bot freigeschaltet ist.", ephemeral=True)
            return
        if len(choices) == 1:
            guild, member = choices[0]
            await self._start_for(interaction, guild, member, v2)
            return
        await interaction.response.send_message("Für welchen Server ist die Runde?",
                                                view=GuildPickView(self, choices, v2), ephemeral=True)

    async def _start_for(self, interaction: discord.Interaction, guild: discord.Guild, member: discord.Member,
                         v2: bool):
        store = self.bot.store
        actor = actor_from_member(member)
        access = service.get_access(store, guild.id)

        if not permissions.can(actor, permissions.CREATE, access):
            await interaction.response.send_message(missing_create_permission_text(guild, access),
                                                    ephemeral=True)
            return

        event_channel_id = get_guild_config(guild.id).get("event_channel_id")
        if not event_channel_id or not guild.get_channel(event_channel_id):
            await interaction.response.send_message(
                "Es ist noch kein Event-Channel eingerichtet. Ein Admin kann ihn mit `/set_event_channel` setzen.",
                ephemeral=True,
            )
            return

        allow_academy = permissions.can(actor, permissions.CREATE_ACADEMY, access)
        draft = service.open_draft(store, guild.id, member.id, now())
        if draft is not None and not v2:  # /botc2 (Test) startet immer neu
            await interaction.response.send_message(
                "Du hast noch einen offenen Entwurf. Weitermachen oder neu beginnen?",
                view=ResumeOrNewView(store, draft, allow_academy, guild, member),
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(BotcModal(store, allow_academy, v2=v2, guild=guild, member=member))


async def setup(bot):
    await bot.add_cog(Botc(bot))
