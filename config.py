import json
import os

CONFIG_FILE = "config.json"


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