# Gold Signal Bot  |  XAU/USD

Live trading signals for Gold using 1-minute candles. BUY/SELL alerts go to Discord. Trades are tracked with take profit and stop loss. Includes a strategy editor and backtester.

---

## One-liner install

If you already have Python installed, open a terminal in this folder and run:

```
python setup.py
```

That installs all packages, creates a desktop shortcut, and optionally launches the app — one command, done.

---

## Installing Python first (if you do not have it)

1. Go to **https://www.python.org/downloads/**
2. Click Download Python
3. Run the installer
4. Tick **"Add Python to PATH"** — this step is required
5. Click Install Now

Then run `python setup.py` or double-click `install.bat`.

---

## Starting the app

- Desktop: double-click **Gold Signal Bot** (created by setup)
- Or: double-click `START_BOT.bat`
- Or: `pythonw app.py`

---

## App tabs

### Live

Control the bot from here.

- Pick a strategy from the dropdown
- Set Take Profit and Stop Loss in USD per ounce (e.g. TP = 10 means the trade closes when price moves $10 in your favour)
- Click Start — the bot checks for signals every 60 seconds
- The Active Trade panel shows the current open trade: entry price, TP level, SL level
- Click "Close Trade Now" to manually exit at the current price
- The log shows every action the bot takes

### Trades

Full history of every trade the bot has opened and closed.

Columns: Side, Entry, TP, SL, Exit, PnL, Reason, Open time, Close time.

Reason column values:
- `OPEN` — trade is still running
- `TP_HIT` — closed at take profit
- `SL_HIT` — closed at stop loss
- `REVERSED` — closed because the signal flipped
- `MANUAL` — you clicked Close Trade Now

### Strategy Editor

Write and save custom strategies. Each strategy is a Python file with one function:

```python
import pandas as pd

def generate_signal(df: pd.DataFrame) -> str | None:
    """
    df has columns: Open, High, Low, Close, Volume
    Last row = most recent candle.
    Return "BUY", "SELL", or None.
    """
    return None
```

Buttons:
- **Load** — load the selected strategy into the editor
- **Save** — overwrite the current file
- **Save As** — save with a new name
- **New** — blank template with a name you choose
- **Delete** — remove the strategy file

### Backtest

Test a strategy against historical data.

1. Pick strategy, symbol, date range, interval, TP and SL amounts
2. Click Run Backtest
3. Results show: Trades, Win Rate, Total PnL $, Max Drawdown $, Avg Trade $
4. Every simulated trade is listed in the table

Interval guide:
- `1d` — any date range, fastest
- `1h` — up to 60 days back
- `5m / 15m / 30m` — up to 60 days back
- `1m` — last 7 days only (Yahoo Finance limit)

### Settings

Change the Discord webhook, check interval, lookback candles, TP/SL defaults, and data interval. Click Save Settings.

---

## Built-in strategies

| File | Logic |
|---|---|
| `heikin_ashi.py` | BUY when Heikin Ashi candle flips from bearish to bullish. SELL on the reverse. |
| `ma_crossover.py` | BUY when the 10-period MA crosses above the 20-period MA. SELL on the reverse. |

---

## Take Profit and Stop Loss explained

Both values are in US dollars per troy ounce.

Example with TP = 10, SL = 5, BUY signal at $2,350:
- Take Profit level = $2,360 (trade closes with +$10 gain)
- Stop Loss level   = $2,345 (trade closes with -$5 loss)

For a SELL signal, the levels are mirrored.

---

## Discord alerts

The bot sends a message when a trade opens (entry, TP, SL) and another when it closes (exit price, PnL, reason).

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python is not recognized` | Reinstall Python, tick "Add to PATH" |
| App does not open | Open terminal in folder, run `python app.py`, read the error |
| No data / market closed | Gold futures trade Sun 6pm to Fri 5pm ET. Try GC=F during those hours. |
| Backtest returns 0 trades | Strategy may not generate signals on that date range. Try `1d` interval and a longer range. |

---

## Files

| File | Purpose |
|---|---|
| `app.py` | Desktop application |
| `engine.py` | Live bot engine and backtester |
| `notifier.py` | Discord alerts |
| `setup.py` | One-command installer and launcher |
| `config.json` | Settings |
| `trades.json` | Trade history (created automatically) |
| `strategies/` | Strategy plugin files |
| `install.bat` | Windows installer (calls setup.py) |
| `START_BOT.bat` | Launches the app |
