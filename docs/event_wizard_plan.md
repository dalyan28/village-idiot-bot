# Event-Wizard: Plan

Stand: 19.10.2026, Branch `event-wizard` (von `main`).
Diese Datei ist die Übergabe: Wer die Arbeit aufnimmt, liest zuerst sie und aktualisiert sie am Ende jedes Arbeitsblocks.

## Ziel

Die Event-Erstellung aus Branch `event-creation` wird ohne KI neu gebaut: deterministisch und linear.

1. `/botc` öffnet ein **Modal** mit den Eckdaten (kein Titel, keine Beschreibung).
2. Ein **DM-Wizard** führt Schritt für Schritt bis zum fertigen Event.
3. Ein Event ist danach **im DM-Wizard bearbeitbar** und **auf einer Website verwaltbar**.
4. Auch die **Erstellung** geht auf der Website, für alle, die das lieber dort machen.

## Entscheidungen (Dalyan, 19.10.2026)

| Thema | Entscheidung |
|---|---|
| Basis | Neuer Branch von `main`. Die Module ohne KI werden aus `event-creation` übernommen, der Branch selbst wird nicht gemerged. |
| Datum im Modal | Textfeld mit deterministischem Parser (kein Select). |
| Website | Läuft im Bot-Service (FastAPI im Event-Loop des Bots), eigene Subdomain, z. B. `events.widow-botc.com`. Das Design übernimmt CSS und Header vom ScriptRater. |
| Einschätzung des Skripts | Kommt vom ScriptRater (`POST /api/analyse`). Dort ist der Algorithmus gepflegt und korrigiert. |
| KI | Fällt vollständig weg: `anthropic`, `logic/conversation.py`, `logic/llm_config.py`, Kostenzeile, Max-Calls, Resume-Keywords. |
| Wer darf `/botc` | Nur eine bestimmte Rolle, von Server-Admins konfigurierbar (siehe „Rollen und Berechtigungen“). |
| Academy | Nur konfigurierbare Rollen oder User dürfen Academy-Events erstellen (siehe „Rollen und Berechtigungen“). |
| botcscripts.com | Die Anbindung bleibt zentral: Suche, Versionen, Skript-JSON für den Reminder. Sie wird aus `event-creation` übernommen und nicht vereinfacht. |
| Bestandsdaten | `event-creation` lief nie produktiv. Keine Migration von `events.json`, die Datenbank startet leer. |
| Skript-Bild | Nur das schlichte Design (weißer Hintergrund, normale Icons, = `plain_white` vom alten Branch, pixelgleich). Papier, Starfield, Neon und `script_image_v2.py` verworfen (Dalyan, 20.10.2026). |
| Co-ST | Darf das Event weder bearbeiten noch Teilnehmer verwalten. |
| Gäste | Sehen auf der Website nichts. Ohne Login und Servermitgliedschaft gibt es keine Termine. |
| Event-Team | Eine eigene Rolle neben „Server verwalten“, die alle Events des Servers verwalten darf. |
| Embed-Felder | „NPCs“ (Fabled/Loric) wird wieder angezeigt. „Relevante Charaktere“ kommt als **„Highlights“** zurück (siehe „Event-Embed“). Nutzer werden immer als Text angezeigt, nie als Mention. |
| ScriptRater | Läuft unter `https://widow-botc.com/script-check`, gehostet auf Railway, DNS bei Cloudflare. |

## Feldschema

Ein Schema an genau einer Stelle (`events/schema.py`). Modal, Wizard, Website, Embed und Speicherung lesen alle daraus.

Die Defaults aus Branch `event-creation` gelten unverändert weiter (Dalyan, 19.10.2026): 12 Spieler, 150 Minuten, Level
„Alle“, Kamera „Keine Pflicht“, Casual/Academy/Aufzeichnung aus, Storyteller = der erstellende User, kein Co-ST.

| Feld | Typ | Default | Wo erfasst | Hinweis |
|---|---|---|---|---|
| `start` | Zeitpunkt (Europe/Berlin) | – | Modal (Datum + Uhrzeit) | Pflicht, muss in der Zukunft liegen |
| `max_players` | int | 12 | Modal | erlaubt 1–200 (Dalyan, 19.10.2026) |
| `level` | Neuling / Erfahren / Profi / Alle | Alle | Modal | |
| `is_casual` | bool | false | Modal (Checkbox) | darf mit Academy kombiniert werden; im Titel steht 🎓 vor 🕊️ (Dalyan, 20.10.2026) |
| `is_academy` | bool | false | Modal (Checkbox) | Beschreibung fest, Thumbnail Academy, „Auffüller“ statt „Vorläufig“ |
| `is_recorded` | bool | false | Modal (Checkbox) | |
| `camera` | Pflicht / Keine Pflicht / Aus | Keine Pflicht | Modal (Checkbox „Kamera-Pflicht“), „Aus“ im Wizard | |
| `duration_minutes` | int | 150 | Wizard Schritt 3 | Select: 90–240 in 30er-Schritten |
| `storyteller` | Text | Anzeigename des Users | Wizard Schritt 3 | |
| `co_storyteller` | User-ID + Anzeigename, oder leer | leer | Wizard Schritt 3 | Die User-ID wird für die Rechte auf der Website gebraucht, siehe dort |
| `script` | Referenz | – | Wizard Schritt 1 | Basis-3, botcscripts.com (ID + Version), Upload (JSON gespeichert) oder freie Wahl |
| `rating` | grün / gelb / rot / homebrew | aus ScriptRater | Wizard Schritt 2 | per Button überschreibbar, mit Herkunft (`rater` / `manuell` / `fest`) |
| Titel | – | – | wird gebaut, nie eingegeben | Symbole, dann „{Skript} mit {ST}[ und {Co-ST}]“ (Dalyan, 19.10.2026) |
| `description` | Text, max. 1000 Zeichen | leer | Wizard Schritt 4 | schreibt der Ersteller selbst; Pflicht außer bei Academy, dort folgt der feste Academy-Text |
| `image_mode` / `custom_image` | auto / eigenes / keins | auto | Wizard Schritt 5 | auto = Skript-Bild (auch für Basis-3), eigenes Bild als PNG auf dem Volume |
| `reminder_overrides` | Abweichungen vom Server-Default | leer | Wizard Schritt 3 | siehe „Reminder“ |

