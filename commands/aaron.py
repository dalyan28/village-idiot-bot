import re
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from config import get_guild_config
from logic.parser import parse_events

BERLIN_TZ = ZoneInfo("Europe/Berlin")
AARON_ID = 1424409721187729489
HEADER = "Hier die heutigen Events zum Rauskopieren. Thanks for being the real Town Crier 🥹"
EMOJI_CODE = re.compile(r"<a?:\w+:\d+>|:[a-z_+][a-z0-9_+-]*:")
EMOJI_CATEGORIES = {"So", "Sk", "Mn", "Me", "Cf"}
MIN_LINK_CHARS = 2


def _is_emoji(c: str) -> bool:
    # ab U+2000, sonst wären umlaut-akzente und © auch emojis
    return ord(c) >= 0x2000 and unicodedata.category(c) in EMOJI_CATEGORIES


def _split_emojis(title: str) -> list[tuple[bool, str]]:
    parts = []
    i = 0
    while i < len(title):
        code = EMOJI_CODE.match(title, i)
        end = code.end() if code else i + 1
        is_emoji = bool(code) or _is_emoji(title[i])
        if parts and parts[-1][0] == is_emoji:
            parts[-1] = (is_emoji, parts[-1][1] + title[i:end])
        else:
            parts.append((is_emoji, title[i:end]))
        i = end
    return parts


def link_title(title: str, url: str) -> str:
    # discord baut im nachrichtentext keinen link mit emojis drin, deshalb nur den text dazwischen verlinken
    pieces = []
    for is_emoji, text in _split_emojis(title.strip()):
        if is_emoji or sum(c.isalnum() for c in text) < MIN_LINK_CHARS:
            pieces.append(("emoji" if is_emoji else "text", text))
        else:
            pieces.append(("text", " " if text[0].isspace() else ""))
            pieces.append(("link", f"[{text.strip()}]({url})"))
            pieces.append(("text", " " if text[-1].isspace() else ""))
    if not any(kind == "link" for kind, _ in pieces):
        return f"[{title.strip()}]({url})"

    out = ""
    prev = None
    for kind, text in pieces:
        if not text:
            continue
        # angeklebte emojis bekommen ein leerzeichen zum link
        if {prev, kind} == {"emoji", "link"}:
            out += " "
        out += text
        prev = kind
    return " ".join(out.split())


def todays_lines(events: list[dict], today: date) -> list[str]:
    lines = []
    for e in events:
        start = datetime.fromtimestamp(e["start_ts"], tz=BERLIN_TZ)
        if start.date() != today:
            continue
        # uhrzeit als code, damit alle zeilen bündig sind. <> um die url verhindert die vorschau
        lines.append(f"`{start:%H:%M}` {link_title(e['title'], '<' + e['url'] + '>')}")
    return lines


def to_code_blocks(lines: list[str], limit: int = 2000) -> list[str]:
    # Codeblock, damit Links und Formatierung beim Kopieren roh bleiben
    blocks = []
    current = ""
    for line in lines:
        if current and len(current) + 1 + len(line) + 8 > limit:
            blocks.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        blocks.append(current)
    return [f"```\n{b}\n```" for b in blocks]


def build_messages(lines: list[str]) -> list[str]:
    # header steht über dem codeblock, damit er nicht mitkopiert wird
    messages = to_code_blocks(lines, limit=2000 - len(HEADER) - 1)
    if messages:
        messages[0] = f"{HEADER}\n{messages[0]}"
    return messages


class Aaron(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="aaron", description="Die heutigen Events zum Rauskopieren")
    @app_commands.guild_only()
    async def aaron(self, interaction: discord.Interaction):
        if interaction.user.id != AARON_ID and not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("Du bist nicht Aaron 👀", ephemeral=True)
            return

        cfg = get_guild_config(interaction.guild_id)
        event_channel_id = cfg.get("event_channel_id")
        event_channel = self.bot.get_channel(event_channel_id) if event_channel_id else None
        if not event_channel:
            await interaction.response.send_message(
                "Kein Event-Channel gesetzt. Bitte erst `/set_event_channel` nutzen.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        messages = [msg async for msg in event_channel.history(limit=100)]
        lines = todays_lines(parse_events(messages), datetime.now(tz=BERLIN_TZ).date())

        if not lines:
            await interaction.followup.send("Heute stehen keine Events an.", ephemeral=True)
            return
        for message in build_messages(lines):
            await interaction.followup.send(message, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Aaron(bot))
