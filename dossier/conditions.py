"""What happens when: condition -> forward-return study with honest statistics.

Method
- Every condition is computed from data known at the close of day t.
- A trade is entered at the NEXT session's open and exited at the close h
  sessions later, so no same-bar look-ahead.
- Events are condition *onsets* (true today, false for the previous 5
  sessions), so one long episode is not counted many times.
- Abnormal return = stock return minus trailing beta x Nifty Smallcap 250
  return over the same window (Smallcap 250 is NETWEB's best-fit index).
- The tested quantity is the EDGE: abnormal return minus a baseline. The
  pool was chosen from hot-theme stocks that beat the index over this
  period, so a random day already shows a large positive abnormal return;
  without a baseline, opposite conditions (gap up / gap down) both look
  bullish. Baselines:
    stock-specific conditions -> the pool's average abnormal return for
      entries on the same date (what a random peer bought that day did);
    market-wide conditions    -> the stock's own average abnormal return
      over all days (everyone shares the same state on a date).
  Raw and abnormal returns are reported alongside.
- Evidence is pooled over NETWEB and its peers. Standard errors are
  clustered by calendar week, because peers co-move and events in the same
  week are not independent.
- Benjamini-Hochberg corrects for testing ~25 conditions x 3 horizons.
- Out-of-sample: a condition is 'validated' only if it is significant before
  VALIDATION_START and still has the same sign after it.
- NETWEB's own estimate is shrunk toward the pooled one by how much stocks
  genuinely differ (DerSimonian-Laird random effects).
"""
import numpy as np
import pandas as pd
from scipy import stats

from dossier import universe
from dossier.data import load_index_closes, load_stocks

HORIZONS = {"1w": 5, "1m": 21, "3m": 63}
ONSET_GAP = 5
WARMUP = 126
VALIDATION_START = pd.Timestamp("2025-07-01")
MIN_CLUSTERS = 15
MARKET = "SMALLCAP"
MARKET_WIDE = {"market_below_200", "vix_high"}
MIN_STOCKS_FOR_DATE_BASELINE = 5


# ------------------------------------------------------------- features

def _rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def _pct(x, min_periods=WARMUP):
    """Percentile of today's value within the series' own history to date."""
    return x.expanding(min_periods=min_periods).rank(pct=True)


