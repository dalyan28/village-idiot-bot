import logging
import time

import discord
from discord.ext import commands

from event_storage import save_event
from logic.event_builder import build_event_embed
from views.event_view import EventView

logger = logging.getLogger(__name__)


class EventCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def post_event(
        self,
        channel: discord.TextChannel,
        event_data: dict,
        script_image: discord.File | None = None,
    ) -> discord.Message:
        """Postet ein Event-Embed mit RSVP-Buttons und speichert es.

        Args:
            channel: Der Ziel-Channel für das Event.
            event_data: Dict mit allen Event-Feldern (siehe event_storage.py Datenmodell).
            script_image: Optionales Script-Bild als discord.File.

        Returns:
            Die gesendete Discord-Message.
        """
        event_data.setdefault("accepted", [])
        event_data.setdefault("declined", [])
        event_data.setdefault("tentative", [])
        event_data.setdefault("created_at", int(time.time()))
        event_data.setdefault("deleted_at", None)
        event_data["channel_id"] = channel.id
        event_data["guild_id"] = channel.guild.id

        embed = build_event_embed(event_data)

        if script_image:
            embed.set_image(url="attachment://script.png")

        view = EventView()
        kwargs = {"embed": embed, "view": view}
        if script_image:
            kwargs["file"] = script_image

        msg = await channel.send(**kwargs)

        # CDN-URL des Bildes speichern (für spätere Edits ohne Attachment-Probleme)
        if msg.embeds and msg.embeds[0].image and msg.embeds[0].image.url:
            event_data["image_url"] = msg.embeds[0].image.url

        save_event(msg.id, event_data)
        logger.info(
            "Event erstellt: '%s' von %s (msg_id=%s, channel=%s)",
            event_data.get("title"), event_data.get("creator_name"), msg.id, channel.name,
        )
        return msg


async def setup(bot: commands.Bot):
    await bot.add_cog(EventCommands(bot))
