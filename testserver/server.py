"""Testserver aufsetzen, zurücksetzen und abbauen. Von /testserver aufgerufen, ohne Interaction testbar.

Setup ist mehrfach ausführbar: Was schon da ist, wird über die gespeicherten IDs (Fallback: Name)
wiedergefunden und aufgefrischt statt doppelt angelegt.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import discord

import config as bot_config
from events import service
from events.schema import EventData
from events.store import Store
from logic.event_images import delete_custom_image
from testserver import bot_texts, registry, texts

logger = logging.getLogger(__name__)

REASON = "Village Idiot /testserver"

READONLY, EVENTS, WRITE = "readonly", "events", "write"
# Klein gehalten, wir sind sechs Leute (Dalyan, 20.10.2026). Kein Sprachchat.
# (Kategorie-Key, Kategorie-Name, [(Channel-Key, „Emoji︱name“ wie auf dem echten Server, Rechte für alle)])
CATEGORY_PLAN = [
    ("start", "Start", [
        ("welcome", "👋︱willkommen", READONLY),
        ("texts", "🗒️︱texte", WRITE),
        ("chat", "💬︱chat", WRITE),
        ("feedback", "📝︱feedback", WRITE),
    ]),
    ("rounds", "Runden", [
        ("events", "📅︱events", EVENTS),
        ("overview", "📋︱übersicht", READONLY),
    ]),
]
CHANNEL_PLAN = [ch for _, _, channels in CATEGORY_PLAN for ch in channels]
# (Key, Rollenname); Setup trägt sie wie /set_event_roles ein
ROLE_PLAN = [("storyteller", "Storyteller"), ("event_team", "Event-Team")]

# Bleibt bei Delete All stehen, damit das Feedback nicht verloren geht (Dalyan, 20.10.2026)
KEEP_ON_DELETE = "feedback"

MESSAGE_LIMIT = 2000


# ── Rechte ───────────────────────────────────────────────────────────────────


_NO_THREADS = dict(create_public_threads=False, create_private_threads=False)


def everyone_overwrite(mode: str) -> discord.PermissionOverwrite:
    if mode == WRITE:
        return discord.PermissionOverwrite(view_channel=True, send_messages=True, add_reactions=True, **_NO_THREADS)
    # Im Event-Channel darf man in den Reminder-Threads schreiben, sonst nirgends
    return discord.PermissionOverwrite(view_channel=True, send_messages=False, add_reactions=False,
                                       send_messages_in_threads=mode == EVENTS, **_NO_THREADS)


def bot_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True, send_messages=True, embed_links=True, attach_files=True, read_message_history=True,
        manage_messages=True, manage_threads=True, create_public_threads=True, send_messages_in_threads=True,
    )


def channel_overwrites(guild: discord.Guild, mode: str) -> dict:
    return {guild.default_role: everyone_overwrite(mode), guild.me: bot_overwrite()}


# ── Setup ────────────────────────────────────────────────────────────────────


@dataclass
class SetupResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = ["Fertig." if not self.failed else "Fertig, aber nicht alles hat geklappt."]
        if self.created:
            lines.append(f"Neu: {', '.join(self.created)}")
        if self.updated:
            lines.append(f"Aufgefrischt: {', '.join(self.updated)}")
        if self.failed:
            lines.append(f"Hat nicht geklappt: {', '.join(self.failed)}")
            lines.append("-# Meist fehlen dem Bot Rechte (Kanäle verwalten, Rollen verwalten).")
        return "\n".join(lines)


def _by_name(items, name: str):
    folded = name.casefold()
    return next((i for i in items if i.name.casefold() == folded), None)


async def ensure_sample_event(bot, guild: discord.Guild, store: Store, member, result: SetupResult):
    """Beim ersten Setup ein volles Beispiel-Event posten; gibt es schon eins, bleibt es."""
    from testserver.sample_event import create_sample_event

    reg = registry.get(store, guild.id)
    if reg["sample_event"] and store.get_event(reg["sample_event"]) is not None:
        return
    try:
        event = await create_sample_event(bot, store, guild, member)
    except Exception:
        logger.exception("Testserver: Beispiel-Event fehlgeschlagen")
        result.failed.append("Beispiel-Event")
        return
    reg = registry.get(store, guild.id)
    reg["sample_event"] = event.id
    registry.save(store, guild.id, reg)
    result.created.append("Beispiel-Event")


async def setup_server(guild: discord.Guild, store: Store) -> SetupResult:
    result = SetupResult()
    reg = registry.get(store, guild.id)

    # Rollen
    for key, name in ROLE_PLAN:
        role = guild.get_role(reg["roles"].get(key) or 0) or _by_name(guild.roles, name)
        try:
            if role is None:
                role = await guild.create_role(name=name, mentionable=False, reason=REASON)
                result.created.append(f"Rolle {name}")
            else:
                result.updated.append(f"Rolle {role.name}")
        except discord.HTTPException as e:
            logger.warning("Testserver: Rolle %s fehlgeschlagen: %s", name, e)
            result.failed.append(f"Rolle {name}")
            continue
        reg["roles"][key] = role.id
    access = service.get_access(store, guild.id)
    access.storyteller_role_id = reg["roles"].get("storyteller", access.storyteller_role_id)
    access.event_team_role_id = reg["roles"].get("event_team", access.event_team_role_id)
    service.set_access(store, guild.id, access)

    # Kategorien und Channels
    cat_overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=True), guild.me: bot_overwrite()}
    for cat_position, (cat_key, cat_name, channels) in enumerate(CATEGORY_PLAN):
        category = guild.get_channel(reg["categories"].get(cat_key) or 0) or _by_name(guild.categories, cat_name)
        try:
            if category is None:
                category = await guild.create_category(cat_name, overwrites=cat_overwrites, position=cat_position,
                                                       reason=REASON)
                result.created.append(f"Kategorie {cat_name}")
            else:
                await category.edit(name=cat_name, overwrites=cat_overwrites, position=cat_position, reason=REASON)
                result.updated.append(f"Kategorie {cat_name}")
        except discord.HTTPException as e:
            logger.warning("Testserver: Kategorie %s fehlgeschlagen: %s", cat_name, e)
            result.failed.append(f"Kategorie {cat_name}")
            continue
        reg["categories"][cat_key] = category.id
        for position, (key, name, mode) in enumerate(channels):
            overwrites = channel_overwrites(guild, mode)
            channel = guild.get_channel(reg["channels"].get(key) or 0) or _by_name(category.channels, name)
            try:
                if channel is None:
                    channel = await category.create_text_channel(name, overwrites=overwrites, position=position,
                                                                 reason=REASON)
                    result.created.append(channel.mention)
                else:
                    await channel.edit(name=name, category=category, overwrites=overwrites, position=position,
                                       reason=REASON)
                    result.updated.append(channel.mention)
            except discord.HTTPException as e:
                logger.warning("Testserver: Channel %s fehlgeschlagen: %s", name, e)
                result.failed.append(f"#{name}")
                continue
            reg["channels"][key] = channel.id
    registry.save(store, guild.id, reg)

    # Event- und Übersichts-Channel beim Bot eintragen (wie /set_event_channel, /set_overview_channel)
    cfg = bot_config.get_guild_config(guild.id)
    for key, cfg_key in (("events", "event_channel_id"), ("overview", "overview_channel_id")):
        if key in reg["channels"]:
            cfg[cfg_key] = reg["channels"][key]
    bot_config.save_guild_config(guild.id, cfg)

    await update_texts(guild, store, result)
    return result


# Channels mit festen Texten (für /testserver update)
TEXT_CHANNELS = ("welcome", "texts", "feedback", "chat")


def text_channel_key(store: Store, guild_id: int, channel_id: int) -> str | None:
    """Key des Channels, wenn er feste Texte hat (sonst None)."""
    channels = registry.get(store, guild_id)["channels"]
    return next((k for k in TEXT_CHANNELS if channels.get(k) == channel_id), None)


async def update_texts(guild: discord.Guild, store: Store, result: SetupResult | None = None,
                       only: str | None = None) -> SetupResult:
    """Feste Texte posten bzw. bearbeiten, ohne Channels, Rollen oder Rechte anzufassen.
    `only`: nur dieser Channel (Key aus TEXT_CHANNELS)."""
    result = result or SetupResult()
    reg = registry.get(store, guild.id)
    # mehrere Texte in einem Channel bleiben in dieser Reihenfolge
    links = {k: f"<#{cid}>" for k, cid in reg["channels"].items()}
    def filled(*channel_texts):
        values = {k: links.get(k, f"#{k}") for k, _, _ in CHANNEL_PLAN} | {"rater_url": texts.RATER_URL}
        return [text.format(**values) for text in channel_texts]

    posts = {"welcome": filled(texts.WELCOME), "texts": bot_texts.posts(),
             "feedback": filled(texts.FEEDBACK_INTRO), "chat": filled(texts.CHAT_INTRO)}
    for key, channel_texts in posts.items():
        if only and key != only:
            continue
        channel = guild.get_channel(reg["channels"].get(key) or 0)
        if channel is None:
            result.failed.append(f"#{key} (gibt es nicht, erst /testserver setup)")
            continue
        parts = [part for text in channel_texts for part in split_message(text)]
        try:
            ids, appended = await _post_or_edit(channel, parts, reg["messages"].get(key) or [])
            reg["messages"][key] = ids
            if key == "welcome":  # Test-Karte direkt unter der Willkommensnachricht
                reg["messages"][CARD_KEY] = await _post_card(channel, reg, appended)
        except discord.HTTPException as e:
            logger.warning("Testserver: Text für %s fehlgeschlagen: %s", key, e)
            result.failed.append(f"Text in #{channel.name}")
            continue
        result.updated.append(f"Text in {channel.mention}")
        registry.save(store, guild.id, reg)
    return result


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Teilt an Absätzen, damit jede Nachricht unter Discords Grenze bleibt."""
    parts, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(block) > limit:
            parts.append(block[:limit])
            block = block[limit:]
        current = block
    if current:
        parts.append(current)
    return parts


