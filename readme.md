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

### Projektstruktur

```
village-idiot-bot/
├── bot.py              # Einstiegspunkt
├── config.py           # Config laden/speichern
├── commands/
│   ├── settings.py     # /set_event_channel, /set_overview_channel
│   └── overview.py     # /overview_events, /automate_overview, /stop_automate
├── logic/
│   └── parser.py       # Apollo-Nachrichten parsen & Übersicht bauen
├── requirements.txt
├── .env                # nicht in Git
└── config.json         # wird automatisch erstellt, nicht in Git
```

### Commands

| Command | Parameter | Beschreibung |
|---|---|---|
| `/set_event_channel` | `channel` | Setzt den Channel, aus dem Apollo-Events ausgelesen werden |
| `/set_overview_channel` | `channel` | Setzt den Channel, in dem die Übersicht gepostet wird |
| `/overview_events` | `channel` (optional) | Postet die aktuelle Übersicht. Priorität: angegebener Channel → set_overview_channel → aktueller Channel |
| `/automate_overview` | `frequenz`, `event_channel` (optional), `summary_channel` (optional) | Postet die Übersicht automatisch im gewählten Intervall und löscht die vorherige. Channel-Parameter überschreiben die gesetzten Werte aus `/set_event_channel` und `/set_overview_channel` |
| `/stop_automate` | – | Stoppt alle laufenden automatischen Übersichten |

**Verfügbare Intervalle für `/automate_overview`:**
- 3 Sekunden (nur zum Testen)
- 2 / 4 / 8 / 12 / 24 Stunden

### Hinweise

- Der Bot löscht beim automatischen Update nur seine eigene zuletzt gepostete Übersicht, nie andere Nachrichten
- Apollo-Events müssen als Embeds mit einem `Time`- oder `Termin`-Feld vorliegen, damit der Parser sie erkennt. Es werden nur Apollo-Events unterstützt, die auf Deutsch oder Englisch erstellt wurden.
- Die Übersicht zeigt Tagesnamen und Monate immer auf Deutsch an, unabhängig von der Sprache des Servers.
- `.env` und `config.json` niemals in Git committen. Sie können sensible Daten enthalten. Wenn die Token-ID jemals bei Git exposed werden sollte, dringend eine neue ID generieren.

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

### Project Structure

```
village-idiot-bot/
├── bot.py              # Entry point
├── config.py           # Load/save config
├── commands/
│   ├── settings.py     # /set_event_channel, /set_overview_channel
│   └── overview.py     # /overview_events, /automate_overview, /stop_automate
├── logic/
│   └── parser.py       # Parse Apollo messages & build overview
├── requirements.txt
├── .env                # not in Git
└── config.json         # auto-generated, not in Git
```

### Commands

| Command | Parameter | Description |
|---|---|---|
| `/set_event_channel` | `channel` | Sets the channel from which Apollo events are read |
| `/set_overview_channel` | `channel` | Sets the channel where the overview will be posted |
| `/overview_events` | `channel` (optional) | Posts the current overview. Priority: given channel → set_overview_channel → current channel |
| `/automate_overview` | `frequency`, `event_channel` (optional), `summary_channel` (optional) | Automatically posts the overview at the chosen interval and deletes the previous one. Channel parameters override the values set via `/set_event_channel` and `/set_overview_channel` |
| `/stop_automate` | – | Stops all running automated overviews |

**Available intervals for `/automate_overview`:**
- 3 seconds (testing only)
- 2 / 4 / 8 / 12 / 24 hours

### Notes

- The bot only deletes its own last posted overview, never any other messages
- Apollo events must be posted as embeds with a `Time` or `Termin` field for the parser to detect them. Only Apollo events created in German or English are supported.
- The overview always displays day names and months in German, regardless of the server language.
- Never commit `.env` or `config.json` to Git. They may contain sensitive data. If the token is ever exposed in Git, generate a new one immediately.