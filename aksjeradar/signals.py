"""
Tekniske indikatorer og signaler.

compute_indicators(df)  -> legger til kolonner (SMA, EMA, MACD, RSI, Bollinger, ATR, 52-ukers topp/bunn, avkastning)
latest_signals(df, cfg) -> et oppslagsverk med dagens situasjon for aksjen (brukes av scoring)

Alt regnes med pandas – ingen eksterne TA-biblioteker, så det er lett å lese og endre.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _f(x):
    """float eller None (NaN -> None)."""
    try:
        v = float(x)
        return None if (np.isnan(v) or np.isinf(v)) else v
    except (TypeError, ValueError):
        return None


def compute_indicators(df: pd.DataFrame, rsi_period: int = 14, sma_fast: int = 50, sma_slow: int = 200) -> pd.DataFrame:
    df = df.sort_index().copy()
    c = df["Close"].astype(float)

    # Glidende gjennomsnitt – trendretning
    df["sma20"] = c.rolling(20).mean()
    df["sma_fast"] = c.rolling(sma_fast).mean()
    df["sma_slow"] = c.rolling(sma_slow).mean()

    # MACD – momentum i trenden
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # RSI – overkjøpt (>70) / oversolgt (<30)
    delta = c.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / rsi_period, min_periods=rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / rsi_period, min_periods=rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(avg_loss > 0, 100.0)       # ingen tap i perioden -> RSI 100
    rsi = rsi.where(avg_gain.notna(), np.nan)  # for lite data -> NaN
    df["rsi"] = rsi

    # Bollinger-bånd – hvor "strukket" kursen er
    std20 = c.rolling(20).std()
    df["bb_upper"] = df["sma20"] + 2 * std20
    df["bb_lower"] = df["sma20"] - 2 * std20

    # ATR – daglig svingning (volatilitet)
    prev_c = c.shift(1)
    tr = pd.concat(
        [df["High"] - df["Low"], (df["High"] - prev_c).abs(), (df["Low"] - prev_c).abs()], axis=1
    ).max(axis=1)
    df["atr14"] = tr.rolling(14).mean()

    # Volum og 52-ukers nivåer
    df["vol_avg20"] = df["Volume"].rolling(20).mean()
    df["high52"] = c.rolling(252, min_periods=100).max()
    df["low52"] = c.rolling(252, min_periods=100).min()

    # Avkastning over ulike horisonter (ca. handelsdager)
    for label, n in (("ret_1m", 21), ("ret_3m", 63), ("ret_6m", 126), ("ret_12m", 252)):
        df[label] = c.pct_change(n)
    return df


def _crossed(frame: pd.DataFrame, a: str, b: str, up: bool) -> bool:
    """Har kolonne `a` krysset over (up=True) / under (up=False) kolonne `b` i dette utsnittet?"""
    d = frame[a] - frame[b]
    if up:
        return bool(((d > 0) & (d.shift(1) <= 0)).any())
    return bool(((d < 0) & (d.shift(1) >= 0)).any())


def latest_signals(df: pd.DataFrame, scfg: dict) -> dict:
    """Dagens tekniske bilde for én aksje."""
    ind = compute_indicators(
        df,
        rsi_period=int(scfg.get("rsi_period", 14)),
        sma_fast=int(scfg.get("sma_fast", 50)),
        sma_slow=int(scfg.get("sma_slow", 200)),
    )
    if len(ind) < 30:
        raise ValueError("for lite kurshistorikk")

    last = ind.iloc[-1]
    prev = ind.iloc[-2]
    close = float(last["Close"])
    lookback = int(scfg.get("breakout_lookback", 60))
    spike_mult = float(scfg.get("volume_spike_mult", 2.0))

    r10 = ind.tail(10)   # siste to uker
    r5 = ind.tail(5)     # siste uke

    sma_fast = _f(last["sma_fast"])
    sma_slow = _f(last["sma_slow"])
    rsi = _f(last["rsi"])
    vol_ratio = _f(last["Volume"] / last["vol_avg20"]) if _f(last["vol_avg20"]) else None
    high52 = _f(last["high52"])
    pct_from_high = (close / high52 - 1) if high52 else None

    prior_high = _f(ind["High"].iloc[-lookback - 1:-1].max())
    breakout = bool(prior_high and close > prior_high and (vol_ratio or 0) >= 1.5)

    return {
        "price": close,
        "change_1d": close / float(prev["Close"]) - 1,
        "last_date": pd.Timestamp(ind.index[-1]).strftime("%Y-%m-%d"),
        # Trend
        "sma_fast": sma_fast,
        "sma_slow": sma_slow,
        "above_sma_fast": bool(sma_fast and close > sma_fast),
        "above_sma_slow": bool(sma_slow and close > sma_slow),
        "fast_gt_slow": bool(sma_fast and sma_slow and sma_fast > sma_slow),
        "golden_cross": _crossed(r10, "sma_fast", "sma_slow", up=True),
        "death_cross": _crossed(r10, "sma_fast", "sma_slow", up=False),
        "broke_below_slow": _crossed(r5, "Close", "sma_slow", up=False),
        "dist_sma_slow": (close / sma_slow - 1) if sma_slow else None,
        # Momentum
        "rsi": rsi,
        "oversold": bool(rsi is not None and rsi < 30),
        "overbought": bool(rsi is not None and rsi > 70),
        "macd_hist": _f(last["macd_hist"]),
        "macd_cross_up": bool(((r5["macd_hist"] > 0) & (r5["macd_hist"].shift(1) <= 0)).any()),
        "macd_cross_down": bool(((r5["macd_hist"] < 0) & (r5["macd_hist"].shift(1) >= 0)).any()),
        # Nivåer og volum
        "high52": high52,
        "pct_from_52w_high": pct_from_high,
        "near_52w_high": bool(pct_from_high is not None and pct_from_high >= -0.03),
        "breakout": breakout,
        "volume_ratio": vol_ratio,
        "volume_spike": bool(vol_ratio is not None and vol_ratio >= spike_mult),
        "bb_upper": _f(last["bb_upper"]),
        "bb_lower": _f(last["bb_lower"]),
        "atr_pct": (_f(last["atr14"]) / close) if _f(last["atr14"]) else None,
        # Avkastning
        "ret_1m": _f(last["ret_1m"]),
        "ret_3m": _f(last["ret_3m"]),
        "ret_6m": _f(last["ret_6m"]),
        "ret_12m": _f(last["ret_12m"]),
    }
