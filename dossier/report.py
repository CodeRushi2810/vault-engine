"""The dossier as a minimal, plain-language HTML report (report.html).

Written for someone who does not follow markets: the first tab says what
the agent will do at the next open and why, every page leads with plain
sentences, and technical tables sit inside "Details" panels.

Self-contained apart from the web font (Modern Era if installed, else
Manrope from Google Fonts, else the system font). Light/dark switch,
tabs kept in the URL hash, charts redraw on resize and theme change.
"""
import html
import json
import os
from datetime import date, timedelta

import numpy as np

from dossier.universe import INDICES

# ------------------------------------------------------------------ formatting

def _d(iso):
    """ISO date -> '25 September 2026'."""
    if not iso:
        return "—"
    y, m, d = map(int, str(iso)[:10].split("-"))
    return f"{d} {date(y, m, d):%B %Y}"


def _day(iso):
    y, m, d = map(int, str(iso)[:10].split("-"))
    return f"{date(y, m, d):%A} {d} {date(y, m, d):%B %Y}"


def _e(s):
    return html.escape(str(s))


def _pct(x, digits=0, sign=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x * 100:{'+' if sign else ''}.{digits}f}%"


def _inr(x):
    """Indian grouping: 5904417 -> '₹59,04,417'."""
    if x is None:
        return "—"
    neg, n = x < 0, f"{abs(x):.0f}"
    head, tail = n[:-3], n[-3:]
    while len(head) > 2:
        tail = head[-2:] + "," + tail
        head = head[:-2]
    return ("−₹" if neg else "₹") + ((head + "," + tail) if head else tail)


def _words(x):
    """Rupees in words people use: ₹7.6 lakh, ₹2,507 crore."""
    if x is None:
        return "—"
    a = abs(x)
    s = f"₹{a / 1e7:,.0f} crore" if a >= 1e9 else f"₹{a / 1e7:,.1f} crore" if a >= 1e7 else f"₹{a / 1e5:,.1f} lakh" if a >= 1e5 else _inr(a)
    s = s.replace(".0 lakh", " lakh").replace(".0 crore", " crore")
    return ("−" if x < 0 else "") + s


def _next_trading_day(iso):
    y, m, d = map(int, iso.split("-"))
    nd = date(y, m, d) + timedelta(days=1)
    while nd.weekday() >= 5:
        nd += timedelta(days=1)
    return nd.isoformat()


def _plain_reason(r):
    """'Bad results: Results of 02 May 2026: first reaction -4.3% vs market.' -> plain English."""
    import re
    m = re.search(r"Results of (\d+) (\w+ \d{4}): first reaction ([+-]?[\d.]+)% vs (?:the )?market", r)
    if m:
        move = float(m.group(3))
        return (f"Disappointing results on {int(m.group(1))} {m.group(2)}: the share did {abs(move):.1f}% "
                f"{'worse' if move < 0 else 'better'} than the market that day.")
    m = re.search(r"Net profit ([+-]?\d+)% vs a year ago", r)
    if m:
        return f"Profit came in {abs(int(m.group(1)))}% lower than a year earlier."
    if "Price stop" in r:
        return "The price fell sharply below its recent high."
    if "not growing" in r:
        return "Sales fell below a year earlier."
    return r


def _stat(label, value, note="", tone=""):
    return (f'<div class="stat"><div class="label">{_e(label)}</div>'
            f'<div class="value {tone}">{value}</div><div class="note">{note}</div></div>')


def _details(summary, body):
    return f'<details class="more"><summary>{_e(summary)}</summary><div class="more-body">{body}</div></details>'


def _table(head, rows, cls=""):
    th = "".join(f"<th{' class=n' if h.startswith('#') else ''}>{_e(h.lstrip('#'))}</th>" for h in head)
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


RATING_WORD = {"upgrade": "upgraded", "downgrade": "downgraded", "reaffirm": "reaffirmed", "assigned": "assigned",
               "outlook_positive": "outlook raised", "outlook_negative": "outlook cut"}

PLAIN_LABEL = {
    "above_200dma": "Price rises back above its long-term average", "below_200dma": "Price falls below its long-term average",
    "golden_cross": "Short-term average rises above the long-term one", "death_cross": "Short-term average falls below the long-term one",
    "new_6m_high": "Price reaches a 6-month high", "strong_3m_momentum": "An unusually strong three months",
    "weak_3m_momentum": "An unusually weak three months", "rel_strength_top": "Far ahead of other small companies",
    "rel_strength_bottom": "Far behind other small companies", "rsi_oversold": "After heavy selling (“oversold”)",
    "rsi_overbought": "After heavy buying (“overbought”)", "stretched_down": "Price far below its recent average",
    "stretched_up": "Price far above its recent average", "drawdown_25": "Price 25% or more below its 6-month high",
    "drawdown_40": "Price 40% or more below its 6-month high", "down_streak_4": "Four falling days in a row",
    "vol_squeeze": "Unusually calm trading", "vol_stormy": "Unusually jumpy trading",
    "volume_spike_up": "Very heavy trading on a rising day", "volume_spike_down": "Very heavy trading on a falling day",
    "delivery_accumulation": "Buyers keeping the shares, on a rising day", "delivery_distribution": "Many shares handed over, on a falling day",
    "delivery_qty_surge": "Unusually many shares change owners for good", "gap_up_4": "Opens 4% or more above the day before",
    "gap_down_4": "Opens 4% or more below the day before", "market_below_200": "Small companies overall fall below their long-term average",
    "vix_high": "The market's fear gauge is high",
    "results_all": "Any results day", "results_strong": "Results day: share beats the market by 3% or more",
    "results_weak": "Results day: share trails the market by 3% or more", "results_muted": "Results day: share moves with the market",
    "order_win": "Announces an order win", "credit_rating": "Any credit-rating news", "acquisition": "Announces an acquisition",
    "management_exit": "A director or senior manager leaves", "exchange_query": "The exchange asks about an unusual price move",
    "large_holder_filing": "A big shareholder reports a trade", "investor_meet": "Meets big investors",
    "inst_deal_buy": "A fund buys a large block of shares", "inst_deal_sell": "A fund sells a large block of shares",
    "deal_net_buy": "Another large block of shares bought", "deal_net_sell": "Another large block of shares sold",
    "promoter_cut": "Founders reduce their stake", "promoter_raise": "Founders increase their stake",
    "rev_accel": "Results: sales growth speeds up", "rev_decel": "Results: sales growth slows down",
    "margin_expand": "Results: profit margin widens", "margin_compress": "Results: profit margin narrows",
    "profit_decline": "Results: profit lower than a year earlier", "rating_upgrade": "Credit rating upgraded",
    "rating_downgrade": "Credit rating downgraded", "rating_reaffirm": "Credit rating kept the same",
    "order_large": "Wins a big order (5%+ of a year's sales)", "order_small": "Wins a smaller order",
}

PLAIN_VERDICT = {"validated": "Proven", "consistent, not yet confirmed": "Promising, not yet proven",
                 "suggestive (not validated)": "A weak hint", "no evidence": "No effect", "insufficient data": "Too little data"}

# ------------------------------------------------------------------ sections

