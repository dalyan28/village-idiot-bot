"""/botc: Einstieg in die Event-Erstellung (Modal, danach DM-Wizard)."""

import discord
from discord import app_commands
from discord.ext import commands

from discord_ui.botc_start import start_layout, start_problem
from discord_ui.members import NOT_READY, actor_from_member, fetch_member, is_ready
from discord_ui import wizard
from events import guild_lock, service


# Diese Commands gibt es auf den Servern UND in den DMs mit dem Bot. bot.py registriert sie deshalb
# global statt nur je Server (siehe sync_commands).
DM_COMMANDS = ("botc", "skriptblatt_paket")  # skriptblatt_paket nur mit SCRIPT_SHEET_UPLOAD=1 geladen


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

    def __init__(self, cog: "Botc", choices: list[tuple[discord.Guild, discord.Member]]):
        super().__init__(timeout=15 * 60)
        self.cog, self.choices = cog, {str(g.id): (g, m) for g, m in choices}
        select = discord.ui.Select(placeholder="Server wählen", options=[
            discord.SelectOption(label=g.name[:100], value=str(g.id)) for g, _ in choices[:25]])
        select.callback = self._picked
        self.add_item(select)

    async def _picked(self, interaction: discord.Interaction):
        guild, member = self.choices[interaction.data["values"][0]]
        await self.cog._start_for(interaction, guild, member)


class Botc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        from discord_ui import text_edit

        if await text_edit.take_text(self.bot, message):
            return
        await take_chat_text(self.bot, message)

    @app_commands.command(name="botc", description="Neue Runde anlegen")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=False)
    @app_commands.allowed_installs(guilds=True, users=False)
    async def botc(self, interaction: discord.Interaction):
        await self._start(interaction)

    async def _start(self, interaction: discord.Interaction):
        if not is_ready(self.bot):
            await interaction.response.send_message(NOT_READY, ephemeral=True)
            return
        if interaction.guild is not None:
            await self._start_for(interaction, interaction.guild, interaction.user)
            return
        # In den DMs: Server über die Mitgliedschaft bestimmen
        choices = await member_guilds(self.bot, interaction.user)
        if not choices:
            await interaction.response.send_message(
                "Du bist auf keinem Server Mitglied, für den dieser Bot freigeschaltet ist.", ephemeral=True)
            return
        if len(choices) == 1:
            guild, member = choices[0]
            await self._start_for(interaction, guild, member)
            return
        await interaction.response.send_message("Für welchen Server ist die Runde?",
                                                view=GuildPickView(self, choices), ephemeral=True)

    async def _start_for(self, interaction: discord.Interaction, guild: discord.Guild, member: discord.Member):
        """Startnachricht in den DMs (Dalyan, 20.10.2026); in einem Channel nur ein kurzer Hinweis."""
        store = self.bot.store
        problem = start_problem(store, guild, member)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        # Erst bestätigen: Das Skript-Bild des offenen Entwurfs kann einen Moment dauern (3-Sekunden-Grenze)
        in_dm = interaction.guild is None
        await interaction.response.defer(ephemeral=not in_dm)
        layout, files = await start_layout(guild, member.id,
                                           service.open_draft(store, guild.id, member.id, wizard.now()),
                                           links=service.get_start_links(store, guild.id))
        if in_dm:
            await interaction.followup.send(view=layout, files=files)
            return
        try:
            await member.send(view=layout, files=files)
        except discord.Forbidden:
            await interaction.followup.send(
                "Ich kann dir keine DM schicken. Erlaube DMs von Servermitgliedern "
                "(Servereinstellungen → Privatsphäre) und starte `/botc` dann erneut.", ephemeral=True)
            return
        await interaction.followup.send("Es geht in deinen DMs weiter.", ephemeral=True)


async def take_chat_text(bot, message: discord.Message) -> bool:
    """DM-Nachricht als Titel bzw. Beschreibung übernehmen, wenn ein Entwurf darauf wartet."""

    if message.guild is not None or message.author.bot:
        return False
    store = bot.store
    draft = next((d for d in store.list_drafts(message.author.id) if (d.ui or {}).get(wizard.AWAIT_KEY)), None)
    if draft is None:
        return False
    member = await fetch_member(bot, draft.guild_id, message.author.id)
    if member is None or not guild_lock.is_allowed(draft.guild_id):
        return False
    wait = dict(draft.ui[wizard.AWAIT_KEY])
    ctx = wizard.WizardContext(bot, store, draft, actor_from_member(member), member)
    try:
        notice = wizard.apply_chat_text(ctx, message.content)
    except service.ServiceError as e:
        notice = str(e)
    layout, files = await wizard.render(bot, ctx.draft, notice)
    try:
        target = await message.channel.fetch_message(wait["message_id"]) if wait.get("message_id") else None
    except discord.HTTPException:
        target = None
    if target is not None:
        await target.edit(view=layout, attachments=files)
    else:
        await message.channel.send(view=layout, files=files)
    if notice is None:
        try:
            await message.add_reaction("✅")
        except discord.HTTPException:
            pass
    return True


async def setup(bot):
    await bot.add_cog(Botc(bot))
