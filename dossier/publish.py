"""Publish the finished report to MongoDB for the vault-report web app.

One document per stock in vault_db.dossier_reports:
    {_id: "NETWEB", html: <report.html>, as_of, generated_at, signal: {...}}
The web app serves `html` exactly as written, so the online page is the
same page as data/dossier/<SYMBOL>/report.html.
"""
import json
import os
from datetime import datetime

from dossier import universe
from dossier.data import BASE_DIR, CACHE_DIR

DB, COLLECTION = "vault_db", "dossier_reports"


DATA_COLLECTION = "dossier_data"
SCHEMA = 1


def _clean(x):
    """JSON-safe: NaN/inf -> None, numpy scalars -> Python, tuples -> lists."""
    import math
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        try:
            x = x.item()
        except (AttributeError, ValueError):
            pass
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x


def _result(r):
    """One research result, trimmed to what the web report shows (stock-neutral names)."""
    keep = lambda d, *ks: {k: d.get(k) for k in ks} if d else {}
    return {
        "condition": r["condition"], "description": r["description"], "horizon": r["horizon"], "h": r["h"],
        "verdict": r["verdict"], "baseline": r.get("baseline"),
        "pooled": keep(r["pooled"], "n", "clusters", "mean", "ci95", "p", "hit_rate"),
        "raw_mean": (r.get("pooled_raw") or {}).get("mean"),
        "discovery_mean": (r.get("discovery") or {}).get("mean"), "validation_mean": (r.get("validation") or {}).get("mean"),
        "focus_n": (r.get("netweb") or {}).get("n"), "focus_estimate": r.get("netweb_estimate"),
    }


def payload(symbol=None):
    """Everything the web report needs for one stock, as plain JSON."""
    symbol = symbol or universe.FOCUS
    from dossier.data import load_stocks
    from dossier.sources import nse_api

    folder = os.path.join(CACHE_DIR, symbol)
    with open(os.path.join(folder, "dossier.json")) as f:
        d = json.load(f)
    agent, peers = None, []
    if os.path.exists(os.path.join(folder, "agent.json")):
        with open(os.path.join(folder, "agent.json")) as f:
            agent = json.load(f)
    if os.path.exists(os.path.join(folder, "peers.json")):
        with open(os.path.join(folder, "peers.json")) as f:
            peers = [{k: p.get(k) for k in ("symbol", "role", "resid_corr_daily", "overlap_days")} for p in json.load(f)
                     if "resid_corr_daily" in p]
    cal = nse_api.company("calendar", symbol, refresh=False)
    company = next((r.get("company") for r in cal if r.get("company")), symbol)

    bars = load_stocks([symbol])[symbol][0]
    close = bars["Close"].dropna()
    ev, wh = d.get("events") or {}, d.get("what_happens_when") or {}
    doc = {
        "_id": symbol, "schema": SCHEMA, "symbol": symbol, "company": company,
        "as_of": d["history"]["last"], "generated_at": datetime.now().isoformat(timespec="seconds"),
        "history": d["history"], "anatomy": d["anatomy"], "data_quality": d["data_quality"],
        "prices": {"dates": [x.date().isoformat() for x in close.index], "close": [round(float(v), 2) for v in close.values]},
        "patterns": {"results": [_result(r) for r in wh.get("results", [])], "method": wh.get("method"), "now": wh.get("now")},
        "events": {"results": [_result(r) for r in ev.get("results", [])], "method": ev.get("method"),
                   "results_profile": ev.get("results_profile"), "scorecard": ev.get("scorecard"),
                   "upcoming": ev.get("upcoming"), "recent": ev.get("focus_recent")},
        "agent": agent, "peers": peers, "indices": universe.INDICES,
    }
    return _clean(doc)


def publish_data(symbol=None):
    """Save the stock's report data for the web app (vault_db.dossier_data)."""
    symbol = symbol or universe.FOCUS
    from dotenv import load_dotenv
    from pymongo import MongoClient

    doc = payload(symbol)
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    uri = os.getenv("MONGO_URI")
    if not uri:
        raise RuntimeError("MONGO_URI is not set in .env")
    MongoClient(uri, serverSelectionTimeoutMS=15000)[DB][DATA_COLLECTION].replace_one({"_id": symbol}, doc, upsert=True)
    doc["bytes"] = len(json.dumps(doc))
    return doc


def publish(symbol=None):
    symbol = symbol or universe.FOCUS
    from dotenv import load_dotenv
    from pymongo import MongoClient

    folder = os.path.join(CACHE_DIR, symbol)
    with open(os.path.join(folder, "report.html"), encoding="utf-8") as f:
        page = f.read()
    signal, as_of = None, None
    agent_path = os.path.join(folder, "agent.json")
    if os.path.exists(agent_path):
        with open(agent_path) as f:
            ag = json.load(f)
        signal, as_of = ag.get("today"), ag.get("as_of")

    load_dotenv(os.path.join(BASE_DIR, ".env"))
    uri = os.getenv("MONGO_URI")
    if not uri:
        raise RuntimeError("MONGO_URI is not set in .env")
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    doc = {"_id": symbol, "html": page, "as_of": as_of, "signal": signal,
           "generated_at": datetime.now().isoformat(timespec="seconds"), "bytes": len(page.encode("utf-8"))}
    client[DB][COLLECTION].replace_one({"_id": symbol}, doc, upsert=True)
    return doc
