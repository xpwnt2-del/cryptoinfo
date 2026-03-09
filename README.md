# CryptoInfo – AI-Powered Crypto Trading Bot

An AI-powered cryptocurrency trading bot with a web dashboard, automated trading,
and multi-exchange support.

---

## 🚀 Quick Start (Double-Click Launcher)

The easiest way to run the bot is with the platform-specific launcher scripts.
They automatically install dependencies, let you enter your API keys, and open
the dashboard in your browser.

| Platform | File to double-click |
|----------|----------------------|
| **Windows** | `run.bat` |
| **macOS** | `run.command` *(right-click → Open the first time if macOS blocks it)* |
| **Linux** | `run.sh` *(make executable once: `chmod +x run.sh`)* |

All three launchers open the same **graphical settings window** where you can:

- Choose your exchange (Binance, Coinbase, Kraken, Bybit, OKX) and enter API keys
- Optionally enter an OpenAI API key for AI-powered analysis
- Configure bot behavior (dry-run mode, check interval, confidence threshold, trade size)
- Save settings, start/stop the bot, and open the browser dashboard

> **Tip:** Leave the API keys blank (or enable *Dry Run*) to explore the dashboard
> without placing any real trades.

---

## Manual Setup (command line)

```bash
# 1. Install Python 3.9+ – https://www.python.org/downloads/
# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure settings
cp .env.example .env
# Edit .env with your API keys and preferences

# 4. Run the bot
python app.py
# Then open http://localhost:5000 in your browser
```

---

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `EXCHANGE_ID` | `binance` | Exchange: binance, coinbase, kraken, bybit, okx |
| `EXCHANGE_API_KEY` | *(empty)* | Exchange API key – leave blank for read-only mode |
| `EXCHANGE_SECRET` | *(empty)* | Exchange API secret |
| `OPENAI_API_KEY` | *(empty)* | OpenAI key – optional, enables GPT analysis |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model to use |
| `DRY_RUN` | `true` | `true` = simulate trades, no real orders |
| `BOT_INTERVAL` | `60` | Seconds between bot analysis cycles |
| `MIN_CONFIDENCE` | `70` | Minimum confidence (0–100) required to place a trade |
| `BOT_TRADE_AMOUNT` | `0.001` | Amount per trade in base currency units (e.g. BTC) |
| `PORT` | `5000` | Port the web dashboard listens on |

---

## Running Tests

```bash
pytest tests/
```
