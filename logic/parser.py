import re
import discord
from datetime import datetime, timezone
from logic.ocr import analyse_attachment, get_top4, format_top4, load_characters


TAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]

FIELD_CHAR_LIMIT = 1024
EMBED_CHAR_LIMIT = 5500


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

    # events nach tag gruppieren
    days: dict[str, list] = {}
    day_labels: dict[str, str] = {}
    for e in events:
        dt = datetime.fromtimestamp(e["start_ts"], tz=timezone.utc)
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

        # field-value für diesen tag aufbauen
        # events mit skript bekommen zeilenumbruch danach, ausser das letzte
        chunks = []
        for i, e in enumerate(day_events):
            title = e["title"]
            if len(title) > 40:
                title = title[:38] + ".."

            line = f"> <t:{e['start_ts']}:t> [{title}]({e['url']}) **({e['accepted']}/{e['max_players']})** <t:{e['start_ts']}:R>"

            if e["top4"] and e.get("image_url"):
                line += f"\n> [🔗 Skript]({e['image_url']}) · {e['top4']}"
            elif e["top4"]:
                line += f"\n> {e['top4']}"

            # zeilenumbruch nach skript-zeile, ausser letztes event des tages
            has_skript = e["top4"] or e.get("image_url")
            is_last = i == len(day_events) - 1
            if has_skript and not is_last:
                line += "\n"

            chunks.append(line)

        # chunks zu fields zusammenfassen (max 1024 zeichen pro field)
        field_text = ""
        first_field = True
        for chunk in chunks:
            if len(field_text) + len(chunk) + 1 > FIELD_CHAR_LIMIT and field_text:
                # prüfen ob neuer embed nötig
                projected = embed_char_count(current_embed) + len(label if first_field else "\u200b") + len(field_text)
                if projected > EMBED_CHAR_LIMIT and current_embed.fields:
                    current_embed.set_footer(text="Zeiten werden in deiner lokalen Zeitzone angezeigt.")
                    embeds.append(current_embed)
                    current_embed = new_embed()
                    first_field = True
                current_embed.add_field(name=label if first_field else "\u200b", value=field_text, inline=False)
                first_field = False
                field_text = chunk + "\n"
            else:
                field_text += chunk + "\n"

        if field_text.strip():
            projected = embed_char_count(current_embed) + len(label if first_field else "\u200b") + len(field_text)
            if projected > EMBED_CHAR_LIMIT and current_embed.fields:
                current_embed.set_footer(text="Zeiten werden in deiner lokalen Zeitzone angezeigt.")
                embeds.append(current_embed)
                current_embed = new_embed()
                first_field = True
            current_embed.add_field(name=label if first_field else "\u200b", value=field_text.rstrip(), inline=False)

    current_embed.set_footer(text="Zeiten werden in deiner lokalen Zeitzone angezeigt.")
    embeds.append(current_embed)

    return embeds