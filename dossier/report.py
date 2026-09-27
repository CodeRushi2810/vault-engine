"""Readable HTML report for a dossier. Written next to dossier.json.

Self-contained: one file, no network needed, charts drawn from embedded data.
"""
import html
import json
import os
from datetime import date

import numpy as np

from dossier.universe import INDICES

VERDICT_ORDER = ["validated", "consistent, not yet confirmed", "suggestive (not validated)", "no evidence", "insufficient data"]


def _d(iso):
    """ISO date -> '25 September 2026'."""
    if not iso:
        return "—"
    y, m, d = map(int, str(iso)[:10].split("-"))
    return f"{d} {date(y, m, d):%B %Y}"


def _pct(x, digits=1, sign=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x * 100:{'+' if sign else ''}.{digits}f}%"


def _num(x, digits=2):
    return "—" if x is None else f"{x:,.{digits}f}"


def _esc(s):
    return html.escape(str(s))


def _headline(d):
    w = d.get("what_happens_when") or {}
    res = [r for r in w.get("results", [])]
    counts = {v: sum(r["verdict"] == v for r in res) for v in VERDICT_ORDER}
    active = w.get("now", {}).get("active", [])
    tests = w.get("method", {}).get("tests", len(res))
    lines = []
    if counts["validated"]:
        names = sorted({r["description"] for r in res if r["verdict"] == "validated"})
        lines.append(f"<b>{counts['validated']}</b> of {tests} condition/horizon tests passed out-of-sample validation: "
                     + "; ".join(_esc(n) for n in names) + ".")
    else:
        lines.append(f"<b>None</b> of the {tests} condition/horizon tests passed out-of-sample validation. "
                     f"{counts['suggestive (not validated)']} looked promising on the full sample, which is about what "
                     f"chance alone produces ({tests} × 5% ≈ {round(tests * 0.05)}). On this evidence, no condition "
                     "tells you more about NETWEB's next week, month or quarter than a random day does.")
    if active:
        verdicts = {}
        for a in active:
            vs = {r["horizon"]: r["verdict"] for r in res if r["condition"] == a["condition"]}
            verdicts[a["condition"]] = vs
        parts = []
        for a in active:
            vs = verdicts[a["condition"]]
            best = ("a validated edge" if "validated" in vs.values() else
                    "a suggestive but unvalidated edge" if any(v.startswith("sugg") for v in vs.values()) else
                    "no evidence of an edge")
            parts.append(f"{_esc(a['description'].lower())} (since {_d(a['since'])}; history shows {best})")
        lines.append("Right now: " + "; ".join(parts) + ".")
    ev = d.get("events") or {}
    er = ev.get("results", [])
    if er:
        strong = [r for r in er if r["verdict"] in ("validated", "consistent, not yet confirmed")]
        if strong:
            best = min(strong, key=lambda r: r["pooled"]["p"])
            span = {"1w": "week", "1m": "month", "3m": "quarter"}
            same = sorted((r for r in strong if r["condition"] == best["condition"]), key=lambda r: r["h"])
            moves = " and ".join(f"{_pct(abs(r['pooled']['mean']), 1)} over the next {span[r['horizon']]}" for r in same)
            word = "trail" if best["pooled"]["mean"] < 0 else "beat"
            lines.append(f"<b>Events:</b> the strongest finding is <i>{_esc(best['description'].lower())}</i>. "
                         f"Those stocks went on to {word} their peers by {moves} ({best['pooled']['n']} events). It passes the multiple-testing check and points the same way "
                         "before and after the split, but the earlier half alone is not significant, so treat it as a "
                         "risk rule to watch, not a proven edge.")
        else:
            lines.append(f"<b>Events:</b> none of the {ev.get('method', {}).get('tests', len(er))} event tests passed validation.")
    return lines