async def _post_or_edit(channel, parts: list[str], old_ids: list[int]) -> tuple[list[int], bool]:
    """Vorhandene Beiträge der Reihe nach bearbeiten, überzählige löschen, fehlende anhängen
    (Dalyan, 26.10.2026: nicht mehr alles löschen und neu posten). Gibt (IDs, ob neu angehängt wurde) zurück."""
    old = []
    for mid in old_ids:
        try:
            old.append(await channel.fetch_message(mid))
        except (discord.NotFound, discord.Forbidden):
            pass
    no_pings = discord.AllowedMentions.none()
    ids = []
    for msg, part in zip(old, parts):
        if msg.content != part:
            await msg.edit(content=part, allowed_mentions=no_pings)
        ids.append(msg.id)
    for msg in old[len(parts):]:
        try:
            await msg.delete()
        except discord.HTTPException:
            pass
    appended = len(parts) > len(old)
    for part in parts[len(old):]:
        ids.append((await channel.send(part, allowed_mentions=no_pings)).id)
    return ids, appended


CARD_KEY = "welcome_card"


async def _post_card(channel, reg: dict, repost: bool) -> list[int]:
    """Test-Karte bearbeiten oder (neu) posten. `repost`: Es kamen Beiträge darüber hinzu, also muss die
    Karte wieder ans Ende."""
    from testserver.test_card import card_layout

    layout = card_layout(f"<#{reg['channels']['events']}>" if reg["channels"].get("events") else "#events",
                         channel.guild.id)
    old = None
    for mid in reg["messages"].get(CARD_KEY) or []:
        try:
            old = await channel.fetch_message(mid)
        except (discord.NotFound, discord.Forbidden):
            old = None
    if old is not None and not repost:
        await old.edit(view=layout)
        return [old.id]
    if old is not None:
        try:
            await old.delete()
        except discord.HTTPException:
            pass
    return [(await channel.send(view=layout)).id]


