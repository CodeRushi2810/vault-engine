"""Export the agent's backtest and paper ledger in the Vault dashboard's format
and push it to MongoDB (vault_db.dashboard_snapshot).

Format: the dashboard's /api/mongo_dashboard route returns the newest
snapshot's `data`; the Backtest tab reads `data.backtest` (configs,
benchmarks, signal_screen, costs, provenance, headline, warnings) and the
trade tabs read `data.trades` (the fields written by core/run_pipeline.py).

Safety: the existing snapshot is saved to data/dossier/_dashboard_backup/
before anything is written. `trades`, `backtest`, the run metadata (kind,
strategy, run_id, disclaimer, headline) and the focus stock's `market_data`
/ `prevClosePrices` entries are replaced; every other key already in the
snapshot (e.g. systemConfig) is kept.
"""
import json
import os
from datetime import datetime

import pandas as pd

from dossier import agent as A
from dossier import universe
from dossier.data import BASE_DIR, CACHE_DIR

BACKUP_DIR = os.path.join(CACHE_DIR, "_dashboard_backup")
USED_BY_AGENT = {"results_weak", "profit_decline"}


def _fy(ts):
    return f"FY{str(ts.year - 1)[-2:]}-{str(ts.year)[-2:]}" if ts.month < 4 else f"FY{str(ts.year)[-2:]}-{str(ts.year + 1)[-2:]}"


def _trade_row(status, entry_time, entry_price, exit_time, exit_price, shares, strategy):
    entry_time, exit_time = pd.Timestamp(entry_time), pd.Timestamp(exit_time)
    cost_basis = entry_price * shares
    pnl = (exit_price - entry_price) * shares
    return {
        "Status": status,
        "Entry_Time": entry_time.strftime("%Y-%m-%d 09:15:00"),
        "Exit_Time": exit_time.strftime("%Y-%m-%d 15:30:00") if status == "OPEN" else exit_time.strftime("%Y-%m-%d 09:15:00"),
        "Entry_Time_Formatted": entry_time.strftime("%d %B %Y, 09:15"),
        "Exit_Time_Formatted": exit_time.strftime("%d %B %Y, 15:30") if status == "OPEN" else exit_time.strftime("%d %B %Y, 09:15"),
        "Financial_Year": _fy(entry_time), "Stock": universe.FOCUS, "Strategy": strategy,
        "Entry_Price": round(float(entry_price), 2), "Exit_Price": round(float(exit_price), 2), "Shares": int(shares),
        "Cost_Basis": round(float(cost_basis), 2), "PnL_Amount": round(float(pnl), 2),
        "PnL_Percent": float(100 * pnl / cost_basis) if cost_basis else 0.0, "Win_Loss": int(pnl > 0),
    }


def backtest_trades(book, bars):
    """The backtest account (config A) as dashboard trades, open position included,
    so the dashboard's cash formula shows that ₹10 lakh book as it grew."""
    last_px, last_day = float(bars["Close"].iloc[-1]), bars.index[-1]
    rows = [_trade_row("CLOSED", t["entry_time"], t["entry_price"], t["exit_time"], t["exit_price"],
                       t["shares"], f"{A.POLICY} · backtest") for t in book.trades]
    if book.entry:
        e = book.entry
        rows.append(_trade_row("OPEN", e["time"], e["price"], last_day, last_px, e["shares"], f"{A.POLICY} · backtest"))
    return rows


def trades(paper_book, bars):
    """The paper ledger only.

    The dashboard computes cash as ₹10,00,000 + realised P&L - open cost
    from this list, so it must hold the real paper book (which starts at
    ₹10 lakh and grows only by its own P&L). Backtest trades live in the
    `backtest` block; mixing them in here would add simulated profit to the
    live capital. P&L is price P&L, as in core/run_pipeline.py.
    """
    last_px, last_day = float(bars["Close"].iloc[-1]), bars.index[-1]
    rows = []
    for t in paper_book.trades:
        rows.append(_trade_row("CLOSED", t["entry_time"], t["entry_price"], t["exit_time"], t["exit_price"],
                               t["shares"], f"{A.POLICY} · paper"))
    if paper_book.entry:
        e = paper_book.entry
        rows.append(_trade_row("OPEN", e["time"], e["price"], last_day, last_px, e["shares"], f"{A.POLICY} · paper"))
    return rows


