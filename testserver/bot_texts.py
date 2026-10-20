"""Inhalt von #texte: die längeren Texte, die der Bot an die Leute schickt, zum Gegenlesen.

Keine Buttons, nur Fließtext. Was der Bot aus Funktionen baut (Academy-Text, Erinnerungen,
Rechte-Hinweis), wird hier direkt erzeugt. Der Rest ist eine Kopie vom Stand des Codes;
tests/test_testserver.py prüft, dass jede Kopie dort noch so steht (Datei + die ersten 25 Zeichen).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from events.permissions import AccessSettings
from events.schema import BERLIN_TZ, Person
from testserver.texts import FROM_DALYAN

INTRO = FROM_DALYAN + """
**Hier sind die relevanten Texte**
Das ist, was der Bot euch an Text schickt, wenn mal mehr kommt als ein Button. Ich bin nicht besonders gut im Texten und es macht mir auch keinen Spaß. Ich würde mich also freuen, wenn ihr hier Feedback gebt. Schreibt einfach drunter, was komisch klingt oder wie ihr es sagen würdet."""

# (Gruppe, Anlass, Text, Datei im Code)
COPIED = [
    ("Runde anlegen", "/botc in einem Channel",
     "Es geht in deinen DMs weiter.", "commands/botc.py"),
    ("Runde anlegen", "DMs sind zu",
     "Ich kann dir keine DM schicken. Erlaube DMs von Servermitgliedern (Servereinstellungen → Privatsphäre) "
     "und starte `/botc` dann erneut.", "commands/botc.py"),
    ("Im Wizard", "Erste Karte nach dem Termin",
     "Such dein Skript auf **botcscripts.com** oder wähl direkt ein Basis-Skript. Ein eigenes Skript kannst du als "
     "JSON anhängen.\n-# Danach siehst du die Zusammenfassung. Dort kannst du alles anpassen und die Runde "
     "veröffentlichen.", "discord_ui/layout_v2.py"),
    ("Im Wizard", "Skript-Karte",
     "Such dein Skript auf **botcscripts.com**, wähl ein Basis-Skript oder die freie Skriptwahl, oder häng ein "
     "eigenes JSON an.", "discord_ui/layout_v2.py"),
    ("Im Wizard", "botcscripts.com antwortet nicht",
     "botcscripts.com antwortet gerade nicht (zu langsam oder nicht erreichbar). Du kannst ein Basis-Skript oder "
     "die freie Skriptwahl nehmen, dein Skript als JSON hochladen oder es später erneut versuchen.",
     "discord_ui/wizard.py"),
    ("Im Wizard", "ScriptRater antwortet nicht",
     "Der ScriptRater ist gerade nicht erreichbar. Bitte stell die Schwierigkeit selbst ein.",
     "discord_ui/wizard.py"),
    ("Im Wizard", "Zusammenfassung, wenn noch was fehlt",
     "🔴 **Bevor du veröffentlichen kannst, fehlt noch:** Beschreibung", "discord_ui/layout_v2.py"),
    ("Im Wizard", "Zusammenfassung, wenn alles da ist",
     "Alle Pflichtangaben sind vollständig. Wenn alles passt: **Veröffentlichen**.", "discord_ui/layout_v2.py"),
    ("Im Wizard", "Veröffentlicht", "Dein Event ist veröffentlicht.", "discord_ui/wizard.py"),
    ("Im Wizard", "Abgebrochen",
     "Event-Erstellung abgebrochen. Mit `/botc` kannst du jederzeit neu starten.", "discord_ui/wizard.py"),
    ("Im Wizard", "Bearbeitung verworfen",
     "Bearbeitung verworfen, das Event bleibt unverändert.", "discord_ui/wizard.py"),
    ("Am Post", "Bearbeiten",
     "Du kannst das Event in deinen DMs bearbeiten.", "discord_ui/event_post.py"),
    ("Am Post", "Bearbeiten ohne Recht",
     "Bearbeiten dürfen nur der Ersteller und das Event-Team.", "discord_ui/event_post.py"),
    ("Am Post", "Löschen",
     "Soll dieses Event wirklich gelöscht werden?", "discord_ui/event_post.py"),
]


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.split("\n"))


def _entry(label: str, text: str) -> str:
    return f"-# {label}\n{_quote(text)}"


def generated() -> list[tuple[str, str, str]]:
    """Texte, die der Bot zur Laufzeit baut, mit Beispielwerten."""
    import discord

    from discord_ui.botc_start import start_layout, start_problem
    from events import reminders, service
    from events.store import Store
    from events.templates import academy_description

    guild = SimpleNamespace(id=1, name="Widow", get_role=lambda rid: SimpleNamespace(name="Storyteller"),
                            get_channel=lambda cid: None)
    member = SimpleNamespace(id=2, roles=[], guild_permissions=SimpleNamespace(manage_guild=False))
    store = Store(":memory:")
    no_role = start_problem(store, guild, member)
    service.set_access(store, guild.id, AccessSettings(storyteller_role_id=1))
    with_role = start_problem(store, guild, member)
    store.close()
    start = "\n".join(i.content for i in start_layout(guild, member.id).walk_children()
                      if isinstance(i, discord.ui.TextDisplay))

    when = datetime(2026, 10, 24, 20, 0, tzinfo=BERLIN_TZ)
    people = [Person("Anna", 1), Person("Rosanna", 2)]
    names = reminders.copy_of(reminders.DEFAULTS[reminders.FIRST])
    names.mode = reminders.MODE_NAMES
    from events.schema import EventData, ScriptRef

    event = EventData(start=when, storyteller=Person("Dalyan", 3), script=ScriptRef(kind="base", name="Boozling"))
    return [
        ("Runde anlegen", "Startnachricht in den DMs", start),
        ("Runde anlegen", "Ohne Storyteller-Rolle", with_role),
        ("Runde anlegen", "Noch keine Storyteller-Rolle eingestellt", no_role),
        ("Erinnerungen", "Erinnerung im Thread (hier ohne Ping)", reminders.message_text(names, when, people)),
        ("Erinnerungen", f"Dazu hängt {reminders.ATTENDANCE_FILENAME} (neben dem Skript-JSON)",
         f"```\n{reminders.attendance_txt(event, people)}```"),
        ("Academy", "Fester Academy-Text unter der Beschreibung (hier für 💚)", academy_description("green")),
    ]


GROUPS = ["Runde anlegen", "Im Wizard", "Am Post", "Erinnerungen", "Academy"]


def posts() -> list[str]:
    """Ein Post je Gruppe, davor die Einleitung."""
    entries = [(g, label, text) for g, label, text, _ in COPIED] + generated()
    result = [INTRO]
    for group in GROUPS:
        body = "\n\n".join(_entry(label, text) for g, label, text in entries if g == group)
        if body:
            result.append(f"**{group}**\n{body}")
    return result
