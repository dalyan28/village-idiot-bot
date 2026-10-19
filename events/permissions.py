"""Wer darf was: eine Funktion für Discord-Buttons, Commands und (später) die Website.

Grundsatz: Standard ist „verboten“. Jede Aktion wird ausdrücklich erlaubt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Aktionen
CREATE = "create"                          # /botc nutzen
CREATE_ACADEMY = "create_academy"          # Academy-Events anlegen bzw. Academy einschalten
EDIT = "edit"
DELETE = "delete"
MANAGE_PARTICIPANTS = "manage_participants"
TAKE_OVER = "take_over"                    # Event eines anderen Erstellers übernehmen
CONFIGURE = "configure"                    # Rollen, Academy-Zugang, Reminder-Defaults setzen

ACTIONS = (CREATE, CREATE_ACADEMY, EDIT, DELETE, MANAGE_PARTICIPANTS, TAKE_OVER, CONFIGURE)


@dataclass
class Actor:
    """Der handelnde Discord-User, so wie der Bot ihn in der Guild sieht."""

    user_id: int
    role_ids: frozenset[int] = frozenset()
    is_admin: bool = False  # „Server verwalten“


@dataclass
class AccessSettings:
    """Rollen-Konfiguration einer Guild (gespeichert in guild_settings)."""

    storyteller_role_id: int | None = None
    event_team_role_id: int | None = None
    academy_role_ids: list[int] = field(default_factory=list)
    academy_user_ids: list[int] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict | None) -> "AccessSettings":
        d = d or {}
        return cls(
            storyteller_role_id=d.get("storyteller_role_id"),
            event_team_role_id=d.get("event_team_role_id"),
            academy_role_ids=list(d.get("academy_role_ids", [])),
            academy_user_ids=list(d.get("academy_user_ids", [])),
        )

    def to_dict(self) -> dict:
        return {
            "storyteller_role_id": self.storyteller_role_id,
            "event_team_role_id": self.event_team_role_id,
            "academy_role_ids": list(self.academy_role_ids),
            "academy_user_ids": list(self.academy_user_ids),
        }


def is_event_team(actor: Actor, settings: AccessSettings) -> bool:
    """Event-Team-Rolle oder „Server verwalten“."""
    if actor.is_admin:
        return True
    return settings.event_team_role_id is not None and settings.event_team_role_id in actor.role_ids


def is_storyteller(actor: Actor, settings: AccessSettings) -> bool:
    return settings.storyteller_role_id is not None and settings.storyteller_role_id in actor.role_ids


def can(actor: Actor, action: str, settings: AccessSettings, creator_id: int | None = None) -> bool:
    """Darf `actor` die Aktion ausführen? `creator_id` ist der Ersteller des betroffenen Events.

    Der Co-ST hat bewusst keine Rechte am Event (Entscheidung Dalyan, 19.10.2026).
    """
    if action not in ACTIONS:
        raise ValueError(f"Unbekannte Aktion: {action}")

    team = is_event_team(actor, settings)

    if action == CONFIGURE or action == TAKE_OVER:
        return team
    if action == CREATE:
        # Ohne gesetzte Storyteller-Rolle dürfen nur Event-Team und Admins erstellen.
        return team or is_storyteller(actor, settings)
    if action == CREATE_ACADEMY:
        return (
            team
            or actor.user_id in settings.academy_user_ids
            or any(r in actor.role_ids for r in settings.academy_role_ids)
        )
    if action in (EDIT, DELETE, MANAGE_PARTICIPANTS):
        # Ein Ersteller behält die Rechte an seinen Events, auch ohne Storyteller-Rolle.
        return team or (creator_id is not None and actor.user_id == creator_id)
    return False
