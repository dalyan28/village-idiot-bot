# Village Idiot Bot

Ein Discord-Bot, der Events aus einem Apollo-Bot-Channel ausliest und automatisch eine Übersicht postet.

---

## Deutsch

### Voraussetzungen

- Python 3.10+
- Ein Discord-Bot-Token ([Discord Developer Portal](https://discord.com/developers/applications))
- Der Bot muss auf dem Server eingeladen sein mit folgenden Berechtigungen:
  - Nachrichten senden
  - Nachrichten verwalten
  - Nachrichtenverlauf anzeigen
  - Kanäle ansehen

### Installation

```bash
git clone https://github.com/dalyan28/village-idiot-bot.git
cd village-idiot-bot
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux
pip install -r requirements.txt
```

`.env` Datei anlegen:
```
DISCORD_TOKEN=dein_token_hier
```

Bot starten:
```bash
python bot.py
```

Dev-Modus (Test-Commands aktivieren):
```
ENV=dev
```

### Projektstruktur

```
village-idiot-bot/
├── bot.py                      # Einstiegspunkt
├── config.py                   # Config laden/speichern/bereinigen
├── commands/
│   ├── settings.py             # /set_event_channel, /set_overview_channel
│   ├── overview.py             # /overview_events, /automate_overview, /stop_automate
│   └── test_commands.py        # Dev-only: /create_test_event, /clear_test_events,
│                               #   /clear_past_events
├── logic/
│   └── parser.py               # Apollo-Nachrichten parsen & Übersicht bauen
├── tests/
│   └── test_overview_logic.py  # Unit-Tests (pytest)
├── requirements.txt
├── requirements-dev.txt        # + pytest
├── .env                        # nicht in Git
└── config.json                 # wird automatisch erstellt, nicht in Git
```

### Commands

| Command | Parameter | Beschreibung |
|---|---|---|
| `/set_event_channel` | `channel` | Setzt den Channel, aus dem Apollo-Events ausgelesen werden |
| `/set_overview_channel` | `channel` | Setzt den Channel, in dem die Übersicht gepostet wird |
| `/overview_events` | `channel` (optional) | Postet die aktuelle Übersicht manuell |
| `/automate_overview` | `event_channel` (optional), `overview_channel` (optional) | Startet die automatische Übersicht (Listen-Modus) |
| `/stop_automate` | – | Stoppt die laufende automatische Übersicht |

### Automatische Übersicht (Listen-Modus)

Die Übersicht aktualisiert sich nur, wenn sich im Event-Channel etwas tut, und sonst nie:

- **Neues Event:** Die alte Übersicht wird gelöscht und unten im Channel neu gepostet.
- **Bearbeitung, An- oder Abmeldung, gelöschtes Event:** Die Übersicht wird an Ort und Stelle bearbeitet. Mehrere Änderungen kurz hintereinander werden zusammengefasst (5 bis höchstens 15 Sekunden).

Die Automatik bleibt über Neustarts erhalten. `/testserver setup` schaltet sie auf Testservern gleich mit ein.

### Tests

Unit-Tests ausführen:
```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

### Hinweise

- Der Bot löscht beim automatischen Update nur seine eigene zuletzt gepostete Übersicht, nie andere Nachrichten
- Apollo-Events müssen als Embeds mit einem `Time`- oder `Termin`-Feld vorliegen
- Die Übersicht zeigt Tagesnamen und Monate immer auf Deutsch an
- `.env` und `config.json` niemals in Git committen

---

## English

### Requirements

- Python 3.10+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- The bot must be invited to the server with the following permissions:
  - Send Messages
  - Manage Messages
  - Read Message History
  - View Channels

### Installation

```bash
git clone https://github.com/dalyan28/village-idiot-bot.git
cd village-idiot-bot
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux
pip install -r requirements.txt
```

Create a `.env` file:
```
DISCORD_TOKEN=your_token_here
```

Start the bot:
```bash
python bot.py
```

Dev mode (enables test commands):
```
ENV=dev
```

### Commands

| Command | Parameter | Description |
|---|---|---|
| `/set_event_channel` | `channel` | Sets the channel from which Apollo events are read |
| `/set_overview_channel` | `channel` | Sets the channel where the overview will be posted |
| `/overview_events` | `channel` (optional) | Manually posts the current overview |
| `/automate_overview` | `event_channel` (optional), `overview_channel` (optional) | Starts the automated overview (listen mode) |
| `/stop_automate` | – | Stops the running automated overview |

### Automated overview (listen mode)

The overview only updates when something happens in the event channel, never on a timer:

- **New event:** the old overview is deleted and reposted at the bottom of the channel.
- **Edit, sign-up or cancellation, deleted event:** the overview is edited in place. Several changes in quick succession are batched (5 to at most 15 seconds).

The automation survives restarts.

### Notes

- The bot only deletes its own last posted overview, never other messages
- Apollo events must be posted as embeds with a `Time` or `Termin` field
- Never commit `.env` or `config.json` to Git
