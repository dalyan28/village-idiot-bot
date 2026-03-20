import logging
import discord

logger = logging.getLogger(__name__)


def format_user_list(user_ids: list[int]) -> str:
    if not user_ids:
        return "-"
    return "\n".join(f"<@{uid}>" for uid in user_ids)


def build_event_embed(event_data: dict) -> discord.Embed:
    embed = discord.Embed(
        title=event_data.get("title", "Event"),
        description=event_data.get("description") or "",
        color=0x5865F2,
    )

    # Storyteller:in
    storyteller = event_data.get("storyteller") or "-"
    embed.add_field(name="Storyteller:in", value=storyteller, inline=False)

    # Skript
    script = event_data.get("script") or "-"
    embed.add_field(name="Skript:", value=script, inline=False)

    # Level
    level = event_data.get("level") or "-"
    embed.add_field(name="Level:", value=level, inline=False)

    # Termin
    ts = event_data.get("timestamp")
    end_ts = event_data.get("end_timestamp")
    if ts:
        if end_ts:
            termin_value = f"<t:{ts}:F> - <t:{end_ts}:t>\n<t:{ts}:R>"
        else:
            termin_value = f"<t:{ts}:F>\n<t:{ts}:R>"
    else:
        termin_value = "-"
    embed.add_field(name="Termin:", value=termin_value, inline=False)

    # Weitere Informationen (nur wenn vorhanden)
    additional = event_data.get("additional_info")
    if additional:
        embed.add_field(name="Weitere Informationen:", value=additional, inline=False)

    # Separator
    embed.add_field(name="\u200b", value="\u200b", inline=False)

    # RSVP-Listen
    accepted = event_data.get("accepted", [])
    declined = event_data.get("declined", [])
    tentative = event_data.get("tentative", [])

    embed.add_field(
        name=f"✅ Akzeptiert ({len(accepted)})",
        value=format_user_list(accepted),
        inline=False,
    )
    embed.add_field(
        name="❌ Abgelehnt",
        value=format_user_list(declined),
        inline=False,
    )
    embed.add_field(
        name=f"❓ Vorläufig ({len(tentative)})",
        value=format_user_list(tentative),
        inline=False,
    )

    # Footer
    creator = event_data.get("creator_name", "Unbekannt")
    embed.set_footer(text=f"Erstellt von {creator}")

    logger.debug("Embed gebaut für Event '%s'", event_data.get("title"))
    return embed