def _today(ag, sym, ev):
    t = ag.get("today") if ag else None
    if not t:
        return "<section class='hero'><p class='eyebrow'>Signal</p><h2 class='statement'>No signal yet</h2>" \
               "<p class='lede'>Run <code>python -m dossier.run agent</code> after the market closes.</p></section>"
    nxt = _next_trading_day(t["as_of"])
    pos = ag["paper"].get("open")
    held = pos["shares"] if pos else 0
    if t["action"] == "buy":
        statement = f"Buy {t['shares']:,} shares"
        detail = (f"of {sym} at the opening price on {_day(nxt)}. That is about <b>{_words(t['ref_value'])}</b>, "
                  f"{_pct(t['weight'])} of the {_words(t['equity'])} account, at the last closing price of ₹{t['ref_price']:,.2f}.")
    elif t["action"] == "add":
        statement = f"Buy {t['shares']:,} more shares"
        detail = f"at the opening price on {_day(nxt)}, about {_words(t['ref_value'])}."
    elif t["action"] == "trim":
        statement = f"Sell {t['shares']:,} shares"
        detail = f"at the opening price on {_day(nxt)}, keeping the rest."
    elif t["action"] == "sell":
        statement = f"Sell all {t['shares']:,} shares"
        detail = f"at the opening price on {_day(nxt)}, about {_words(t['ref_value'])} at the last closing price."
    elif t["action"] == "hold":
        statement = f"Hold {held:,} shares"
        detail = f"No trade on {_day(nxt)}. The reasons for owning {sym} still hold."
    else:
        statement = "No trade"
        detail = f"Stay in cash on {_day(nxt)}."

    why = []
    if t["revenue_yoy"] is not None:
        mult = 1 + t["revenue_yoy"]
        grow = (f"{mult:.1f}× what it was a year earlier" if mult >= 1.5 else f"{_pct(t['revenue_yoy'], 0, True)} on a year earlier")
        verdict = "The business is growing" if t["revenue_yoy"] > 0 else "The business is shrinking"
        why.append(f"<b>{verdict}.</b> Sales in the latest quarter ({_e(t['growth_note'].split('(quarter ended ')[-1].rstrip(')'))}) "
                   f"were {grow}.")
    if t["cooling_sessions_left"] > 0:
        why.append(f"<b>It is waiting after disappointing results.</b> {t['cooling_sessions_left']} more trading days "
                   "before it may buy again.")
    elif t["last_bad_results"]:
        why.append(f"<b>No recent warning from results.</b> The last disappointing results were on {_d(t['last_bad_results'])}; "
                   f"the {t['cool_off']}-day wait that followed is over.")
    if t["action"] in ("buy", "add") and t["vol63"]:
        why.append(f"<b>It invests {_pct(t['weight'])}, not everything,</b> because this share swings a lot "
                   f"(about {_pct(t['vol63'])} a year). Keeping {_pct(1 - t['weight'])} in cash limits how much a bad month can hurt.")
    why_html = "".join(f"<li>{w}</li>" for w in why)

    sell_rules = (f"<li>Results disappoint: on results day the share does at least {_pct(t['reaction_cut'])} worse than the "
                  "market, or profit comes in lower than a year earlier.</li>"
                  "<li>Sales fall below the same quarter a year earlier.</li>")
    up = (ev or {}).get("upcoming") or []
    prof = (ev or {}).get("results_profile") or {}
    q2 = [r["meeting"] for r in prof.get("focus_table", []) if r["meeting"][5:7] in ("10", "11")]
    nxt_results = (f"Next results: {_d(up[0]['date'])}." if up else
                   "Next results: not announced yet" + (f" (last year's came out on {_d(q2[-1])})." if q2 else "."))

    p = ag["paper"]
    profit = p["equity"] - ag["capital"]
    acct = "".join([
        _stat("Account value", _inr(p["equity"]), f"started with {_inr(ag['capital'])}"),
        _stat("Profit so far", _inr(profit), _pct(profit / ag["capital"], 1, True), "up" if profit > 0 else "down" if profit < 0 else ""),
        _stat("Cash", _inr(p["cash"]), f"{_pct(p['cash'] / p['equity'])} of the account"),
        _stat("Shares held", f"{held:,}" if held else "None", f"bought at ₹{pos['entry_price']:,.2f}" if pos else "nothing bought yet"),
    ])
    return f"""
<section class="hero">
  <p class="eyebrow">The agent's instruction for the next trading day</p>
  <h2 class="statement">{_e(statement)}</h2>
  <p class="lede">{detail}</p>
  <p class="fine">Decided at the close on {_d(t['as_of'])}. Paper trading only: no real order is placed. Not investment advice.</p>
</section>
<div class="two">
  <section><h3>Why</h3><ul class="plain">{why_html}</ul></section>
  <section><h3>What would make it sell</h3><ul class="plain">{sell_rules}</ul>
    <p class="fine">It then sells at the next opening price and waits {t['cool_off']} trading days before buying back. {_e(nxt_results)}</p></section>
</div>
<h3>Your paper account</h3>
<div class="stats">{acct}</div>"""


def _summary(d, sym):
    a = d["anatomy"]
    sc = (d.get("events") or {}).get("scorecard") or {}
    q = sc.get("quarters") or []
    lines = []
    if q and q[-1].get("revenue_yoy") is not None:
        lines.append(f"<b>The business is growing fast.</b> Sales in the quarter to {_d(q[-1]['quarter'])} were "
                     f"{_words(q[-1]['revenue'])}, {_pct(q[-1]['revenue_yoy'], 0, True)} on a year earlier.")
    lines.append(f"<b>The share price swings a lot.</b> A typical day moves about {_pct(a['volatility']['atr14_pct_median'], 1)}, "
                 f"and at its worst it fell {_pct(-a['drawdowns']['max_drawdown'])} from its high.")
    cr = (d.get("what_happens_when") or {}).get("results", [])
    n_pat = len({r["condition"] for r in cr})
    proven = {r["condition"] for r in cr if r["verdict"] == "validated"}
    if n_pat:
        lines.append(f"<b>Chart patterns don't predict it.</b> None of the {n_pat} patterns we tested told us more about "
                     "the next week, month or quarter than picking a random day." if not proven else
                     f"<b>{len(proven)} of {n_pat} chart patterns held up in testing.</b>")
    er = (d.get("events") or {}).get("results", [])
    bad = [r for r in er if r["condition"] in ("results_weak", "profit_decline")
           and r["verdict"] in ("validated", "consistent, not yet confirmed")]
    if bad:
        worst = min(bad, key=lambda r: r["pooled"]["mean"])
        lines.append(f"<b>Bad results tend to keep hurting.</b> Across similar companies, disappointing results were followed "
                     f"by a month about {_pct(abs(worst['pooled']['mean']))} weaker than usual. This is "
                     f"{'proven' if worst['verdict'] == 'validated' else 'promising but not yet proven'}, so the agent uses it only to step aside.")
    return "".join(f"<li>{x}</li>" for x in lines)


