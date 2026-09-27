"""Dossier Agent: a paper-trading bot for the focus stock, driven only by
what the dossier's evidence supports.

Policy v1 (fixed on 27 September 2026, before any backtest was run)
- Stance: hold the stock while the business is growing (latest published
  quarter's revenue above a year ago; allowed while no year-ago quarter is
  known yet).
- Exit: after bad results -- the first reaction trails the market by more
  than 3%, or net profit is below a year ago -- sell at the next open and
  stay out for COOL_OFF sessions. Both rules are the event study's
  "consistent, not yet confirmed" findings (dossier.events).
- Size: volatility-targeted, TARGET_VOL / 63-day realised vol, capped at
  100% of equity. This is risk control, not an edge.
- Execution: decide on day t's close, fill at day t+1's open, with full
  NSE delivery charges and slippage.
- Capital: every book (backtest configs and the paper ledger) starts with
  CAPITAL (₹10 lakh) and never receives outside money. Position size is a
  share of the book's current equity, so capital grows only by reinvested
  profit and shrinks with losses.

Honesty notes
- The exit rules were found on data that includes NETWEB 2023-2026, so
  the backtest is in-sample. Only the forward paper ledger is a real test.
- Configs B and C exist to show what sizing and the exit rules add; A is
  the only one used for paper trading.
"""
import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from dossier import conditions as C
from dossier import events as E
from dossier import fundamentals, universe
from dossier.data import CACHE_DIR, load_index_closes, load_stocks

CAPITAL = 1_000_000.0
TARGET_VOL = 0.35
COOL_OFF = 21
REACTION_CUT = E.REACTION_CUT
SLIPPAGE_BPS = 5.0
POLICY = "Dossier Agent v1"

# Rule variants, fixed on 27 September 2026 BEFORE they were tested
# (see `variant_study`). Textbook defaults, not tuned:
STOP_ATR = 3.0          # chandelier exit: highest close of 22 sessions - 3 x ATR(22)
PULLBACK_DAYS = 4       # top up on the 4th down day in a row ...
PULLBACK_ADD = 0.25     # ... by 25% of equity, capped at 100% invested ...
PULLBACK_HOLD = 21      # ... and trim back to the base position after 21 sessions
SMART_MIN_WAIT = 5      # smart re-entry: at least 5 sessions, then first close above the 20-day average


# ------------------------------------------------------------------ costs

def charges(value, side):
    """NSE equity-delivery charges for one leg, in rupees (Groww-style schedule).

    Brokerage ₹20 or 0.1% (lower), STT 0.1%, exchange 0.00297%, SEBI ₹10/crore,
    stamp duty 0.015% on buys, GST 18% on brokerage + exchange + SEBI, DP ₹15.93
    on sells, plus SLIPPAGE_BPS of slippage. Reconcile against a real contract
    note before relying on the rupee totals.
    """
    brokerage = min(20.0, 0.001 * value)
    stt = 0.001 * value
    exchange = 0.0000297 * value
    sebi = value * 10 / 1e7
    stamp = 0.00015 * value if side == "buy" else 0.0
    gst = 0.18 * (brokerage + exchange + sebi)
    dp = 15.93 if side == "sell" else 0.0
    slippage = value * SLIPPAGE_BPS / 1e4
    return brokerage + stt + exchange + sebi + stamp + gst + dp + slippage


def round_trip_pct(value):
    return 100 * (charges(value, "buy") + charges(value, "sell")) / value


# ------------------------------------------------------------------ inputs

