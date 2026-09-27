"""Events: what happens after results, filings, big deals and holding changes.

Every event is turned into a *signal session*: the first session in which
the market could react to it (a filing at 16:10 is only tradable the next
day). The drift test then enters at the NEXT session's open, exactly like
the condition study, and uses the same statistics: same-day peer baseline,
week-clustered errors, Benjamini-Hochberg, and a before/after validation
split (see dossier.conditions).

Event families
- Results: every quarterly result, split by the market's first reaction
  (abnormal move from the close before the release to the close of the
  reaction session) into strong (> +REACTION_CUT), weak (< -REACTION_CUT)
  and muted. A continued drift in the reaction's direction is the classic
  post-results drift.
- Filings: NSE's own announcement categories. Only the category is used;
  direction (e.g. rating upgrade vs downgrade) lives in the PDF and is not
  parsed, so these test "does news of this kind matter at all".
- Deals: bulk/block deals after removing round-trippers (a client who both
  bought and sold the stock that day, almost always an HFT/prop desk).
  Bulk-deal lists are published after the close, so the deal date is the
  signal session.
- Holdings: quarterly promoter stake changes, dated by NSE broadcast time.
"""
import re
from datetime import time as dtime

import numpy as np
import pandas as pd

from dossier import conditions as C
from dossier import universe
from dossier.sources import nse_api

MARKET_CLOSE = dtime(15, 30)
MARKET_OPEN = dtime(9, 15)
# NSE's official close is the weighted average of the last 30 minutes, so
# news released after 15:00 is only partly in that day's close.
CLOSE_AUCTION = dtime(15, 0)
REACTION_CUT = 0.03
DEDUPE_SESSIONS = 5

FILING_TYPES = {
    "order_win": ({"Bagging/Receiving of orders/contracts"}, "Company announces an order or contract win"),
    "credit_rating": ({"Credit Rating"}, "Credit rating action announced (direction not parsed)"),
    "acquisition": ({"Acquisition"}, "Company announces an acquisition"),
    "management_exit": ({"Resignation", "Cessation", "Change in Management"}, "Director or key manager leaves / management change"),
    "exchange_query": ({"Spurt in Volume", "Price movement", "News Verification"}, "NSE queries an unusual price or volume move"),
    "large_holder_filing": ({"Disclosure under SEBI Takeover Regulations", "Disc. under Reg.30 of SEBI (SAST) Reg.2011"}, "A large shareholder files a takeover-code disclosure"),
    "investor_meet": ({"Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of Analysts/Institutional Investor Meet/Con. Call"}, "Analyst / institutional investor meeting"),
}
RESULT_FILINGS = {"Outcome of Board Meeting", "Financial Result Updates", "Press Release", "Investor Presentation"}

CATALOG = {
    "results_all": "Quarterly results released (any reaction)",
    "results_strong": f"Results: first reaction beats the market by more than {REACTION_CUT:.0%}",
    "results_weak": f"Results: first reaction trails the market by more than {REACTION_CUT:.0%}",
    "results_muted": f"Results: first reaction within ±{REACTION_CUT:.0%} of the market",
    **{k: v[1] for k, v in FILING_TYPES.items()},
    "inst_deal_buy": "Institution is a net buyer in a bulk/block deal",
    "inst_deal_sell": "Institution is a net seller in a bulk/block deal",
    "deal_net_buy": "Other directional bulk/block buying (non-institutional)",
    "deal_net_sell": "Other directional bulk/block selling (non-institutional)",
    "promoter_cut": "Promoter stake falls by 0.5 percentage points or more in a quarter",
    "promoter_raise": "Promoter stake rises by 0.25 percentage points or more in a quarter",
}

# Directional institutions. Arbitrage desks are excluded by name; HFT/prop
# desks are removed by the round-trip filter.
INSTITUTION = re.compile(
    r"MUTUAL FUND|\bFUNDS?\b|INSURANCE|\bLIFE\b|ASSURANCE|PENSION|PROVIDENT|SOCIETE GENERALE|BNP PARIBAS|"
    r"MORGAN STANLEY|GOLDMAN|CITIGROUP|NOMURA|J ?P ?MORGAN|MERRILL|HSBC|\bUBS\b|BARCLAYS|VANGUARD|ISHARES|"
    r"BLACKROCK|GOVERNMENT OF SINGAPORE|MONETARY AUTHORITY|ABU DHABI|INVESTMENT AUTHORITY|FIDELITY|NORGES|"
    r"AMUNDI|\bPLC\b|\bPTE\b|\bFPI\b|\bAIF\b|TRUSTEE|ASSET MANAGEMENT|\bAMC\b", re.I)
