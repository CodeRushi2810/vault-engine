"""NSE end-of-day data: the dossier's source of record.

Three official inputs, all cached under data/dossier/_nse/:
- sec_bhavdata_full_DDMMYYYY.csv : every security's OHLC, VWAP, volume,
  trades and delivery for one session.
- ind_close_all_DDMMYYYY.csv     : every NSE index's OHLC plus P/E, P/B and
  dividend yield for one session.
- Corporate actions (via nselib)  : splits and bonuses used to back-adjust.

Facts checked on 27 September 2026:
- The bhav file's PREV_CLOSE is NOT adjusted on a split ex-date (E2E on
  5 June 2026 shows 4313.60 next to a post-split 452.90), so split factors
  must come from the corporate-actions list.
- A missing file returns HTTP 404; that is how non-session days show up.
  Special weekend sessions (budget day, Muhurat) do exist, so weekends are
  probed rather than assumed closed.
"""
import gzip
import io
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.join(BASE_DIR, "data", "dossier", "_nse")
BHAV_DIR = os.path.join(ROOT, "bhav")
INDEX_DIR = os.path.join(ROOT, "index")
NO_SESSION_FILE = os.path.join(ROOT, "no_session.json")
CA_FILE = os.path.join(ROOT, "corporate_actions.csv")
EQUITY_CACHE = os.path.join(ROOT, "equity_cache.pkl")

ARCHIVE = "https://nsearchives.nseindia.com"
BHAV_URL = ARCHIVE + "/products/content/sec_bhavdata_full_{:%d%m%Y}.csv"
INDEX_URL = ARCHIVE + "/content/indices/ind_close_all_{:%d%m%Y}.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,application/octet-stream,*/*",
}
BHAV_HEADER = "SYMBOL"
INDEX_HEADER = "Index Name"
SERIES_PREFERENCE = ["EQ", "BE", "BZ"]   # BE/BZ: trade-for-trade segments

_local = threading.local()


def _session():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(HEADERS)
    return _local.s


# ---------------------------------------------------------------- download

def _path(kind, d):
    folder = BHAV_DIR if kind == "bhav" else INDEX_DIR
    return os.path.join(folder, f"{d:%Y%m%d}.csv.gz")


def _file_date(text, kind):
    """Session date written inside a downloaded file (first data row)."""
    first = text.lstrip().splitlines()[1].split(",")
    if kind == "bhav":
        return datetime.strptime(first[2].strip(), "%d-%b-%Y").date()
    return datetime.strptime(first[1].strip(), "%d-%m-%Y").date()


def _download(url, dest, expect_header, kind, day, retries=4):
    """Fetch one archive file. Returns 'ok', 'missing' or raises.

    NSE sometimes serves an earlier session's file under a later date (the
    file for Sunday 20 September 2026 holds Friday 18 September's rows), so
    a file whose inner date differs from `day` is treated as missing.
    """
    delay = 2.0
    for attempt in range(retries):
        try:
            resp = _session().get(url, timeout=20)
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 404:
            return "missing"
        if resp.status_code == 200:
            text = resp.content.decode("utf-8", errors="replace")
            if not text.lstrip().startswith(expect_header):
                raise ValueError(f"Unexpected content from {url}: {text[:80]!r}")
            if len(text.strip().splitlines()) < 2 or _file_date(text, kind) != day:
                return "missing"
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".part"
            with gzip.open(tmp, "wt", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, dest)
            return "ok"
        # 403/429/5xx: NSE throttling or a hiccup; back off and retry.
        if attempt == retries - 1:
            resp.raise_for_status()
        time.sleep(delay)
        delay *= 2
    return "missing"


def _load_no_session():
    if os.path.exists(NO_SESSION_FILE):
        with open(NO_SESSION_FILE) as f:
            return set(json.load(f))
    return set()


