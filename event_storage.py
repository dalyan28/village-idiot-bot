import json
import logging
import os
import time

logger = logging.getLogger(__name__)

EVENTS_FILE = os.path.join(os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "."), "events.json")
CLEANUP_AFTER_DAYS = 30


def load_events() -> dict:
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_events(events: dict):
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)


def get_event(message_id: int) -> dict | None:
    events = load_events()
    event = events.get(str(message_id))
    if event and event.get("deleted_at") is not None:
        return None
    logger.debug("Event geladen: msg_id=%s, gefunden=%s", message_id, event is not None)
    return event


def save_event(message_id: int, event_data: dict):
    events = load_events()
    events[str(message_id)] = event_data
    _save_events(events)
    logger.debug("Event gespeichert: msg_id=%s", message_id)


def delete_event(message_id: int):
    events = load_events()
    key = str(message_id)
    if key in events:
        events[key]["deleted_at"] = int(time.time())
        _save_events(events)
        logger.info("Event soft-deleted: msg_id=%s", message_id)


def cleanup_old_events():
    events = load_events()
    now = int(time.time())
    cutoff = now - (CLEANUP_AFTER_DAYS * 86400)
    to_remove = []

    for msg_id, event in events.items():
        deleted_at = event.get("deleted_at")
        if deleted_at is not None and deleted_at < cutoff:
            to_remove.append(msg_id)
            continue

        event_ts = event.get("timestamp", 0)
        if event_ts and event_ts < cutoff:
            to_remove.append(msg_id)

    if to_remove:
        for msg_id in to_remove:
            del events[msg_id]
        _save_events(events)
        logger.info("Event-Cleanup: %d alte Events entfernt", len(to_remove))
    else:
        logger.debug("Event-Cleanup: keine alten Events gefunden")
