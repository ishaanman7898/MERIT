"""
Heikin Ashi Cross Strategy
--------------------------
BUY  when the latest candle flips bearish → bullish.
SELL when the latest candle flips bullish → bearish.

df columns: Open, High, Low, Close, Volume
"""

import pandas as pd


def _compute_ha(df: pd.DataFrame) -> pd.DataFrame:
    ha = pd.DataFrame(index=df.index)
    ha["Close"] = (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4
    ha["Open"] = 0.0
    ha.iloc[0, ha.columns.get_loc("Open")] = (df["Open"].iloc[0] + df["Close"].iloc[0]) / 2
    for i in range(1, len(ha)):
        ha.iloc[i, ha.columns.get_loc("Open")] = (
            ha["Open"].iloc[i - 1] + ha["Close"].iloc[i - 1]
        ) / 2
    ha["High"] = pd.concat([df["High"], ha["Open"], ha["Close"]], axis=1).max(axis=1)
    ha["Low"]  = pd.concat([df["Low"],  ha["Open"], ha["Close"]], axis=1).min(axis=1)
    ha["Bull"] = ha["Close"] > ha["Open"]
    return ha


def generate_signal(df: pd.DataFrame) -> str | None:
    """
    Parameters
    ----------
    df : DataFrame with OHLCV columns, latest row = most recent candle.

    Returns
    -------
    "BUY", "SELL", or None
    """
    if len(df) < 3:
        return None

    ha = _compute_ha(df)
    prev = ha["Bull"].iloc[-2]
    curr = ha["Bull"].iloc[-1]

    if not prev and curr:
        return "BUY"
    if prev and not curr:
        return "SELL"
    return None