def render(dossier_path, panel):
    with open(dossier_path) as f:
        d = json.load(f)
    a = d["anatomy"]
    q = d["data_quality"]
    w = d.get("what_happens_when") or {"results": [], "now": {"active": []}, "method": {}}
    sym = d["symbol"]

    agent_path = os.path.join(os.path.dirname(dossier_path), "agent.json")
    agent_data = None
    if os.path.exists(agent_path):
        with open(agent_path) as f:
            agent_data = json.load(f)
    agent_html, agent_series = _agent_html(agent_data)

    close = panel["Close"].dropna()
    dd = close / close.cummax() - 1
    series = {
        "dates": [x.date().isoformat() for x in close.index],
        "close": [round(float(v), 2) for v in close.values],
        "dd": [round(float(v), 4) for v in dd.values],
    }
    cond_rows = _rows(w["results"])
    ev = d.get("events") or {"results": [], "results_profile": {}, "focus_recent": [], "upcoming": [], "method": {}}
    event_rows = _rows(ev["results"])
    events_html = _events_html(ev, sym)
    score_html, revenue_series = _scorecard_html(ev.get("scorecard") or {})

    ret, vol, dr, fr, rel = a["returns"], a["volatility"], a["drawdowns"], a["forward_returns"], a["relationships"]
    last_close = series["close"][-1]
    as_of = d["history"]["last"]

    tiles = [
        ("Last close", f"₹{last_close:,.2f}", _d(as_of)),
        ("Growth per year since listing", _pct(ret["cagr"], 0), f"{ret['years']} years of history"),
        ("Volatility (annual)", _pct(vol["rv20_now"], 0) + " now", f"{_pct(ret['ann_vol'], 0)} over its whole history"),
        ("Typical daily range (ATR)", _pct(vol["atr14_pct_now"]), f"median {_pct(vol['atr14_pct_median'])}"),
        ("Below its peak", _pct(dr["current_drawdown"], 0), f"worst ever {_pct(dr['max_drawdown'], 0)}"),
        ("Volatility regime", vol["regime_now"].capitalize(), f"{_pct(vol['rv20_percentile_now'], 0)} percentile"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="tl">{_esc(l)}</div><div class="tv">{v}</div>'
                         f'<div class="ts">{_esc(s)}</div></div>' for l, v, s in tiles)

    fwd_rows = "".join(
        f"<tr><td>{k}</td><td class=n>{x['n_independent']}</td><td class=n>{_pct(x['mean'], 1, True)}</td>"
        f"<td class=n>{(_pct(x['mean_ci95'][0], 1, True) + ' to ' + _pct(x['mean_ci95'][1], 1, True)) if x.get('mean_ci95') else '<span class=muted>too few to say</span>'}</td>"
        f"<td class=n>{_pct(x['p_positive'], 0)}</td><td class=n>{_pct(x['p10'], 0, True)}</td><td class=n>{_pct(x['p90'], 0, True)}</td>"
        f"<td class=n>{_pct(x['median_worst_dip'], 1)}</td></tr>"
        for k, x in fr.items() if "mean" in x)

    rel_rows = "".join(
        f"<tr{' class=hl' if k == rel.get('best_fit_index') else ''}><td>{_esc(INDICES.get(k, k))}</td>"
        f"<td class=n>{x['beta']:.2f}</td><td class=n>{x['downside_beta']:.2f}</td><td class=n>{x['upside_beta']:.2f}</td>"
        f"<td class=n>{_pct(x['r_squared'], 0)}</td><td class=n>{x['n_days']}</td></tr>"
        for k, x in rel.items() if isinstance(x, dict))

    peers_path = os.path.join(os.path.dirname(dossier_path), "peers.json")
    peer_rows = ""
    if os.path.exists(peers_path):
        with open(peers_path) as f:
            for p in json.load(f):
                if "resid_corr_daily" in p:
                    lo, hi = p["resid_corr_ci95"]
                    peer_rows += (f"<tr><td>{_esc(p['symbol'])}</td><td>{_esc(p['role'])}</td>"
                                  f"<td class=n>{p['resid_corr_daily']:.2f}</td><td class=n>{lo:.2f} to {hi:.2f}</td>"
                                  f"<td class=n>{p['overlap_days']}</td><td class=n>{_pct(p['ann_vol'], 0)}</td></tr>")

    now_rows = ""
    for act in w["now"].get("active", []):
        vs = {r["h"]: r for r in cond_rows if r["key"] == act["condition"]}
        cells = "".join(f"<td>{_badge(vs[h]['verdict'])} <span class=n>{_pct(vs[h]['edge'], 1, True)}</span></td>" if h in vs else "<td>—</td>"
                        for h in ("1w", "1m", "3m"))
        now_rows += (f"<tr><td>{_esc(act['description'])}</td><td>{_d(act['since'])}</td>"
                     f"<td class=n>{act['sessions_since_onset']}</td>{cells}</tr>")
    if not now_rows:
        now_rows = "<tr><td colspan=6 class=muted>No tracked condition is active at the latest close.</td></tr>"

    issues = q.get("stock", [])
    issue_rows = "".join(f"<li><b>{_esc(i['check'].replace('_', ' '))}</b> — {_esc(i['detail'])}</li>" for i in issues) \
        or "<li>No problems found in the NSE bars.</li>"
    yc = q.get("yahoo_crosscheck", {})
    yahoo_line = (f"Yahoo agrees on {yc.get('common_days', 0) - len(yc.get('close_mismatch_days', []))} of "
                  f"{yc.get('common_days', 0)} shared sessions. Differences: "
                  f"{', '.join(_d(x) for x in yc.get('close_mismatch_days', [])) or 'none'}; "
                  f"{yc.get('yahoo_placeholder_days', 0)} Yahoo placeholder bars set aside; "
                  f"{yc.get('missing_in_yahoo', 0)} NSE sessions Yahoo lacks.") if "common_days" in yc else \
        f"Cross-check unavailable: {_esc(yc.get('error', 'not run'))}"
    ca = q.get("corporate_actions_applied", [])
    ca_line = "; ".join(f"{_d(c['ex_date'])}: {_esc(c['subject'])}" for c in ca) or "None since listing."

    m = w.get("method", {})
    headline = "".join(f"<p>{l}</p>" for l in _headline(d))
    page = TEMPLATE.format(
        sym=_esc(sym), as_of=_d(as_of), generated=_d(d["generated_at"][:10]),
        first=_d(d["history"]["first"]), bars=d["history"]["bars"],
        headline=headline, tiles=tiles_html, fwd_rows=fwd_rows, rel_rows=rel_rows, agent=agent_html,
        peer_rows=peer_rows or "<tr><td colspan=6 class=muted>Run <code>python -m dossier.run peers</code>.</td></tr>",
        now_rows=now_rows, issue_rows=issue_rows, yahoo_line=yahoo_line, ca_line=ca_line,
        pool=", ".join(m.get("pool", [])), val_start=_d(m.get("validation_start")), tests=m.get("tests", "—"),
        abn_vs=_esc(m.get("abnormal_vs", "")), best_fit=_esc(INDICES.get(rel.get("best_fit_index"), "—")),
        worst_dd=_pct(-dr['max_drawdown'], 0), worst_peak=_d(_worst(dr)[0]), worst_trough=_d(_worst(dr)[1]),
        legend=LEGEND, ev_tiles=events_html["tiles"], ev_table=events_html["table"], ev_upcoming=events_html["upcoming"],
        ev_recent=events_html["recent"], ev_tests=events_html["tests"], ev_cut=events_html["cut"],
        scorecard=score_html,
        data=json.dumps({"series": series, "conds": cond_rows, "events": event_rows, "revenue": revenue_series, "agent": agent_series}),
    )
    out = os.path.join(os.path.dirname(dossier_path), "report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote {out}")
    return out


def _rows(results):
    return [{
        "key": r["condition"], "desc": r["description"], "h": r["horizon"], "verdict": r["verdict"],
        "edge": r["pooled"].get("mean"), "ci": r["pooled"].get("ci95"), "p": r["pooled"].get("p"),
        "n": r["pooled"].get("n"), "clusters": r["pooled"].get("clusters"),
        "disc": r["discovery"].get("mean"), "val": r["validation"].get("mean"),
        "nw_n": r["netweb"].get("n"), "nw_est": r["netweb_estimate"], "raw": r["pooled_raw"].get("mean"),
        "hit": r["pooled"].get("hit_rate"), "baseline": r.get("baseline"),
    } for r in results]


def _inr(x):
    """Indian digit grouping: 5904417 -> '59,04,417'."""
    if x is None:
        return "—"
    neg, n = x < 0, f"{abs(x):.0f}"
    head, tail = n[:-3], n[-3:]
    while len(head) > 2:
        tail = head[-2:] + "," + tail
        head = head[:-2]
    s = (head + "," + tail) if head else tail
    return ("−₹" if neg else "₹") + s


def _agent_html(ag):
    """The trading agent section: paper ledger first, then the backtest."""
    if not ag:
        return ("<h2>Trading agent</h2><div class='card'><p class=muted>No agent run yet. Run "
                "<code>python -m dossier.run agent</code> after the close.</p></div>"), None
    p, bt = ag["paper"], ag["backtest"]
    cap = ag["capital"]
    ret = p["equity"] / cap - 1
    last = p["decisions"][-1] if p["decisions"] else {}
    stance = (last.get("stance") or "—").upper()
    pend = p.get("pending")
    pos = p.get("open")
    order_txt = "No order"
    if pend:
        if pend["side"] == "buy":
            order_txt = f"BUY at the next open, about {pend['weight']:.0%} of the account"
        elif pend["side"] == "add":
            order_txt = f"ADD {pend['weight']:.0%} of the account at the next open"
        elif pend["side"] == "trim":
            order_txt = f"TRIM {pend['shares']} shares at the next open"
        else:
            order_txt = "SELL everything at the next open"
    tiles = [
        ("Paper account value", _inr(p["equity"]), f"{ret:+.1%} vs the {_inr(cap)} start"),
        ("Cash", _inr(p["cash"]), f"{p['cash'] / p['equity']:.0%} of the account"),
        ("Position", f"{pos['shares']} shares" if pos else "None",
         f"bought at ₹{pos['entry_price']:,.2f} · {_inr(pos['pnl'])} ({pos['pnl_pct']:+.1f}%)" if pos else "flat"),
        (f"Decision at the close of {_d(last.get('date'))}", stance, order_txt),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="tl">{_esc(l)}</div><div class="tv">{_esc(v)}</div>'
                         f'<div class="ts">{_esc(s)}</div></div>' for l, v, s in tiles)
    why = [w for w in ((pend or {}).get("reason") or last.get("reason") or "").split(" | ") if w]
    why_html = "".join(f"<li>{_esc(w)}</li>" for w in why) or "<li class=muted>No change: holding, no new signal.</li>"

    def trade_rows(rows, reasons=True):
        out = ""
        for t in reversed(rows):
            cls = "pos" if t["pnl"] > 0 else "neg"
            out += (f"<tr><td>{'<b>Open</b>' if t['status'] == 'OPEN' else 'Closed'}</td>"
                    f"<td>{_d(t['entry'])}</td><td class=n>₹{t['entry_price']:,.2f}</td>"
                    f"<td>{'—' if t['status'] == 'OPEN' else _d(t['exit'])}</td>"
                    f"<td class=n>₹{t['exit_price']:,.2f}{' <span class=muted>(now)</span>' if t['status'] == 'OPEN' else ''}</td>"
                    f"<td class=n>{t['shares']:,}</td><td class='n {cls}'>{_inr(t['pnl'])}</td>"
                    f"<td class='n {cls}'>{t['pnl_pct']:+.1f}%</td>"
                    + (f"<td class=why>{_esc(t['exit_reason'].split(' | ')[0]) if t['exit_reason'] else '<span class=muted>still held</span>'}</td>" if reasons else "")
                    + "</tr>")
        return out

    head = ("<tr><th>Status</th><th>Bought</th><th class=n>Price</th><th>Sold</th><th class=n>Price</th>"
            "<th class=n>Shares</th><th class=n>P&amp;L</th><th class=n>%</th><th>Why it sold</th></tr>")
    paper_rows = trade_rows(p["trades"] + ([pos] if pos else []))
    if not paper_rows:
        paper_rows = (f"<tr><td colspan=9 class=muted>No fills yet. The paper account started on {_d(p['start'])}; "
                      "orders fill at the next session's open, the next time the agent runs.</td></tr>")
    log = "".join(f"<tr><td>{_d(x['date'])}</td><td>{_esc((x['stance'] or '').upper())}</td>"
                  f"<td>{_esc((x['order'] or '—').upper())}</td><td class=why>{_esc((x['reason'] or '').replace(' | ', ' · '))}</td></tr>"
                  for x in reversed(p["decisions"]))

    rows = [(c["id"], c["name"], c["metrics"]) for c in bt["configs"]] + [(b["id"], b["name"], b["metrics"]) for b in bt["benchmarks"]]
    cfg_rows = "".join(
        f"<tr{' class=hl' if i == 'A' else ''}><td><b>{_esc(i)}</b></td><td>{_esc(n.split('. ', 1)[-1])}</td>"
        f"<td class=n>{m['total_return_pct']:+.0f}%</td><td class=n>{m['cagr_pct']:.0f}%</td>"
        f"<td class=n>{m['max_drawdown_pct']:.0f}%</td><td class=n>{m['sharpe']:.2f}</td>"
        f"<td class=n>{m.get('trades') if m.get('trades') is not None else '—'}</td>"
        f"<td class=n>{_inr(cap * (1 + m['total_return_pct'] / 100))}</td></tr>"
        for i, n, m in rows)
    verdicts = ""
    if ag.get("variants"):
        verdicts = "".join(
            f"<li><b>{_esc(v['name'].split(':')[0])}</b>: {'kept' if v['keep'] else 'rejected'}. "
            f"Sharpe up on the focus stock: {'yes' if v['focus_sharpe_up'] else 'no'}; on {v['peers_sharpe_up']} of "
            f"{v['peers']} peers; peers' median worst drawdown {v['peer_median_dd_base']:.0f}% → {v['peer_median_dd_variant']:.0f}%.</li>"
            for v in ag["variants"]["verdicts"].values())
        verdicts = (f"<div class='card'><p><b>Rule variants tested</b> <span class=muted>({_esc(ag['variants']['keep_rule'])})</span></p>"
                    f"<ul>{verdicts}</ul></div>")

    html_ = f"""<h2>Trading agent: paper account</h2>
<p class="sub">{_esc(ag['policy'])} · paper trading since {_d(p['start'])} · starts with {_inr(cap)} and grows only by its own profit. Run <code>python -m dossier.run agent</code> after the close; orders fill at the next open.</p>
<div class="tiles">{tiles_html}</div>
<div class="card"><p><b>Why</b></p><ul>{why_html}</ul></div>
<div class="card scroll"><p><b>Paper trades</b></p><table>{head}{paper_rows}</table></div>
<details><summary>Decision log (last {len(p['decisions'])} sessions)</summary><div class="card scroll"><table><tr><th>Close of</th><th>Stance</th><th>Order</th><th>Reasoning</th></tr>{log}</table></div></details>

<h2>Trading agent: backtest</h2>
<p class="sub">The same rules replayed from {_d(bt['start'])} to {_d(bt['end'])}, each account starting at {_inr(cap)}, net of charges (about {ag['costs_round_trip_pct_at_5L']:.2f}% per round trip at ₹5 lakh). In-sample: the exit rule was found on data that includes these events, so this does not prove the rule works; only the paper account above can.</p>
<div class="legend"><span><i style="background:var(--series-1)"></i>A. Agent</span><span><i style="background:var(--series-2)"></i>Buy &amp; hold</span><span><i style="background:var(--series-3)"></i>Nifty 50</span></div>
<div class="card"><div class="chart" id="agentEq"></div></div>
<div class="card scroll"><table><tr><th></th><th>Config</th><th class=n>Return</th><th class=n>CAGR</th><th class=n>Worst drawdown</th><th class=n>Sharpe</th><th class=n>Trades</th><th class=n>₹10 lakh became</th></tr>{cfg_rows}</table></div>
<div class="card scroll"><p><b>Backtest trades (config A)</b></p><table>{head}{trade_rows(bt['trades'])}</table></div>
{verdicts}"""
    series = {"A": bt["equity"]["A"], "CONTROL": bt["equity"]["CONTROL"], "NIFTY": bt["equity"]["NIFTY"]}
    return html_, series


def _cr(rupees, digits=0):
    return "—" if rupees is None else f"₹{rupees / 1e7:,.{digits}f} cr"


def _scorecard_html(sc):
    q = sc.get("quarters") or []
    if not q:
        return "", []
    rows = "".join(
        f"<tr><td>{_d(r['quarter'])}</td><td>{_d(r['published'][:10]) if r['published'] else '—'}</td>"
        f"<td class=n>{_cr(r['revenue'])}</td><td class=n>{_pct(r['revenue_yoy'], 0, True)}</td>"
        f"<td class=n>{_pct(r['ebitda_margin'])}</td><td class=n>{_cr(r['pat'], 1)}</td>"
        f"<td class=n>{_pct(r['pat_margin'])}</td><td class=n>{_num(r['eps'])}</td></tr>"
        for r in reversed(q))
    series = [{"q": r["quarter"], "v": r["revenue"]} for r in q]
    ttm_by_q = [(r["published"], r["revenue_ttm"]) for r in q if r["published"] and r["revenue_ttm"]]

    def ttm_at(ts):
        known = [v for p, v in ttm_by_q if p <= ts]
        return known[-1] if known else None

    facts = sc.get("facts") or []
    book = {}
    for f in facts:
        if f["kind"] in ("order_book", "order_book_organic", "l1_position", "pipeline"):
            book.setdefault(f["ts"][:10], {})[f["kind"]] = f
    book_rows = ""
    for day in sorted(book, reverse=True):
        b = book[day]
        ob = b.get("order_book") or b.get("order_book_organic")
        ttm = ttm_at(day + " 23:59:59")
        cover = f"{ob['value'] / ttm * 12:.1f}" if ob and ttm else "—"
        cells = "".join(f"<td class=n title=\"{_esc(b[k]['quote'][:300])}\">{_cr(b[k]['value'])}</td>" if k in b else "<td class=n>—</td>"
                        for k in ("order_book", "order_book_organic", "l1_position", "pipeline"))
        book_rows += f"<tr><td>{_d(day)}</td>{cells}<td class=n>{cover}</td></tr>"

    def quoted(kind, fmt):
        items = [f for f in facts if f["kind"] == kind]
        return "".join(f"<li><b>{_d(f['ts'][:10])}</b>: {fmt(f)} <span class=muted>“{_esc(f['quote'][-220:])}”</span> "
                       f"<a href=\"{_esc(f['source'])}\">source</a></li>" for f in reversed(items)) or "<li class=muted>None found.</li>"

    rng = lambda f: f"{f['value'][0]:g}% to {f['value'][1]:g}%"
    guidance = quoted("revenue_growth_guidance", lambda f: "revenue growth " + rng(f)) + \
        quoted("margin_guidance", lambda f: "EBITDA margin " + rng(f))
    ratings = quoted("rating_action", lambda f: f"{_esc((f.get('agency') or 'Agency'))} <b>{_esc(f['value'].replace('_', ' '))}</b>")
    orders = quoted("order_value", lambda f: f"order worth <b>{_cr(f['value'])}</b>"
                    + (f" ({f['value'] / ttm_at(f['ts']) * 100:.0f}% of the last 12 months' revenue)" if ttm_at(f['ts']) else ""))
    html_ = f"""<h2>Business scorecard</h2>
<p class="sub">From NSE's structured results filings ({_esc(sc.get('basis') or '')} figures, as first published) and from rules that read the company's own presentations, press releases, call transcripts, rating letters and order filings. Hover a figure for the sentence it came from.</p>
<div class="card"><div class="chart" id="revbars"></div></div>
<div class="card scroll"><table><tr><th>Quarter ended</th><th>Published</th><th class=n>Revenue</th><th class=n>vs a year ago</th><th class=n>EBITDA margin</th><th class=n>Net profit</th><th class=n>Net margin</th><th class=n>EPS (₹)</th></tr>{rows}</table></div>
<div class="card scroll"><p><b>Order book and pipeline</b> <span class=muted>(as stated in each filing)</span></p><table><tr><th>Filed</th><th class=n>Order book</th><th class=n>Organic order book</th><th class=n>L1 (won, awaiting order)</th><th class=n>Pipeline</th><th class=n>Months of revenue covered</th></tr>{book_rows}</table>
<p class="disclaimer">Months covered = order book ÷ the last 12 months' revenue known at that date × 12. From November 2025 the company also reports large "strategic" orders separately from its organic order book. In July 2026 the deck states the pipeline as ₹104,100 Mn while the call transcript says ₹10,401 Mn; the deck figure is shown.</p></div>
<div class="card"><p><b>Guidance, in management's words</b></p><ul>{guidance}</ul></div>
<div class="card"><p><b>Credit ratings</b></p><ul>{ratings}</ul><p><b>Order wins</b></p><ul>{orders}</ul></div>"""
    return html_, series


def _events_html(ev, sym):
    prof = ev.get("results_profile") or {}
    tiles = []
    if prof.get("focus_median_abs_reaction") is not None:
        ratio = prof["focus_median_abs_reaction"] / prof["focus_ordinary_2day_move"]
        tiles = [
            ("Typical results-day move", _pct(prof["focus_median_abs_reaction"]),
             f"{ratio:.1f}x an ordinary 2-day move ({_pct(prof['focus_ordinary_2day_move'])})"),
            ("Results reactions that were up", _pct(prof["focus_share_up"], 0),
             f"{len(prof.get('focus_table', []))} results since listing"),
            ("Comparison group, typical results move", _pct(prof["pool_median_abs_reaction"]),
             f"{prof['pool_results']} results across the group"),
        ]
    tiles_html = "".join(f'<div class="tile"><div class="tl">{_esc(l)}</div><div class="tv">{v}</div>'
                         f'<div class="ts">{_esc(s)}</div></div>' for l, v, s in tiles)
    rows = "".join(
        f"<tr><td>{_d(r['meeting'])}</td><td>{_esc(r['timing'])}"
        f"{(' at ' + r['released'][11:16]) if r.get('released') else ''}</td><td>{_d(r['reaction_session'])}</td>"
        f"<td class=n>{_pct(r['reaction_raw'], 1, True)}</td><td class=n>{_pct(r['reaction_abn'], 1, True)}</td>"
        f"<td class=n>{_pct(r['next_month_raw'], 1, True)}</td></tr>"
        for r in reversed(prof.get("focus_table", [])))
    table = ("<div class='card scroll'><table><tr><th>Results date</th><th>Released</th><th>Reaction session</th>"
             "<th class=n>Reaction</th><th class=n>vs market</th><th class=n>Next month</th></tr>" + rows + "</table></div>") if rows else ""
    up = ev.get("upcoming") or []
    if up:
        upcoming = "Next scheduled: " + "; ".join(f"{_d(u['date'])}: {_esc(u['purpose'])}" for u in up) + "."
    else:
        q2 = [r["meeting"] for r in prof.get("focus_table", []) if r["meeting"][5:7] in ("10", "11")]
        upcoming = (f"NSE has no upcoming results date for {sym} yet."
                    + (" Earlier September-quarter results came out on " + ", ".join(_d(x) for x in q2) + "." if q2 else ""))
    recent = "".join(f"<li>{_d(e['date'])}: {_esc(e['description'])}</li>" for e in (ev.get("focus_recent") or [])[:12]) \
        or "<li class=muted>No tracked events in the last 120 days.</li>"
    return {"tiles": tiles_html, "table": table, "upcoming": upcoming, "recent": recent,
            "tests": ev.get("method", {}).get("tests", "—"), "cut": _pct(ev.get("method", {}).get("reaction_cut"), 0)}


def _worst(dr):
    eps = dr.get('episodes_gt_10pct') or []
    if not eps:
        return None, None
    e = min(eps, key=lambda x: x['depth'])
    return e['peak'], e['trough']


def _badge(v):
    cls = {"validated": "good", "consistent, not yet confirmed": "cons", "suggestive (not validated)": "warn",
           "no evidence": "none", "insufficient data": "thin"}[v]
    icon = {"good": "✓", "cons": "~", "warn": "!", "none": "–", "thin": "?"}[cls]
    label = {"good": "Validated", "cons": "Consistent, not yet confirmed", "warn": "Suggestive",
             "none": "No evidence", "thin": "Too few events"}[cls]
    return f'<span class="badge {cls}"><span aria-hidden="true">{icon}</span> {label}</span>'


LEGEND = ('<div class="legend"><span><i style="background:var(--good)"></i>Validated (✓)</span>'
          '<span><i style="border:2px solid var(--good);background:transparent"></i>Consistent, not yet confirmed (~)</span>'
          '<span><i style="background:var(--warning)"></i>Suggestive, failed validation (!)</span>'
          '<span><i style="background:var(--neutral)"></i>No evidence (–)</span>'
          '<span><i style="border:2px solid var(--neutral);background:transparent"></i>Too few events (?)</span></div>')

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{sym} Stock Dossier</title>
<style>
:root {{
  color-scheme: light;
  --surface-0:#f6f6f4; --surface-1:#fcfcfb; --line:#e4e3df; --grid:#ecebe7;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#7a7975;
  --series-1:#2a78d6; --series-dd:#e34948; --wash-dd:rgba(227,73,72,.10); --wash-1:rgba(42,120,214,.10);
  --series-2:#eb6834; --series-3:#1baf7a;
  --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b; --neutral:#a3a29c;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
    --surface-0:#121211; --surface-1:#1a1a19; --line:#2c2c2a; --grid:#262624;
    --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8f8e86;
    --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70; --series-dd:#e66767; --wash-dd:rgba(230,103,103,.12); --wash-1:rgba(57,135,229,.12);
    --neutral:#6f6e68;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --surface-0:#121211; --surface-1:#1a1a19; --line:#2c2c2a; --grid:#262624;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8f8e86;
  --series-1:#3987e5; --series-dd:#e66767; --wash-dd:rgba(230,103,103,.12); --wash-1:rgba(57,135,229,.12);
  --neutral:#6f6e68;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--surface-0); color:var(--text-primary);
  font:15px/1.55 "Modern Era", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
main {{ max-width:1080px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ font-size:28px; margin:0 0 4px; font-weight:650; letter-spacing:-.01em; }}
h2 {{ font-size:19px; margin:40px 0 6px; font-weight:620; }}
.sub {{ color:var(--text-secondary); margin:0 0 4px; }}
.muted {{ color:var(--text-muted); }}
.card {{ background:var(--surface-1); border:1px solid var(--line); border-radius:12px; padding:18px 20px; margin-top:12px; }}
.headline {{ border-left:4px solid var(--series-1); }}
.headline p {{ margin:.3em 0; }}
.disclaimer {{ font-size:13px; color:var(--text-secondary); margin-top:10px; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:12px; margin-top:16px; }}
.tile {{ background:var(--surface-1); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
.tl {{ font-size:13px; color:var(--text-secondary); }}
.tv {{ font-size:24px; font-weight:620; margin:2px 0; }}
.ts {{ font-size:12.5px; color:var(--text-muted); }}
.scroll {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; font-size:14px; }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--grid); vertical-align:top; }}
th {{ font-weight:600; color:var(--text-secondary); font-size:13px; white-space:nowrap; }}
td.n, th.n {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
tr.hl td {{ background:var(--wash-1); }}
.badge {{ display:inline-flex; gap:4px; align-items:center; font-size:12.5px; padding:1px 8px; border-radius:999px;
  border:1px solid var(--line); color:var(--text-primary); white-space:nowrap; }}
.badge.good span {{ color:var(--good); font-weight:700; }} .badge.warn span {{ color:var(--warning); font-weight:700; }}
.badge.none span {{ color:var(--text-muted); }} .badge.thin span {{ color:var(--text-muted); }}
.badge.good {{ border-color:var(--good); }} .badge.cons {{ border-color:var(--good); border-style:dashed; }} .badge.cons span {{ color:var(--good); font-weight:700; }} .badge.warn {{ border-color:var(--warning); }}
.chart {{ position:relative; width:100%; }}
.chart svg {{ display:block; width:100%; }}
.axis text {{ fill:var(--text-muted); font-size:11.5px; font-variant-numeric:tabular-nums; }}
.gridline {{ stroke:var(--grid); stroke-width:1; }}
.tip {{ position:absolute; pointer-events:none; background:var(--surface-1); border:1px solid var(--line);
  border-radius:8px; padding:8px 10px; font-size:13px; box-shadow:0 4px 16px rgba(0,0,0,.12); display:none;
  max-width:320px; z-index:5; }}
.tip b {{ font-weight:620; }}
.tabs {{ display:flex; gap:6px; margin:12px 0 4px; flex-wrap:wrap; }}
.tabs button {{ font:inherit; font-size:13.5px; padding:5px 12px; border-radius:999px; border:1px solid var(--line);
  background:var(--surface-1); color:var(--text-primary); cursor:pointer; }}
.tabs button[aria-pressed="true"] {{ background:var(--text-primary); color:var(--surface-1); border-color:var(--text-primary); }}
.legend {{ display:flex; gap:14px; flex-wrap:wrap; font-size:13px; color:var(--text-secondary); margin:6px 0; }}
.legend i {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:5px; vertical-align:-1px; }}
details summary {{ cursor:pointer; color:var(--text-secondary); margin-top:10px; }}
ul {{ padding-left:20px; }} li {{ margin:4px 0; }}
code {{ font-size:13px; }}
td.pos {{ color:var(--good); }} td.neg {{ color:var(--critical); }}
td.why {{ font-size:13px; color:var(--text-secondary); min-width:260px; }}
</style></head>
<body><main>
<h1>{sym} Stock Dossier</h1>
<p class="sub">Data to {as_of} · {bars} sessions since {first} · built {generated}</p>

<div class="card headline">{headline}
<p class="disclaimer">Research for paper trading only. This is not investment advice, and past behaviour does not guarantee future returns.</p></div>

<div class="tiles">{tiles}</div>

{agent}

<h2>Price since listing</h2>
<p class="sub">NSE closing price, adjusted for splits and bonuses. Log scale, so equal heights mean equal percentage moves.</p>
<div class="card"><div class="chart" id="price"></div></div>

<h2>Distance below its previous peak</h2>
<p class="sub">How far the price sat below its highest close so far. The worst fall took {worst_dd} off its value, from {worst_peak} to {worst_trough}.</p>
<div class="card"><div class="chart" id="dd"></div></div>

<h2>What has happened after a random day</h2>
<p class="sub">The baseline for every other number. Buying on any day and holding for a fixed period gave the returns below. The mean mostly reflects the stock's rise since listing; it is not a forecast.</p>
<div class="card scroll"><table>
<tr><th>Hold for</th><th class=n>Independent periods</th><th class=n>Average</th><th class=n>95% range of the average</th><th class=n>Ended up</th><th class=n>Bad case (10%)</th><th class=n>Good case (90%)</th><th class=n>Typical dip along the way</th></tr>
{fwd_rows}</table></div>

<h2>What is true right now</h2>
<p class="sub">Tracked conditions active at the latest close, with what the evidence says for each holding period.</p>
<div class="card scroll"><table>
<tr><th>Condition</th><th>Since</th><th class=n>Sessions</th><th>1 week</th><th>1 month</th><th>3 months</th></tr>
{now_rows}</table></div>

<h2>What happens when…</h2>
<p class="sub">Each dot is the average extra return after a condition first appears, compared with a random peer bought the same day. The bar shows the 95% range. Anything crossing zero is indistinguishable from nothing.</p>
<div class="tabs" role="group" aria-label="Holding period" data-chart="conds">
<button data-h="1w" aria-pressed="false">1 week</button><button data-h="1m" aria-pressed="true">1 month</button><button data-h="3m" aria-pressed="false">3 months</button></div>
{legend}
<div class="card"><div class="chart" id="conds"></div></div>
<details><summary>Show the full table</summary><div class="card scroll"><table id="condstable"></table></div></details>

{scorecard}

<h2>Around results</h2>
<p class="sub">Each result is dated by the first session the market could trade on it: a release after 3:30pm reacts the next day. The reaction runs from the close before the release to the close of that session.</p>
<div class="tiles">{ev_tiles}</div>
<p class="sub" style="margin-top:12px">{ev_upcoming}</p>
{ev_table}

<h2>What happens after events</h2>
<p class="sub">The same test as above, for company events across the comparison group: results split by first reaction ({ev_cut} either way), NSE filing categories, bulk and block deals, and promoter stake changes. The trade enters at the open after the event is public. {ev_tests} tests.</p>
<div class="tabs" role="group" aria-label="Holding period" data-chart="events">
<button data-h="1w" aria-pressed="false">1 week</button><button data-h="1m" aria-pressed="true">1 month</button><button data-h="3m" aria-pressed="false">3 months</button></div>
{legend}
<div class="card"><div class="chart" id="events"></div></div>
<details><summary>Show the full table</summary><div class="card scroll"><table id="eventstable"></table></div></details>
<div class="card"><p><b>Recent {sym} events</b></p><ul>{ev_recent}</ul>
<p class="disclaimer">Filing categories come from NSE; their content (for example a rating upgrade vs a downgrade, or the size of an order) is in the PDF and is not read yet. Bulk deals exclude clients who bought and sold the same stock that day (high-frequency and prop desks).</p></div>

<h2>How it moves with the market</h2>
<p class="sub">Beta is how much NETWEB tends to move for a 1% index move. The highlighted row is the index that explains the most of its moves ({best_fit}).</p>
<div class="card scroll"><table>
<tr><th>Index</th><th class=n>Beta</th><th class=n>On down days</th><th class=n>On up days</th><th class=n>Moves explained</th><th class=n>Sessions</th></tr>
{rel_rows}</table></div>

<h2>Comparison group</h2>
<p class="sub">How closely each stock moves with NETWEB once the whole market's move is removed (0 = unrelated, 1 = identical).</p>
<div class="card scroll"><table>
<tr><th>Stock</th><th>Role</th><th class=n>Co-movement</th><th class=n>95% range</th><th class=n>Sessions</th><th class=n>Volatility</th></tr>
{peer_rows}</table></div>

<h2>Data quality</h2>
<div class="card"><p><b>Source:</b> NSE official daily files. <b>Splits and bonuses:</b> {ca_line}</p>
<p><b>Yahoo cross-check:</b> {yahoo_line}</p><ul>{issue_rows}</ul></div>

<h2>How the evidence is judged</h2>
<div class="card"><ul>
<li>Signals use only information available at that day's close; the trade is entered at the <b>next session's open</b>.</li>
<li>An event is the first day a condition appears after at least 5 sessions without it, so one long episode counts once.</li>
<li>Returns are measured against {abn_vs}, then against a random comparison stock bought the same day, so the whole theme's rise is not mistaken for an edge. Market-wide conditions (VIX, index trend) are compared with the stock's own average instead.</li>
<li>Evidence is pooled across {pool}. Uncertainty is grouped by calendar week because these stocks move together.</li>
<li>{tests} tests are corrected for multiple testing (Benjamini-Hochberg). <b>Validated</b> means significant after that correction, significant in data before {val_start}, <i>and</i> pointing the same way in the data after it.</li>
<li>NETWEB's own estimate is pulled toward the group's unless NETWEB clearly behaves differently (random-effects shrinkage).</li>
<li><b>Consistent, not yet confirmed</b> means it passes the multiple-testing correction and points the same way in both halves, but only one half is significant on its own. This tier was added on 27 September 2026 after the first event study, so treat it as provisional.</li>
<li>The method is tested: a deliberately planted signal is found and validated, and a random one is rejected.</li>
<li>Returns are before costs; allow roughly 0.3% for a round trip.</li>
</ul></div>
</main>
<div class="tip" id="tip"></div>
<script>
const D = {data};
const tip = document.getElementById('tip');
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const fmtDate = s => {{ const [y,m,d] = s.split('-').map(Number); return d + ' ' + MONTHS[m-1] + ' ' + y; }};
const pct = (x, s) => x == null ? '—' : ((s && x > 0 ? '+' : '') + (x*100).toFixed(1) + '%');
const NS = 'http://www.w3.org/2000/svg';
const el = (t, a, p) => {{ const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; }};
function showTip(host, x, y, html) {{
  tip.innerHTML = html; tip.style.display = 'block';
  const r = host.getBoundingClientRect(), tw = tip.offsetWidth;
  let left = r.left + window.scrollX + x + 14; if (left + tw > window.scrollX + document.documentElement.clientWidth - 8) left = r.left + window.scrollX + x - tw - 14;
  tip.style.left = left + 'px'; tip.style.top = (r.top + window.scrollY + y - 10) + 'px';
}}
const hideTip = () => tip.style.display = 'none';

function lineChart(id, ys, opts) {{
  const host = document.getElementById(id); host.innerHTML = '';
  const W = host.clientWidth, H = opts.h, m = {{l:56, r:14, t:10, b:26}};
  const svg = el('svg', {{viewBox:`0 0 ${{W}} ${{H}}`, height:H, role:'img', 'aria-label':opts.label}}, host);
  const n = ys.length, xs = i => m.l + (W - m.l - m.r) * i / (n - 1);
  const tv = opts.log ? ys.map(Math.log) : ys;
  let lo = Math.min(...tv), hi = Math.max(...tv); if (opts.zeroTop) hi = 0;
  const yv = v => m.t + (H - m.t - m.b) * (1 - ((opts.log ? Math.log(v) : v) - lo) / (hi - lo || 1));
  const g = el('g', {{class:'axis'}}, svg);
  opts.ticks(lo, hi).forEach(t => {{ const y = yv(t); el('line', {{x1:m.l, x2:W-m.r, y1:y, y2:y, class:'gridline'}}, g);
    el('text', {{x:m.l-8, y:y+4, 'text-anchor':'end'}}, g).textContent = opts.fmt(t); }});
  // Year ticks at each year's first session; skip any that would crowd the previous label.
  const dates = D.series.dates; let lastYear = null, lastEnd = -1e9;
  dates.forEach((s, i) => {{ const yr = s.slice(0,4);
    if (yr === lastYear) return;
    lastYear = yr;
    const text = i === 0 ? fmtDate(s) : yr, x0 = xs(i), w = text.length * 6.5;
    const left = i === 0 ? x0 : x0 - w / 2;
    if (left < lastEnd + 12) return;
    el('text', {{x:x0, y:H-6, 'text-anchor': i === 0 ? 'start' : 'middle'}}, g).textContent = text;
    lastEnd = left + w; }});
  const path = ys.map((v, i) => (i ? 'L' : 'M') + xs(i).toFixed(1) + ' ' + yv(v).toFixed(1)).join('');
  if (opts.area) el('path', {{d: path + `L${{xs(n-1)}} ${{yv(0)}}L${{xs(0)}} ${{yv(0)}}Z`, fill:css(opts.wash), stroke:'none'}}, svg);
  el('path', {{d:path, fill:'none', stroke:css(opts.color), 'stroke-width':2, 'stroke-linejoin':'round', 'stroke-linecap':'round'}}, svg);
  const endx = xs(n-1), endy = yv(ys[n-1]);
  el('circle', {{cx:endx, cy:endy, r:4.5, fill:css(opts.color), stroke:css('--surface-1'), 'stroke-width':2}}, svg);
  const cross = el('line', {{y1:m.t, y2:H-m.b, stroke:css('--text-muted'), 'stroke-width':1, visibility:'hidden'}}, svg);
  const dot = el('circle', {{r:4.5, fill:css(opts.color), stroke:css('--surface-1'), 'stroke-width':2, visibility:'hidden'}}, svg);
  const hit = el('rect', {{x:m.l, y:0, width:W-m.l-m.r, height:H, fill:'transparent'}}, svg);
  hit.addEventListener('mousemove', e => {{
    const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(n-1, Math.round((px - m.l) / (W - m.l - m.r) * (n - 1))));
    const x = xs(i), y = yv(ys[i]);
    cross.setAttribute('x1', x); cross.setAttribute('x2', x); cross.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', x); dot.setAttribute('cy', y); dot.setAttribute('visibility', 'visible');
    showTip(host, x * r.width / W, y * r.height / H, `<b>${{fmtDate(dates[i])}}</b><br>${{opts.tipFmt(ys[i], i)}}`);
  }});
  hit.addEventListener('mouseleave', () => {{ cross.setAttribute('visibility','hidden'); dot.setAttribute('visibility','hidden'); hideTip(); }});
}}

function equityChart(id, S) {{
  const host = document.getElementById(id); if (!host || !S) return; host.innerHTML = '';
  const keys = [['A', 'Agent', '--series-1'], ['CONTROL', 'Buy & hold', '--series-2'], ['NIFTY', 'Nifty 50', '--series-3']];
  const dates = S.A.map(p => p[0]);
  const val = {{}}; keys.forEach(([k]) => {{ val[k] = new Map(S[k].map(p => [p[0], p[1]])); }});
  const W = host.clientWidth, H = 300, m = {{l:72, r:16, t:10, b:26}};
  const svg = el('svg', {{viewBox:`0 0 ${{W}} ${{H}}`, height:H, role:'img', 'aria-label':'Equity: agent vs buy and hold vs Nifty 50'}}, host);
  const all = keys.flatMap(([k]) => S[k].map(p => p[1]));
  const lo = Math.log(Math.min(...all)), hi = Math.log(Math.max(...all));
  const xs = i => m.l + (W - m.l - m.r) * i / (dates.length - 1);
  const y = v => m.t + (H - m.t - m.b) * (1 - (Math.log(v) - lo) / (hi - lo));
  const g = el('g', {{class:'axis'}}, svg);
  [5e5, 1e6, 2e6, 5e6, 1e7, 2e7].forEach(t => {{ if (t < Math.exp(lo) * 0.9 || t > Math.exp(hi) * 1.1) return;
    el('line', {{x1:m.l, x2:W-m.r, y1:y(t), y2:y(t), class:'gridline'}}, g);
    el('text', {{x:m.l-8, y:y(t)+4, 'text-anchor':'end'}}, g).textContent = '₹' + (t >= 1e7 ? (t/1e7) + ' cr' : (t/1e5) + ' L'); }});
  let lastYear = null;
  dates.forEach((d, i) => {{ const yr = d.slice(0, 4); if (yr !== lastYear) {{ lastYear = yr;
    if (i > 0) el('text', {{x:xs(i), y:H-6, 'text-anchor':'middle'}}, g).textContent = yr; }} }});
  keys.forEach(([k, label, c]) => {{
    const pts = dates.map((d, i) => [xs(i), val[k].get(d)]).filter(p => p[1] != null);
    el('path', {{d: pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + y(p[1]).toFixed(1)).join(''), fill:'none',
      stroke:css(c), 'stroke-width':2, 'stroke-linejoin':'round', 'stroke-linecap':'round'}}, svg);
    const [lx, lv] = pts[pts.length - 1];
    el('circle', {{cx:lx, cy:y(lv), r:4.5, fill:css(c), stroke:css('--surface-1'), 'stroke-width':2}}, svg);
  }});
  const cross = el('line', {{y1:m.t, y2:H-m.b, stroke:css('--text-muted'), 'stroke-width':1, visibility:'hidden'}}, svg);
  const hit = el('rect', {{x:m.l, y:0, width:W-m.l-m.r, height:H, fill:'transparent'}}, svg);
  const inr = v => '₹' + Math.round(v).toLocaleString('en-IN');
  hit.addEventListener('mousemove', e => {{
    const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(dates.length - 1, Math.round((px - m.l) / (W - m.l - m.r) * (dates.length - 1))));
    cross.setAttribute('x1', xs(i)); cross.setAttribute('x2', xs(i)); cross.setAttribute('visibility', 'visible');
    showTip(host, xs(i) * r.width / W, m.t + 20, `<b>Week of ${{fmtDate(dates[i])}}</b>` +
      keys.map(([k, label]) => `<br>${{label}}: ${{val[k].has(dates[i]) ? inr(val[k].get(dates[i])) : '—'}}`).join(''));
  }});
  hit.addEventListener('mouseleave', () => {{ cross.setAttribute('visibility', 'hidden'); hideTip(); }});
}}

