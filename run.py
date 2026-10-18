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
import logging
import sys
import time
from datetime import date

from aksjeradar.config import all_tickers, load_config
from aksjeradar.data import FX_DEMO, demo_details, demo_prices, fetch_details, fetch_fx, fetch_prices
from aksjeradar.export import export_json
from aksjeradar.notify import send_email, send_telegram
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
    skipped = [t for t in tickers if t not in prices]
    if skipped:
        log.warning("Hoppet over (ingen kursdata): %s", ", ".join(skipped))
    json_path = export_json(store, table, ideas, run_date, cfg, demo=args.demo, skipped=skipped, fx=fx)

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
            send_telegram(render_telegram(table, ideas, run_date, demo=args.demo))
        if cfg["notify"].get("email"):
            send_email(f"Aksjeradar {run_date}", render_html(md), md)

    log.info("Ferdig på %.0f sek.", time.time() - t0)
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
