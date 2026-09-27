"""The whole evening routine in one command. Run after about 6pm on trading days:

    python -m dossier.daily               # sync, study, trade, publish
    python -m dossier.daily --no-publish  # everything except the MongoDB push
    python -m dossier.daily --variants    # also re-run the rule-variant study (about 2 minutes)

Steps, in order; the run stops at the first failure and says which step:
  1. Sync        NSE daily files, corporate actions, events, results filings, filing PDFs
  2. Peers       how closely each comparison company moves with the stock
  3. Study       the dossier (price, conditions, events, fundamentals), checked against Yahoo
  4. Variants    optional: the pre-registered rule-variant test
  5. Agent       advance the paper account, write report.html
  6. Publish     push the report data (and a page snapshot) to MongoDB for the web app
A log of each run is kept in data/dossier/logs/.
"""
import argparse
import contextlib
import io
import os
import sys
import time
import traceback
from datetime import datetime

from dossier import universe
from dossier.data import CACHE_DIR

LOG_DIR = os.path.join(CACHE_DIR, "logs")


class Tee(io.TextIOBase):
    """Write to the console and the log file at the same time."""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
            st.flush()
        return len(s)


def main():
    ap = argparse.ArgumentParser(prog="python -m dossier.daily")
    ap.add_argument("--no-publish", action="store_true", help="skip the MongoDB push")
    ap.add_argument("--variants", action="store_true", help="also re-run the rule-variant study")
    args = ap.parse_args()

    from dossier import run
    sym = universe.FOCUS
    steps = [
        ("Sync", lambda: (run.sync(), __import__("dossier.events", fromlist=["refresh"]).refresh())),
        ("Peers", run.cmd_peers),
        ("Study", lambda: run.cmd_build(sym, check_yahoo=True)),
    ]
    if args.variants:
        steps.append(("Variants", run.cmd_variants))
    steps.append(("Agent", lambda: run.cmd_agent(push=False)))
    if not args.no_publish:
        steps.append(("Publish", _publish))

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"daily_{datetime.now():%Y%m%d_%H%M}.log")
    with open(log_path, "w", encoding="utf-8") as log, contextlib.redirect_stdout(Tee(sys.stdout, log)):
        if datetime.now().hour < 18:
            print("Note: before 6pm NSE may not have published today's file yet; today will be picked up on the next run.")
        start = time.time()
        for n, (name, fn) in enumerate(steps, 1):
            t0 = time.time()
            print(f"\n[{n}/{len(steps)}] {name} ...")
            try:
                fn()
            except Exception:
                traceback.print_exc(file=sys.stdout)
                print(f"\nStopped: step '{name}' failed. Nothing after it ran. Log: {log_path}")
                sys.exit(1)
            print(f"[{n}/{len(steps)}] {name} done in {time.time() - t0:.0f}s")
        _signal_summary(sym)
        print(f"\nAll done in {(time.time() - start) / 60:.1f} minutes. Report: {os.path.join(CACHE_DIR, sym, 'report.html')}")
        print(f"Log: {log_path}")


def _publish():
    from dossier.publish import publish, publish_data
    data = publish_data()
    print(f"Published {data['_id']} report data ({data['bytes'] / 1024:.0f} KB) to MongoDB vault_db.dossier_data")
    doc = publish()
    print(f"Published {doc['_id']} page snapshot ({doc['bytes'] / 1024:.0f} KB) to MongoDB vault_db.dossier_reports")


def _signal_summary(sym):
    import json
    path = os.path.join(CACHE_DIR, sym, "agent.json")
    if not os.path.exists(path):
        return
    with open(path) as f:
        t = json.load(f).get("today") or {}
    words = {"buy": f"BUY about {t.get('shares', 0):,} shares", "add": f"BUY {t.get('shares', 0):,} more shares",
             "trim": f"SELL {t.get('shares', 0):,} shares", "sell": f"SELL all {t.get('shares', 0):,} shares",
             "hold": f"HOLD {t.get('shares', 0):,} shares (no trade)", "wait": "NO TRADE (stay in cash)"}
    print("\n" + "=" * 60)
    print(f"  Signal for the next trading day ({sym}): {words.get(t.get('action'), '—')}")
    if t.get("action") in ("buy", "add", "sell", "trim"):
        from dossier.report import _inr
        print(f"  At the opening price; about {_inr(t.get('ref_value', 0))} at the last close of ₹{t.get('ref_price', 0):,.2f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
