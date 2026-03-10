import re
import discord
from datetime import datetime, timezone


TAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]


def parse_events(messages: list[discord.Message]) -> list[dict]:
    events = []

    for msg in messages:
        if not msg.author.bot or not msg.embeds:
            continue

        embed = msg.embeds[0]
        if not embed.title or not embed.fields:
            continue

        time_field = next((f for f in embed.fields if f.name == "Time"), None)
        if not time_field:
            continue

        timestamps = re.findall(r"<t:(\d+):[FtTdDfR]>", time_field.value)
        if not timestamps:
            continue

        start_ts = int(timestamps[0])

        accepted = 0
        max_players = "?"
        for field in embed.fields:
            match = re.search(r"Accepted \((\d+)/(\d+)\)", field.name)
            if match:
                accepted = int(match.group(1))
                max_players = match.group(2)
                break

        events.append({
            "title": embed.title,
            "start_ts": start_ts,
            "accepted": accepted,
            "max_players": max_players,
        })

    events.sort(key=lambda e: e["start_ts"])
    return events


def build_overview(events: list[dict]) -> discord.Embed:
    embed = discord.Embed(title="Kommende Events", color=0x5865F2)

    if not events:
        embed.description = "Keine Events gefunden."
        return embed

    current_day = None
    day_text = ""
    day_label = ""

    for e in events:
        dt = datetime.fromtimestamp(e["start_ts"], tz=timezone.utc)
        day_key = dt.strftime("%Y-%m-%d")

        if day_key != current_day:
            if current_day and day_text:
                embed.add_field(name=day_label, value=day_text, inline=False)
            current_day = day_key
            day_text = ""
            day_label = f"{TAGE[dt.weekday()]} · {MONATE[dt.month - 1]} {dt.day}"

        # Titel kürzen falls zu lang
        title = e["title"]
        if len(title) > 40:
            title = title[:38] + ".."

        day_text += f"<t:{e['start_ts']}:t> {title} **({e['accepted']}/{e['max_players']})** <t:{e['start_ts']}:R>\n"

    if day_text:
        embed.add_field(name=day_label, value=day_text, inline=False)

    return embed