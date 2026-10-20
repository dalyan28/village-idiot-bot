# Testserver für die Admins

Nur auf Branch `testserver`. Der Branch wird nicht gemergt, sondern nach dem Test weggeworfen.

## Was es gibt

- `/testserver setup`: legt zwei Kategorien an: „Start“ mit `👋︱willkommen` (Willkommen mit den wichtigsten Commands, Features),
  `🗒️︱texte` (die längeren Bot-Texte zum Gegenlesen), `💬︱chat` und `📝︱feedback`, und „Runden“ mit `📅︱events` und `📋︱übersicht`. Kein Sprachchat. Dazu die Rollen
  „Storyteller“ und „Event-Team“. Trägt Event- und
  Übersichts-Channel ein (wie `/set_event_channel`, `/set_overview_channel`) und die Rollen (wie `/set_event_roles`).
  Postet die Texte (als „Nachricht von Dalyan“). Mehrfach ausführbar: Vorhandenes wird aufgefrischt, Texte werden
  bearbeitet statt neu gepostet.
- `/testserver beispiel-event`: postet ein volles Beispiel-Event (Boozling, 23 erfundene Anmeldungen: 12 spielen,
  3 auf der Warteliste, 4 vorläufig, 4 Absagen). Setup legt einmal eins an, wenn es noch keins gibt.
- `/testserver reset`: leert den Event-Channel (Posts und Reminder-Threads) und löscht alle Runden, Anmeldungen,
  Entwürfe und eigenen Bilder dieses Servers aus der Datenbank. Channels bleiben.
- `/testserver delete_all`: nach Bestätigung alles weg, was Setup angelegt hat (außer `📝︱feedback`), plus alle Bot-Einstellungen dieses
  Servers (Rollen, Reminder, Channels in `config.json`).
- Button **Feedback** an Skript-Karte, Zusammenfassung, Bild-Seite und Event-Post. Der Post im Feedback-Channel
  nennt Person, Karte, Entwurf bzw. Event und die letzten Aktionen davor.

Die Commands laufen nur für Admins (Server verwalten) und nur auf Servern aus `TEST_GUILD_IDS`. Überall sonst
antworten sie mit einem Hinweis und tun nichts.

## Variablen

Neu (in `.env` bzw. beim Railway-Service eintragen):

| Variable | Wert | Wozu |
|---|---|---|
| `TEST_SERVER` | `1` | lädt `/testserver` und schaltet den Feedback-Button ein. Ohne: Bot wie auf `event-wizard`. |
| `TEST_GUILD_IDS` | Server-IDs, kommagetrennt | nur diese Server zählen als Testserver |

Der Testserver muss außerdem in `ALLOWED_GUILD_IDS` stehen, sonst verlässt der Bot ihn sofort (Server-Lock).

Empfohlen ist die eigene Test-Anwendung („Village Idiot Dev“) mit eigenem Token und eigener Datenbank, siehe
`docs/event_wizard_plan.md`, „Testen auf anderen Servern“. Dann stehen in `ALLOWED_GUILD_IDS` und `TEST_GUILD_IDS`
nur Testserver.

## Ablauf

1. Testserver in Discord anlegen, Server-ID kopieren (Entwicklermodus, Rechtsklick auf den Server).
2. `ALLOWED_GUILD_IDS` und `TEST_GUILD_IDS` setzen, `TEST_SERVER=1`, Bot neu starten.
3. Bot einladen. Am einfachsten mit „Administrator“; sonst braucht er mindestens Kanäle verwalten, Rollen verwalten,
   Nachrichten verwalten, Threads verwalten, Nachrichten senden, Links einbetten, Dateien anhängen,
   Nachrichtenverlauf lesen und öffentliche Threads erstellen. Scopes: `bot` und `applications.commands`.
4. `/testserver setup` ausführen. Danach den Admins die Rolle „Storyteller“ geben, wenn sie keine Admins sind.
5. Zwischendurch `/testserver reset`, wenn der Event-Channel voll ist.
6. Zum Schluss `/testserver delete_all`.

## Wieder wegwerfen

Im Bestandscode hängt der Testserver nur an Zeilen mit `# TESTSERVER` (`bot.py`, `discord_ui/wizard.py`,
`discord_ui/layout_v2.py`, `discord_ui/event_post.py`). Der Rest liegt in `testserver/`,
`commands/test_server.py`, `tests/test_testserver.py` und dieser Datei.

```
git checkout event-wizard
git branch -D testserver
```

Die Variablen `TEST_SERVER` und `TEST_GUILD_IDS` danach wieder entfernen. Auf dem Testserver vorher
`/testserver delete_all`, sonst bleiben Channels und Rollen stehen.