NOT_DIRECTIONAL = re.compile(r"ARBITRAGE", re.I)


def _ts(s, fmt):
    try:
        return pd.to_datetime(s, format=fmt)
    except (TypeError, ValueError):
        return pd.NaT


def reaction_session(ts, sessions):
    """First session whose close fully reflects information public at `ts`.

    News after 15:00 is only partly in that day's close (NSE's close is the
    last half-hour's weighted average), so it counts from the next session.
    """
    day = ts.normalize()
    if day in sessions and ts.time() < CLOSE_AUCTION:
        return day
    later = sessions[sessions > day]
    return later[0] if len(later) else None


def _prev_session(d, sessions):
    earlier = sessions[sessions < d]
    return earlier[-1] if len(earlier) else None


def _dedupe(df, sessions):
    """Keep the first event of each type per stock within DEDUPE_SESSIONS."""
    out, last = [], {}
    pos = {d: i for i, d in enumerate(sessions)}
    for r in df.sort_values("date").itertuples():
        k = (r.symbol, r.cond)
        i = pos.get(r.date)
        if i is None:
            continue
        if k in last and i - last[k] <= DEDUPE_SESSIONS:
            continue
        last[k] = i
        out.append(r._asdict())
    return pd.DataFrame(out).drop(columns="Index", errors="ignore")


# ------------------------------------------------------------- builders

def results_for(symbol, sessions, close, mkt_close, beta):
    """One row per quarterly result with its timing and first reaction."""
    cal = nse_api.company("calendar", symbol, refresh=False)
    ann = nse_api.company("announcements", symbol, refresh=False)
    filings = nse_api.company("results", symbol, refresh=False)
    meetings = sorted({_ts(r["date"], "%d-%b-%Y") for r in cal if "Financial Results" in (r.get("purpose") or "")} - {pd.NaT})

    stamps = [_ts(a["an_dt"], "%d-%b-%Y %H:%M:%S") for a in ann if a.get("desc") in RESULT_FILINGS]
    stamps += [_ts(f.get("broadCastDate"), "%d-%b-%Y %H:%M:%S") for f in filings]
    stamps = sorted(s for s in stamps if s is not pd.NaT and not pd.isna(s))

    rows = []
    for m in meetings:
        if m < sessions[0] or m > sessions[-1] + pd.Timedelta(days=1):
            continue
        near = [s for s in stamps if m <= s.normalize() <= m + pd.Timedelta(days=2)]
        if near:
            ts = near[0]
            r = reaction_session(ts, sessions)
            timing = ("before open" if ts.time() < MARKET_OPEN else
                      "during market" if ts.time() < CLOSE_AUCTION else
                      "in the closing half-hour" if ts.time() < MARKET_CLOSE else "after close")
            if timing == "in the closing half-hour":
                # Barely in the release day's close: measure from the close
                # before the release day through the next session's close.
                start = _prev_session(ts.normalize() if ts.normalize() in sessions else r, sessions)
            else:
                start = _prev_session(r, sessions) if r is not None else None
        else:
            # Unknown time: assume after the close, and widen the reaction
            # window back to the close before the meeting so an intraday
            # release is still captured.
            ts, timing = None, "unknown"
            later = sessions[sessions > m]
            r = later[0] if len(later) else None
            start = _prev_session(m if m in sessions else r, sessions) if r is not None else None
        if r is None or start is None:
            continue
        raw = close[r] / close[start] - 1
        mret = mkt_close[r] / mkt_close[start] - 1
        b = beta.get(start, np.nan)
        rows.append({"symbol": symbol, "meeting": m, "released": ts, "timing": timing,
                     "reaction_session": r, "reaction_raw": raw,
                     "reaction_abn": raw - (b if not np.isnan(b) else 1.0) * mret})
    return pd.DataFrame(rows)


def filings_for(symbol):
    ann = nse_api.company("announcements", symbol, refresh=False)
    rows = []
    for a in ann:
        for key, (cats, _) in FILING_TYPES.items():
            if a.get("desc") in cats:
                ts = _ts(a["an_dt"], "%d-%b-%Y %H:%M:%S")
                if not pd.isna(ts):
                    rows.append({"symbol": symbol, "cond": key, "ts": ts})
    return pd.DataFrame(rows)


