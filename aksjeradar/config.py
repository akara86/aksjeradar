"""
Laster innstillinger fra config.yaml og hemmeligheter fra .env.

config.yaml  -> hvilke aksjer som følges, terskler for signaler, vekting av score
.env         -> Telegram-token, e-postpassord o.l. (skal ALDRI deles eller legges på GitHub)
"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Rotmappen til prosjektet (mappen som inneholder config.yaml)
ROOT = Path(__file__).resolve().parent.parent

# Standardverdier – brukes hvis noe mangler i config.yaml
DEFAULTS = {
    "universe": {},
    "data": {
        "history_period": "2y",          # hvor lang kurshistorikk som hentes
        "fundamentals_max_age_days": 2,  # hvor gamle fundamentaldata kan være før de hentes på nytt
        "db_path": "data/aksjeradar.db",
    },
    "signals": {
        "rsi_period": 14,
        "sma_fast": 50,
        "sma_slow": 200,
        "volume_spike_mult": 2.0,
        "breakout_lookback": 60,
    },
    "scoring": {
        "weights": {
            "technical": 0.35,
            "analyst": 0.25,
            "fundamental": 0.25,
            "insider": 0.15,
        },
        "min_analysts": 3,
    },
    "report": {
        "top_n": 10,
        "per_category": 5,
        "screener_rows": 40,
        "output_dir": "reports",
    },
    "notify": {
        "telegram": True,
        "email": False,
    },
    "export": {
        "json_path": "docs/data.json",  # datafilen mobil-appen leser
        "history_days": 130,            # kursdager som tas med i grafen
    },
}


def _merge(base: dict, override: dict) -> dict:
    """Slår sammen to oppslagsverk – verdier i `override` vinner."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None = None) -> dict:
    """Leser config.yaml (og .env) og returnerer en ferdig innstillingsstruktur."""
    load_dotenv(ROOT / ".env")  # gjør TELEGRAM_BOT_TOKEN osv. tilgjengelig via os.getenv
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    user_cfg = {}
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, user_cfg)
    cfg["_root"] = str(ROOT)
    # Gjør relative stier absolutte, slik at scriptet kan kjøres fra hvor som helst
    cfg["data"]["db_path"] = str((ROOT / cfg["data"]["db_path"]).resolve())
    cfg["report"]["output_dir"] = str((ROOT / cfg["report"]["output_dir"]).resolve())
    return cfg


def all_tickers(cfg: dict) -> list[str]:
    """Alle tickere fra alle grupper i config, uten duplikater."""
    seen: set[str] = set()
    out: list[str] = []
    for group in (cfg.get("universe") or {}).values():
        for t in group or []:
            t = str(t).strip().upper()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


def market_of(ticker: str) -> str:
    """Hvilken børs tickeren hører til, basert på suffikset Yahoo bruker."""
    t = ticker.upper()
    if t.endswith(".OL"):
        return "Oslo"
    if t.endswith(".ST"):
        return "Stockholm"
    if t.endswith(".CO"):
        return "København"
    if t.endswith(".HE"):
        return "Helsinki"
    return "USA"
