"""Leser den publiserte funds.json og skriver et lite sammendrag (for kontroll utenfra)."""
import json, sys, requests
d = requests.get("https://akara86.github.io/aksjeradar/funds.json", timeout=30).json()
f = d["funds"]
out = {"generated_at": d.get("generated_at"), "run_date": d.get("run_date"),
       "funds": {x["id"]: {"price_nok": x["price_nok"], "last_date": x["last_date"], "nav": x.get("nav"), "deposit": (x.get("deposit") or {}).get("action"),
                           "level": x["level"], "hist_last": x["history"]["dates"][-1], "hist_len": len(x["history"]["dates"]),
                           "fee": x.get("fee"), "holdings": {"source": (x.get("holdings") or {}).get("source"), "n_sectors": len((x.get("holdings") or {}).get("sectors") or {}), "top3": [t["name"] for t in ((x.get("holdings") or {}).get("top") or [])[:3]]} if x.get("holdings") else None,
                           "stress": {k: (round(v["drop"], 3) if isinstance(v, dict) and "drop" in v else v) for k, v in (x.get("stress") or {}).items() if k != "since"}, "monthly_last": list((x.get("monthly") or {}).items())[-2:]} for x in f["funds"] if x.get("owned")},
       "market": {"regime": (f.get("market") or {}).get("regime"), "summary": (f.get("market") or {}).get("summary"),
                  "top": [(s["name"], s["status"], s["forward"]) for s in (f.get("market") or {}).get("sectors", [])][:5]},
       "reports": [(r["title"], round(r["avg"], 4)) for r in f.get("reports") or []],
       "picks": [(p["name"], p["attr_score"], (p.get("long") or {}).get("ann_5y")) for p in (f.get("picks") or {}).get("list", [])]}
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:1500])