def deals_for(pool, start):
    d = nse_api.deals(start, refresh=False)
    d = d[d["Symbol"].isin(pool)].copy()
    d["Client"] = d["ClientName"].str.upper().str.strip()
    sides = d.groupby(["Symbol", "Date", "Client"])["Side"].transform("nunique")
    d = d[(sides == 1) & ~d["Client"].str.contains(NOT_DIRECTIONAL)]
    d["signed"] = np.where(d["Side"].str.upper() == "BUY", 1, -1) * d["Qty"] * d["Price"]
    d["inst"] = d["Client"].str.contains(INSTITUTION)
    rows = []
    for (s, day), g in d.groupby(["Symbol", "Date"]):
        inst = g.loc[g["inst"], "signed"].sum()
        other = g.loc[~g["inst"], "signed"].sum()
        if inst > 0:
            rows.append((s, "inst_deal_buy", day, inst))
        elif inst < 0:
            rows.append((s, "inst_deal_sell", day, inst))
        if other > 0:
            rows.append((s, "deal_net_buy", day, other))
        elif other < 0:
            rows.append((s, "deal_net_sell", day, other))
    return pd.DataFrame(rows, columns=["symbol", "cond", "date", "value_rs"]), d


def holdings_for(symbol):
    h = nse_api.company("holdings", symbol, refresh=False)
    rows = []
    for r in h:
        q = _ts(r.get("date"), "%d-%b-%Y")
        ts = _ts(r.get("broadcastDate"), "%d-%b-%Y %H:%M:%S")
        try:
            pct = float(r.get("pr_and_prgrp"))
        except (TypeError, ValueError):
            continue
        if not pd.isna(q) and not pd.isna(ts):
            rows.append({"quarter": q, "ts": ts, "promoter": pct})
    if not rows:
        return pd.DataFrame(columns=["symbol", "cond", "ts", "change_pp"])
    df = pd.DataFrame(rows).sort_values("quarter").drop_duplicates("quarter", keep="last")
    df["change_pp"] = df["promoter"].diff()
    out = []
    for r in df.dropna(subset=["change_pp"]).itertuples():
        if r.change_pp <= -0.5:
            out.append({"symbol": symbol, "cond": "promoter_cut", "ts": r.ts, "change_pp": r.change_pp})
        elif r.change_pp >= 0.25:
            out.append({"symbol": symbol, "cond": "promoter_raise", "ts": r.ts, "change_pp": r.change_pp})
    return pd.DataFrame(out, columns=["symbol", "cond", "ts", "change_pp"])


# ------------------------------------------------------------- study

def refresh(log=print):
    """Pull the latest per-company event data (at most once a day)."""
    pool = [universe.FOCUS] + universe.PEERS
    for s in pool:
        for kind in nse_api.ENDPOINTS:
            nse_api.company(kind, s)
    nse_api.deals(universe.HISTORY_START)
    # New results filings and filing PDFs (only unseen ones are downloaded).
    from dossier.sources import documents, financials
    for s in pool:
        financials.quarterly(s, refresh=True)
        for doc in documents.wanted(s, s == universe.FOCUS):
            documents.text(doc)
    log(f"Event data, financials and filings refreshed for {len(pool)} stocks")


