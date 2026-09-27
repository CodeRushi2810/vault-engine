"""NSE per-company and market-wide event data, cached under data/dossier/_nse/api/.

Endpoints (checked 27 September 2026; nseindia.com/api needs browser-like
cookies, which nselib.libutil.nse_urlfetch provides):
- event-calendar             : board meetings, incl. results dates
- corporates-financial-results: results filings with broadcast timestamps
- corporate-share-holdings-master: quarterly promoter / public holding
- corporate-announcements    : exchange filings, each tagged with a category
- bulk and block deals       : market-wide, via nselib (3-month chunks)

Each cache file is refreshed at most once per day.
"""
import json
import os
import time
from datetime import date, datetime

import pandas as pd

from dossier.sources.nse import ROOT

API_DIR = os.path.join(ROOT, "api")
BASE = "https://www.nseindia.com/api/"
ENDPOINTS = {
    "calendar": "event-calendar?index=equities&symbol={s}",
    "results": "corporates-financial-results?index=equities&symbol={s}&period=Quarterly",
    "holdings": "corporate-share-holdings-master?index=equities&symbol={s}",
    "announcements": "corporate-announcements?index=equities&symbol={s}",
}


def _fresh(path):
    return os.path.exists(path) and datetime.fromtimestamp(os.path.getmtime(path)).date() == date.today()


def _fetch_json(url, retries=3):
    from nselib import libutil
    delay = 2.0
    for attempt in range(retries):
        try:
            r = libutil.nse_urlfetch(url)
            if r.status_code == 200:
                return r.json()
        except Exception:
            if attempt == retries - 1:
                raise
        time.sleep(delay)
        delay *= 2
    raise RuntimeError(f"NSE API failed: {url}")


def company(kind, symbol, refresh=True):
    """Rows from one per-company endpoint as a list of dicts (cached)."""
    path = os.path.join(API_DIR, kind, f"{symbol}.json")
    if os.path.exists(path) and (not refresh or _fresh(path)):
        with open(path) as f:
            return json.load(f)
    data = _fetch_json(BASE + ENDPOINTS[kind].format(s=symbol))
    rows = data if isinstance(data, list) else data.get("data", [])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(rows, f)
    time.sleep(0.8)
    return rows


def deals(start, refresh=True):
    """Bulk and block deals since `start`, all symbols, one frame (cached)."""
    path = os.path.join(API_DIR, "deals.csv")
    if os.path.exists(path) and (not refresh or _fresh(path)):
        return pd.read_csv(path, parse_dates=["Date"])
    from nselib import capital_market as cm
    frames = []
    cur, today = pd.Timestamp(start), pd.Timestamp(date.today())
    while cur <= today:
        stop = min(cur + pd.DateOffset(months=3) - pd.Timedelta(days=1), today)
        for kind, fn in (("bulk", cm.bulk_deal_data), ("block", cm.block_deals_data)):
            try:
                df = fn(from_date=f"{cur:%d-%m-%Y}", to_date=f"{stop:%d-%m-%Y}")
            except Exception:
                df = None   # nselib raises when a window has no deals
            if df is not None and len(df):
                frames.append(df.assign(Kind=kind))
            time.sleep(1.0)
        cur = stop + pd.Timedelta(days=1)
    out = pd.concat(frames, ignore_index=True)
    out.columns = [c.strip() for c in out.columns]
    out = out.rename(columns={"Buy/Sell": "Side", "QuantityTraded": "Qty", "TradePrice/Wght.Avg.Price": "Price"})
    out["Date"] = pd.to_datetime(out["Date"], format="%d-%b-%Y")
    out["Qty"] = pd.to_numeric(out["Qty"].astype(str).str.replace(",", ""), errors="coerce")
    out["Price"] = pd.to_numeric(out["Price"].astype(str).str.replace(",", ""), errors="coerce")
    out = out.drop_duplicates()
    os.makedirs(API_DIR, exist_ok=True)
    out.to_csv(path, index=False)
    return out