def _weekly(eq):
    w = eq.resample("W-FRI").last().dropna()
    if w.index[-1] != eq.index[-1]:
        w.loc[eq.index[-1]] = eq.iloc[-1]
    return [{"d": d.date().isoformat(), "v": round(float(v), 2)} for d, v in w.items()]


def _stock_notes(a):
    """Caveats that depend on which stock this is. The exit rules were found on NETWEB's group."""
    if universe.FOCUS == "NETWEB":
        return [
            "In-sample: the bad-results exit was found on 2023-2026 data that includes NETWEB's own results.",
            f"Only {a['trades']} completed trades; one avoided crash (January-February 2025) drives most of the risk improvement.",
            "Single stock: the result depends on NETWEB having risen about 5x; a falling stock would look very different.",
        ]
    return [
        f"Out-of-sample: the rules were found on NETWEB and its peers and are applied to {universe.FOCUS} unchanged.",
        f"Only {a['trades']} completed trades; a handful of results days decide the record.",
        f"Single stock: the result depends on how {universe.FOCUS} itself moved over this window.",
    ]


def _screen(dossier):
    rows = []
    studies = [(dossier.get("what_happens_when") or {}).get("results", []), (dossier.get("events") or {}).get("results", [])]
    for res in studies:
        for r in res:
            p, d, v = r["pooled"], r["discovery"], r["validation"]
            if not p.get("n"):
                continue
            stable = d.get("mean") is not None and v.get("mean") is not None and (d["mean"] > 0) == (v["mean"] > 0)
            rows.append({
                "signal": r["description"], "horizon_days": r["h"], "n": p["n"],
                "freq_pct": None, "mean_pct": 100 * r["pooled_raw"]["mean"] if r["pooled_raw"].get("mean") is not None else None,
                "edge_pct": 100 * p["mean"], "hit_pct": 100 * p["hit_rate"],
                "t_stat": p["mean"] / p["se"] if p.get("se") else None,
                "h1_edge_pct": 100 * d["mean"] if d.get("mean") is not None else None,
                "h2_edge_pct": 100 * v["mean"] if v.get("mean") is not None else None,
                "stable": bool(stable), "verdict": r["verdict"],
                "is_current_strategy": r["condition"] in USED_BY_AGENT,
            })
    return rows