def _company(d, sym):
    ev = d.get("events") or {}
    sc = ev.get("scorecard") or {}
    q = sc.get("quarters") or []
    facts = sc.get("facts") or []
    if not q:
        return "<p class=muted>No results data yet.</p>", []
    last = q[-1]
    book = [f for f in facts if f["kind"] in ("order_book", "order_book_organic")]
    ratings = [f for f in facts if f["kind"] == "rating_action"]
    ob = book[-1] if book else None
    ttm = last.get("revenue_ttm")
    stats = [
        _stat("Sales, latest quarter", _words(last["revenue"]), f"{_pct(last['revenue_yoy'], 0, True)} on a year earlier" if last["revenue_yoy"] is not None else ""),
        _stat("Profit, latest quarter", _words(last["pat"]), f"keeps {_pct(last['pat_margin'])} of every rupee of sales"),
        _stat("Orders in hand", _words(ob["value"]) if ob else "—",
              f"about {ob['value'] / ttm * 12:.0f} months of sales" if ob and ttm else ""),
        _stat("Credit rating", RATING_WORD.get(ratings[-1]["value"], ratings[-1]["value"]).capitalize() if ratings else "—",
              f"by {_e(ratings[-1]['agency'] or 'the agency')} on {_d(ratings[-1]['ts'][:10])}" if ratings else ""),
    ]
    qrows = [f"<tr><td>{_d(r['quarter'])}</td><td class=n>{_words(r['revenue'])}</td>"
             f"<td class=n>{_pct(r['revenue_yoy'], 0, True)}</td><td class=n>{_words(r['pat'])}</td>"
             f"<td class=n>{_pct(r['pat_margin'], 1)}</td></tr>" for r in reversed(q)]
    books = {}
    for f in facts:
        if f["kind"] in ("order_book", "order_book_organic", "l1_position", "pipeline"):
            books.setdefault(f["ts"][:10], {})[f["kind"]] = f
    brows = []
    for day in sorted(books, reverse=True):
        b = books[day]
        o = b.get("order_book") or b.get("order_book_organic")
        brows.append(f"<tr><td>{_d(day)}</td><td class=n>{_words(o['value']) if o else '—'}</td>"
                     f"<td class=n>{_words(b['l1_position']['value']) if 'l1_position' in b else '—'}</td>"
                     f"<td class=n>{_words(b['pipeline']['value']) if 'pipeline' in b else '—'}</td></tr>")

    def quotes(kind, fmt):
        items = [f for f in facts if f["kind"] == kind]
        return "".join(f"<li><span class=date>{_d(f['ts'][:10])}</span> {fmt(f)}<br><span class=quote>“{_e(f['quote'][-200:])}”</span> "
                       f"<a href=\"{_e(f['source'])}\">source</a></li>" for f in reversed(items))
    rng = lambda f: f"{f['value'][0]:g}% to {f['value'][1]:g}%"
    guidance = quotes("revenue_growth_guidance", lambda f: f"Expects sales to grow <b>{rng(f)}</b> a year.") + \
        quotes("margin_guidance", lambda f: f"Expects operating margin of <b>{rng(f)}</b>.")
    rating_list = quotes("rating_action", lambda f: f"{_e(f.get('agency') or 'Agency')} <b>{RATING_WORD.get(f['value'], f['value'])}</b> the rating.")
    orders = quotes("order_value", lambda f: f"Won an order worth <b>{_words(f['value'])}</b>.")

    prof = ev.get("results_profile") or {}
    rrows = [f"<tr><td>{_d(r['meeting'])}</td><td class='n {'up' if r['reaction_abn'] > 0 else 'down'}'>{_pct(r['reaction_abn'], 1, True)}</td>"
             f"<td class='n {'up' if (r['next_month_raw'] or 0) > 0 else 'down'}'>{_pct(r['next_month_raw'], 1, True)}</td></tr>"
             for r in reversed(prof.get("focus_table", []))]
    typical = prof.get("focus_median_abs_reaction")

    body = f"""
<p class="intro">What the company reports every quarter, read straight from its filings with the stock exchange.</p>
<div class="stats">{''.join(stats)}</div>
<h3>Sales each quarter</h3>
<div class="chart" id="revbars"></div>
{_details("Quarter by quarter", _table(["Quarter ended", "#Sales", "#vs a year earlier", "#Profit", "#Profit margin"], qrows))}
{_details("Orders in hand, over time", "<p class=fine>“Won, awaiting order” means the company is the lowest bidder but the order is not signed yet. The pipeline is business it is bidding for.</p>" + _table(["Reported", "#Orders in hand", "#Won, awaiting order", "#Pipeline"], brows))}
{_details("What management has promised", f"<ul class='quotes'>{guidance or '<li>None found.</li>'}</ul>")}
{_details("Credit ratings and big orders", f"<ul class='quotes'>{rating_list or '<li>None found.</li>'}{orders}</ul>")}
<h3>How the share reacts to results</h3>
<p class="intro">On results day the share typically moves about <b>{_pct(typical, 1) if typical else '—'}</b> more or less than the market.</p>
{_details("Every results day", _table(["Results on", "#Move vs the market that day", "#Share price one month later"], rrows))}"""
    return body, [{"q": r["quarter"], "v": r["revenue"]} for r in q]


def _price(d, sym):
    a = d["anatomy"]
    ret, vol, dr, fr, rel = a["returns"], a["volatility"], a["drawdowns"], a["forward_returns"], a["relationships"]
    worst = min(dr.get("episodes_gt_10pct") or [{"peak": None, "trough": None, "depth": dr["max_drawdown"]}], key=lambda e: e["depth"])
    growth = (1 + ret["cagr"]) ** ret["years"]
    stats = [
        _stat("Growth since listing", f"{growth:.1f}×", f"about {_pct(ret['cagr'])} a year over {ret['years']:.1f} years"),
        _stat("A typical day", _pct(vol["atr14_pct_median"], 1), "up or down, from open to close and overnight"),
        _stat("Worst fall", _pct(dr["max_drawdown"]), f"{_d(worst['peak'])} to {_d(worst['trough'])}", "down"),
        _stat("Today vs its high", _pct(dr["current_drawdown"]), "below its highest close so far"),
    ]
    best = rel.get("best_fit_index")
    b = rel.get(best) if best else None
    market = ""
    if b:
        market = (f"<p class='intro'>{sym} moves most like the <b>{_e(INDICES.get(best, best))}</b> index. When that index moves 1%, "
                  f"{sym} tends to move about <b>{b['beta']:.1f}%</b>: {b['downside_beta']:.1f}% on falling days and "
                  f"{b['upside_beta']:.1f}% on rising days, so it falls harder than it rises.</p>")
    frows = [f"<tr><td>{ {'1w': '1 week', '1m': '1 month', '3m': '3 months', '6m': '6 months'}[k]}</td>"
             f"<td class=n>{_pct(x['p_positive'])}</td><td class=n>{_pct(x['median'], 0, True)}</td>"
             f"<td class=n>{_pct(x['p10'], 0, True)}</td><td class=n>{_pct(x['p90'], 0, True)}</td></tr>"
             for k, x in fr.items() if "median" in x]
    rrows = [f"<tr><td>{_e(INDICES.get(k, k))}</td><td class=n>{x['beta']:.2f}</td><td class=n>{x['downside_beta']:.2f}</td>"
             f"<td class=n>{x['upside_beta']:.2f}</td><td class=n>{_pct(x['r_squared'])}</td></tr>"
             for k, x in rel.items() if isinstance(x, dict)]
    return f"""
<p class="intro">How the share price has behaved since {sym} listed on {_d(d['history']['first'])}.</p>
<div class="stats">{''.join(stats)}</div>
<h3>Share price</h3>
<p class="fine">Each step up the scale is the same percentage rise, so early and recent moves compare fairly.</p>
<div class="chart" id="price"></div>
<h3>How far below its high</h3>
<p class="fine">0% means a new high. The deeper the shape, the bigger the fall a holder sat through.</p>
<div class="chart" id="dd"></div>
<h3>If you bought on any day and waited</h3>
<p class="intro">Past results, not a forecast: they mostly reflect how much the share has risen since listing.</p>
{_table(["Waited", "#Ended higher", "#Typical result", "#Bad case (1 in 10)", "#Good case (1 in 10)"], frows)}
<h3>Compared with the market</h3>
{market}
{_details("All market indices", "<p class=fine>“Moves with it” is how many percent the share tends to move for a 1% index move; “explained” is how much of its daily movement the index accounts for.</p>" + _table(["Index", "#Moves with it", "#On falling days", "#On rising days", "#Explained"], rrows))}"""