def inputs(symbol=universe.FOCUS):
    """Everything the agent may know, indexed by the session it became known."""
    stocks = load_stocks([symbol])
    bars = stocks[symbol][0]
    idx = load_index_closes()
    feats = C.features(bars, idx)
    sessions = bars.index

    res = E.results_for(symbol, sessions, bars["Close"], idx[C.MARKET]["Close"].reindex(sessions), feats["beta"])
    q = fundamentals.metrics(symbol)

    known = pd.DataFrame(index=sessions)
    known["weak_results"] = False
    known["profit_decline"] = False
    known["note"] = ""
    for r in res.itertuples():
        if r.reaction_abn < -REACTION_CUT and r.reaction_session in known.index:
            known.at[r.reaction_session, "weak_results"] = True
            known.at[r.reaction_session, "note"] += (f"Results {r.meeting.date()}: first reaction "
                                                     f"{r.reaction_abn:+.1%} vs market. ")
    growth = pd.Series(np.nan, index=sessions)
    growth_note = pd.Series("", index=sessions, dtype=object)
    for r in q.itertuples():
        if pd.isna(r.published):
            continue
        s = E.reaction_session(r.published, sessions)
        if s is None:
            continue
        if not np.isnan(r.pat_yoy) and r.pat_yoy < 0:
            known.at[s, "profit_decline"] = True
            known.at[s, "note"] += f"Net profit {r.pat_yoy:+.0%} vs a year ago (quarter ended {r.period_end.date()}). "
        growth.loc[s] = r.revenue_yoy
        growth_note.loc[s] = (f"revenue {r.revenue_yoy:+.0%} vs a year ago" if not np.isnan(r.revenue_yoy)
                              else "no year-ago quarter yet") + f" (quarter ended {r.period_end.date()})"
    known["revenue_yoy"] = growth.ffill()
    known["growth_note"] = growth_note.replace("", np.nan).ffill().fillna("no results published yet")
    known["vol63"] = np.log(bars["Close"]).diff().rolling(63).std() * math.sqrt(252)
    # Price context for the rule variants (all known at the close).
    c = bars["Close"]
    prev = c.shift(1)
    tr = pd.concat([bars["High"] - bars["Low"], (bars["High"] - prev).abs(), (bars["Low"] - prev).abs()], axis=1).max(axis=1)
    known["sma20"] = c.rolling(20).mean()
    known["chandelier"] = c.rolling(22).max() - STOP_ATR * tr.rolling(22).mean()
    known["down_streak"] = feats["down_streak"]
    return bars, known


# ------------------------------------------------------------------ engine

@dataclass
class Config:
    id: str
    name: str
    use_exits: bool = True
    vol_target: bool = True
    growth_filter: bool = True
    stop: bool = False            # variant 1: chandelier price stop, re-enter above the 20-day average
    pullback: bool = False        # variant 2: top up on pullbacks while the business is healthy
    smart_reentry: bool = False   # variant 3: re-enter on recovery instead of a fixed 21-session wait


@dataclass
class Book:
    cash: float = CAPITAL
    shares: int = 0
    entry: dict = None
    cool_until: int = -1
    wait_recover: bool = False
    topup_until: int = -1
    base_shares: int = 0
    pending: dict = None
    trades: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    costs: float = 0.0


def _decide(cfg, i, day, bars, known, book):
    """Stance at day's close -> an order for the next open (or None)."""
    k = known.loc[day]
    close = float(bars.at[day, "Close"])
    reasons = []
    bad = cfg.use_exits and (bool(k["weak_results"]) or bool(k["profit_decline"]))
    if bad:
        reasons.append("Bad results: " + k["note"].strip())
    growth_ok = (not cfg.growth_filter) or np.isnan(k["revenue_yoy"]) or k["revenue_yoy"] > 0
    reasons.append(f"Business: {k['growth_note']}" + ("" if growth_ok else " (not growing)"))
    cooling = cfg.use_exits and i <= book.cool_until

    def after_bad():
        if cfg.smart_reentry:
            book.cool_until, book.wait_recover = i + SMART_MIN_WAIT, True
        else:
            book.cool_until = i + COOL_OFF

    if book.shares > 0:
        if bad or not growth_ok:
            if bad:
                after_bad()
            book.topup_until = -1
            return {"side": "sell", "reason": " | ".join(reasons)}, "exit"
        if cfg.stop and not np.isnan(k["chandelier"]) and close < k["chandelier"]:
            book.wait_recover, book.topup_until = True, -1
            reasons.append(f"Price stop: close {close:,.2f} below {k['chandelier']:,.2f} "
                           f"(22-session high minus {STOP_ATR:g} x ATR)")
            return {"side": "sell", "reason": " | ".join(reasons)}, "exit"
        if cfg.pullback:
            if book.topup_until >= 0 and i >= book.topup_until:
                book.topup_until = -1
                extra = book.shares - book.base_shares
                if extra > 0:
                    return {"side": "trim", "shares": extra,
                            "reason": f"Pullback top-up held {PULLBACK_HOLD} sessions; trim back to the base position"}, "trim"
            elif book.topup_until < 0 and k["down_streak"] == PULLBACK_DAYS:
                book.topup_until = i + PULLBACK_HOLD
                return {"side": "add", "weight": PULLBACK_ADD,
                        "reason": " | ".join(reasons + [f"{PULLBACK_DAYS} down days in a row while healthy: add "
                                                         f"{PULLBACK_ADD:.0%} of equity"])}, "add"
        return None, "hold"

    if bad:
        after_bad()
    if cooling or bad:
        reasons.append(f"Cooling off after bad results for {book.cool_until - i} more sessions")
        return None, "wait"
    if book.wait_recover and not (not np.isnan(k["sma20"]) and close > k["sma20"]):
        reasons.append("Waiting for a close above the 20-day average before buying back")
        return None, "wait"
    if not growth_ok:
        return None, "wait"
    vol = k["vol63"]
    if np.isnan(vol):
        reasons.append("Not enough history for sizing yet")
        return None, "wait"
    book.wait_recover = False
    weight = min(1.0, TARGET_VOL / vol) if cfg.vol_target else 1.0
    reasons.append(f"Size {weight:.0%} of equity (63-day volatility {vol:.0%}, target {TARGET_VOL:.0%})"
                   if cfg.vol_target else "Size 100% of equity")
    return {"side": "buy", "weight": weight, "reason": " | ".join(reasons)}, "enter"


