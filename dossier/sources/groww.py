"""Groww: kept for the live feed and intraday quotes, not for history.

Groww facts observed on 27 September 2026 (verify if behaviour changes):
- Daily bars differ slightly from NSE's official file (High/Low/Volume) and
  `Open` is None on most bars since 1 January 2025.
- Prices are not split-adjusted and contain bad prints (ZENTEC 12 May 2025
  shows a 100x close; NSE's official close is 1476.70).
- NIFTYIT and NIFTY500 history only starts 1 January 2025.
- Daily candles are capped at 180 days per request, and the SDK timeout
  defaults to infinite (one call hung for 90s+).
"""
import time
from datetime import timedelta

import pandas as pd

CHUNK_DAYS = 170
REQUEST_TIMEOUT = 20
COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]


def client():
    from growwapi import GrowwAPI
    from core.auth import get_groww_token
    return GrowwAPI(get_groww_token())


def fetch_daily(groww, symbol, start, end, retries=3):
    """Daily candles for an NSE cash symbol between two datetimes."""
    rows = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=CHUNK_DAYS), end)
        for attempt in range(retries):
            try:
                resp = groww.get_historical_candles(
                    exchange=groww.EXCHANGE_NSE,
                    segment=groww.SEGMENT_CASH,
                    groww_symbol=f"NSE-{symbol}",
                    start_time=cur.strftime("%Y-%m-%d 09:15:00"),
                    end_time=chunk_end.strftime("%Y-%m-%d 15:30:00"),
                    candle_interval=groww.CANDLE_INTERVAL_DAY,
                    timeout=REQUEST_TIMEOUT,
                )
                rows.extend(resp.get("candles", []))
                time.sleep(0.3)
                break
            except Exception:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
        cur = chunk_end + timedelta(days=1)

    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame([r[:6] for r in rows], columns=COLUMNS)
    df["Date"] = pd.to_datetime(df["Date"]).dt.normalize()
    for c in COLUMNS[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.drop_duplicates("Date", keep="last").sort_values("Date").reset_index(drop=True)