Vom System gepflegt: `creator_id`, `guild_id`, `channel_id`, `message_id`, `created_at`, `deleted_at`, RSVP-Listen, Reminder-Status.

## Server-Lock (Dalyan, 19.10.2026)

Der Bot läuft vorerst **nur auf einem Server** und funktioniert auf keinem anderen. Der Code bleibt trotzdem
mehrserverfähig: Alles ist weiter je `guild_id` gespeichert und konfiguriert, der Lock ist eine Schicht darüber und lässt
sich später durch eine längere Liste aufheben.

- **Konfiguration**: Umgebungsvariable `ALLOWED_GUILD_IDS` (kommagetrennt, heute genau eine ID).
- **Commands nur dort registriert**: statt globalem `bot.tree.sync()` (heute in `bot.py`) Sync je erlaubtem Server
  (`tree.copy_global_to(guild=…)` + `tree.sync(guild=…)`) und die globalen Commands leeren. Auf anderen Servern tauchen die
  Commands dann gar nicht erst auf. Nebeneffekt: Guild-Sync greift sofort, globaler Sync braucht bis zu einer Stunde.
- **Prüfung bei jeder Interaktion**: globaler `interaction_check` im Command-Tree und in allen Views (Buttons, Modals,
  Selects). Fremder Server → ephemere Antwort „Dieser Bot ist nur für {Servername} freigeschaltet“, sonst nichts.
- **DMs**: Ein DM-Wizard gehört immer zu einem Entwurf mit `guild_id`; nur Entwürfe erlaubter Server werden bearbeitet.
- **Hintergrund-Tasks** (Übersicht, Reminder, Cleanup) laufen nur für erlaubte Server.
- **Fremder Server lädt den Bot ein**: `on_guild_join` → Server verlassen, im Log vermerken. Beim Start werden fremde
  Server ebenso verlassen.
  Schutz vor Fehlkonfiguration: Ist `ALLOWED_GUILD_IDS` leer oder fehlt, verlässt der Bot **keinen** Server, sondern
  verweigert nur alle Interaktionen und loggt eine Warnung. Sonst würde ein Tippfehler in der Variable den Bot aus dem
  eigenen Server werfen.
- **Website** (Phase 7): Login nur für Mitglieder eines erlaubten Servers.
- **Zusätzlich im Discord Developer Portal**: „Public Bot“ ausschalten. Dann kann nur der Eigentümer der Anwendung den Bot
  einladen. Das ist eine Einstellung, kein Code, und muss von Hand gesetzt werden.
- Der Lock gilt für den **ganzen Bot**, also auch für die bestehenden Übersichts-Features von `main`.

### Testen auf anderen Servern

Dalyan muss den Bot auch auf Test-Servern ausprobieren können. Dafür:

- **Erlaubte Server sind eine Liste.** Ein Test-Server wird einfach mit seiner ID in `ALLOWED_GUILD_IDS` eingetragen.
- **Empfohlen: eigene Test-Anwendung im Developer Portal** (eigener Bot-Token, z. B. „Village Idiot Dev“), lokal oder als
  zweiter Railway-Service mit `ENV=dev`. Ihre `ALLOWED_GUILD_IDS` enthält nur die Test-Server, die des Produktiv-Bots nur
  den echten Server. So landen Test-Events und Test-Commands (`/create_test_event` usw., heute schon an `ENV=dev`
  gebunden) nie auf dem echten Server, und der Produktiv-Bot muss keinem Test-Server beitreten.
- Eigene Datenbank je Umgebung (lokal eine Datei im Projektordner, auf Railway das jeweilige Volume).
- **Reihenfolge beim Einladen**: erst die ID in `ALLOWED_GUILD_IDS` eintragen und neu starten, dann einladen. Sonst
  verlässt der Bot den Server sofort wieder. Die Log-Meldung beim Verlassen nennt Servername und ID, damit man sie direkt
  übernehmen kann.

## Event-Embed

Aufbau wie in `event-creation` (`logic/event_builder.py`): Author, Titel, Storytelling/Kamera/Level, Co-ST, Beschreibung,
Skript, Termin, RSVP-Listen, Bild, Footer. Dazu kommen zwei Felder wieder hinzu, die dort auskommentiert waren:

- **NPCs**: Fabled und Loric des Skripts, durch Komma getrennt. Fehlt das Feld, wenn es keine gibt.
- **Highlights** (Name: Dalyan, 19.10.2026; ersetzt „Relevante Charaktere“, weil „relevant“ andere Charaktere als
  unwichtig hinstellt): bis zu 5 Charaktere mit dem höchsten Score aus `character_rating.json`, Score 9–10 fett. Die Zahl
  hinter dem Namen (Score) entfällt im Embed, sie ist für Spieler ohne Kontext nicht lesbar.
