"""
Datainnhenting fra Yahoo Finance (gratis, via biblioteket yfinance).

Alt her er skrevet "defensivt": hvis Yahoo mangler data for en aksje, eller
nettverket hoster, logger vi en advarsel og går videre – kjøringen skal ikke stoppe.

I tillegg finnes det en demo-modus som lager syntetiske data uten nettverk,
slik at du kan se hvordan verktøyet fungerer før du henter ekte data.
"""
from __future__ import annotations

import logging
import zlib
from datetime import datetime

import numpy as np
import pandas as pd

log = logging.getLogger("aksjeradar.data")

# Feltene vi henter fra Yahoo sin "info"-blokk per aksje
INFO_KEYS = [
    # Identitet
    "shortName", "longName", "sector", "industry", "currency", "marketCap", "currentPrice",
    # Verdsettelse og kvalitet
    "trailingPE", "forwardPE", "enterpriseToEbitda", "trailingPegRatio", "priceToBook",
    "revenueGrowth", "earningsGrowth", "profitMargins", "operatingMargins", "returnOnEquity",
    "debtToEquity", "freeCashflow", "dividendYield", "beta",
    # Analytikerkonsensus
    "recommendationMean", "recommendationKey", "numberOfAnalystOpinions",
    "targetMeanPrice", "targetMedianPrice", "targetHighPrice", "targetLowPrice",
]

ANALYST_KEYS = [
    "recommendationMean", "recommendationKey", "numberOfAnalystOpinions",
    "targetMeanPrice", "targetMedianPrice", "targetHighPrice", "targetLowPrice",
]


def _num(x):
    """Gjør om til float – eller None hvis verdien ikke er et brukbart tall."""
    try:
        if x is None:
            return None
        v = float(x)
        if np.isnan(v) or np.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _to_naive(ts) -> pd.Timestamp | None:
    """Dato uten tidssone (yfinance blander tidssoner)."""
    try:
        t = pd.to_datetime(ts, errors="coerce", utc=True)
        if pd.isna(t):
            return None
        return t.tz_localize(None).normalize()
    except Exception:
        return None


