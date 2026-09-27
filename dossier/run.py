"""Stock Dossier command line.

    python -m dossier.run sync             # download missing NSE files, corporate actions and event data
    python -m dossier.run build NETWEB     # study one stock; writes dossier.json and report.html
    python -m dossier.run peers            # peer co-movement screen
    python -m dossier.run check            # audit + Yahoo cross-check for the whole universe
"""
import argparse
import json
import os
from datetime import datetime

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


def main():
    ap = argparse.ArgumentParser(prog="python -m dossier.run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync")
    b = sub.add_parser("build")
    b.add_argument("symbol", nargs="?", default=universe.FOCUS)
    b.add_argument("--no-yahoo", action="store_true", help="skip the Yahoo cross-check")
    sub.add_parser("peers")
    sub.add_parser("check")
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


if __name__ == "__main__":
    main()
