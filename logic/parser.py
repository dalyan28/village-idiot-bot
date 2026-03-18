import re
import discord
from datetime import datetime, timezone
from logic.ocr import analyse_attachment, get_top4, format_top4, load_characters


TAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]

EMBED_CHAR_LIMIT = 5500
FIELD_CHAR_LIMIT = 1024


def embed_char_count(embed: discord.Embed) -> int:
    count = len(embed.title or "")
    for field in embed.fields:
        count += len(field.name) + len(field.value)
    return count


def new_embed() -> discord.Embed:
    return discord.Embed(title="Kommende Events", color=0x5865F2)


async def parse_events(messages: list[discord.Message], ocr_cache: dict, force_ocr: bool = False) -> tuple[list[dict], dict]:
    events = []
    characters = load_characters()

    aktuelle_ids = {str(msg.id) for msg in messages}
    ocr_cache = {k: v for k, v in ocr_cache.items() if k in aktuelle_ids}

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

        top4_str = ""
        msg_id = str(msg.id)
        image_url = None

        attachments = [a for a in msg.attachments if a.content_type and "image" in a.content_type]

        if attachments:
            image_url = attachments[0].url
        elif embed.image and embed.image.url:
            image_url = embed.image.url

        if image_url:
            if not force_ocr and msg_id in ocr_cache:
                top4_str = ocr_cache[msg_id]
            else:
                found = await analyse_attachment(image_url, characters)
                top4 = get_top4(found, characters)
                top4_str = format_top4(top4)
                ocr_cache[msg_id] = top4_str

        events.append({
            "title": embed.title,
            "start_ts": start_ts,
            "accepted": accepted,
            "max_players": max_players,
            "url": msg.jump_url,
            "top4": top4_str,
            "image_url": image_url,
        })

    events.sort(key=lambda e: e["start_ts"])
    return events, ocr_cache


def build_overviews(events: list[dict]) -> list[discord.Embed]:
    if not events:
        embed = new_embed()
        embed.description = "Keine Events gefunden."
        embed.set_footer(text="Zeiten werden in deiner lokalen Zeitzone angezeigt.")
        return [embed]

    embeds = []
    current_embed = new_embed()
    current_day = None
    day_label = ""
    # field_chunks = liste von (label, text) für aktuellen tag
    field_chunks = []
    current_chunk = ""
    current_label = ""

    def flush_chunks():
        nonlocal field_chunks, current_chunk, current_label, current_embed, embeds
        if current_chunk:
            field_chunks.append((current_label, current_chunk.rstrip()))
            current_chunk = ""

        for label, text in field_chunks:
            projected = embed_char_count(current_embed) + len(label) + len(text)
            if projected > EMBED_CHAR_LIMIT and current_embed.fields:
                current_embed.set_footer(text="Zeiten werden in deiner lokalen Zeitzone angezeigt.")
                embeds.append(current_embed)
                current_embed = new_embed()
            current_embed.add_field(name=label, value=text, inline=False)

        field_chunks = []

    for e in events:
        dt = datetime.fromtimestamp(e["start_ts"], tz=timezone.utc)
        day_key = dt.strftime("%Y-%m-%d")

        title = e["title"]
        if len(title) > 40:
            title = title[:38] + ".."

        line = f"> <t:{e['start_ts']}:t> [{title}]({e['url']}) **({e['accepted']}/{e['max_players']})** <t:{e['start_ts']}:R>"
        if e["top4"] and e.get("image_url"):
            line += f"\n> [🔗 Skript]({e['image_url']}) · {e['top4']}"
        elif e["top4"]:
            line += f"\n> {e['top4']}"
        line += "\n"

        if day_key != current_day:
            # vorherigen tag abschliessen
            flush_chunks()
            current_day = day_key
            current_label = f"{TAGE[dt.weekday()]} · {MONATE[dt.month - 1]} {dt.day}"
            current_chunk = line
        else:
            # prüfen ob event noch ins aktuelle chunk passt
            if len(current_chunk) + len(line) > FIELD_CHAR_LIMIT:
                # aktuelles chunk abschliessen, neues starten
                field_chunks.append((current_label, current_chunk.rstrip()))
                current_label = "\u200b"
                current_chunk = line
            else:
                current_chunk += line

    flush_chunks()
    current_embed.set_footer(text="Zeiten werden in deiner lokalen Zeitzone angezeigt.")
    embeds.append(current_embed)

    return embeds