def _agent(ag, sym):
    if not ag:
        return "<p class=muted>No agent run yet.</p>", None
    p, bt = ag["paper"], ag["backtest"]
    cap = ag["capital"]

    def trade_rows(rows):
        out = []
        for t in reversed(rows):
            tone = "up" if t["pnl"] > 0 else "down"
            reason = t["exit_reason"].split(" | ")[0] if t["exit_reason"] else "still held"
            reason = _plain_reason(reason)
            out.append(f"<tr><td class=dt>{_d(t['entry'])}</td><td class=n>₹{t['entry_price']:,.0f}</td>"
                       f"<td class=dt>{'still held' if t['status'] == 'OPEN' else _d(t['exit'])}</td>"
                       f"<td class=n>₹{t['exit_price']:,.0f}</td><td class=n>{t['shares']:,}</td>"
                       f"<td class='n {tone}'>{_words(t['pnl'])}</td><td class='n {tone}'>{t['pnl_pct']:+.0f}%</td>"
                       f"<td class=why>{_e(reason)}</td></tr>")
        return out
    head = ["Bought", "#At", "Sold", "#At", "#Shares", "#Profit", "#Return", "Why it sold"]
    paper_trades = trade_rows(p["trades"] + ([p["open"]] if p.get("open") else []))
    paper_tbl = _table(head, paper_trades) if paper_trades else \
        f"<p class=muted>No trades yet. The paper account started on {_d(p['start'])}; the first order fills at the next opening price.</p>"

    word = {"enter": "Buy", "exit": "Sell", "hold": "Hold", "wait": "Wait", "add": "Buy more", "trim": "Sell some"}
    drows = [f"<tr><td>{_d(x['date'])}</td><td><b>{word.get(x['stance'], x['stance'])}</b></td>"
             f"<td class=why>{_e((x['reason'] or 'Nothing new; keep the current position.').replace(' | ', '. '))}</td></tr>"
             for x in reversed(p["decisions"])]

    a = next(c for c in bt["configs"] if c["id"] == "A")["metrics"]
    hold = next(b for b in bt["benchmarks"] if b["id"] == "CONTROL")["metrics"]
    nifty = next(b for b in bt["benchmarks"] if b["id"] == "NIFTY")["metrics"]
    became = lambda m: cap * (1 + m["total_return_pct"] / 100)
    stats = [
        _stat("The agent", _words(became(a)), f"worst fall {a['max_drawdown_pct']:.0f}%"),
        _stat(f"Just holding {sym}", _words(became(hold)), f"worst fall {hold['max_drawdown_pct']:.0f}%"),
        _stat("The Nifty 50 index", _words(became(nifty)), f"worst fall {nifty['max_drawdown_pct']:.0f}%"),
    ]
    # The comparison sentence is computed, never written in: it must stay true as the data changes.
    ratio = became(a) / became(hold)
    level = ("ended up about level with" if 0.9 <= ratio <= 1.1 else
             f"ended up {abs(ratio - 1):.0%} {'ahead of' if ratio > 1 else 'behind'}")
    hold_eq = bt["equity"]["CONTROL"]
    peak_i, trough_i, run_max, best = 0, 0, 0, 0.0
    for i, (_, v) in enumerate(hold_eq):
        if v > hold_eq[run_max][1]:
            run_max = i
        dd_i = v / hold_eq[run_max][1] - 1
        if dd_i < best:
            best, peak_i, trough_i = dd_i, run_max, i
    peak_day, trough_day = hold_eq[peak_i][0], hold_eq[trough_i][0]
    sold_in_fall = any(t["status"] == "CLOSED" and peak_day <= t["exit"] <= trough_day for t in bt["trades"])
    dd_a, dd_h = abs(a["max_drawdown_pct"]), abs(hold["max_drawdown_pct"])
    if dd_a < dd_h - 5:
        risk = f"but its <b>worst fall was {dd_a:.0f}% instead of {dd_h:.0f}%</b>" + (
            f", because it sold during the big drop between {_d(peak_day)} and {_d(trough_day)}" if sold_in_fall else "")
    elif dd_a > dd_h + 5:
        risk = f"and its <b>worst fall was deeper: {dd_a:.0f}% against {dd_h:.0f}%</b>"
    else:
        risk = f"with a similar worst fall ({dd_a:.0f}% against {dd_h:.0f}%)"
    tried = ""
    if ag.get("variants"):
        plain = {"D": "Selling when the price drops sharply (a “stop-loss”)", "E": "Buying extra after a few falling days",
                 "F": "Buying back sooner, once the price recovers"}
        tried = "".join(f"<li><b>{plain.get(k, k)}</b>: {'kept' if v['keep'] else 'not adopted'}. It helped on "
                        f"{v['peers_sharpe_up']} of {v['peers']} similar companies"
                        f"{' and on ' + sym if v['focus_sharpe_up'] else ', and not on ' + sym}.</li>"
                        for k, v in ag["variants"]["verdicts"].items())
    crow = [f"<tr><td><b>{_e(c['id'])}</b></td><td>{_e(c['name'].split('. ', 1)[-1])}</td><td class=n>{_words(became(c['metrics']))}</td>"
            f"<td class=n>{c['metrics']['max_drawdown_pct']:.0f}%</td><td class=n>{c['metrics']['sharpe']:.2f}</td>"
            f"<td class=n>{c['metrics'].get('trades') if c['metrics'].get('trades') is not None else '—'}</td></tr>"
            for c in bt["configs"] + bt["benchmarks"]]
    html_ = f"""
<p class="intro">The agent trades one share, {sym}, on paper. It starts with {_inr(cap)} and grows only by its own profit.</p>
<h3>Paper trades</h3>
{paper_tbl}
{_details(f"Every decision ({len(drows)} so far)", _table(["At the close of", "Decision", "Reason"], drows))}
<h3>How the same rules would have done since {_d(bt['start'])}</h3>
<p class="intro">Starting with {_inr(cap)}, after all trading charges. The agent {level} simply holding,
{risk}. This replay uses rules found on the same period, so it shows how the rules work, not proof that they will keep working.</p>
<div class="stats three">{''.join(stats)}</div>
<div class="legend"><span><i class="k-ink"></i>The agent</span><span><i class="k-bronze"></i>Just holding {sym}</span><span><i class="k-grey"></i>Nifty 50</span></div>
<div class="chart" id="agentEq"></div>
<h3>Its trades in the replay</h3>
{_table(head, trade_rows(bt['trades']))}
<h3>Other rules we tried</h3>
<p class="intro">Each idea was written down before testing and had to help on {sym} and on most similar companies.</p>
<ul class="plain">{tried or '<li>None tested yet.</li>'}</ul>
{_details("Technical comparison", "<p class=fine>“Risk score” is the Sharpe ratio: return per unit of risk. Higher is better.</p>" + _table(["", "Rules", "#₹10 lakh became", "#Worst fall", "#Risk score", "#Trades"], crow))}"""
    return html_, {"A": bt["equity"]["A"], "CONTROL": bt["equity"]["CONTROL"], "NIFTY": bt["equity"]["NIFTY"]}


def _research(d, sym):
    w = d.get("what_happens_when") or {}
    ev = d.get("events") or {}

    def rows(results):
        return [{"desc": PLAIN_LABEL.get(r["condition"], r["description"]), "h": r["horizon"], "verdict": r["verdict"], "plain": PLAIN_VERDICT[r["verdict"]],
                 "edge": r["pooled"].get("mean"), "ci": r["pooled"].get("ci95"), "n": r["pooled"].get("n")} for r in results]

    def count(results, *verdicts):
        return len({r["condition"] for r in results if r["verdict"] in verdicts})
    cr, er = w.get("results", []), ev.get("results", [])
    stats = [
        _stat("Chart patterns tested", f"{len({r['condition'] for r in cr})}", f"{count(cr, 'validated')} proven to work"),
        _stat("Company events tested", f"{len({r['condition'] for r in er})}",
              f"{count(er, 'validated')} proven, {count(er, 'consistent, not yet confirmed')} promising"),
    ]
    toggle = ('<div class="seg" role="group" aria-label="How long after" data-chart="{id}">'
              '<button data-h="1w" aria-pressed="false">1 week</button><button data-h="1m" aria-pressed="true">1 month</button>'
              '<button data-h="3m" aria-pressed="false">3 months</button></div>')
    legend = ('<div class="legend"><span><i class="k-good"></i>Proven</span><span><i class="k-good-o"></i>Promising, not yet proven</span>'
              '<span><i class="k-warn"></i>A weak hint</span><span><i class="k-grey"></i>No effect</span><span><i class="k-grey-o"></i>Too little data</span></div>')
    proven_patterns = count(cr, "validated")
    patterns_line = ("None beat picking a random day." if not proven_patterns else
                     f"{proven_patterns} of them held up in testing.")
    html_ = f"""
<p class="intro">We asked: after something happens, does {sym} (and similar companies) do better or worse than usual over the
following weeks? Each dot is the answer; the line through it is how sure we are. If the line crosses the middle, we can't tell it apart from luck.</p>
<div class="stats three">{''.join(stats)}</div>
<h3>After company events</h3>
<p class="fine">Results days, big orders, rating changes, big share deals and changes in the founders' holding.</p>
{toggle.format(id='events')}{legend}
<div class="chart" id="events"></div>
<h3>After chart patterns</h3>
<p class="fine">Signals people often watch on price charts. {patterns_line}</p>
{toggle.format(id='conds')}{legend}
<div class="chart" id="conds"></div>"""
    return html_, rows(cr), rows(er)


