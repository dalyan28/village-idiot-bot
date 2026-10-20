"""Texte für den Testserver. Stil wie Dalyan: kurz, locker, direkt, duzen, keine Gedankenstriche.

Platzhalter wie {feedback} oder {chat} werden durch Channel-Links ersetzt (Keys aus server.CATEGORY_PLAN).
Willkommen und Features stehen nacheinander im Willkommens-Channel. Die Posts kommen vom Bot,
sind aber Nachrichten von Dalyan; das steht als erste Zeile drüber (FROM_DALYAN).
"""

FROM_DALYAN = "-# Nachricht von Dalyan"
RATER_URL = "https://widow-botc.com/script-check"  # Link zum ScriptRater, erste Erwähnung im Willkommenstext

WELCOME = FROM_DALYAN + """
**Hey, schön dass ihr da seid.**
Nachdem sich Apollo verändert hat, haben wir beschlossen, einen eigenen Bot für die Event-Erstellung zu schreiben. Daran sitze ich schon eine ganze Weile (daher kam übrigens auch der [Widow ScriptRater]({rater_url}), mein Tool zum Einstufen von Skripten). Jetzt bin ich bei ungefähr 95 % und würde mich sehr freuen, wenn ihr mit mir drüberschaut und mir ehrlich Feedback gebt. Ich bin da komplett schmerzbefreit und hänge an nichts. Alles darf sich ändern.

**Commands**
`/botc` neue Runde anlegen. Wie der Rest funktioniert, seht ihr dann schon.
`/testserver beispiel-event` ein volles Beispiel-Event mit 23 erfundenen Anmeldungen posten

Die Testserver-Commands braucht ihr in der Regel nicht, die sind eher für mich:
`/testserver reset` Event-Channel leeren, alle Runden und Entwürfe weg
`/testserver setup` Channels und Texte hier auffrischen
`/testserver update` die Texte im aktuellen Channel auffrischen
`/testserver delete_all` löscht alle Channels, Rollen und Runden hier. Bitte nicht benutzen, das brauche ich nur, um am Ende alles zu wipen. Kaputt machen könnt ihr damit aber nichts: Mit `/testserver setup` ist der Server wieder eingerichtet. Und schlau wie ich war, wird der Feedback-Channel nicht gelöscht.

**Channels**
{events} hier landen die Runden
{overview} hier landet der Wochenplan
{feedback} hier landet euer Feedback. An jeder Karte im Bot und an jedem Post gibt's dafür den Button **Feedback**, ihr könnt aber auch direkt reinschreiben.
{texts} die Texte, die der Bot schickt, zum Gegenlesen
{chat} zum Yappen

Was schon drin ist und was noch offen ist, steht hier drunter.

Vielen Dank für eure Hilfe."""

