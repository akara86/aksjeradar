"""Leser den publiserte funds.json og skriver et lite sammendrag (for kontroll utenfra)."""
import json, sys, requests
d = requests.get("https://akara86.github.io/aksjeradar/funds.json", timeout=30).json()
f = d["funds"]
out = {"generated_at": d.get("generated_at"), "run_date": d.get("run_date"),
       "funds": {x["id"]: {"price_nok": x["price_nok"], "last_date": x["last_date"], "nav": x.get("nav"), "deposit": (x.get("deposit") or {}).get("action"),
                           "level": x["level"], "hist_last": x["history"]["dates"][-1], "hist_len": len(x["history"]["dates"])} for x in f["funds"] if x.get("owned")},
       "market": {"regime": (f.get("market") or {}).get("regime"), "summary": (f.get("market") or {}).get("summary"),
                  "top": [(s["name"], s["status"], s["forward"]) for s in (f.get("market") or {}).get("sectors", [])][:5]},
       "picks": [(p["name"], p["attr_score"], (p.get("long") or {}).get("ann_5y")) for p in (f.get("picks") or {}).get("list", [])]}
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:1500])
