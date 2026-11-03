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