def _method(d, sym):
    q = d["data_quality"]
    yc = q.get("yahoo_crosscheck", {})
    peers = []
    pp = os.path.join(os.path.dirname(DOSSIER_PATH[0]), "peers.json")
    if os.path.exists(pp):
        with open(pp) as f:
            for p in json.load(f):
                if "resid_corr_daily" in p:
                    c = p["resid_corr_daily"]
                    peers.append(f"<tr><td>{_e(p['symbol'])}</td><td>{'Closely' if c >= 0.3 else 'Somewhat' if c >= 0.2 else 'Loosely'}</td>"
                                 f"<td class=n>{c:.2f}</td></tr>")
    checks = "".join(f"<li>{_e(i['detail'])}</li>" for i in q.get("stock", [])) or "<li>No problems found.</li>"
    ca = q.get("corporate_actions_applied", [])
    glossary = [
        ("Opening price", "The first price of the trading day, at 9:15 am. The agent always trades at this price."),
        ("Results", "The company's report of sales and profit for a quarter (three months)."),
        ("Disappointing results", f"On results day the share does at least 3% worse than the market, or profit is lower than a year earlier."),
        ("Worst fall", "The biggest drop from a high point to a later low, before a new high."),
        ("Moves with the market", "How much the share tends to move when the market index moves 1%."),
        ("Orders in hand", "Signed orders the company has yet to deliver: future sales it can count on."),
        ("Proven / promising", "Proven: held up in both halves of our history and after allowing for luck. Promising: looks real, not enough data yet."),
        ("Paper trading", "Recording trades as if they were real, with no money involved, to test the rules honestly."),
        ("Risk score (Sharpe ratio)", "Return earned per unit of risk taken. Higher is better."),
        ("Nifty 50", "An index of India's 50 largest listed companies, used as a yardstick for the market."),
    ]
    return f"""
<h3>Where the numbers come from</h3>
<ul class="plain">
<li>Prices: the National Stock Exchange's official daily files, adjusted for share splits and bonus issues{(' (' + '; '.join(_d(c['ex_date']) for c in ca) + ')') if ca else ''}.</li>
<li>Checked against Yahoo Finance: they agree on {yc.get('common_days', 0) - len(yc.get('close_mismatch_days', []))} of {yc.get('common_days', 0)} trading days.</li>
<li>Company results, orders, ratings and management's statements: the company's own filings with the exchange.</li>
</ul>
{_details("Data checks", f"<ul class='plain'>{checks}</ul>")}
<h3>How we judge evidence</h3>
<ul class="plain">
<li>Every decision uses only what was known at that day's close, and trades at the next day's opening price.</li>
<li>Results are compared with similar companies on the same days, so a rising market or a popular sector isn't mistaken for skill.</li>
<li>Many ideas were tested, so a few will look good by luck. We correct for that, and an idea must also work in both halves of the history.</li>
<li>We check the method itself: a fake signal planted on purpose is found, and a random one is rejected.</li>
</ul>
<h3>Similar companies used for comparison</h3>
{_table(["Company", "Moves with " + sym, "#Score (0 to 1)"], peers)}
<h3>Words used in this report</h3>
<dl class="glossary">{''.join(f'<dt>{_e(k)}</dt><dd>{_e(v)}</dd>' for k, v in glossary)}</dl>"""


# ------------------------------------------------------------------ page

DOSSIER_PATH = [""]


