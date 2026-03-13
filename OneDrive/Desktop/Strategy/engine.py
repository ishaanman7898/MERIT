"""
Live trading engine (background thread) + backtesting engine.
Gold (XAU/USD) focused — single symbol, TP/SL tracking.
"""

import importlib.util
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

import notifier

TRADES_PATH = Path(__file__).parent / "trades.json"


# ── Strategy loader ────────────────────────────────────────────────────────────

def load_strategy(name: str):
    path = Path("strategies") / f"{name}.py"
    if not path.exists():
        raise FileNotFoundError(f"strategies/{name}.py not found")
    spec   = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "generate_signal"):
        raise AttributeError(f"'{name}' must define generate_signal(df) -> str | None")
    return module


# ── Trade record helpers ───────────────────────────────────────────────────────

def _empty_trade() -> dict:
    return {
        "id":         None,
        "side":       None,
        "entry":      None,
        "tp":         None,
        "sl":         None,
        "open_time":  None,
        "close_time": None,
        "close_price":None,
        "pnl":        None,
        "status":     "NONE",   # NONE | OPEN | TP_HIT | SL_HIT | CLOSED
    }


def load_trades() -> list[dict]:
    if TRADES_PATH.exists():
        try:
            return json.loads(TRADES_PATH.read_text())
        except Exception:
            return []
    return []


def save_trades(trades: list[dict]) -> None:
    TRADES_PATH.write_text(json.dumps(trades, indent=2, default=str))


# ── Data fetch ────────────────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str, interval: str, lookback: int) -> pd.DataFrame | None:
    try:
        df = yf.Ticker(symbol).history(period="1d", interval=interval)
        if df.empty or len(df) < 5:
            return None
        return df.tail(lookback).copy()
    except Exception:
        return None


def fetch_price(symbol: str) -> float | None:
    try:
        df = yf.Ticker(symbol).history(period="1d", interval="1m")
        if df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


# ── Live Trading Engine ───────────────────────────────────────────────────────

