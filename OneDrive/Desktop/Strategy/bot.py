"""
Heikin Ashi Trading Signal Bot
Monitors tickers using 1-minute candles and sends BUY/SELL signals to Discord.
"""

import json
import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime

# ── Load config ──────────────────────────────────────────────────────────────
with open("config.json") as f:
    config = json.load(f)

SYMBOLS          = config["symbols"]
INTERVAL         = config["interval"]
WEBHOOK_URL      = config["discord_webhook"]
CHECK_EVERY      = config["check_interval_seconds"]
LOOKBACK         = config["lookback_candles"]

# Track last signal per symbol so we don't spam
last_signal: dict[str, str] = {}   # "BUY" | "SELL" | None


# ── Heikin Ashi calculation ───────────────────────────────────────────────────
def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    ha = pd.DataFrame(index=df.index)

    ha["Close"] = (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4

    # First HA Open = midpoint of first real candle
    ha["Open"] = 0.0
    ha.iloc[0, ha.columns.get_loc("Open")] = (df["Open"].iloc[0] + df["Close"].iloc[0]) / 2
    for i in range(1, len(ha)):
        ha.iloc[i, ha.columns.get_loc("Open")] = (
            ha["Open"].iloc[i - 1] + ha["Close"].iloc[i - 1]
        ) / 2

    ha["High"] = pd.concat([df["High"], ha["Open"], ha["Close"]], axis=1).max(axis=1)
    ha["Low"]  = pd.concat([df["Low"],  ha["Open"], ha["Close"]], axis=1).min(axis=1)

    ha["Bullish"] = ha["Close"] > ha["Open"]
    return ha


# ── Signal detection ──────────────────────────────────────────────────────────
def detect_signal(ha: pd.DataFrame) -> str | None:
    """
    Returns 'BUY'  when the last candle flipped from bearish → bullish.
    Returns 'SELL' when the last candle flipped from bullish → bearish.
    Returns None   when no crossover happened.
    """
    if len(ha) < 2:
        return None

    prev_bull = ha["Bullish"].iloc[-2]
    curr_bull = ha["Bullish"].iloc[-1]

    if not prev_bull and curr_bull:
        return "BUY"
    if prev_bull and not curr_bull:
        return "SELL"
    return None


# ── Discord notification ──────────────────────────────────────────────────────
def send_discord(symbol: str, signal: str, ha_row: pd.Series, price: float) -> None:
    color   = 0x00FF88 if signal == "BUY" else 0xFF4444
    emoji   = "🟢" if signal == "BUY" else "🔴"
    action  = "**BUY  ↑**" if signal == "BUY" else "**SELL ↓**"
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    embed = {
        "title": f"{emoji} {signal} — {symbol}",
        "description": (
            f"{action}\n"
            f"> Price: **${price:.2f}**\n"
            f"> HA Open: {ha_row['Open']:.2f}  |  HA Close: {ha_row['Close']:.2f}\n"
            f"> HA High: {ha_row['High']:.2f}  |  HA Low:  {ha_row['Low']:.2f}\n"
            f"> Time:  {ts}"
        ),
        "color": color,
        "footer": {"text": "Heikin Ashi 1-min Signal Bot"},
    }

    payload = {"embeds": [embed]}
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"[{ts}] Sent {signal} for {symbol} @ ${price:.2f}")
    except requests.RequestException as e:
        print(f"[{ts}] Discord error for {symbol}: {e}")


# ── Data fetch ────────────────────────────────────────────────────────────────
def fetch_ha(symbol: str) -> tuple[pd.DataFrame, float] | tuple[None, None]:
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1d", interval=INTERVAL)
        if df.empty or len(df) < 5:
            print(f"  [{symbol}] Not enough data yet.")
            return None, None
        df = df.tail(LOOKBACK)
        ha = heikin_ashi(df)
        price = df["Close"].iloc[-1]
        return ha, price
    except Exception as e:
        print(f"  [{symbol}] Fetch error: {e}")
        return None, None


# ── Main loop ─────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 55)
    print("  Heikin Ashi Signal Bot  |  1-min candles")
    print(f"  Watching: {', '.join(SYMBOLS)}")
    print(f"  Checking every {CHECK_EVERY}s")
    print("  Press Ctrl+C to stop.")
    print("=" * 55)

    # Send startup ping
    startup_payload = {
        "content": (
            f"🤖 **Signal Bot started** — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Watching: `{'` `'.join(SYMBOLS)}` on `{INTERVAL}` candles."
        )
    }
    try:
        requests.post(WEBHOOK_URL, json=startup_payload, timeout=10)
    except Exception:
        pass

    while True:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scanning {len(SYMBOLS)} symbol(s)...")
        for symbol in SYMBOLS:
            ha, price = fetch_ha(symbol)
            if ha is None:
                continue

            signal = detect_signal(ha)
            if signal is None:
                print(f"  [{symbol}] No crossover. Last candle {'bullish' if ha['Bullish'].iloc[-1] else 'bearish'}.")
                continue

            # Only fire if the signal changed
            if last_signal.get(symbol) == signal:
                print(f"  [{symbol}] Duplicate {signal} — skipping.")
                continue

            last_signal[symbol] = signal
            send_discord(symbol, signal, ha.iloc[-1], price)

        print(f"  Sleeping {CHECK_EVERY}s...")
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot stopped.")