- Basis-3 zeigt beide Felder wie jedes andere Skript. Bei freier Skriptwahl gibt es keine Charaktere, dort fehlen beide Felder.

### Nutzer immer als Text anzeigen (Dalyan, 19.10.2026)

Überall, wo Nutzer angezeigt werden (Teilnehmer, Warteliste, Auffüller, Abgelehnt, Storyteller, Co-ST, Author/Footer),
steht der **Anzeigename als Text**, nie eine Mention `<@id>`. Grund: Discord löst Mentions in Embeds oft nicht auf, weil
der Client den Nutzer nicht im Cache hat, und zeigt dann die rohe ID.

- Gespeichert wird immer beides: `user_id` (für Rechte und Logik) und `display_name` (Anzeigename auf dem Server zum
  Zeitpunkt der Aktion, also Server-Nickname vor globalem Namen).
- Beim Rendern nimmt der Bot den aktuellen Namen aus seinem Member-Cache und fällt auf den gespeicherten zurück. Ändert
  jemand den Namen, steht beim nächsten Neuaufbau des Embeds (jede RSVP-Änderung) der neue Name drin.
- Namen werden für Markdown escaped (`discord.utils.escape_markdown`), damit `*`, `_` oder `~` im Namen das Embed nicht zerschießen.
- Die alte Hilfsfunktion `_format_user_list_quoted` (Mentions `> <@id>`) wird durch eine Variante mit Namen ersetzt.
- Ausnahme: **Reminder** dürfen per Mention pingen, wenn das so eingestellt ist (siehe „Reminder“). Dort ist der Ping der
  Zweck. Bei der Einstellung „nur Namen“ gilt auch dort Text.

Die Score-Daten liegen auch im ScriptRater (`app/data/character_rating.json`). Solange `/api/analyse` keine Liste der
hervorgehobenen Charaktere liefert, bleibt die Kopie im Bot; langfristig soll sie aus dem ScriptRater kommen.

## Reminder

Bisher (`commands/reminder.py` auf `event-creation`): Schleife alle 2 Min.; ~15 Min. vor Start Thread am Event-Post,
Ping aller Zusagen, Skript-JSON; ~5 Min. vor Start Anwesenheitskontrolle mit nummerierter Liste, wieder als Ping. Alles
fest eingebaut. Schwächen: Ein verpasstes Zeitfenster (Neustart, Event kurz vor Start angelegt) lässt den Reminder
ausfallen; die Warteliste wird als Zusage mitgepingt; Vorläufige/Auffüller und Co-ST bekommen nie etwas; für Basis-3 wird
vermutlich kein Skript-JSON gepostet (keine botcscripts-ID gespeichert, beim Übernehmen prüfen).

Neu (Dalyan, 19.10.2026): **Server-Default + Anpassung je Event.**

Einstellungen je Reminder:

| Einstellung | Werte | Default |
|---|---|---|
| Aktiv | ja / nein | ja |
| Zeitpunkt | Minuten vor Start | 15 bzw. 5 |
| Benachrichtigung | Ping / nur Namen | Ping |
| Empfänger | Zusagen, Warteliste, Vorläufig/Auffüller, Co-ST (Mehrfachauswahl) | Zusagen ohne Warteliste |
| Skript-JSON posten | ja / nein | ja beim ersten, nein beim zweiten |
| Art | Erinnerung / Anwesenheitskontrolle (nummerierte Liste) | erster: Erinnerung, zweiter: Anwesenheitskontrolle |

- **Server-Default**: `/set_reminders` und `/see_reminders`, nur Event-Team bzw. „Server verwalten“. Gespeichert in der
  Guild-Konfiguration.
- **Je Event**: Wizard Schritt 3 zeigt „Erinnerungen: Server-Standard (15 Min. Ping, 5 Min. Anwesenheit)“ mit Button
  „Anpassen“. Gespeichert wird nur die Abweichung (`reminder_overrides`); ändert ein Admin später den Server-Default,
  greift das für alle Events ohne eigene Anpassung.
- **Auslösung**: „fällig und noch nicht gesendet“ statt Zeitfenster. Ein verpasster Reminder wird nachgeholt, solange das
  Event noch nicht begonnen hat; danach verfällt er still. Gesendete Reminder je Event in der Datenbank
  (`event_reminders`: `event_id`, `reminder_key`, `sent_at`). Termin geändert → Status zurückgesetzt (wie bisher).

## Rollen und Berechtigungen (Discord)

Zwei Rollen je Server, gespeichert in der Guild-Konfiguration:

- **Storyteller-Rolle**: darf `/botc` nutzen und eigene Events bearbeiten und löschen.
- **Event-Team-Rolle**: darf zusätzlich alle Events des Servers bearbeiten, löschen und Teilnehmer verwalten.
  „Server verwalten“ zählt immer als Event-Team.

Konfiguration über `/set_event_roles storyteller:<Rolle> event_team:<Rolle>`, nur für „Server verwalten“
(`default_permissions`). `/see_event_roles` zeigt den Stand. Ist keine Storyteller-Rolle gesetzt, dürfen nur Event-Team
und Admins `/botc` nutzen. Der Bot erklärt das in der Antwort und verweist auf den Command.

Warum ein eigener Command und nicht nur die Discord-Einstellungen? Unter *Servereinstellungen → Integrationen* lässt sich
`/botc` zwar auf Rollen beschränken, und das bleibt als zusätzliche Möglichkeit erhalten. Der Bot muss die Rollen aber
selbst kennen: für die Buttons „Bearbeiten“ und „Löschen“ am Event, für das Event-Team und später für die Website. Die
Prüfung im Bot ist deshalb maßgeblich, die Discord-Einstellung ist nur ein Filter für die Sichtbarkeit des Commands.

