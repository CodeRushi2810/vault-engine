"""Peer co-movement screen: how closely each stock tracks the focus stock
once the whole-market (NIFTY) move is removed from both."""
import numpy as np
import pandas as pd

from dossier import universe
from dossier.data import load_index_closes, load_stocks


def _residual(x, m):
    return x - (x.cov(m) / m.var()) * m


def screen(focus=universe.FOCUS, candidates=None):
    candidates = candidates or universe.PEERS + universe.THEME
    stocks = load_stocks([focus] + candidates)
    nifty = load_index_closes()["NIFTY"]["Close"]
    f = stocks[focus][0]["Close"]

    rows = []
    for s in candidates:
        if s not in stocks:
            rows.append({"symbol": s, "note": "not in NSE archive"})
            continue
        p = pd.concat([f, stocks[s][0]["Close"], nifty], axis=1, keys=["f", "s", "m"]).dropna()
        r = np.log(p).diff().dropna()
        w = np.log(p.resample("W-FRI").last()).diff().dropna()
        rc = _residual(r.f, r.m).corr(_residual(r.s, r.m))
        se = 1 / np.sqrt(len(r) - 3)
        lo, hi = np.tanh(np.arctanh(rc) - 1.96 * se), np.tanh(np.arctanh(rc) + 1.96 * se)
        rows.append({
            "symbol": s,
            "role": "theme" if s in universe.THEME else "peer",
            "overlap_days": int(len(r)),
            "corr_daily": float(r.f.corr(r.s)),
            "resid_corr_daily": float(rc),
            "resid_corr_ci95": [float(lo), float(hi)],
            "resid_corr_weekly": float(_residual(w.f, w.m).corr(_residual(w.s, w.m))),
            "ann_vol": float(r.s.std() * np.sqrt(248)),
        })
    return sorted(rows, key=lambda x: -x.get("resid_corr_daily", -9))
