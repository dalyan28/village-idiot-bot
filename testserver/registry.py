"""Was Setup angelegt hat (Kategorien, Channels, Rollen, Posts), je Server in `guild_settings`.

Über die IDs findet Setup seine Channels auch nach einer Umbenennung wieder, und Delete All
weiß, was weg muss.
"""

from __future__ import annotations

from events.store import Store

KEY = "testserver"


def get(store: Store, guild_id: int) -> dict:
    reg = store.get_guild_settings(guild_id).get(KEY) or {}
    return {"categories": dict(reg.get("categories") or {}), "channels": dict(reg.get("channels") or {}),
            "roles": dict(reg.get("roles") or {}), "messages": dict(reg.get("messages") or {}),
            "sample_event": reg.get("sample_event")}


def save(store: Store, guild_id: int, reg: dict):
    settings = store.get_guild_settings(guild_id)
    settings[KEY] = reg
    store.set_guild_settings(guild_id, settings)


def channel_id(store: Store, guild_id: int, key: str) -> int | None:
    return get(store, guild_id)["channels"].get(key)
