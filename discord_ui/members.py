"""Hilfen rund um Server-Mitglieder: Actor für die Rechteprüfung, Anzeigenamen."""

from __future__ import annotations

import discord

from events.permissions import Actor


def actor_from_member(member: discord.Member) -> Actor:
    return Actor(
        user_id=member.id,
        role_ids=frozenset(r.id for r in member.roles),
        is_admin=member.guild_permissions.manage_guild,
    )


def display_name(member: discord.abc.User) -> str:
    """Server-Nickname vor globalem Namen vor Username."""
    return member.display_name


async def fetch_member(bot: discord.Client, guild_id: int, user_id: int) -> discord.Member | None:
    """Mitglied aus dem Cache oder per REST (ohne Members-Intent ist der Cache oft leer).

    Wird gebraucht, wenn eine Interaktion aus den DMs kommt und keine Rollen mitliefert.
    """
    guild = bot.get_guild(guild_id)
    if guild is None:
        return None
    member = guild.get_member(user_id)
    if member is not None:
        return member
    # Ein kurzer Aussetzer bei Discord (z. B. 5xx) soll nicht wie „kein Mitglied“ aussehen: einmal wiederholen
    for attempt in range(2):
        try:
            return await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden):
            return None
        except discord.HTTPException:
            if attempt == 1:
                return None
    return None


NOT_READY = ("Der Bot ist gerade erst neu gestartet und noch nicht ganz bereit. "
             "Versuch es bitte in ein paar Sekunden noch einmal.")


def is_ready(bot: discord.Client) -> bool:
    """Nach einem Neustart kennt der Bot die Server erst, wenn er bereit ist."""
    check = getattr(bot, "is_ready", None)
    return check() if callable(check) else True