def study():
    pool = [universe.FOCUS] + universe.PEERS
    stocks, idx, feats, fwd, all_abn = C.returns_panel(pool)
    mkt = idx[C.MARKET]["Close"]
    frames, results_tables = [], []

    for s in fwd:
        bars = stocks[s][0]
        sessions = bars.index
        res = results_for(s, sessions, bars["Close"], mkt.reindex(sessions), feats[s]["beta"])
        if len(res):
            results_tables.append(res)
            res = res.assign(date=res["reaction_session"])
            frames.append(res.assign(cond="results_all")[["symbol", "cond", "date"]])
            label = np.select([res["reaction_abn"] > REACTION_CUT, res["reaction_abn"] < -REACTION_CUT],
                              ["results_strong", "results_weak"], "results_muted")
            frames.append(res.assign(cond=label)[["symbol", "cond", "date"]])

        for kind_df in (filings_for(s), holdings_for(s)):
            if len(kind_df):
                kind_df = kind_df.assign(date=[reaction_session(t, sessions) for t in kind_df["ts"]]).dropna(subset=["date"])
                frames.append(kind_df[["symbol", "cond", "date"]])

    deal_events, clean_deals = deals_for(list(fwd), universe.HISTORY_START)
    frames.append(deal_events[["symbol", "cond", "date"]])

    # Fundamentals (structured results) and facts read from filing PDFs.
    from dossier import filings, fundamentals
    facts = filings.all_facts()
    fund = [fundamentals.fundamental_events(s) for s in fwd] + [fundamentals.fact_events(facts)]
    fund = pd.concat([f for f in fund if len(f)], ignore_index=True) if any(len(f) for f in fund) else pd.DataFrame()
    for s, g in (fund.groupby("symbol") if len(fund) else []):
        if s not in fwd:
            continue
        sessions = stocks[s][0].index
        g = g.assign(date=[reaction_session(t, sessions) for t in g["ts"]]).dropna(subset=["date"])
        frames.append(g[["symbol", "cond", "date"]])

    raw = pd.concat(frames, ignore_index=True)
    raw["date"] = pd.to_datetime(raw["date"])
    all_sessions = pd.DatetimeIndex(sorted(set().union(*[stocks[s][0].index for s in fwd])))
    events = _dedupe(raw, all_sessions)
    events = C.attach_returns(events, fwd, all_abn)
    catalog = {**CATALOG, **fundamentals.CATALOG}
    results, tests = C.evaluate(events, catalog)

    results_table = pd.concat(results_tables, ignore_index=True) if results_tables else pd.DataFrame()
    return {
        "method": {**C.method_note(tests), "reaction_cut": REACTION_CUT, "dedupe_sessions": DEDUPE_SESSIONS},
        "results": results,
        "results_profile": _results_profile(results_table, fwd, all_abn, stocks),
        "focus_recent": _recent(events, clean_deals),
        "upcoming": _upcoming(stocks[universe.FOCUS][0].index[-1]),
        "counts": events.groupby("cond").size().to_dict(),
        "scorecard": fundamentals.scorecard(facts),
        "facts_summary": facts.groupby(["symbol", "kind"]).size().unstack(fill_value=0).to_dict("index") if len(facts) else {},
    }


def _results_profile(tbl, fwd, all_abn, stocks):
    """How big results reactions are, versus an ordinary day of the same length."""
    if tbl.empty:
        return {}
    out = {"pool_median_abs_reaction": float(tbl["reaction_abn"].abs().median()),
           "pool_results": int(len(tbl))}
    f = tbl[tbl["symbol"] == universe.FOCUS].copy()
    bars = stocks[universe.FOCUS][0]
    ordinary = (bars["Close"].pct_change(2)).abs().median()
    out["focus_median_abs_reaction"] = float(f["reaction_abn"].abs().median()) if len(f) else None
    out["focus_ordinary_2day_move"] = float(ordinary)
    out["focus_share_up"] = float((f["reaction_raw"] > 0).mean()) if len(f) else None
    rows = []
    for r in f.sort_values("meeting").itertuples():
        after = fwd[universe.FOCUS]["1m"]["raw"].get(r.reaction_session, np.nan)
        rows.append({
            "meeting": r.meeting.date().isoformat(),
            "released": r.released.isoformat(sep=" ") if isinstance(r.released, pd.Timestamp) else None,
            "timing": r.timing, "reaction_session": r.reaction_session.date().isoformat(),
            "reaction_raw": float(r.reaction_raw), "reaction_abn": float(r.reaction_abn),
            "next_month_raw": None if np.isnan(after) else float(after),
        })
    out["focus_table"] = rows
    return out


def _recent(events, clean_deals, days=120):
    f = events[events["symbol"] == universe.FOCUS]
    last = f["date"].max() if len(f) else None
    if last is None:
        return []
    rec = f[f["date"] >= last - pd.Timedelta(days=days)].sort_values("date", ascending=False)
    from dossier.fundamentals import CATALOG as FUND
    return [{"date": d.date().isoformat(), "cond": c, "description": CATALOG.get(c) or FUND.get(c, c)}
            for d, c in zip(rec["date"], rec["cond"])]


def _upcoming(last_session):
    cal = nse_api.company("calendar", universe.FOCUS, refresh=False)
    out = []
    for r in cal:
        d = _ts(r["date"], "%d-%b-%Y")
        if not pd.isna(d) and d > last_session:
            out.append({"date": d.date().isoformat(), "purpose": r.get("purpose"), "detail": r.get("bm_desc")})
    return sorted(out, key=lambda x: x["date"])
