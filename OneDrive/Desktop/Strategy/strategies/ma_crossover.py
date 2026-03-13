"""
Moving Average Crossover Strategy
----------------------------------
BUY  when the fast MA crosses above the slow MA.
SELL when the fast MA crosses below the slow MA.

Tweak FAST and SLOW to adjust sensitivity.
"""

import pandas as pd

FAST = 10   # fast MA period (candles)
SLOW = 20   # slow MA period (candles)


def generate_signal(df: pd.DataFrame) -> str | None:
    """
    Parameters
    ----------
    df : DataFrame with OHLCV columns, latest row = most recent candle.

    Returns
    -------
    "BUY", "SELL", or None
    """
    if len(df) < SLOW + 1:
        return None

    close = df["Close"]
    fast  = close.rolling(FAST).mean()
    slow  = close.rolling(SLOW).mean()

    # crossover: fast crossed above slow between previous and current bar
    if fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]:
        return "BUY"
    if fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]:
        return "SELL"
    return None
