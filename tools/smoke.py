"""Røyktest av den publiserte appen: åpner alle faner med en eksempelportefølje og samler JavaScript-feil."""
import json, sys
from playwright.sync_api import sync_playwright

URL = "https://akara86.github.io/aksjeradar/"
PF = {"funds": [{"id": "klp_global", "value": 392907, "date": "2026-11-24", "cost": 390160},
                {"id": "storebrand_solutions", "value": 260765, "date": "2026-11-24", "cost": 211803},
                {"id": "gambak", "value": 162787, "date": "2026-11-24", "cost": 110199},
                {"id": "klp_em", "value": 77118, "date": "2026-11-24", "cost": 79299},
                {"id": "dnb_teknologi", "value": 68927, "date": "2026-11-24", "cost": 69400}],
      "deposits": [], "basis": {"date": "2026-11-24", "invested": 806179}}
out = {"errors": [], "console": [], "tabs": {}}
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 844})
    pg.on("pageerror", lambda e: out["errors"].append(str(e)))
    pg.on("console", lambda m: out["console"].append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    pg.goto(URL, wait_until="networkidle")
    pg.evaluate(f"localStorage.setItem('ar.portfolio.v1', JSON.stringify({json.dumps(PF)}))")
    for tab in ["idag", "verdi", "marked", "utvalgt", "fond", "mer"]:
        pg.evaluate(f"localStorage.setItem('ar.tab','{tab}')")
        pg.reload(wait_until="networkidle"); pg.wait_for_timeout(1500)
        out["tabs"][tab] = pg.inner_text("body")[:1500]
        pg.screenshot(path=f"smoke_{tab}.png")
    for vm in ["oversikt", "fordeling", "fremtid", "risiko", "vekting"]:
        pg.evaluate("localStorage.setItem('ar.tab','verdi')"); pg.evaluate(f"localStorage.setItem('ar.vmode','{vm}')")
        pg.reload(wait_until="networkidle"); pg.wait_for_timeout(1200)
        out["tabs"]["verdi_" + vm] = pg.inner_text("body")[:2500]
    for name in ["sw.js", "app.js", "funds.json", "funds_now.json"]:
        r = pg.request.get(URL + name)
        out[name] = {"status": r.status, "len": len(r.body())}
    b.close()
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print(json.dumps({"errors": out["errors"], "console": out["console"][:10]}, ensure_ascii=False))