# --------------------------------------------------------------------------
# Kurser
# --------------------------------------------------------------------------
def fetch_prices(tickers: list[str], period: str = "2y", batch_size: int = 40) -> dict[str, pd.DataFrame]:
    """Henter daglige kurser for mange aksjer i batcher. Returnerer {ticker: DataFrame}."""
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), batch_size):
        chunk = tickers[i:i + batch_size]
        try:
            raw = yf.download(
                chunk, period=period, interval="1d", group_by="ticker",
                auto_adjust=True, threads=True, progress=False,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Kursnedlasting feilet for %s: %s", chunk, e)
            continue
        if raw is None or raw.empty:
            log.warning("Ingen kursdata returnert for %s", chunk)
            continue

        for t in chunk:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    if t not in raw.columns.get_level_values(0):
                        continue
                    df = raw[t]
                else:
                    df = raw
                df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                df = df.dropna(subset=["Close"])
                df.index = pd.to_datetime(df.index)
                if getattr(df.index, "tz", None) is not None:
                    df.index = df.index.tz_localize(None)
                df = df[~df.index.duplicated(keep="last")].sort_index()
            except Exception as e:  # noqa: BLE001
                log.warning("Kunne ikke tolke kursdata for %s: %s", t, e)
                continue
            if len(df) < 60:
                log.warning("For lite kurshistorikk for %s (%d dager) – hoppes over", t, len(df))
                continue
            out[t] = df
    return out


# --------------------------------------------------------------------------
# Valutakurser (til NOK) – brukes til å summere porteføljer i appen
# --------------------------------------------------------------------------
FX_PAIRS = {"USD": "USDNOK=X", "SEK": "SEKNOK=X", "DKK": "DKKNOK=X", "EUR": "EURNOK=X"}
FX_DEMO = {"NOK": 1.0, "USD": 10.6, "SEK": 1.02, "DKK": 1.55, "EUR": 11.6}


def fetch_fx() -> dict[str, float]:
    """Siste kurs for USD, SEK, DKK og EUR mot NOK. Tom dict ved feil."""
    import yfinance as yf

    out: dict[str, float] = {"NOK": 1.0}
    try:
        raw = yf.download(list(FX_PAIRS.values()), period="5d", interval="1d", group_by="ticker",
                          auto_adjust=True, threads=True, progress=False)
        for cur, pair in FX_PAIRS.items():
            try:
                series = raw[pair]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
                v = _num(series.dropna().iloc[-1])
                if v:
                    out[cur] = round(v, 4)
            except Exception:  # noqa: BLE001
                continue
    except Exception as e:  # noqa: BLE001
        log.warning("Valutakurser feilet: %s", e)
    return out if len(out) > 1 else {}


# --------------------------------------------------------------------------
# Fundamentaldata, analytikere, innsidehandler (én aksje om gangen)
# --------------------------------------------------------------------------
def fetch_details(ticker: str) -> dict:
    """Henter info-blokk, opp-/nedgraderinger og innsidehandler for én aksje."""
    import yfinance as yf

    tk = yf.Ticker(ticker)
    info: dict = {}
    try:
        info = tk.info or {}
    except Exception as e:  # noqa: BLE001
        log.warning("info feilet for %s: %s", ticker, e)

    fundamentals = {}
    for k in INFO_KEYS:
        v = info.get(k)
        fundamentals[k] = v if isinstance(v, str) else _num(v)
    analyst = {k: fundamentals.get(k) for k in ANALYST_KEYS}

    return {
        "fundamentals": fundamentals,
        "analyst": analyst,
        "upgrades": _fetch_upgrades(tk, ticker),
        "insider": _fetch_insider(tk, ticker),
        "fetched_at": datetime.now().strftime("%Y-%m-%d"),
    }


def _fetch_upgrades(tk, ticker: str, days: int = 120) -> list[dict]:
    """Analytikeres opp- og nedgraderinger siste `days` dager (mest komplett for USA)."""
    try:
        ud = tk.upgrades_downgrades
    except Exception as e:  # noqa: BLE001
        log.debug("upgrades_downgrades feilet for %s: %s", ticker, e)
        return []
    if ud is None or len(ud) == 0:
        return []
    try:
        ud = ud.reset_index()
        date_col = "GradeDate" if "GradeDate" in ud.columns else ud.columns[0]
        cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
        out = []
        for _, r in ud.iterrows():
            d = _to_naive(r[date_col])
            if d is None or d < cutoff:
                continue
            out.append({
                "date": d.strftime("%Y-%m-%d"),
                "firm": str(r.get("Firm", "") or ""),
                "to": str(r.get("ToGrade", "") or ""),
                "from": str(r.get("FromGrade", "") or ""),
                "action": str(r.get("Action", "") or "").lower(),  # up / down / main / init / reit
            })
        out.sort(key=lambda x: x["date"], reverse=True)
        return out[:30]
    except Exception as e:  # noqa: BLE001
        log.debug("Kunne ikke tolke upgrades for %s: %s", ticker, e)
        return []


def _fetch_insider(tk, ticker: str, days: int = 180) -> list[dict]:
    """Innsidehandler (kjøp/salg) siste `days` dager, der Yahoo har data."""
    try:
        ins = tk.insider_transactions
    except Exception as e:  # noqa: BLE001
        log.debug("insider_transactions feilet for %s: %s", ticker, e)
        return []
    if ins is None or len(ins) == 0:
        return []
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
    out = []
    try:
        for _, r in ins.iterrows():
            text = f"{r.get('Text', '')} {r.get('Transaction', '')}".lower()
            if "purchase" in text or "buy" in text or "acquisition" in text:
                kind = "buy"
            elif "sale" in text or "sell" in text or "disposition" in text:
                kind = "sell"
            else:
                continue  # opsjonsutøvelser, gaver o.l. ignoreres
            d = _to_naive(r.get("Start Date"))
            if d is None or d < cutoff:
                continue
            out.append({
                "date": d.strftime("%Y-%m-%d"),
                "kind": kind,
                "insider": str(r.get("Insider", "") or ""),
                "position": str(r.get("Position", "") or ""),
                "shares": _num(r.get("Shares")),
                "value": _num(r.get("Value")),
            })
        out.sort(key=lambda x: x["date"], reverse=True)
        return out[:40]
    except Exception as e:  # noqa: BLE001
        log.debug("Kunne ikke tolke insider for %s: %s", ticker, e)
        return []


# --------------------------------------------------------------------------
# Demo-data (ingen nettverk)
# --------------------------------------------------------------------------
_DEMO_NAMES = {
    "EQNR.OL": "Equinor", "DNB.OL": "DNB Bank", "MOWI.OL": "Mowi", "YAR.OL": "Yara",
    "NHY.OL": "Norsk Hydro", "TEL.OL": "Telenor", "AKRBP.OL": "Aker BP", "KOG.OL": "Kongsberg Gruppen",
    "ORK.OL": "Orkla", "SALM.OL": "SalMar", "VOLV-B.ST": "Volvo B", "NOVO-B.CO": "Novo Nordisk",
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AMZN": "Amazon",
    "GOOGL": "Alphabet", "META": "Meta Platforms", "TSLA": "Tesla", "JPM": "JPMorgan",
}
_SECTORS = ["Energy", "Financial Services", "Technology", "Healthcare", "Industrials",
            "Consumer Defensive", "Basic Materials", "Communication Services"]


def demo_prices(tickers: list[str], days: int = 520, seed: int = 7) -> dict[str, pd.DataFrame]:
    """Lager tilfeldige, men realistisk utseende kursserier."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    out = {}
    for t in tickers:
        drift = rng.normal(0.0003, 0.0008)
        vol = rng.uniform(0.012, 0.03)
        rets = rng.normal(drift, vol, days)
        rets[-60:] += rng.normal(0, 0.0025)        # gir noen aksjer en tydelig trend sist
        close = 100 * rng.uniform(0.3, 6) * np.exp(np.cumsum(rets))
        open_ = close * (1 + rng.normal(0, 0.004, days))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, days)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, days)))
        volume = rng.lognormal(13, 0.35, days)
        if rng.random() < 0.3:
            volume[-1] *= rng.uniform(2, 3.5)       # volumhopp hos noen
        out[t] = pd.DataFrame(
            {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates
        )
    return out


def demo_details(ticker: str, price: float, seed: int = 7) -> dict:
    """Lager tilfeldige fundamentaldata, analytikerkonsensus og innsidehandler."""
    rng = np.random.default_rng(zlib.crc32(f"{ticker}:{seed}".encode()))
    usa = "." not in ticker
    n_analysts = int(rng.integers(0, 35 if usa else 14))
    rec_mean = float(np.clip(rng.normal(2.3, 0.6), 1.0, 4.5)) if n_analysts else None
    upside = float(rng.normal(0.12, 0.18))
    mcap = float(price * rng.uniform(2e7, 5e9))
    fundamentals = {
        "shortName": _DEMO_NAMES.get(ticker, ticker.split(".")[0].title()),
        "longName": _DEMO_NAMES.get(ticker, ticker),
        "sector": str(rng.choice(_SECTORS)),
        "industry": "Demo",
        "currency": "USD" if usa else {"OL": "NOK", "ST": "SEK", "CO": "DKK", "HE": "EUR"}.get(ticker.split(".")[-1], "NOK"),
        "marketCap": mcap,
        "currentPrice": price,
        "trailingPE": float(rng.choice([rng.uniform(6, 45), -5.0], p=[0.85, 0.15])),
        "forwardPE": float(rng.uniform(7, 35)),
        "enterpriseToEbitda": float(rng.uniform(4, 30)),
        "trailingPegRatio": float(rng.uniform(0.5, 3.5)),
        "priceToBook": float(rng.uniform(0.8, 12)),
        "revenueGrowth": float(rng.normal(0.08, 0.15)),
        "earningsGrowth": float(rng.normal(0.10, 0.3)),
        "profitMargins": float(rng.normal(0.12, 0.1)),
        "operatingMargins": float(rng.normal(0.15, 0.1)),
        "returnOnEquity": float(rng.normal(0.15, 0.12)),
        "debtToEquity": float(abs(rng.normal(60, 50))),
        "freeCashflow": float(mcap * rng.normal(0.04, 0.03)),
        "dividendYield": float(abs(rng.normal(0.02, 0.02))),
        "beta": float(rng.uniform(0.5, 1.8)),
        "recommendationMean": rec_mean,
        "recommendationKey": None if rec_mean is None else ("buy" if rec_mean < 2.5 else "hold" if rec_mean < 3.5 else "sell"),
        "numberOfAnalystOpinions": n_analysts,
        "targetMeanPrice": price * (1 + upside) if n_analysts else None,
        "targetMedianPrice": price * (1 + upside * 0.9) if n_analysts else None,
        "targetHighPrice": price * (1 + upside + 0.2) if n_analysts else None,
        "targetLowPrice": price * (1 + upside - 0.2) if n_analysts else None,
    }
    analyst = {k: fundamentals[k] for k in ANALYST_KEYS}

    today = pd.Timestamp.today().normalize()
    upgrades = []
    for _ in range(int(rng.integers(0, 4 if usa else 2))):
        d = today - pd.Timedelta(days=int(rng.integers(1, 110)))
        action = str(rng.choice(["up", "down", "main", "init"], p=[0.35, 0.25, 0.25, 0.15]))
        upgrades.append({"date": d.strftime("%Y-%m-%d"), "firm": str(rng.choice(["Morgan Stanley", "Goldman", "DNB Markets", "Pareto", "JPMorgan"])),
                         "to": "Buy" if action in ("up", "init") else "Hold", "from": "Hold" if action == "up" else "Buy", "action": action})
    insider = []
    for _ in range(int(rng.integers(0, 5))):
        d = today - pd.Timedelta(days=int(rng.integers(1, 170)))
        kind = str(rng.choice(["buy", "sell"], p=[0.45, 0.55]))
        shares = float(rng.integers(500, 50000))
        insider.append({"date": d.strftime("%Y-%m-%d"), "kind": kind, "insider": "Demo Person",
                        "position": str(rng.choice(["CEO", "CFO", "Director", "Officer"])),
                        "shares": shares, "value": shares * price})
    return {"fundamentals": fundamentals, "analyst": analyst, "upgrades": upgrades,
            "insider": insider, "fetched_at": today.strftime("%Y-%m-%d")}
