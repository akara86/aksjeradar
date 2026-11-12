"""Kontroll: hvilken dag i proxyen (ETF × valuta) treffer fondets ekte andelskurs best? (forsinkelse -1/0/+1)"""
import json, sys
import pandas as pd
import yfinance as yf
import yaml

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
funds = [f for f in cfg["funds"]["list"] if f.get("nav_ticker")]
tick = sorted({f["proxy"] for f in funds} | {f["nav_ticker"] for f in funds} | {"USDNOK=X", "EURNOK=X"} | {p["ticker"] for f in funds for p in f.get("intraday_proxies") or []})
raw = yf.download(tick, period="1y", interval="1d", auto_adjust=True, progress=False)["Close"]
raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
out = {}
for f in funds:
    nav = raw[f["nav_ticker"]].dropna()
    rec = {}
    for name, tk, cur in [("proxy", f["proxy"], f.get("currency", "USD"))] + [(p["ticker"], p["ticker"], p.get("currency", "USD")) for p in f.get("intraday_proxies") or []]:
        px = raw[tk].dropna()
        fx = raw[f"{cur}NOK=X"].dropna() if cur != "NOK" else None
        nok = px * fx.reindex(px.index, method="ffill") if fx is not None and f.get("fx_relevant", True) else px
        r = {}
        for lag in (-1, 0, 1):
            j = pd.concat([nav.pct_change().rename("n"), nok.pct_change().shift(lag).rename("p")], axis=1).dropna().tail(180)
            r[str(lag)] = {"corr": round(float(j["n"].corr(j["p"])), 3), "te": round(float((j["n"] - j["p"]).std()), 5)}
        # og: ETF i lokal valuta uten valuta, og valuta forskjøvet
        j = pd.concat([nav.pct_change().rename("n"), px.pct_change().rename("p"), (fx.pct_change() if fx is not None else px * 0).rename("x")], axis=1).dropna().tail(180)
        r["etf_only"] = round(float(j["n"].corr(j["p"])), 3)
        r[name] = tk
        last = pd.concat([nav.pct_change().rename("nav"), nok.pct_change().rename("p0"), nok.pct_change().shift(1).rename("p_lag1")], axis=1).tail(8)
        r["recent"] = {d.strftime("%m-%d"): [None if pd.isna(v) else round(float(v), 4) for v in row] for d, row in last.iterrows()}
        rec[name] = r
    out[f["id"]] = rec
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: {n: {l: v[l] for l in ("-1", "0", "1")} for n, v in r.items()} for k, r in out.items()}))
