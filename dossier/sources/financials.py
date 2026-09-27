"""Quarterly financial statements from NSE's structured filings (free, exact).

Two formats, checked 27 September 2026:
- Legacy XBRL (quarters to December 2024): the per-company results list
  (corporates-financial-results) links an XML instance. Values are in
  rupees; context 'OneD' is the reporting quarter.
- Integrated Filing (from 2025): integrated-filing-results links an HTML
  rendering of the filing. The first value column of the results table is
  the quarter; the unit is given by 'Level of rounding used in financial
  results' (Lakhs, Millions, ...).

The scanned PDF of the signed results is never needed.
Point-in-time rule: each quarter keeps the version first published (its
broadcast time), because that is what the market saw; later revisions are
recorded but not used for signals.
"""
import json
import os
import re
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests

from dossier.sources import nse_api
from dossier.sources.nse import HEADERS, ROOT

FIN_DIR = os.path.join(ROOT, "financials")

# field -> (legacy XBRL tag, integrated-filing row label)
FIELDS = {
    "revenue": ("RevenueFromOperations", "revenue from operations"),
    "other_income": ("OtherIncome", "other income"),
    "materials": ("CostOfMaterialsConsumed", "cost of materials consumed"),
    "purchases": ("PurchasesOfStockInTrade", "purchases of stock-in-trade"),
    "inventory_change": ("ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade",
                         "changes in inventories of finished goods, work-in-progress and stock-in-trade"),
    "employee": ("EmployeeBenefitExpense", "employee benefit expense"),
    "finance_cost": ("FinanceCosts", "finance costs"),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense", "depreciation, depletion and amortisation expense"),
    "total_expenses": ("Expenses", "total expenses"),
    "pbt": ("ProfitBeforeTax", "total profit before tax"),
    "tax": ("TaxExpense", "total tax expenses"),
    "pat": ("ProfitLossForPeriod", "total profit (loss) for period"),
    "eps": ("BasicEarningsLossPerShareFromContinuingOperations", "basic earnings (loss) per share from continuing operations"),
}
UNITS = {"rupees": 1, "thousands": 1e3, "lakhs": 1e5, "lakh": 1e5, "millions": 1e6, "million": 1e6,
         "crores": 1e7, "crore": 1e7, "billions": 1e9}


def _get(url, dest):
    if os.path.exists(dest):
        with open(dest, "rb") as f:
            return f.read()
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(r.content)
    time.sleep(0.4)
    return r.content


def _num(text):
    t = str(text).strip().replace(",", "").replace("\xa0", "")
    if t in ("", "null", "-", "NA"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def parse_legacy(content):
    root = ET.fromstring(content)
    ctx = {}
    for c in root.iter():
        if c.tag.endswith("}context"):
            dates = {t.tag.split("}")[-1]: t.text for t in c.iter() if t.tag.endswith(("startDate", "endDate", "instant"))}
            ctx[c.get("id")] = dates
    out = {}
    q = ctx.get("OneD", {})
    out["period_start"], out["period_end"] = q.get("startDate"), q.get("endDate")
    for field, (tag, _) in FIELDS.items():
        for e in root.iter():
            if e.tag.split("}")[-1] == tag and e.get("contextRef") == "OneD":
                out[field] = _num(e.text)
                break
    return out


def parse_integrated(content):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(content, "lxml")
    rows = []
    for tr in soup.find_all("tr"):
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip() for c in tr.find_all(["td", "th"])]
        if any(cells):
            rows.append(cells)

    def value_after(label, first=True):
        for cells in rows:
            low = [c.lower() for c in cells]
            if label in low:
                i = low.index(label)
                if i + 1 < len(cells):
                    return cells[i + 1]
        return None

    unit = (value_after("level of rounding used in financial results") or "rupees").strip().lower()
    reporting = (value_after("reporting type") or "").strip().lower()
    scale = UNITS.get(unit, 1)
    out = {"period_start": value_after("date of start of reporting period"),
           "period_end": value_after("date of end of reporting period"), "unit": unit,
           "reporting_type": reporting}
    for field, (_, label) in FIELDS.items():
        v = _num(value_after(label)) if value_after(label) is not None else None
        out[field] = None if v is None else (v if field == "eps" else v * scale)
    return out


