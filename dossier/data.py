"""Data layer: NSE as the source of record, Yahoo as a cross-check.

    sync()            download any missing NSE files and corporate actions
    load_stocks(...)  split/bonus-adjusted daily bars per symbol
    build_panel(sym)  one stock's bars with every benchmark index aligned
"""
import os

import numpy as np
import pandas as pd

from dossier import universe
from dossier.sources import nse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "data", "dossier")

# NSE vs Yahoo tolerances. On 25 September 2026 the two matched exactly for
# NETWEB, so anything beyond rounding is worth a look.
TOL_CLOSE = 0.0025
TOL_RANGE = 0.005
TOL_VOLUME = 0.02


def sync(log=print):
    """Bring the local NSE archive up to date. Safe to re-run; only fetches gaps."""
    log(f"Syncing NSE daily files from {universe.HISTORY_START} ...")
    counts = nse.sync(universe.HISTORY_START, log=log)
    log(f"  {counts}")
    log("Refreshing NSE corporate actions ...")
    ca = nse.corporate_actions(universe.HISTORY_START)
    log(f"  {len(ca)} corporate-action records")
    return counts


def load_stocks(symbols=None):
    """{symbol: (adjusted bars, applied split/bonus events)} for the universe
    plus any extra `symbols`. The universe is always loaded together so the
    parsed-row cache stays valid."""
    wanted = sorted(set(universe.EQUITIES) | set(symbols or []))
    raw = nse.load_equities(wanted)
    ca = nse.corporate_actions(universe.HISTORY_START, refresh=False)
    out = {}
    for s in wanted:
        if s not in raw:
            continue
        out[s] = nse.adjust(raw[s], nse.price_events(ca, s))
    return out


def load_index_closes():
    idx = nse.load_indices(list(universe.INDICES.values()))
    return {key: idx[name] for key, name in universe.INDICES.items() if name in idx}


def audit(df, symbol):
    """Flag data problems in adjusted bars. Returns [{check, severity, detail}]."""
    issues = []
    n = len(df)
    if n == 0:
        return [{"check": "empty", "severity": "fatal", "detail": f"No NSE bars for {symbol}"}]

    if df["Open"].isna().any():
        issues.append({"check": "missing_open", "severity": "warn",
                       "detail": f"{int(df['Open'].isna().sum())}/{n} bars have no Open"})

    bad = df[(df["High"] < df["Low"]) | (df["Close"] > df["High"] * 1.0001) | (df["Close"] < df["Low"] * 0.9999)]
    if len(bad):
        issues.append({"check": "ohlc_inconsistent", "severity": "warn",
                       "detail": f"{len(bad)} bars where Close lies outside High-Low",
                       "dates": [d.date().isoformat() for d in bad.index[:10]]})

    ret = df["Close"].pct_change()
    jumps = ret[ret.abs() > 0.30]
    if len(jumps):
        issues.append({"check": "unexplained_jump_gt_30pct", "severity": "warn",
                       "detail": "Large move with no split/bonus on record; check NSE announcements",
                       "dates": [f"{d.date()} ({r:+.1%})" for d, r in jumps.items()]})

    t4t = df[df["Series"] != "EQ"]
    if len(t4t):
        issues.append({"check": "trade_for_trade_days", "severity": "info",
                       "detail": f"{len(t4t)} sessions in series {sorted(t4t['Series'].unique())} "
                                 "(trade-for-trade: no intraday netting, thinner trading)"})

    locked = df[(df["High"] == df["Low"]) & (df["Volume"] > 0)]
    if len(locked):
        issues.append({"check": "price_locked_days", "severity": "info",
                       "detail": f"{len(locked)} sessions traded at a single price (limit-locked); "
                                 "range and ATR are understated on those days",
                       "dates": [d.date().isoformat() for d in locked.index[:10]]})

    gaps = df.index.to_series().diff().dt.days
    long_gaps = gaps[gaps > 6]
    if len(long_gaps):
        issues.append({"check": "calendar_gaps", "severity": "info",
                       "detail": f"{len(long_gaps)} gaps longer than 6 calendar days (suspension or late listing?)",
                       "dates": [d.date().isoformat() for d in long_gaps.index[:10]]})
    return issues


def reconcile(nse_df, yahoo_df):
    """Compare adjusted NSE bars against Yahoo. Returns a summary dict.

    Checked on 27 September 2026, NSE was right every time the two differed:
    Yahoo carries zero-volume placeholder bars (repeating the prior close) on
    some real sessions and on some NSE holidays, a partial bar for 2 May 2025,
    and none of NSE's special weekend sessions. Placeholders are set aside
    before comparing so real disagreements stand out.
    """
    placeholder = yahoo_df.index[yahoo_df["Volume"].fillna(0) == 0]
    yahoo_df = yahoo_df.drop(placeholder)
    common = nse_df.index.intersection(yahoo_df.index)
    a, b = nse_df.loc[common], yahoo_df.loc[common]
    rel = lambda x, y: (x / y - 1).abs()
    close_bad = common[rel(a["Close"], b["Close"]) > TOL_CLOSE]
    range_bad = common[(rel(a["High"], b["High"]) > TOL_RANGE) | (rel(a["Low"], b["Low"]) > TOL_RANGE)]
    vol_bad = common[rel(a["Volume"], b["Volume"].replace(0, np.nan)) > TOL_VOLUME]
    return {
        "common_days": int(len(common)),
        "yahoo_placeholder_days": int(len(placeholder[placeholder >= nse_df.index.min()])),
        "missing_in_yahoo": int(len(nse_df.index.difference(yahoo_df.index))),
        "missing_in_nse": int(len(yahoo_df.index[yahoo_df.index >= nse_df.index.min()].difference(nse_df.index))),
        "close_mismatch_days": [d.date().isoformat() for d in close_bad],
        "range_mismatch_days": int(len(range_bad)),
        "volume_mismatch_days": int(len(vol_bad)),
        "agrees": bool(len(close_bad) == 0),
    }


def build_panel(symbol, check_yahoo=True):
    """Adjusted bars for `symbol` with benchmark closes aligned on its dates."""
    stocks = load_stocks([symbol])
    if symbol not in stocks:
        raise ValueError(f"{symbol} not found in the NSE archive; run `python -m dossier.run sync`")
    bars, events = stocks[symbol]
    panel = bars.copy()

    bench = {}
    for key, frame in load_index_closes().items():
        panel[key] = frame["Close"].reindex(panel.index)
        bench[key] = {"name": universe.INDICES[key], "first": frame.index.min().date().isoformat(),
                      "missing_on_stock_days": int(panel[key].isna().sum())}

    quality = {"source": "NSE sec_bhavdata_full (official)", "stock": audit(bars, symbol),
               "corporate_actions_applied": events, "benchmarks": bench}

    if check_yahoo:
        try:
            from dossier.sources import yahoo
            y = yahoo.fetch([symbol], start=bars.index.min().date().isoformat())
            quality["yahoo_crosscheck"] = reconcile(bars, y[symbol]) if symbol in y else {"error": "no Yahoo data"}
        except Exception as e:  # the cross-check is optional; never block a build on it
            quality["yahoo_crosscheck"] = {"error": f"{type(e).__name__}: {e}"}

    return panel, quality
