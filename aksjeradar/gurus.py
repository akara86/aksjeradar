"""
Guruer: porteføljer og porteføljebevegelser til kjente investorer, fra SEC EDGAR (13F-rapporter).

Alle forvaltere i USA med over 100 mill. USD må rapportere aksjebeholdningene sine til SEC hvert
kvartal (skjema 13F-HR), senest 45 dager etter kvartalsslutt. Rapportene er offentlige og gratis.

For hver investor i config.yaml (`gurus.list`):
  1. hent listen over innsendinger (submissions-API) og finn de to siste 13F-HR
  2. hent informasjonstabellen (XML) for begge og les ut beholdningene (navn, CUSIP, verdi, antall)
  3. finn ticker for hver CUSIP via OpenFIGI (gratis, bufres i databasen) – eller via navnematch mot universet
  4. sammenlign kvartalene: nye posisjoner, økninger, reduksjoner, salg
Deretter lages konsensus på tvers: hvilke aksjer flest eier, flest kjøper og flest selger.

Begrensninger: 13F dekker bare amerikanske aksjer (og ADR-er), bare long-posisjoner, og kommer med
inntil 45 dagers forsinkelse. Short-posisjoner, obligasjoner og utenlandske aksjer er ikke med.
"""
from __future__ import annotations

import logging
import math
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from .storage import Storage, clean_for_json

log = logging.getLogger("aksjeradar.gurus")

import os as _os

