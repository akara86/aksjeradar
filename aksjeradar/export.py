"""
Eksporterer resultatet av en kjøring til én JSON-fil (docs/data.json).

Mobil-appen i docs/ leser denne filen. Den inneholder alt appen trenger:
score og nøkkeltall per aksje, idékategoriene, kort kurshistorikk (for grafen),
opp-/nedgraderinger og innsidehandler.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .signals import compute_indicators
from .storage import Storage, clean_for_json

log = logging.getLogger("aksjeradar.export")

# Kolonner fra score-tabellen som tas med per aksje
STOCK_COLUMNS = [
    "ticker", "name", "market", "sector", "currency", "market_cap", "rank",
    "price", "change_1d", "last_date",
    "verdict", "verdict_reasons", "risk", "coverage",
    "score", "score_technical", "score_analyst", "score_fundamental", "score_insider",
    "rsi", "ret_1m", "ret_3m", "ret_6m", "ret_12m", "pct_from_52w_high", "dist_sma_slow",
    "above_sma_fast", "above_sma_slow", "fast_gt_slow", "golden_cross", "death_cross",
    "broke_below_slow", "macd_hist", "macd_cross_up", "macd_cross_down", "breakout",
    "near_52w_high", "volume_spike", "volume_ratio", "oversold", "overbought", "atr_pct",
    "n_analysts", "rec_mean", "rec_key", "target_mean", "upside",
    "upgrades_30d", "upgrades_90d", "downgrades_90d", "last_upgrade",
    "trailingPE", "forwardPE", "enterpriseToEbitda", "trailingPegRatio", "priceToBook",
    "revenueGrowth", "earningsGrowth", "profitMargins", "returnOnEquity", "debtToEquity",
    "dividendYield", "fcf_yield", "beta",
    "insider_buys", "insider_sells", "insider_buy_value", "insider_sell_value", "insider_buys_90d",
]


def _round(v, nd: int = 4):
    if isinstance(v, float):
        return round(v, nd)
    return v


def export_json(store: Storage, table: pd.DataFrame, ideas: dict, run_date: str, cfg: dict,
                demo: bool = False, skipped: list[str] | None = None) -> Path:
    out_path = Path(cfg["_root"]) / cfg["export"]["json_path"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    history_days = int(cfg["export"].get("history_days", 130))
    scfg = cfg["signals"]

    # Forrige kjøring – for å vise endring i score og plassering
    prev: dict[str, dict] = {}
    dates = [d for d in store.run_dates() if d < run_date]
    prev_date = dates[0] if dates else None
    if prev_date:
        pdf = store.load_scores(prev_date)
        for rec in pdf.to_dict(orient="records"):
            prev[rec["ticker"]] = rec

    stocks = []
    for rec in table.to_dict(orient="records"):
        t = rec["ticker"]
        s = {k: _round(clean_for_json(rec.get(k))) for k in STOCK_COLUMNS if k in rec}
        p = prev.get(t)
        s["score_prev"] = _round(clean_for_json(p.get("score"))) if p else None
        s["rank_prev"] = clean_for_json(p.get("rank")) if p else None

        # Kort kurshistorikk med glidende snitt (for grafen i appen)
        hist = store.load_prices(t)
        if not hist.empty:
            ind = compute_indicators(hist, scfg["rsi_period"], scfg["sma_fast"], scfg["sma_slow"]).tail(history_days)
            s["history"] = {
                "dates": [d.strftime("%Y-%m-%d") for d in ind.index],
                "close": [round(float(x), 2) for x in ind["Close"]],
                "sma_fast": [None if pd.isna(x) else round(float(x), 2) for x in ind["sma_fast"]],
                "sma_slow": [None if pd.isna(x) else round(float(x), 2) for x in ind["sma_slow"]],
            }
        snap, _ = store.load_snapshot("details", t)
        snap = snap or {}
        s["upgrades"] = (snap.get("upgrades") or [])[:10]
        s["insider"] = (snap.get("insider") or [])[:15]
        stocks.append(s)

    payload = {
        "app": "Aksjeradar",
        "run_date": run_date,
        "prev_run_date": prev_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "demo": bool(demo),
        "universe": len(stocks),
        "skipped": skipped or [],
        "verdict_counts": {v: int((table["verdict"] == v).sum()) for v in ["Sterkt kjøp", "Kjøp", "Hold", "Avvent", "Unngå"]} if "verdict" in table else {},
        "weights": cfg["scoring"]["weights"],
        "ideas": clean_for_json(ideas),
        "stocks": stocks,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Eksporterte %s (%.0f kB)", out_path, out_path.stat().st_size / 1024)
    return out_path
