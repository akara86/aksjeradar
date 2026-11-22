"""
Teknisk analyse for fond, sektorer og regioner – bare ut fra sluttkurser (fond har ingen høy/lav-kurs).

Indikatorer:
  * Trend: kurs mot 20/50/200-dagers glidende snitt, retningen på 200-dagers, gyllent kryss / dødskryss
  * Trendstyrke: lineær regresjon av log-kurs siste 3 mnd (årlig stigningstakt og R² = hvor «ren» trenden er)
  * Momentum: RSI (14 dager), MACD (12, 26, 9) med siste kryss, endring 1 og 3 mnd
  * Svingninger: Bollinger-bånd (20 dager, 2 standardavvik) med %B og båndbredde, årlig volatilitet
  * Nivåer: støtte og motstand fra lokale bunner/topper siste 6 mnd, 52-ukers topp og bunn

Alt samles i en samlet score (−100 til +100), en karakter og en kort tekst på norsk. Grafene (RSI, MACD, bånd)
regnes ut i appen fra kurshistorikken, så datafilen holdes liten.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _f(x, d: int = 4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(x) or math.isinf(x)) else round(x, d)


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0)


def macd(s: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9):
    line = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    signal = line.ewm(span=sig, adjust=False).mean()
    return line, signal, line - signal


def _last_cross(a: pd.Series, b: pd.Series, lookback: int) -> dict | None:
    """Siste gang a krysset b (innen lookback dager): {date, up, days_ago}."""
    diff = (a - b).dropna().tail(lookback + 1)
    if len(diff) < 2:
        return None
    sgn = np.sign(diff.values)
    for i in range(len(sgn) - 1, 0, -1):
        if sgn[i] != 0 and sgn[i - 1] != 0 and sgn[i] != sgn[i - 1]:
            return {"date": diff.index[i].strftime("%Y-%m-%d"), "up": bool(sgn[i] > 0), "days_ago": int(len(sgn) - 1 - i)}
    return None


def _pivots(s: pd.Series, w: int = 5):
    """Lokale topper og bunner (høyeste/laveste innenfor ±w dager)."""
    hi, lo = [], []
    v = s.values
    for i in range(w, len(v) - w):
        win = v[i - w:i + w + 1]
        if v[i] == win.max():
            hi.append((s.index[i], float(v[i])))
        if v[i] == win.min():
            lo.append((s.index[i], float(v[i])))
    return hi, lo


def _cluster(levels: list[float], tol: float = 0.015) -> list[dict]:
    """Slå sammen nivåer som ligger tett (innen 1,5 %) – flere treff gir sterkere nivå."""
    out: list[dict] = []
    for x in sorted(levels):
        if out and abs(x / out[-1]["level"] - 1) < tol:
            c = out[-1]
            c["level"] = (c["level"] * c["touches"] + x) / (c["touches"] + 1)
            c["touches"] += 1
        else:
            out.append({"level": x, "touches": 1})
    return out


def technical(s: pd.Series) -> dict | None:
    s = s.dropna().astype(float)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    if len(s) < 60:
        return None
    last = float(s.iloc[-1])
    sma20, sma50, sma200 = s.rolling(20).mean(), s.rolling(50).mean(), s.rolling(200).mean()
    have200 = len(s) >= 200
    r = rsi(s)
    m_line, m_sig, m_hist = macd(s)
    bb_mid, bb_sd = sma20, s.rolling(20).std()
    bb_up, bb_lo = bb_mid + 2 * bb_sd, bb_mid - 2 * bb_sd
    pct_b = (last - float(bb_lo.iloc[-1])) / max(float(bb_up.iloc[-1] - bb_lo.iloc[-1]), 1e-9)
    bandwidth = float((bb_up.iloc[-1] - bb_lo.iloc[-1]) / bb_mid.iloc[-1])
    bw_hist = ((bb_up - bb_lo) / bb_mid).dropna().tail(252)
    bw_rank = float((bw_hist < bandwidth).mean()) if len(bw_hist) > 50 else None
    vol = float(s.pct_change().tail(63).std() * math.sqrt(252))

    # trendstyrke: log-kurs siste 63 dager
    y = np.log(s.tail(63).values)
    xs = np.arange(len(y))
    slope, icpt = np.polyfit(xs, y, 1)
    fit = slope * xs + icpt
    r2 = 1 - float(((y - fit) ** 2).sum()) / max(float(((y - y.mean()) ** 2).sum()), 1e-12)
    trend_ann = math.exp(slope * 252) - 1

    # nivåer
    look = s.tail(126)
    hi_p, lo_p = _pivots(look)
    sup = [c for c in _cluster([p for _, p in lo_p]) if c["level"] < last * 0.995]
    res = [c for c in _cluster([p for _, p in hi_p]) if c["level"] > last * 1.005]
    support = max(sup, key=lambda c: c["level"]) if sup else None
    resistance = min(res, key=lambda c: c["level"]) if res else None
    hi52, lo52 = float(s.tail(252).max()), float(s.tail(252).min())

    rsi_now = _f(r.iloc[-1], 1)
    macd_now, sig_now, hist_now = float(m_line.iloc[-1]), float(m_sig.iloc[-1]), float(m_hist.iloc[-1])
    hist_prev = float(m_hist.iloc[-6]) if len(m_hist) > 6 else hist_now
    macd_cross = _last_cross(m_line, m_sig, 60)
    ma_cross = _last_cross(sma50, sma200, 250) if have200 else None
    v20, v50 = last / float(sma20.iloc[-1]) - 1, last / float(sma50.iloc[-1]) - 1
    v200 = last / float(sma200.iloc[-1]) - 1 if have200 else None
    slope200 = float(sma200.iloc[-1] / sma200.iloc[-21] - 1) if len(s) >= 221 else None
    ret1m = last / float(s.iloc[-22]) - 1 if len(s) > 22 else None
    ret3m = last / float(s.iloc[-64]) - 1 if len(s) > 64 else None

    # ---- signaler: (gruppe, navn, verdi-tekst, poeng −2..+2, forklaring) ----
    sig: list[dict] = []

    def add(group, name, value, pts, text):
        sig.append({"group": group, "name": name, "value": value, "pts": pts,
                    "tone": "pos" if pts > 0 else "neg" if pts < 0 else "neu", "text": text})

    if v200 is not None:
        add("Trend", "Mot 200-dagers snitt", f"{v200 * 100:+.1f} %", 2 if v200 > 0.02 else 1 if v200 > 0 else -1 if v200 > -0.03 else -2,
            "Over snittet = langsiktig opptrend." if v200 > 0 else "Under snittet = langsiktig svakhet.")
    if slope200 is not None:
        add("Trend", "Retning 200-dagers", f"{slope200 * 100:+.1f} % 1 mnd", 1 if slope200 > 0.003 else -1 if slope200 < -0.003 else 0,
            "Snittet stiger." if slope200 > 0.003 else "Snittet faller." if slope200 < -0.003 else "Snittet går sidelengs.")
    add("Trend", "Mot 50-dagers snitt", f"{v50 * 100:+.1f} %", 1 if v50 > 0 else -1,
        "Mellomlang trend er opp." if v50 > 0 else "Mellomlang trend er ned.")
    if have200:
        gold = bool(sma50.iloc[-1] > sma200.iloc[-1])
        txt = ("50-dagers over 200-dagers (gyllent kryss)" if gold else "50-dagers under 200-dagers (dødskryss)")
        if ma_cross:
            txt += f" – krysset {ma_cross['days_ago']} børsdager siden."
        add("Trend", "Gyllent kryss / dødskryss", "gyllent" if gold else "dødskryss", 1 if gold else -1, txt)
    add("Trend", "Trendstyrke 3 mnd", f"{trend_ann * 100:+.0f} %/år · R² {r2:.2f}",
        (1 if trend_ann > 0 else -1) * (1 if r2 > 0.5 else 0),
        ("Tydelig " if r2 > 0.5 else "Svak, hakkete ") + ("opptrend." if trend_ann > 0 else "nedtrend.") + " R² over 0,5 betyr en jevn trend.")
    if rsi_now is not None:
        if rsi_now >= 70:
            add("Momentum", "RSI (14)", f"{rsi_now:.0f}", -1, "Overkjøpt – kursen har steget mye på kort tid og tar ofte en pause.")
        elif rsi_now <= 30:
            add("Momentum", "RSI (14)", f"{rsi_now:.0f}", 1, "Oversolgt – fallet har vært kraftig; ofte en kortsiktig motreaksjon.")
        else:
            add("Momentum", "RSI (14)", f"{rsi_now:.0f}", 1 if rsi_now >= 55 else -1 if rsi_now <= 45 else 0,
                "Positivt momentum." if rsi_now >= 55 else "Svakt momentum." if rsi_now <= 45 else "Nøytralt.")
    mtxt = ("MACD over signallinjen" if macd_now > sig_now else "MACD under signallinjen")
    if macd_cross and macd_cross["days_ago"] <= 10:
        mtxt += f" – {'kjøpssignal' if macd_cross['up'] else 'salgssignal'} for {macd_cross['days_ago']} dager siden"
    mtxt += "; " + ("styrkes." if abs(hist_now) > abs(hist_prev) else "svekkes.")
    add("Momentum", "MACD (12, 26, 9)", "positiv" if macd_now > sig_now else "negativ", 1 if macd_now > sig_now else -1, mtxt)
    if ret3m is not None:
        add("Momentum", "Endring 3 mnd", f"{ret3m * 100:+.1f} %", 1 if ret3m > 0.03 else -1 if ret3m < -0.03 else 0, "Kursendring siste kvartal.")
    btxt = ("Ved øvre bånd – sterk, men strukket." if pct_b > 0.95 else "Ved nedre bånd – presset, ofte nær kortsiktig bunn." if pct_b < 0.05
            else "Inne i båndet.")
    if bw_rank is not None and bw_rank < 0.15:
        btxt += " Båndene er uvanlig smale – et større utslag (opp eller ned) kommer ofte etter slike rolige perioder."
    add("Svingninger", "Bollinger %B", f"{pct_b * 100:.0f} %", 0, btxt)
    add("Svingninger", "Volatilitet (3 mnd)", f"{vol * 100:.0f} %/år", 0, "Typisk årlig svingning. Aksjefond ligger ofte på 12–25 %.")

    # samlet score: trend teller mest (langsiktig sparer), momentum mindre
    tpts = [x["pts"] for x in sig if x["group"] == "Trend"]
    mpts = [x["pts"] for x in sig if x["group"] == "Momentum"]
    t_score = sum(tpts) / (2 * len(tpts)) if tpts else 0
    m_score = sum(mpts) / (2 * len(mpts)) if mpts else 0
    score = round(100 * (0.65 * t_score + 0.35 * m_score))
    verdict = ("Sterk" if score >= 45 else "Positiv" if score >= 15 else "Nøytral" if score > -15 else "Svak" if score > -45 else "Negativ")

    # sammendrag
    parts = []
    if v200 is not None:
        parts.append(("Langsiktig opptrend" if v200 > 0 else "Under langsiktig trend") + f" ({v200 * 100:+.1f} % mot 200-dagers)")
    parts.append(("kortsiktig momentum er positivt" if m_score > 0.15 else "kortsiktig momentum er svakt" if m_score < -0.15 else "kortsiktig momentum er nøytralt")
                 + (f", RSI {rsi_now:.0f}" if rsi_now is not None else ""))
    summary = ", ".join(parts) + "."
    if rsi_now is not None and rsi_now >= 70:
        summary += " Overkjøpt på kort sikt – nye penger kan med fordel spres over tid."
    elif rsi_now is not None and rsi_now <= 30:
        summary += " Oversolgt på kort sikt – historisk ofte et brukbart innkjøpspunkt for langsiktige sparere."
    if support:
        summary += f" Nærmeste støtte {(support['level'] / last - 1) * 100:+.1f} %"
        summary += f", motstand {(resistance['level'] / last - 1) * 100:+.1f} %." if resistance else "."
    elif resistance:
        summary += f" Nærmeste motstand {(resistance['level'] / last - 1) * 100:+.1f} %."

    import re
    nb = lambda t: re.sub(r"(\d)\.(\d)", r"\1,\2", t)  # noqa: E731  norsk desimalkomma
    summary = nb(summary)
    for x in sig:
        x["value"], x["text"] = nb(x["value"]), nb(x["text"])
    return {
        "as_of": s.index[-1].strftime("%Y-%m-%d"), "score": score, "verdict": verdict, "summary": summary,
        "trend_score": round(100 * t_score), "momentum_score": round(100 * m_score),
        "rsi": rsi_now, "macd": _f(macd_now, 5), "macd_signal": _f(sig_now, 5), "macd_hist": _f(hist_now, 5),
        "macd_cross": macd_cross, "ma_cross": ma_cross, "vs_sma20": _f(v20), "vs_sma50": _f(v50), "vs_sma200": _f(v200),
        "slope200_1m": _f(slope200), "trend_ann": _f(trend_ann), "r2": _f(r2, 3), "pct_b": _f(pct_b, 3), "bandwidth": _f(bandwidth),
        "bw_rank": _f(bw_rank, 2), "vol": _f(vol), "ret_1m": _f(ret1m), "ret_3m": _f(ret3m),
        "support": {"level": _f(support["level"]), "pct": _f(support["level"] / last - 1), "touches": support["touches"]} if support else None,
        "resistance": {"level": _f(resistance["level"]), "pct": _f(resistance["level"] / last - 1), "touches": resistance["touches"]} if resistance else None,
        "high52": _f(hi52), "low52": _f(lo52), "from_high52": _f(last / hi52 - 1), "from_low52": _f(last / lo52 - 1),
        "signals": sig,
    }