function barChart(id, rows) {{
  const host = document.getElementById(id); host.innerHTML = '';
  const W = host.clientWidth, H = 220, m = {{l:64, r:10, t:12, b:28}};
  const svg = el('svg', {{viewBox:`0 0 ${{W}} ${{H}}`, height:H, role:'img', 'aria-label':'Quarterly revenue'}}, host);
  const max = Math.max(...rows.map(r => r.v)), n = rows.length;
  const step = (W - m.l - m.r) / n, bw = Math.min(24, step - 6);
  const y = v => m.t + (H - m.t - m.b) * (1 - v / max);
  const g = el('g', {{class:'axis'}}, svg);
  const tickStep = max > 5e9 ? 2e9 : max > 2e9 ? 1e9 : 5e8;
  for (let t = 0; t <= max; t += tickStep) {{ el('line', {{x1:m.l, x2:W-m.r, y1:y(t), y2:y(t), class:'gridline'}}, g);
    el('text', {{x:m.l-8, y:y(t)+4, 'text-anchor':'end'}}, g).textContent = '₹' + (t/1e7).toLocaleString('en-IN') + ' cr'; }}
  rows.forEach((r, i) => {{
    const x = m.l + i * step + (step - bw) / 2, top = y(r.v), base = y(0), rr = Math.min(4, (base - top) / 2);
    el('path', {{d:`M${{x}} ${{base}}V${{top + rr}}Q${{x}} ${{top}} ${{x + rr}} ${{top}}H${{x + bw - rr}}Q${{x + bw}} ${{top}} ${{x + bw}} ${{top + rr}}V${{base}}Z`, fill:css('--series-1')}}, svg);
    if (i % Math.ceil(n / 7) === 0 || i === n - 1) el('text', {{x:x + bw/2, y:H-8, 'text-anchor':'middle'}}, g).textContent = r.q.slice(0,7);
    const hit = el('rect', {{x:m.l + i * step, y:m.t, width:step, height:H - m.t - m.b, fill:'transparent'}}, svg);
    hit.addEventListener('mousemove', e => {{ const rr2 = svg.getBoundingClientRect();
      showTip(host, (e.clientX - rr2.left), top * rr2.height / H, `<b>Quarter ended ${{fmtDate(r.q)}}</b><br>Revenue ₹${{(r.v/1e7).toLocaleString('en-IN', {{maximumFractionDigits:0}})}} cr`); }});
    hit.addEventListener('mouseleave', hideTip);
  }});
}}

