# Village Idiot Bot

Ein Discord-Bot, der Events aus einem Apollo-Bot-Channel ausliest und automatisch eine Übersicht postet.

---

## Deutsch

### Voraussetzungen

- Python 3.10+
- Ein Discord-Bot-Token ([Discord Developer Portal](https://discord.com/developers/applications))
- Tesseract OCR (lokal: [Windows Installer](https://github.com/UB-Mannheim/tesseract/wiki))
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

Unter Windows muss der Tesseract-Pfad in `logic/ocr.py` eingetragen werden:
```python
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
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
├── characters.json     # BotC-Charaktere mit Bewertungen
├── nixpacks.toml       # Tesseract-Installation für Railway
├── railway.toml        # Erzwingt Nixpacks auf Railway
├── commands/
│   ├── settings.py     # /set_event_channel, /set_overview_channel
│   └── overview.py     # /overview_events, /automate_overview, /stop_automate
├── logic/
│   ├── ocr.py          # Bildanalyse & Charaktererkennung
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
| `/overview_events` | `channel` (optional), `force_ocr` (optional, default: true) | Postet die aktuelle Übersicht. Priorität: angegebener Channel → set_overview_channel → aktueller Channel. Mit `force_ocr: true` werden alle Skript-Bilder neu analysiert. |
| `/automate_overview` | `frequenz`, `event_channel` (optional), `overview_channel` (optional), `on_new_event` (optional, default: true) | Postet die Übersicht automatisch im gewählten Intervall und löscht die vorherige. Mit `on_new_event` wird die Übersicht zusätzlich aktualisiert, wenn ein neues Event gepostet wird. |
| `/stop_automate` | - | Stoppt alle laufenden automatischen Übersichten |

**Verfügbare Intervalle für `/automate_overview`:**
- 3 Sekunden (nur zum Testen)
- 1 / 2 / 4 / 8 / 12 / 24 Stunden

### Charakterbewertungen (characters.json)

Jeder BotC-Charakter hat einen Score von 1-10, der beschreibt wie sehr er das Spielgeschehen beeinflusst. Die Top 4 Charaktere eines Skripts werden in der Übersicht unter dem jeweiligen Event angezeigt. Charaktere mit einem Score von 9 oder 10 werden fett und mit einem 🔹 hervorgehoben.

Die Datei kann manuell angepasst werden. Sie gehört in Git, da sie keine sensiblen Daten enthält.

### Hinweise

- Der Bot löscht beim automatischen Update nur seine eigene zuletzt gepostete Übersicht, nie andere Nachrichten
- Apollo-Events müssen als Embeds mit einem `Time`- oder `Termin`-Feld vorliegen, damit der Parser sie erkennt. Es werden nur Apollo-Events unterstützt, die auf Deutsch oder Englisch erstellt wurden.
- Die Übersicht zeigt Tagesnamen und Monate immer auf Deutsch an, unabhängig von der Sprache des Servers.
- OCR-Ergebnisse werden gecacht. Events ohne Skript-Bild werden bei jedem Update neu geprüft. Mit `force_ocr: true` kann der Cache manuell geleert werden.
- `.env` und `config.json` niemals in Git committen. Sie können sensible Daten enthalten. Wenn die Token-ID jemals bei Git exposed werden sollte, dringend eine neue ID generieren.

---

## English

### Requirements

- Python 3.10+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- Tesseract OCR (local: [Windows Installer](https://github.com/UB-Mannheim/tesseract/wiki))
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

On Windows, add the Tesseract path to `logic/ocr.py`:
```python
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
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
├── characters.json     # BotC characters with scores
├── nixpacks.toml       # Tesseract installation for Railway
├── railway.toml        # Forces Nixpacks on Railway
├── commands/
│   ├── settings.py     # /set_event_channel, /set_overview_channel
│   └── overview.py     # /overview_events, /automate_overview, /stop_automate
├── logic/
│   ├── ocr.py          # Image analysis & character detection
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
| `/overview_events` | `channel` (optional), `force_ocr` (optional, default: true) | Posts the current overview. Priority: given channel → set_overview_channel → current channel. Use `force_ocr: true` to re-analyse all script images. |
| `/automate_overview` | `frequency`, `event_channel` (optional), `overview_channel` (optional), `on_new_event` (optional, default: true) | Automatically posts the overview at the chosen interval and deletes the previous one. With `on_new_event` the overview is also updated when a new event is posted. |
| `/stop_automate` | - | Stops all running automated overviews |

**Available intervals for `/automate_overview`:**
- 3 seconds (testing only)
- 1 / 2 / 4 / 8 / 12 / 24 hours

### Character Scores (characters.json)

Each BotC character has a score from 1-10 describing how much they influence the game. The top 4 characters of a script are shown in the overview below each event. Characters with a score of 9 or 10 are highlighted in bold with a 🔹 emoji.

The file can be edited manually and belongs in Git as it contains no sensitive data.

### Notes

- The bot only deletes its own last posted overview, never any other messages
- Apollo events must be posted as embeds with a `Time` or `Termin` field for the parser to detect them. Only Apollo events created in German or English are supported.
- The overview always displays day names and months in German, regardless of the server language.
- OCR results are cached. Events without a script image are re-checked on every update. Use `force_ocr: true` to clear the cache manually.
- Never commit `.env` or `config.json` to Git. They may contain sensitive data. If the token is ever exposed in Git, generate a new one immediately.