**Academy-Angebote** (Dalyan, 19.10.2026): Nur bestimmte Rollen oder einzelne User dürfen Academy-Events erstellen.
Konfigurierbar über `/set_academy_access` (Rollen und/oder User hinzufügen und entfernen), nur Event-Team bzw. „Server
verwalten“. **Server-Admins dürfen es immer, das Event-Team nur mit Freigabe** (Dalyan, 20.10.2026).
- Im Modal erscheint die Checkbox „Academy“ nur für Berechtigte (das Modal wird je Aufruf gebaut, das geht).
- Wer nicht berechtigt ist, kann Academy auch beim Bearbeiten nicht einschalten. Ein bestehendes Academy-Event bleibt
  Academy, auch wenn der Ersteller die Berechtigung später verliert.
- Details (z. B. ob Academy-Berechtigte automatisch auch die Storyteller-Rolle brauchen) klären wir später.

Eine Person verliert die Storyteller-Rolle: Ihre bestehenden Events bleiben, sie kann sie weiter bearbeiten und löschen,
aber keine neuen anlegen.

## Modal (`/botc`)

Fünf Elemente (Grenze von Discord), discord.py 2.7.1 kann Label, Select, Radio, Checkbox und FileUpload in Modals:

1. **Datum**: Textfeld, Platzhalter „z. B. Sa, morgen, 24.10.“
2. **Uhrzeit**: Textfeld, Platzhalter „20:00“
3. **Max. Spieler**: Textfeld, vorbelegt mit 12
4. **Erfahrungslevel**: Radio Neuling / Erfahren / Profi / Alle, vorausgewählt Alle
5. **Optionen**: Checkboxen Casual, Academy, Aufzeichnung, Kamera-Pflicht

Nach dem Absenden: ephemere Antwort „Check deine DMs“ und Start des Wizards. Die erste DM nennt den erkannten Termin
ausgeschrieben („Samstag, 24.10.2026, 20:00–22:30“), damit Fehler sofort auffallen.

Kann der Parser die Eingabe nicht lesen, antwortet der Bot ephemer mit dem Grund und einem Button „Nochmal“. Der öffnet das
Modal erneut, vorbelegt mit der alten Eingabe.

### Parser (deterministisch, `events/parse.py`)

- Datum: `heute`, `morgen`, `übermorgen`; Wochentage lang und kurz (`Samstag`, `Sa`, `nächsten Samstag`); `in 3 Tagen`;
  `24.10.`, `24.10`, `24.10.2026`, `24.10.26`, `2026-10-24`. Ohne Jahr: das nächste Vorkommen in der Zukunft.
- Uhrzeit: `20`, `20:00`, `20.00`, `2000`, `20 Uhr`, `20:30 Uhr`.
- Ablehnen: Zeitpunkt in der Vergangenheit, mehr als 1 Jahr in der Zukunft, ungültiges Datum (31.02.).
- Umfangreich getestet, ohne Discord.

## DM-Wizard

> Stand 20.10.2026: Ablauf und Zusammenfassung wurden nach dem ersten Test umgebaut, siehe „Umbau nach dem ersten Test“.
> Die folgende Beschreibung ist der ursprüngliche Plan.

Eine Wizard-Nachricht pro Session, die bei jedem Schritt **bearbeitet** statt neu gesendet wird. Jeder Schritt hat
„Zurück“ und „Abbrechen“. Texteingaben laufen über kleine Modals statt über freie Chat-Nachrichten. Damit fällt die
Zustandsweiche über Chat-Nachrichten (`on_message`) komplett weg.

1. **Skript**: Buttons Trouble Brewing, Bad Moon Rising, Sects & Violets, Freie Skriptwahl, Suchen, JSON hochladen.
   - Suchen: Modal mit Suchbegriff → Select mit den Treffern von botcscripts.com → Select mit der Version (falls mehrere).
   - JSON hochladen: Modal mit FileUpload, Validierung wie bisher (`validate_script_json`).
2. **Einschätzung**: Ergebnis vom ScriptRater mit Überschrift und Begründung. Buttons „Passt“, „Grün“, „Gelb“, „Rot“.
   Basis-3 fest (TB grün, BMR/S&V gelb). Freie Wahl: keine Einschätzung. ScriptRater nicht erreichbar: der Storyteller wählt selbst.
3. **Leitung und Details**: Storyteller (Default: User), Co-ST, Dauer, Kamera, Erinnerungen (siehe „Reminder“). Den Co-ST tippt der User in ein Modal, der
   Bot sucht ihn unter den Servermitgliedern und bietet die Treffer als Select an (siehe Website, „Folgen für die früheren Phasen“).
4. **Beschreibung**: schreibt der Ersteller selbst (Modal, vorbelegt beim Bearbeiten). Der Titel wird nicht
   eingegeben, sondern immer gebaut.
5. **Bild**: „Aus dem Skript“ (Skript-PNG wird gerendert und gezeigt), „Eigenes Bild hochladen“ (Modal mit
   FileUpload, ersetzt ein vorheriges), „Kein Bild“.
6. **Vorschau**: Das Embed genau so, wie es gepostet wird. Buttons „Veröffentlichen“, „Schritt ändern“ (Select),
   „Im Browser bearbeiten“ (Link), „Abbrechen“.

