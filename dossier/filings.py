"""Rule-based facts from filing text. Free, local and deterministic.

Every fact carries the sentence it came from (`quote`) and the filing's
publish time (`ts`), so a number can be checked against its source and is
only used from the moment it was public. Rules are deliberately narrow: a
fact the rules are unsure of is dropped, not guessed.

Facts
- credit rating letters: agency and action (upgrade / downgrade /
  outlook change / reaffirm / assigned), read from the cover pages only,
  because rating rationales use "upgrade" in other senses.
- order-win letters: the largest amount stated near "order" / "contract".
- transcripts, presentations, press releases: order book (total and
  organic), L1 position, pipeline -- only when the amount directly follows
  the label -- plus an EBITDA/operating margin guidance range and a revenue
  growth guidance range, each only when stated with a guidance word.
"""
import re

import pandas as pd

from dossier import universe
from dossier.sources import documents

CUR = r"(?:₹|Rs\.?|INR|Rupees)"
NUM = r"(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
UNIT = r"(crores?|cr\b\.?|lakhs?|lacs?|millions?|mn\b|billions?|bn\b)"
SCALE = {"crore": 1e7, "cr": 1e7, "lakh": 1e5, "lac": 1e5, "million": 1e6, "mn": 1e6, "billion": 1e9, "bn": 1e9}
MONEY = re.compile(CUR + r"\s*" + NUM + r"\s*" + UNIT + r"?", re.I)

AGENCIES = {"CRISIL": r"crisil", "ICRA": r"\bicra\b", "CARE": r"\bcare (?:ratings|edge|bbb|a|aa)|care ratings",
            "India Ratings": r"india ratings|ind-?ra\b", "Acuite": r"acuit[eé]", "Brickwork": r"brickwork",
            "Infomerics": r"infomerics"}
# Highest-priority action first: one letter can upgrade long-term and
# reaffirm short-term, which is an upgrade.
ACTIONS = [("downgrade", r"downgrad"), ("upgrade", r"upgrad"),
           ("outlook_negative", r"outlook[^.]{0,60}(?:revised|changed)[^.]{0,40}negative|negative outlook"),
           ("outlook_positive", r"outlook[^.]{0,60}(?:revised|changed)[^.]{0,40}positive|positive outlook"),
           ("reaffirm", r"reaffirm|re-affirm"), ("assigned", r"assign")]


def _clean(t):
    t = t.replace(" ", " ").replace("\xa0", " ").replace("’", "'")
    return re.sub(r"\s+", " ", t)


def _to_rupees(num, unit):
    v = float(num.replace(",", ""))
    if not unit:
        return v
    u = unit.lower().rstrip(".").rstrip("s")
    return v * SCALE.get(u, 1)


def _sentence(text, start, end, before=200, after=120):
    """The sentence(s) around a match; always contains the matched text."""
    lo = max(0, start - before)
    cut = text.rfind(". ", lo, start)
    lo = cut + 2 if cut != -1 else lo
    hi = min(len(text), end + after)
    cut = text.find(". ", end, hi)
    hi = cut + 1 if cut != -1 else hi
    return text[lo:hi].strip()


def rating_facts(pages):
    head = _clean(" ".join(pages[:2])).lower()
    agency = next((name for name, pat in AGENCIES.items() if re.search(pat, head)), None)
    for action, pat in ACTIONS:
        m = re.search(pat, head)
        if m:
            return [{"kind": "rating_action", "value": action, "agency": agency,
                     "quote": _sentence(_clean(" ".join(pages[:2])), m.start(), m.end())}]
    return []


def order_facts(pages):
    text = _clean(" ".join(pages[:3]))
    best = None
    for m in MONEY.finditer(text):
        window = text[max(0, m.start() - 220):m.start()].lower()
        if not re.search(r"order|contract|letter of award|\bloa\b|purchase order|work order", window):
            continue
        rupees = _to_rupees(m.group(1), m.group(2))
        if rupees < 1e5:        # a bare small number is almost always not the order value
            continue
        if best is None or rupees > best["value"]:
            best = {"kind": "order_value", "value": rupees, "unit": "INR",
                    "quote": _sentence(text, m.start(), m.end())}
    return [best] if best else []


def _amount_after(label, text, gap=25):
    """Amount stated directly after a label (at most `gap` characters later,
    with no number and no other label in between), e.g. 'Order Book ₹ 3,391
    Mn'. 'Strong Order Pipeline: Order book - ₹3,603 Mn' is not a pipeline."""
    between = r"(?:(?!order ?book|pipeline|\bL-?1\b)[^\d.]){0," + str(gap) + r"}?"
    pat = re.compile(label + between + CUR + r"\s*" + NUM + r"\s*" + UNIT, re.I)
    m = pat.search(text)
    if not m:
        return None
    return _to_rupees(m.group(1), m.group(2)), _sentence(text, m.start(), m.end())


BOX_LABEL = re.compile(r"(organic order ?book|order ?book|\bL-?1\b|pipeline)\s*[#*]?", re.I)
BOX_KIND = {"organic order book": "order_book_organic", "organic orderbook": "order_book_organic",
            "order book": "order_book", "orderbook": "order_book", "l1": "l1_position", "l-1": "l1_position",
            "pipeline": "pipeline"}


