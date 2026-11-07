import json, sys
import yfinance as yf
out = {}
for t in ["URTH", "USDNOK=X", "NORW", "0P0001OPBL.IR"]:
    h = yf.Ticker(t).history(start="2020-02-01", end="2020-04-30", auto_adjust=True)
    out[t] = {d.strftime("%Y-%m-%d"): round(float(v), 4) for d, v in h["Close"].items()}
d = yf.download(["URTH", "USDNOK=X"], period="10y", interval="1d", group_by="ticker", auto_adjust=True, progress=False)
fx = d["USDNOK=X"]["Close"].dropna()
out["fx10y_2020"] = {k.strftime("%Y-%m-%d"): round(float(v), 4) for k, v in fx[(fx.index >= "2020-02-01") & (fx.index <= "2020-04-30")].items()}
json.dump(out, open(sys.argv[1], "w"), indent=1)