**Bearbeiten**: Der Button „Bearbeiten“ am Event öffnet in den DMs direkt die Vorschau (Schritt 6). Über
„Schritt ändern“ springt man in einen Schritt und kommt danach zurück zur Vorschau. Beim Speichern bleiben die RSVPs
erhalten, und Reminder werden zurückgesetzt, wenn sich der Termin ändert (wie bisher).

**Entwürfe** liegen in der Datenbank, nicht im Arbeitsspeicher. Ein Wizard übersteht einen Neustart, läuft nach 24 h
ohne Aktivität ab und lässt sich auf der Website fortsetzen. `/botc` mit offenem Entwurf fragt: „Weitermachen“ oder „Neu“.

## Website (`events.widow-botc.com`) — wird zuletzt umgesetzt

Dalyan (19.10.2026): Die Website ist von Anfang an mitgedacht. Der Kern (`events/service.py`) kennt deshalb kein Discord
und kein Web, und jede Änderung läuft über eine Funktion, die den handelnden User und seine Rolle prüft. Gebaut wird die
Website aber erst, wenn Modal und Wizard produktiv laufen (Phase 7). Der Grund ist das Rechtemodell: Wer darf welches
Event sehen und ändern?

### Technik

- FastAPI + Jinja, gestartet in `bot.py` neben dem Bot im selben Event-Loop (`uvicorn.Server(...).serve()`).
- Optik: `style.css` und Header vom ScriptRater übernehmen, gegenseitig verlinken.
- Speichern auf der Website aktualisiert die Discord-Nachricht sofort (gleiche Service-Funktion wie der Wizard).

### Identität: wer ist der Besucher?

- Login nur über **Discord OAuth2** (Authorization Code Flow, Scope `identify`). Die Website kennt danach die Discord-User-ID,
  sonst nichts: keine eigenen Konten, keine Passwörter.
- `state`-Parameter gegen CSRF im Login. Die Session liegt in einem signierten, `HttpOnly`-, `Secure`-, `SameSite=Lax`-Cookie
  (Starlette `SessionMiddleware`, `SESSION_SECRET`). Das Discord-Access-Token wird nach dem Login nicht gespeichert.
- **Servermitgliedschaft und Rollen prüft der Bot**, nicht der Browser: Der Bot fragt seinen Member-Cache (oder
  `fetch_member`) der Guild des Events. Wer den Server verlassen hat, sieht nichts mehr. Ergebnis kurz cachen (z. B. 5 Min.).
- **Login-Link aus Discord**: „Im Browser bearbeiten“ führt auf eine normale URL der Website. Die Website verlangt dort
  ganz normal den Login. Kein Token in der URL, das sich weiterleiten ließe. (Optional später: ein kurzlebiger,
  einmal gültiger, an die User-ID gebundener Link, der den OAuth-Schritt nur vorausfüllt.)

### Rollen je Event

Die Rolle wird **je Anfrage und je Event** auf dem Server aus der Datenbank und der Guild berechnet, nie aus dem Request
übernommen:

| Rolle | Wer | Ableitung |
|---|---|---|
| Ersteller | hat das Event angelegt | `events.creator_id` |
| Co-ST | leitet mit, hat aber keine Verwaltungsrechte | Feld mit **User-ID** statt nur Text (siehe unten) |
| Event-Team | Event-Team-Rolle oder „Server verwalten“ in der Guild des Events | Guild-Konfiguration + Rollen über den Bot |
| Teilnehmer | ist in `accepted`, `tentative` oder auf der Warteliste | RSVP-Tabelle |
| Servermitglied | ist Mitglied der Guild, sonst nichts | Guild über den Bot |
| Gast | nicht eingeloggt oder nicht in der Guild | – |

### Was jede Rolle darf

| Aktion | Gast | Mitglied | Teilnehmer | Co-ST | Ersteller | Event-Team |
|---|---|---|---|---|---|---|
| Überhaupt etwas sehen | – | ✔ | ✔ | ✔ | ✔ | ✔ |
| Eventliste der Guild sehen | – | ✔ (Felder wie im Discord-Embed) | ✔ | ✔ | ✔ | ✔ |
| Eigene Anmeldung ändern (zu-/absagen, vorläufig) | – | ✔ | ✔ | – | – | – |
| Teilnehmerliste sehen | – | ✔ (wie im Embed) | ✔ | ✔ | ✔ | ✔ |
| Event erstellen | – | nur mit Storyteller-Rolle | – | – | – | ✔ |
| Event bearbeiten | – | – | – | – | ✔ | ✔ |
| Teilnehmer entfernen oder verschieben (Warteliste) | – | – | – | – | ✔ | ✔ |
| Event löschen | – | – | – | – | ✔ | ✔ |
| Entwürfe sehen | – | – | – | – | nur eigene | – |
| Event eines anderen Erstellers übernehmen | – | – | – | – | – | ✔ |

Die Spalten sind kumulativ zu lesen, wo es passt: Ein Ersteller ist auch Mitglied und kann sich bei fremden Events anmelden.

Grundsätze:
- **Standard ist „verboten“**: Jede Route prüft ausdrücklich `can(user, action, event)` aus `events/permissions.py`. Diese
  Funktion nutzen auch die Buttons im Discord, damit beide Oberflächen dieselben Regeln haben.
- **Kein Zugriff über erratbare IDs**: Eine URL wie `/events/123/edit` prüft immer die Rolle. Wer keine Rechte hat,
  bekommt 404 statt 403, damit nicht einmal die Existenz fremder Entwürfe sichtbar wird.
