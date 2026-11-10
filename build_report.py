"""Daily Stock Focus — builds a CSE daily market PDF.

Usage:
  python3 build_report.py --day day.json --baseline baseline.json --history history.json --out Daily_Stock_Focus-YYYY-MM-DD.pdf [--no-history-update]

day.json (gathered after the close from cse.lk):
{
  "date": "2026-11-09",
  "market": {"aspi": .., "sl20": .., "turnover_mn": .., "volume": .., "trades": ..,
             "foreign_buy_mn": .., "foreign_sell_mn": .., "mcap_bn": .., "pe": .., "pbv": ..,
             "gainers": .., "losers": .., "unchanged": ..},
  "sectors": {"Banks": {"index": .., "pe": .., "pbv": ..}, ...},     # pe/pbv optional
  "prices":  {"ABL.N": {"close": .., "prev_close": .., "volume": .., "turnover": ..}, ...},
  "rates":   {"tb91": [latest, prev], ...}                              # optional; else baseline
}
Any missing market field is shown as "–" rather than guessed.
"""
import argparse, json, math, io, os, re, subprocess, tempfile, html, datetime as dt
import matplotlib
import matplotlib.ticker
matplotlib.use("Agg")
import matplotlib.pyplot as plt

GREEN = "#6abf45"; ORANGE = "#ff8a3d"; RED = "#ff3b30"; INK = "#1d1d1f"; MUTED = "#6e6e73"

INDEX_NAME = {"Household & Personal": "Household & Personal Products"}


# ---------------------------------------------------------------- formatting
def fnum(v, d=2, sign=False):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    s = f"{abs(v):,.{d}f}"
    if v < 0: return "−" + s
    if sign and v > 0: return "+" + s
    return s

def pct(new, old):
    if new is None or old in (None, 0): return None
    return (new / old - 1) * 100

def cls(v):
    return "" if v is None else ("pos" if v > 0 else "neg" if v < 0 else "")

def shade(v):
    """Background tint for price-change cells, scaled by size of move."""
    if v is None or v == 0: return ""
    a = min(abs(v) / 10, 1) * 0.28 + 0.06
    rgb = "76,160,60" if v > 0 else "214,69,58"
    return f' style="background:rgba({rgb},{a:.2f})"'


# ---------------------------------------------------------------- company names
KEEP_UPPER = {"DFCC", "HNB", "LOLC", "LB", "CIC", "PGP", "IOC", "CWE", "RIL", "BPPL", "ACL", "SL", "HNBF", "NDB", "UB"}
def short_name(raw, limit=30):
    if not raw: return ""
    s = re.sub(r"\s+", " ", raw).strip()
    s = re.sub(r"\b(?:[A-Z] )+[A-Z]\b", lambda m: m.group(0).replace(" ", ""), s)   # "L O L C" -> "LOLC"
    s = re.sub(r"\s+(PLC|LIMITED|LTD)\.?$", "", s, flags=re.I)
    s = re.sub(r"^THE\s+", "", s, flags=re.I)
    words = []
    for w in s.split(" "):
        core = re.sub(r"[^A-Za-z]", "", w)
        if core.upper() in KEEP_UPPER or (core.isupper() and len(core) <= 4 and not re.search(r"[AEIOU]", core)):
            words.append(w.upper())
        else:
            words.append(re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), w.lower()))
    s = " ".join(words).replace(" Of ", " of ").replace(" And ", " & ").replace(" Company", " Co.").replace("'S ", "'s ")
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


# ---------------------------------------------------------------- history helpers
def close_on_or_before(days, date, ticker):
    for d in reversed(days):
        if d["date"] <= date and ticker in d.get("prices", {}):
            return d["prices"][ticker], d["date"]
    return None, None

def market_on_or_before(days, date, key):
    for d in reversed(days):
        if d["date"] <= date and d.get(key) is not None:
            return d[key], d["date"]
    return None, None


# ---------------------------------------------------------------- charts (inline SVG)
def svg(fig):
    buf = io.StringIO(); fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True); plt.close(fig)
    s = buf.getvalue(); return s[s.find("<svg"):]

def style_ax(ax):
    for sp in ("top", "right", "left"): ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#cccccc"); ax.tick_params(colors=MUTED, labelsize=7, length=0)
    ax.grid(axis="y", color="#e5e5e5", lw=0.6); ax.set_axisbelow(True)

