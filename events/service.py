"""Abläufe rund um Entwürfe, Events und Anmeldungen. Von Wizard und Website gemeinsam genutzt.

Discord-Nachrichten posten oder ändern gehört nicht hierher, sondern in die Oberfläche;
der Service liefert nur die Daten und hält die Regeln ein.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime

from events import permissions
from events.permissions import AccessSettings, Actor
from events.schema import (
    EventData,
    Person,
    missing_for_publish,
    normalize,
    validate,
)
from events.store import (
    RSVP_ACCEPTED,
    RSVP_DECLINED,
    RSVP_TENTATIVE,
    Draft,
    EventRecord,
    Store,
)

DRAFT_TTL_SECONDS = 24 * 3600
EVENT_RETENTION_SECONDS = 30 * 24 * 3600

STEP_SCRIPT = "script"
STEP_PREVIEW = "preview"

GUILD_ACCESS_KEY = "access"
ACADEMY_TEMPLATE_KEY = "academy_template"  # eigener Academy-Text des Servers (/academy_text)
START_LINKS_KEY = "start_links"  # Links in der /botc-Startnachricht je Server (/set_start_links)


class ServiceError(Exception):
    """Fachlicher Fehler mit deutscher Meldung für den User."""


class PermissionDenied(ServiceError):
    pass


# ── Server-Einstellungen ─────────────────────────────────────────────────────


def get_start_links(store: Store, guild_id: int) -> tuple[str, str]:
    """(Hinweise, Regeln) für die Startnachricht: Server-Einstellung, sonst der eingebaute Standard."""
    from events.templates import RULES_URL, STORYTELLER_GUIDE_URL

    stored = store.get_guild_settings(guild_id).get(START_LINKS_KEY) or {}
    return stored.get("guide") or STORYTELLER_GUIDE_URL, stored.get("rules") or RULES_URL


def set_start_links(store: Store, guild_id: int, guide: str | None = None, rules: str | None = None,
                    reset: bool = False):
    """Setzt einen oder beide Links; `reset` stellt den eingebauten Standard wieder her."""
    settings = store.get_guild_settings(guild_id)
    stored = {} if reset else dict(settings.get(START_LINKS_KEY) or {})
    for key, url in (("guide", guide), ("rules", rules)):
        if url is None:
            continue
        url = url.strip()
        if not url.startswith("https://"):
            raise ServiceError("Bitte gib einen vollständigen Link an, der mit https:// beginnt.")
        stored[key] = url
    settings[START_LINKS_KEY] = stored
    store.set_guild_settings(guild_id, settings)


def _with_academy(data: EventData) -> bool:
    return data.is_academy and not data.is_other_event


def description_limit(store: Store, guild_id: int, data: EventData) -> int:
    """Höchstlänge der eigenen Beschreibung: 2000, bei Academy der Rest von 3000 nach dem Academy-Text des Servers."""
    from events.schema import DESCRIPTION_MAX_LENGTH, DESCRIPTION_TOTAL_MAX_LENGTH
    from events.templates import academy_description

    if not _with_academy(data):
        return DESCRIPTION_MAX_LENGTH
    academy = academy_description(data.rating, get_academy_template(store, guild_id))
    return max(0, min(DESCRIPTION_MAX_LENGTH, DESCRIPTION_TOTAL_MAX_LENGTH - len(academy)))


def description_overflow(store: Store, guild_id: int, data: EventData) -> int:
    """Zeichen, um die die Beschreibung zu lang ist (0 = passt): über der Höchstlänge oder, als Sicherung, zu lang
    für Discords Grenze je Event-Post."""
    from logic.event_builder import description_overflow as embed_overflow  # zirkulären Import vermeiden

    template = get_academy_template(store, guild_id) if data.is_academy else None
    return max(len(data.description.strip()) - description_limit(store, guild_id, data),
               embed_overflow(data, template), 0)


def description_limit_text(store: Store, guild_id: int, data: EventData) -> str:
    """„Bis zu N Zeichen“, bei Academy mit Hinweis auf den Academy-Text."""
    limit = description_limit(store, guild_id, data)
    return f"Bis zu {limit} Zeichen (der Rest von 3000 nach dem Academy-Text)" if _with_academy(data) \
        else f"Bis zu {limit} Zeichen"


def description_overflow_text(store: Store, guild_id: int, data: EventData, over: int) -> str:
    """Hinweis für zu lange Beschreibungen."""
    if _with_academy(data):
        limit = description_limit(store, guild_id, data)
        return (f"Die Beschreibung ist zu lang. Zusammen mit dem Academy-Text sind höchstens 3000 Zeichen möglich, "
                f"für deine Beschreibung bleiben also {limit}. Bitte kürze sie um {over} Zeichen.")
    return f"Die Beschreibung ist zu lang für den Event-Post. Bitte kürze sie um {over} Zeichen."


def get_academy_template(store: Store, guild_id: int) -> str:
    """Academy-Text des Servers, sonst der eingebaute."""
    from events.templates import ACADEMY_TEMPLATE_DEFAULT

    stored = store.get_guild_settings(guild_id).get(ACADEMY_TEMPLATE_KEY)
    return stored if isinstance(stored, str) and stored.strip() else ACADEMY_TEMPLATE_DEFAULT


def set_academy_template(store: Store, guild_id: int, text: str | None):
    """Eigenen Academy-Text speichern; None oder leer = eingebauter Text."""
    settings = store.get_guild_settings(guild_id)
    if text and text.strip():
        settings[ACADEMY_TEMPLATE_KEY] = text.strip()
    else:
        settings.pop(ACADEMY_TEMPLATE_KEY, None)
    store.set_guild_settings(guild_id, settings)


def get_access(store: Store, guild_id: int) -> AccessSettings:
    return AccessSettings.from_dict(store.get_guild_settings(guild_id).get(GUILD_ACCESS_KEY))


def set_access(store: Store, guild_id: int, access: AccessSettings):
    settings = store.get_guild_settings(guild_id)
    settings[GUILD_ACCESS_KEY] = access.to_dict()
    store.set_guild_settings(guild_id, settings)


def _require(actor: Actor, action: str, access: AccessSettings, creator_id: int | None = None):
    if not permissions.can(actor, action, access, creator_id):
        raise PermissionDenied("Dafür fehlt dir die Berechtigung.")


# ── Entwürfe ─────────────────────────────────────────────────────────────────


def start_draft(store: Store, guild_id: int, actor: Actor, user_name: str, data: EventData,
                now: datetime) -> Draft:
    """Neuer Entwurf aus den Modal-Daten. Storyteller ist per Default der User selbst.

    Ein älterer Entwurf für ein neues Event wird dabei ersetzt.
    """
    access = get_access(store, guild_id)
    _require(actor, permissions.CREATE, access)
    if data.is_academy:
        _require(actor, permissions.CREATE_ACADEMY, access)
    data = normalize(copy.deepcopy(data))
    # Eigene Standardwerte der Person (Dalyan, 26.10.2026)
    from events import user_settings
    user_settings.get(store, guild_id, actor.user_id).apply(data)
    if data.storyteller is None:
        data.storyteller = Person(name=user_name, user_id=actor.user_id)
    errors = validate(data, now)
    if errors:
        raise ServiceError(" ".join(errors))
    # Pro User und Server gibt es höchstens einen Entwurf für ein neues Event
    for old in store.list_drafts(actor.user_id, guild_id):
        if old.event_id is None:
            store.delete_draft(old.id)
    draft = store.create_draft(guild_id, actor.user_id, data, STEP_SCRIPT, int(now.timestamp()))
    # Startwert für die Teensyville-Regel merken (zurück auf diesen Wert, wenn kein Teensyville mehr)
    store.set_draft_ui(draft.id, {"base_players": data.max_players})
    return store.get_draft(draft.id)


def open_draft(store: Store, guild_id: int, user_id: int, now: datetime) -> Draft | None:
    """Der jüngste noch gültige Entwurf für ein neues Event (nicht für eine Bearbeitung)."""
    cutoff = int(now.timestamp()) - DRAFT_TTL_SECONDS
    for draft in store.list_drafts(user_id, guild_id):
        if draft.event_id is None and draft.updated_at >= cutoff:
            return draft
    return None


def update_draft(store: Store, draft: Draft, actor: Actor, data: EventData, step: str,
                 now: datetime) -> Draft:
    """Speichert einen geänderten Entwurf. Academy einschalten braucht die Berechtigung."""
    # Immer gegen den gespeicherten Stand vergleichen: `data` kann dasselbe Objekt wie
    # `draft.data` sein, wenn der Aufrufer den geladenen Entwurf direkt verändert hat.
    stored = store.get_draft(draft.id)
    if stored is None:
        raise ServiceError("Den Entwurf gibt es nicht mehr.")
    if stored.user_id != actor.user_id:
        raise PermissionDenied("Das ist nicht dein Entwurf.")
    if data.is_academy and not stored.data.is_academy:
        _require(actor, permissions.CREATE_ACADEMY, get_access(store, stored.guild_id))
    data = normalize(copy.deepcopy(data))
    check_start = stored.event_id is None or data.start != stored.data.start
    errors = validate(data, now, check_start=check_start)
    if errors:
        raise ServiceError(" ".join(errors))
    store.update_draft(draft.id, data, step, int(now.timestamp()))
    return store.get_draft(draft.id)


def draft_for_edit(store: Store, event: EventRecord, actor: Actor, now: datetime) -> Draft:
    """Entwurf zum Bearbeiten eines bestehenden Events. Ein alter Bearbeitungs-Entwurf wird ersetzt."""
    _require(actor, permissions.EDIT, get_access(store, event.guild_id), event.creator_id)
    for old in store.list_drafts(actor.user_id, event.guild_id):
        if old.event_id == event.id:
            store.delete_draft(old.id)
    return store.create_draft(event.guild_id, actor.user_id, copy.deepcopy(event.data), STEP_PREVIEW,
                              int(now.timestamp()), event_id=event.id)


def discard_draft(store: Store, draft: Draft, actor: Actor):
    if draft.user_id != actor.user_id:
        raise PermissionDenied("Das ist nicht dein Entwurf.")
    store.delete_draft(draft.id)


# ── Veröffentlichen und Bearbeiten ───────────────────────────────────────────


def changed_fields(old: EventData, new: EventData) -> dict:
    """{feld: [alt, neu]} für alle geänderten Felder (für das Änderungslog)."""
    a, b = old.to_dict(), new.to_dict()
    return {k: [a[k], b[k]] for k in b if a.get(k) != b[k]}


@dataclass
class PublishResult:
    event: EventRecord
    created: bool                       # neu angelegt (True) oder bestehendes geändert (False)
    start_changed: bool = False
    changes: dict = field(default_factory=dict)


def publish_draft(store: Store, draft: Draft, actor: Actor, actor_name: str, now: datetime) -> PublishResult:
    """Macht aus dem Entwurf ein Event bzw. übernimmt ihn in das bestehende Event.

    Die Oberfläche postet bzw. ändert danach die Discord-Nachricht und trägt bei neuen
    Events die Message-ID mit `store.set_event_message` nach.
    """
    if draft.user_id != actor.user_id:
        raise PermissionDenied("Das ist nicht dein Entwurf.")
    data = normalize(copy.deepcopy(draft.data))
    missing = missing_for_publish(data)
    if missing:
        raise ServiceError("Es fehlt noch: " + ", ".join(missing) + ".")
    over = description_overflow(store, draft.guild_id, data)
    if over:
        raise ServiceError(description_overflow_text(store, draft.guild_id, data, over))

    ts = int(now.timestamp())
    access = get_access(store, draft.guild_id)
    existing = store.get_event(draft.event_id) if draft.event_id is not None else None
    if draft.event_id is not None and existing is None:
        raise ServiceError("Das Event gibt es nicht mehr.")

    check_start = existing is None or data.start != existing.data.start
    errors = validate(data, now, check_start=check_start)
    if errors:
        raise ServiceError(" ".join(errors))

    if existing is None:
        _require(actor, permissions.CREATE, access)
        if data.is_academy:
            _require(actor, permissions.CREATE_ACADEMY, access)
        event = store.insert_event(draft.guild_id, actor.user_id, actor_name, data, ts)
        store.add_log(event.id, actor.user_id, "create", {}, ts)
        store.delete_draft(draft.id)
        return PublishResult(event=event, created=True)

    event = existing
    _require(actor, permissions.EDIT, access, event.creator_id)
    if data.is_academy and not event.data.is_academy:
        _require(actor, permissions.CREATE_ACADEMY, access)

    changes = changed_fields(event.data, data)
    start_changed = "start" in changes
    store.update_event_data(event.id, data, ts)
    if start_changed:
        store.reset_reminders(event.id)
    if changes:
        store.add_log(event.id, actor.user_id, "edit", changes, ts)
    store.delete_draft(draft.id)
    return PublishResult(event=store.get_event(event.id), created=False,
                         start_changed=start_changed, changes=changes)


def delete_event(store: Store, event: EventRecord, actor: Actor, now: datetime):
    _require(actor, permissions.DELETE, get_access(store, event.guild_id), event.creator_id)
    ts = int(now.timestamp())
    store.soft_delete_event(event.id, ts)
    store.add_log(event.id, actor.user_id, "delete", {}, ts)


def cleanup(store: Store, now: datetime) -> tuple[int, int]:
    """Alte Entwürfe und Events endgültig entfernen. Gibt (Entwürfe, Events) zurück."""
    ts = int(now.timestamp())
    return store.purge_drafts(ts - DRAFT_TTL_SECONDS), store.purge_events(ts - EVENT_RETENTION_SECONDS)


# ── Anmeldungen ──────────────────────────────────────────────────────────────


@dataclass
class RsvpLists:
    """Anmeldungen, wie sie angezeigt werden. Die Warteliste ergibt sich aus der Reihenfolge."""

    players: list[Person]
    waitlist: list[Person]
    tentative: list[Person]
    declined: list[Person]

    @property
    def accepted_count(self) -> int:
        return len(self.players) + len(self.waitlist)


def rsvp_lists(store: Store, event: EventRecord) -> RsvpLists:
    accepted, tentative, declined = [], [], []
    for r in store.list_rsvps(event.id):
        person = Person(name=r.display_name, user_id=r.user_id)
        {RSVP_ACCEPTED: accepted, RSVP_TENTATIVE: tentative, RSVP_DECLINED: declined}[r.status].append(person)
    limit = event.data.max_players
    return RsvpLists(players=accepted[:limit], waitlist=accepted[limit:],
                     tentative=tentative, declined=declined)


def toggle_rsvp(store: Store, event: EventRecord, user_id: int, display_name: str, status: str,
                now: datetime) -> str | None:
    """Klick auf einen RSVP-Button: gleicher Status nochmal = abmelden. Gibt den neuen Status zurück."""
    current = store.get_rsvp(event.id, user_id)
    if current is not None and current.status == status:
        store.remove_rsvp(event.id, user_id)
        return None
    store.set_rsvp(event.id, user_id, display_name, status, int(now.timestamp()))
    return status