def _read_boxes(text, gap=6):
    """Pair labels and amounts inside tight runs like a deck's summary box."""
    tokens = [("L", m.start(), m.end(), m) for m in BOX_LABEL.finditer(text)]
    tokens += [("A", m.start(), m.end(), m) for m in MONEY.finditer(text) if m.group(2)]
    tokens.sort(key=lambda t: t[1])
    out, run = {}, []

    def flush(run):
        # A box has at least two label/amount pairs, alternating.
        if len(run) < 4 or any(run[i][0] == run[i + 1][0] for i in range(len(run) - 1)):
            return
        pairs = zip(run[0::2], run[1::2])
        for a, b in pairs:
            lab, amt = (a, b) if a[0] == "L" else (b, a)
            kind = BOX_KIND.get(re.sub(r"\s+", " ", lab[3].group(1).lower()))
            if kind and kind not in out:
                out[kind] = (_to_rupees(amt[3].group(1), amt[3].group(2)),
                             _sentence(text, run[0][1], run[-1][2], before=60, after=20))

    for t in tokens:
        if run and t[1] - run[-1][2] > gap:
            flush(run)
            run = []
        run.append(t)
    flush(run)
    return out


GUIDE_WORDS = r"guid|maintain|expect|confident|target|aim|remain|sustain"
AMOUNT_KINDS = {"order_book", "order_book_organic", "l1_position", "pipeline"}


def business_facts(pages, amounts=True):
    """`amounts=False` for call transcripts: analysts there often quote last
    quarter's numbers back, so order book / L1 / pipeline come only from
    presentations and press releases."""
    text = _clean(" ".join(pages))
    facts = []
    labels = () if not amounts else (("order_book_organic", r"organic order ?book"),
              ("order_book", r"(?<!organic )order ?book(?: stood at| of| at| was| is)?"),
              ("l1_position", r"\bL-?1\b\s*(?:#|position)?(?: of| at| stood at)?"),
              ("pipeline", r"pipeline\s*#?\*?(?: of| at| stood at| remains robust at)?"))
    # Summary boxes come in two layouts: 'Order Book ₹ 994 Mn L1# ₹ 5,392 Mn'
    # (label first) and '₹104,100.00 Mn Pipeline* ₹8,480.47 Mn L1*' (value
    # first, from July 2026). A box is read as a unit: whichever token opens
    # it decides how labels and amounts pair. Free text is the fallback.
    boxed = _read_boxes(text) if labels else {}
    for kind, label in labels:
        hit = boxed.get(kind) or _amount_after(label, text)
        if hit:
            facts.append({"kind": kind, "value": hit[0], "unit": "INR", "quote": hit[1]})

    for m in re.finditer(r"(\d{1,2}(?:\.\d+)?)\s*%?\s*(?:to|-|–)\s*(\d{1,2}(?:\.\d+)?)\s*%", text):
        sent = _sentence(text, m.start(), m.end(), before=160, after=40)
        low = sent.lower()
        lo, hi = float(m.group(1)), float(m.group(2))
        # The margin words must lead into this range ("EBITDA margin ... 13% to
        # 14%"), not belong to another clause ("revenue guidance of 35% to 40%").
        lead = text[max(0, m.start() - 70):m.start()].lower()
        near = re.search(r"(\w+\s+)?(?:ebitda|operating margin|margins?)[^%]*$", lead)
        if (near and "revenue" not in lead and not re.search(r"\b(?:pat|net|gross|profit)\b", near.group(0))
                and re.search(r"ebitda|operating margin", low) and not re.search(r"gross", low)
                and re.search(GUIDE_WORDS, low) and 5 <= lo < hi <= 40):
            facts.append({"kind": "margin_guidance", "value": [lo, hi], "unit": "%", "quote": sent})
            break

    for m in re.finditer(r"(\d{2})\s*%\s*(?:to|-|–)\s*(\d{2})\s*%\s*(?:\w+\s){0,3}?(?:cagr|growth|top ?line|revenue)", text, re.I):
        sent = _sentence(text, m.start(), m.end(), before=160, after=40)
        if re.search(GUIDE_WORDS, sent, re.I):
            facts.append({"kind": "revenue_growth_guidance", "value": [float(m.group(1)), float(m.group(2))],
                          "unit": "%", "quote": sent})
            break
    return facts


def extract(symbol, focus):
    """All facts for one symbol, each with its filing time and source."""
    rows = []
    for doc in documents.wanted(symbol, focus):
        t = documents.text(doc)
        if t["status"] != "ok":
            continue
        if doc["category"] == "Credit Rating":
            facts = rating_facts(t["pages"])
        elif doc["category"].startswith("Bagging"):
            facts = order_facts(t["pages"])
        else:
            facts = business_facts(t["pages"], amounts=doc["category"] != "Transcript")
        for f in facts:
            rows.append({"symbol": symbol, "ts": doc["ts"], "category": doc["category"], "source": doc["url"], **f})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # A business figure repeated in a later filing (the same order book in the
    # results deck and a conference deck) is not new information. Ratings,
    # orders and guidance are kept every time: a repeat is itself news
    # (a second upgrade, guidance maintained).
    df = df.sort_values("ts").reset_index(drop=True)
    amounts = df["kind"].isin(AMOUNT_KINDS)
    key = df["value"].map(lambda v: tuple(v) if isinstance(v, list) else round(float(v), 2) if isinstance(v, float) else v)
    dup = amounts & df.assign(_k=key).duplicated(["kind", "_k"])
    same_doc = df.duplicated(["kind", "source"])
    # The same order filed twice (E2E's ₹177 cr order on 2 and 3 September
    # 2025) is one order.
    orders = df["kind"] == "order_value"
    prev_same = df[orders].groupby(key[orders])["ts"].diff().dt.days.le(10)
    refiled = pd.Series(False, index=df.index)
    refiled.loc[prev_same.index] = prev_same.fillna(False).astype(bool)
    return df[~dup & ~same_doc & ~refiled].reset_index(drop=True)


def all_facts():
    frames = [extract(s, s == universe.FOCUS) for s in [universe.FOCUS] + universe.PEERS]
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