def render(dossier_path, panel):
    DOSSIER_PATH[0] = dossier_path
    with open(dossier_path) as f:
        d = json.load(f)
    folder = os.path.dirname(dossier_path)
    ag = None
    if os.path.exists(os.path.join(folder, "agent.json")):
        with open(os.path.join(folder, "agent.json")) as f:
            ag = json.load(f)
    sym = d["symbol"]
    ev = d.get("events") or {}

    close = panel["Close"].dropna()
    dd = close / close.cummax() - 1
    company_html, revenue = _company(d, sym)
    agent_html, equity = _agent(ag, sym)
    research_html, conds, events = _research(d, sym)
    data = {"dates": [x.date().isoformat() for x in close.index], "close": [round(float(v), 2) for v in close.values],
            "dd": [round(float(v), 4) for v in dd.values], "revenue": revenue, "equity": equity,
            "conds": conds, "events": events}

    tabs = [("today", "Today"), ("company", "The company"), ("shareprice", "The share price"), ("agent", "The agent's record"),
            ("research", "Research"), ("method", "How it works")]
    panels = {
        "today": _today(ag, sym, ev) + f"<h3>{sym} in four sentences</h3><ul class='plain summary'>{_summary(d, sym)}</ul>",
        "company": company_html, "shareprice": _price(d, sym), "agent": agent_html, "research": research_html,
        "method": _method(d, sym),
    }
    nav = "".join(f'<button role="tab" data-tab="{t}" aria-selected="false">{_e(n)}</button>' for t, n in tabs)
    body = "".join(f'<section class="panel" data-tab="{t}" role="tabpanel" hidden>{panels[t]}</section>' for t, _ in tabs)
    page = (PAGE.replace("__SYM__", _e(sym))
            .replace("__ASOF__", _d(d["history"]["last"]))
            .replace("__NAV__", nav).replace("__BODY__", body)
            .replace("__CSS__", CSS).replace("__JS__", JS.replace("__DATA__", json.dumps(data))))
    out = os.path.join(folder, "report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote {out}")
    return out


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__SYM__ Dossier</title>
<script>try { const t = localStorage.getItem('dossier-theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) {}</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>__CSS__</style></head>
<body>
<header class="masthead">
  <div class="brand"><span class="mark">__SYM__</span><span class="sub">Stock dossier · data to __ASOF__</span></div>
  <button id="theme" class="ghost" type="button">Dark</button>
</header>
<nav class="tabbar" role="tablist" aria-label="Sections">__NAV__</nav>
<main>__BODY__</main>
<footer class="foot">Research for paper trading only. Not investment advice. Past behaviour does not guarantee future returns.</footer>
<div class="tip" id="tip" role="tooltip"></div>
<script>__JS__</script>
</body></html>"""

CSS = r"""
:root {
  color-scheme: light;
  --bg:#f6f4ef; --surface:#fbfaf7; --ink:#1a1916; --ink-2:#55524b; --ink-3:#8b877e; --rule:#e5e1d8; --rule-2:#eeebe4;
  --bronze:#9a7a4c; --grey:#a8a49a; --good:#0f8a4a; --down:#b3382f; --warning:#c98a12; --wash:rgba(179,56,47,.08);
  --font:"Modern Era","Manrope",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --bg:#0e0e0d; --surface:#151513; --ink:#f1eee6; --ink-2:#bdb8ad; --ink-3:#86817a; --rule:#2a2925; --rule-2:#201f1c;
    --bronze:#c9a870; --grey:#6d6a63; --good:#3fbf7a; --down:#e0736a; --warning:#e2a93b; --wash:rgba(224,115,106,.10);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg:#0e0e0d; --surface:#151513; --ink:#f1eee6; --ink-2:#bdb8ad; --ink-3:#86817a; --rule:#2a2925; --rule-2:#201f1c;
  --bronze:#c9a870; --grey:#6d6a63; --good:#3fbf7a; --down:#e0736a; --warning:#e2a93b; --wash:rgba(224,115,106,.10);
}
* { box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body { margin:0; background:var(--bg); color:var(--ink); font-family:var(--font); font-weight:400; font-size:16px;
  line-height:1.65; letter-spacing:.005em; -webkit-font-smoothing:antialiased; }
a { color:var(--ink-2); text-underline-offset:3px; }
code { font-size:.9em; background:var(--rule-2); padding:1px 6px; border-radius:4px; }
.masthead, .tabbar, main, .foot { max-width:1040px; margin:0 auto; padding-left:24px; padding-right:24px; }
.masthead { display:flex; justify-content:space-between; align-items:center; gap:16px; padding-top:40px; padding-bottom:8px; }
.brand { display:flex; flex-direction:column; gap:2px; min-width:0; }
.mark { font-size:13px; font-weight:600; letter-spacing:.32em; text-transform:uppercase; }
.brand .sub { font-size:13px; color:var(--ink-3); letter-spacing:.04em; }
.ghost { font:inherit; font-size:12px; letter-spacing:.18em; text-transform:uppercase; padding:9px 16px; border-radius:999px;
  border:1px solid var(--rule); background:transparent; color:var(--ink); cursor:pointer; flex-shrink:0; }
.ghost:hover { border-color:var(--ink-3); }
.tabbar { position:sticky; top:0; z-index:5; display:flex; gap:28px; overflow-x:auto; background:var(--bg);
  border-bottom:1px solid var(--rule); scrollbar-width:none; padding-top:14px; }
.tabbar::-webkit-scrollbar { display:none; }
.tabbar button { font:inherit; font-size:13px; letter-spacing:.12em; text-transform:uppercase; white-space:nowrap;
  padding:12px 0 14px; border:0; border-bottom:1px solid transparent; margin-bottom:-1px; background:none;
  color:var(--ink-3); cursor:pointer; }
.tabbar button:hover { color:var(--ink); }
.tabbar button[aria-selected="true"] { color:var(--ink); border-bottom-color:var(--ink); }
main { padding-top:8px; padding-bottom:40px; }
.panel { animation:fade .35s ease; }
@keyframes fade { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:none; } }
h3 { font-size:12px; font-weight:600; letter-spacing:.22em; text-transform:uppercase; color:var(--ink-2);
  margin:64px 0 18px; padding-top:22px; border-top:1px solid var(--rule); }
.intro { font-size:17px; font-weight:300; color:var(--ink-2); max-width:760px; margin:24px 0 8px; }
.intro b { font-weight:500; color:var(--ink); }
.fine { font-size:13px; color:var(--ink-3); max-width:760px; margin:6px 0 14px; }
.muted { color:var(--ink-3); }
.hero { padding:56px 0 36px; }
.eyebrow { font-size:12px; letter-spacing:.24em; text-transform:uppercase; color:var(--bronze); margin:0 0 18px; }
.statement { font-size:clamp(40px, 7vw, 76px); font-weight:300; letter-spacing:-.025em; line-height:1.04; margin:0;
  overflow-wrap:anywhere; }
.lede { font-size:clamp(17px, 2vw, 20px); font-weight:300; color:var(--ink-2); max-width:720px; margin:22px 0 0; }
.lede b { font-weight:500; color:var(--ink); }
.hero .fine { margin-top:18px; }
.two { display:grid; grid-template-columns:1fr 1fr; gap:48px; }
.two h3 { margin-top:24px; }
ul.plain { list-style:none; padding:0; margin:0; }
ul.plain li { padding:12px 0; border-bottom:1px solid var(--rule-2); color:var(--ink-2); font-weight:300; }
ul.plain li:last-child { border-bottom:0; }
ul.plain li b { font-weight:500; color:var(--ink); }
ul.summary li { font-size:17px; }
.stats { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); border-top:1px solid var(--rule); border-bottom:1px solid var(--rule); margin:22px 0 8px; }
.stats.three { grid-template-columns:repeat(3, minmax(0, 1fr)); }
.stat { padding:22px 20px 22px 0; min-width:0; }
.stat + .stat { padding-left:20px; border-left:1px solid var(--rule); }
.label { font-size:11px; letter-spacing:.2em; text-transform:uppercase; color:var(--ink-3); }
.value { font-size:clamp(26px, 3.2vw, 36px); font-weight:300; letter-spacing:-.015em; margin:10px 0 4px; line-height:1.1; overflow-wrap:anywhere; }
.value.up { color:var(--good); } .value.down { color:var(--down); }
.note { font-size:13px; color:var(--ink-3); overflow-wrap:anywhere; }
.scroll { overflow-x:auto; margin:10px 0; }
table { border-collapse:collapse; width:100%; font-size:14px; font-variant-numeric:tabular-nums; }
th { font-size:11px; font-weight:500; letter-spacing:.16em; text-transform:uppercase; color:var(--ink-3); text-align:left;
  padding:10px 16px 10px 0; border-bottom:1px solid var(--rule); white-space:nowrap; }
td { padding:12px 16px 12px 0; border-bottom:1px solid var(--rule-2); vertical-align:top; color:var(--ink-2); }
td b { color:var(--ink); font-weight:500; }
th.n, td.n { text-align:right; white-space:nowrap; }
td.up { color:var(--good); } td.down { color:var(--down); }
td.why { min-width:240px; font-size:13px; color:var(--ink-3); }
td.dt, tbody td:first-child { white-space:nowrap; }
details.more { border-bottom:1px solid var(--rule-2); margin:6px 0; }
details.more summary { cursor:pointer; list-style:none; padding:14px 0; font-size:13px; letter-spacing:.14em; text-transform:uppercase; color:var(--ink-2); }
details.more summary::-webkit-details-marker { display:none; }
details.more summary::before { content:"+"; display:inline-block; width:22px; color:var(--bronze); }
details.more[open] summary::before { content:"−"; }
.more-body { padding:0 0 18px; }
ul.quotes { list-style:none; padding:0; margin:0; }
ul.quotes li { padding:12px 0; border-bottom:1px solid var(--rule-2); color:var(--ink-2); font-size:14px; }
.date { display:inline-block; min-width:150px; color:var(--ink-3); font-size:13px; }
.quote { color:var(--ink-3); font-size:13px; font-style:italic; }
.chart { position:relative; width:100%; margin:8px 0 6px; min-height:40px; }
.chart svg { display:block; width:100%; overflow:visible; }
.axis text { fill:var(--ink-3); font-size:11px; font-family:var(--font); font-variant-numeric:tabular-nums; }
.grid { stroke:var(--rule-2); stroke-width:1; }
.legend { display:flex; flex-wrap:wrap; gap:8px 22px; font-size:12px; color:var(--ink-2); margin:14px 0 4px; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:8px; vertical-align:-1px; }
.k-ink { background:var(--ink); } .k-bronze { background:var(--bronze); } .k-grey { background:var(--grey); }
.k-good { background:var(--good); } .k-warn { background:var(--warning); }
.k-good-o { border:1.5px solid var(--good); } .k-grey-o { border:1.5px solid var(--grey); }
.seg { display:inline-flex; border:1px solid var(--rule); border-radius:999px; padding:3px; margin:10px 0 0; }
.seg button { font:inherit; font-size:12px; letter-spacing:.1em; text-transform:uppercase; padding:6px 14px; border-radius:999px;
  border:0; background:none; color:var(--ink-3); cursor:pointer; }
.seg button[aria-pressed="true"] { background:var(--ink); color:var(--bg); }
dl.glossary { display:grid; grid-template-columns:minmax(160px, 240px) 1fr; gap:0; margin:0; }
dl.glossary dt, dl.glossary dd { padding:12px 0; border-bottom:1px solid var(--rule-2); margin:0; }
dl.glossary dt { font-weight:500; padding-right:20px; } dl.glossary dd { color:var(--ink-2); font-weight:300; }
.foot { font-size:12px; color:var(--ink-3); letter-spacing:.04em; padding-top:28px; padding-bottom:48px; border-top:1px solid var(--rule); }
.tip { position:fixed; pointer-events:none; z-index:20; display:none; max-width:300px; padding:10px 12px; font-size:13px; line-height:1.5;
  background:var(--surface); color:var(--ink); border:1px solid var(--rule); border-radius:8px; box-shadow:0 8px 28px rgba(0,0,0,.14); }
.tip b { font-weight:600; }
@media (max-width: 760px) {
  .masthead, .tabbar, main, .foot { padding-left:16px; padding-right:16px; }
  .two { grid-template-columns:1fr; gap:0; }
  .stats, .stats.three { grid-template-columns:1fr 1fr; }
  .stat:nth-child(odd) { padding-left:0; border-left:0; }
  .stat:nth-child(n+3) { border-top:1px solid var(--rule); }
  .tabbar { gap:20px; -webkit-mask-image:linear-gradient(90deg, #000 85%, transparent); mask-image:linear-gradient(90deg, #000 85%, transparent); padding-right:40px; }
  dl.glossary { grid-template-columns:1fr; } dl.glossary dt { border-bottom:0; padding-bottom:0; }
}
"""

JS = r"""
const D = __DATA__;
const tip = document.getElementById('tip');
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const fmtDate = s => { const [y, m, d] = s.split('-').map(Number); return d + ' ' + MONTHS[m - 1] + ' ' + y; };
const pct = (x, sign) => x == null ? '—' : ((sign && x > 0 ? '+' : '') + (x * 100).toFixed(1) + '%');
const lakh = v => v >= 1e7 ? '₹' + (v / 1e7).toFixed(2) + ' crore' : '₹' + (v / 1e5).toFixed(1) + ' lakh';
const NS = 'http://www.w3.org/2000/svg';
const el = (t, a, p) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };

// Tooltip: fixed-position and clamped inside the window so it never runs off-screen or covers the pointer.
function showTip(ev, html) {
  tip.innerHTML = html; tip.style.display = 'block';
  const pad = 12, w = tip.offsetWidth, h = tip.offsetHeight, vw = innerWidth, vh = innerHeight;
  let x = ev.clientX + 16, y = ev.clientY + 16;
  if (x + w + pad > vw) x = ev.clientX - w - 16;
  if (y + h + pad > vh) y = ev.clientY - h - 16;
  tip.style.left = Math.max(pad, x) + 'px'; tip.style.top = Math.max(pad, y) + 'px';
}
const hideTip = () => { tip.style.display = 'none'; };

// Fit text into a width, adding an ellipsis; the full text stays available in the tooltip.
function fitText(node, text, width) {
  node.textContent = text;
  if (node.getComputedTextLength() <= width) return;
  let lo = 0, hi = text.length;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; node.textContent = text.slice(0, mid) + '…';
    if (node.getComputedTextLength() <= width) lo = mid; else hi = mid - 1; }
  node.textContent = text.slice(0, lo) + '…';
}

// X-axis year labels that never collide: each is placed only if it clears the previous one.
function yearLabels(g, dates, xs, y, first) {
  let lastYear = null, lastEnd = -1e9;
  dates.forEach((s, i) => {
    const yr = s.slice(0, 4); if (yr === lastYear) return; lastYear = yr;
    if (i === 0 && !first) return;
    const t = el('text', {x: xs(i), y, 'text-anchor': i === 0 ? 'start' : 'middle'}, g);
    t.textContent = i === 0 ? fmtDate(s) : yr;
    const w = t.getComputedTextLength(), left = i === 0 ? xs(i) : xs(i) - w / 2;
    if (left < lastEnd + 14) { t.remove(); return; }
    lastEnd = left + w;
  });
}

function lineChart(id, ys, o) {
  const host = document.getElementById(id); if (!host) return; host.innerHTML = '';
  const W = host.clientWidth; if (!W) return;
  const H = o.h, m = {l: 60, r: 12, t: 12, b: 30};
  const svg = el('svg', {viewBox: `0 0 ${W} ${H}`, height: H, role: 'img', 'aria-label': o.label}, host);
  const n = ys.length, xs = i => m.l + (W - m.l - m.r) * i / (n - 1);
  const tv = o.log ? ys.map(Math.log) : ys;
  let lo = Math.min(...tv), hi = o.zeroTop ? 0 : Math.max(...tv);
  const yv = v => m.t + (H - m.t - m.b) * (1 - ((o.log ? Math.log(v) : v) - lo) / (hi - lo || 1));
  const g = el('g', {class: 'axis'}, svg);
  let lastY = -1e9;
  o.ticks(lo, hi).forEach(t => { const y = yv(t); if (Math.abs(y - lastY) < 16) return; lastY = y;
    el('line', {x1: m.l, x2: W - m.r, y1: y, y2: y, class: 'grid'}, g);
    el('text', {x: m.l - 10, y: y + 4, 'text-anchor': 'end'}, g).textContent = o.fmt(t); });
  yearLabels(g, D.dates, xs, H - 8, true);
  const path = ys.map((v, i) => (i ? 'L' : 'M') + xs(i).toFixed(1) + ' ' + yv(v).toFixed(1)).join('');
  if (o.area) el('path', {d: path + `L${xs(n - 1)} ${yv(0)}L${xs(0)} ${yv(0)}Z`, fill: css('--wash'), stroke: 'none'}, svg);
  el('path', {d: path, fill: 'none', stroke: css(o.color), 'stroke-width': 1.6, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}, svg);
  el('circle', {cx: xs(n - 1), cy: yv(ys[n - 1]), r: 4, fill: css(o.color), stroke: css('--bg'), 'stroke-width': 2}, svg);
  const cross = el('line', {y1: m.t, y2: H - m.b, stroke: css('--ink-3'), 'stroke-width': 1, visibility: 'hidden'}, svg);
  const dot = el('circle', {r: 4, fill: css(o.color), stroke: css('--bg'), 'stroke-width': 2, visibility: 'hidden'}, svg);
  const hit = el('rect', {x: m.l, y: 0, width: W - m.l - m.r, height: H, fill: 'transparent'}, svg);
  hit.addEventListener('mousemove', e => {
    const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(n - 1, Math.round((px - m.l) / (W - m.l - m.r) * (n - 1))));
    cross.setAttribute('x1', xs(i)); cross.setAttribute('x2', xs(i)); cross.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', xs(i)); dot.setAttribute('cy', yv(ys[i])); dot.setAttribute('visibility', 'visible');
    showTip(e, `<b>${fmtDate(D.dates[i])}</b><br>${o.tipFmt(ys[i])}`);
  });
  hit.addEventListener('mouseleave', () => { cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); hideTip(); });
}

