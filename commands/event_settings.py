"""Rollen-Konfiguration der Event-Erstellung: wer Runden und Academy-Angebote anlegen darf."""

import discord
from discord import app_commands
from discord.ext import commands

from discord_ui.members import actor_from_member
from events import permissions, service


def _role_text(guild: discord.Guild, role_id: int | None) -> str:
    if role_id is None:
        return "nicht gesetzt"
    role = guild.get_role(role_id)
    return f"**{discord.utils.escape_markdown(role.name)}**" if role else f"gelöschte Rolle ({role_id})"


async def _user_text(guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.HTTPException:
            return f"ehemaliges Mitglied ({user_id})"
    return discord.utils.escape_markdown(member.display_name)


class EventSettings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _check(self, interaction: discord.Interaction) -> bool:
        actor = actor_from_member(interaction.user)
        if permissions.can(actor, permissions.CONFIGURE, service.get_access(self.bot.store, interaction.guild_id)):
            return True
        await interaction.response.send_message("Das dürfen nur Event-Team und Admins.", ephemeral=True)
        return False

    @app_commands.command(name="set_event_roles", description="Legt fest, wer Runden anlegen und verwalten darf")
    @app_commands.describe(
        storyteller="Rolle, die mit /botc Runden anlegen darf",
        event_team="Rolle, die alle Runden verwalten darf (nur Admins können sie ändern)",
        entfernen="Eine der beiden Rollen wieder entfernen",
    )
    @app_commands.choices(entfernen=[
        app_commands.Choice(name="Storyteller-Rolle", value="storyteller"),
        app_commands.Choice(name="Event-Team-Rolle", value="event_team"),
    ])
    @app_commands.guild_only()
    async def set_event_roles(self, interaction: discord.Interaction, storyteller: discord.Role | None = None,
                              event_team: discord.Role | None = None,
                              entfernen: app_commands.Choice[str] | None = None):
        if not await self._check(interaction):
            return
        if storyteller is None and event_team is None and entfernen is None:
            await interaction.response.send_message(
                "Gib eine Storyteller-Rolle, eine Event-Team-Rolle oder `entfernen` an.", ephemeral=True)
            return
        changes_team = event_team is not None or (entfernen and entfernen.value == "event_team")
        if changes_team and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "Die Event-Team-Rolle können nur Admins (Server verwalten) ändern.", ephemeral=True)
            return

        store = self.bot.store
        access = service.get_access(store, interaction.guild_id)
        if storyteller is not None:
            access.storyteller_role_id = storyteller.id
        if event_team is not None:
            access.event_team_role_id = event_team.id
        if entfernen is not None:
            setattr(access, f"{entfernen.value}_role_id", None)
        service.set_access(store, interaction.guild_id, access)
        await interaction.response.send_message(await self._summary(interaction.guild), ephemeral=True)

    @app_commands.command(name="set_academy_access",
                          description="Legt fest, wer Academy-Runden anlegen darf (Admins dürfen es immer)")
    @app_commands.describe(aktion="Freigabe hinzufügen oder entfernen", rolle="Rolle", mitglied="Einzelne Person")
    @app_commands.choices(aktion=[
        app_commands.Choice(name="hinzufügen", value="add"),
        app_commands.Choice(name="entfernen", value="remove"),
    ])
    @app_commands.guild_only()
    async def set_academy_access(self, interaction: discord.Interaction, aktion: app_commands.Choice[str],
                                 rolle: discord.Role | None = None, mitglied: discord.Member | None = None):
        if not await self._check(interaction):
            return
        if rolle is None and mitglied is None:
            await interaction.response.send_message("Gib eine Rolle oder ein Mitglied an.", ephemeral=True)
            return

        store = self.bot.store
        access = service.get_access(store, interaction.guild_id)
        for target, ids in ((rolle, access.academy_role_ids), (mitglied, access.academy_user_ids)):
            if target is None:
                continue
            if aktion.value == "add" and target.id not in ids:
                ids.append(target.id)
            elif aktion.value == "remove" and target.id in ids:
                ids.remove(target.id)
        service.set_access(store, interaction.guild_id, access)
        await interaction.response.send_message(await self._summary(interaction.guild), ephemeral=True)

    @app_commands.command(name="see_event_roles", description="Zeigt, wer Runden und Academy-Angebote anlegen darf")
    @app_commands.guild_only()
    async def see_event_roles(self, interaction: discord.Interaction):
        if not await self._check(interaction):
            return
        await interaction.response.send_message(await self._summary(interaction.guild), ephemeral=True)

    async def _summary(self, guild: discord.Guild) -> str:
        access = service.get_access(self.bot.store, guild.id)
        academy = [_role_text(guild, rid) for rid in access.academy_role_ids]
        academy += [await _user_text(guild, uid) for uid in access.academy_user_ids]
        lines = [
            "**Rechte für Runden**",
            f"Storyteller-Rolle (darf `/botc` nutzen): {_role_text(guild, access.storyteller_role_id)}",
            f"Event-Team-Rolle (verwaltet alle Runden): {_role_text(guild, access.event_team_role_id)}",
            f"Academy-Freigabe: {', '.join(academy) if academy else 'nur Admins'}",
            "-# Admins (Server verwalten) zählen immer zum Event-Team.",
        ]
        if access.storyteller_role_id is None:
            lines.append("-# Ohne Storyteller-Rolle dürfen nur Event-Team und Admins Runden anlegen.")
        return "\n".join(lines)


async def setup(bot):
    await bot.add_cog(EventSettings(bot))
