import re
import discord
from datetime import datetime
from zoneinfo import ZoneInfo


TAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]

BERLIN_TZ = ZoneInfo("Europe/Berlin")
KUERZEL = (("CET", "MEZ"), ("CEST", "MESZ"))

FIELD_CHAR_LIMIT = 1024
EMBED_CHAR_LIMIT = 5500


def embed_char_count(embed: discord.Embed) -> int:
    count = len(embed.title or "")
    for field in embed.fields:
        count += len(field.name) + len(field.value)
    return count


def new_embed() -> discord.Embed:
    return discord.Embed(title="Kommende Events", color=0x0083C2)


def parse_events(messages: list[discord.Message]) -> list[dict]:
    events = []

    for msg in messages:
        if not msg.author.bot or not msg.embeds:
            continue

        embed = msg.embeds[0]
        if not embed.title or not embed.fields:
            continue

        time_field = next((f for f in embed.fields if f.name in ("Time", "Termin")), None)
        if not time_field:
            continue

        timestamps = re.findall(r"<t:(\d+):[FtTdDfR]>", time_field.value)
        if not timestamps:
            continue

        start_ts = int(timestamps[0])

        accepted = 0
        max_players = "?"
        for field in embed.fields:
            match = re.search(r"(?:Accepted|Akzeptiert) \((\d+)/(\d+)\)", field.name)
            if match:
                accepted = int(match.group(1))
                max_players = match.group(2)
                break

        events.append({
            "title": embed.title,
            "start_ts": start_ts,
            "accepted": accepted,
            "max_players": max_players,
            "url": msg.jump_url,
        })

    events.sort(key=lambda e: e["start_ts"])
    return events


def build_footer(events: list[dict]) -> str:
    # kürzel der angezeigten termine, um die zeitumstellung herum beide
    names = {datetime.fromtimestamp(e["start_ts"], tz=BERLIN_TZ).tzname() for e in events}
    names = names or {datetime.now(tz=BERLIN_TZ).tzname()}
    kuerzel = "/".join(de for en, de in KUERZEL if en in names)
    return f"Alle Zeiten und Daten in deutscher Zeit ({kuerzel})."


def build_overviews(events: list[dict]) -> list[discord.Embed]:
    footer = build_footer(events)
    if not events:
        embed = new_embed()
        embed.description = "Keine Events gefunden."
        embed.set_footer(text=footer)
        return [embed]

    # events nach tag gruppieren
    days: dict[str, list] = {}
    day_labels: dict[str, str] = {}
    for e in events:
        dt = datetime.fromtimestamp(e["start_ts"], tz=BERLIN_TZ)
        day_key = dt.strftime("%Y-%m-%d")
        if day_key not in days:
            days[day_key] = []
            day_labels[day_key] = f"{TAGE[dt.weekday()]} · {MONATE[dt.month - 1]} {dt.day}"
        days[day_key].append(e)

    embeds = []
    current_embed = new_embed()

    for day_key in sorted(days.keys()):
        day_events = days[day_key]
        label = day_labels[day_key]

        # alle events des tages als einen textblock zusammenbauen
        chunks = []
        for e in day_events:
            title = e["title"]
            if len(title) > 40:
                title = title[:38] + ".."
            # uhrzeit in berliner zeit, ortszeit per hover auf <t:..:R>
            start = datetime.fromtimestamp(e["start_ts"], tz=BERLIN_TZ)
            line = f"> `{start:%H:%M}` [{title}]({e['url']}) **({e['accepted']}/{e['max_players']})** <t:{e['start_ts']}:R>\n"
            chunks.append(line)

        # chunks zu fields zusammenfassen, dabei event-blöcke nicht trennen
        field_text = ""
        first_field = True

        for chunk in chunks:
            if len(field_text) + len(chunk) > FIELD_CHAR_LIMIT and field_text:
                # prüfen ob neuer embed nötig
                projected = embed_char_count(current_embed) + len(label if first_field else "\u200b") + len(field_text)
                if projected > EMBED_CHAR_LIMIT and current_embed.fields:
                    current_embed.set_footer(text=footer)
                    embeds.append(current_embed)
                    current_embed = new_embed()
                    first_field = True
                current_embed.add_field(name=label if first_field else "\u200b", value=field_text.rstrip(), inline=False)
                first_field = False
                field_text = chunk
            else:
                field_text += chunk

        if field_text.strip():
            projected = embed_char_count(current_embed) + len(label if first_field else "\u200b") + len(field_text)
            if projected > EMBED_CHAR_LIMIT and current_embed.fields:
                current_embed.set_footer(text=footer)
                embeds.append(current_embed)
                current_embed = new_embed()
                first_field = True
            current_embed.add_field(name=label if first_field else "\u200b", value=field_text.rstrip(), inline=False)

    current_embed.set_footer(text=footer)
    embeds.append(current_embed)

    return embeds