- **Guild-Grenze**: Ein Event ist nur für Mitglieder der Guild sichtbar, in der es gepostet ist. Gäste sehen nur die
  Login-Seite.
- Änderungen über Formulare (POST) brauchen ein CSRF-Token.
- **Audit-Log**: Jede Änderung wird mit User, Rolle, Zeit und geänderten Feldern in `event_log` gespeichert. So lassen sich
  Änderungen durch das Event-Team nachvollziehen, und dem Ersteller kann eine DM „X hat dein Event geändert“ geschickt werden.

### Folgen für die früheren Phasen

Damit die Website später ohne Umbau drauf passt, gilt schon ab Phase 1:
- `storyteller` und `co_storyteller` speichern eine **Discord-User-ID** (wenn bekannt) und zusätzlich den Anzeigenamen.
  Der Co-ST bekommt dadurch keine Rechte; die ID dient der Anzeige („Meine Events“) und künftigen Erinnerungen.
  Der Co-ST wird als **einfacher Text** eingegeben, ohne Mitgliedersuche (Dalyan, 20.10.2026: „zu umständlich“);
  eine User-ID gibt es dann nur für den Storyteller, wenn er der Ersteller ist.
- RSVPs als eigene Tabelle (`event_id`, `user_id`, `display_name`, `status`, `created_at`) statt Listen im Event. So geht die Warteliste
  nach Anmeldezeit.
- `events/permissions.py` gibt es schon in Phase 2 und 3, für `/botc` und die Buttons „Bearbeiten“ und „Löschen“.

### Seiten (Phase 7)

- **Übersicht der Guild**: kommende Events wie im Discord, mit Filtern (Level, Skript, Label).
- **Meine Events**: als Ersteller oder ST, als Teilnehmer, und meine Entwürfe.
- **Event-Detail**: Embed-Inhalt, Teilnehmer, eigene Anmeldung.
- **Event erstellen / bearbeiten**: ein Formular mit allen Feldern und derselben Validierung wie der Wizard. Ein Entwurf aus
  dem Wizard lässt sich hier fortsetzen und umgekehrt.
- **Teilnehmer verwalten** (Ersteller, Event-Team): entfernen, von der Warteliste nachrücken lassen.

## Architektur

```
bot.py                    startet Bot + Webserver
events/                   gemeinsamer Kern, ohne Discord- und Web-Code
  schema.py               Feldschema, Defaults, Validierung
  parse.py                Datum/Uhrzeit-Parser
  templates.py            Titel- und Beschreibungsvorlagen, Emoji-Präfix
  store.py                SQLite: events, drafts, rsvps, event_log, event_reminders
  permissions.py          can(user, action, event): Storyteller-Rolle, Event-Team, Ersteller
  service.py              create / update / publish / delete — von Wizard und Web genutzt
  rating.py               Client für ScriptRater /api/analyse, Basis-3 fest
discord_ui/
  modal.py                /botc-Modal
  wizard.py               DM-Wizard (Schritte als Klassen, ein state-Feld)
  event_view.py           RSVP, Bearbeiten, Löschen (aus event-creation)
web/
  app.py, auth.py, routes.py, templates/, static/
logic/                    aus event-creation übernommen: botcscripts.py, script_cache.py,
                          script_image.py (nur Plain White), event_builder.py
commands/                 overview/settings (main, + /set_event_roles), reminder.py (aus event-creation)
```

Speicherung: SQLite unter `RAILWAY_VOLUME_MOUNT_PATH`. Railway-Deploy wird vom `worker` zum `web`-Prozess (braucht
`$PORT` und den Healthcheck `/health`).

Neue Umgebungsvariablen: `ALLOWED_GUILD_IDS`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `WEB_BASE_URL`, `SESSION_SECRET`,
`SCRIPT_RATER_URL` (inkl. Präfix: `https://widow-botc.com/script-check`; liegen Bot und ScriptRater im selben
Railway-Projekt, geht es auch über das private Netzwerk).

## Phasen

0. **Branch und Plan** (diese Datei). ✅
1. **Kern**: Schema, Parser, Vorlagen, SQLite-Store (events, drafts, rsvps, event_log), Service. Module ohne KI aus
   `event-creation` übernehmen. Server-Lock (`ALLOWED_GUILD_IDS`, Guild-Sync, `interaction_check`, `on_guild_join`).
   Tests ohne Discord. ✅ (19.10.2026, siehe „Stand Phase 1“)
2. **Rollen und Modal**: `/set_event_roles`, `/see_event_roles`, `/set_academy_access`, Rechteprüfung in `/botc`, Modal
   und Start des Wizards. ✅ (19.10.2026, siehe „Stand Phase 2“)
3. **Wizard** Schritte 1–6, Veröffentlichen, Bearbeiten über den Button am Event, Entwürfe, `events/permissions.py`.
   Reminder neu auf der Datenbank, mit `/set_reminders`, `/see_reminders` und Anpassung je Event.
   ✅ (19.10.2026, siehe „Stand Phase 3“)
4. **Einschätzung** über den ScriptRater, Fallback manuell. ✅ (mit Phase 3 erledigt)
5. **Deploy Bot**: Volume, Umgebungsvariablen, Test auf dem Server.
6. **Betrieb und Feedback**: Wizard im Alltag nutzen und nachschärfen, bevor die Website darauf aufbaut.
7. **Website** (zuletzt): Rechtemodell umsetzen und testen, Login, Seiten, Sync nach Discord. Deploy als `web`-Prozess
   (`$PORT`, Healthcheck `/health`), Subdomain in Cloudflare (CNAME) und Railway, OAuth-Redirect, `SESSION_SECRET`.