# SEC krever at automatiske verktøy oppgir navn og kontaktadresse i User-Agent (ellers 403).
# Standard er GitHub-kontoens noreply-adresse; kan overstyres med SEC_CONTACT (hemmelighet) eller gurus.contact i config.yaml.
SEC_CONTACT = _os.getenv("SEC_CONTACT", "").strip() or "akara86@users.noreply.github.com"
SEC_HEADERS = {
    "User-Agent": f"Aksjeradar personal research tool {SEC_CONTACT}",
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json, text/html, application/xml;q=0.9, */*;q=0.8",
}
SEC_PAUSE = 0.15  # SEC tillater maks 10 forespørsler per sekund


def _num(x):
    try:
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return None


def _get(url: str, **kw):
    time.sleep(SEC_PAUSE)
    r = requests.get(url, headers=SEC_HEADERS, timeout=30, **kw)
    r.raise_for_status()
    return r


# --------------------------------------------------------------------------
# SEC EDGAR
# --------------------------------------------------------------------------
def find_cik(name: str) -> str | None:
    """Slår opp CIK ut fra navn via EDGARs selskapssøk (atom-feed). Returnerer 10-sifret CIK."""
    try:
        r = _get("https://www.sec.gov/cgi-bin/browse-edgar", params={"company": name, "type": "13F-HR", "output": "atom", "count": 5})
        m = re.search(r"<cik>(\d+)</cik>", r.text, re.I) or re.search(r"CIK=(\d{10})", r.text)
        if m:
            return m.group(1).zfill(10)
    except Exception as e:  # noqa: BLE001
        log.info("CIK-oppslag feilet for «%s»: %s", name, e)
    return None


def fetch_submissions(cik: str) -> dict | None:
    try:
        return _get(f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json").json()
    except Exception as e:  # noqa: BLE001
        log.warning("Submissions feilet for CIK %s: %s", cik, e)
        _LAST_ERR.append(f"submissions CIK{cik}: {e!r}"[:300])
        return None


_LAST_ERR: list[str] = []


def latest_13f(sub: dict, n: int = 2) -> list[dict]:
    """De siste n 13F-HR-innsendingene (nyeste først): accession, filing_date, report_date."""
    rec = (sub or {}).get("filings", {}).get("recent", {})
    out = []
    for form, acc, fdate, rdate in zip(rec.get("form", []), rec.get("accessionNumber", []), rec.get("filingDate", []), rec.get("reportDate", [])):
        if form == "13F-HR":
            out.append({"accession": acc, "filing_date": fdate, "report_date": rdate})
    # én per rapportdato (nyeste innsending vinner)
    seen, uniq = set(), []
    for f in out:
        if f["report_date"] in seen:
            continue
        seen.add(f["report_date"])
        uniq.append(f)
    return uniq[:n]


def fetch_info_table(cik: str, accession: str) -> list[dict]:
    """Henter og tolker informasjonstabellen (beholdningene) for én 13F-innsending."""
    acc = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}"
    idx = _get(base + "/index.json").json()
    files = [it["name"] for it in idx.get("directory", {}).get("item", [])]
    cands = [f for f in files if f.lower().endswith(".xml") and "primary_doc" not in f.lower()]
    if not cands:  # noen eldre innsendinger har tabellen i .txt – hopp over
        return []
    # Den største XML-filen er informasjonstabellen
    best, best_rows = None, []
    for f in sorted(cands):
        try:
            xml = _get(f"{base}/{f}").content
            rows = parse_info_table(xml)
            if len(rows) > len(best_rows):
                best, best_rows = f, rows
        except Exception as e:  # noqa: BLE001
            log.debug("Kunne ikke tolke %s: %s", f, e)
    return best_rows


def parse_info_table(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    rows = []
    for el in root.iter():
        if not el.tag.lower().endswith("infotable"):
            continue
        d = {}
        for ch in el.iter():
            tag = ch.tag.split("}")[-1].lower()
            if tag in ("nameofissuer", "titleofclass", "cusip", "value", "sshprnamt", "sshprnamttype", "putcall", "investmentdiscretion"):
                d[tag] = (ch.text or "").strip()
        if not d.get("cusip"):
            continue
        if d.get("putcall"):
            continue  # opsjoner holdes utenfor
        if d.get("sshprnamttype", "SH").upper() != "SH":
            continue  # bare aksjer (ikke prinsipalbeløp)
        rows.append({
            "name": d.get("nameofissuer", ""), "class": d.get("titleofclass", ""), "cusip": d["cusip"].upper(),
            "value": _num(d.get("value")) or 0.0, "shares": _num(d.get("sshprnamt")) or 0.0,
        })
    # Slå sammen linjer med samme CUSIP (flere forvaltere/kontoer i samme rapport)
    merged: dict[str, dict] = {}
    for r in rows:
        m = merged.setdefault(r["cusip"], {"name": r["name"], "class": r["class"], "cusip": r["cusip"], "value": 0.0, "shares": 0.0})
        m["value"] += r["value"]
        m["shares"] += r["shares"]
    return list(merged.values())


# --------------------------------------------------------------------------
# CUSIP -> ticker
# --------------------------------------------------------------------------
def map_cusips(cusips: list[str], store: Storage, max_new: int = 400) -> dict[str, dict]:
    """CUSIP -> {ticker, name} via OpenFIGI (gratis, uten nøkkel: 25 kall/min à 10 oppslag). Bufres i databasen."""
    cache, _ = store.load_snapshot("gurus", "cusip_map")
    cache = cache or {}
    todo = [c for c in dict.fromkeys(cusips) if c not in cache][:max_new]
    for i in range(0, len(todo), 10):
        batch = todo[i:i + 10]
        try:
            r = requests.post("https://api.openfigi.com/v3/mapping", json=[{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch],
                              headers={"Content-Type": "application/json"}, timeout=30)
            if r.status_code == 429:
                log.info("OpenFIGI: ratebegrenset – fortsetter neste kjøring")
                break
            r.raise_for_status()
            for c, res in zip(batch, r.json()):
                data = (res or {}).get("data") or []
                if data:
                    tk = str(data[0].get("ticker") or "").replace("/", "-").upper()
                    cache[c] = {"ticker": tk or None, "name": data[0].get("name") or ""}
                else:
                    cache[c] = {"ticker": None, "name": ""}
        except Exception as e:  # noqa: BLE001
            log.info("OpenFIGI feilet: %s", e)
            break
        time.sleep(2.6)
    store.save_snapshot("gurus", "cusip_map", cache)
    return cache


def _norm(s: str) -> str:
    s = re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper())
    for w in (" INC", " CORP", " CO", " LTD", " PLC", " CL A", " CL B", " CLASS A", " CLASS B", " COM", " NEW", " HOLDINGS", " HLDGS", " GROUP", " THE"):
        s = s.replace(w, " ")
    return " ".join(s.split())


def match_by_name(issuer: str, universe_names: dict[str, str]) -> str | None:
    """Reserve: finn ticker ved å matche utstedernavn mot navnene i aksjeuniverset."""
    key = _norm(issuer)
    if not key:
        return None
    first = key.split()[0]
    hits = [t for t, n in universe_names.items() if _norm(n).startswith(key) or key.startswith(_norm(n))]
    if len(hits) == 1:
        return hits[0]
    hits = [t for t, n in universe_names.items() if _norm(n).split()[:1] == [first] and len(first) >= 5]
    return hits[0] if len(hits) == 1 else None


# --------------------------------------------------------------------------
# Sammenligning og konsensus
# --------------------------------------------------------------------------
def compare(latest: list[dict], prev: list[dict]) -> list[dict]:
    """Bevegelser fra forrige til siste kvartal, per CUSIP."""
    p = {h["cusip"]: h for h in prev}
    l = {h["cusip"]: h for h in latest}
    total = sum(h["value"] for h in latest) or 1.0
    moves = []
    for c, h in l.items():
        old = p.get(c)
        if not old:
            moves.append({**h, "move": "ny", "change_shares": None, "weight": h["value"] / total})
        elif old["shares"] > 0 and h["shares"] / old["shares"] - 1 >= 0.10:
            moves.append({**h, "move": "økt", "change_shares": h["shares"] / old["shares"] - 1, "weight": h["value"] / total})
        elif old["shares"] > 0 and h["shares"] / old["shares"] - 1 <= -0.10:
            moves.append({**h, "move": "redusert", "change_shares": h["shares"] / old["shares"] - 1, "weight": h["value"] / total})
    for c, old in p.items():
        if c not in l:
            moves.append({**old, "move": "solgt", "change_shares": -1.0, "weight": 0.0})
    order = {"ny": 0, "økt": 1, "redusert": 2, "solgt": 3}
    moves.sort(key=lambda m: (order[m["move"]], -(m.get("value") or 0)))
    return moves


def run_gurus(store: Storage, cfg: dict, universe_names: dict[str, str], prices: dict | None = None,
              verdicts: dict | None = None, demo: bool = False) -> dict:
    gcfg = cfg["gurus"]
    if gcfg.get("contact") and not _os.getenv("SEC_CONTACT"):
        SEC_HEADERS["User-Agent"] = f"Aksjeradar personal research tool {gcfg['contact']}"
    out_investors, alerts = [], []
    errors: list[dict] = []
    if not demo:
        import subprocess
        probes = [
            ("curl data.sec.gov", ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "-A", SEC_HEADERS["User-Agent"], "-H", "Accept-Encoding: gzip, deflate", "https://data.sec.gov/submissions/CIK0001067983.json"]),
            ("curl www.sec.gov", ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "-A", SEC_HEADERS["User-Agent"], "https://www.sec.gov/Archives/edgar/data/1067983/index.json"]),
            ("curl efts", ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "-A", SEC_HEADERS["User-Agent"], "https://efts.sec.gov/LATEST/search-index?q=berkshire&forms=13F-HR"]),
            ("curl 13f.info", ["curl", "-sS", "-o", "/tmp/13f.html", "-w", "%{http_code}", "-A", "Mozilla/5.0 (aksjeradar research)", "https://13f.info/manager/0001067983-berkshire-hathaway-inc"]),
        ]
        for label, cmd in probes:
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                entry = {"check": label, "status": out.stdout.strip(), "err": out.stderr[:200]}
                if "13f.info" in label:
                    try:
                        html = open("/tmp/13f.html", encoding="utf-8", errors="ignore").read()
                        links = re.findall(r'href="(/13f/[^"]+)"', html)[:6]
                        entry["links"] = links
                        entry["text"] = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)).split())[:500]
                    except Exception as e:  # noqa: BLE001
                        entry["parse"] = repr(e)
                errors.append(entry)
            except Exception as e:  # noqa: BLE001
                errors.append({"check": label, "error": repr(e)[:300]})
        # requests med eksplisitt Host-header (SEC sin dokumenterte variant)
        for host, url in (("data.sec.gov", "https://data.sec.gov/submissions/CIK0001067983.json"), ("www.sec.gov", "https://www.sec.gov/Archives/edgar/data/1067983/index.json")):
            try:
                rr = requests.get(url, headers={**SEC_HEADERS, "Host": host}, timeout=30)
                errors.append({"check": f"requests+Host {host}", "status": rr.status_code})
            except Exception as e:  # noqa: BLE001
                errors.append({"check": f"requests+Host {host}", "error": repr(e)[:200]})
        for url in ("https://data.sec.gov/submissions/CIK0001067983.json", "https://www.sec.gov/Archives/edgar/data/1067983/index.json", "https://api.openfigi.com/v3/mapping"):
            try:
                time.sleep(SEC_PAUSE)
                rr = requests.get(url, headers=SEC_HEADERS, timeout=30) if "openfigi" not in url else requests.post(url, json=[{"idType": "ID_CUSIP", "idValue": "037833100"}], headers={"Content-Type": "application/json"}, timeout=30)
                body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", rr.text, flags=re.S | re.I)
                body = " ".join(re.sub(r"<[^>]+>", " ", body).split())
                errors.append({"check": url, "status": rr.status_code, "len": len(rr.content), "text": body[:700],
                               "ua": SEC_HEADERS["User-Agent"], "resp_headers": {k: v for k, v in rr.headers.items() if k.lower() in ("server", "x-cache", "via", "content-type", "x-amz-cf-pop")}})
            except Exception as e:  # noqa: BLE001
                errors.append({"check": url, "error": repr(e)[:300]})
    prev_state, _ = store.load_snapshot("gurus", "state")
    prev_state = prev_state or {}
    new_state = {}
    cusip_map: dict[str, dict] = {}
    all_latest: list[tuple[str, dict]] = []

    for g in gcfg.get("list") or []:
        gid = g.get("id") or re.sub(r"\W+", "_", g["name"].lower())
        if demo:
            inv = _demo_investor(g, gid, universe_names)
            out_investors.append(inv)
            continue
        cik = str(g.get("cik") or "").zfill(10) if g.get("cik") else None
        sub = fetch_submissions(cik) if cik else None
        if not sub or not latest_13f(sub):
            cik2 = find_cik(g.get("edgar_name") or g["firm"])
            if cik2 and cik2 != cik:
                sub = fetch_submissions(cik2)
                cik = cik2
        if not sub:
            log.warning("Guru «%s»: fant ingen innsendinger", g["name"])
            errors.append({"investor": g["name"], "cik": cik, "error": "ingen submissions"})
            continue
        filings = latest_13f(sub, 2)
        if not filings:
            log.warning("Guru «%s»: ingen 13F-HR", g["name"])
            errors.append({"investor": g["name"], "cik": cik, "error": "ingen 13F-HR", "forms": list(dict.fromkeys((sub.get("filings", {}).get("recent", {}).get("form") or [])[:40]))})
            continue
        latest_f = filings[0]
        cached = None
        cache_key = f"13f:{cik}:{latest_f['accession']}"
        payload, _ = store.load_snapshot("gurus", cache_key)
        if payload:
            cached = payload
        else:
            try:
                rows_l = fetch_info_table(cik, latest_f["accession"])
                rows_p = fetch_info_table(cik, filings[1]["accession"]) if len(filings) > 1 else []
            except Exception as e:  # noqa: BLE001
                log.warning("Guru «%s»: henting feilet: %s", g["name"], e)
                errors.append({"investor": g["name"], "cik": cik, "accession": latest_f["accession"], "error": repr(e)[:300]})
                continue
            if not rows_l:
                log.warning("Guru «%s»: tom beholdning i %s", g["name"], latest_f["accession"])
                errors.append({"investor": g["name"], "cik": cik, "accession": latest_f["accession"], "error": "tom informasjonstabell"})
                continue
            # Verdier før 2023 ble rapportert i tusen dollar
            for rows, f in ((rows_l, latest_f), (rows_p, filings[1] if len(filings) > 1 else None)):
                if f and f["report_date"] < "2023-01-01":
                    for r in rows:
                        r["value"] *= 1000
            cached = {"latest": rows_l, "prev": rows_p, "filing": latest_f, "prev_filing": filings[1] if len(filings) > 1 else None, "cik": cik,
                      "entity": sub.get("name")}
            store.save_snapshot("gurus", cache_key, cached)
        inv = _build_investor(g, gid, cached, universe_names, store, cusip_map, prices, verdicts)
        out_investors.append(inv)
        all_latest.append((gid, cached))
        new_state[gid] = cached["filing"]["accession"]
        if prev_state.get(gid) and prev_state[gid] != cached["filing"]["accession"]:
            top_new = [m["ticker"] or m["name"] for m in inv["moves"] if m["move"] == "ny"][:3]
            top_sold = [m["ticker"] or m["name"] for m in inv["moves"] if m["move"] == "solgt"][:3]
            alerts.append({"id": gid, "name": g["name"], "text": f"{g['name']} har levert ny 13F (per {cached['filing']['report_date']}): "
                           + (f"nye: {', '.join(top_new)}" if top_new else "ingen nye posisjoner") + (f"; solgt: {', '.join(top_sold)}" if top_sold else "")})

    if not demo:
        store.save_snapshot("gurus", "state", new_state)

    consensus = _consensus(out_investors)
    return clean_for_json({
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "demo": demo,
        "investors": out_investors,
        "consensus": consensus,
        "alerts": alerts,
        "errors": (errors + [{"error": x} for x in _LAST_ERR])[:60],
        "note": "Kilde: SEC EDGAR, skjema 13F-HR. Dekker amerikanske aksjer (long), rapportert inntil 45 dager etter kvartalsslutt.",
    })


def _build_investor(g: dict, gid: str, cached: dict, universe_names: dict[str, str], store: Storage, cusip_map: dict,
                    prices: dict | None, verdicts: dict | None) -> dict:
    rows_l, rows_p = cached["latest"], cached.get("prev") or []
    cusips = [r["cusip"] for r in rows_l] + [r["cusip"] for r in rows_p]
    fresh = map_cusips(cusips, store)
    cusip_map.update(fresh)

    def tick(r: dict) -> str | None:
        m = cusip_map.get(r["cusip"]) or {}
        t = m.get("ticker")
        if t and (t in universe_names):
            return t
        if t:
            return t
        return match_by_name(r["name"], universe_names)

    total = sum(r["value"] for r in rows_l) or 1.0
    holdings = []
    for r in sorted(rows_l, key=lambda x: -x["value"]):
        t = tick(r)
        h = {"name": r["name"].title(), "cusip": r["cusip"], "ticker": t, "value": r["value"], "shares": r["shares"], "weight": r["value"] / total,
             "in_universe": bool(t and t in universe_names)}
        if t and verdicts and t in verdicts:
            h["verdict"] = verdicts[t].get("verdict")
            h["score"] = verdicts[t].get("score")
            h["price"] = verdicts[t].get("price")
        holdings.append(h)
    moves = []
    for m in compare(rows_l, rows_p):
        t = tick(m)
        moves.append({"name": m["name"].title(), "cusip": m["cusip"], "ticker": t, "move": m["move"], "change_shares": m.get("change_shares"),
                      "value": m.get("value"), "weight": m.get("weight"), "in_universe": bool(t and t in universe_names),
                      "verdict": (verdicts or {}).get(t, {}).get("verdict") if t else None})
    top_n = int(g.get("top_n") or 15)
    return {
        "id": gid, "name": g["name"], "firm": g["firm"], "style": g.get("style", ""), "bio": g.get("bio", ""),
        "report_date": cached["filing"]["report_date"], "filing_date": cached["filing"]["filing_date"],
        "prev_report_date": (cached.get("prev_filing") or {}).get("report_date"),
        "total_value": total, "n_positions": len(rows_l),
        "top10_weight": sum(h["weight"] for h in holdings[:10]),
        "holdings": holdings[:top_n], "moves": moves[:40],
        "n_moves": {k: sum(1 for m in moves if m["move"] == k) for k in ("ny", "økt", "redusert", "solgt")},
    }


def _consensus(investors: list[dict]) -> dict:
    owned: dict[str, dict] = {}
    bought: dict[str, dict] = {}
    sold: dict[str, dict] = {}
    for inv in investors:
        for h in inv["holdings"]:
            key = h["ticker"] or h["name"]
            o = owned.setdefault(key, {"ticker": h["ticker"], "name": h["name"], "n": 0, "investors": [], "avg_weight": 0.0, "in_universe": h["in_universe"], "verdict": h.get("verdict")})
            o["n"] += 1
            o["investors"].append(inv["name"].split()[-1] if " " in inv["name"] else inv["name"])
            o["avg_weight"] += h["weight"]
        for m in inv["moves"]:
            key = m["ticker"] or m["name"]
            tgt = bought if m["move"] in ("ny", "økt") else sold
            d = tgt.setdefault(key, {"ticker": m["ticker"], "name": m["name"], "n": 0, "investors": [], "in_universe": m["in_universe"], "verdict": m.get("verdict"), "kinds": []})
            d["n"] += 1
            d["investors"].append(inv["name"].split()[-1] if " " in inv["name"] else inv["name"])
            d["kinds"].append(m["move"])
    for o in owned.values():
        o["avg_weight"] = o["avg_weight"] / o["n"]
    top_owned = sorted(owned.values(), key=lambda x: (-x["n"], -x["avg_weight"]))[:15]
    top_bought = sorted(bought.values(), key=lambda x: -x["n"])[:15]
    top_sold = sorted(sold.values(), key=lambda x: -x["n"])[:15]
    return {"owned": top_owned, "bought": top_bought, "sold": top_sold}


# --------------------------------------------------------------------------
# Demo
# --------------------------------------------------------------------------
def _demo_investor(g: dict, gid: str, universe_names: dict[str, str]) -> dict:
    import random

    rnd = random.Random(gid)
    us = [t for t in universe_names if "." not in t]
    picks = rnd.sample(us, min(25, len(us)))
    vals = sorted([rnd.lognormvariate(20, 1) for _ in picks], reverse=True)
    total = sum(vals)
    holdings = [{"name": universe_names[t], "cusip": f"DEMO{i:05d}", "ticker": t, "value": v, "shares": v / 100, "weight": v / total, "in_universe": True} for i, (t, v) in enumerate(zip(picks, vals))]
    moves = []
    for h in holdings[:8]:
        mv = rnd.choice(["ny", "økt", "redusert"])
        moves.append({"name": h["name"], "cusip": h["cusip"], "ticker": h["ticker"], "move": mv, "change_shares": None if mv == "ny" else rnd.uniform(-0.5, 0.8), "value": h["value"], "weight": h["weight"], "in_universe": True})
    for t in rnd.sample(us, 3):
        moves.append({"name": universe_names[t], "cusip": "X", "ticker": t, "move": "solgt", "change_shares": -1.0, "value": None, "weight": 0.0, "in_universe": True})
    return {"id": gid, "name": g["name"], "firm": g["firm"], "style": g.get("style", ""), "bio": g.get("bio", ""),
            "report_date": "2026-06-30", "filing_date": "2026-08-14", "prev_report_date": "2026-03-31", "total_value": total, "n_positions": len(holdings),
            "top10_weight": sum(h["weight"] for h in holdings[:10]), "holdings": holdings[:15], "moves": moves,
            "n_moves": {k: sum(1 for m in moves if m["move"] == k) for k in ("ny", "økt", "redusert", "solgt")}}
