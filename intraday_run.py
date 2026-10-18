#!/usr/bin/env python3
"""
Intradag-kjøring – hvert 15. minutt i børstiden (GitHub Actions: .github/workflows/intraday.yml).

    python intraday_run.py                 # henter 15m-kurser, lager setups, skriver docs/intraday.json
    python intraday_run.py --site site     # skriv til en annen mappe (workflowen bruker den nedlastede nettsiden)
    python intraday_run.py --demo          # syntetiske 15m-kurser, ingen nettverk

Universet: listene under `intraday.universe` i config.yaml + dagens kjøpskandidater (fra data.json)
+ autotraderens beholdning (fra autotrader.json), inntil `intraday.max_tickers`.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from aksjeradar.config import load_config, market_of
from aksjeradar.intraday import MARKETS, run_intraday, setup_id
from aksjeradar.notify import push_settings, send_push
from aksjeradar.storage import Storage

log = logging.getLogger("aksjeradar")


def intraday_universe(cfg: dict, site: Path) -> tuple[list[str], dict[str, str]]:
    icfg = cfg["intraday"]
    tickers: list[str] = []
    for group in (icfg.get("universe") or {}).values():
        tickers += [str(t).strip().upper() for t in (group or [])]
    names: dict[str, str] = {}
    data_path = site / "data.json"
    if data_path.exists():
        try:
            d = json.loads(data_path.read_text(encoding="utf-8"))
            for s in d.get("stocks", []):
                names[s["ticker"]] = s.get("name") or s["ticker"]
            if icfg.get("include_buy_candidates", True):
                tickers += [s["ticker"] for s in d.get("stocks", []) if s.get("verdict") in ("Sterkt kjøp", "Kjøp")]
        except Exception as e:  # noqa: BLE001
            log.warning("Kunne ikke lese %s: %s", data_path, e)
    auto_path = site / "autotrader.json"
    if auto_path.exists() and icfg.get("include_autotrader_holdings", True):
        try:
            a = json.loads(auto_path.read_text(encoding="utf-8"))
            tickers += [h["ticker"] for h in a.get("holdings", [])]
        except Exception as e:  # noqa: BLE001
            log.warning("Kunne ikke lese %s: %s", auto_path, e)
    seen, out = set(), []
    for t in tickers:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[: int(icfg.get("max_tickers", 120))], names


def demo_frames(tickers: list[str], now_utc: datetime, seed: int = 3) -> dict[str, pd.DataFrame]:
    """Fem dager med syntetiske 15m-barer per aksje, med noen innbakte setups."""
    rng = np.random.default_rng(seed)
    out = {}
    for i, t in enumerate(tickers):
        m = MARKETS[market_of(t)]
        tz = ZoneInfo(m["tz"])
        today = now_utc.astimezone(tz).date()
        days = []
        d = today
        while len(days) < 5:
            if d.weekday() < 5:
                days.append(d)
            d -= timedelta(days=1)
        days.reverse()
        price = 100 * rng.uniform(0.5, 4)
        rows, idx = [], []
        for di, day in enumerate(days):
            t0 = datetime.combine(day, m["open"], tzinfo=tz)
            t_end = datetime.combine(day, m["close"], tzinfo=tz)
            if di == len(days) - 1:
                t_end = min(t_end, now_utc.astimezone(tz))
            gap = rng.normal(0, 0.01) if di < 4 else (0.035 if i % 4 == 0 else rng.normal(0, 0.008))
            price *= 1 + gap
            t_ = t0
            k = 0
            while t_ < t_end:
                drift = 0.0015 if (di == 4 and i % 4 in (0, 1)) else 0.0
                r = rng.normal(drift, 0.003)
                o = price
                c = price * (1 + r)
                h = max(o, c) * (1 + abs(rng.normal(0, 0.0015)))
                lo = min(o, c) * (1 - abs(rng.normal(0, 0.0015)))
                v = rng.lognormal(11, 0.3) * (2.2 if (di == 4 and i % 4 in (0, 1)) else 1.0) * (1.5 if k < 2 else 1.0)
                rows.append((o, h, lo, c, v))
                idx.append(t_)
                price = c
                t_ += timedelta(minutes=15)
                k += 1
        out[t] = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"], index=pd.DatetimeIndex(idx))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Aksjeradar – intradag")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--site", default=None, help="mappe med data.json/autotrader.json; intraday.json skrives her (standard: docs/)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("yfinance").setLevel(logging.ERROR)

    cfg = load_config()
    if not cfg["intraday"].get("enabled", True):
        log.info("Intradag er slått av i config.yaml.")
        return 0
    site = Path(args.site).resolve() if args.site else Path(cfg["_root"]) / "docs"
    site.mkdir(parents=True, exist_ok=True)
    store = Storage(cfg["data"]["db_path"])
    tickers, names = intraday_universe(cfg, site)
    log.info("Intradag-univers: %d aksjer", len(tickers))

    if args.demo:
        os.environ["AKSJERADAR_NO_FETCH"] = "1"
        now = datetime.now(timezone.utc)
        # legg "nå" midt i en handelsdag i Oslo, så det finnes åpne markeder
        oslo = now.astimezone(ZoneInfo("Europe/Oslo"))
        if oslo.weekday() >= 5 or not (9 <= oslo.hour < 16):
            days_back = (oslo.weekday() - 4) if oslo.weekday() >= 5 else 0
            oslo = (oslo - timedelta(days=days_back)).replace(hour=13, minute=0, second=0, microsecond=0)
            now = oslo.astimezone(timezone.utc)
        tickers = tickers[:24]
        payload = run_intraday(store, tickers, cfg, frames=demo_frames(tickers, now), now_utc=now, names=names)
        payload["demo"] = True
    else:
        payload = run_intraday(store, tickers, cfg, names=names)

    # Push-varsel for nye setups (tak per dag), ikke i demo
    pc = (cfg["notify"].get("push") or {})
    if not args.demo and pc.get("intraday", True) and push_settings(cfg):
        maxn = int(pc.get("max_intraday_per_day", 6))
        today_keys = [k for k, v in payload["log"].items() if v.get("session") == datetime.now(timezone.utc).strftime("%Y-%m-%d")]
        sent_today = sum(1 for k in today_keys if payload["log"][k].get("pushed"))
        for s_ in payload["setups"]:
            if sent_today >= maxn:
                break
            if s_.get("first_seen") != s_.get("seen_at"):
                continue  # ikke nytt i denne kjøringen
            k = setup_id(s_)
            if payload["log"].get(k, {}).get("pushed"):
                continue
            ok = send_push(cfg, f"Intradag: {s_['ticker']} – {s_['type_label']} (score {s_['score']})",
                           f"Inngang {s_['entry']:.2f} · stop {s_['stop']:.2f} ({s_['stop_pct'] * 100:+.1f} %) · mål {s_['target']:.2f} ({s_['target_pct'] * 100:+.1f} %)\n"
                           + " · ".join(s_.get("why") or []) + f"\nGyldig til stenging. Kurser ca. 15 min forsinket.", tags=["zap"])
            if ok:
                payload["log"][k]["pushed"] = True
                sent_today += 1
        store.save_snapshot("intraday", "log", {"setups": payload["log"]})

    out = site / "intraday.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Intradag: {len(payload['setups'])} setups, {payload['universe']} aksjer -> {out}")
    for s in payload["setups"][:8]:
        print(f"  {s['type_label']:<14} {s['ticker']:<10} score {s['score']:>3}  inngang {s['entry']:.2f}  stop {s['stop']:.2f} ({s['stop_pct']*100:+.1f} %)  mål {s['target']:.2f} ({s['target_pct']*100:+.1f} %)")
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
