"""SQLite-Speicher für Events, Entwürfe, Anmeldungen, Änderungslog, Reminder und Server-Einstellungen.

Die Datei liegt auf dem Railway-Volume (RAILWAY_VOLUME_MOUNT_PATH), lokal unter data/.
Zeitstempel sind Unix-Sekunden (int). Die Felder eines Events liegen als JSON in `data`
(siehe events.schema.EventData), damit neue Felder keine Migration brauchen.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass

from events.schema import EventData

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(
    os.getenv("RAILWAY_VOLUME_MOUNT_PATH", os.path.join(PROJECT_ROOT, "data")), "events.db"
)

RSVP_ACCEPTED = "accepted"
RSVP_TENTATIVE = "tentative"   # bei Academy als „Auffüller“ angezeigt
RSVP_DECLINED = "declined"
RSVP_STATUSES = (RSVP_ACCEPTED, RSVP_TENTATIVE, RSVP_DECLINED)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id    INTEGER PRIMARY KEY,
    data        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_settings (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    data        TEXT NOT NULL,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    channel_id    INTEGER,
    message_id    INTEGER UNIQUE,
    creator_id    INTEGER NOT NULL,
    creator_name  TEXT NOT NULL,
    data          TEXT NOT NULL,
    start_ts      INTEGER,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    deleted_at    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_guild_start ON events (guild_id, start_ts);
CREATE TABLE IF NOT EXISTS drafts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    event_id    INTEGER REFERENCES events (id) ON DELETE CASCADE,
    step        TEXT NOT NULL,
    data        TEXT NOT NULL,
    ui          TEXT NOT NULL DEFAULT '{}',
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drafts_user ON drafts (guild_id, user_id);
CREATE TABLE IF NOT EXISTS rsvps (
    event_id      INTEGER NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL,
    display_name  TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_at    INTEGER NOT NULL,
    PRIMARY KEY (event_id, user_id)
);
CREATE TABLE IF NOT EXISTS event_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    INTEGER NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    actor_id    INTEGER NOT NULL,
    action      TEXT NOT NULL,
    changes     TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS event_reminders (
    event_id      INTEGER NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    reminder_key  TEXT NOT NULL,
    sent_at       INTEGER NOT NULL,
    PRIMARY KEY (event_id, reminder_key)
);
"""


@dataclass
class EventRecord:
    id: int
    guild_id: int
    channel_id: int | None
    message_id: int | None
    creator_id: int
    creator_name: str
    data: EventData
    created_at: int
    updated_at: int
    deleted_at: int | None


@dataclass
class Draft:
    id: int
    guild_id: int
    user_id: int
    event_id: int | None  # gesetzt, wenn der Entwurf ein bestehendes Event bearbeitet
    step: str
    data: EventData
    created_at: int
    updated_at: int
    ui: dict = None  # Zwischenstand der Oberfläche (z. B. Suchergebnisse), kein Event-Feld


@dataclass
class Rsvp:
    user_id: int
    display_name: str
    status: str
    created_at: int


def _start_ts(data: EventData) -> int | None:
    return int(data.start.timestamp()) if data.start else None