## Stand Phase 1 (19.10.2026)

Gebaut:
- `events/schema.py` (Felder, Defaults, Validierung), `events/parse.py` (Datum/Uhrzeit), `events/templates.py`
  (Titel, Beschreibung, Emoji-Präfix, Academy-Text), `events/permissions.py` (`can()`), `events/guild_lock.py`,
  `events/store.py` (SQLite), `events/service.py` (Entwürfe, Veröffentlichen, Bearbeiten, Löschen, RSVP, Aufräumen).
- Aus `event-creation` übernommen: `logic/botcscripts.py`, `logic/script_cache.py`, `logic/script_image.py`,
  `logic/event_builder.py`, `static/` (Charaktere, Jinxes, Basis-Skripte, Fonts, Thumbnails, `character_rating.json`).
- `script_image.py` kann nur noch das Papier-Design (vorher war Plain White der Default). Die Papier-Textur liegt jetzt
  unter `static/images/paper_texture.jpg`, weil `images/` per `.gitignore` nie deployt wurde. Behoben: Version und
  Autor überlappten im Kopf des Bildes.
- `event_builder.py` auf das neue Schema umgebaut: Namen als Text (Markdown-escaped, optional aktueller Name über
  `name_for`), NPCs und Highlights wieder aktiv, lange Teilnehmerlisten enden mit „… und N weitere“.
- `static/base_scripts.json`: `pithaag` → `pithag`, `eviltwins` → `eviltwin` (Fehler, den der ScriptRater gefunden hatte).
- Homebrew ist ein eigenes Merkmal (`is_homebrew`) zusätzlich zum Rating, wie im alten Code und im ScriptRater.
- Server-Lock in `bot.py` und in den Listenern von `commands/overview.py`.
- Neue Server-Einstellungen (Rollen, später Reminder) liegen in SQLite (`guild_settings`), nicht in `config.json`:
  `cleanup_config()` löscht dort beim Start jeden unbekannten Key.
- 98 neue Tests (`tests/test_parse.py`, `test_schema_templates.py`, `test_permissions.py`, `test_service.py`,
  `test_event_builder.py`), alle grün.

Noch nicht verdrahtet (Phase 2/3): Der Store wird in `bot.py` noch nicht erzeugt, `/botc` gibt es noch nicht.
Für Phase 3 merken: Die Charakter-Icons lädt `update_characters_from_tpi()` aufs Volume; in `event-creation` hing das an
einem Command in `commands/settings.py`, der noch übernommen werden muss.

## Stand Phase 2 (19.10.2026)

Gebaut:
- `commands/event_settings.py`: `/set_event_roles` (Storyteller- und Event-Team-Rolle, `entfernen`),
  `/set_academy_access` (Rollen und Mitglieder hinzufügen/entfernen), `/see_event_roles`. Nutzen dürfen sie Event-Team
  und Admins; **die Event-Team-Rolle selbst ändern nur Admins** (sonst könnte das Team die Rolle beliebig umhängen).
- `commands/botc.py`: `/botc` prüft Storyteller-Recht und Event-Channel, bietet bei offenem Entwurf „Weitermachen“ oder
  „Neu beginnen“ an und öffnet sonst das Modal.
- `discord_ui/botc_modal.py`: Modal mit fünf Feldern; die Academy-Checkbox sehen nur Berechtigte. Bei einem
  Eingabefehler kommt die Meldung mit Button „Nochmal“, der das Modal mit den alten Eingaben öffnet. Nach dem Absenden
  zeigt eine ephemere Antwort den erkannten Termin, der Wizard kommt per DM. Sind DMs zu, bleibt der Entwurf gespeichert.
- `discord_ui/wizard.py`: Gerüst des DM-Wizards. Buttons sind `DynamicItem`s (`wiz:<draft_id>:<aktion>[:<arg>]`) und
  funktionieren nach einem Neustart weiter; neue Schritte registrieren Aktionen mit `@action`. Bisher: Zusammenfassung
  und „Abbrechen“, die Schritte 1–6 folgen in Phase 3.
- `events/intake.py`: Modal-Eingaben → EventData (testbar ohne Discord).
- Pro User und Server gibt es höchstens einen Entwurf für ein neues Event; ein neuer ersetzt den alten.
- `bot.py` erzeugt den Store (`bot.store`) und registriert die Wizard-Buttons.
- Tests: `tests/test_intake.py`, `tests/test_discord_wiring.py` (Cogs laden, Modal bauen, custom_id), insgesamt 189 grün.

Nicht getestet: ein echter Durchlauf in Discord. Dafür braucht es den Bot mit `ALLOWED_GUILD_IDS` auf einem Test-Server.

## Stand Phase 3 und 4 (19.10.2026)

Gebaut:
- `discord_ui/wizard.py`: alle sechs Schritte plus Unterseite „Erinnerungen“. Die Wizard-Nachricht wird bei jedem
  Klick bearbeitet; Texteingaben laufen über Modals (Suche, JSON-Upload, Beschreibung, Bild-Upload).
  Zwischenstände (Suchergebnisse, Kandidaten) liegen in `drafts.ui`.
- Skript: Basis-3, freie Wahl, botcscripts.com-Suche (10 Treffer im Select) mit Versionswahl, JSON-Upload. Das
  Skript-JSON wird im Event gespeichert (Bild, Homebrew-Namen, Reminder ohne Netz).