function equityChart(id, S) {
  const host = document.getElementById(id); if (!host || !S) return; host.innerHTML = '';
  const W = host.clientWidth; if (!W) return;
  const keys = [['A', 'The agent', '--ink'], ['CONTROL', 'Just holding', '--bronze'], ['NIFTY', 'Nifty 50', '--grey']];
  const dates = S.A.map(p => p[0]);
  const val = {}; keys.forEach(([k]) => { val[k] = new Map(S[k].map(p => [p[0], p[1]])); });
  const H = 300, m = {l: 70, r: 12, t: 12, b: 30};
  const svg = el('svg', {viewBox: `0 0 ${W} ${H}`, height: H, role: 'img', 'aria-label': 'Account value: agent, just holding, Nifty 50'}, host);
  const all = keys.flatMap(([k]) => S[k].map(p => p[1]));
  const lo = Math.log(Math.min(...all)), hi = Math.log(Math.max(...all));
  const xs = i => m.l + (W - m.l - m.r) * i / (dates.length - 1);
  const y = v => m.t + (H - m.t - m.b) * (1 - (Math.log(v) - lo) / (hi - lo));
  const g = el('g', {class: 'axis'}, svg);
  [5e5, 1e6, 2e6, 5e6, 1e7, 2e7].forEach(t => { if (t < Math.exp(lo) * 0.9 || t > Math.exp(hi) * 1.1) return;
    el('line', {x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), class: 'grid'}, g);
    el('text', {x: m.l - 10, y: y(t) + 4, 'text-anchor': 'end'}, g).textContent = t >= 1e7 ? '₹' + t / 1e7 + ' crore' : '₹' + t / 1e5 + ' lakh'; });
  yearLabels(g, dates, xs, H - 8, false);
  keys.forEach(([k, , c]) => {
    const pts = dates.map((d, i) => [xs(i), val[k].get(d)]).filter(p => p[1] != null);
    el('path', {d: pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + y(p[1]).toFixed(1)).join(''), fill: 'none',
      stroke: css(c), 'stroke-width': k === 'A' ? 2 : 1.4, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}, svg);
  });
  const cross = el('line', {y1: m.t, y2: H - m.b, stroke: css('--ink-3'), 'stroke-width': 1, visibility: 'hidden'}, svg);
  const hit = el('rect', {x: m.l, y: 0, width: W - m.l - m.r, height: H, fill: 'transparent'}, svg);
  hit.addEventListener('mousemove', e => {
    const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(dates.length - 1, Math.round((px - m.l) / (W - m.l - m.r) * (dates.length - 1))));
    cross.setAttribute('x1', xs(i)); cross.setAttribute('x2', xs(i)); cross.setAttribute('visibility', 'visible');
    showTip(e, `<b>Week of ${fmtDate(dates[i])}</b>` + keys.map(([k, label]) => `<br>${label}: ${val[k].has(dates[i]) ? lakh(val[k].get(dates[i])) : '—'}`).join(''));
  });
  hit.addEventListener('mouseleave', () => { cross.setAttribute('visibility', 'hidden'); hideTip(); });
}

