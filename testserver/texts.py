"""Texte für den Testserver. Stil wie Dalyan: kurz, locker, direkt, duzen, keine Gedankenstriche.

Platzhalter wie {feedback} oder {chat} werden durch Channel-Links ersetzt (Keys aus server.CATEGORY_PLAN).
Willkommen und Features stehen nacheinander im Willkommens-Channel. Die Posts kommen vom Bot,
sind aber Nachrichten von Dalyan; das steht als erste Zeile drüber (FROM_DALYAN).
"""

FROM_DALYAN = "-# Nachricht von Dalyan"
RATER_URL = "https://widow-botc.com/script-check"  # Link zum ScriptRater, erste Erwähnung im Willkommenstext

WELCOME = FROM_DALYAN + """
**Hey, das ist der neue Event-Bot für unseren Discord.**
Mit `/botc` legt ihr ein neues Event an. Mit den Knöpfen unten könnt ihr außerdem Dinge ausprobieren, die sonst erst später oder nur bei anderen passieren, zum Beispiel Erinnerungen oder DMs.

Feedback gern über den Button **Feedback**, den ihr an jeder Karte findet, oder direkt in {feedback}. Vielen Dank fürs Mitmachen."""

# Test-Karte unter der Willkommensnachricht (testserver/test_card.py)
TEST_CARD = """**Ausprobieren**
**Event erstellen**
-# Startet `/botc`, falls ihr den Command nicht tippen wollt.
**[Dev] Beispiel-Event posten**
-# Postet in {events} ein Event mit 23 erfundenen Anmeldungen. So seht ihr volle Listen und die Warteliste.
**[Dev] Meine Events ansehen**
-# Zeigt, wie `/meine_events` aussieht, wenn man für mehrere Runden angemeldet ist. Mit dem Command seht ihr eure echten Anmeldungen und könnt euch direkt abmelden.
**[Dev] Doppelanmeldung testen**
-# Schickt euch die DM, die man 3 Stunden vor Beginn bekommt, wenn man für zwei Runden zur gleichen Zeit zugesagt hat.
**[Dev] Erinnerung ansehen**
-# Schickt euch die Erinnerung, die 15 Minuten vor Start im Thread unter dem Event kommt, mit Skript und Anwesenheitsliste.

-# Alles mit [Dev] nutzt erfundene Daten. Eure echten Anmeldungen bleiben unverändert, und niemand wird angepingt."""
TEST_SEE_DMS = "Schau in deine DMs."
TEST_DM_CLOSED = ("Ich kann dir keine DM schicken. Erlaube DMs von Servermitgliedern "
                  "(Servereinstellungen → Privatsphäre) und versuch es dann erneut.")
TEST_REMINDER_NOTE = ("-# Vorschau mit erfundenen Leuten: So sieht die Erinnerung im Thread unter dem Event aus. "
                      "Dort werden alle angepingt.")
TEST_MY_EVENTS_NOTE = "-# Vorschau mit erfundenen Runden. Deine echten Anmeldungen siehst du mit `/meine_events`."

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
