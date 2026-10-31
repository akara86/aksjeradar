#!/usr/bin/env python3
"""
Aksjeradar – daglig kjøring.

    python run.py              # ekte data fra Yahoo Finance
    python run.py --demo       # syntetiske data, ingen nettverk (for å prøve verktøyet)
    python run.py --no-notify  # lag rapport, men ikke send Telegram/e-post
    python run.py --refresh    # tving ny henting av fundamentaldata for alle aksjer
    python run.py --tickers EQNR.OL,AAPL,NVDA   # kjør bare på disse

Stegene:
  1. hent kurser (batch)            -> data/aksjeradar.db
  2. hent fundamental/analytiker/innsider per aksje (hurtigbufret i noen dager)
  3. beregn signaler + score + ideer
  4. skriv rapport til reports/      -> aksjeradar_<dato>.md / .html + latest.*
  5. send Telegram / e-post (hvis satt opp i .env)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

from aksjeradar.autotrader import run_autotrader
from aksjeradar.config import all_tickers, load_config
from aksjeradar.data import FX_DEMO, demo_details, demo_fx_frames, demo_prices, fetch_details, fetch_fx, fetch_prices
from aksjeradar.export import export_json
from aksjeradar.funds import run_funds, run_picks
from aksjeradar.market import run_market
from aksjeradar.gurus import run_gurus
from aksjeradar.notify import push_settings, send_email, send_push, send_telegram
from aksjeradar.report import render_html, render_markdown, render_telegram, write_reports
from aksjeradar.scoring import CATEGORIES, build_table, generate_ideas
from aksjeradar.storage import Storage
from aksjeradar.universe import build_universe

log = logging.getLogger("aksjeradar")


def main() -> int:
    ap = argparse.ArgumentParser(description="Aksjeradar – daglig analyse")
    ap.add_argument("--demo", action="store_true", help="bruk syntetiske data (ingen nettverk)")
    ap.add_argument("--no-notify", action="store_true", help="ikke send Telegram/e-post")
    ap.add_argument("--refresh", action="store_true", help="hent fundamentaldata på nytt for alle aksjer")
    ap.add_argument("--tickers", help="kommaseparert liste som overstyrer config.yaml")
    ap.add_argument("--config", help="alternativ config-fil")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
    )
    logging.getLogger("yfinance").setLevel(logging.ERROR)
    logging.getLogger("peewee").setLevel(logging.ERROR)

    cfg = load_config(args.config)
    store = Storage(cfg["data"]["db_path"])
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.demo:
        tickers = all_tickers(cfg)
    else:
        tickers = build_universe(cfg, store)
    if not tickers:
        log.error("Ingen tickere i config.yaml.")
        return 1
    run_date = date.today().isoformat()
    t0 = time.time()

    # ---------- 1. kurser ----------
    log.info("Henter kurser for %d aksjer ...", len(tickers))
    if args.demo:
        prices = demo_prices(tickers)
    else:
        prices = fetch_prices(tickers, cfg["data"]["history_period"])
        # Aksjer som feilet nå, men som finnes i databasen fra før: bruk gammel historikk
        for t in tickers:
            if t not in prices:
                cached = store.load_prices(t)
                if len(cached) >= 60:
                    prices[t] = cached
                    log.info("Bruker bufrede kurser for %s", t)
    for t, df in prices.items():
        store.save_prices(t, df)
    log.info("Kurser klare for %d av %d aksjer.", len(prices), len(tickers))
    if not prices:
        log.error("Ingen kursdata. Sjekk nettverk eller tickere.")
        return 1

    # Valutakurser (til NOK) – lagres, så forrige kjørings kurser brukes hvis hentingen feiler
    if args.demo:
        fx = dict(FX_DEMO)
    else:
        fx = fetch_fx()
        if fx:
            store.save_snapshot("fx", "NOK", fx)
        else:
            fx, _ = store.load_snapshot("fx", "NOK")
            fx = fx or {}
            log.warning("Bruker lagrede valutakurser: %s", fx)

    # ---------- 2. fundamental / analytiker / innsider ----------
    details: dict[str, dict] = {}
    max_age = float(cfg["data"]["fundamentals_max_age_days"])
    max_fetch = int(cfg["data"].get("max_details_per_run", 350))
    pause = float(cfg["data"].get("request_pause", 0.3))
    if args.demo:
        for t in prices:
            details[t] = demo_details(t, float(prices[t]["Close"].iloc[-1]))
            store.save_snapshot("details", t, details[t])
    else:
        # Bruk buffer der den er fersk; hent de som mangler eller er eldst – inntil taket per kjøring
        todo: list[tuple[float, str]] = []
        for t in prices:
            payload, age = store.load_snapshot("details", t)
            if payload and not args.refresh and age is not None and age < max_age:
                details[t] = payload
            else:
                todo.append((age if age is not None else 1e9, t))
                if payload:
                    details[t] = payload  # bruk gammel versjon inntil ny er hentet
        todo.sort(key=lambda x: -x[0])  # mangler/eldst først
        if len(todo) > max_fetch:
            log.info("%d aksjer trenger fundamentaldata; henter %d nå, resten neste kjøring.", len(todo), max_fetch)
        fetched = failed = 0
        for i, (_, t) in enumerate(todo[:max_fetch], start=1):
            d = fetch_details(t)
            if d["fundamentals"].get("shortName") or d["fundamentals"].get("currentPrice"):
                details[t] = d
                store.save_snapshot("details", t, d)
                fetched += 1
            else:
                failed += 1  # tomt svar (f.eks. ratebegrensning) – prøves igjen neste kjøring
                details.setdefault(t, d)
            time.sleep(pause)
            if i % 25 == 0:
                log.info("  ... %d/%d aksjer", i, min(len(todo), max_fetch))
        log.info("Fundamentaldata: %d hentet nå, %d tomme svar, %d fra buffer.", fetched, failed, len(prices) - fetched - failed)

    # ---------- 3. signaler, score, ideer ----------
    table = build_table(prices, details, cfg)
    ideas = generate_ideas(table, cfg)
    store.save_scores(run_date, table)
    store.save_ideas(run_date, ideas)

    # ---------- 4. rapport + datafil til mobil-appen ----------
    md = render_markdown(table, ideas, run_date, cfg, demo=args.demo)
    md_path, html_path = write_reports(md, run_date, cfg["report"]["output_dir"])
    # Fond – gunstige innganger ut fra fall i NOK og valuta
    funds_payload = {}
    if cfg["funds"].get("enabled", True) and cfg["funds"].get("list"):
        try:
            picks_list = (cfg.get("picks") or {}).get("list") or [] if (cfg.get("picks") or {}).get("enabled", True) else []
            all_f = cfg["funds"]["list"] + picks_list
            proxies = sorted({f["proxy"] for f in all_f} | {"URTH"})
            currencies = sorted({f.get("currency", "USD") for f in all_f} - {"NOK"})
            if args.demo:
                proxy_frames = demo_prices(proxies, days=2600, seed=5)
                fx_frames = demo_fx_frames(days=2600)
            else:
                proxy_frames = fetch_prices(proxies, "10y")   # 2 år i grafen, 200 dager til snitt, 10 år til langsiktige tall
                fx_frames = fetch_prices([f"{c}NOK=X" for c in currencies], "10y")
            funds_payload = run_funds(store, cfg, proxy_frames, fx_frames, table)
            log.info("Fond: %d analysert, %d varsler", len(funds_payload.get("funds", [])), len(funds_payload.get("alerts", [])))
            mc = cfg.get("market") or {}
            if mc.get("enabled", True) and mc.get("sectors"):
                try:
                    mt = sorted({x["etf"] for x in mc.get("sectors", []) + mc.get("themes", []) + mc.get("regions", [])} | {mc.get("benchmark", "SPY")})
                    mt_macro = [x["ticker"] for x in mc.get("macro", [])]
                    need = [t for t in mt + mt_macro if t not in proxy_frames and t not in fx_frames]
                    if args.demo:
                        extra = demo_prices(need, days=760, seed=9)
                    else:
                        extra = fetch_prices(need, "3y") if need else {}
                    market = run_market(cfg, {**proxy_frames, **fx_frames, **extra}, table)
                    funds_payload["market"] = market
                    log.info("Marked: %d sektorer/tema, %d regioner, regime %s", len(market["sectors"]), len(market["regions"]), market["regime"])
                except Exception as e:  # noqa: BLE001
                    log.exception("Markedsanalysen feilet: %s", e)
            if picks_list:
                glob = next((x for x in funds_payload.get("funds", []) if x["id"] in ("klp_global", "global")), None)
                picks = run_picks(cfg, proxy_frames, fx_frames, table, glob["ret_1y"] if glob else None)
                funds_payload = {k: v for k, v in funds_payload.items() if k != "funds"} | {"picks": picks, "funds": funds_payload.get("funds", [])}
                log.info("Utvalgt: %d fond", len(picks["list"]))
        except Exception as e:  # noqa: BLE001
            log.exception("Fondsmodulen feilet: %s", e)

    # Guruer – kjente investorers porteføljer fra SEC (13F)
    gurus_payload = {}
    if cfg["gurus"].get("enabled", True) and cfg["gurus"].get("list"):
        try:
            names = {r["ticker"]: str(r["name"]) for r in table.to_dict(orient="records")}
            verd = {r["ticker"]: {"verdict": r.get("verdict"), "score": r.get("score"), "price": r.get("price")} for r in table.to_dict(orient="records")}
            gurus_payload = run_gurus(store, cfg, names, verdicts=verd, demo=args.demo)
            gp = Path(cfg["_root"]) / "docs" / "gurus.json"
            gp.write_text(json.dumps(gurus_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            log.info("Guruer: %d investorer, %d nye rapporter", len(gurus_payload.get("investors", [])), len(gurus_payload.get("alerts", [])))
        except Exception as e:  # noqa: BLE001
            import traceback
            log.exception("Guru-modulen feilet: %s", e)
            gp = Path(cfg["_root"]) / "docs" / "gurus.json"
            gp.write_text(json.dumps({"generated_at": date.today().isoformat(), "investors": [], "consensus": {"owned": [], "bought": [], "sold": []},
                                      "alerts": [], "errors": [{"fatal": repr(e)[:400], "trace": traceback.format_exc()[-2500:]}]}, ensure_ascii=False), encoding="utf-8")

    # Autotrader – virtuell portefølje som følger anbefalingene (egen fane i appen)
    auto = {}
    if cfg["autotrader"].get("enabled", True):
        try:
            auto = run_autotrader(store, table, cfg, fx)
            auto_path = Path(cfg["_root"]) / "docs" / "autotrader.json"
            auto_path.write_text(json.dumps(auto, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            if auto:
                log.info("Autotrader: verdi %.0f %s (%+.1f %%), %d posisjoner, %d handler totalt",
                         auto["total"], auto["base"], (auto["return_pct"] or 0) * 100, len(auto["holdings"]), auto["stats"]["n_trades"])
        except Exception as e:  # noqa: BLE001
            log.exception("Autotrader feilet: %s", e)

    skipped = [t for t in tickers if t not in prices]
    if skipped:
        log.warning("Hoppet over (ingen kursdata): %s", ", ".join(skipped))
    json_path = export_json(store, table, ideas, run_date, cfg, demo=args.demo, skipped=skipped, fx=fx, funds=funds_payload)

    # Kort oppsummering i terminalen
    print()
    print(f"=== Aksjeradar {run_date} {'(DEMO)' if args.demo else ''} ===")
    for _, r in table.head(int(cfg["report"]["top_n"])).iterrows():
        sc = "–" if r["score"] != r["score"] else f"{r['score']:.0f}"
        print(f"  {int(r['rank']):2d}. {r['ticker']:<10} {str(r['name'])[:24]:<24} score {sc:>3}")
    for key, title in CATEGORIES:
        n = len(ideas.get(key) or [])
        if n:
            print(f"  {title}: " + ", ".join(it["ticker"] for it in ideas[key]))
    if ideas.get("warnings"):
        print("  Varsler: " + ", ".join(it["ticker"] for it in ideas["warnings"]))
    print(f"\nRapport:    {html_path}")
    print(f"Mobil-app:  {json_path} (åpne docs/index.html, eller publiser via GitHub Pages)")
    print(f"Dashboard:  streamlit run dashboard.py")

    # ---------- 5. varsling ----------
    if not args.no_notify:
        if cfg["notify"].get("telegram"):
            send_telegram(render_telegram(table, ideas, run_date, demo=args.demo, funds=funds_payload))
        if cfg["notify"].get("email"):
            send_email(f"Aksjeradar {run_date}", render_html(md), md)

    # ---------- 6. push-varsler (ntfy) ----------
    pc = (cfg["notify"].get("push") or {})
    if not args.no_notify and push_settings(cfg):
        if pc.get("morning", True):
            lines = []
            if pc.get("stocks", False):
                buys = [r for _, r in table.head(30).iterrows() if r.get("verdict") in ("Sterkt kjøp", "Kjøp")][:3]
                if buys:
                    lines.append("Kjøp: " + ", ".join(f"{r['ticker']} ({r['score']:.0f})" for r in buys))
                vc = {v: int((table["verdict"] == v).sum()) for v in ("Sterkt kjøp", "Kjøp", "Avvent", "Unngå")}
                lines.append(f"{vc['Sterkt kjøp'] + vc['Kjøp']} kjøp · {vc['Avvent']} avvent · {vc['Unngå']} unngå · {len(ideas.get('warnings') or [])} varsler")
            mine = [f for f in (funds_payload.get("funds") or []) if f.get("owned") and f.get("deposit")]
            short = {"boost": "ekstrainnskudd anbefales", "consider": "vurder ekstrainnskudd", "regular": "vanlig sparing", "wait": "avvent"}
            for f in mine[:6]:
                d = f["deposit"]
                lines.append(f"{'★ ' if d['code'] in ('boost', 'consider') else ''}{f['name'][:26]}: {short.get(d['code'], d['code'])} ({f['dd_52w'] * 100:+.0f} % fra topp)")
            good = [f for f in (funds_payload.get("funds") or []) if f["level"] in ("Gunstig", "Svært gunstig") and not f.get("owned")]
            if good:
                lines.append("Andre fond gunstig: " + ", ".join(f"{f['name'][:22]} ({f['dd_52w'] * 100:+.0f} %)" for f in good[:3]))
            if not mine:
                topf = [f for f in (funds_payload.get("funds") or []) if f.get("rank")][:3]
                if topf:
                    lines.append("Fond topp 3: " + ", ".join(f"{f['name'][:22]} ({f['attr_score']:.0f})" for f in topf))
            if auto and auto.get("traded_today"):
                todays = [t for t in auto.get("trades", []) if t.get("date") == auto.get("price_date")]
                if todays:
                    lines.append("Autotrader: " + ", ".join(f"{'kjøpte' if t['kind'] == 'buy' else 'solgte'} {t['ticker']}" for t in todays[:6]))
            if auto:
                lines.append(f"Autotrader {auto['return_pct'] * 100:+.1f} % · marked {auto['bench_return_pct'] * 100:+.1f} %")
            n_act = sum(1 for f in mine if f["deposit"]["code"] in ("boost", "consider"))
            send_push(cfg, f"Fondene dine {run_date}" + (f" – {n_act} med gunstig inngang" if n_act else ""), "\n".join(lines),
                      tags=["moneybag" if n_act else "satellite"], priority=4 if n_act else 3)
        if pc.get("funds", True):
            for a in (funds_payload.get("alerts") or []):
                if a["kind"] == "innskudd":
                    send_push(cfg, "Fond: nytt råd – " + a.get("code", "").replace("boost", "ekstrainnskudd anbefales").replace("consider", "vurder ekstrainnskudd"),
                              a["text"] + "\nÅpne appen → Mer → Fond for hele analysen.", tags=["moneybag"], priority=4)
                elif a["kind"] == "innskudd_slutt":
                    send_push(cfg, "Fond: rådet er endret", a["text"], tags=["white_check_mark"], priority=3)
                else:
                    send_push(cfg, "Fond: " + ("gunstig inngang" if a["kind"] == "inngang" else "ikke lenger gunstig"), a["text"],
                              tags=["moneybag" if a["kind"] == "inngang" else "white_check_mark"], priority=4 if a["kind"] == "inngang" else 3)
        if pc.get("gurus", True):
            for a in (gurus_payload.get("alerts") or []):
                send_push(cfg, "Ny 13F: " + a["name"], a["text"], tags=["crown"])
        if pc.get("autotrader", True) and auto and auto.get("traded_today"):
            todays = [t for t in auto.get("trades", []) if t.get("date") == auto.get("price_date")]
            for t in todays[:8]:
                send_push(cfg, f"Autotrader {'kjøpte' if t['kind'] == 'buy' else 'solgte'} {t['ticker']}",
                          f"{t['shares']} stk à {t['price']:.2f} {t.get('currency') or ''} · {t.get('reason') or ''}"
                          + (f" · {t['pnl']:+.0f} kr" if t.get('pnl') is not None else ""), tags=["robot"])

    log.info("Ferdig på %.0f sek.", time.time() - t0)
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