FEATURES = FROM_DALYAN + """
**Was schon drin ist**

**Event-Ersteller**
Mit `/botc` geht's los, wie das genau funktioniert, könnt ihr gerne selbst erforschen. Angefangene Entwürfe bleiben 24 Stunden gespeichert. Runden anlegen darf die Storyteller-Rolle, alle Runden verwalten darf das Event-Team. Admins dürfen natürlich immer alles. Die Rollen könnt ihr selbstverständlich frei wählen und benennen, es geht nur darum, dass sich diese Rechte an eine Rolle binden lassen (`/set_event_roles`).

**Skripte und Schwierigkeit**
botcscripts.com ist direkt angebunden, ihr könnt Skripte dort suchen und die Version wählen. Außerdem gehen die Basis-Skripte, freie Skriptwahl oder ein eigenes JSON. Die Schwierigkeit kommt vom ScriptRater und lässt sich jederzeit überschreiben. Uns ist ja schon aufgefallen, dass der ScriptRater noch nicht perfekt ist. Da arbeite ich dran, das ist aber ein etwas größeres Projekt. Homebrew, Lorics und ähnliche Abweichungen erkennt der Bot und setzt ⭐. Teensyville erkennt er auch und stellt die Spielerzahl auf 6.

**Skript-Bilder**
Aus jedem Skript, auch einem hochgeladenen, baut der Bot automatisch ein Bild für den Post. Das Design ist noch nicht final, aber ich bin happy genug damit, dass ich es schon rausgeben würde. Feedback dazu gern, ich bin kein Designer (auch wenn ich es ein paar Semester studiert hab, lol).

**Academy**
Die Option Academy sieht beim Anlegen nur, wer die Freigabe hat. Hier auf dem Testserver habt ihr volle Rechte, deshalb seht ihr alles. Bei Academy ist schon eine Beschreibung vorausgefüllt. Dafür hab ich die Vorlage genommen, die mal im Umlauf war, die kann man aber ändern. Statt Vorläufig gibt es Auffüller.

**Der Post**
Die Pflichtangaben, die bisher in der Beschreibung stehen, sind jetzt eigene Felder, und der Bot füllt sie aus dem Dialog. Die Farbe am Rand richtet sich nach der Schwierigkeit.
-# Zum Nachdenken: Brauchen wir all diese Felder? Und brauchen wir den Absagen-Button überhaupt, was bringt der eigentlich?

**Erinnerungen**
15 Minuten vor Start macht der Bot einen Thread am Post auf, pingt alle an, wie ihr es von Apollo kennt, und postet für den Storyteller das Skript als JSON und die Anwesenheitsliste als TXT zum Abhaken.

**Wochenplan**
Rückwärtskompatibel mit Apollo. Fällt einer der beiden Bots aus, kann man einfach den anderen nehmen.

**Was noch offen ist**
**Storyteller-Briefings**: Briefing mit einem Klick aus fester Vorlage, kommt auf jeden Fall noch
**Meine Runden**: sehen, wo man angemeldet ist, und direkt umstellen
**Server-Insider**: Srunden und Trunden automatisch nach Startzeit erkennen und in den Titel packen
**Streaming**: als Option mit Hinweis in der Beschreibung (für unsere Twitch-Streamer). Vielleicht wäre ein Emoji dafür cooler, als groß „Streaming“ hinzuschreiben.
**Website** (optional, fänd ich aber cool): Runden auch über die Widow-Website anlegen und verwalten, synchron mit Discord. Was ihr dort ändert, steht sofort im Post und umgekehrt."""

CHAT_INTRO = FROM_DALYAN + """
Unser allgemeiner Chat. Hier können wir uns über alles Mögliche unterhalten."""

FEEDBACK_INTRO = FROM_DALYAN + """
Hier landet alles, was über den Button **Feedback** reinkommt. Ihr könnt auch direkt hier schreiben. Screenshots sind immer sehr gern gesehen.\
"""

# Antworten der Commands
NOT_A_TEST_SERVER = "Das geht nur auf einem Testserver. Dieser Server steht nicht in `TEST_GUILD_IDS`."
ADMINS_ONLY = "Das dürfen nur Admins (Server verwalten)."
SETUP_RUNNING = "Ich richte den Server ein …"
UPDATE_RUNNING = "Ich aktualisiere die Texte in diesem Channel …"
UPDATE_NO_TEXTS = "In diesem Channel gibt es keine festen Texte. Ruf den Command in dem Channel auf, den du auffrischen willst."
SAMPLE_RUNNING = "Ich poste ein Beispiel-Event …"
RESET_RUNNING = "Ich räume den Event-Channel auf …"
DELETE_CONFIRM = ("Damit fliegen alle Channels, Rollen, Runden, Entwürfe und die Bot-Einstellungen für diesen "
                  "Server raus. Nur der Feedback-Channel bleibt. Sicher?")
DELETE_RUNNING = "Ich räume alles weg …"
DELETE_CANCELLED = "Okay, bleibt alles da."
NOT_YOUR_BUTTON = "Das ist nicht deine Abfrage."