def line_chart(points, label_last=True):
    fig, ax = plt.subplots(figsize=(3.8, 1.75), dpi=100)
    if len(points) < 2:
        ax.text(0.5, 0.5, "History builds up as daily runs accumulate", ha="center", va="center", color=MUTED, fontsize=7, transform=ax.transAxes)
        ax.set_xticks([]); ax.set_yticks([])
    else:
        xs = list(range(len(points))); ys = [p[1] for p in points]
        ax.plot(xs, ys, color=ORANGE, lw=1.4); ax.plot(xs[-1], ys[-1], "o", color=ORANGE, ms=3)
        if label_last: ax.annotate(f"{ys[-1]:,.0f}", (xs[-1], ys[-1]), xytext=(4, 0), textcoords="offset points", fontsize=7, fontweight="bold", va="center")
        ticks = sorted(set([0, len(xs) // 2, len(xs) - 1]))
        ax.set_xticks(ticks); ax.set_xticklabels([dt.date.fromisoformat(points[i][0]).strftime("%d %b") for i in ticks])
        ax.margins(x=0.08)
    style_ax(ax); return svg(fig)

def bar_chart(points, colour_fn, label_last=True):
    fig, ax = plt.subplots(figsize=(3.8, 1.75), dpi=100)
    if not points:
        ax.text(0.5, 0.5, "History builds up as daily runs accumulate", ha="center", va="center", color=MUTED, fontsize=7, transform=ax.transAxes)
        ax.set_xticks([]); ax.set_yticks([])
    else:
        off = max(0, 12 - len(points)); xs = [i + off for i in range(len(points))]; ys = [p[1] for p in points]
        cols = [colour_fn(y, i == len(ys) - 1) for i, y in enumerate(ys)]
        ax.bar(xs, ys, color=cols, width=0.75)
        if label_last: ax.annotate(f"{ys[-1]:,.0f}", (xs[-1], ys[-1]), xytext=(0, 3 if ys[-1] >= 0 else -9), textcoords="offset points", ha="center", fontsize=7, fontweight="bold")
        ticks = sorted(set([0, len(xs) // 2, len(xs) - 1]))
        ax.set_xticks([xs[i] for i in ticks]); ax.set_xticklabels([dt.date.fromisoformat(points[i][0]).strftime("%d %b") for i in ticks])
        ax.set_xlim(-0.6, max(11, xs[-1]) + 0.6); ax.axhline(0, color="#999", lw=0.6)
        lo, hi = min(ys + [0]), max(ys + [0]); pad = (hi - lo) * 0.15 or 1; ax.set_ylim(lo - (pad if lo < 0 else 0), hi + (pad if hi > 0 else 0))
    style_ax(ax); return svg(fig)


# ---------------------------------------------------------------- main build
def build(day, base, hist, names=None):
    names = dict(names or {}); names.update(day.get("names", {}))
    D = day["date"]; m = day.get("market", {})
    days = [d for d in hist["days"] if d["date"] < D]
    prev = next((d for d in reversed(days) if not d.get("approx_month_ago")), None)
    date_txt = dt.date.fromisoformat(D).strftime("%-d %B %Y")
    prev_txt = dt.date.fromisoformat(prev["date"]).strftime("%-d %b %Y") if prev else "–"

    # ---- market metrics vs previous session
    def prev_val(k):
        return prev.get(k) if prev else None
    rows = [("All Share Price Index", "aspi", 2), ("S&P SL 20 Index", "sl20", 2), ("Market PE (x)", "pe", 2),
            ("Market PBV (x)", "pbv", 2), ("Market cap LKR Bn", "mcap_bn", 2), ("Turnover LKR Mn", "turnover_mn", 2),
            ("Foreign purchases LKR Mn", "foreign_buy_mn", 2), ("Foreign sales LKR Mn", "foreign_sell_mn", 2)]
    # turnover/foreign of a weekly-aggregate day are not comparable with one session
    def cmp_prev(k):
        if k in ("turnover_mn", "foreign_buy_mn", "foreign_sell_mn") and prev and prev.get("weekly_aggregate"):
            return None
        return prev_val(k)

    nf = None
    if m.get("foreign_buy_mn") is not None and m.get("foreign_sell_mn") is not None:
        nf = m["foreign_buy_mn"] - m["foreign_sell_mn"]

    # ---- YTD
    yb = hist.get("ytd_base", {})
    aspi_ytd = pct(m.get("aspi"), yb.get("aspi_start")); sl20_ytd = pct(m.get("sl20"), yb.get("sl20_start"))
    ytd_turn = None; ytd_nf = None
    if m.get("turnover_mn") is not None and yb.get("ytd_turnover_mn_2026-11-06") is not None:
        add = sum(d.get("turnover_mn") or 0 for d in days if d["date"] > "2026-11-06" and not d.get("weekly_aggregate"))
        ytd_turn = yb["ytd_turnover_mn_2026-11-06"] + add + m["turnover_mn"]
    if nf is not None and yb.get("ytd_net_foreign_mn_2026-11-06") is not None:
        add = sum((d.get("foreign_buy_mn") or 0) - (d.get("foreign_sell_mn") or 0) for d in days if d["date"] > "2026-11-06" and not d.get("weekly_aggregate"))
        ytd_nf = yb["ytd_net_foreign_mn_2026-11-06"] + add + nf

    # ---- sectors
    sec_today = day.get("sectors", {}); sec_base = base["sector_indices_2026-11-06"]
    sec_rows = []
    for name in sorted(sec_base):
        t = sec_today.get(name, {}); idx = t.get("index")
        p = t.get("prev") if t.get("prev") is not None else (prev.get("sectors", {}).get(name) if prev else None)
        sec_rows.append(dict(name=name, index=idx, prev=p, chg=pct(idx, p),
                             pe=t.get("pe"), pbv=t.get("pbv")))
    up_secs = sum(1 for r in sec_rows if (r["chg"] or 0) > 0); dn_secs = sum(1 for r in sec_rows if (r["chg"] or 0) < 0)

    # ---- stocks
    prices = day.get("prices", {}); d7 = (dt.date.fromisoformat(D) - dt.timedelta(days=7)).isoformat()
    d30 = (dt.date.fromisoformat(D) - dt.timedelta(days=30)).isoformat()
    stocks = []; ref_dates = set(); ref_m = set()
    for s in base["stocks"]:
        t = s["ticker"]; q = prices.get(t, {})
        close = q.get("close"); traded = close is not None
        prevc = q.get("prev_close") or (prev.get("prices", {}).get(t) if prev else None)
        if close is None: close = prevc
        wk, wd = close_on_or_before(days, d7, t); mo, md = close_on_or_before(days, d30, t)
        if wd: ref_dates.add(wd)
        if md: ref_m.add(md)
        r = dict(s); r.update(price=close, traded=traded, vol=q.get("volume"),
                              dod=pct(close, prevc) if traded else None,
                              wow=pct(close, wk), mom=pct(close, mo), ytd=pct(close, hist.get("ytd_base_prices", {}).get(t)))
        r["per_fy"] = close / s["eps_fy"] if close and s["eps_fy"] and s["eps_fy"] > 0 else None
        r["per_ttm"] = close / s["eps_ttm"] if close and s["eps_ttm"] and s["eps_ttm"] > 0 else None
        r["pbv"] = close / s["bvps"] if close and s["bvps"] else None
        r["yld"] = s["dps"] / close * 100 if close and s["dps"] else None
        r["roe"] = s["eps_ttm"] / s["bvps"] * 100 if s["eps_ttm"] and s["bvps"] and s["eps_ttm"] > 0 else None
        stocks.append(r)

    covered = [r for r in stocks if r["dod"] is not None]
    gainers = sorted([r for r in covered if r["dod"] > 0], key=lambda r: -r["dod"])[:8]
    losers = sorted([r for r in covered if r["dod"] < 0], key=lambda r: r["dod"])[:8]

    # ---- charts
    session_days = [d for d in days if not d.get("approx_month_ago")]
    aspi_pts = [(d["date"], d["aspi"]) for d in session_days if d.get("aspi")][-25:] + ([(D, m["aspi"])] if m.get("aspi") else [])
    sl_pts = [(d["date"], d["sl20"]) for d in session_days if d.get("sl20")][-25:] + ([(D, m["sl20"])] if m.get("sl20") else [])
    daily = [d for d in session_days if not d.get("weekly_aggregate")]
    turn_pts = [(d["date"], d["turnover_mn"]) for d in daily if d.get("turnover_mn") is not None][-11:] + ([(D, m["turnover_mn"])] if m.get("turnover_mn") is not None else [])
    nf_pts = [(d["date"], d["foreign_buy_mn"] - d["foreign_sell_mn"]) for d in daily if d.get("foreign_buy_mn") is not None and d.get("foreign_sell_mn") is not None][-11:] + ([(D, nf)] if nf is not None else [])
    c_aspi = line_chart(aspi_pts); c_sl = line_chart(sl_pts)
    c_turn = bar_chart(turn_pts, lambda y, last: ORANGE if last else "#ffc7a3")
    c_nf = bar_chart(nf_pts, lambda y, last: (GREEN if y >= 0 else RED) if last else ("#a8dc8f" if y >= 0 else "#ff9a95"))

    sec_sorted = sorted([r for r in sec_rows if r["chg"] is not None], key=lambda r: -r["chg"])
    max_abs = max([abs(r["chg"]) for r in sec_sorted] or [1]) or 1
    any_neg = any(r["chg"] < 0 for r in sec_sorted)
    def sbar(r):
        w = abs(r["chg"]) / max_abs * (55 if any_neg else 70); lab = f'{fnum(r["chg"],2,True)}%'
        if not any_neg:
            return f'<span class="st"><span class="bar pos" style="width:{w:.1f}%"></span><span class="bv">{lab}</span></span>'
        if r["chg"] >= 0:
            return f'<span class="st2"><span class="lh"></span><span class="rh"><span class="bar pos" style="width:{w:.1f}%"></span><span class="bv">{lab}</span></span></span>'
        return f'<span class="st2"><span class="lh"><span class="bv">{lab}</span><span class="bar neg" style="width:{w:.1f}%"></span></span><span class="rh"></span></span>'
    sec_bars = "".join(f'<div class="sb"><span class="sn">{html.escape(r["name"])}</span>{sbar(r)}</div>' for r in sec_sorted) or '<p class="muted">Sector indices not captured today.</p>'

    # ---- KPI tiles
    def tile(label, val, sub, subcls="", big=False):
        return f'<div class="kpi{" big" if big else ""}"><div class="kl">{label}</div><div class="kv">{val}</div><div class="ks {subcls}">{sub}</div></div>'
    aspi_d = pct(m.get("aspi"), prev_val("aspi")); sl_d = pct(m.get("sl20"), prev_val("sl20"))
    t_d = pct(m.get("turnover_mn"), cmp_prev("turnover_mn")); mc_d = pct(m.get("mcap_bn"), prev_val("mcap_bn"))
    tiles = (
        f'<div class="kpi big"><div class="kl">ALL SHARE PRICE INDEX</div><div class="kv">{fnum(m.get("aspi"))}</div>'
        f'<div class="ks"><span class="pill {cls(aspi_d)}">{fnum(aspi_d,2,True)}% d/d</span> YTD {fnum(aspi_ytd,2,True)}%</div></div>'
        + tile("S&amp;P SL20", fnum(m.get("sl20")), f"{fnum(sl_d,2,True)}% d/d" if sl_d is not None else "", cls(sl_d))
        + tile("MARKET PE", f'{fnum(m.get("pe"))}x' if m.get("pe") else "–", f'prev. {fnum(prev_val("pe"))}x' if prev_val("pe") else "")
        + tile("MARKET PBV", f'{fnum(m.get("pbv"))}x' if m.get("pbv") else "–", f'prev. {fnum(prev_val("pbv"))}x' if prev_val("pbv") else "")
        + tile("MARKET CAP LKR BN", fnum(m.get("mcap_bn")), f"{fnum(mc_d,2,True)}% d/d" if mc_d is not None else "", cls(mc_d))
        + tile("TURNOVER LKR MN", fnum(m.get("turnover_mn")), f"{fnum(t_d,2,True)}% d/d" if t_d is not None else "first daily print", cls(t_d))
        + tile("NET FOREIGN LKR MN", fnum(nf), f'B {fnum(m.get("foreign_buy_mn"))} / S {fnum(m.get("foreign_sell_mn"))}' if nf is not None else "not yet published", cls(nf))
    )
    breadth = ""
    if m.get("gainers") is not None:
        breadth = f'{m["gainers"]} up · {m.get("losers","–")} down · {m.get("unchanged","–")} unchanged'
    sub = f'Colombo Stock Exchange · trading day {date_txt} · ASPI {fnum(aspi_d,2,True)}%'
    if sec_sorted: sub += f'; {up_secs} of {len(sec_sorted)} sectors higher'
    if day.get("test"): sub = (day.get('test_label') or 'LAYOUT TEST — SYNTHETIC NUMBERS, NOT MARKET DATA') + ' · ' + sub

    # ---- page 2: market dashboard
    def chip(v, suffix="%"):
        if v is None: return '<span class="chip">–</span>'
        return f'<span class="chip {cls(v)}">{fnum(v,2,True)}{suffix}</span>'
    mrows = "".join(
        f'<tr><td>{en}</td><td class="r b">{fnum(m.get(k),d)}</td><td class="r muted">{fnum(cmp_prev(k),d)}</td>'
        f'<td class="r">{chip(pct(m.get(k),cmp_prev(k)))}</td></tr>' for en, k, d in rows)
    if m.get("volume") is not None or m.get("trades") is not None:
        mrows += f'<tr><td>Share volume / Trades</td><td class="r b" colspan="3">{fnum(m.get("volume"),0)} / {fnum(m.get("trades"),0)}</td></tr>'
    rates = day.get("rates") or {k: v for k, v in base["rates_2026-11-06"].items() if k != "source"}
    rates_src = day.get("rates_source") or base["rates_2026-11-06"]["source"]

    # breadth donut
    g_, l_, u_ = m.get("gainers"), m.get("losers"), m.get("unchanged")
    if g_ is not None:
        fig, ax = plt.subplots(figsize=(1.9, 1.9), dpi=100)
        vals = [g_, l_ or 0, u_ or 0]
        ax.pie(vals, colors=[GREEN, RED, "#c7c7cc"], startangle=90, counterclock=False,
               wedgeprops=dict(width=0.32, edgecolor="white", linewidth=1.5))
        ax.text(0, 0.08, f"{g_ / max(1, sum(vals)) * 100:.0f}%", ha="center", va="center", fontsize=15, fontweight="bold", color=INK)
        ax.text(0, -0.22, "advancing", ha="center", va="center", fontsize=7, color=MUTED)
        ax.set_aspect("equal"); c_breadth = svg(fig)
    else:
        c_breadth = '<p class="muted">Breadth not captured.</p>'

    # foreign buy vs sell
    fb, fs = m.get("foreign_buy_mn"), m.get("foreign_sell_mn")
    if fb is not None and fs is not None:
        fig, ax = plt.subplots(figsize=(3.0, 1.05), dpi=100)
        ax.barh([1, 0], [fb, fs], color=[GREEN, RED], height=0.55)
        for y, v in ((1, fb), (0, fs)):
            ax.text(v, y, f"  {v:,.1f}", va="center", fontsize=7.5, fontweight="bold", color=INK)
        ax.set_yticks([1, 0]); ax.set_yticklabels(["Bought", "Sold"]); ax.set_xlim(0, max(fb, fs) * 1.3 or 1)
        style_ax(ax); ax.grid(False); ax.set_xticks([]); c_foreign = svg(fig)
    else:
        c_foreign = '<p class="muted small">Foreign buying and selling not yet published by the CSE.</p>'

    # top movers diverging bars
    mv = sorted(gainers[:8] + losers[:8], key=lambda r: r["dod"])
    if mv:
        fig, ax = plt.subplots(figsize=(3.8, 4.9), dpi=100)
        ys = range(len(mv)); vals = [r["dod"] for r in mv]
        ax.barh(list(ys), vals, color=[GREEN if v > 0 else RED for v in vals], height=0.68)
        ax.set_yticks(list(ys)); ax.set_yticklabels([f'{r["ticker"]}  {short_name(names.get(r["ticker"], ""), 16)}'.strip() for r in mv], fontsize=6.4)
        for y, v in zip(ys, vals):
            ax.text(v, y, f" {v:+.1f}% " , va="center", ha="left" if v > 0 else "right", fontsize=6.5, color=INK)
        lim = max(abs(v) for v in vals) * 1.35; ax.set_xlim(-lim, lim); ax.axvline(0, color="#999", lw=0.6)
        style_ax(ax); ax.grid(axis="x", color="#eee", lw=0.6); ax.grid(axis="y", visible=False)
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:+.0f}%"))
        c_movers = svg(fig)
    else:
        c_movers = '<p class="muted">No covered stock moved today.</p>'

    # sector heatmap tiles
    def heat(v):
        if v is None: return "background:#f2f2f4"
        a = min(abs(v) / 3, 1) * 0.75 + 0.12
        rgb = "106,191,69" if v >= 0 else "255,59,48"
        return f"background:rgba({rgb},{a:.2f})"
    tiles2 = "".join(
        f'<div class="ht" style="{heat(r["chg"])}"><div class="hn">{html.escape(r["name"])}</div>'
        f'<div class="hv">{(fnum(r["chg"],2,True)+"%") if r["chg"] is not None else "–"}</div><div class="hi">{fnum(r["index"])}</div></div>'
        for r in sorted(sec_rows, key=lambda r: -(r["chg"] if r["chg"] is not None else -999)))

    # index performance: day / week / month / YTD, grouped bars
    def idx_change(key, cutoff):
        v, _ = market_on_or_before(session_days, cutoff, key)
        return pct(m.get(key), v)
    d30m = (dt.date.fromisoformat(D) - dt.timedelta(days=30)).isoformat()
    perf = {"Day": (aspi_d, sl_d), "Week": (idx_change("aspi", d7), idx_change("sl20", d7)),
            "Month": (idx_change("aspi", d30m), idx_change("sl20", d30m)), "YTD": (aspi_ytd, sl20_ytd)}
    fig, ax = plt.subplots(figsize=(3.8, 2.2), dpi=100)
    xs = list(range(len(perf))); w = 0.36
    for i, (lab, col) in enumerate((("ASPI", ORANGE), ("S&P SL20", "#2f7fbf"))):
        vals = [perf[k][i] if perf[k][i] is not None else 0 for k in perf]
        bars = ax.bar([x + (i - 0.5) * w for x in xs], vals, width=w, color=col, label=lab)
        for x, (k, v) in zip(xs, perf.items()):
            v = v[i]
            if v is None:
                ax.text(x + (i - 0.5) * w, 0, "n/a", ha="center", va="bottom", fontsize=5.5, color=MUTED); continue
            ax.text(x + (i - 0.5) * w, v, f"{v:+.1f}", ha="center", va="bottom" if v >= 0 else "top", fontsize=6.3, color=INK)
    ax.set_xticks(xs); ax.set_xticklabels(list(perf)); ax.axhline(0, color="#999", lw=0.6)
    ax.legend(fontsize=6.5, frameon=False, loc="lower left", ncol=2)
    lo, hi = ax.get_ylim(); ax.set_ylim(lo - (hi - lo) * 0.12, hi + (hi - lo) * 0.12)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{y:.0f}%"))
    style_ax(ax); c_perf = svg(fig)

    # T-bill yield curve
    tb = [k for k in ("tb91", "tb182", "tb364") if k in rates]
    fig, ax = plt.subplots(figsize=(2.4, 1.7), dpi=100)
    lab = {"tb91": "91d", "tb182": "182d", "tb364": "364d"}
    ax.plot([lab[k] for k in tb], [rates[k][1] for k in tb], "--o", color="#b0b0b5", ms=3, lw=1, label="Previous")
    ax.plot([lab[k] for k in tb], [rates[k][0] for k in tb], "-o", color="#7a4fbf", ms=4, lw=1.8, label="Latest")
    for k in tb: ax.annotate(f"{rates[k][0]:.2f}", (lab[k], rates[k][0]), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=6.5, fontweight="bold")
    ax.legend(fontsize=6, frameon=False, loc="lower right"); ys_ = [rates[k][j] for k in tb for j in (0, 1)]
    ax.set_ylim(min(ys_) - 0.25, max(ys_) + 0.45); style_ax(ax); c_curve = svg(fig)
    def rate_chip(label, k):
        if k not in rates: return ""
        a, b = rates[k]; d_ = a - b
        return f'<div class="rc"><span>{label}</span><b>{a:.2f}%</b><span class="chip {cls(d_)}">{d_:+.2f}</span></div>'
    rate_chips = rate_chip("AWPR (weekly)", "awpr") + rate_chip("AWFDR (monthly)", "awfdr")

    # ---- sector stock pages
    order = base["sectors"]
    sector_blocks = []
    for sec in order:
        rs = [r for r in stocks if r["sector"] == sec]
        if not rs: continue
        g = rs[0]["group"]; iname = INDEX_NAME.get(sec, sec)
        sr = next((x for x in sec_rows if x["name"] == iname), None)
        fy_lbl = "FY25/26" if all(r["fy"] == "Mar" for r in rs) else "CY25" if all(r["fy"] == "Dec" for r in rs) else "CY25 &amp; FY25/26"
        max_per = max([r["per_ttm"] or 0 for r in rs] or [1]) or 1; max_roe = max([r["roe"] or 0 for r in rs] or [1]) or 1
        body = ""
        for r in rs:
            mark = "" if r["traded"] else '<sup class="nt">†</sup>'
            body += (f'<tr class="{"nt-row" if not r["traded"] else ""}"><td class="tk">{r["ticker"]}{mark}<span class="cn">{html.escape(short_name(names.get(r["ticker"], "")))}</span></td><td>{r["fy"]}</td><td class="r b">{fnum(r["price"])}</td>'
                     f'<td class="r"{shade(r["dod"])}>{fnum(r["dod"],2,True)}</td><td class="r"{shade(r["wow"])}>{fnum(r["wow"],2,True)}</td>'
                     f'<td class="r"{shade(r["mom"])}>{fnum(r["mom"],2,True)}</td><td class="r"{shade(r["ytd"])}>{fnum(r["ytd"],2,True)}</td>'
                     f'<td class="r">{fnum(r["vol"],0)}</td><td class="r gb">{fnum(r["shares"],1)}</td><td class="r">{fnum(r["ne_fy"],0)}</td><td class="r">{fnum(r["ne_ttm"],0)}</td>'
                     f'<td class="r">{fnum(r["eps_fy"])}</td><td class="r">{fnum(r["eps_ttm"])}</td>'
                     f'<td class="r gb">{fnum(r["per_fy"]) if r["per_fy"] else "n.m."}</td>'
                     f'<td class="r barcell"><span class="ib" style="width:{(r["per_ttm"] or 0)/max_per*100:.0f}%"></span>{fnum(r["per_ttm"]) if r["per_ttm"] else "n.m."}</td>'
                     f'<td class="r">{fnum(r["pbv"])}</td><td class="r">{fnum(r["bvps"])}</td><td class="r gb">{fnum(r["dps"])}</td><td class="r">{fnum(r["yld"])}</td>'
                     f'<td class="r barcell"><span class="ib" style="width:{(r["roe"] or 0)/max_roe*100:.0f}%"></span>{fnum(r["roe"]) if r["roe"] else "n.m."}</td></tr>')
        notes = " · ".join(base["notes"].get(sec, ["TTM : Trailing Twelve Months"]))
        sector_blocks.append(f'''
<section class="sec">
 <div class="sechead">
  <div><div class="grp">{g}</div><div class="sname">{html.escape(sec)}</div></div>
  <div class="secstats">
   <div><b>{fnum(sr["index"]) if sr else "–"}</b><span>SECTOR INDEX</span></div>
   <div><b class="{cls(sr["chg"]) if sr else ""}">{(fnum(sr["chg"],2,True)+"%") if sr and sr["chg"] is not None else "–"}</b><span>DOD CHANGE</span></div>
   <div><b>{(fnum(sr["pe"])+"x") if sr and sr["pe"] else "–"}</b><span>CSE SECTOR PE</span></div>
   <div><b>{(fnum(sr["pbv"])+"x") if sr and sr["pbv"] else "–"}</b><span>CSE SECTOR PBV</span></div>
  </div>
 </div>
 <table class="stk">
  <thead><tr class="grp-row"><th colspan="2"></th><th colspan="6">Price &amp; performance</th><th colspan="5">Earnings</th><th colspan="4">Valuation</th><th colspan="3">Dividend &amp; return</th></tr><tr>
   <th>Stock</th><th>FY</th><th>Price LKR</th>
   <th>DoD %</th><th>WoW %</th><th>MoM %</th><th>YTD %</th>
   <th>Volume</th><th>Shares Mn</th>
   <th>Net earn. {fy_lbl}</th><th>Net earn. TTM</th>
   <th>EPS {fy_lbl}</th><th>EPS TTM</th>
   <th>PER {fy_lbl}</th><th>PER TTM</th>
   <th>PBV x</th><th>BVPS LKR</th><th>DPS last FY</th>
   <th>Div. yield %</th><th>ROE %</th>
  </tr></thead><tbody>{body}</tbody></table>
 <div class="note">{html.escape(notes)}</div>
</section>''')

    untraded = [r["ticker"] for r in stocks if not r["traded"]]
    wk_ref = ", ".join(sorted(dt.date.fromisoformat(x).strftime("%-d %b") for x in ref_dates)) or "–"
    mo_ref = ", ".join(sorted(dt.date.fromisoformat(x).strftime("%-d %b") for x in ref_m)) or "–"

    css = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "report.css")).read()
    footer_txt = f"Daily Stock Focus · {date_txt} · For information only - not investment advice"
    doc = f'''<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body>
<div class="page p1">
 <header class="hero"><div><h1>Daily Stock Focus</h1><p>{sub}</p></div><div class="badge">CSE<br><span>DAILY</span></div></header>
 <div class="kpis">{tiles}</div>
 <div class="grid">
  <div class="card"><h3>ASPI · recent sessions</h3><p class="cs">Daily close, points</p>{c_aspi}</div>
  <div class="card"><h3>S&amp;P SL20 · recent sessions</h3><p class="cs">Daily close, points</p>{c_sl}</div>
  <div class="card tall"><h3>Sector moves today · CSE GICS groups</h3><p class="cs">Day-on-day change in sector index</p>{sec_bars}</div>
  <div class="card"><h3>Equity turnover · last 12 sessions</h3><p class="cs">LKR Mn per day; today highlighted</p>{c_turn}</div>
  <div class="card"><h3>Net foreign flow · last 12 sessions</h3><p class="cs">LKR Mn; purchases minus sales (green = net buying)</p>{c_nf}</div>
 </div>
</div>

<div class="page p2">
 <div class="dash">
  <div class="card"><h3>Market performance</h3><p class="cs">Today vs previous session ({prev_txt})</p>
   <table class="mt"><thead><tr><th>Metric</th><th class="r">Today</th><th class="r">Prev.</th><th class="r">Change</th></tr></thead><tbody>{mrows}</tbody></table></div>
  <div class="card"><h3>Market breadth &amp; foreign flow</h3><p class="cs">{(str(g_) + " up · " + str(l_) + " down · " + str(u_) + " unchanged") if g_ is not None else ""}</p>
   <div class="bf"><div class="donut">{c_breadth}<div class="lg"><i class="sw g"></i>Up <i class="sw r"></i>Down <i class="sw n"></i>Flat</div></div>
   <div class="ff"><div class="cs b">Foreign trading, LKR Mn</div>{c_foreign}<div class="nfv">Net: <b class="{cls(nf)}">{fnum(nf)}</b></div></div></div></div>
  <div class="card r2"><h3>Top movers today</h3><p class="cs">Biggest day-on-day moves among covered stocks</p>{c_movers}</div>
  <div class="card"><h3>Index performance</h3><p class="cs">% change over each period</p>{c_perf}</div>
  <div class="card"><h3>Rates</h3><p class="cs">T-bill yields, latest weekly auction</p><div class="rates">{c_curve}<div class="rcs">{rate_chips}</div></div>
   <div class="ytd"><div><span>YTD turnover</span><b>LKR {fnum(ytd_turn,0)} Mn</b></div><div><span>YTD net foreign</span><b class="{cls(ytd_nf)}">LKR {fnum(ytd_nf,0)} Mn</b></div></div></div>
  <div class="card wide"><h3>Sector heatmap</h3><p class="cs">CSE GICS industry groups, ranked by today's change; tile shows change and index level</p><div class="heat">{tiles2}</div></div>
 </div>
 <p class="note">*{html.escape(rates_src)}. Rates update weekly or monthly, not daily.</p>
</div>

<div class="page">
 <p class="legend">Price-change cells shaded by size of rise / fall · Bar in PER TTM and ROE cells = value relative to the highest in the sector · n.m. = not meaningful · – = nil · † = not traded today (last close shown) · Sector PE/PBV are not published daily by the CSE.</p>
 {"".join(sector_blocks)}
 <section class="sec closing">
  <div class="hero small"><div><h1>Sources, method &amp; disclaimer</h1><p>Source: Colombo Stock Exchange (cse.lk)</p></div></div>
  <div class="info">
   <div class="ib2"><h4>Market data</h4><p>Prices, indices, turnover and foreign flows from the Colombo Stock Exchange (cse.lk), captured after the close on {date_txt}.</p></div>
   <div class="ib2"><h4>Company fundamentals</h4><p>{html.escape(base["source"])}. These change only when companies report, so P/E, P/B and dividend yield are recalculated daily from the closing price.</p></div>
   <div class="ib2"><h4>Interest rates</h4><p>{html.escape(rates_src)}. T-bill, AWPR and AWFDR figures update weekly or monthly, not daily.</p></div>
   <div class="ib2"><h4>Reference closes</h4><p>DoD vs previous session ({prev_txt}) · WoW vs {wk_ref} · MoM vs {mo_ref} · YTD vs implied 2025 year-end close.</p></div>
   <div class="ib2 wide2"><h4>Not traded today</h4><p>{(", ".join(untraded) + ". Last close shown, marked †.") if untraded else "Every covered stock traded today."}</p></div>
  </div>
  <p class="disc">Disclaimer: This report is compiled automatically for personal use from publicly available data. It has not been independently verified and may contain errors. It is not an offer or solicitation to buy or sell any security, and is not investment advice.</p>
 </section>
</div>
</body></html>'''
    return doc, footer_txt


def render_pdf(doc, footer_txt, out):
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "r.html"); open(p, "w").write(doc)
    footer = (f'<div style="font-family:Inter,sans-serif;font-size:7px;color:#444;width:100%;padding:0 10mm;display:flex;justify-content:space-between">'
              f'<span>{html.escape(footer_txt)}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path="/usr/bin/google-chrome" if os.path.exists("/usr/bin/google-chrome") else None, args=["--no-sandbox"])
        pg = br.new_page(); pg.goto("file://" + p); pg.wait_for_timeout(300)
        pg.pdf(path=out, format="A4", landscape=True, print_background=True, display_header_footer=True,
               header_template="<span></span>", footer_template=footer,
               margin={"top": "10mm", "bottom": "12mm", "left": "8mm", "right": "8mm"})
        br.close()


def update_history(hist, day):
    m = day.get("market", {})
    entry = {"date": day["date"], **{k: m.get(k) for k in ("aspi", "sl20", "pe", "pbv", "mcap_bn", "turnover_mn", "foreign_buy_mn", "foreign_sell_mn")},
             "sectors": {k: v.get("index") for k, v in day.get("sectors", {}).items() if v.get("index") is not None},
             "prices": {t: q["close"] for t, q in day.get("prices", {}).items() if q.get("close") is not None}}
    prior = [d for d in hist["days"] if d["date"] < day["date"] and not d.get("approx_month_ago")]
    if prior and not prior[-1].get("prices"):
        prior[-1]["prices"] = {t: q["prev_close"] for t, q in day.get("prices", {}).items() if q.get("prev_close")}
    hist["days"] = [d for d in hist["days"] if d["date"] != day["date"]] + [entry]
    hist["days"].sort(key=lambda d: d["date"])
    # keep ~6 months of sessions to stay small
    if len(hist["days"]) > 140: hist["days"] = hist["days"][-140:]
    return hist


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True); ap.add_argument("--baseline", required=True); ap.add_argument("--history", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--no-history-update", action="store_true")
    a = ap.parse_args()
    day = json.load(open(a.day)); base = json.load(open(a.baseline)); hist = json.load(open(a.history))
    npath = os.path.join(os.path.dirname(os.path.abspath(a.baseline)), "names.json")
    names = json.load(open(npath)) if os.path.exists(npath) else {}
    doc, foot = build(day, base, hist, names)
    from name_guard import check_text
    check_text(doc, "the report")
    render_pdf(doc, foot, a.out)
    if not a.no_history_update:
        json.dump(update_history(hist, day), open(a.history, "w"), indent=1)
        if day.get("names"):
            names.update(day["names"]); json.dump(dict(sorted(names.items())), open(npath, "w"), indent=1, ensure_ascii=False)
    print("wrote", a.out)
