"""Kontroll: hvilke beholdningsdata (sektor, toppselskaper, aktivaklasser) gir Yahoo for fondene og ETF-ene?"""
import json, sys
import yfinance as yf
T = ["0P0001OPBL.IR", "0P0001EC8K.IR", "0P0001LR11.IR", "0P0001OPBE.IR", "0P00000MVB.IR", "URTH", "ACWI", "NORW", "IEMG", "QQQ"]
out = {}
for t in T:
    rec = {}
    try:
        fd = yf.Ticker(t).funds_data
        for attr in ("sector_weightings", "asset_classes", "equity_holdings", "fund_overview", "fund_operations", "description"):
            try:
                v = getattr(fd, attr)
                if hasattr(v, "to_dict"):
                    v = v.reset_index().to_dict(orient="records") if hasattr(v, "reset_index") else v.to_dict()
                rec[attr] = v if isinstance(v, (dict, list, str, type(None))) else str(v)
            except Exception as e:  # noqa: BLE001
                rec[attr] = "ERR " + repr(e)[:150]
        try:
            th = fd.top_holdings
            rec["top_holdings"] = th.reset_index().to_dict(orient="records")
        except Exception as e:  # noqa: BLE001
            rec["top_holdings"] = "ERR " + repr(e)[:150]
    except Exception as e:  # noqa: BLE001
        rec["error"] = repr(e)[:300]
    out[t] = rec
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1, default=str)
print({k: {a: (len(v) if isinstance(v, (list, dict)) else str(v)[:60]) for a, v in r.items()} for k, r in out.items()})