class TradingEngine:
    def __init__(self, config: dict, log_cb, trade_cb):
        """
        log_cb(msg: str)          — append to log
        trade_cb(trade: dict)     — called whenever active trade changes
        """
        self.config   = config
        self.log_cb   = log_cb
        self.trade_cb = trade_cb
        self._stop    = threading.Event()
        self._thread: threading.Thread | None = None

        self._trades: list[dict]  = load_trades()
        self._active: dict | None = None  # current open trade
        # Restore open trade if it exists
        for t in reversed(self._trades):
            if t["status"] == "OPEN":
                self._active = t
                break

    # ── Public API ──────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_trades(self) -> list[dict]:
        return list(self._trades)

    def close_active_trade(self) -> None:
        """Manually close the active trade at current price."""
        if not self._active:
            return
        price = fetch_price(self.config.get("symbol", "GC=F"))
        if price is None:
            return
        self._close_trade(price, "MANUAL")

    # ── Internal ─────────────────────────────────────────────

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_cb(f"[{ts}]  {msg}")

    def _open_trade(self, signal: str, price: float) -> None:
        cfg    = self.config
        tp_dist = cfg.get("take_profit_usd", 10.0)
        sl_dist = cfg.get("stop_loss_usd",   5.0)

        if signal == "BUY":
            tp = price + tp_dist
            sl = price - sl_dist
        else:
            tp = price - tp_dist
            sl = price + sl_dist

        trade = {
            "id":          len(self._trades) + 1,
            "side":        signal,
            "entry":       round(price, 2),
            "tp":          round(tp, 2),
            "sl":          round(sl, 2),
            "open_time":   datetime.now().isoformat(timespec="seconds"),
            "close_time":  None,
            "close_price": None,
            "pnl":         None,
            "status":      "OPEN",
        }

        self._active = trade
        self._trades.append(trade)
        save_trades(self._trades)
        self.trade_cb(trade)

        notifier.send_signal(
            signal=signal,
            price=price,
            tp=tp,
            sl=sl,
            strategy=cfg.get("active_strategy", ""),
            webhook_url=cfg.get("discord_webhook", ""),
        )
        self._log(f"{signal}  entry=${price:,.2f}  TP=${tp:,.2f}  SL=${sl:,.2f}")

    def _close_trade(self, price: float, reason: str) -> None:
        if not self._active:
            return
        entry = self._active["entry"]
        side  = self._active["side"]
        pnl   = round((price - entry) if side == "BUY" else (entry - price), 2)

        self._active["close_price"] = round(price, 2)
        self._active["close_time"]  = datetime.now().isoformat(timespec="seconds")
        self._active["pnl"]         = pnl
        self._active["status"]      = reason   # TP_HIT | SL_HIT | CLOSED | MANUAL

        save_trades(self._trades)
        self.trade_cb(None)

        notifier.send_close(
            signal=side,
            entry=entry,
            close_price=price,
            pnl=pnl,
            reason=reason,
            webhook_url=self.config.get("discord_webhook", ""),
        )
        pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
        self._log(f"CLOSED [{reason}]  exit=${price:,.2f}  PnL={pnl_str}")
        self._active = None

    def _check_tp_sl(self, price: float) -> None:
        if not self._active:
            return
        side = self._active["side"]
        tp   = self._active["tp"]
        sl   = self._active["sl"]

        if side == "BUY":
            if price >= tp:
                self._close_trade(price, "TP_HIT")
            elif price <= sl:
                self._close_trade(price, "SL_HIT")
        else:
            if price <= tp:
                self._close_trade(price, "TP_HIT")
            elif price >= sl:
                self._close_trade(price, "SL_HIT")

    def _run(self):
        cfg      = self.config
        symbol   = cfg.get("symbol", "GC=F")
        interval = cfg.get("interval", "1m")
        lookback = cfg.get("lookback_candles", 50)
        sleep_s  = cfg.get("check_interval_seconds", 60)
        strat    = cfg.get("active_strategy", "heikin_ashi")

        self._log(f"Bot started  |  strategy: {strat}  |  symbol: {symbol}")
        notifier.send_startup(cfg.get("discord_webhook", ""), strat)

        last_signal = None

        while not self._stop.is_set():
            # Reload config each cycle so settings changes take effect
            try:
                from pathlib import Path as _P
                _cfg = json.loads((_P(__file__).parent / "config.json").read_text())
                self.config = _cfg
                cfg      = _cfg
                sleep_s  = cfg.get("check_interval_seconds", 60)
                strat    = cfg.get("active_strategy", "heikin_ashi")
            except Exception:
                pass

            # Fetch data
            df = fetch_ohlcv(symbol, interval, lookback)
            if df is None:
                self._log("No data — market may be closed")
                self._stop.wait(sleep_s)
                continue

            price = float(df["Close"].iloc[-1])
            self._log(f"XAU/USD  ${price:,.2f}")

            # Check TP/SL on active trade first
            self._check_tp_sl(price)

            # Generate signal
            try:
                strategy = load_strategy(strat)
                signal   = strategy.generate_signal(df)
            except Exception as e:
                self._log(f"Strategy error: {e}")
                signal = None

            if signal and signal != last_signal:
                # Close existing trade if opposite signal
                if self._active and self._active["side"] != signal:
                    self._close_trade(price, "REVERSED")
                # Open new trade if no active trade
                if not self._active:
                    last_signal = signal
                    self._open_trade(signal, price)
            elif signal is None:
                self._log("No signal")

            self._stop.wait(sleep_s)

        self._log("Bot stopped.")


# ── Backtester ────────────────────────────────────────────────────────────────