# ── Reset ────────────────────────────────────────────────────────────────────


@dataclass
class ResetResult:
    events: int = 0
    drafts: int = 0
    messages: int = 0
    threads: int = 0
    problems: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Event-Channel ist leer. Weg sind {self.events} Runden, {self.drafts} Entwürfe, "
                 f"{self.messages} Nachrichten und {self.threads} Threads."]
        lines += [f"-# {p}" for p in self.problems]
        return "\n".join(lines)


def wipe_guild_data(store: Store, guild_id: int) -> tuple[int, int]:
    """Alle Events (auch gelöschte), Anmeldungen, Logs, Reminder und Entwürfe dieses Servers.

    Eigene Bilder auf dem Volume gehen mit. Gibt (Events, Entwürfe) zurück.
    """
    images = set()
    for table in ("events", "drafts"):
        for row in store.conn.execute(f"SELECT data FROM {table} WHERE guild_id = ?", (guild_id,)):
            images.add(EventData.from_dict(json.loads(row["data"])).custom_image)
    with store.conn:
        drafts = store.conn.execute("DELETE FROM drafts WHERE guild_id = ?", (guild_id,)).rowcount
        # rsvps, event_log und event_reminders hängen per ON DELETE CASCADE dran
        events = store.conn.execute("DELETE FROM events WHERE guild_id = ?", (guild_id,)).rowcount
    for name in images - {""}:
        try:
            delete_custom_image(name)
        except OSError:
            logger.warning("Testserver: Bild %s konnte nicht gelöscht werden", name)
    return events, drafts


async def reset_server(guild: discord.Guild, store: Store) -> ResetResult:
    result = ResetResult()
    channel_id = bot_config.get_guild_config(guild.id).get("event_channel_id")
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        result.problems.append("Kein Event-Channel gefunden, nur die Datenbank wurde geleert.")
    else:
        result.threads = await _delete_threads(channel, result)
        try:
            while True:
                deleted = await channel.purge(limit=100)
                result.messages += len(deleted)
                if len(deleted) < 100:
                    break
        except discord.HTTPException as e:
            logger.warning("Testserver: Event-Channel leeren fehlgeschlagen: %s", e)
            result.problems.append("Nachrichten konnten nicht gelöscht werden (fehlt „Nachrichten verwalten“?).")
    result.events, result.drafts = wipe_guild_data(store, guild.id)
    return result