function barChart(id, rows) {
  const host = document.getElementById(id); if (!host || !rows.length) return; host.innerHTML = '';
  const W = host.clientWidth; if (!W) return;
  const H = 240, m = {l: 70, r: 8, t: 12, b: 30};
  const svg = el('svg', {viewBox: `0 0 ${W} ${H}`, height: H, role: 'img', 'aria-label': 'Sales each quarter'}, host);
  const max = Math.max(...rows.map(r => r.v)), n = rows.length;
  const step = (W - m.l - m.r) / n, bw = Math.max(4, Math.min(22, step - 8));
  const y = v => m.t + (H - m.t - m.b) * (1 - v / max);
  const g = el('g', {class: 'axis'}, svg);
  const tick = max > 5e9 ? 2e9 : max > 2e9 ? 1e9 : 5e8;
  for (let t = 0; t <= max; t += tick) { el('line', {x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), class: 'grid'}, g);
    el('text', {x: m.l - 10, y: y(t) + 4, 'text-anchor': 'end'}, g).textContent = '₹' + (t / 1e7).toLocaleString('en-IN') + ' cr'; }
  let lastEnd = -1e9;
  rows.forEach((r, i) => {
    const x = m.l + i * step + (step - bw) / 2, top = y(r.v), base = y(0), rr = Math.min(3, (base - top) / 2);
    el('path', {d: `M${x} ${base}V${top + rr}Q${x} ${top} ${x + rr} ${top}H${x + bw - rr}Q${x + bw} ${top} ${x + bw} ${top + rr}V${base}Z`,
      fill: css(i === n - 1 ? '--ink' : '--bronze')}, svg);
    const lab = el('text', {x: x + bw / 2, y: H - 8, 'text-anchor': 'middle'}, g);
    const [yy, mm] = r.q.split('-'); lab.textContent = MONTHS[+mm - 1].slice(0, 3) + ' ' + yy.slice(2);
    const w = lab.getComputedTextLength();
    if (x + bw / 2 - w / 2 < lastEnd + 10) lab.remove(); else lastEnd = x + bw / 2 + w / 2;
    const hit = el('rect', {x: m.l + i * step, y: m.t, width: step, height: H - m.t - m.b, fill: 'transparent'}, svg);
    hit.addEventListener('mousemove', e => showTip(e, `<b>Quarter to ${fmtDate(r.q)}</b><br>Sales ₹${(r.v / 1e7).toLocaleString('en-IN', {maximumFractionDigits: 0})} crore`));
    hit.addEventListener('mouseleave', hideTip);
  });
}

const HSTATE = {conds: '1m', events: '1m'};
const VCOL = {'validated': '--good', 'consistent, not yet confirmed': '--good', 'suggestive (not validated)': '--warning', 'no evidence': '--grey', 'insufficient data': '--grey'};
const HOLLOW = new Set(['insufficient data', 'consistent, not yet confirmed']);
const SPAN = {'1w': 'week', '1m': 'month', '3m': 'three months'};
function dotChart(id, all) {
  const host = document.getElementById(id); if (!host) return; host.innerHTML = '';
  const W = host.clientWidth; if (!W) return;
  const rows = all.filter(r => r.h === HSTATE[id] && r.edge != null).sort((a, b) => b.edge - a.edge);
  const narrow = W < 640, labelW = narrow ? W - 24 : Math.min(360, W * 0.42);
  const rowH = narrow ? 46 : 30, m = {l: narrow ? 8 : labelW + 20, r: 12, t: 28, b: 8}, Hh = m.t + rows.length * rowH + m.b;
  const svg = el('svg', {viewBox: `0 0 ${W} ${Hh}`, height: Hh, role: 'img', 'aria-label': 'What happened next'}, host);
  const ext = Math.max(0.03, ...rows.map(r => Math.max(Math.abs(r.ci ? r.ci[0] : r.edge), Math.abs(r.ci ? r.ci[1] : r.edge))));
  const x = v => m.l + (W - m.l - m.r) * (v + ext) / (2 * ext);
  const g = el('g', {class: 'axis'}, svg);
  const step = ext > 0.2 ? 0.1 : ext > 0.08 ? 0.05 : 0.02;
  let lastEnd = -1e9;
  for (let t = -Math.floor(ext / step) * step; t <= ext + 1e-9; t += step) {
    const xx = x(t); el('line', {x1: xx, x2: xx, y1: m.t - 6, y2: Hh - m.b, class: 'grid'}, g);
    const lab = el('text', {x: xx, y: 14, 'text-anchor': 'middle'}, g); lab.textContent = (t > 0 ? '+' : '') + Math.round(t * 100) + '%';
    const w = lab.getComputedTextLength(); if (xx - w / 2 < lastEnd + 8) lab.remove(); else lastEnd = xx + w / 2;
  }
  el('line', {x1: x(0), x2: x(0), y1: m.t - 6, y2: Hh - m.b, stroke: css('--ink-3'), 'stroke-width': 1}, svg);
  rows.forEach((r, i) => {
    const cy = m.t + i * rowH + (narrow ? 32 : rowH / 2), c = css(VCOL[r.verdict]);
    const lab = el('text', {x: narrow ? m.l : labelW, y: narrow ? cy - 16 : cy + 4, 'text-anchor': narrow ? 'start' : 'end', fill: css('--ink-2'), 'font-size': 13}, svg);
    fitText(lab, r.desc, labelW);
    if (r.ci) el('line', {x1: x(r.ci[0]), x2: x(r.ci[1]), y1: cy, y2: cy, stroke: c, 'stroke-width': 1.6, 'stroke-linecap': 'round'}, svg);
    const hollow = HOLLOW.has(r.verdict);
    el('circle', {cx: x(r.edge), cy, r: 5, fill: hollow ? css('--bg') : c, stroke: hollow ? c : css('--bg'), 'stroke-width': 2}, svg);
    const hit = el('rect', {x: 0, y: cy - rowH / 2, width: W, height: rowH, fill: 'transparent'}, svg);
    hit.addEventListener('mousemove', e => showTip(e, `<b>${r.desc}</b><br>${r.plain}<br>Over the next ${SPAN[r.h]}: ` +
      `${r.edge >= 0 ? 'better' : 'worse'} than usual by ${pct(Math.abs(r.edge))}` + (r.ci ? `<br>Likely somewhere between ${pct(r.ci[0], true)} and ${pct(r.ci[1], true)}` : '') +
      `<br>Seen ${r.n} times`));
    hit.addEventListener('mouseleave', hideTip);
  });
}
document.querySelectorAll('.seg').forEach(group => group.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
  HSTATE[group.dataset.chart] = b.dataset.h;
  group.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b));
  dotChart(group.dataset.chart, D[group.dataset.chart]);
})));

function logTicks(lo, hi) { const a = Math.exp(lo), b = Math.exp(hi), out = [];
  [100, 200, 500, 1000, 2000, 3000, 5000, 10000, 20000].forEach(t => { if (t >= a * 0.98 && t <= b * 1.02) out.push(t); }); return out; }
function ddTicks(lo) { const out = []; for (let t = 0; t >= lo - 1e-9; t -= 0.1) out.push(+t.toFixed(1)); return out.length > 6 ? out.filter((_, i) => i % 2 === 0) : out; }

function drawAll() {
  lineChart('price', D.close, {h: 300, log: true, color: '--ink', label: 'Share price since listing', ticks: logTicks,
    fmt: v => '₹' + v.toLocaleString('en-IN'), tipFmt: v => 'Closing price ₹' + v.toLocaleString('en-IN', {minimumFractionDigits: 2})});
  lineChart('dd', D.dd, {h: 200, area: true, zeroTop: true, color: '--down', label: 'How far below its high', ticks: ddTicks,
    fmt: v => Math.round(v * 100) + '%', tipFmt: v => v === 0 ? 'At a new high' : (v * 100).toFixed(1) + '% below its high'});
  barChart('revbars', D.revenue);
  equityChart('agentEq', D.equity);
  dotChart('conds', D.conds);
  dotChart('events', D.events);
}

const store = { get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
                set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} } };
const isDark = () => { const t = document.documentElement.dataset.theme; return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; };
const paintTheme = () => { document.getElementById('theme').textContent = isDark() ? 'Light' : 'Dark'; };
document.getElementById('theme').addEventListener('click', () => {
  const next = isDark() ? 'light' : 'dark'; document.documentElement.dataset.theme = next; store.set('dossier-theme', next);
  paintTheme(); drawAll();
});
function showTab(id) {
  const tabs = [...document.querySelectorAll('.tabbar button')];
  if (!tabs.some(b => b.dataset.tab === id)) id = tabs[0].dataset.tab;
  tabs.forEach(b => b.setAttribute('aria-selected', b.dataset.tab === id));
  document.querySelectorAll('.panel').forEach(p => { p.hidden = p.dataset.tab !== id; });
  if (location.hash !== '#' + id) history.replaceState(null, '', '#' + id);
  hideTip(); drawAll();
}
document.querySelectorAll('.tabbar button').forEach(b => b.addEventListener('click', () => { showTab(b.dataset.tab); scrollTo({top: 0}); }));
paintTheme();
showTab(location.hash.slice(1));
scrollTo(0, 0);
if (document.fonts) document.fonts.ready.then(drawAll);
let rt; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(drawAll, 120); });
addEventListener('scroll', hideTip, {passive: true});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', drawAll);
"""