def run_backtest(
    strategy_name: str,
    symbol: str,
    start: str,
    end: str,
    interval: str,
    tp_usd: float,
    sl_usd: float,
    progress_cb=None,
) -> dict:
    df = yf.download(symbol, start=start, end=end, interval=interval, progress=False)
    if df.empty:
        return {"error": f"No data for {symbol}  {start} to {end}"}

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    try:
        strategy = load_strategy(strategy_name)
    except Exception as e:
        return {"error": str(e)}

    trades   = []
    position = None   # {side, entry, tp, sl, bar}
    equity   = [0.0]
    min_bars = 5

    for i in range(min_bars, len(df)):
        if progress_cb:
            progress_cb(i / len(df))

        price = float(df["Close"].iloc[i])

        # Check TP/SL
        if position:
            side = position["side"]
            hit  = None
            if side == "BUY":
                if price >= position["tp"]:
                    hit = "TP_HIT"
                elif price <= position["sl"]:
                    hit = "SL_HIT"
            else:
                if price <= position["tp"]:
                    hit = "TP_HIT"
                elif price >= position["sl"]:
                    hit = "SL_HIT"

            if hit:
                close_price = position["tp"] if hit == "TP_HIT" else position["sl"]
                pnl = (close_price - position["entry"]) if side == "BUY" else (position["entry"] - close_price)
                trades.append({
                    "side":   side,
                    "entry":  position["entry"],
                    "exit":   close_price,
                    "pnl":    round(pnl, 2),
                    "reason": hit,
                    "bar":    i,
                })
                equity.append(equity[-1] + pnl)
                position = None

        # Generate signal
        try:
            signal = strategy.generate_signal(df.iloc[:i].copy())
        except Exception:
            signal = None

        # Open new trade
        if signal and not position:
            tp = (price + tp_usd) if signal == "BUY" else (price - tp_usd)
            sl = (price - sl_usd) if signal == "BUY" else (price + sl_usd)
            position = {"side": signal, "entry": price, "tp": tp, "sl": sl, "bar": i}

        # Close and reverse if opposite signal
        elif signal and position and signal != position["side"]:
            pnl = (price - position["entry"]) if position["side"] == "BUY" else (position["entry"] - price)
            trades.append({
                "side":   position["side"],
                "entry":  position["entry"],
                "exit":   price,
                "pnl":    round(pnl, 2),
                "reason": "REVERSED",
                "bar":    i,
            })
            equity.append(equity[-1] + pnl)
            tp = (price + tp_usd) if signal == "BUY" else (price - tp_usd)
            sl = (price - sl_usd) if signal == "BUY" else (price + sl_usd)
            position = {"side": signal, "entry": price, "tp": tp, "sl": sl, "bar": i}

    # Close remaining position at last bar
    if position:
        price = float(df["Close"].iloc[-1])
        pnl   = (price - position["entry"]) if position["side"] == "BUY" else (position["entry"] - price)
        trades.append({
            "side":   position["side"],
            "entry":  position["entry"],
            "exit":   price,
            "pnl":    round(pnl, 2),
            "reason": "END",
            "bar":    len(df) - 1,
        })
        equity.append(equity[-1] + pnl)

    return _stats(trades, equity)


def _stats(trades: list, equity: list) -> dict:
    if not trades:
        return {
            "trades": 0, "win_rate": 0.0, "total_pnl": 0.0,
            "max_drawdown": 0.0, "avg_trade": 0.0,
            "equity_curve": [0.0], "trade_list": [],
        }

    pnls    = [t["pnl"] for t in trades]
    wins    = [p for p in pnls if p > 0]
    peak    = equity[0]
    mdd     = 0.0
    for v in equity:
        peak = max(peak, v)
        mdd  = min(mdd, v - peak)

    return {
        "trades":       len(trades),
        "win_rate":     round(len(wins) / len(pnls) * 100, 1),
        "total_pnl":    round(sum(pnls), 2),
        "max_drawdown": round(mdd, 2),
        "avg_trade":    round(sum(pnls) / len(pnls), 2),
        "equity_curve": equity,
        "trade_list":   trades,
    }