class Store:
    def __init__(self, path: str = DEFAULT_DB_PATH):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        with self.conn:
            self.conn.executescript(_SCHEMA)
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self):
        self.conn.close()

    # ── Server-Einstellungen ─────────────────────────────────────────────

    def get_guild_settings(self, guild_id: int) -> dict:
        row = self.conn.execute("SELECT data FROM guild_settings WHERE guild_id = ?", (guild_id,)).fetchone()
        return json.loads(row["data"]) if row else {}

    def set_guild_settings(self, guild_id: int, data: dict):
        with self.conn:
            self.conn.execute(
                "INSERT INTO guild_settings (guild_id, data) VALUES (?, ?) "
                "ON CONFLICT (guild_id) DO UPDATE SET data = excluded.data",
                (guild_id, json.dumps(data)),
            )

    # ── Einstellungen pro Person (events/user_settings.py) ──────────────

    def get_user_settings(self, guild_id: int, user_id: int) -> dict:
        row = self.conn.execute("SELECT data FROM user_settings WHERE guild_id = ? AND user_id = ?",
                                (guild_id, user_id)).fetchone()
        if not row:
            return {}
        try:
            data = json.loads(row["data"])
        except ValueError:
            return {}  # kaputter Eintrag: eingebaute Standards statt Absturz
        return data if isinstance(data, dict) else {}

    def set_user_settings(self, guild_id: int, user_id: int, data: dict, now: int):
        with self.conn:
            self.conn.execute(
                "INSERT INTO user_settings (guild_id, user_id, data, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (guild_id, user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                (guild_id, user_id, json.dumps(data), now),
            )

    # ── Events ───────────────────────────────────────────────────────────

    @staticmethod
    def _event(row) -> EventRecord:
        return EventRecord(
            id=row["id"], guild_id=row["guild_id"], channel_id=row["channel_id"],
            message_id=row["message_id"], creator_id=row["creator_id"],
            creator_name=row["creator_name"], data=EventData.from_dict(json.loads(row["data"])),
            created_at=row["created_at"], updated_at=row["updated_at"], deleted_at=row["deleted_at"],
        )

    def insert_event(self, guild_id: int, creator_id: int, creator_name: str,
                     data: EventData, now: int, channel_id: int | None = None) -> EventRecord:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO events (guild_id, channel_id, creator_id, creator_name, data, start_ts, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (guild_id, channel_id, creator_id, creator_name, json.dumps(data.to_dict()),
                 _start_ts(data), now, now),
            )
        return self.get_event(cur.lastrowid, include_deleted=True)

    def get_event(self, event_id: int, include_deleted: bool = False) -> EventRecord | None:
        row = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None or (row["deleted_at"] is not None and not include_deleted):
            return None
        return self._event(row)

    def get_event_by_message(self, message_id: int) -> EventRecord | None:
        row = self.conn.execute(
            "SELECT * FROM events WHERE message_id = ? AND deleted_at IS NULL", (message_id,)
        ).fetchone()
        return self._event(row) if row else None

    def set_event_message(self, event_id: int, channel_id: int, message_id: int):
        with self.conn:
            self.conn.execute(
                "UPDATE events SET channel_id = ?, message_id = ? WHERE id = ?",
                (channel_id, message_id, event_id),
            )

    def update_event_data(self, event_id: int, data: EventData, now: int):
        with self.conn:
            self.conn.execute(
                "UPDATE events SET data = ?, start_ts = ?, updated_at = ? WHERE id = ?",
                (json.dumps(data.to_dict()), _start_ts(data), now, event_id),
            )

    def set_event_creator(self, event_id: int, creator_id: int, creator_name: str, now: int):
        with self.conn:
            self.conn.execute(
                "UPDATE events SET creator_id = ?, creator_name = ?, updated_at = ? WHERE id = ?",
                (creator_id, creator_name, now, event_id),
            )

    def soft_delete_event(self, event_id: int, now: int):
        with self.conn:
            self.conn.execute("UPDATE events SET deleted_at = ? WHERE id = ?", (now, event_id))

    def list_events(self, guild_id: int | None = None, start_from: int | None = None,
                    start_until: int | None = None) -> list[EventRecord]:
        """Nicht gelöschte Events, nach Termin sortiert. Optional gefiltert."""
        sql = "SELECT * FROM events WHERE deleted_at IS NULL"
        args: list = []
        if guild_id is not None:
            sql += " AND guild_id = ?"
            args.append(guild_id)
        if start_from is not None:
            sql += " AND start_ts >= ?"
            args.append(start_from)
        if start_until is not None:
            sql += " AND start_ts < ?"
            args.append(start_until)
        sql += " ORDER BY start_ts"
        return [self._event(r) for r in self.conn.execute(sql, args)]

    def purge_events(self, cutoff: int) -> int:
        """Entfernt endgültig: gelöschte Events vor `cutoff` und Events, deren Termin davor lag."""
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM events WHERE (deleted_at IS NOT NULL AND deleted_at < ?) "
                "OR (start_ts IS NOT NULL AND start_ts < ?)",
                (cutoff, cutoff),
            )
        return cur.rowcount

    # ── Entwürfe ─────────────────────────────────────────────────────────

    @staticmethod
    def _draft(row) -> Draft:
        return Draft(
            id=row["id"], guild_id=row["guild_id"], user_id=row["user_id"], event_id=row["event_id"],
            step=row["step"], data=EventData.from_dict(json.loads(row["data"])),
            created_at=row["created_at"], updated_at=row["updated_at"], ui=json.loads(row["ui"]),
        )

    def create_draft(self, guild_id: int, user_id: int, data: EventData, step: str, now: int,
                     event_id: int | None = None) -> Draft:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO drafts (guild_id, user_id, event_id, step, data, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (guild_id, user_id, event_id, step, json.dumps(data.to_dict()), now, now),
            )
        return self.get_draft(cur.lastrowid)

    def get_draft(self, draft_id: int) -> Draft | None:
        row = self.conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        return self._draft(row) if row else None

    def list_drafts(self, user_id: int, guild_id: int | None = None) -> list[Draft]:
        """Entwürfe eines Users, neuester zuerst."""
        sql = "SELECT * FROM drafts WHERE user_id = ?"
        args: list = [user_id]
        if guild_id is not None:
            sql += " AND guild_id = ?"
            args.append(guild_id)
        sql += " ORDER BY updated_at DESC, id DESC"
        return [self._draft(r) for r in self.conn.execute(sql, args)]

    def update_draft(self, draft_id: int, data: EventData, step: str, now: int):
        with self.conn:
            self.conn.execute(
                "UPDATE drafts SET data = ?, step = ?, updated_at = ? WHERE id = ?",
                (json.dumps(data.to_dict()), step, now, draft_id),
            )

    def set_draft_ui(self, draft_id: int, ui: dict):
        with self.conn:
            self.conn.execute("UPDATE drafts SET ui = ? WHERE id = ?", (json.dumps(ui), draft_id))

    def delete_draft(self, draft_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))

    def stale_drafts(self, cutoff: int) -> list[Draft]:
        """Entwürfe, die seit `cutoff` nicht mehr angefasst wurden (vor dem Aufräumen)."""
        return [self._draft(r) for r in self.conn.execute("SELECT * FROM drafts WHERE updated_at < ?", (cutoff,))]

    def purge_drafts(self, cutoff: int) -> int:
        """Entfernt Entwürfe, die seit `cutoff` nicht mehr angefasst wurden."""
        with self.conn:
            cur = self.conn.execute("DELETE FROM drafts WHERE updated_at < ?", (cutoff,))
        return cur.rowcount

    # ── Anmeldungen ──────────────────────────────────────────────────────

    def get_rsvp(self, event_id: int, user_id: int) -> Rsvp | None:
        row = self.conn.execute(
            "SELECT * FROM rsvps WHERE event_id = ? AND user_id = ?", (event_id, user_id)
        ).fetchone()
        return Rsvp(row["user_id"], row["display_name"], row["status"], row["created_at"]) if row else None

    def set_rsvp(self, event_id: int, user_id: int, display_name: str, status: str, now: int):
        """Setzt den Status. Ein Statuswechsel stellt den User in der Reihenfolge hinten an."""
        if status not in RSVP_STATUSES:
            raise ValueError(f"Unbekannter RSVP-Status: {status}")
        with self.conn:
            self.conn.execute(
                "INSERT INTO rsvps (event_id, user_id, display_name, status, created_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (event_id, user_id) DO UPDATE SET display_name = excluded.display_name, "
                "status = excluded.status, created_at = excluded.created_at",
                (event_id, user_id, display_name, status, now),
            )

    def remove_rsvp(self, event_id: int, user_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM rsvps WHERE event_id = ? AND user_id = ?", (event_id, user_id))

    def list_rsvps(self, event_id: int) -> list[Rsvp]:
        """Alle Anmeldungen in Reihenfolge der Anmeldung (für die Warteliste entscheidend)."""
        rows = self.conn.execute(
            "SELECT * FROM rsvps WHERE event_id = ? ORDER BY created_at, rowid", (event_id,)
        )
        return [Rsvp(r["user_id"], r["display_name"], r["status"], r["created_at"]) for r in rows]

    # ── Änderungslog ─────────────────────────────────────────────────────

    def add_log(self, event_id: int, actor_id: int, action: str, changes: dict, now: int):
        with self.conn:
            self.conn.execute(
                "INSERT INTO event_log (event_id, actor_id, action, changes, created_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, actor_id, action, json.dumps(changes, default=str), now),
            )

    def list_log(self, event_id: int) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM event_log WHERE event_id = ? ORDER BY id", (event_id,))
        return [
            {"actor_id": r["actor_id"], "action": r["action"],
             "changes": json.loads(r["changes"]), "created_at": r["created_at"]}
            for r in rows
        ]

    # ── Reminder ─────────────────────────────────────────────────────────

    def mark_reminder_sent(self, event_id: int, reminder_key: str, now: int):
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO event_reminders (event_id, reminder_key, sent_at) VALUES (?, ?, ?)",
                (event_id, reminder_key, now),
            )

    def sent_reminders(self, event_id: int) -> set[str]:
        rows = self.conn.execute("SELECT reminder_key FROM event_reminders WHERE event_id = ?", (event_id,))
        return {r["reminder_key"] for r in rows}

    def reset_reminders(self, event_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM event_reminders WHERE event_id = ?", (event_id,))