def _fill(order, day, bars, book, cfg_id):
    px = float(bars.at[day, "Open"]) if not np.isnan(bars.at[day, "Open"]) else float(bars.at[day, "Close"])
    if order["side"] == "buy":
        equity = book.cash
        budget = equity * order["weight"]
        shares = int(budget // (px * (1 + 0.003)))
        if shares <= 0:
            return
        value = shares * px
        cost = charges(value, "buy")
        book.cash -= value + cost
        book.costs += cost
        book.shares = book.base_shares = shares
        book.entry = {"time": day, "price": px, "shares": shares, "cost": cost, "reason": order["reason"]}
    elif order["side"] == "add":
        equity = book.cash + book.shares * px
        room = min(order["weight"] * equity, equity - book.shares * px, book.cash)
        add = int(max(0.0, room) // (px * (1 + 0.003)))
        if add <= 0:
            return
        value = add * px
        cost = charges(value, "buy")
        book.cash -= value + cost
        book.costs += cost
        e = book.entry
        e["price"] = (e["price"] * e["shares"] + value) / (e["shares"] + add)
        e["shares"] += add
        e["cost"] += cost
        book.shares += add
    elif order["side"] == "trim":
        q = min(order["shares"], book.shares)
        e = book.entry
        value = q * px
        cost = charges(value, "sell")
        buy_cost = e["cost"] * q / e["shares"]
        pnl = value - cost - (q * e["price"] + buy_cost)
        book.cash += value - cost
        book.costs += cost
        book.trades.append({"entry_time": e["time"], "entry_price": e["price"], "exit_time": day, "exit_price": px,
                            "shares": q, "pnl": pnl, "pnl_pct": 100 * pnl / (q * e["price"]),
                            "entry_reason": e["reason"], "exit_reason": order["reason"], "config": cfg_id})
        e["shares"] -= q
        e["cost"] -= buy_cost
        book.shares -= q
    else:
        value = book.shares * px
        cost = charges(value, "sell")
        book.cash += value - cost
        book.costs += cost
        e = book.entry
        pnl = value - cost - (e["shares"] * e["price"] + e["cost"])
        book.trades.append({"entry_time": e["time"], "entry_price": e["price"], "exit_time": day, "exit_price": px,
                            "shares": e["shares"], "pnl": pnl, "pnl_pct": 100 * pnl / (e["shares"] * e["price"]),
                            "entry_reason": e["reason"], "exit_reason": order["reason"], "config": cfg_id})
        book.shares, book.entry = 0, None


def simulate(cfg, bars, known, start, book=None, log_decisions=False):
    """Run the policy from session `start` to the last bar. Returns (book, equity)."""
    book = book or Book()
    days = bars.index
    equity = []
    for i, day in enumerate(days):
        if day < start:
            continue
        if book.pending:
            _fill(book.pending, day, bars, book, cfg.id)
            book.pending = None
        order, stance = _decide(cfg, i, day, bars, known, book)
        if log_decisions:
            book.decisions.append({"date": day.date().isoformat(), "stance": stance,
                                   "order": order["side"] if order else None,
                                   "reason": order["reason"] if order else None})
        book.pending = order
        equity.append((day, book.cash + book.shares * float(bars.at[day, "Close"])))
    return book, pd.Series(dict(equity))


# ------------------------------------------------------------------ metrics

def metrics(eq, book, bars):
    r = eq.pct_change().dropna()
    years = len(eq) / 248
    total = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    trades = book.trades
    pcts = [t["pnl_pct"] for t in trades]
    holds = [(t["exit_time"] - t["entry_time"]).days for t in trades]
    last = float(bars["Close"].iloc[-1])
    open_unrl = (book.shares * last - (book.entry["shares"] * book.entry["price"] + book.entry["cost"])) if book.entry else 0.0
    return {
        "total_return_pct": float(100 * total), "cagr_pct": float(100 * cagr),
        "sharpe": float(r.mean() / r.std() * math.sqrt(248)) if r.std() > 0 else None,
        "max_drawdown_pct": float(100 * dd), "calmar": float(cagr / abs(dd)) if dd < 0 else None,
        "trades": len(trades), "win_rate_pct": 100 * float(np.mean([p > 0 for p in pcts])) if pcts else None,
        "expectancy_pct": float(np.mean(pcts)) if pcts else None,
        "median_hold_days": float(np.median(holds)) if holds else None,
        "total_costs": float(book.costs), "cash_pct_final": float(100 * book.cash / eq.iloc[-1]),
        "open_unrealized_final": float(open_unrl), "final_equity": float(eq.iloc[-1]),
    }


CONFIGS = [
    Config("A", "A. Dossier Agent v1: hold while growing, step aside after bad results, volatility-sized"),
    Config("B", "B. Same rules at full size (no volatility sizing)", vol_target=False),
    Config("C", "C. Volatility-sized hold with NO bad-results exits (shows what the exits add)", use_exits=False, growth_filter=False),
]


def backtest():
    bars, known = inputs()
    start = known["vol63"].first_valid_index()
    out, books = [], {}
    for cfg in CONFIGS + VARIANTS[1:]:
        book, eq = simulate(cfg, bars, known, start)
        exposure = _exposure(book, eq)
        m = metrics(eq, book, bars)
        m["exposure_pct"] = exposure
        out.append({"cfg": cfg, "book": book, "equity": eq, "metrics": m})
        books[cfg.id] = book

    close = bars["Close"].loc[start:]
    first_open = float(bars["Open"].loc[start:].iloc[1])
    bh_shares = int(CAPITAL // (first_open * 1.003))
    bh_cost = charges(bh_shares * first_open, "buy")
    bh = (CAPITAL - bh_shares * first_open - bh_cost) + bh_shares * close
    bh.iloc[0] = CAPITAL
    nifty = load_index_closes()["NIFTY"]["Close"].reindex(close.index).ffill()
    nifty_eq = CAPITAL * nifty / nifty.iloc[0]
    return bars, known, start, out, {"CONTROL": bh, "NIFTY": nifty_eq}


def _exposure(book, eq):
    days_in = 0
    for t in book.trades:
        days_in += ((eq.index >= t["entry_time"]) & (eq.index < t["exit_time"])).sum()
    if book.entry:
        days_in += (eq.index >= book.entry["time"]).sum()
    return float(100 * days_in / len(eq))


def _bench_metrics(eq):
    r = eq.pct_change().dropna()
    years = len(eq) / 248
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    dd = (eq / eq.cummax() - 1).min()
    return {"total_return_pct": float(100 * (eq.iloc[-1] / eq.iloc[0] - 1)), "cagr_pct": float(100 * cagr),
            "sharpe": float(r.mean() / r.std() * math.sqrt(248)), "max_drawdown_pct": float(100 * dd),
            "calmar": float(cagr / abs(dd)) if dd < 0 else None, "trades": None, "exposure_pct": 100.0,
            "cash_pct_final": 0.0, "open_unrealized_final": None}


# ------------------------------------------------------------------ paper ledger

PAPER_FILE = os.path.join(CACHE_DIR, universe.FOCUS, "paper_state.json")


def _book_to_json(book, start, last):
    def enc(x):
        if isinstance(x, pd.Timestamp):
            return x.isoformat()
        return x
    return {"policy": POLICY, "start": start.isoformat(), "last_session": last.isoformat(),
            "cash": book.cash, "shares": book.shares, "costs": book.costs, "cool_until_date": None,
            "entry": {k: enc(v) for k, v in book.entry.items()} if book.entry else None,
            "pending": book.pending, "trades": [{k: enc(v) for k, v in t.items()} for t in book.trades],
            "decisions": book.decisions[-400:]}


def paper_run():
    """Advance the paper ledger to the latest session. Manual: run after the close.

    The first run starts a fresh ₹10 lakh book at the latest session. Every
    later run replays the policy from that start date on the data now
    available; because the policy only uses information known at each
    close, earlier decisions cannot change unless the underlying data is
    corrected (which is then visible in the decision log).
    """
    bars, known = inputs()
    if os.path.exists(PAPER_FILE):
        with open(PAPER_FILE) as f:
            prev = json.load(f)
        start = pd.Timestamp(prev["start"])
    else:
        prev, start = None, bars.index[-1]
    cfg = CONFIGS[0]
    book, eq = simulate(cfg, bars, known, start, log_decisions=True)
    state = _book_to_json(book, start, bars.index[-1])
    state["equity"] = float(eq.iloc[-1])
    os.makedirs(os.path.dirname(PAPER_FILE), exist_ok=True)
    with open(PAPER_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)
    return bars, known, book, eq, state, prev


# ------------------------------------------------------------------ variant study

VARIANTS = [
    Config("A", "A. Current agent (baseline)"),
    # Ids D-F so the dashboard's equity chart gives each its own colour.
    Config("D", "D. Variant 1 (REJECTED): A + price stop (chandelier 22 / 3 x ATR), buy back above the 20-day average", stop=True),
    Config("E", "E. Variant 2 (REJECTED): A + pullback top-up on the 4th down day while healthy", pullback=True),
    Config("F", "F. Variant 3 (REJECTED): A + smart re-entry, buy back on a close above the 20-day average", smart_reentry=True),
]
KEEP_RULE = ("A variant is kept only if it raises the Sharpe ratio on the focus stock AND on at least 7 of "
             "the 10 peers, and the peers' median max drawdown is no deeper than the baseline's.")


def variant_study(symbols=None):
    """Run every variant on the focus stock and each peer (same rules, each stock's
    own data). Returns {symbol: {config_id: metrics}} and the verdict per variant."""
    symbols = symbols or [universe.FOCUS] + universe.PEERS
    table = {}
    for s in symbols:
        try:
            bars, known = inputs(s)
        except Exception as e:     # a stock without results data cannot be traded by this policy
            table[s] = {"error": f"{type(e).__name__}: {e}"}
            continue
        start = known["vol63"].first_valid_index()
        row = {}
        for cfg in VARIANTS:
            book, eq = simulate(cfg, bars, known, start)
            m = metrics(eq, book, bars)
            m["exposure_pct"] = _exposure(book, eq)
            row[cfg.id] = m
        close = bars["Close"].loc[start:]
        row["HOLD"] = _bench_metrics(CAPITAL * close / close.iloc[0])
        table[s] = row

    peers = [s for s in symbols if s != universe.FOCUS and "error" not in table[s]]
    verdicts = {}
    for cfg in VARIANTS[1:]:
        focus_up = table[universe.FOCUS][cfg.id]["sharpe"] > table[universe.FOCUS]["A"]["sharpe"]
        peer_up = sum(table[s][cfg.id]["sharpe"] > table[s]["A"]["sharpe"] for s in peers)
        dd_base = float(np.median([table[s]["A"]["max_drawdown_pct"] for s in peers]))
        dd_var = float(np.median([table[s][cfg.id]["max_drawdown_pct"] for s in peers]))
        keep = focus_up and peer_up >= 7 and dd_var >= dd_base
        verdicts[cfg.id] = {"name": cfg.name, "focus_sharpe_up": bool(focus_up), "peers_sharpe_up": int(peer_up),
                            "peers": len(peers), "peer_median_dd_base": dd_base, "peer_median_dd_variant": dd_var,
                            "keep": bool(keep)}
    return table, verdicts