- `events/rating.py`: ScriptRater `/api/analyse` (live geprüft), Basis-3 fest, sonst manuell. Gelesen werden nur
  `rating`, `headline`, `reasons`, `metrics.is_homebrew`/`is_amnesiac`.
- `discord_ui/event_post.py`: Event-Post mit RSVP-Buttons (weiße Custom-Emojis, Academy: 👼), Bearbeiten (DM-Wizard
  startet in der Vorschau) und Löschen mit Bestätigung. Bilder hängen als `event_image.png`/`thumbnail.png` an;
  Anmeldungen bauen nur das Embed neu und verweisen per `attachment://` auf sie.
- `logic/event_images.py`: eigenes Bild wird geprüft und als PNG auf dem Volume gespeichert (Discord-Links laufen ab),
  erzeugte Skript-Bilder werden zwischengespeichert.
- `events/reminders.py` + `commands/reminder.py`: Reminder wie geplant; Schleife jede Minute, Thread am Event-Post,
  Pings nur an User (nie @everyone/Rollen), lange Ping-Listen werden geteilt. Aufräumen stündlich.
- `/update_characters` (aus `event-creation` übernommen, nur Bot-Owner); beim ersten Start ohne Icons lädt der Bot
  sie automatisch.
- `/set_event_channel` und `/set_overview_channel` brauchen jetzt „Server verwalten“ (vorher durfte das jedes Mitglied).
- Die Übersicht von `main` liest die neuen Event-Posts weiterhin (Felder „Termin“ und „Akzeptiert (n/m)“).

Gefunden und behoben:
- botcscripts: `/api/scripts/<id>/` erwartet den internen `pk`; mit der Skript-ID kam ein anderes Skript zurück (173 →
  „Rise of The Outsiders“ statt Boozling). Der alte Reminder hätte oft das falsche Skript-JSON gepostet. Jetzt über
  `/script/<id>/<version>/download`.
- Veröffentlichen ohne Event-Channel hätte ein Event in der Datenbank angelegt, das nie gepostet wird.

Tests: 229 grün, darunter ein kompletter Durchlauf mit Discord-Attrappen (`tests/test_wizard_flow.py`) und jeder
Schritt gegen die Discord-Grenzen (`tests/test_wizard.py`). Ein echter Durchlauf in Discord steht noch aus.

## Umbau nach dem ersten Test (20.10.2026)

Feedback von Dalyan nach dem ersten echten Durchlauf in Discord:
- **Ablauf**: Skript → Einschätzung → Beschreibung → Bild → Zusammenfassung. Standardwerte (Dauer, Kamera, Co-ST,
  Labels, Erinnerungen) werden nicht abgefragt, sondern nur in der Zusammenfassung über „Feld ändern“ geändert.
  Der Schritt „Leitung & Details“ ist entfallen.
- **Zusammenfassung** wie auf `event-creation`: nummerierte Felder 1–13, Werte in Code-Blöcken, Einschätzung als Zitat
  neben dem Skript, Skript-Bild unten. „Feld ändern“ öffnet je nach Feld einen Schritt (Skript, Einschätzung, Bild,
  Erinnerungen) oder ein kurzes Modal (Beschreibung; Storyteller & Co-ST; Datum, Uhrzeit, Dauer, Spieler, Level;
  Labels & Kamera). Ein unveränderter Termin bleibt erhalten, auch wenn er schon vorbei ist.
- **Co-ST** als Freitext, keine Mitgliedersuche mehr.
- **Academy** nur mit Freigabe (siehe „Rollen und Berechtigungen“).
- **Skript-Bild** Plain White; dauert 0,8 statt ~8 Sekunden (die Wartezeit wirkte wie ein Hänger).
- Behoben: `restore_auto_tasks` stürzte bei Altlasten auf oberster Ebene von `config.json` ab.

Zweite Runde Feedback (20.10.2026):
- Die nummerierte Zusammenfassung steht auf **jeder** Wizard-Seite oben, darunter der aktuelle Schritt. Nicht gefüllte
  Pflichtfelder zeigen „offen“; Veröffentlichen bleibt gesperrt, solange die Beschreibung fehlt (Button + Service).
- **Titel bearbeitbar** (`EventData.title`, „1 · Titel“): leer = automatisch „{Skript} mit {ST}“; die Symbole kommen
  immer davor.
- **Schwierigkeit selbst einstellbar** mit sechs Optionen: 💚, 🟡, 🟥 und die Bereiche 💚/🟡, 🟡/🟥, 💚/🟡/🟥
  (`RATING_GREEN_YELLOW`, `RATING_YELLOW_RED`, `RATING_ANY`). Freie Skriptwahl startet mit 💚/🟡/🟥. Bei Academy sind
  alle Stufen des Bereichs fett, „hier N“ nennt die höchste Rundenzahl.
- **Einschätzungstext**: Der ScriptRater erzeugt einen Fließtext (`explain.verdict_reason`), liefert ihn über
  `/api/analyse` aber nicht aus. Der Bot liest ein optionales Feld `verdict` und zeigt es statt der Kriterienliste,
  sobald der ScriptRater es liefert (Prompt für das ScriptRater-Projekt ging an Dalyan).

## Offene Fragen

- Academy-Berechtigung im Detail (z. B. Verhältnis zur Storyteller-Rolle). Kann später geklärt werden.

- ScriptRater: Vorschlag, im ScriptRater einen Test für das Antwortformat von `/api/analyse` anzulegen (siehe oben,
  der Bot fällt bei unlesbarer Antwort auf manuelle Einschätzung zurück).
