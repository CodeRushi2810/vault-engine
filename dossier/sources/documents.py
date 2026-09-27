"""Filing PDFs: download once, extract text with pypdf, cache both.

Files live under data/dossier/_nse/docs/<SYMBOL>/. Scanned PDFs (no text
layer, e.g. signed results statements) are recorded as 'scanned' and
skipped; their numbers come from the structured filings instead (see
sources/financials.py).
"""
import json
import os
import time

import pandas as pd
import requests

from dossier.sources import nse_api
from dossier.sources.nse import HEADERS, ROOT

DOC_DIR = os.path.join(ROOT, "docs")
MAX_BYTES = 25 * 1024 * 1024

# Which filings to read. Transcripts are filed under the investor-meet
# category, so they are picked out by name.
FOCUS_CATEGORIES = {"Credit Rating", "Bagging/Receiving of orders/contracts", "Investor Presentation", "Press Release"}
PEER_CATEGORIES = {"Credit Rating", "Bagging/Receiving of orders/contracts"}
TRANSCRIPT_WORDS = ("transcript",)


def wanted(symbol, focus, since="2023-01-01"):
    """Announcements whose PDFs should be read, oldest first."""
    cats = FOCUS_CATEGORIES if focus else PEER_CATEGORIES
    out = []
    for a in nse_api.company("announcements", symbol, refresh=False):
        url = a.get("attchmntFile") or ""
        if not url.lower().endswith(".pdf"):
            continue
        ts = pd.to_datetime(a["an_dt"], format="%d-%b-%Y %H:%M:%S", errors="coerce")
        if pd.isna(ts) or ts < pd.Timestamp(since):
            continue
        is_transcript = focus and any(w in (url + (a.get("attchmntText") or "")).lower() for w in TRANSCRIPT_WORDS)
        if a.get("desc") in cats or is_transcript:
            out.append({"symbol": symbol, "category": "Transcript" if is_transcript else a["desc"],
                        "ts": ts, "url": url, "subject": a.get("attchmntText")})
    return sorted(out, key=lambda x: x["ts"])


def text(doc):
    """Page texts for one filing (cached). Returns {'status', 'pages'}."""
    folder = os.path.join(DOC_DIR, doc["symbol"])
    name = os.path.basename(doc["url"])
    txt_path = os.path.join(folder, name + ".json")
    if os.path.exists(txt_path):
        with open(txt_path, encoding="utf-8") as f:
            return json.load(f)

    os.makedirs(folder, exist_ok=True)
    pdf_path = os.path.join(folder, name)
    result = {"status": "ok", "pages": []}
    try:
        if not os.path.exists(pdf_path):
            r = requests.get(doc["url"], headers=HEADERS, timeout=60, stream=True)
            if r.status_code != 200:
                result = {"status": f"http {r.status_code}", "pages": []}
            else:
                data = r.raw.read(MAX_BYTES + 1, decode_content=True)
                if len(data) > MAX_BYTES:
                    result = {"status": "too large", "pages": []}
                else:
                    with open(pdf_path, "wb") as f:
                        f.write(data)
            time.sleep(0.5)
        if result["status"] == "ok":
            import pypdf
            reader = pypdf.PdfReader(pdf_path)
            pages = [(p.extract_text() or "") for p in reader.pages]
            if sum(len(p.strip()) for p in pages) < 100:
                result = {"status": "scanned", "pages": []}
            else:
                result = {"status": "ok", "pages": pages}
    except Exception as e:   # a broken PDF must not stop the batch
        result = {"status": f"error: {type(e).__name__}", "pages": []}

    with open(txt_path, "w", encoding="utf-8") as f:
        json.dump(result, f)
    # Keep the text, drop the PDF itself to save disk.
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    return result
