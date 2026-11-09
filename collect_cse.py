"""Collect today's CSE market data from cse.lk's own data feeds and write day.json for build_report.py.

Exit codes: 0 = day.json written, 10 = no trading today (holiday / Poya), 1 = error.
"""
import json, sys, datetime as dt, urllib.request

BASE = "https://www.cse.lk/api/"
HEADERS = {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Mozilla/5.0 (daily-report)",
           "Origin": "https://www.cse.lk", "Referer": "https://www.cse.lk/"}
COLOMBO = dt.timezone(dt.timedelta(hours=5, minutes=30))
NAME = {"Real Estate Management&Development": "Real Estate"}


def post(endpoint):
    req = urllib.request.Request(BASE + endpoint, data=b"", headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def colombo_date(ms):
    return dt.datetime.fromtimestamp(ms / 1000, COLOMBO).date().isoformat()


def main(baseline_path, out_path):
    want = {s["ticker"] for s in json.load(open(baseline_path))["stocks"]}
    today = dt.datetime.now(COLOMBO).date().isoformat()
    status = post("marketStatus"); daily = post("dailyMarketSummery"); sectors = post("allSectors")
    trades = post("tradeSummary"); aspi = post("aspiData"); snp = post("snpData")

    ts = trades.get("reqTradeSummery") or []
    traded = [x for x in ts if x.get("lastTradedTime") and colombo_date(x["lastTradedTime"]) == today]
    if not traded:
        print(f"No trading on {today} (market status: {status.get('status')}). Nothing to build.")
        return 10

    rows = [r for grp in daily for r in (grp if isinstance(grp, list) else [grp])]
    d = next((r for r in rows if colombo_date(r["tradeDate"]) == today), None)

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
        "aspi": aspi["value"], "sl20": snp["value"],
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
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "baseline.json", sys.argv[2] if len(sys.argv) > 2 else "day.json"))
