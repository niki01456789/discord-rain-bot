# Discord Rain Bot

Monitors crypto casino websites for "rain" bonus events and sends Discord notifications via webhooks with live countdown timers.

## How It Works

1. Opens each configured site in a headless browser (one tab, reused sequentially)
2. Detects rain via **websocket interception** (catches Socket.IO/WS events like `rainAmountUpdate`) and **DOM scanning** (looks for active rain phrases like "IT'S RAINING")
3. Sends a Discord embed with site link, amount, participants, and a live `<t:timestamp:R>` countdown
4. Skips duplicate alerts if rain is still ongoing on the next scan cycle
5. Logs all activity to `bot.log` (including site errors)

## Setup

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Chromium for Playwright
playwright install chromium

# 4. Create your config
cp config.example.yaml config.yaml
# Edit config.yaml — add your Discord webhook URL
```

## Configuration

Edit `config.yaml`:

```yaml
discord:
  webhook_url: "https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN"
  # Ping options:
  #   "@everyone"       - ping everyone
  #   "@here"           - ping online members
  #   "<@USER_ID>"      - ping specific user
  #   "<@&ROLE_ID>"     - ping specific role
  #   ""                - silent (no ping)
  ping: "@everyone"

scan_interval: 60  # seconds between scan cycles

sites:
  - url: "https://howl.gg"
    keywords: ["rain", "raining"]
  - url: "https://clash.gg"
    keywords: ["rain", "raining"]
  # Add more sites...
```

### Adding a New Site

Just add a new entry under `sites:` with the URL and keywords to scan for:

```yaml
  - url: "https://example-casino.com"
    keywords: ["rain", "raining", "bonus drop"]
```

## Running

```bash
source venv/bin/activate
python main.py
```

Stop with `Ctrl+C` (graceful shutdown).

## Getting a Discord Webhook URL

1. Open Discord, go to the channel where you want alerts
2. Click the gear icon (Edit Channel) > Integrations > Webhooks
3. Click "New Webhook", name it, copy the URL
4. Paste it in `config.yaml`

## Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point and scan loop |
| `scanner.py` | Headless browser management + WS capture |
| `detector.py` | Rain detection (websocket + DOM) |
| `notifier.py` | Discord webhook embed sender |
| `state.py` | Deduplication (tracks active rains) |
| `logger_setup.py` | Console + file logging |
| `config.yaml` | Your configuration (not committed) |
| `bot.log` | Runtime log file |

## Resource Usage

- ~150-200MB RAM (single Chromium tab)
- ~5-10 seconds per site per scan cycle
- Scales to ~10 sites per minute with default 60s interval
