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
│   ├── overview.py             # /overview_events, /automate_overview, /stop_automate,
│   │                           #   /set_schedule, /see_schedule
│   └── test_commands.py        # Dev-only: /create_test_event, /clear_test_events,
│                               #   /clear_past_events, /smart_status
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
| `/automate_overview` | `frequenz`, `event_channel` (optional), `overview_channel` (optional), `on_new_event` (optional, default: true), `dynamic` (optional, default: true) | Startet die automatische Übersicht |
| `/stop_automate` | – | Stoppt die laufende automatische Übersicht |
| `/set_schedule` | `zeiten` | Setzt den Smart-Mode-Zeitplan (z.B. `05:00 08:00 12:00`) oder `default` |
| `/see_schedule` | – | Zeigt den aktuellen Zeitplan und dynamische Zeiten |

**Verfügbare Modi für `/automate_overview`:**
- **Smart (automatisch)** – Intelligenter Zeitplan (empfohlen, siehe unten)
- 1 / 2 / 4 / 8 / 12 / 24 Stunden

### Smart Mode

Der Smart Mode aktualisiert die Übersicht nach einem intelligenten Zeitplan statt in einem festen Intervall:

**Standard-Zeitplan:** `05:00, 08:00, 12:00, 16:00, 18:00, 19:00, 19:30, 20:00, 22:00` (Berliner Zeit)

**Dynamische Zeiten:** Wenn ein Event für heute geplant ist, aktualisiert der Bot zusätzlich 30, 20 und 10 Minuten vor dem Eventstart automatisch.

**Regeln:**
- Feste Zeiten werden übersprungen, wenn das letzte Update weniger als 15 Minuten her ist (z.B. weil gerade ein neues Event gepostet wurde)
- Dynamische Zeiten werden nie übersprungen
- Bei neuem Event: sofortige Aktualisierung
- Bei gelöschtem Event: sofortige Aktualisierung

Mit `/set_schedule` kann der Zeitplan individuell angepasst werden.

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
| `/automate_overview` | `frequency`, `event_channel` (optional), `overview_channel` (optional), `on_new_event` (optional, default: true), `dynamic` (optional, default: true) | Starts automated overview posting |
| `/stop_automate` | – | Stops the running automated overview |
| `/set_schedule` | `times` | Sets the Smart Mode schedule (e.g. `05:00 08:00 12:00`) or `default` |
| `/see_schedule` | – | Shows the current schedule and dynamic times |

**Available modes for `/automate_overview`:**
- **Smart (automatic)** – Intelligent schedule (recommended, see below)
- 1 / 2 / 4 / 8 / 12 / 24 hours

### Smart Mode

Smart Mode updates the overview on an intelligent schedule instead of a fixed interval:

**Default schedule:** `05:00, 08:00, 12:00, 16:00, 18:00, 19:00, 19:30, 20:00, 22:00` (Berlin time)

**Dynamic times:** If an event is scheduled for today, the bot additionally updates 30, 20, and 10 minutes before the event start.

**Rules:**
- Fixed times are skipped if the last update was less than 15 minutes ago
- Dynamic times are never skipped
- New event posted: immediate update
- Event deleted: immediate update

### Notes

- The bot only deletes its own last posted overview, never other messages
- Apollo events must be posted as embeds with a `Time` or `Termin` field
- Never commit `.env` or `config.json` to Git
