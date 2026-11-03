"""Kontroll: finner fondenes ekte andelskurser hos Yahoo (via ISIN) og sammenligner med proxy-estimatet."""
import json, sys
from datetime import datetime, timezone
import requests
import yfinance as yf

ISINS = {
    "klp_global": "NO0012445404", "storebrand_solutions": "NO0010817703", "gambak": "NO0010904857",
    "klp_em": "NO0012443664", "dnb_teknologi": "NO0010337678",
}
UA = {"User-Agent": "Mozilla/5.0 (aksjeradar fondskontroll)"}
out = {"generated_at": datetime.now(timezone.utc).isoformat(), "funds": {}}
for fid, isin in ISINS.items():
    rec = {"isin": isin}
    try:
        r = requests.get("https://query2.finance.yahoo.com/v1/finance/search", params={"q": isin, "quotesCount": 5, "newsCount": 0}, headers=UA, timeout=20)
        rec["search_status"] = r.status_code
        quotes = r.json().get("quotes", []) if r.ok else []
        rec["candidates"] = [{k: q.get(k) for k in ("symbol", "shortname", "longname", "quoteType", "exchange")} for q in quotes]
        sym = next((q["symbol"] for q in quotes if q.get("quoteType") in ("MUTUALFUND", "ETF")), quotes[0]["symbol"] if quotes else None)
        rec["symbol"] = sym
        if sym:
            h = yf.Ticker(sym).history(period="3mo", interval="1d", auto_adjust=False)
            rec["currency"] = (yf.Ticker(sym).fast_info or {}).get("currency") if hasattr(yf.Ticker(sym), "fast_info") else None
            rec["nav"] = {d.strftime("%Y-%m-%d"): round(float(v), 4) for d, v in h["Close"].dropna().items()}
    except Exception as e:  # noqa: BLE001
        rec["error"] = repr(e)[:300]
    out["funds"][fid] = rec
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: (v.get("symbol"), len(v.get("nav", {})), v.get("error")) for k, v in out["funds"].items()}))

# ---- sammenlign med proxy-estimatet appen bruker (ETF × valuta) ----
import pandas as pd
PROX = {"klp_global": ("URTH", "USD", True), "storebrand_solutions": ("ACWI", "USD", True), "gambak": ("NORW", "USD", False),
        "klp_em": ("IEMG", "USD", True), "dnb_teknologi": ("QQQ", "USD", True)}
px = yf.download([p[0] for p in PROX.values()] + ["USDNOK=X"], period="3mo", interval="1d", group_by="ticker", auto_adjust=True, progress=False)
fx = px["USDNOK=X"]["Close"].dropna(); fx.index = fx.index.normalize()
cmp = {}
for fid, (t, cur, fxrel) in PROX.items():
    nav = pd.Series(out["funds"][fid].get("nav", {}), dtype=float); nav.index = pd.to_datetime(nav.index)
    p = px[t]["Close"].dropna(); p.index = p.index.normalize()
    nok = (p * fx.reindex(p.index, method="ffill")).dropna()
    # fondets NAV for dag D følger markedet på dag D (proxyens sluttkurs samme dag)
    j = pd.concat([nav.rename("nav"), nok.rename("proxy")], axis=1).dropna()
    r = j.pct_change().dropna()
    def per(a, b):
        s = j[(j.index >= a) & (j.index <= b)]
        return None if len(s) < 2 else {"real": s["nav"].iloc[-1] / s["nav"].iloc[0] - 1, "proxy": s["proxy"].iloc[-1] / s["proxy"].iloc[0] - 1, "from": str(s.index[0].date()), "to": str(s.index[-1].date())}
    lag = pd.concat([nav.rename("nav"), nok.shift(1).rename("proxy")], axis=1).dropna().pct_change().dropna()
    cmp[fid] = {"proxy": t, "n": len(r), "corr_same_day": round(float(r["nav"].corr(r["proxy"])), 3), "corr_lag1": round(float(lag["nav"].corr(lag["proxy"])), 3),
                "te_daily": round(float((r["nav"] - r["proxy"]).std()), 5),
                "since_18_10": per("2026-10-16", "2026-12-31"), "last_1m": per(str((j.index[-1] - pd.Timedelta(days=30)).date()), "2026-12-31"),
                "last_3m": per("2026-01-01", "2026-12-31"), "last_nav": [str(nav.index[-1].date()), float(nav.iloc[-1])], "last_proxy": [str(nok.index[-1].date()), float(nok.iloc[-1])]}
out["compare"] = cmp
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print(json.dumps(cmp, indent=1, default=str)[:3000])
