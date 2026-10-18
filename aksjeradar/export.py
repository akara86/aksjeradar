"""
Eksporterer resultatet av en kjøring til mobil-appen:

  docs/data.json           – lett indeks med alle aksjer (score, anbefaling, nøkkeltall, liten kursgraf)
  docs/stocks/<TICKER>.json – detaljer per aksje (full kurshistorikk, opp-/nedgraderinger, innsidehandler)

Appen leser indeksen ved oppstart og henter detaljfilen først når du åpner en aksje.
Slik holder appen seg rask selv med mange hundre aksjer.
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

# Felter i indeksen (det appen trenger for lister, søk og kort)
INDEX_COLUMNS = [
    "ticker", "name", "market", "sector", "currency", "market_cap", "rank",
    "price", "change_1d", "last_date",
    "verdict", "verdict_reasons", "risk", "coverage",
    "score", "score_technical", "score_analyst", "score_fundamental", "score_insider",
    "rsi", "ret_1m", "ret_3m", "ret_6m", "ret_12m", "pct_from_52w_high",
    "above_sma_fast", "above_sma_slow", "fast_gt_slow", "golden_cross", "death_cross", "broke_below_slow",
    "macd_hist", "macd_cross_up", "breakout", "near_52w_high", "volume_spike", "oversold", "overbought",
    "n_analysts", "rec_mean", "rec_key", "target_mean", "upside", "upgrades_30d", "upgrades_90d", "downgrades_90d",
    "forwardPE", "trailingPE", "dividendYield", "insider_buys_90d",
]

# Ekstra felter som bare ligger i detaljfilen
DETAIL_COLUMNS = INDEX_COLUMNS + [
    "dist_sma_slow", "macd_cross_down", "volume_ratio", "atr_pct", "last_upgrade",
    "enterpriseToEbitda", "trailingPegRatio", "priceToBook", "revenueGrowth", "earningsGrowth",
    "profitMargins", "operatingMargins", "returnOnEquity", "debtToEquity", "fcf_yield", "beta",
    "insider_buys", "insider_sells", "insider_buy_value", "insider_sell_value",
]


def _round(v, nd: int = 4):
    if isinstance(v, float):
        return round(v, nd)
    return v


def _pick(rec: dict, cols: list[str]) -> dict:
    return {k: _round(clean_for_json(rec.get(k))) for k in cols if k in rec}


def export_json(store: Storage, table: pd.DataFrame, ideas: dict, run_date: str, cfg: dict,
                demo: bool = False, skipped: list[str] | None = None, fx: dict | None = None, funds: dict | None = None) -> Path:
    index_path = Path(cfg["_root"]) / cfg["export"]["json_path"]
    details_dir = Path(cfg["export"]["details_dir"])
    index_path.parent.mkdir(parents=True, exist_ok=True)
    details_dir.mkdir(parents=True, exist_ok=True)
    history_days = int(cfg["export"].get("history_days", 130))
    spark_days = int(cfg["export"].get("spark_days", 30))
    scfg = cfg["signals"]

    # Forrige kjøring – for å vise endring i score og plassering
    prev: dict[str, dict] = {}
    dates = [d for d in store.run_dates() if d < run_date]
    prev_date = dates[0] if dates else None
    if prev_date:
        for rec in store.load_scores(prev_date).to_dict(orient="records"):
            prev[rec["ticker"]] = rec

    index = []
    written = set()
    for rec in table.to_dict(orient="records"):
        t = rec["ticker"]
        p = prev.get(t)
        entry = _pick(rec, INDEX_COLUMNS)
        entry["score_prev"] = _round(clean_for_json(p.get("score"))) if p else None
        entry["rank_prev"] = clean_for_json(p.get("rank")) if p else None

        detail = _pick(rec, DETAIL_COLUMNS)
        detail["score_prev"] = entry["score_prev"]
        detail["rank_prev"] = entry["rank_prev"]

        hist = store.load_prices(t)
        if not hist.empty:
            ind = compute_indicators(hist, scfg["rsi_period"], scfg["sma_fast"], scfg["sma_slow"]).tail(history_days)
            closes = [round(float(x), 2) for x in ind["Close"]]
            entry["spark"] = closes[-spark_days:]
            detail["history"] = {
                "dates": [d.strftime("%Y-%m-%d") for d in ind.index],
                "close": closes,
                "sma_fast": [None if pd.isna(x) else round(float(x), 2) for x in ind["sma_fast"]],
                "sma_slow": [None if pd.isna(x) else round(float(x), 2) for x in ind["sma_slow"]],
            }
        snap, _ = store.load_snapshot("details", t)
        snap = snap or {}
        detail["upgrades"] = (snap.get("upgrades") or [])[:10]
        detail["insider"] = (snap.get("insider") or [])[:15]
        detail["run_date"] = run_date

        safe = t.replace("/", "_")
        (details_dir / f"{safe}.json").write_text(json.dumps(detail, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        written.add(f"{safe}.json")
        index.append(entry)

    # Rydd bort detaljfiler for aksjer som ikke lenger er med
    for old in details_dir.glob("*.json"):
        if old.name not in written:
            old.unlink()

    payload = {
        "app": "Aksjeradar",
        "run_date": run_date,
        "prev_run_date": prev_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "demo": bool(demo),
        "universe": len(index),
        "skipped": skipped or [],
        "fx": fx or {},  # kurs mot NOK, f.eks. {"USD": 10.6}
        "funds": funds or {},
        "verdict_counts": {v: int((table["verdict"] == v).sum()) for v in ["Sterkt kjøp", "Kjøp", "Hold", "Avvent", "Unngå"]} if "verdict" in table else {},
        "weights": cfg["scoring"]["weights"],
        "ideas": clean_for_json(ideas),
        "stocks": index,
    }
    index_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Eksporterte %s (%.0f kB) og %d detaljfiler i %s", index_path, index_path.stat().st_size / 1024, len(written), details_dir)
    return index_path
