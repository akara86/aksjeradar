"""
Scoring og idégenerering.

Hver aksje får fire delscore (0–100):
  teknisk       – trend, momentum, utbrudd, volum
  analytiker    – konsensus (kjøp/hold/selg), kursmål-oppside, nylige opp-/nedgraderinger
  fundamental   – verdsettelse, vekst, lønnsomhet, gjeld (rangert mot resten av universet)
  innsider      – netto innsidekjøp/-salg siste 180 dager

Samlet score = vektet snitt (vekter i config.yaml). Manglende delscore holdes utenfor
snittet, så en aksje uten analytikerdekning straffes ikke for det.

Deretter sorteres aksjene i idékategorier med en kort begrunnelse per aksje.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import market_of
from .signals import latest_signals

log = logging.getLogger("aksjeradar.scoring")

FUNDAMENTAL_KEYS = [
    "trailingPE", "forwardPE", "enterpriseToEbitda", "trailingPegRatio", "priceToBook",
    "revenueGrowth", "earningsGrowth", "profitMargins", "operatingMargins", "returnOnEquity",
    "debtToEquity", "dividendYield", "beta",
]

# Hvilken retning som er "bra" for hvert fundamentalt nøkkeltall
LOWER_IS_BETTER = {"trailingPE", "forwardPE", "enterpriseToEbitda", "trailingPegRatio", "priceToBook", "debtToEquity"}
HIGHER_IS_BETTER = {"revenueGrowth", "earningsGrowth", "profitMargins", "operatingMargins", "returnOnEquity", "fcf_yield"}

CATEGORIES = [
    ("buy", "Kjøpskandidater i dag"),
    ("momentum", "Momentum – sterk trend"),
    ("analyst_upside", "Analytiker-oppside"),
    ("upgrades", "Nylige oppgraderinger"),
    ("breakout", "Utbrudd / nær 52-ukers topp"),
    ("oversold_quality", "Oversolgt kvalitet (mulig rekyl)"),
    ("insider_buying", "Innsidekjøp"),
]


# --------------------------------------------------------------------------
# 1. Samle alle tall i én tabell
# --------------------------------------------------------------------------
def build_table(prices: dict[str, pd.DataFrame], details: dict[str, dict], cfg: dict) -> pd.DataFrame:
    rows = []
    today = date.today()
    c30 = (today - timedelta(days=30)).isoformat()
    c90 = (today - timedelta(days=90)).isoformat()

    for ticker, df in prices.items():
        try:
            sig = latest_signals(df, cfg["signals"])
        except Exception as e:  # noqa: BLE001
            log.warning("Signaler feilet for %s: %s", ticker, e)
            continue

        d = details.get(ticker) or {}
        f = d.get("fundamentals") or {}
        a = d.get("analyst") or {}
        ups = d.get("upgrades") or []
        ins = d.get("insider") or []

        row = {
            "ticker": ticker,
            "name": f.get("shortName") or f.get("longName") or ticker,
            "market": market_of(ticker),
            "sector": f.get("sector"),
            "currency": f.get("currency"),
            "market_cap": f.get("marketCap"),
            **sig,
        }

        # Analytikere
        row["rec_mean"] = a.get("recommendationMean")
        row["rec_key"] = a.get("recommendationKey")
        row["n_analysts"] = int(a.get("numberOfAnalystOpinions") or 0)
        tm = a.get("targetMeanPrice")
        row["target_mean"] = tm
        row["upside"] = (tm / sig["price"] - 1) if (tm and sig["price"]) else None
        row["upgrades_30d"] = sum(1 for u in ups if u.get("action") == "up" and u.get("date", "") >= c30)
        row["upgrades_90d"] = sum(1 for u in ups if u.get("action") == "up" and u.get("date", "") >= c90)
        row["downgrades_90d"] = sum(1 for u in ups if u.get("action") == "down" and u.get("date", "") >= c90)
        row["last_upgrade"] = next((f"{u['firm']}: {u['from']} → {u['to']} ({u['date']})" for u in ups if u.get("action") == "up"), None)

        # Fundamentalt
        for k in FUNDAMENTAL_KEYS:
            row[k] = f.get(k)
        if row.get("dividendYield") is not None and row["dividendYield"] > 1.0:
            row["dividendYield"] = row["dividendYield"] / 100.0  # eldre bufrede snapshots i prosent
        fcf, mc = f.get("freeCashflow"), f.get("marketCap")
        row["fcf_yield"] = (fcf / mc) if (fcf is not None and mc) else None

        # Innsidere
        buys = [x for x in ins if x.get("kind") == "buy"]
        sells = [x for x in ins if x.get("kind") == "sell"]
        row["insider_buys"] = len(buys)
        row["insider_sells"] = len(sells)
        row["insider_buy_value"] = sum(x.get("value") or 0 for x in buys)
        row["insider_sell_value"] = sum(x.get("value") or 0 for x in sells)
        row["insider_buys_90d"] = sum(1 for x in buys if x.get("date", "") >= c90)

        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return score_table(pd.DataFrame(rows), cfg)


# --------------------------------------------------------------------------
# 2. Delscore
# --------------------------------------------------------------------------
def _pct_rank(s: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """Prosentil-rangering 0–100 innenfor universet. NaN forblir NaN."""
    s = pd.to_numeric(s, errors="coerce")
    return s.rank(pct=True, ascending=higher_is_better) * 100


def technical_score(r: pd.Series, mom_pct: float) -> float:
    s = 20.0
    s += 0.25 * (mom_pct if not np.isnan(mom_pct) else 50)  # 0–25 for relativ 6m-styrke
    if r.get("above_sma_slow"):
        s += 12
    if r.get("above_sma_fast"):
        s += 8
    if r.get("fast_gt_slow"):
        s += 8
    if (r.get("macd_hist") or 0) > 0:
        s += 7
    if r.get("macd_cross_up"):
        s += 5
    rsi = r.get("rsi")
    if rsi is not None and not np.isnan(rsi):
        if 50 <= rsi <= 70:
            s += 8
        elif rsi > 75:
            s -= 8
        elif rsi < 30:
            s -= 4
    if r.get("near_52w_high"):
        s += 5
    if r.get("breakout"):
        s += 7
    if r.get("volume_spike") and (r.get("change_1d") or 0) > 0:
        s += 3
    if r.get("death_cross") or r.get("broke_below_slow"):
        s -= 10
    return float(np.clip(s, 0, 100))


def analyst_score(r: pd.Series, min_analysts: int) -> float | None:
    n = int(r.get("n_analysts") or 0)
    rec = r.get("rec_mean")
    if n < min_analysts or rec is None or np.isnan(rec):
        return None  # for tynn dekning -> ingen delscore
    rec_score = (5 - float(rec)) / 4 * 100          # 1=strong buy -> 100, 5=sell -> 0
    up = r.get("upside")
    if up is None or np.isnan(up):
        upside_score = 50.0
    else:
        upside_score = float(np.clip(up / 0.30, 0, 1) * 100)  # 0 % -> 0, 30 %+ -> 100
    s = 0.55 * rec_score + 0.45 * upside_score
    s += 6 * int(r.get("upgrades_90d") or 0) - 6 * int(r.get("downgrades_90d") or 0)
    return float(np.clip(s, 0, 100))


def fundamental_scores(df: pd.DataFrame) -> pd.Series:
    parts = []
    for k in LOWER_IS_BETTER:
        s = pd.to_numeric(df[k], errors="coerce")
        if k in ("trailingPE", "forwardPE", "trailingPegRatio", "enterpriseToEbitda"):
            s = s.where(s > 0, np.nan)
            # Underskudd (negativ P/E) -> rangeres dårligst
            neg = pd.to_numeric(df[k], errors="coerce") <= 0
            ranked = _pct_rank(s, higher_is_better=False)
            ranked[neg] = 0.0
        else:
            ranked = _pct_rank(s, higher_is_better=False)
        parts.append(ranked)
    for k in HIGHER_IS_BETTER:
        parts.append(_pct_rank(df[k], higher_is_better=True))
    mat = pd.concat(parts, axis=1)
    count = mat.notna().sum(axis=1)
    score = mat.mean(axis=1)
    return score.where(count >= 3, np.nan)  # krever minst tre nøkkeltall


def insider_score(r: pd.Series) -> float | None:
    buys, sells = int(r.get("insider_buys") or 0), int(r.get("insider_sells") or 0)
    if buys + sells == 0:
        return None
    bv, sv = float(r.get("insider_buy_value") or 0), float(r.get("insider_sell_value") or 0)
    if bv + sv > 0:
        ratio = bv / (bv + sv)
    else:
        ratio = buys / (buys + sells)
    s = ratio * 100
    # Små beløp i forhold til selskapets størrelse betyr mindre -> trekk mot 50
    mc = r.get("market_cap")
    if mc and not np.isnan(mc) and mc > 0:
        rel = (bv + sv) / mc
        if rel < 1e-5:
            s = 50 + (s - 50) * 0.4
    return float(np.clip(s, 0, 100))


def score_table(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    w = cfg["scoring"]["weights"]
    min_an = int(cfg["scoring"].get("min_analysts", 3))

    mom_pct = _pct_rank(df["ret_6m"], higher_is_better=True)
    df["score_technical"] = [technical_score(r, mom_pct.iloc[i]) for i, (_, r) in enumerate(df.iterrows())]
    df["score_analyst"] = [analyst_score(r, min_an) for _, r in df.iterrows()]
    df["score_fundamental"] = fundamental_scores(df)
    df["score_insider"] = [insider_score(r) for _, r in df.iterrows()]

    comps = {
        "score_technical": w.get("technical", 0.35),
        "score_analyst": w.get("analyst", 0.25),
        "score_fundamental": w.get("fundamental", 0.25),
        "score_insider": w.get("insider", 0.15),
    }
    # Manglende delscore teller som nøytral (50): mindre data gir en score nærmere midten,
    # slik at en aksje med bare teknisk bilde ikke kan toppe listen over aksjer med fullt bilde.
    total = []
    for _, r in df.iterrows():
        num, den, present = 0.0, 0.0, 0
        for col, weight in comps.items():
            v = r.get(col)
            if v is not None and not pd.isna(v):
                num += weight * float(v)
                present += 1
            else:
                num += weight * 50.0
            den += weight
        total.append(num / den if (den and present) else np.nan)
    df["score"] = total
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = np.arange(1, len(df) + 1)

    verdicts = [recommend(r, min_an) for _, r in df.iterrows()]
    df["verdict"] = [v[0] for v in verdicts]
    df["verdict_reasons"] = [v[1] for v in verdicts]
    df["risk"] = [v[2] for v in verdicts]
    df["coverage"] = [v[3] for v in verdicts]
    return df


# --------------------------------------------------------------------------
# 2b. Anbefaling per aksje (regelbasert, forklarbar)
# --------------------------------------------------------------------------
VERDICTS = ["Sterkt kjøp", "Kjøp", "Hold", "Avvent", "Unngå"]
BUY_VERDICTS = {"Sterkt kjøp", "Kjøp"}


def _num(x):
    return None if (x is None or (isinstance(x, float) and np.isnan(x))) else x


def recommend(r: pd.Series, min_analysts: int) -> tuple[str, list[str], str, str]:
    """
    Gir (anbefaling, begrunnelser, risikonivå, datagrunnlag).

    Trinn:
      1. Samlet score setter utgangspunktet:  >=75 Sterkt kjøp, >=65 Kjøp, >=50 Hold, >=40 Avvent, ellers Unngå
      2. Kjøp krever bekreftet opptrend (kurs over SMA200) – ellers ett hakk ned
      3. Risikoflagg kan begrense: death cross / brudd under SMA200, sterkt overkjøpt RSI,
         negative analytikere, kurs over kursmål, flere nedgraderinger
      4. Tynt datagrunnlag (bare én delscore) gir aldri Sterkt kjøp
    """
    score = _num(r.get("score"))
    present = sum(1 for c in ("score_technical", "score_analyst", "score_fundamental", "score_insider")
                  if _num(r.get(c)) is not None)
    coverage = "fullt" if present == 4 else "delvis" if present >= 2 else "tynt"

    atr = _num(r.get("atr_pct"))
    risk = "ukjent" if atr is None else "lav" if atr < 0.015 else "middels" if atr < 0.03 else "høy"

    if score is None:
        return "Hold", ["for lite data til å vurdere"], risk, coverage

    if score >= 75:
        level = 0
    elif score >= 65:
        level = 1
    elif score >= 50:
        level = 2
    elif score >= 40:
        level = 3
    else:
        level = 4
    reasons = [f"samlet score {score:.0f}"]

    # 2. trendbekreftelse
    if level <= 1:
        if r.get("above_sma_slow"):
            reasons.append("i opptrend (over SMA200)")
        else:
            level += 1
            reasons.append("mangler bekreftet opptrend (under SMA200)")

    # 3. begrensende flagg – det strengeste vinner
    rsi = _num(r.get("rsi"))
    n = int(r.get("n_analysts") or 0)
    rec = _num(r.get("rec_mean"))
    upside = _num(r.get("upside"))
    caps: list[tuple[int, str]] = []
    if r.get("death_cross") or r.get("broke_below_slow"):
        caps.append((3, "nylig death cross / brudd under SMA200"))
    if rsi is not None and rsi > 78:
        caps.append((2, f"RSI {rsi:.0f} – sterkt overkjøpt, vent på rekyl"))
    if n >= 5 and rec is not None and rec >= 3.5:
        caps.append((2, f"analytikerne er negative (snitt {rec:.1f})"))
    if n >= 5 and upside is not None and upside < 0:
        caps.append((2, "kursen er over analytikernes snittkursmål"))
    if int(r.get("downgrades_90d") or 0) >= 2 and int(r.get("upgrades_90d") or 0) == 0:
        caps.append((2, f"{int(r['downgrades_90d'])} nedgraderinger siste 90 dager"))
    for cap_level, why in caps:
        if level < cap_level:
            level = cap_level
        reasons.append(why)

    # 4. datagrunnlag: bare én delscore gir aldri mer enn Hold, to–tre gir aldri Sterkt kjøp
    if coverage == "tynt" and level < 2:
        level = 2
        reasons.append("tynt datagrunnlag (bare teknisk bilde) – avventer fundamental- og analytikerdata")
    elif coverage == "delvis" and level == 0:
        level = 1
        reasons.append("delvis datagrunnlag")

    # støttende argumenter for kjøpskandidater
    if level <= 1:
        if n >= min_analysts and rec is not None and rec <= 2.2:
            reasons.append(f"analytikerkonsensus kjøp ({n} analytikere)")
        if upside is not None and upside >= 0.15:
            reasons.append(f"kursmål {upside * 100:+.0f} % over kursen")
        if int(r.get("insider_buys_90d") or 0):
            reasons.append("innsidekjøp siste 90 dager")
        if r.get("breakout"):
            reasons.append("ferskt utbrudd på høyt volum")
    if level >= 3:
        if not r.get("above_sma_slow"):
            reasons.append("under SMA200")
        if _num(r.get("score_fundamental")) is not None and r["score_fundamental"] < 35:
            reasons.append("svake fundamentale nøkkeltall")
        if _num(r.get("score_technical")) is not None and r["score_technical"] < 35:
            reasons.append("svak teknisk trend")

    return VERDICTS[level], reasons, risk, coverage


# --------------------------------------------------------------------------
# 3. Idékategorier med begrunnelse
# --------------------------------------------------------------------------
def _pct(x, signed=True):
    if x is None or pd.isna(x):
        return "–"
    return f"{x * 100:+.1f} %" if signed else f"{x * 100:.1f} %"


def _reasons(r: pd.Series) -> list[str]:
    out = []
    if r.get("above_sma_slow") and r.get("fast_gt_slow"):
        out.append("over SMA50 og SMA200 (opptrend)")
    elif r.get("above_sma_slow"):
        out.append("over SMA200")
    if r.get("golden_cross"):
        out.append("golden cross")
    if r.get("macd_cross_up"):
        out.append("MACD krysset opp")
    elif (r.get("macd_hist") or 0) > 0:
        out.append("MACD positiv")
    if r.get("breakout"):
        out.append("brudd over 60-dagers topp på høyt volum")
    elif r.get("near_52w_high"):
        out.append("nær 52-ukers topp")
    if r.get("volume_spike"):
        out.append(f"volum {r.get('volume_ratio'):.1f}× normalt")
    if r.get("oversold"):
        out.append(f"RSI {r.get('rsi'):.0f} (oversolgt)")
    r6 = r.get("ret_6m")
    if r6 is not None and not pd.isna(r6):
        out.append(f"6 mnd {_pct(r6)}")
    n = int(r.get("n_analysts") or 0)
    if n and r.get("rec_mean") is not None and not pd.isna(r.get("rec_mean")):
        out.append(f"{n} analytikere, snitt {r.get('rec_mean'):.1f} ({r.get('rec_key') or '-'})")
    if r.get("upside") is not None and not pd.isna(r.get("upside")):
        out.append(f"kursmål {_pct(r.get('upside'))}")
    if r.get("upgrades_30d"):
        out.append(f"{int(r['upgrades_30d'])} oppgradering(er) siste 30 d")
    if r.get("insider_buys_90d"):
        out.append(f"{int(r['insider_buys_90d'])} innsidekjøp siste 90 d")
    return out


def _item(r: pd.Series) -> dict:
    return {
        "ticker": r["ticker"],
        "name": r["name"],
        "market": r["market"],
        "price": r["price"],
        "currency": r.get("currency"),
        "score": None if pd.isna(r["score"]) else round(float(r["score"]), 1),
        "verdict": r.get("verdict"),
        "reasons": _reasons(r),
    }


def generate_ideas(df: pd.DataFrame, cfg: dict) -> dict:
    k = int(cfg["report"].get("per_category", 5))
    min_an = int(cfg["scoring"].get("min_analysts", 3))
    ideas: dict[str, list] = {}
    if df.empty:
        return {key: [] for key, _ in CATEGORIES} | {"warnings": []}

    d = df.copy()
    for col in ("score_technical", "score_analyst", "score_fundamental", "score_insider", "rsi", "upside"):
        d[col] = pd.to_numeric(d[col], errors="coerce")

    buy = d[d["verdict"].isin(BUY_VERDICTS)]
    ideas["buy"] = []
    for _, r in buy.head(k).iterrows():
        item = _item(r)
        item["reasons"] = list(r["verdict_reasons"])  # anbefalingens egen begrunnelse
        ideas["buy"].append(item)

    momentum = d[(d["score_technical"] >= 65) & d["above_sma_slow"] & (d["rsi"] <= 75)]
    ideas["momentum"] = [_item(r) for _, r in momentum.head(k).iterrows()]

    upside = d[(d["n_analysts"] >= min_an) & (d["upside"] >= 0.15) & (d["rec_mean"] <= 2.5)]
    upside = upside.sort_values(["score_analyst", "score"], ascending=False)
    ideas["analyst_upside"] = [_item(r) for _, r in upside.head(k).iterrows()]

    ups = d[d["upgrades_30d"] >= 1].sort_values(["upgrades_30d", "score"], ascending=False)
    ideas["upgrades"] = [_item(r) for _, r in ups.head(k).iterrows()]

    brk = d[d["breakout"] | (d["near_52w_high"] & d["volume_spike"])]
    ideas["breakout"] = [_item(r) for _, r in brk.head(k).iterrows()]

    oversold = d[(d["rsi"] < 35) & (d["score_fundamental"] >= 55) & (d["ret_12m"].fillna(0) > -0.25)]
    oversold = oversold.sort_values("score_fundamental", ascending=False)
    ideas["oversold_quality"] = [_item(r) for _, r in oversold.head(k).iterrows()]

    ins = d[(d["score_insider"] >= 70) & (d["insider_buys_90d"] >= 1)]
    ins = ins.sort_values(["insider_buy_value", "score"], ascending=False)
    ideas["insider_buying"] = [_item(r) for _, r in ins.head(k).iterrows()]

    # Varsler – aksjer som viser svakhet (nyttig hvis du eier dem)
    warn = []
    for _, r in d.iterrows():
        flags = []
        if r.get("death_cross"):
            flags.append("death cross (SMA50 under SMA200)")
        if r.get("broke_below_slow"):
            flags.append("brutt under SMA200")
        if int(r.get("downgrades_90d") or 0) >= 2:
            flags.append(f"{int(r['downgrades_90d'])} nedgraderinger siste 90 d")
        if r.get("overbought") and (r.get("rsi") or 0) > 80:
            flags.append(f"RSI {r['rsi']:.0f} – sterkt overkjøpt")
        if (r.get("score_insider") is not None and not pd.isna(r.get("score_insider"))
                and r["score_insider"] <= 20 and int(r.get("insider_sells") or 0) >= 3):
            flags.append(f"{int(r['insider_sells'])} innsidesalg siste 180 d")
        if flags:
            item = _item(r)
            item["reasons"] = flags
            warn.append(item)
    ideas["warnings"] = warn[: k * 2]
    return ideas