async def _delete_threads(channel, result: ResetResult) -> int:
    """Reminder-Threads am Event-Post bleiben sonst stehen, wenn die Nachricht weg ist."""
    threads = {t.id: t for t in getattr(channel, "threads", [])}
    try:
        async for t in channel.archived_threads(limit=None):
            threads[t.id] = t
    except discord.HTTPException:
        pass
    count = 0
    for t in threads.values():
        try:
            await t.delete()
            count += 1
        except discord.HTTPException:
            result.problems.append(f"Thread {t.name} konnte nicht gelöscht werden.")
    return count


# ── Delete All ───────────────────────────────────────────────────────────────


@dataclass
class DeleteResult:
    removed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    events: int = 0
    drafts: int = 0

    def summary(self) -> str:
        lines = [f"Abgebaut. Weg: {', '.join(self.removed) or 'nichts'}; {self.events} Runden, {self.drafts} Entwürfe "
                 "und die Bot-Einstellungen für diesen Server."]
        if self.kept:
            lines.append(f"Stehen geblieben ist {', '.join(self.kept)}, damit das Feedback nicht verloren geht.")
        if self.failed:
            lines.append(f"Hat nicht geklappt: {', '.join(self.failed)}")
        return "\n".join(lines)


async def delete_all(guild: discord.Guild, store: Store, bot=None) -> DeleteResult:
    result = DeleteResult()
    reg = registry.get(store, guild.id)
    _stop_overview(bot, guild.id)
    result.events, result.drafts = wipe_guild_data(store, guild.id)

    for key, name, _ in CHANNEL_PLAN:
        channel = guild.get_channel(reg["channels"].get(key) or 0)
        if channel is not None and key != KEEP_ON_DELETE:
            await _delete(channel, f"#{channel.name}", result)
    for cat_key, _, _ in CATEGORY_PLAN:
        category = guild.get_channel(reg["categories"].get(cat_key) or 0)
        if category is not None:
            await _delete(category, f"Kategorie {category.name}", result)
    for key, name in ROLE_PLAN:
        role = guild.get_role(reg["roles"].get(key) or 0)
        if role is not None:
            await _delete(role, f"Rolle {role.name}", result)

    # Bot-Einstellungen: SQLite (Rollen, Reminder, Registry) und config.json (Channels, Übersicht)
    with store.conn:
        store.conn.execute("DELETE FROM guild_settings WHERE guild_id = ?", (guild.id,))
    # Den Feedback-Channel merken, damit Setup ihn wieder einsortiert statt einen zweiten anzulegen
    kept = guild.get_channel(reg["channels"].get(KEEP_ON_DELETE) or 0)
    if kept is not None:
        registry.save(store, guild.id, {"categories": {}, "roles": {}, "channels": {KEEP_ON_DELETE: kept.id},
                                        "messages": {KEEP_ON_DELETE: reg["messages"].get(KEEP_ON_DELETE, [])}})
        result.kept.append(kept.mention)
    cfg = bot_config.load_config()
    if cfg.pop(str(guild.id), None) is not None:
        with open(bot_config.CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    return result


async def _delete(obj, label: str, result: DeleteResult):
    try:
        await obj.delete(reason=REASON)
        result.removed.append(label)
    except discord.HTTPException as e:
        logger.warning("Testserver: %s nicht gelöscht: %s", label, e)
        result.failed.append(label)


def _stop_overview(bot, guild_id: int):
    """Laufende automatische Übersicht stoppen, sonst postet sie in einen gelöschten Channel."""
    overview = bot.cogs.get("Overview") if bot is not None and hasattr(bot, "cogs") else None
    if overview is None:
        return
    overview.stop_listening(guild_id)


async def start_overview(bot, guild: discord.Guild, store: Store) -> None:
    """Automatische Übersicht (Listen-Modus) für die Setup-Channels einschalten, wie /automate_overview."""
    overview = bot.cogs.get("Overview") if bot is not None and hasattr(bot, "cogs") else None
    channels = registry.get(store, guild.id)["channels"]
    event_channel = guild.get_channel(channels.get("events") or 0)
    overview_channel = guild.get_channel(channels.get("overview") or 0)
    if overview is None or event_channel is None or overview_channel is None:
        return
    await overview.start_listening(guild.id, event_channel, overview_channel)