def features(bars, idx):
    """Per-day indicators for one stock; every column uses data up to t only."""
    c, h, l, v = bars["Close"], bars["High"], bars["Low"], bars["Volume"]
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    f = pd.DataFrame(index=bars.index)
    f["ret"] = c.pct_change()
    f["sma20"], f["sma50"], f["sma200"] = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    f["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    f["rsi14"] = _rsi(c)
    f["rv20"] = np.log(c).diff().rolling(20).std()
    f["rv20_pct"] = _pct(f["rv20"])
    f["dd126"] = c / c.rolling(126, min_periods=60).max() - 1
    f["new_high126"] = c >= c.rolling(126, min_periods=126).max()
    f["r63"] = c / c.shift(63) - 1
    f["r63_pct"] = _pct(f["r63"])
    f["vol_ratio"] = v / v.rolling(50, min_periods=30).median().shift(1)
    f["deliv_pct_rank"] = _pct(bars["DelivPct"])
    f["deliv_ratio"] = bars["DelivQty"] / bars["DelivQty"].rolling(50, min_periods=30).median().shift(1)
    f["gap"] = bars["Open"] / prev - 1
    bw = 4 * c.rolling(20).std() / f["sma20"]
    f["bandwidth_pct"] = _pct(bw)
    down = (f["ret"] < 0).astype(int)
    f["down_streak"] = down.groupby((down == 0).cumsum()).cumsum()

    m = idx[MARKET]["Close"].reindex(bars.index)
    mret = m.pct_change()
    f["beta"] = (f["ret"].rolling(126, min_periods=60).cov(mret) / mret.rolling(126, min_periods=60).var())
    mma = m.rolling(200, min_periods=200).mean()
    f["mkt_above_200"] = (m > mma).astype(float).where(mma.notna())
    f["rel63"] = c / c.shift(63) - m / m.shift(63)
    f["rel63_pct"] = _pct(f["rel63"])
    vix = idx["VIX"]["Close"].reindex(bars.index)
    f["vix_pct"] = _pct(vix, min_periods=60)
    return f


# Each entry: key -> (plain-English description, features the rule needs,
# rule on the feature frame). Events only count once every needed feature
# has existed for ONSET_GAP sessions, so warm-up edges are not "onsets".
CONDITIONS = {
    "above_200dma":        ("Price closes back above its 200-day average", ("sma200",), lambda f, b: b["Close"] > f["sma200"]),
    "below_200dma":        ("Price closes below its 200-day average", ("sma200",), lambda f, b: (b["Close"] < f["sma200"])),
    "golden_cross":        ("50-day average crosses above the 200-day", ("sma200",), lambda f, b: f["sma50"] > f["sma200"]),
    "death_cross":         ("50-day average crosses below the 200-day", ("sma200",), lambda f, b: f["sma50"] < f["sma200"]),
    "new_6m_high":         ("Closes at a new 6-month high", ("dd126", "r63_pct",), lambda f, b: f["new_high126"]),
    "strong_3m_momentum":  ("3-month return in the top 20% of its own history", ("r63_pct",), lambda f, b: f["r63_pct"] > 0.8),
    "weak_3m_momentum":    ("3-month return in the bottom 20% of its own history", ("r63_pct",), lambda f, b: f["r63_pct"] < 0.2),
    "rel_strength_top":    ("Beating Smallcap 250 by a top-20% margin over 3 months", ("rel63_pct",), lambda f, b: f["rel63_pct"] > 0.8),
    "rel_strength_bottom": ("Lagging Smallcap 250 by a bottom-20% margin over 3 months", ("rel63_pct",), lambda f, b: f["rel63_pct"] < 0.2),
    "rsi_oversold":        ("RSI(14) drops below 30", ("sma50",), lambda f, b: f["rsi14"] < 30),
    "rsi_overbought":      ("RSI(14) rises above 70", ("sma50",), lambda f, b: f["rsi14"] > 70),
    "stretched_down":      ("Close more than 2 ATR below its 20-day average", ("sma50",), lambda f, b: b["Close"] < f["sma20"] - 2 * f["atr14"]),
    "stretched_up":        ("Close more than 2 ATR above its 20-day average", ("sma50",), lambda f, b: b["Close"] > f["sma20"] + 2 * f["atr14"]),
    "drawdown_25":         ("Falls 25%+ below its 6-month high", ("dd126", "r63_pct",), lambda f, b: f["dd126"] < -0.25),
    "drawdown_40":         ("Falls 40%+ below its 6-month high", ("dd126", "r63_pct",), lambda f, b: f["dd126"] < -0.40),
    "down_streak_4":       ("Four or more down days in a row", ("sma50",), lambda f, b: f["down_streak"] >= 4),
    "vol_squeeze":         ("Bollinger band width in the narrowest 10% of its history", ("bandwidth_pct",), lambda f, b: f["bandwidth_pct"] < 0.10),
    "vol_stormy":          ("20-day volatility in the top third of its history", ("rv20_pct",), lambda f, b: f["rv20_pct"] > 2 / 3),
    "volume_spike_up":     ("Volume 3x normal on an up day", ("vol_ratio",), lambda f, b: (f["vol_ratio"] > 3) & (f["ret"] > 0)),
    "volume_spike_down":   ("Volume 3x normal on a down day", ("vol_ratio",), lambda f, b: (f["vol_ratio"] > 3) & (f["ret"] < 0)),
    "delivery_accumulation": ("Delivery % in top 20% of history on an up day", ("deliv_pct_rank",), lambda f, b: (f["deliv_pct_rank"] > 0.8) & (f["ret"] > 0)),
    "delivery_distribution": ("Delivery % in top 20% of history on a down day", ("deliv_pct_rank",), lambda f, b: (f["deliv_pct_rank"] > 0.8) & (f["ret"] < 0)),
    "delivery_qty_surge":  ("Delivered quantity 2.5x its normal level", ("deliv_ratio",), lambda f, b: f["deliv_ratio"] > 2.5),
    "gap_up_4":            ("Opens 4%+ above the previous close", ("sma50",), lambda f, b: f["gap"] > 0.04),
    "gap_down_4":          ("Opens 4%+ below the previous close", ("sma50",), lambda f, b: f["gap"] < -0.04),
    "market_below_200":    ("Smallcap 250 index falls below its 200-day average", ("mkt_above_200",), lambda f, b: f["mkt_above_200"] == 0),
    "vix_high":            ("India VIX in the top 20% of its history (fear)", ("vix_pct",), lambda f, b: f["vix_pct"] > 0.8),
}


def _onsets(state):
    state = state.fillna(False).astype(bool)
    recent = state.shift(1).rolling(ONSET_GAP, min_periods=1).max().fillna(0).astype(bool)
    return state & ~recent


def _forward(bars, idx, f):
    """Raw and abnormal returns from next open (t+1) to close at t+h."""
    m = idx[MARKET]
    mo, mc = m["Open"].reindex(bars.index), m["Close"].reindex(bars.index)
    entry = bars["Open"].shift(-1).fillna(bars["Close"].shift(-1))
    m_entry = mo.shift(-1).fillna(mc.shift(-1))
    out = {}
    for name, h in HORIZONS.items():
        raw = bars["Close"].shift(-h) / entry - 1
        mkt = mc.shift(-h) / m_entry - 1
        out[name] = pd.DataFrame({"raw": raw, "abn": raw - f["beta"] * mkt})
    return out


# ------------------------------------------------------------- statistics

def _cluster_mean(x, clusters):
    """Mean with a cluster-robust standard error (clusters = event weeks)."""
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return float(x.mean()) if n else None, None, 0
    mu = x.mean()
    g = pd.Series(x - mu).groupby(np.asarray(clusters)).sum()
    k = len(g)
    if k < 2:
        return float(mu), None, k
    se = np.sqrt((g ** 2).sum() * k / (k - 1)) / n
    return float(mu), float(se), k


def _p(mu, se, k):
    if se is None or se == 0 or k < 2:
        return None
    return float(2 * stats.t.sf(abs(mu / se), df=k - 1))


def _summ(ev, col="edge"):
    if ev.empty:
        return {"n": 0, "clusters": 0}
    mu, se, k = _cluster_mean(ev[col], ev["week"])
    p = _p(mu, se, k)
    return {
        "n": int(len(ev)), "clusters": int(k), "mean": mu, "se": se,
        "ci95": [mu - 1.96 * se, mu + 1.96 * se] if se else None, "p": p,
        "hit_rate": float((ev[col] > 0).mean()),
    }


def _random_effects(per_stock):
    """DerSimonian-Laird between-stock variance tau^2 from per-stock means."""
    rows = [(s["mean"], s["se"] ** 2) for s in per_stock if s.get("se")]
    if len(rows) < 3:
        return None, None
    m, v = np.array(rows).T
    w = 1 / v
    fixed = (w * m).sum() / w.sum()
    q = (w * (m - fixed) ** 2).sum()
    tau2 = max(0.0, (q - (len(m) - 1)) / (w.sum() - (w ** 2).sum() / w.sum()))
    w_re = 1 / (v + tau2)
    return float((w_re * m).sum() / w_re.sum()), float(tau2)


def _bh(pvals, alpha=0.05):
    idx = [i for i, p in enumerate(pvals) if p is not None]
    ps = np.array([pvals[i] for i in idx])
    passed = [False] * len(pvals)
    if not len(ps):
        return passed
    order = np.argsort(ps)
    m = len(ps)
    cutoff = -1
    for rank, j in enumerate(order, 1):
        if ps[j] <= alpha * rank / m:
            cutoff = rank
    for j in order[:max(cutoff, 0)]:
        passed[idx[j]] = True
    return passed


# ------------------------------------------------------------- study

def returns_panel(symbols=None):
    """Bars, features and forward returns for every stock in the pool.

    Returns (stocks, idx, feats, fwd, all_abn): fwd[symbol][horizon] is a
    frame of raw/abnormal returns entered at the next open; all_abn[horizon]
    maps symbol -> abnormal-return series (for same-day baselines).
    """
    symbols = symbols or [universe.FOCUS] + universe.PEERS
    stocks = load_stocks(symbols)
    idx = load_index_closes()
    feats, fwd, all_abn = {}, {}, {h: {} for h in HORIZONS}
    for s in symbols:
        if s not in stocks:
            continue
        bars = stocks[s][0]
        feats[s] = features(bars, idx)
        fwd[s] = _forward(bars, idx, feats[s])
        for hname, fr in fwd[s].items():
            all_abn[hname][s] = fr["abn"]
    return stocks, idx, feats, fwd, all_abn


def attach_returns(events, fwd, all_abn, market_wide=()):
    """Add raw_/abn_/edge_<h> and week columns to events (symbol, cond, date).

    `date` is the signal session: the trade enters at the next open.
    """
    events = events[events["symbol"].isin(list(fwd))].copy().reset_index(drop=True)
    for hname in HORIZONS:
        events[f"raw_{hname}"] = [fwd[s][hname]["raw"].get(d, np.nan) for s, d in zip(events["symbol"], events["date"])]
        events[f"abn_{hname}"] = [fwd[s][hname]["abn"].get(d, np.nan) for s, d in zip(events["symbol"], events["date"])]
    events["week"] = events["date"].dt.to_period("W").astype(str)

    wide = events["cond"].isin(list(market_wide))
    for hname in HORIZONS:
        panel = pd.DataFrame(all_abn[hname])
        # Leave-one-out: the same-day baseline excludes the event's own stock.
        total, count = panel.sum(axis=1, min_count=1), panel.notna().sum(axis=1)
        own = events[f"abn_{hname}"]
        d_total, d_count = events["date"].map(total), events["date"].map(count)
        others = d_count - own.notna().astype(int)
        loo = ((d_total - own.fillna(0)) / others).where(others >= MIN_STOCKS_FOR_DATE_BASELINE)
        stock_base = panel.mean()
        base = np.where(wide, events["symbol"].map(stock_base), loo)
        events[f"edge_{hname}"] = events[f"abn_{hname}"] - base
    return events


def evaluate(events, catalog, market_wide=()):
    """Pooled, validated, shrunk statistics for every event type x horizon.

    `catalog` maps event type -> plain-English description. Multiple-testing
    correction runs across everything passed in one call.
    """
    results, pvals = [], []
    for key, desc in catalog.items():
        ce = events[events["cond"] == key]
        for hname in HORIZONS:
            cols = {f"edge_{hname}": "edge", f"abn_{hname}": "abn", f"raw_{hname}": "raw"}
            ev = ce.dropna(subset=[f"edge_{hname}"])[["symbol", "date", "week", *cols]].rename(columns=cols)
            pooled = _summ(ev)
            disc = _summ(ev[ev["date"] < VALIDATION_START])
            val = _summ(ev[ev["date"] >= VALIDATION_START])
            per_stock = []
            for s, g in ev.groupby("symbol"):
                ps = _summ(g)
                ps["symbol"] = s
                per_stock.append(ps)
            re_mean, tau2 = _random_effects(per_stock)
            focus = next((p for p in per_stock if p["symbol"] == universe.FOCUS), {"n": 0, "clusters": 0})
            shrunk = None
            if focus.get("se") and re_mean is not None:
                if tau2 == 0:
                    shrunk = re_mean
                else:
                    w_f, w_p = 1 / focus["se"] ** 2, 1 / tau2
                    shrunk = (w_f * focus["mean"] + w_p * re_mean) / (w_f + w_p)
            elif re_mean is not None:
                shrunk = re_mean

            results.append({
                "condition": key, "description": desc, "horizon": hname, "h": HORIZONS[hname],
                "baseline": "stock's own average" if key in market_wide else "same-day peer average",
                "pooled": pooled, "pooled_abnormal": _summ(ev, "abn"), "pooled_raw": _summ(ev, "raw"),
                "discovery": disc, "validation": val,
                "stocks_with_events": len(per_stock), "between_stock_var": tau2,
                "netweb": focus, "netweb_estimate": shrunk,
                "netweb_raw": _summ(ev[ev["symbol"] == universe.FOCUS], "raw"),
            })
            pvals.append(pooled.get("p"))

    for r, ok in zip(results, _bh(pvals)):
        r["significant_after_bh"] = ok
        r["verdict"] = _verdict(r)
    return results, len([p for p in pvals if p is not None])


def collect_events(symbols=None):
    """Onset events for every condition on every stock, with forward returns."""
    stocks, idx, feats, fwd, all_abn = returns_panel(symbols)
    frames, states = [], {}
    for s, f in feats.items():
        bars = stocks[s][0]
        for key, (_, needs, rule) in CONDITIONS.items():
            valid = f[list(needs)].notna().all(axis=1)
            live = valid & valid.shift(ONSET_GAP, fill_value=False)
            state = rule(f, bars).reindex(bars.index).fillna(False).astype(bool) & valid
            if s == universe.FOCUS:
                states[key] = state
            on = _onsets(state) & live
            dates = on.index[on]
            if len(dates):
                frames.append(pd.DataFrame({"symbol": s, "cond": key, "date": dates}))
    events = attach_returns(pd.concat(frames, ignore_index=True), fwd, all_abn, MARKET_WIDE)
    return events, states


def method_note(tests):
    return {
        "entry": "next session open", "abnormal_vs": f"trailing 126-day beta x {universe.INDICES[MARKET]}",
        "onset_gap_sessions": ONSET_GAP, "validation_start": VALIDATION_START.date().isoformat(),
        "pool": [universe.FOCUS] + universe.PEERS, "tests": tests,
        "costs_note": "Returns are before costs; allow roughly 0.3% for a round trip.",
    }


def study():
    events, focus_states = collect_events()
    catalog = {k: v[0] for k, v in CONDITIONS.items()}
    results, tests = evaluate(events, catalog, MARKET_WIDE)
    return {"method": method_note(tests), "results": results, "now": _current_state(focus_states, events)}


def _verdict(r):
    p, d, v = r["pooled"], r["discovery"], r["validation"]
    if p.get("clusters", 0) < MIN_CLUSTERS:
        return "insufficient data"
    same_sign = d.get("mean") is not None and v.get("mean") is not None and np.sign(d["mean"]) == np.sign(v["mean"])
    disc_sig = d.get("p") is not None and d["p"] < 0.05
    val_ok = v.get("p") is not None and v["p"] / 2 < 0.10 and same_sign   # one-sided, correct direction
    if r["significant_after_bh"] and disc_sig and val_ok:
        return "validated"
    # Added 27 September 2026 after the first event study, so treat as
    # provisional: survives the multiple-testing correction and points the
    # same way in both halves, but only one half is significant on its own.
    one_half = disc_sig or (v.get("p") is not None and v["p"] < 0.05)
    if r["significant_after_bh"] and same_sign and one_half:
        return "consistent, not yet confirmed"
    if p.get("p") is not None and p["p"] < 0.05:
        return "suggestive (not validated)"
    return "no evidence"


def _current_state(states, events):
    """Which conditions are true for the focus stock at its latest close."""
    out = []
    for key, s in states.items():
        if not len(s) or not bool(s.iloc[-1]):
            continue
        on = _onsets(s)
        onset_dates = s.index[on]
        since = onset_dates[-1] if len(onset_dates) else None
        sessions = int((s.index > since).sum()) if since is not None else None
        out.append({"condition": key, "description": CONDITIONS[key][0],
                    "since": since.date().isoformat() if since is not None else None,
                    "sessions_since_onset": sessions})
    return {"as_of": next(iter(states.values())).index[-1].date().isoformat() if states else None,
            "active": out}
