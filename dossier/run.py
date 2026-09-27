"""Stock Dossier command line.

    python -m dossier.run sync             # download missing NSE files, corporate actions and event data
    python -m dossier.run build NETWEB     # study one stock; writes dossier.json and report.html
    python -m dossier.run peers            # peer co-movement screen
    python -m dossier.run check            # audit + Yahoo cross-check for the whole universe
    python -m dossier.run agent            # backtest + advance the paper ledger + push to the dashboard
    python -m dossier.run agent --no-push  # same, but only write the dashboard JSON locally
    python -m dossier.run agent --show backtest  # dashboard trades show the backtest account instead
"""
import argparse
import json
import os
from datetime import datetime

import pandas as pd

from dossier import anatomy, universe
from dossier.data import CACHE_DIR, audit, build_panel, load_stocks, reconcile, sync


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, default=str)
    print(f"Wrote {path}")


def cmd_build(sym, check_yahoo):
    panel, quality = build_panel(sym, check_yahoo=check_yahoo)
    what_happens_when = None
    events_study = None
    if sym == universe.FOCUS:
        from dossier import conditions, events
        what_happens_when = conditions.study()
        events_study = events.study()
    out = os.path.join(CACHE_DIR, sym, "dossier.json")
    _write(out, {
        "symbol": sym,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "history": {"first": panel.index.min().date().isoformat(),
                    "last": panel.index.max().date().isoformat(),
                    "bars": int(len(panel))},
        "data_quality": quality,
        "anatomy": anatomy.build(panel),
        "what_happens_when": what_happens_when,
        "events": events_study,
    })
    from dossier import report
    report.render(out, panel)


def cmd_check():
    from dossier.sources import yahoo
    stocks = load_stocks()
    ydata = yahoo.fetch(sorted(stocks), start=universe.HISTORY_START)
    report = {}
    for s, (bars, events) in sorted(stocks.items()):
        rec = reconcile(bars, ydata[s]) if s in ydata else {"error": "no Yahoo data"}
        report[s] = {"bars": int(len(bars)), "first": bars.index.min().date().isoformat(),
                     "last": bars.index.max().date().isoformat(), "corporate_actions": events,
                     "issues": audit(bars, s), "yahoo": rec}
        flag = "ok" if rec.get("agrees") else "CHECK"
        print(f"{s:<11} bars={len(bars):>4} {report[s]['first']}..{report[s]['last']} "
              f"splits={len(events)} issues={len(report[s]['issues'])} "
              f"yahoo_close_mismatch={len(rec.get('close_mismatch_days', [])) if 'error' not in rec else rec['error']} [{flag}]")
    _write(os.path.join(CACHE_DIR, "data_check.json"), report)


def cmd_agent(push, show="paper"):
    from dossier import agent, dashboard

    dossier_path = os.path.join(CACHE_DIR, universe.FOCUS, "dossier.json")
    if not os.path.exists(dossier_path):
        raise SystemExit("Run `python -m dossier.run build` first; the agent reads the dossier's evidence.")
    with open(dossier_path) as f:
        dossier = json.load(f)

    bars, known, start, results, bench = agent.backtest()
    _, _, paper_book, paper_eq, state, prev = agent.paper_run()

    print()
    print(f"Backtest {start.date()} to {bars.index[-1].date()} (in-sample; costs included)")
    rows = [(o["cfg"].id, o["metrics"]) for o in results] + [(k, agent._bench_metrics(v)) for k, v in bench.items()]
    for key, m in rows:
        print(f"  {key:<8} return {m['total_return_pct']:>7.1f}%  CAGR {m['cagr_pct']:>6.1f}%  "
              f"max DD {m['max_drawdown_pct']:>6.1f}%  Sharpe {m['sharpe']:.2f}  trades {m.get('trades') if m.get('trades') is not None else '-'}")

    last = state["decisions"][-1] if state["decisions"] else None
    print()
    print(f"Paper ledger ({agent.POLICY}) since {pd.Timestamp(state['start']).date()}: "
          f"equity ₹{state['equity']:,.0f}, cash ₹{state['cash']:,.0f}, shares {state['shares']}")
    for t in paper_book.trades:
        print(f"  closed {t['entry_time'].date()} -> {t['exit_time'].date()}  {t['pnl_pct']:+.1f}%")
    if last:
        order = state.get("pending")
        print()
        print(f"Decision at the close of {last['date']}: {last['stance'].upper()}")
        if order:
            px = float(bars["Close"].iloc[-1])
            est = int(state["cash"] * order.get("weight", 0) // (px * 1.003)) if order["side"] == "buy" else state["shares"]
            print(f"  Order for the next open: {order['side'].upper()} about {est} shares (last close ₹{px:,.2f})")
        print(f"  Why: {(last['reason'] or '').replace(' | ', chr(10) + '       ') or 'no change'}")

    data = dashboard.payload(bars, start, results, bench, paper_book, dossier, show=show)
    _write(os.path.join(CACHE_DIR, universe.FOCUS, "dashboard_payload.json"), data)
    if push:
        backup = dashboard.push(data)
        print(f"Pushed to MongoDB vault_db.dashboard_snapshot (previous snapshot saved to {backup})")


def main():
    ap = argparse.ArgumentParser(prog="python -m dossier.run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync")
    b = sub.add_parser("build")
    b.add_argument("symbol", nargs="?", default=universe.FOCUS)
    b.add_argument("--no-yahoo", action="store_true", help="skip the Yahoo cross-check")
    sub.add_parser("peers")
    sub.add_parser("check")
    ag = sub.add_parser("agent")
    ag.add_argument("--no-push", action="store_true", help="write the dashboard JSON locally only")
    ag.add_argument("--show", choices=["paper", "backtest"], default="paper",
                    help="which Rs 10 lakh book the dashboard's trades show (default: the paper ledger)")
    args = ap.parse_args()

    if args.cmd == "sync":
        sync()
        from dossier import events
        events.refresh()
    elif args.cmd == "build":
        cmd_build(args.symbol.upper(), not args.no_yahoo)
    elif args.cmd == "peers":
        from dossier import peers
        rows = peers.screen()
        for r in rows:
            if "note" in r:
                print(f"{r['symbol']:<11} {r['note']}")
                continue
            lo, hi = r["resid_corr_ci95"]
            print(f"{r['symbol']:<11} {r['role']:<5} days={r['overlap_days']:>4} "
                  f"resid_corr={r['resid_corr_daily']:.2f} ({lo:.2f}-{hi:.2f}) weekly={r['resid_corr_weekly']:.2f}")
        _write(os.path.join(CACHE_DIR, universe.FOCUS, "peers.json"), rows)
    elif args.cmd == "check":
        cmd_check()
    elif args.cmd == "agent":
        cmd_agent(push=not args.no_push, show=args.show)


if __name__ == "__main__":
    main()