def backtest_block(bars, start, results, bench, dossier):
    cost_1l = {k: round(v, 4) for k, v in {
        "brokerage": min(20.0, 100.0), "stt": 100.0, "exchange_txn": 2.97, "sebi": 0.1, "ipft": 0.0,
        "stamp_duty": 15.0, "gst": 0.18 * (20.0 + 2.97 + 0.1), "dp": 0.0, "slippage": 100000 * A.SLIPPAGE_BPS / 1e4}.items()}
    configs = []
    for o in results:
        cfg, m, book = o["cfg"], o["metrics"], o["book"]
        reasons = {}
        for t in book.trades:
            r = t["exit_reason"]
            key = ("bad results" if r.startswith("Bad results") else "price stop" if "Price stop" in r
                   else "pullback trim" if r.startswith("Pullback") else "business stopped growing")
            reasons[key] = reasons.get(key, 0) + 1
        monthly = {}
        for t in book.trades:
            k = pd.Timestamp(t["exit_time"]).strftime("%Y-%m")
            monthly[k] = monthly.get(k, 0) + round(t["pnl"], 2)
        configs.append({"id": cfg.id, "name": cfg.name, "is_legacy": False, "has_loss_exit": cfg.use_exits,
                        "entry_signal": "hold while growing" if cfg.growth_filter else "always hold",
                        "metrics": m, "equity": _weekly(o["equity"]), "exit_reasons": reasons, "monthly_net_pnl": monthly})
    benchmarks = []
    for key, name in (("CONTROL", f"-- BENCHMARK: buy & hold {universe.FOCUS}"), ("NIFTY", "-- BENCHMARK: Nifty 50")):
        benchmarks.append({"id": key, "name": name, "kind": "buy_and_hold", "metrics": A._bench_metrics(bench[key]),
                           "equity": _weekly(bench[key])})

    a = results[0]["metrics"]
    study_notes = []
    study_path = os.path.join(CACHE_DIR, universe.FOCUS, "variant_study.json")
    if os.path.exists(study_path):
        with open(study_path) as f:
            study = json.load(f)
        for vid, v in study["verdicts"].items():
            study_notes.append(f"{v['name'].split(':')[0]}: {'kept' if v['keep'] else 'rejected'} by the rule fixed before "
                               f"testing (Sharpe up on {universe.FOCUS}: {'yes' if v['focus_sharpe_up'] else 'no'}; "
                               f"on {v['peers_sharpe_up']} of {v['peers']} peers; peer median max drawdown "
                               f"{v['peer_median_dd_base']:.0f}% -> {v['peer_median_dd_variant']:.0f}%).")
        tab = study["table"]
        peers = [s_ for s_ in tab if s_ != universe.FOCUS and "error" not in tab[s_]]
        hold_beats = sum(tab[s_]["HOLD"]["total_return_pct"] > tab[s_]["A"]["total_return_pct"] for s_ in peers)
        shallower = sum(tab[s_]["A"]["max_drawdown_pct"] > tab[s_]["HOLD"]["max_drawdown_pct"] for s_ in peers)
        study_notes.append(f"Across the {len(peers)} peers, agent A's rules cut the worst drawdown on {shallower} "
                           f"but earned less than simply holding on {hold_beats}: the exits work as insurance, at a cost.")
    control = benchmarks[0]["metrics"]["total_return_pct"]
    beats = all(o["metrics"]["total_return_pct"] < control for o in results)
    conclusion = (f"{A.POLICY} returned {a['total_return_pct']:.0f}% against {control:.0f}% for simply holding "
                  f"{universe.FOCUS}, with a worst drawdown of {a['max_drawdown_pct']:.0f}% against "
                  f"{benchmarks[0]['metrics']['max_drawdown_pct']:.0f}%. The exit rule was discovered on data that "
                  "includes these very events, so this is in-sample; only the paper ledger is a real test.")
    return {
        "schema_version": 1, "generated_at": datetime.now().isoformat(timespec="seconds"), "kind": "dossier_agent",
        "disclaimer": "Paper-trading research for one stock. Not investment advice; not live trading state.",
        "provenance": {
            "data_dir": "data/dossier/_nse (NSE official daily files)", "corporate_action_adjusted": True,
            "universe_label": f"{universe.FOCUS} only (single-stock agent); evidence pooled over {universe.FOCUS} + {len(universe.PEERS)} peers",
            "symbols": 1, "rows": int(len(bars.loc[start:])), "date_from": start.date().isoformat(),
            "date_to": bars.index[-1].date().isoformat(),
            "fill_convention": "decide at the session close, fill at the next session's open",
            "fill_reason": "NSE's official file has a real open price for every session",
        },
        "costs": {"note": "Groww-style delivery schedule plus slippage; reconcile against a real contract note.",
                  "round_trip_pct": {f"at_{k}": round(A.round_trip_pct(v), 4) for k, v in
                                     (("10k", 1e4), ("25k", 2.5e4), ("100k", 1e5), ("500k", 5e5))},
                  "buy_leg_on_1L": cost_1l, "slippage_bps_per_side": A.SLIPPAGE_BPS},
        "window": {"start": start.date().isoformat(), "end": bars.index[-1].date().isoformat()},
        "configs": configs, "benchmarks": benchmarks,
        "signal_screen": _screen(dossier),
        "headline": {"control_beats_every_strategy": beats, "conclusion": conclusion,
                     "control_return_pct": control, "legacy_reported_return_pct": None,
                     "legacy_win_rate_pct": None, "legacy_hidden_open_unrealized": None},
        "warnings": study_notes + _stock_notes(a) + [
            "The exit evidence is 'consistent, not yet confirmed': strong on the full sample and the same direction in both halves, but the earlier half alone is not significant.",
            "Charges follow a delivery schedule with 5 bps slippage per side; confirm against a real contract note.",
            f"Every config starts with ₹{A.CAPITAL / 1e5:.0f} lakh and only reinvests its own profits; no money is ever added.",
            "The dashboard's trades and cash show the forward paper ledger only (also started at ₹10 lakh); these backtest trades are not in them.",
            "Dashboard trade P&L is price-only (as elsewhere on the dashboard); the metrics above are net of charges.",
        ],
    }


