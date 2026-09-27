"""Anatomy: how the stock moves, with sample sizes and confidence intervals.

Forward returns over h days overlap, so N daily observations hold only about
N/h independent ones. Confidence intervals use a moving-block bootstrap with
block length h to respect that; `n_independent` is reported alongside.
"""
import numpy as np
import pandas as pd

TRADING_DAYS = 248
HORIZONS = {"1w": 5, "1m": 21, "3m": 63, "6m": 126}
RNG = np.random.default_rng(7)


def block_bootstrap_ci(x, block, stat=np.mean, reps=2000, alpha=0.05):
    """Moving-block bootstrap CI of `stat` over a 1-D array."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    # Fewer than 10 independent blocks gives a CI that looks precise but isn't.
    if n < 10 * block or n < 20:
        return None
    n_blocks = int(np.ceil(n / block))
    starts = RNG.integers(0, n - block + 1, size=(reps, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)).reshape(reps, -1)[:, :n]
    stats = np.apply_along_axis(stat, 1, x[idx])
    return float(np.quantile(stats, alpha / 2)), float(np.quantile(stats, 1 - alpha / 2))


def return_profile(close):
    r = np.log(close).diff().dropna()
    simple = close.pct_change().dropna()
    ci = block_bootstrap_ci(r.values, block=5)
    years = len(r) / TRADING_DAYS
    return {
        "n_days": int(len(r)),
        "years": round(years, 2),
        "cagr": float((close.iloc[-1] / close.iloc[0]) ** (1 / years) - 1),
        "ann_vol": float(r.std() * np.sqrt(TRADING_DAYS)),
        "mean_daily_log": float(r.mean()),
        "mean_daily_log_ci95": ci,
        "mean_is_significant": bool(ci and (ci[0] > 0 or ci[1] < 0)),
        "skew": float(r.skew()),
        "excess_kurtosis": float(r.kurt()),
        "pct_up_days": float((r > 0).mean()),
        "quantiles_daily": {f"p{int(q*100)}": float(simple.quantile(q)) for q in (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)},
        "moves_gt_3sd": int((r.abs() > 3 * r.std()).sum()),
        "moves_gt_3sd_if_normal": round(len(r) * 0.0027, 1),
        "best_days": [(d.date().isoformat(), float(v)) for d, v in simple.nlargest(5).items()],
        "worst_days": [(d.date().isoformat(), float(v)) for d, v in simple.nsmallest(5).items()],
    }


def atr(df, n=14):
    prev = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def volatility_profile(df):
    r = np.log(df["Close"]).diff()
    rv20 = r.rolling(20).std() * np.sqrt(TRADING_DAYS)
    atr_pct = atr(df) / df["Close"]
    cur = rv20.dropna()
    # Regime = tercile of 20-day realised vol against history known at the
    # time (expanding window), so conditional stats carry no look-ahead.
    lo_t = rv20.expanding(min_periods=126).quantile(1 / 3)
    hi_t = rv20.expanding(min_periods=126).quantile(2 / 3)
    regime = pd.Series(np.select([rv20 <= lo_t, rv20 > hi_t], ["calm", "stormy"], "normal"), index=rv20.index)
    regime[lo_t.isna() | rv20.isna()] = None
    lo, hi = lo_t.iloc[-1], hi_t.iloc[-1]

    # Does vol cluster? Correlation of today's |r| with the next 20 days' |r|.
    fwd_abs = r.abs().rolling(20).mean().shift(-20)
    return {
        "atr14_pct_now": float(atr_pct.iloc[-1]),
        "atr14_pct_median": float(atr_pct.median()),
        "atr14_pct_p90": float(atr_pct.quantile(0.9)),
        "rv20_now": float(cur.iloc[-1]),
        "rv20_percentile_now": float((cur <= cur.iloc[-1]).mean()),
        "rv20_terciles": {"calm_below": float(lo), "stormy_above": float(hi)},
        "regime_now": str(regime.iloc[-1]),
        "vol_clustering_corr": float(r.abs().corr(fwd_abs)),
        "regime_days": {k: int(v) for k, v in regime.value_counts().items()},
    }, regime


def drawdowns(close, min_depth=0.10):
    """Every peak-to-trough episode deeper than `min_depth`."""
    peak = close.cummax()
    dd = close / peak - 1
    episodes, in_dd, start = [], False, None
    for d, v in dd.items():
        if not in_dd and v < 0:
            in_dd, start = True, d
        elif in_dd and v == 0:
            seg = dd[start:d]
            episodes.append((start, seg.idxmin(), d, seg.min()))
            in_dd = False
    if in_dd:
        seg = dd[start:]
        episodes.append((start, seg.idxmin(), None, seg.min()))

    idx = close.index
    out = []
    for s, t, e, depth in episodes:
        if depth > -min_depth:
            continue
        peak_date = idx[idx.get_loc(s) - 1] if idx.get_loc(s) > 0 else s
        out.append({
            "peak": peak_date.date().isoformat(),
            "trough": t.date().isoformat(),
            "recovered": e.date().isoformat() if e is not None else None,
            "depth": float(depth),
            "days_to_trough": int(idx.get_loc(t) - idx.get_loc(peak_date)),
            "days_to_recover": int(idx.get_loc(e) - idx.get_loc(t)) if e is not None else None,
        })
    return {
        "max_drawdown": float(dd.min()),
        "current_drawdown": float(dd.iloc[-1]),
        "pct_time_below_minus20": float((dd < -0.20).mean()),
        "episodes_gt_10pct": out,
    }


def forward_returns(close, regime=None):
    """Baseline distribution of h-day forward returns from any day."""
    out = {}
    for name, h in HORIZONS.items():
        fwd = (close.shift(-h) / close - 1).dropna()
        if len(fwd) < 2 * h:
            out[name] = {"h": h, "n": int(len(fwd)), "note": "insufficient history"}
            continue
        row = {
            "h": h,
            "n": int(len(fwd)),
            "n_independent": int(len(fwd) // h),
            "mean": float(fwd.mean()),
            "mean_ci95": block_bootstrap_ci(fwd.values, block=h),
            "median": float(fwd.median()),
            "p_positive": float((fwd > 0).mean()),
            "p_positive_ci95": block_bootstrap_ci((fwd > 0).astype(float).values, block=h),
            "p10": float(fwd.quantile(0.10)),
            "p90": float(fwd.quantile(0.90)),
        }
        # Worst intra-window drawdown: what a holder had to sit through.
        lows = close.rolling(h).min().shift(-h)
        row["median_worst_dip"] = float((lows / close - 1).dropna().median())

        if regime is not None:
            by = {}
            for lab in ["calm", "normal", "stormy"]:
                sub = fwd[regime.reindex(fwd.index) == lab]
                by[lab] = {
                    "n_independent": int(len(sub) // h),
                    "mean": float(sub.mean()) if len(sub) else None,
                    "p_positive": float((sub > 0).mean()) if len(sub) else None,
                    "mean_ci95": block_bootstrap_ci(sub.values, block=h),
                }
            row["by_vol_regime"] = by
        out[name] = row
    return out


def seasonality(close):
    """Day-of-week and month-of-year mean returns.

    Testing 17 buckets at 5% yields about one false positive by chance, so
    `significant` applies a Benjamini-Hochberg correction across all buckets.
    Weekend special sessions (budget day etc.) are too rare to bucket.
    """
    from scipy import stats

    r = close.pct_change().dropna()
    r = r[r.index.dayofweek < 5]
    rows = []
    for label, key in (("weekday", r.index.dayofweek), ("month", r.index.month)):
        for k, sub in r.groupby(key):
            # Compare each bucket with all other days, not with zero: a stock
            # that trended up makes every bucket look positive.
            rest = r[key != k]
            p = stats.ttest_ind(sub, rest, equal_var=False).pvalue
            rows.append((label, int(k), sub, float(p)))

    m = len(rows)
    order = np.argsort([p for *_, p in rows])
    passed = np.zeros(m, bool)
    for rank, i in enumerate(order, 1):
        if rows[i][3] <= 0.05 * rank / m:
            passed[order[:rank]] = True

    res = {"weekday": {}, "month": {}, "tests": m, "any_significant": bool(passed.any())}
    for (label, k, sub, p), ok in zip(rows, passed):
        res[label][k] = {"n": int(len(sub)), "mean": float(sub.mean()),
                         "excess_vs_other_days": float(sub.mean() - r[(r.index.dayofweek if label == "weekday" else r.index.month) != k].mean()),
                         "p_raw": p, "significant_after_bh": bool(ok)}
    return res


def relationships(panel):
    from dossier.universe import INDICES

    # Each pair is aligned on its own so one index with a short history
    # cannot silently shorten the window for the others.
    benches = [k for k in INDICES if k != "VIX" and k in panel and panel[k].notna().sum() > 60]
    rets = np.log(panel[["Close"] + benches]).diff()
    out = {}
    for b in benches:
        r = rets[["Close", b]].dropna()
        beta = r["Close"].cov(r[b]) / r[b].var()
        roll = r["Close"].rolling(63).cov(r[b]) / r[b].rolling(63).var()
        down = r[r[b] < 0]
        up = r[r[b] > 0]
        out[b] = {
            "n_days": int(len(r)),
            "from": r.index.min().date().isoformat(),
            "beta": float(beta),
            "corr": float(r["Close"].corr(r[b])),
            "beta_63d_now": float(roll.iloc[-1]),
            "beta_63d_range": [float(roll.min()), float(roll.max())],
            "downside_beta": float(down["Close"].cov(down[b]) / down[b].var()),
            "upside_beta": float(up["Close"].cov(up[b]) / up[b].var()),
            "r_squared": float(r["Close"].corr(r[b]) ** 2),
        }
    out["best_fit_index"] = max(benches, key=lambda k: out[k]["r_squared"]) if benches else None
    # How the stock behaved on NIFTY's worst days.
    r = rets[["Close", "NIFTY"]].dropna()
    worst = r["NIFTY"].nsmallest(10)
    out["on_nifty_worst_days"] = [
        {"date": d.date().isoformat(), "nifty": float(np.expm1(v)), "stock": float(np.expm1(r.loc[d, "Close"]))}
        for d, v in worst.items()
    ]
    return out


def build(panel):
    close = panel["Close"]
    vol, regime = volatility_profile(panel)
    return {
        "returns": return_profile(close),
        "volatility": vol,
        "drawdowns": drawdowns(close),
        "forward_returns": forward_returns(close, regime),
        "seasonality": seasonality(close),
        "relationships": relationships(panel),
    }
