# Auftrag: Testserver für die Admins (Village Idiot, nur Test-Branch)

## Kontext

Repo: `C:\Users\Dalyan\Documents\Programmieren\BOT_VillageIdiot` (Discord-Bot für eine Blood-on-the-Clocktower-Community, discord.py 2.7, Components V2). Auf dem Branch `event-wizard` ist die Event-Erstellung neu gebaut: `/botc` öffnet ein Modal, danach läuft ein DM-Wizard (Skript wählen, dann Zusammenfassung mit „Ändern“-Dialogen), am Ende wird das Event im Event-Channel gepostet (Embed mit Zusagen/Absagen, Bearbeiten, Löschen). Lies zuerst `docs/event_wizard_plan.md`, dort steht der Stand inkl. offener Features (Backlog).

Die Server-Admins der Community sollen das jetzt auf einem eigenen Test-Discord ausprobieren. Dafür braucht der Bot Commands, die so einen Testserver aufsetzen, zurücksetzen und wieder abbauen, und einen Weg, Feedback direkt aus dem Bot heraus zu geben.

Vorlage: Im Projekt `C:\Users\Dalyan\Documents\Programmieren\Ratcon-Bot` gibt es das schon in ähnlicher Form. Dort nur lesen, nichts ändern. Interessant:
- `commands/admin_setup.py`: `CATEGORY_PLAN`, `/setup` (Kategorien und Channels anlegen, Rechte setzen, Überzähliges aufräumen), `/setup-post` (feste Texte posten), `/purge`, `/purge-all`
- `logic/channel_registry.py`, `logic/persistent_messages.py`: Channels und gepostete Nachrichten wiederfinden
- `docs/writingstyle.md`: wie Bot-Texte klingen sollen

Übernimm Ideen und Muster, aber passend zum Aufbau von Village Idiot (Cogs in `commands/`, SQLite-Store in `events/store.py`, Server-Config über `config.py`/`get_guild_config`). Kein Code aus Ratcon blind kopieren.

## Wichtig: alles isoliert, nichts davon wird gemergt

- Neuer Branch `testserver` von `event-wizard`. Nur dort committen. Nicht pushen, nicht mergen, nicht deployen.
- So bauen, dass es sich sauber wieder trennen lässt: eigener Cog (z. B. `commands/test_server.py`), eigene Dateien, im Bestandscode nur minimale, klar markierte Einhängepunkte (Kommentar `# TESTSERVER`). Laden nur, wenn eine Umgebungsvariable gesetzt ist (z. B. `TEST_SERVER=1`). Ohne die Variable verhält sich der Bot exakt wie auf `event-wizard`.
- `.env` und Token nie lesen, ausgeben oder ändern. Neue Variablen nur dokumentieren, eintragen macht Dalyan.

## 1. Commands zum Aufsetzen

Nur für Server-Admins (`manage_guild`) und nur auf Servern, die als Testserver freigegeben sind (eigene Liste, z. B. `TEST_GUILD_IDS`). Auf allen anderen Servern antworten sie mit einem Hinweis und tun nichts. Das ist die Sicherung dagegen, dass jemand aus Versehen den echten Community-Server abräumt.

- **Setup**: legt den Server an. Mindestens diese Channels:
  - **willkommen**: kurz erklärt, was der neue Bot kann, was noch offen ist (aus dem Backlog im Plan) und wie man testet. Schreibgeschützt.
  - **commands**: alle Commands mit je einer Zeile Erklärung, auch die Admin-Commands (`/set_event_channel`, `/set_event_roles`, `/set_reminders` usw.). Schreibgeschützt.
  - **events**: der Event-Channel. Setup trägt ihn beim Bot als Event-Channel ein (wie `/set_event_channel`).
  - **feedback**: hier landet das Feedback (siehe 2). Man kann dort auch selbst schreiben.
  - Was sonst noch sinnvoll ist (z. B. Übersichts-Channel, Storyteller-Rolle für `/botc` über `/set_event_roles`), schlag vor und bau es, wenn es klein bleibt.
  - Mehrfach ausführbar: Was schon da ist, wird wiederverwendet bzw. aktualisiert, nicht doppelt angelegt.
- **Reset**: leert nur den Event-Channel. Alle Event-Posts weg, die zugehörigen Events, Anmeldungen und Entwürfe dieses Servers aus der Datenbank weg. Channels bleiben.
- **Delete All**: entfernt alles, was Setup angelegt hat (Channels, Kategorien, ggf. Rollen) und die Bot-Einstellungen für diesen Server. Mit Bestätigungs-Button.

Namen der Commands schlägst du vor (z. B. `/testserver setup|reset|delete_all` als Gruppe).

## 2. „Feedback“-Button

- An jeder Wizard-Karte (Skript-Karte, Zusammenfassung, Bild-Seite) und am Event-Post ein zusätzlicher Button „Feedback“.
- Klick öffnet einen Dialog mit einem Textfeld („Was ist dir hier aufgefallen? Gut, schlecht, Bug, egal was.“). Optional eine Auswahl Bug / Idee / Gefällt mir / Gefällt mir nicht.
- Danach postet der Bot in den Feedback-Channel des Servers: von wem, bei welchem Schritt (Karte/Seite, Draft- bzw. Event-ID), was die Person davor gemacht hat (die letzten paar Aktionen, z. B. „Skript gesucht: boo → Treffer 2 gewählt → Beschreibung geschrieben“) und das Feedback selbst. Dafür eine kleine Aktions-Historie pro Entwurf mitschreiben (z. B. in `drafts.ui`), nur auf dem Test-Branch.
- Achte auf die Discord-Grenzen: 40 Komponenten und eindeutige custom_ids pro Nachricht, max. 5 Buttons pro Zeile. Der Button darf vorhandene Buttons nicht verdrängen. Bestehende DynamicItem-Muster (`wiz:<draft_id>:<aktion>`, `evt:<event_id>:<aktion>`) nutzen bzw. ein eigenes Präfix anlegen, damit es nach einem Neustart weiter funktioniert.

## Texte

Alle Texte für die Admins auf Deutsch und so, wie Dalyan schreibt und redet: sehr kurz, locker, direkt, duzen. Keine Gedankenstriche, kein Marketing-Ton, keine Deko-Emojis (Regeln dazu in Ratcon `docs/writingstyle.md`, sinngemäß auf Deutsch). Der Willkommens-Text soll in einer halben Minute gelesen sein: was ist neu, was ist noch nicht drin, was sollst du ausprobieren, wo gibst du Feedback. Lass Dalyan die Texte vor dem Commit einmal sehen.

## Abschluss

- Tests im Stil der vorhandenen (`tests/`, Fakes in `tests/test_wizard_flow.py`); `venv/Scripts/python -m pytest -q` muss grün sein.
- Kurze Anleitung für Dalyan in `docs/testserver.md`: Variablen setzen, Bot einladen, Setup ausführen, Reset und Delete All, wie man den Branch später wieder wegwirft.
- Commits auf `testserver`, nicht pushen. Am Ende kurz berichten, was gebaut ist und was offen bleibt.
