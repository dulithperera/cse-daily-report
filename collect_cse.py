"""Collect today's CSE market data from cse.lk's own data feeds and write day.json for build_report.py.

Exit codes: 0 = day.json written, 10 = no trading today (holiday / Poya), 1 = error.
"""
import json, sys, datetime as dt, urllib.request

BASE = "https://www.cse.lk/api/"
HEADERS = {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Mozilla/5.0 (daily-report)",
           "Origin": "https://www.cse.lk", "Referer": "https://www.cse.lk/"}
COLOMBO = dt.timezone(dt.timedelta(hours=5, minutes=30))
NAME = {"Real Estate Management&Development": "Real Estate"}


def post(endpoint, tries=3):
    """Returns parsed JSON, or None if the CSE sends an empty/invalid body (it does between sessions)."""
    import time
    for i in range(tries):
        try:
            req = urllib.request.Request(BASE + endpoint, data=b"", headers=HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8").strip()
            if body:
                return json.loads(body)
        except (ValueError, OSError):
            pass
        time.sleep(3 * (i + 1))
    return None


def colombo_date(ms):
    return dt.datetime.fromtimestamp(ms / 1000, COLOMBO).date().isoformat()


def main(baseline_path, out_path, history_path="history.json"):
    want = {s["ticker"] for s in json.load(open(baseline_path))["stocks"]}
    today = dt.datetime.now(COLOMBO).date().isoformat()
    status = post("marketStatus") or {}; daily = post("dailyMarketSummery") or []; sectors = post("allSectors") or []
    trades = post("tradeSummary") or {}; aspi = post("aspiData") or {}; snp = post("snpData") or {}

    ts = trades.get("reqTradeSummery") or []
    stamped = [x for x in ts if x.get("lastTradedTime")]
    if not stamped:
        print("CSE returned no trades at all. Nothing to build."); return 10
    # The session to report is the latest day that actually traded, not the clock date,
    # so a run that GitHub starts late (even the next morning) still reports the right day.
    session = max(colombo_date(x["lastTradedTime"]) for x in stamped)
    market_status = status.get("status") or ""
    if session == today and "closed" not in market_status.lower():
        print(f"Market is still trading ({market_status}); not building an intraday report."); return 10
    try:
        done = {d["date"] for d in json.load(open(history_path))["days"]}
    except (OSError, ValueError, KeyError):
        done = set()
    if session in done:
        print(f"Latest session {session} is already reported (today {today}: {market_status}). Nothing to build."); return 10
    today = session
    traded = [x for x in stamped if colombo_date(x["lastTradedTime"]) == session]

    rows = [r for grp in daily for r in (grp if isinstance(grp, list) else [grp])]
    d = next((r for r in rows if colombo_date(r["tradeDate"]) == today), None)

    # Index closes: prefer the CSE's official daily summary, then the sector feed, then the live index feed.
    idx = {s["name"]: s.get("indexValue") for s in sectors}
    aspi_v = (d or {}).get("asi") or idx.get("ALL SHARE PRICE INDEX") or aspi.get("value")
    sl20_v = (d or {}).get("spp") or idx.get("S&P SL20") or snp.get("value")
    sec = {}
    for s in sectors:
        if s["name"] in ("S&P SL20", "ALL SHARE PRICE INDEX"):
            continue
        sec[NAME.get(s["name"], s["name"])] = {"index": s["indexValue"], "prev": s["sectorPreviousClose"]}

    prices = {}
    for x in traded:
        sym = x["symbol"]
        if not (sym.endswith(".N0000") or sym.endswith(".X0000")):
            continue
        t = sym[:-4]
        if t not in want:
            continue
        close = x["closingPrice"] if x.get("closingPrice") and x["closingPrice"] > 0 else x["price"]
        prices[t] = {"close": close, "prev_close": x["previousClose"], "volume": x.get("sharevolume")}
    names = {x["symbol"][:-4]: x["name"] for x in ts if x.get("name") and x["symbol"][:-4] in want}

    market = {
        "aspi": aspi_v, "sl20": sl20_v,
        "gainers": sum(1 for x in traded if x["change"] > 0),
        "losers": sum(1 for x in traded if x["change"] < 0),
        "unchanged": sum(1 for x in traded if x["change"] == 0),
        "turnover_mn": (d["equityTurnover"] if d else sum(x.get("turnover") or 0 for x in traded)) / 1e6,
    }
    if d:
        market.update(volume=d["volumeOfTurnOverNumber"], trades=d["tradesNo"], mcap_bn=d["marketCap"] / 1e9,
                      pe=d["per"], pbv=d["pbv"], foreign_buy_mn=d["equityForeignPurchase"] / 1e6,
                      foreign_sell_mn=d["equityForeignSales"] / 1e6)

    day = {"date": today, "marketStatus": status.get("status"), "dailySummaryReady": bool(d),
           "market": market, "sectors": sec, "prices": prices, "names": names}
    json.dump(day, open(out_path, "w"), indent=1)
    print(f"{today}: ASPI {market['aspi']}, {len(prices)}/{len(want)} covered stocks traded, "
          f"daily summary {'ready' if d else 'not yet published'}")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(main(a[0] if a else "baseline.json", a[1] if len(a) > 1 else "day.json", a[2] if len(a) > 2 else "history.json"))