def _ts(s):
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return pd.to_datetime(s, format=fmt)
        except (TypeError, ValueError):
            continue
    return pd.NaT


def filings_index(symbol, refresh=True):
    """All financial-results filings for a symbol, both formats, newest first."""
    path = os.path.join(FIN_DIR, symbol, "index.json")
    if os.path.exists(path) and (not refresh or nse_api._fresh(path)):
        with open(path) as f:
            return json.load(f)
    legacy = nse_api._fetch_json(nse_api.BASE + f"corporates-financial-results?index=equities&symbol={symbol}&period=Quarterly")
    legacy = legacy if isinstance(legacy, list) else legacy.get("data", [])
    time.sleep(0.8)
    integ = nse_api._fetch_json(nse_api.BASE + f"integrated-filing-results?index=equities&symbol={symbol}")
    integ = integ.get("data", []) if isinstance(integ, dict) else integ
    rows = []
    for r in legacy:
        if r.get("xbrl"):
            rows.append({"format": "legacy", "url": r["xbrl"], "basis": r.get("consolidated"),
                         "published": r.get("broadCastDate"), "revised": None, "to": r.get("toDate")})
    for r in integ:
        if "Financials" in (r.get("type") or "") and r.get("ixbrl"):
            rows.append({"format": "integrated", "url": r["ixbrl"], "basis": r.get("consolidated"),
                         "published": r.get("broadcast_Date"), "revised": r.get("revised_Date"), "to": r.get("qe_Date")})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(rows, f)
    return rows


def quarterly(symbol, refresh=False):
    """One row per quarter: first-published figures in rupees, with publish time."""
    rows = []
    for r in filings_index(symbol, refresh=refresh):
        name = os.path.basename(r["url"])
        try:
            content = _get(r["url"], os.path.join(FIN_DIR, symbol, name))
            data = parse_legacy(content) if r["format"] == "legacy" else parse_integrated(content)
        except Exception as e:   # one unreadable filing must not sink the rest
            data = {"error": f"{type(e).__name__}: {e}"}
        basis = "consolidated" if (r["basis"] or "").lower().startswith("consolidated") else "standalone"
        published = _ts(r["published"]) if r["published"] else _ts(r["revised"])
        rows.append({**data, "basis": basis, "format": r["format"], "published": published,
                     "is_revision": r["published"] is None, "source": r["url"]})
    df = pd.DataFrame(rows)
    if df.empty or "period_end" not in df:
        return df
    df["period_end"] = pd.to_datetime(df["period_end"], dayfirst=True, errors="coerce", format="mixed")
    df["period_start"] = pd.to_datetime(df["period_start"], dayfirst=True, errors="coerce", format="mixed")
    df = df.dropna(subset=["period_end", "revenue"])
    # The first column of a quarterly filing is the quarter, identified by its
    # end date. Companies sometimes mistype the start date (NETWEB's original
    # March 2025 and March 2026 filings say 1 October), so the start date is
    # only checked, never trusted.
    df = df[df["period_end"].dt.is_quarter_end]
    span = (df["period_end"] - df["period_start"]).dt.days
    df = df[(df["format"] == "legacy") & span.between(80, 100) |
            (df["format"] == "integrated") & (df.get("reporting_type", "quarterly").fillna("quarterly") != "annual")]
    df = df.assign(start_date_mistyped=~span.reindex(df.index).between(80, 100))
    # One basis per company: whichever gives the longer history.
    counts = df.groupby("basis")["period_end"].nunique()
    basis = counts.idxmax() if len(counts) else "standalone"
    df = df[df["basis"] == basis]
    df = df.sort_values(["period_end", "is_revision", "published"]).drop_duplicates("period_end", keep="first")
    return df.reset_index(drop=True)
