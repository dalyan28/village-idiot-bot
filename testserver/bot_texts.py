"""Inhalt von #texte: die längeren Texte, die der Bot an die Leute schickt, zum Gegenlesen.

Keine Buttons, nur Fließtext. Was der Bot aus Funktionen baut (Erinnerungen,
Rechte-Hinweis), wird hier direkt erzeugt. Der Rest ist eine Kopie vom Stand des Codes;
tests/test_testserver.py prüft, dass jede Kopie dort noch so steht (Datei + die ersten 25 Zeichen).

Ein Post je Gruppe, Gruppen und Texte in der Reihenfolge, in der man sie beim Benutzen trifft
(Dalyan, 27.10.2026: vorher wirkte der Kanal ungeordnet).
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

START = "Event anlegen mit /botc"
SCRIPT = "Skript wählen"
SUMMARY = "Zusammenfassung und Veröffentlichen"
CANCEL = "Abbrechen"
POST = "Am Event-Post"
SIGNUP = "Anmeldungen"
DOUBLE = "Doppelanmeldung (DM)"
REMINDER = "Erinnerungen"
ACADEMY = "Academy"

# Reihenfolge der Posts; je Gruppe die Texte in dieser Reihenfolge
ORDER: list[tuple[str, list[str]]] = [
    (START, ["Antwort im Channel", "DMs sind geschlossen", "Ohne Storyteller-Rolle",
             "Noch keine Storyteller-Rolle eingestellt", "Startnachricht in den DMs"]),
    (SCRIPT, ["Erste Karte nach dem Termin", "Skript-Karte", "botcscripts.com antwortet nicht",
              "ScriptRater antwortet nicht", "Skriptwahl übersprungen"]),
    (SUMMARY, ["Ungewöhnlicher Termin oder ungewöhnliche Dauer", "Titel oder Beschreibung im Chat schreiben",
               "Wenn noch etwas fehlt", "Wenn alles da ist", "Veröffentlicht"]),
    (CANCEL, ["Abgebrochen, der Entwurf bleibt", "Entwurf gelöscht", "Bearbeitung verworfen"]),
    (POST, ["Bearbeiten", "Bearbeiten ohne Recht", "Löschen"]),
    (SIGNUP, ["Zusage zu zwei Runden zur gleichen Zeit", "/meine_events ohne Anmeldungen"]),
    (DOUBLE, ["3 Stunden vor der früheren Runde", "Nach der Wahl einer Runde", "Nach „Ignorieren“",
              "Klick, nachdem die Runde begonnen hat", "Klick, wenn man schon abgemeldet ist"]),
    (REMINDER, ["Erinnerung im Thread", "Anwesenheitsliste"]),
    (ACADEMY, []),
]
GROUPS = [group for group, _ in ORDER]

# Gruppen ohne eigene Bot-Texte, nur mit einem Hinweis (Dalyan, 27.10.2026: der Academy-Text ist per Command
# änderbar, hier stand vorher eine Kopie)
NOTES = {
    ACADEMY: "Unter der Beschreibung von Academy-Runden steht ein fester Text. Den passt ihr direkt im Bot mit "
             "`/academy_text` an, dort seht ihr auch den aktuellen Text. Das dürfen Admins, das Event-Team und alle "
             "mit Academy-Freigabe.",
}

# Kleine Zeile unter dem Namen, wo der Name allein nicht sagt, wann der Text kommt
HINTS = {
    "Antwort im Channel": "nach /botc in einem Channel",
    "Skriptwahl übersprungen": "nach „Später wählen“ oder „Diesen Schritt überspringen“",
    "Ungewöhnlicher Termin oder ungewöhnliche Dauer": "Beispiel mit beiden Warnungen",
    "Zusage zu zwei Runden zur gleichen Zeit": "nur für die Person sichtbar, direkt nach der Zusage",
    "Erinnerung im Thread": "hier ohne Ping, im Thread unter dem Event",
    "Anwesenheitsliste": "hängt als anwesenheit.txt an der Erinnerung, neben dem Skript-JSON",
}

# (Gruppe, Name, Text, Datei im Code)
COPIED = [
    (START, "Antwort im Channel", "Es geht in deinen DMs weiter.", "commands/botc.py"),
    (START, "DMs sind geschlossen",
     "Ich kann dir keine DM schicken. Erlaube DMs von Servermitgliedern (Servereinstellungen → Privatsphäre) "
     "und starte `/botc` dann erneut.", "commands/botc.py"),
    (SCRIPT, "Erste Karte nach dem Termin",
     "Such dein Skript auf **botcscripts.com** oder wähl direkt ein Basis-Skript. Ein eigenes Skript kannst du als "
     "JSON anhängen.\n-# Danach siehst du die Zusammenfassung. Dort kannst du alles anpassen und die Runde "
     "veröffentlichen.", "discord_ui/layout_v2.py"),
    (SCRIPT, "Skript-Karte",
     "Such dein Skript auf **botcscripts.com**, wähl ein Basis-Skript oder die freie Skriptwahl, oder häng ein "
     "eigenes JSON an.", "discord_ui/layout_v2.py"),
    (SCRIPT, "botcscripts.com antwortet nicht",
     "botcscripts.com antwortet gerade nicht (zu langsam oder nicht erreichbar). Du kannst ein Basis-Skript oder "
     "die freie Skriptwahl nehmen, dein Skript als JSON hochladen oder es später erneut versuchen.",
     "discord_ui/wizard.py"),
    (SCRIPT, "ScriptRater antwortet nicht",
     "Der ScriptRater ist gerade nicht erreichbar. Bitte stell die Schwierigkeit selbst ein.",
     "discord_ui/wizard.py"),
    (SUMMARY, "Wenn noch etwas fehlt",
     "**Bevor du veröffentlichen kannst, fehlt noch:** Beschreibung", "discord_ui/layout_v2.py"),
    (SUMMARY, "Wenn alles da ist",
     "Alle Pflichtangaben sind vollständig. Wenn alles passt, klick auf **Veröffentlichen**.", "discord_ui/layout_v2.py"),
    (SUMMARY, "Veröffentlicht", "Dein Event ist veröffentlicht.", "discord_ui/wizard.py"),
    (CANCEL, "Abgebrochen, der Entwurf bleibt",
     "**Abgebrochen**\nDein Entwurf bleibt 24 Stunden gespeichert. Mit `/botc` kannst du jederzeit dort "
     "weitermachen.", "discord_ui/layout_v2.py"),
    (CANCEL, "Entwurf gelöscht",
     "Entwurf gelöscht. Mit `/botc` kannst du jederzeit neu starten.", "discord_ui/wizard.py"),
    (CANCEL, "Bearbeitung verworfen",
     "Bearbeitung verworfen, das Event bleibt unverändert.", "discord_ui/wizard.py"),
    (POST, "Bearbeiten", "Du kannst das Event in deinen DMs bearbeiten.", "discord_ui/event_post.py"),
    (POST, "Bearbeiten ohne Recht",
     "Bearbeiten dürfen nur der Ersteller und das Event-Team.", "discord_ui/event_post.py"),
    (POST, "Löschen", "Soll dieses Event wirklich gelöscht werden?", "discord_ui/event_post.py"),
    (SIGNUP, "/meine_events ohne Anmeldungen",
     "Du bist für keine kommende Runde angemeldet.", "discord_ui/my_events.py"),
]


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.split("\n"))


def _without_server_line(text: str) -> str:
    """Karten beginnen oft mit einer kleinen Serverzeile („-# Widow“); im Kanal ist die nur Rauschen."""
    first, sep, rest = text.partition("\n")
    if first.startswith("-# ") and rest.startswith("\n"):
        return rest.lstrip("\n")
    return text


def _entry(label: str, text: str) -> str:
    hint = HINTS.get(label)
    head = f"**{label}**" + (f"\n-# {hint}" if hint else "")
    return f"{head}\n{_quote(_without_server_line(text))}"


def generated() -> list[tuple[str, str, str]]:
    """Texte, die der Bot zur Laufzeit baut, mit Beispielwerten."""
    import discord

    from discord_ui.botc_start import build_start_layout, start_problem
    from events import reminders, service
    from events.store import Store

    guild = SimpleNamespace(id=1, name="Widow", get_role=lambda rid: SimpleNamespace(name="Storyteller"),
                            get_channel=lambda cid: None)
    member = SimpleNamespace(id=2, roles=[], guild_permissions=SimpleNamespace(manage_guild=False))
    store = Store(":memory:")
    no_role = start_problem(store, guild, member)
    service.set_access(store, guild.id, AccessSettings(storyteller_role_id=1))
    with_role = start_problem(store, guild, member)
    store.close()

    def card_text(layout) -> str:
        return "\n".join(i.content for i in layout.walk_children() if isinstance(i, discord.ui.TextDisplay))

    start = card_text(build_start_layout(guild, member.id))

    when = datetime(2026, 10, 24, 20, 0, tzinfo=BERLIN_TZ)
    people = [Person("Anna", 1), Person("Rosanna", 2)]
    names = reminders.copy_of(reminders.DEFAULTS[reminders.FIRST])
    names.mode = reminders.MODE_NAMES
    from events.schema import EventData, ScriptRef

    event = EventData(start=when, storyteller=Person("Dalyan", 3), script=ScriptRef(kind="base", name="Boozling"))

    # Wizard-Karten, die nur in bestimmten Momenten kommen
    from discord_ui import wizard
    from discord_ui.layout_v2 import chat_wait_layout, kind_layout

    fake_bot = SimpleNamespace(get_guild=lambda gid: guild)
    draft = SimpleNamespace(id=1, guild_id=guild.id, event_id=None, data=EventData(),
                            ui={wizard.AWAIT_KEY: {"field": "description"}})
    kind = card_text(kind_layout(fake_bot, draft))
    chat = card_text(chat_wait_layout(fake_bot, draft))
    soon = datetime(2026, 10, 1, 12, 0, tzinfo=BERLIN_TZ)
    far = EventData(start=datetime(2027, 4, 1, 20, 0, tzinfo=BERLIN_TZ), duration_minutes=600)
    warnings = "\n".join(wizard.plausibility_warnings(far, soon))

    # Doppelanmeldung: Hinweis beim Zusagen und Entscheidungs-DM (erfundene Runden)
    from discord_ui.conflicts import EXPIRED_NOTICE, IGNORED_NOTICE, RESOLVED_NOTICE, choice_notice, signup_hint
    from testserver.test_card import _double_view, fake_double_group
    group = fake_double_group()
    return [
        (START, "Ohne Storyteller-Rolle", with_role),
        (START, "Noch keine Storyteller-Rolle eingestellt", no_role),
        (START, "Startnachricht in den DMs", start),
        (SCRIPT, "Skriptwahl übersprungen", kind),
        (SUMMARY, "Ungewöhnlicher Termin oder ungewöhnliche Dauer", f"**Kurz prüfen**\n{warnings}"),
        (SUMMARY, "Titel oder Beschreibung im Chat schreiben", chat),
        (SIGNUP, "Zusage zu zwei Runden zur gleichen Zeit", signup_hint(group[1], group)),
        (DOUBLE, "3 Stunden vor der früheren Runde", card_text(_double_view())),
        (DOUBLE, "Nach der Wahl einer Runde", choice_notice(group[0], group[1:])),
        (DOUBLE, "Nach „Ignorieren“", IGNORED_NOTICE),
        (DOUBLE, "Klick, nachdem die Runde begonnen hat", EXPIRED_NOTICE),
        (DOUBLE, "Klick, wenn man schon abgemeldet ist", RESOLVED_NOTICE),
        (REMINDER, "Erinnerung im Thread", reminders.message_text(names, when, people)),
        (REMINDER, "Anwesenheitsliste", f"```\n{reminders.attendance_txt(event, people)}```"),
    ]


def posts() -> list[str]:
    """Die Einleitung, dann ein Post je Gruppe mit Überschrift."""
    texts = {label: text for _, label, text, _ in COPIED}
    texts.update({label: text for _, label, text in generated()})
    result = [INTRO]
    for group, labels in ORDER:
        body = NOTES.get(group) or "\n\n".join(_entry(label, texts[label]) for label in labels)
        result.append(f"### {group}\n{body}")
    return result