function niceLogTicks(lo, hi) {{ const a = Math.exp(lo), b = Math.exp(hi), out = [];
  [100,200,500,1000,2000,3000,5000,10000,20000].forEach(t => {{ if (t >= a*0.98 && t <= b*1.02) out.push(t); }}); return out; }}
function ddTicks(lo) {{ const out = []; for (let t = 0; t >= lo - 1e-9; t -= 0.1) out.push(+t.toFixed(1)); return out.length > 7 ? out.filter((_, i) => i % 2 === 0) : out; }}

const HSTATE = {{conds:'1m', events:'1m'}};
const VCOLOR = {{'validated':'--good', 'consistent, not yet confirmed':'--good', 'suggestive (not validated)':'--warning', 'no evidence':'--neutral', 'insufficient data':'--neutral'}};
const VLABEL = {{'validated':'✓ Validated', 'consistent, not yet confirmed':'~ Consistent, not yet confirmed', 'suggestive (not validated)':'! Suggestive, failed validation', 'no evidence':'– No evidence', 'insufficient data':'? Too few events'}};
const HOLLOW = new Set(['insufficient data', 'consistent, not yet confirmed']);
function condChart(id, all) {{
  const H = HSTATE[id];
  const host = document.getElementById(id); host.innerHTML = '';
  const rows = all.filter(r => r.h === H && r.edge != null).sort((a, b) => b.edge - a.edge);
  const W = host.clientWidth, narrow = W < 640, labelW = narrow ? 0 : Math.min(380, W * 0.44);
  const rowH = narrow ? 44 : 26, m = {{l:labelW + 8, r:16, t:24, b:10}}, Hh = m.t + rows.length * rowH + m.b;
  const svg = el('svg', {{viewBox:`0 0 ${{W}} ${{Hh}}`, height:Hh, role:'img', 'aria-label':'Average extra return after each condition or event'}}, host);
  const ext = Math.max(0.02, ...rows.map(r => Math.max(Math.abs(r.ci ? r.ci[0] : r.edge), Math.abs(r.ci ? r.ci[1] : r.edge))));
  const x = v => m.l + (W - m.l - m.r) * (v + ext) / (2 * ext);
  const g = el('g', {{class:'axis'}}, svg);
  const step = ext > 0.2 ? 0.1 : ext > 0.08 ? 0.05 : 0.02;
  for (let t = -Math.floor(ext/step)*step; t <= ext + 1e-9; t += step) {{ const xx = x(t);
    el('line', {{x1:xx, x2:xx, y1:m.t-4, y2:Hh-m.b, class:'gridline'}}, g);
    el('text', {{x:xx, y:14, 'text-anchor':'middle'}}, g).textContent = pct(+t.toFixed(3), true).replace('.0%','%'); }}
  el('line', {{x1:x(0), x2:x(0), y1:m.t-4, y2:Hh-m.b, stroke:css('--text-muted'), 'stroke-width':1}}, svg);
  rows.forEach((r, i) => {{
    const cy = m.t + i * rowH + (narrow ? 30 : rowH / 2), c = css(VCOLOR[r.verdict]);
    const lab = el('text', {{x: narrow ? m.l : labelW, y: narrow ? cy - 14 : cy + 4, 'text-anchor': narrow ? 'start' : 'end', fill:css('--text-primary'), 'font-size':13}}, svg);
    lab.textContent = r.desc;
    if (r.ci) el('line', {{x1:x(r.ci[0]), x2:x(r.ci[1]), y1:cy, y2:cy, stroke:c, 'stroke-width':2, 'stroke-linecap':'round'}}, svg);
    const hollow = HOLLOW.has(r.verdict);
    el('circle', {{cx:x(r.edge), cy, r:5, fill: hollow ? css('--surface-1') : c, stroke: hollow ? c : css('--surface-1'), 'stroke-width':2}}, svg);
    const hit = el('rect', {{x:0, y:cy - rowH/2, width:W, height:rowH, fill:'transparent'}}, svg);
    hit.addEventListener('mousemove', e => {{ const rr = svg.getBoundingClientRect();
      showTip(host, (e.clientX - rr.left), cy * rr.height / Hh,
        `<b>${{r.desc}}</b><br>${{VLABEL[r.verdict]}}<br>Extra return: <b>${{pct(r.edge, true)}}</b>` +
        (r.ci ? ` (${{pct(r.ci[0], true)}} to ${{pct(r.ci[1], true)}})` : '') +
        `<br>${{r.n}} events in ${{r.clusters}} separate weeks · p = ${{r.p == null ? '—' : r.p.toFixed(3)}}` +
        `<br>Before {val_start}: ${{pct(r.disc, true)}} · after: ${{pct(r.val, true)}}` +
        `<br>{sym} alone: ${{r.nw_n}} events · best estimate ${{pct(r.nw_est, true)}}` +
        `<br>Compared with: ${{r.baseline}}`); }});
    hit.addEventListener('mouseleave', hideTip);
  }});
  const t = document.getElementById(id + 'table');
  t.innerHTML = '<tr><th>What happened</th><th>Verdict</th><th class=n>Extra return</th><th class=n>95% range</th><th class=n>Events</th><th class=n>Weeks</th><th class=n>p</th><th class=n>Before / after split</th><th class=n>{sym} events</th><th class=n>{sym} estimate</th></tr>' +
    all.filter(r => r.h === H).map(r => `<tr><td>${{r.desc}}</td><td>${{VLABEL[r.verdict]}}</td><td class=n>${{pct(r.edge, true)}}</td>` +
    `<td class=n>${{r.ci ? pct(r.ci[0], true) + ' to ' + pct(r.ci[1], true) : '—'}}</td><td class=n>${{r.n ?? 0}}</td><td class=n>${{r.clusters ?? 0}}</td>` +
    `<td class=n>${{r.p == null ? '—' : r.p.toFixed(3)}}</td><td class=n>${{pct(r.disc, true)}} / ${{pct(r.val, true)}}</td><td class=n>${{r.nw_n ?? 0}}</td><td class=n>${{pct(r.nw_est, true)}}</td></tr>`).join('');
}}
const CHARTDATA = {{conds: () => D.conds, events: () => D.events}};
document.querySelectorAll('.tabs').forEach(group => group.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {{
  const id = group.dataset.chart; HSTATE[id] = b.dataset.h;
  group.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b)); condChart(id, CHARTDATA[id]()); }})));

function drawAll() {{
  lineChart('price', D.series.close, {{h:300, log:true, color:'--series-1', label:'Price since listing',
    ticks:niceLogTicks, fmt:v => '₹' + v.toLocaleString('en-IN'), tipFmt:v => 'Close ₹' + v.toLocaleString('en-IN', {{minimumFractionDigits:2}})}});
  lineChart('dd', D.series.dd, {{h:200, area:true, zeroTop:true, color:'--series-dd', wash:'--wash-dd', label:'Distance below previous peak',
    ticks:ddTicks, fmt:v => (v*100).toFixed(0) + '%', tipFmt:v => (v === 0 ? 'At a new high' : (v*100).toFixed(1) + '% below its peak')}});
  condChart('conds', D.conds);
  condChart('events', D.events);
  if (D.revenue.length) barChart('revbars', D.revenue);
  if (D.agent) equityChart('agentEq', D.agent);
}}
drawAll();
let rt; window.addEventListener('resize', () => {{ clearTimeout(rt); rt = setTimeout(drawAll, 120); }});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', drawAll);
</script>
</body></html>
"""
