import json
import os

CONFIG_FILE = os.path.join(os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "."), "config.json")


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def get_guild_config(guild_id: int) -> dict:
    cfg = load_config()
    return cfg.get(str(guild_id), {})


def save_guild_config(guild_id: int, guild_cfg: dict):
    cfg = load_config()
    cfg[str(guild_id)] = guild_cfg
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


VALID_GUILD_KEYS = {
    "event_channel_id",
    "overview_channel_id",
    "last_overview_message_ids",
    "auto_interval_hours",
    "on_new_event",
    "auto_active",
    "smart_dynamic",
    "smart_schedule",
}


def cleanup_config():
    """Entfernt veraltete Keys aus allen Guild-Configs und speichert die bereinigte Config."""
    cfg = load_config()
    changed = False

    for guild_id, guild_cfg in cfg.items():
        if not isinstance(guild_cfg, dict):
            continue
        stale_keys = [k for k in guild_cfg if k not in VALID_GUILD_KEYS]
        if stale_keys:
            for key in stale_keys:
                del guild_cfg[key]
            print(f"Config cleanup Guild {guild_id}: entfernt {stale_keys}")
            changed = True

    if changed:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)