def sync(start, end=None, workers=3, pause=0.25, log=print):
    """Download any missing bhav and index files for [start, end].

    A day is recorded as 'no session' only once it is a few days old, so a
    file NSE has not published yet is retried on the next sync.
    """
    start = pd.Timestamp(start).date()
    end = pd.Timestamp(end).date() if end else date.today()
    no_session = _load_no_session()
    settle = date.today() - timedelta(days=3)

    todo = []
    d = start
    while d <= end:
        key = d.isoformat()
        if key not in no_session and not (os.path.exists(_path("bhav", d)) and os.path.exists(_path("index", d))):
            todo.append(d)
        d += timedelta(days=1)

    counts = {"requested_days": len(todo), "sessions": 0, "no_session": 0, "pending": 0}
    lock = threading.Lock()

    def work(day):
        status = "ok"
        if not os.path.exists(_path("bhav", day)):
            status = _download(BHAV_URL.format(day), _path("bhav", day), BHAV_HEADER, "bhav", day)
        if status == "ok" and not os.path.exists(_path("index", day)):
            _download(INDEX_URL.format(day), _path("index", day), INDEX_HEADER, "index", day)
        time.sleep(pause)
        with lock:
            if status == "ok":
                counts["sessions"] += 1
            elif day <= settle:
                counts["no_session"] += 1
                no_session.add(day.isoformat())
            else:
                counts["pending"] += 1
            done = counts["sessions"] + counts["no_session"] + counts["pending"]
            if done % 100 == 0:
                log(f"  NSE sync: {done}/{len(todo)} days checked")

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(work, todo))
    finally:
        os.makedirs(ROOT, exist_ok=True)
        with open(NO_SESSION_FILE, "w") as f:
            json.dump(sorted(no_session), f)
    return counts


# ---------------------------------------------------------------- parsing

