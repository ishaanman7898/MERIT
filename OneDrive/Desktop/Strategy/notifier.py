"""Discord webhook notifications — no emojis, plain structured text."""

import requests
from datetime import datetime


def _post(webhook_url: str, payload: dict) -> None:
    try:
        r = requests.post(webhook_url, json=payload, timeout=10)
        r.raise_for_status()
    except requests.RequestException:
        pass


def send_signal(
    signal: str,
    price: float,
    tp: float,
    sl: float,
    strategy: str,
    webhook_url: str,
) -> None:
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    color = 0x00AA55 if signal == "BUY" else 0xAA2222
    embed = {
        "title": f"XAU/USD  {signal}",
        "color": color,
        "fields": [
            {"name": "Entry",          "value": f"${price:,.2f}",    "inline": True},
            {"name": "Take Profit",    "value": f"${tp:,.2f}",       "inline": True},
            {"name": "Stop Loss",      "value": f"${sl:,.2f}",       "inline": True},
            {"name": "Strategy",       "value": strategy,             "inline": True},
            {"name": "Time",           "value": ts,                   "inline": True},
        ],
        "footer": {"text": "Gold Signal Bot"},
    }
    _post(webhook_url, {"embeds": [embed]})


def send_close(
    signal: str,
    entry: float,
    close_price: float,
    pnl: float,
    reason: str,
    webhook_url: str,
) -> None:
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    color = 0x00AA55 if pnl >= 0 else 0xAA2222
    pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
    embed = {
        "title": f"XAU/USD  TRADE CLOSED  [{reason}]",
        "color": color,
        "fields": [
            {"name": "Side",       "value": signal,               "inline": True},
            {"name": "Entry",      "value": f"${entry:,.2f}",     "inline": True},
            {"name": "Exit",       "value": f"${close_price:,.2f}","inline": True},
            {"name": "PnL",        "value": pnl_str,               "inline": True},
            {"name": "Time",       "value": ts,                    "inline": True},
        ],
        "footer": {"text": "Gold Signal Bot"},
    }
    _post(webhook_url, {"embeds": [embed]})


def send_startup(webhook_url: str, strategy: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _post(webhook_url, {
        "content": f"Gold Signal Bot started  |  {ts}  |  Strategy: {strategy}  |  XAU/USD"
    })
