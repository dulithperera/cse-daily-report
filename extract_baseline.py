"""Extract stock fundamentals + sector structure from a weekly stock-review PDF laid out as sector tables."""
import re, json, subprocess, sys
pdf = sys.argv[1]; out = sys.argv[2]
txt = subprocess.run(["pdftotext","-layout","-f","2","-l","10",pdf,"-"],capture_output=True,text=True).stdout
SECTORS = ["Banks","Diversified Financials","Insurance","Real Estate","Consumer Durables & Apparel","Retailing",
 "Consumer Services","Automobiles & Components","Food, Beverage & Tobacco","Food & Staples Retailing",
 "Household & Personal","Energy","Health Care Equipment & Services","Capital Goods","Transportation",
 "Materials","Telecommunication Services","Utilities"]
GROUP = {"Banks":"FINANCIALS","Diversified Financials":"FINANCIALS","Insurance":"FINANCIALS","Real Estate":"FINANCIALS",
 "Consumer Durables & Apparel":"CONSUMER DISCRETIONARY","Retailing":"CONSUMER DISCRETIONARY","Consumer Services":"CONSUMER DISCRETIONARY",
 "Automobiles & Components":"CONSUMER DISCRETIONARY","Food, Beverage & Tobacco":"CONSUMER STAPLES","Food & Staples Retailing":"CONSUMER STAPLES",
 "Household & Personal":"CONSUMER STAPLES","Energy":"ENERGY","Health Care Equipment & Services":"HEALTH CARE","Capital Goods":"INDUSTRIALS",
 "Transportation":"INDUSTRIALS","Materials":"MATERIALS","Telecommunication Services":"TELECOMMUNICATION SERVICES","Utilities":"UTILITIES"}
num = r"([+−]?[\d,]+(?:\.\d+)?|–|n\.m\.)"
row = re.compile(r"^\s*([A-Z]{3,5}\.[NX])\s+(Dec|Mar)\s+" + r"\s+".join([num]*16) + r"\s*$")
def f(s):
    if s in ("–","n.m."): return None
    return float(s.replace(",","").replace("−","-").replace("+",""))
sector=None; stocks=[]; notes={}
lines=txt.splitlines()
for i,l in enumerate(lines):
    s=l.strip()
    for sec in SECTORS:
        if re.match(re.escape(sec)+r"\s", s) and ("SECTOR INDEX" in lines[i+1] if i+1<len(lines) else False) or re.match(re.escape(sec)+r" [^\x00-\x7F]", s):
            sector=sec
    m=row.match(l)
    if m:
        g=m.groups()
        keys=["price","wow","mom","ytd","shares","ne_fy","ne_ttm","eps_fy","eps_ttm","per_fy","per_ttm","pbv","bvps","dps","yld","roe"]
        d={"ticker":g[0],"fy":g[1],"sector":sector,"group":GROUP.get(sector)}
        for k,v in zip(keys,g[2:]): d[k]=f(v)
        stocks.append(d)
    if s.startswith("TTM : Trailing") and sector:
        notes.setdefault(sector,[]).append(s)
json.dump({"source":"Latest published company results (snapshot as of 6 Nov 2026)","as_of":"2026-11-06","sectors":SECTORS,"group":GROUP,
 "stocks":stocks,"notes":notes},open(out,"w"),indent=1,ensure_ascii=False)
from collections import Counter
print(len(stocks)); print(Counter(x["sector"] for x in stocks))
