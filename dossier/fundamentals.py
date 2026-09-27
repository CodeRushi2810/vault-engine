"""Fundamentals: quarterly metrics, the business scorecard, and fundamental
events for the event study.

All figures come from NSE's structured filings (sources/financials.py) and
from rule-extracted filing facts (filings.py). Each event is dated by the
moment its filing was published, never by the period it describes.

There are no analyst consensus estimates in free data, so "surprise" is
measured against the company's own recent trend: growth speeding up or
slowing down versus the previous quarter, and margin versus its previous
four-quarter average.
"""
import numpy as np
import pandas as pd

from dossier import universe
from dossier.sources import financials

ACCEL_PP = 0.10          # revenue-growth change that counts as a speed-up / slow-down
MARGIN_PP = 0.02         # EBITDA-margin move vs trailing 4-quarter average
LARGE_ORDER = 0.05       # order value as a share of trailing-12-month revenue

CATALOG = {
    "rev_accel": f"Results: revenue growth vs a year ago speeds up by {ACCEL_PP:.0%}+ points",
    "rev_decel": f"Results: revenue growth vs a year ago slows by {ACCEL_PP:.0%}+ points",
    "margin_expand": f"Results: EBITDA margin {MARGIN_PP:.0%}+ points above its previous 4-quarter average",
    "margin_compress": f"Results: EBITDA margin {MARGIN_PP:.0%}+ points below its previous 4-quarter average",
    "profit_decline": "Results: net profit lower than a year ago",
    "rating_upgrade": "Credit rating upgraded or outlook raised (read from the letter)",
    "rating_downgrade": "Credit rating downgraded or outlook cut (read from the letter)",
    "rating_reaffirm": "Credit rating reaffirmed (read from the letter)",
    "order_large": f"Order win worth {LARGE_ORDER:.0%}+ of the last 12 months' revenue",
    "order_small": f"Order win worth under {LARGE_ORDER:.0%} of the last 12 months' revenue",
}


def metrics(symbol):
    q = financials.quarterly(symbol)
    if q.empty:
        return q
    q = q.sort_values("period_end").reset_index(drop=True)
    q["ebitda"] = q["pbt"] + q["finance_cost"].fillna(0) + q["depreciation"].fillna(0) - q["other_income"].fillna(0)
    q["ebitda_margin"] = q["ebitda"] / q["revenue"]
    q["pat_margin"] = q["pat"] / q["revenue"]
    cogs = q[["materials", "purchases", "inventory_change"]].fillna(0).sum(axis=1)
    q["gross_margin"] = (q["revenue"] - cogs) / q["revenue"]

    by_end = q.set_index("period_end")
    year_ago = q["period_end"] - pd.DateOffset(years=1)
    q["revenue_yoy"] = q["revenue"] / year_ago.map(by_end["revenue"]).values - 1
    q["pat_yoy"] = q["pat"] / year_ago.map(by_end["pat"]).values - 1
    q.loc[year_ago.map(by_end["pat"]).values <= 0, "pat_yoy"] = np.nan   # growth off a loss is meaningless
    q["revenue_qoq"] = q["revenue"].pct_change()

    # Trailing 12 months only when the four quarters are consecutive.
    consecutive = (q["period_end"].diff(3).dt.days.between(260, 290))
    q["revenue_ttm"] = q["revenue"].rolling(4).sum().where(consecutive)
    q["margin_prev4"] = q["ebitda_margin"].shift(1).rolling(4, min_periods=3).mean()
    return q


def fundamental_events(symbol):
    """Events from the numbers themselves, dated by publication time."""
    q = metrics(symbol)
    rows = []
    if q.empty:
        return pd.DataFrame(columns=["symbol", "cond", "ts"])
    accel = q["revenue_yoy"] - q["revenue_yoy"].shift(1)
    for i, r in q.iterrows():
        ts = r["published"]
        if pd.isna(ts):
            continue
        if not np.isnan(accel.iloc[i]):
            if accel.iloc[i] >= ACCEL_PP:
                rows.append((symbol, "rev_accel", ts))
            elif accel.iloc[i] <= -ACCEL_PP:
                rows.append((symbol, "rev_decel", ts))
        if not np.isnan(r["margin_prev4"]) and not np.isnan(r["ebitda_margin"]):
            d = r["ebitda_margin"] - r["margin_prev4"]
            if d >= MARGIN_PP:
                rows.append((symbol, "margin_expand", ts))
            elif d <= -MARGIN_PP:
                rows.append((symbol, "margin_compress", ts))
        if not np.isnan(r["pat_yoy"]) and r["pat_yoy"] < 0:
            rows.append((symbol, "profit_decline", ts))
    return pd.DataFrame(rows, columns=["symbol", "cond", "ts"])


def _ttm_at(q, ts):
    """Trailing-12-month revenue as it was known at `ts`."""
    known = q[(q["published"] <= ts) & q["revenue_ttm"].notna()]
    return known["revenue_ttm"].iloc[-1] if len(known) else np.nan


def fact_events(facts):
    """Rating and order events from extracted filing facts."""
    rows = []
    if facts is None or facts.empty:
        return pd.DataFrame(columns=["symbol", "cond", "ts"])
    q_cache = {}
    for f in facts.itertuples():
        if f.kind == "rating_action":
            cond = {"upgrade": "rating_upgrade", "outlook_positive": "rating_upgrade",
                    "downgrade": "rating_downgrade", "outlook_negative": "rating_downgrade",
                    "reaffirm": "rating_reaffirm"}.get(f.value)
            if cond:
                rows.append((f.symbol, cond, f.ts))
        elif f.kind == "order_value":
            if f.symbol not in q_cache:
                q_cache[f.symbol] = metrics(f.symbol)
            ttm = _ttm_at(q_cache[f.symbol], f.ts)
            if not np.isnan(ttm) and ttm > 0:
                rows.append((f.symbol, "order_large" if f.value / ttm >= LARGE_ORDER else "order_small", f.ts))
    return pd.DataFrame(rows, columns=["symbol", "cond", "ts"])


def scorecard(facts):
    """What the report shows about the focus stock's business."""
    q = metrics(universe.FOCUS)
    quarters = []
    for r in q.itertuples():
        quarters.append({
            "quarter": r.period_end.date().isoformat(), "published": r.published.isoformat(sep=" ") if not pd.isna(r.published) else None,
            "revenue": r.revenue, "revenue_yoy": _f(r.revenue_yoy), "ebitda_margin": _f(r.ebitda_margin),
            "gross_margin": _f(r.gross_margin), "pat": r.pat, "pat_margin": _f(r.pat_margin), "eps": _f(r.eps),
            "revenue_ttm": _f(r.revenue_ttm), "start_date_mistyped": bool(r.start_date_mistyped),
        })
    f = facts[facts["symbol"] == universe.FOCUS] if facts is not None and len(facts) else pd.DataFrame()
    business = []
    for r in f.sort_values("ts").itertuples() if len(f) else []:
        business.append({"ts": r.ts.isoformat(sep=" "), "kind": r.kind, "value": r.value,
                         "agency": getattr(r, "agency", None), "quote": r.quote, "source": r.source,
                         "category": r.category})
    return {"quarters": quarters, "facts": business, "basis": q["basis"].iloc[0] if len(q) else None}


def _f(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)
