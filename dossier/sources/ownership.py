"""Who owns the company, quarter by quarter, from NSE's shareholding-pattern XBRL files.

NSE's shareholding master (nse_api "holdings") only gives promoter vs public.
Each row links an XBRL file with the full split. Two layouts exist:
- up to about March 2025: percentages (37.26), category in an explicitMember
- from about April 2025: fractions (0.3726), same categories
Both are read by category name, so either works. Only the parsed numbers are
cached (data/dossier/_nse/ownership/<SYMBOL>.json), keyed by file URL, so a
file is downloaded once.

Dating: a quarter re-filed later (revisedData = "Revised") carries the
re-filing's broadcast time, sometimes a year late. The file name keeps the
upload stamp of the file itself (..._DDMMYYYYhhmmss_WEB.xml, 12-hour clock
without am/pm), usually the original day, so `published` is the broadcast time
when it falls on that day, otherwise that day at 23:59 (counted from the next
session). A file replaced by its revision is dated by the revision: late, never early.
"""
import json
import os
import re

import pandas as pd

from dossier.sources import nse_api
from dossier.sources.nse import ROOT

OWN_DIR = os.path.join(ROOT, "ownership")

# Output field -> category names as they appear in either layout (lower case, no "Member").
CATEGORIES = {
    "promoter": "shareholdingofpromoterandpromotergroup",
    "fii": "institutionsforeign",
    "dii": "institutionsdomestic",
    "mutual_funds": "mutualfundsoruti",
    "insurance": "insurancecompanies",
    "public": "publicshareholding",
}
_PCT = re.compile(r'<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="([^"]+)"[^>]*>([^<]+)<')
_CTX = re.compile(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', re.S)
_MEMBER = re.compile(r'<xbrldi:explicitMember dimension="[^"]*CategoryOfShareholdersAxis">[\w-]+:(\w+?)Member<')


def parse(xml):
    """{field: percent of shares} for the whole-company categories in one filing."""
    values = {cid: v for cid, v in _PCT.findall(xml)}
    found = {}
    for cid, body in _CTX.findall(xml):
        if cid not in values or "typedMember" in body:
            continue   # typedMember contexts are individual holders, not category totals
        m = _MEMBER.search(body)
        name = (m.group(1) if m else re.sub(r"(_ContextI|I)$", "", cid)).lower()
        try:
            found.setdefault(name, float(values[cid]))
        except ValueError:
            pass
    out = {k: found.get(v) for k, v in CATEGORIES.items()}
    if out["promoter"] is None or out["public"] is None:
        raise ValueError("shareholding file without promoter/public totals")
    if out["promoter"] + out["public"] < 1.5:   # fractions (newer layout) -> percent
        out = {k: None if v is None else v * 100 for k, v in out.items()}
    return {k: None if v is None else round(v, 2) for k, v in out.items()}


def _published(row):
    b = pd.to_datetime(row.get("broadcastDate"), format="%d-%b-%Y %H:%M:%S", errors="coerce")
    m = re.search(r"_(\d{8})\d{6}_WEB\.xml$", row.get("xbrl") or "")
    first = pd.to_datetime(m.group(1), format="%d%m%Y", errors="coerce") if m else pd.NaT
    if pd.isna(first) or (not pd.isna(b) and b.normalize() == first):
        return b
    return first + pd.Timedelta(hours=23, minutes=59)


def quarterly(symbol, since="2023-01-01", refresh=True):
    """One row per quarter end since `since`: promoter, fii, dii, mutual_funds,
    insurance, other (everyone else: individuals, companies, NRIs, ...), in percent."""
    path = os.path.join(OWN_DIR, f"{symbol}.json")
    cache = {}
    if os.path.exists(path):
        with open(path) as f:
            cache = json.load(f)
    rows, changed = [], False
    for r in nse_api.company("holdings", symbol, refresh=refresh):
        url, q = r.get("xbrl"), pd.to_datetime(r.get("date"), format="%d-%b-%Y", errors="coerce")
        if not url or pd.isna(q) or q < pd.Timestamp(since):
            continue
        if url not in cache:
            from nselib import libutil
            resp = libutil.nse_urlfetch(url)
            if resp.status_code != 200:
                continue
            try:
                cache[url] = parse(resp.text)
            except ValueError:
                continue
            changed = True
        pub = _published(r)
        rows.append({"quarter": q.date().isoformat(), "published": None if pd.isna(pub) else pub.isoformat(),
                     **cache[url]})
    if changed:
        os.makedirs(OWN_DIR, exist_ok=True)
        with open(path, "w") as f:
            json.dump(cache, f)
    rows = sorted(rows, key=lambda x: (x["quarter"], x["published"] or ""))
    out = list({r["quarter"]: r for r in reversed(rows)}.values())   # earliest filing per quarter
    for r in out:
        known = [r[k] for k in ("promoter", "fii", "dii")]
        r["other"] = None if None in known else round(100 - sum(known), 2)
    return sorted(out, key=lambda x: x["quarter"])