def payload(bars, start, results, bench, paper_book, dossier, show="paper"):
    """`show` picks which ₹10 lakh book the dashboard's trades/cash display:
    'paper' (the forward ledger) or 'backtest' (config A's simulated history)."""
    last_px = float(bars["Close"].iloc[-1])
    unrl = (paper_book.shares * last_px - paper_book.entry["shares"] * paper_book.entry["price"]) if paper_book.entry else 0.0
    realised = sum(t["pnl"] for t in paper_book.trades)
    equity = paper_book.cash + paper_book.shares * last_px
    return {
        # Top-level metadata describes the paper ledger (it replaces older
        # metadata from earlier strategies; the backup keeps the originals).
        "kind": "live_paper", "strategy": A.POLICY, "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run_id": f"dossier-{bars.index[-1]:%Y%m%d}",
        "disclaimer": f"Forward PAPER trading of {A.POLICY} on {universe.FOCUS}. No orders are placed. "
                      f"Rs {A.CAPITAL:,.0f} notional starting capital.",
        "headline": {"closed_trades": len(paper_book.trades), "open_positions": int(paper_book.shares > 0),
                     "wins": sum(t["pnl"] > 0 for t in paper_book.trades),
                     "losses": sum(t["pnl"] <= 0 for t in paper_book.trades),
                     "realised_pnl": round(realised, 2), "unrealised_pnl": round(unrl, 2),
                     "net_pnl_mark_to_market": round(equity - A.CAPITAL, 2),
                     "return_on_initial_pct": round(100 * (equity / A.CAPITAL - 1), 3), "cash": round(paper_book.cash, 2),
                     "pending_order": paper_book.pending},
        "trades": backtest_trades(results[0]["book"], bars) if show == "backtest" else trades(paper_book, bars),
        "trades_view": show,
        "backtest": backtest_block(bars, start, results, bench, dossier),
        "market_data": {universe.FOCUS: float(bars["Close"].iloc[-1])},
        "prevClosePrices": {universe.FOCUS: {"prev_close": float(bars["Close"].iloc[-2])}},
    }


def push(data):
    """Back up the current snapshot, merge in `data`, and replace the snapshot."""
    from dotenv import load_dotenv
    from pymongo import MongoClient

    load_dotenv(os.path.join(BASE_DIR, ".env"))
    uri = os.getenv("MONGO_URI")
    if not uri:
        raise RuntimeError("MONGO_URI is not set in .env")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    col = client["vault_db"]["dashboard_snapshot"]
    current = col.find_one({}, sort=[("_id", -1)])

    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup = os.path.join(BACKUP_DIR, f"snapshot_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(backup, "w") as f:
        json.dump({k: v for k, v in (current or {}).items() if k != "_id"}, f, default=str)

    existing = dict((current or {}).get("data") or {})
    merged = dict(existing)
    for key in ("kind", "strategy", "generated_at", "run_id", "disclaimer", "headline", "trades_view"):
        merged[key] = data[key]
    merged["trades"] = data["trades"]
    merged["backtest"] = data["backtest"]
    merged["market_data"] = {**(existing.get("market_data") or {}), **data["market_data"]}
    merged["prevClosePrices"] = {**(existing.get("prevClosePrices") or {}), **data["prevClosePrices"]}

    col.delete_many({})
    col.insert_one({"data": merged})
    return backup