def read_bhav(path):
    """One session's bhav file as a tidy frame."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        df = pd.read_csv(f, skipinitialspace=True, dtype=str)
    df.columns = df.columns.str.strip()
    df = df.apply(lambda s: s.str.strip())
    out = pd.DataFrame({
        "Symbol": df["SYMBOL"],
        "Series": df["SERIES"],
        "Date": pd.to_datetime(df["DATE1"], format="%d-%b-%Y"),
    })
    num = {
        "PrevClose": "PREV_CLOSE", "Open": "OPEN_PRICE", "High": "HIGH_PRICE",
        "Low": "LOW_PRICE", "Last": "LAST_PRICE", "Close": "CLOSE_PRICE",
        "VWAP": "AVG_PRICE", "Volume": "TTL_TRD_QNTY", "TurnoverLacs": "TURNOVER_LACS",
        "Trades": "NO_OF_TRADES", "DelivQty": "DELIV_QTY", "DelivPct": "DELIV_PER",
    }
    for col, src in num.items():
        out[col] = pd.to_numeric(df[src], errors="coerce")   # '-' -> NaN
    return out


def read_index(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        df = pd.read_csv(f, dtype=str)
    df.columns = df.columns.str.strip()
    out = pd.DataFrame({
        "Index": df["Index Name"].str.strip(),
        "Date": pd.to_datetime(df["Index Date"].str.strip(), format="%d-%m-%Y"),
    })
    num = {
        "Open": "Open Index Value", "High": "High Index Value", "Low": "Low Index Value",
        "Close": "Closing Index Value", "Volume": "Volume", "TurnoverCr": "Turnover (Rs. Cr.)",
        "PE": "P/E", "PB": "P/B", "DivYield": "Div Yield",
    }
    for col, src in num.items():
        out[col] = pd.to_numeric(df[src], errors="coerce")
    return out


def _session_files(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.endswith(".csv.gz"))


def load_equities(symbols):
    """Raw (unadjusted) daily rows for `symbols` from every cached bhav file.

    Parsed rows are cached; only files added since the last call are read,
    unless the symbol list changed.
    """
    symbols = sorted(set(symbols))
    files = _session_files(BHAV_DIR)
    cache = pd.read_pickle(EQUITY_CACHE) if os.path.exists(EQUITY_CACHE) else None
    if cache is not None and cache["symbols"] == symbols:
        seen, frames = set(cache["files"]), [cache["rows"]]
    else:
        seen, frames = set(), []

    new = [f for f in files if f not in seen]
    for name in new:
        day = read_bhav(os.path.join(BHAV_DIR, name))
        frames.append(day[day["Symbol"].isin(symbols) & day["Series"].isin(SERIES_PREFERENCE)])
    rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if new or cache is None:
        os.makedirs(ROOT, exist_ok=True)
        pd.to_pickle({"symbols": symbols, "files": files, "rows": rows}, EQUITY_CACHE)

    # One row per symbol per day, preferring EQ over trade-for-trade series.
    rank = {s: i for i, s in enumerate(SERIES_PREFERENCE)}
    rows = rows.assign(_r=rows["Series"].map(rank)).sort_values(["Symbol", "Date", "_r"])
    rows = rows.drop_duplicates(["Symbol", "Date"]).drop(columns="_r")
    return {s: g.drop(columns="Symbol").set_index("Date").sort_index() for s, g in rows.groupby("Symbol")}


def load_indices(names):
    """Daily rows for the named indices, as {name: frame}."""
    frames = []
    for name in _session_files(INDEX_DIR):
        day = read_index(os.path.join(INDEX_DIR, name))
        frames.append(day[day["Index"].isin(names)])
    if not frames:
        return {}
    rows = pd.concat(frames, ignore_index=True).drop_duplicates(["Index", "Date"])
    return {n: g.drop(columns="Index").set_index("Date").sort_index() for n, g in rows.groupby("Index")}


# ------------------------------------------------------- corporate actions

_SPLIT = re.compile(r"from\s*r[es]\.?\s*([\d.]+).*?to\s*r[es]\.?\s*([\d.]+)", re.I)
_BONUS = re.compile(r"bonus\s*(\d+)\s*:\s*(\d+)", re.I)


def parse_factor(subject):
    """Price divisor implied by a corporate action, or None if not a split/bonus.

    Split 'From Rs 10/- To Re 1/-' -> 10. Bonus 'a:b' is a new shares per b
    held (NSE convention), so the price divides by (a + b) / b.
    """
    s = str(subject)
    if "split" in s.lower():
        m = _SPLIT.search(s)
        if m and float(m.group(2)) > 0:
            return float(m.group(1)) / float(m.group(2))
    m = _BONUS.search(s)
    if m and int(m.group(2)) > 0:
        a, b = int(m.group(1)), int(m.group(2))
        return (a + b) / b
    return None


def corporate_actions(start, refresh=True):
    """NSE corporate actions since `start`, cached. Refreshed at most daily."""
    cached = pd.read_csv(CA_FILE, dtype=str) if os.path.exists(CA_FILE) else None
    fresh_today = cached is not None and \
        datetime.fromtimestamp(os.path.getmtime(CA_FILE)).date() == date.today()
    if cached is not None and (fresh_today or not refresh):
        return cached

    from nselib import capital_market as cm
    frames = []
    cur = pd.Timestamp(start)
    today = pd.Timestamp(date.today())
    while cur <= today:
        stop = min(cur + pd.DateOffset(months=6) - pd.Timedelta(days=1), today)
        df = cm.corporate_actions_for_equity(from_date=f"{cur:%d-%m-%Y}", to_date=f"{stop:%d-%m-%Y}")
        if df is not None and len(df):
            frames.append(df.astype(str))
        cur = stop + pd.Timedelta(days=1)
        time.sleep(1.0)
    ca = pd.concat(frames, ignore_index=True).drop_duplicates() if frames else pd.DataFrame()
    os.makedirs(ROOT, exist_ok=True)
    ca.to_csv(CA_FILE, index=False)
    return ca


def price_events(ca, symbol):
    """Split/bonus events for one symbol: [{ex_date, factor, subject}]."""
    if ca is None or ca.empty:
        return []
    rows = ca[ca["symbol"].str.strip() == symbol]
    events = []
    for _, r in rows.iterrows():
        f = parse_factor(r["subject"])
        if f and f != 1:
            events.append({"ex_date": pd.to_datetime(r["exDate"], format="%d-%b-%Y"),
                           "factor": f, "subject": r["subject"].strip()})
    return sorted(events, key=lambda e: e["ex_date"])


def adjust(raw, events):
    """Back-adjust prices and volumes for splits/bonuses.

    Rows before each ex-date have prices divided by the factor and share
    counts multiplied, so the series is continuous in today's share units.
    Each event is checked against the actual price change on the ex-date.
    """
    df = raw.copy()
    price_cols = [c for c in ("PrevClose", "Open", "High", "Low", "Last", "Close", "VWAP") if c in df]
    qty_cols = [c for c in ("Volume", "DelivQty") if c in df]
    applied = []
    for e in events:
        before = df.index < e["ex_date"]
        if not before.any() or before.all():
            continue
        prior_close = df.loc[before, "Close"].iloc[-1]
        ex_close = df.loc[~before, "Close"].iloc[0]
        implied = prior_close / ex_close
        df.loc[before, price_cols] = df.loc[before, price_cols] / e["factor"]
        df.loc[before, qty_cols] = df.loc[before, qty_cols] * e["factor"]
        applied.append({
            "ex_date": e["ex_date"].date().isoformat(), "factor": e["factor"], "subject": e["subject"],
            "implied_by_prices": round(float(implied), 3),
            # The ex-date also carries a normal day's move; 25% covers limit days.
            "consistent": bool(abs(implied / e["factor"] - 1) < 0.25),
        })
    return df, applied
