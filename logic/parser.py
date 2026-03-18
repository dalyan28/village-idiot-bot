import re
import discord
from datetime import datetime, timezone
from logic.ocr import analyse_attachment, get_top4, format_top4, load_characters


TAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]

DESCRIPTION_CHAR_LIMIT = 4096


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


def build_day_text(day_events: list[dict], day_label: str) -> str:
    text = f"**{day_label}**\n"
    for i, e in enumerate(day_events):
        title = e["title"]
        if len(title) > 40:
            title = title[:38] + ".."

        line = f"> <t:{e['start_ts']}:t> [{title}]({e['url']}) **({e['accepted']}/{e['max_players']})** <t:{e['start_ts']}:R>"

        if e["top4"] and e.get("image_url"):
            line += f"\n> 　　↳ [🔗 Skript]({e['image_url']}) · {e['top4']}"
        elif e["top4"]:
            line += f"\n> 　　↳ {e['top4']}"

        line += "\n"
        text += line
    return text


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
    current_desc = ""

    for day_key in sorted(days.keys()):
        label = day_labels[day_key]
        day_text = build_day_text(days[day_key], label)

        if len(day_text) > DESCRIPTION_CHAR_LIMIT:
            # tag ist zu lang, event für event splitten
            print(f"Tag '{label}' überschreitet Limit alleine ({len(day_text)} Zeichen), splitte innerhalb des Tages")
            header = f"**{label}**\n"

            if current_desc:
                current_embed.description = current_desc.strip()
                current_embed.set_footer(text="Zeiten werden in deiner lokalen Zeitzone angezeigt.")
                embeds.append(current_embed)
                current_embed = new_embed()
                current_desc = ""

            current_desc = header
            for i, e in enumerate(days[day_key]):
                title = e["title"]
                if len(title) > 40:
                    title = title[:38] + ".."

                line = f"> <t:{e['start_ts']}:t> [{title}]({e['url']}) **({e['accepted']}/{e['max_players']})** <t:{e['start_ts']}:R>"
                if e["top4"] and e.get("image_url"):
                    line += f"\n> 　　↳ [Skript]({e['image_url']}) · {e['top4']}" #test
                elif e["top4"]:
                    line += f"\n> 　　↳ {e['top4']}"
                line += "\n"

                if len(current_desc) + len(line) > DESCRIPTION_CHAR_LIMIT:
                    print(f"Split mitten im Tag '{label}' bei Event '{e['title']}'")
                    current_embed.description = current_desc.strip()
                    current_embed.set_footer(text="Zeiten werden in deiner lokalen Zeitzone angezeigt.")
                    embeds.append(current_embed)
                    current_embed = new_embed()
                    current_desc = f"**{label} (Fortsetzung)**\n" + line
                else:
                    current_desc += line

        elif len(current_desc) + len(day_text) > DESCRIPTION_CHAR_LIMIT:
            # tag passt nicht mehr rein, neuen embed starten
            print(f"Neuer Embed vor Tag '{label}' - vorheriger war {len(current_desc)} Zeichen")
            current_embed.description = current_desc.strip()
            current_embed.set_footer(text="Zeiten werden in deiner lokalen Zeitzone angezeigt.")
            embeds.append(current_embed)
            current_embed = new_embed()
            current_desc = day_text
        else:
            current_desc += day_text

    current_embed.description = current_desc.strip()
    current_embed.description += "\n\n*Klassischer oder informativer Wochenplan? [Stimm hier ab!](https://discord.com/channels/1197876498980421652/1197881790623395952/1483740867121647638)*"
    current_embed.set_footer(text="Zeiten werden in deiner lokalen Zeitzone angezeigt.")
    embeds.append(current_embed)

    return embeds