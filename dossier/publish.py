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


def publish(symbol=universe.FOCUS):
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
