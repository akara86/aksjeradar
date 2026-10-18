"""
Fondsmodul: finner gunstige innganger i aksjefond ut fra midlertidige fall i andelskurs (i NOK) og valuta.

Norske fond finnes knapt hos Yahoo, så hvert fond kobles til en børsnotert ETF som følger samme indeks
(config.yaml under `funds.list`). ETF-kursen × valutakurs ≈ fondets kurs i NOK (minus honorar, og
andelskursen settes gjerne én dag senere). For hvert fond regnes:

  - fall fra 52-ukers topp og fra siste 3-måneders topp, målt i NOK
  - avstand til 200- og 50-dagers snitt, RSI(14), avkastning 1 mnd / 3 mnd / 1 år
  - hvor mye av bevegelsen som skyldes indeksen og hvor mye kronekursen
  - valutabilde: kronen sterk eller svak mot sitt eget 200-dagers snitt og siste års intervall
  - en inngangsscore (0–100) og et nivå: Svært gunstig / Gunstig / Nøytral / Dyr

Et varsel lages når nivået skifter til (eller fra) Gunstig/Svært gunstig siden forrige kjøring.
Dette er en mekanisk vurdering av om et fond er «på salg» i forhold til nylig historikk –
ikke en spådom om at fallet er midlertidig, og ikke investeringsråd.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .storage import Storage, clean_for_json

log = logging.getLogger("aksjeradar.funds")

LEVELS = ["Svært gunstig", "Gunstig", "Nøytral", "Dyr"]


def _num(x):
    try:
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return None


def _rsi(close: pd.Series, n: int = 14):
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    if l.empty or pd.isna(l.iloc[-1]):
        return None
    if l.iloc[-1] == 0:
        return 100.0
    return float(100 - 100 / (1 + g.iloc[-1] / l.iloc[-1]))


def fx_series(fx_frames: dict[str, pd.DataFrame], currency: str) -> pd.Series | None:
    if currency == "NOK":
        return None
    df = fx_frames.get(f"{currency}NOK=X")
    if df is None or df.empty:
        return None
    s = df["Close"].astype(float)
    s.index = pd.to_datetime(s.index).normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def analyze_fund(f: dict, proxy: pd.DataFrame, fx: pd.Series | None, th: dict, history_days: int = 130) -> dict:
    """Metrikker for ett fond. `proxy` = daglige kurser for ETF-en, `fx` = valutakurs til NOK (None = ingen omregning)."""
    px = proxy["Close"].astype(float).copy()
    px.index = pd.to_datetime(px.index).normalize()
    px = px[~px.index.duplicated(keep="last")].sort_index()
    hedged = bool(f.get("hedged"))
    fx_relevant = (fx is not None) and not hedged and f.get("fx_relevant", True)
    if fx is not None and not hedged:
        fxa = fx.reindex(px.index, method="ffill")
        nok = (px * fxa).dropna()
    else:
        fxa = None
        nok = px
    nok = nok.dropna()
    last = float(nok.iloc[-1])
    sma200 = _num(nok.rolling(200).mean().iloc[-1])
    sma50 = _num(nok.rolling(50).mean().iloc[-1])
    high52 = float(nok.tail(252).max())
    high3m = float(nok.tail(63).max())
    low52 = float(nok.tail(252).min())

    def ret(s: pd.Series, n: int):
        return (float(s.iloc[-1]) / float(s.iloc[-1 - n]) - 1) if len(s) > n else None

    idx_ret = {k: ret(px, n) for k, n in (("1m", 21), ("3m", 63), ("1y", 252))}
    nok_ret = {k: ret(nok, n) for k, n in (("1m", 21), ("3m", 63), ("1y", 252))}
    fx_last = fx_sma200 = fx_vs_sma200 = fx_rank = fx_ret_1m = None
    if fx is not None and len(fx):
        fx_last = float(fx.iloc[-1])
        fx_sma200 = _num(fx.rolling(200).mean().iloc[-1])
        fx_vs_sma200 = (fx_last / fx_sma200 - 1) if fx_sma200 else None
        lo, hi = float(fx.tail(252).min()), float(fx.tail(252).max())
        fx_rank = ((fx_last - lo) / (hi - lo)) if hi > lo else None   # 0 = kronen på sitt sterkeste siste år
        fx_ret_1m = ret(fx, 21)

    dd52 = last / high52 - 1
    dd3m = last / high3m - 1
    vs200 = (last / sma200 - 1) if sma200 else None
    vs50 = (last / sma50 - 1) if sma50 else None
    rsi = _rsi(nok.tail(120))

    # ---- inngangsscore 0–100 ----
    score = 0.0
    score += 50 * min(1.0, max(0.0, -dd52 / 0.20))                       # fall fra 52u-topp: 20 % = fullt
    score += 25 * min(1.0, max(0.0, -(vs200 or 0) / 0.12))               # under 200d-snitt: 12 % = fullt
    score += 10 * (1.0 if (rsi is not None and rsi < 30) else max(0.0, (50 - (rsi or 50)) / 20))
    if fx_relevant and fx_vs_sma200 is not None:
        score += 15 * min(1.0, max(0.0, -fx_vs_sma200 / 0.06))           # kronen 6 % sterkere enn snitt = fullt
    score = round(score, 1)

    good_dd = float(th.get("good_drawdown", -0.08))
    strong_dd = float(th.get("strong_drawdown", -0.15))
    if score >= 70 or dd52 <= strong_dd:
        level = "Svært gunstig"
    elif score >= 45 or dd52 <= good_dd:
        level = "Gunstig"
    elif dd52 >= -0.01 and (vs200 or 0) > 0.08 and (not fx_relevant or (fx_vs_sma200 or 0) > float(th.get("fx_expensive", 0.04))):
        level = "Dyr"
    else:
        level = "Nøytral"

    # ---- forklaring ----
    why = []
    why.append(f"{dd52 * 100:+.1f} % fra 52-ukers topp i NOK" if dd52 < -0.005 else "nær 52-ukers topp i NOK")
    if vs200 is not None:
        why.append(f"{vs200 * 100:+.1f} % mot 200-dagers snitt")
    if nok_ret["1m"] is not None and idx_ret["1m"] is not None:
        if fx_relevant and fx_ret_1m is not None:
            why.append(f"siste måned: indeks {idx_ret['1m'] * 100:+.1f} %, kronen {-fx_ret_1m * 100:+.1f} % (sum {nok_ret['1m'] * 100:+.1f} % i NOK)")
        else:
            why.append(f"siste måned {nok_ret['1m'] * 100:+.1f} %")
    if fx_relevant and fx_vs_sma200 is not None:
        if fx_vs_sma200 <= -0.02:
            why.append(f"kronen er {-fx_vs_sma200 * 100:.1f} % sterkere enn snittet mot {f.get('currency', 'USD')} – gunstig for kjøp")
        elif fx_vs_sma200 >= 0.03:
            why.append(f"kronen er {fx_vs_sma200 * 100:.1f} % svakere enn snittet mot {f.get('currency', 'USD')} – du betaler dyrt for valutaen")
    if rsi is not None and rsi < 32:
        why.append(f"RSI {rsi:.0f} – oversolgt")

    hist = nok.tail(history_days)
    idx_hist = px.reindex(hist.index).ffill()
    return {
        "id": f["id"], "name": f["name"], "examples": f.get("examples", ""), "proxy": f["proxy"], "currency": f.get("currency", "USD"),
        "hedged": hedged, "fx_relevant": fx_relevant,
        "last_date": hist.index[-1].strftime("%Y-%m-%d"),
        "price_nok": round(last, 2), "change_1d": ret(nok, 1), "proxy_change_1d": ret(px, 1),
        "dd_52w": dd52, "dd_3m": dd3m, "high_52w": high52, "low_52w": low52, "vs_sma200": vs200, "vs_sma50": vs50, "rsi": rsi,
        "ret_1m": nok_ret["1m"], "ret_3m": nok_ret["3m"], "ret_1y": nok_ret["1y"],
        "idx_ret_1m": idx_ret["1m"], "idx_ret_3m": idx_ret["3m"], "idx_ret_1y": idx_ret["1y"],
        "fx_last": fx_last, "fx_vs_sma200": fx_vs_sma200, "fx_rank_1y": fx_rank, "fx_ret_1m": fx_ret_1m,
        "score": score, "level": level, "why": why,
        "history": {"dates": [d.strftime("%Y-%m-%d") for d in hist.index],
                    "nok": [round(float(v), 2) for v in hist], "idx": [round(float(v), 2) for v in idx_hist]},
    }


def run_funds(store: Storage, cfg: dict, proxy_frames: dict[str, pd.DataFrame], fx_frames: dict[str, pd.DataFrame]) -> dict:
    fcfg = cfg["funds"]
    th = fcfg.get("thresholds", {})
    prev, _ = store.load_snapshot("funds", "levels")
    prev = prev or {}
    funds, alerts, levels = [], [], {}
    for i, f in enumerate(fcfg.get("list") or []):
        f = dict(f)
        f.setdefault("id", f"fond{i + 1}")
        f.setdefault("currency", "USD")
        proxy = proxy_frames.get(f["proxy"])
        if proxy is None or len(proxy) < 60:
            log.warning("Fond «%s»: mangler kurser for %s", f["name"], f["proxy"])
            continue
        try:
            a = analyze_fund(f, proxy, fx_series(fx_frames, f["currency"]), th, int(cfg["export"].get("history_days", 130)))
        except Exception as e:  # noqa: BLE001
            log.warning("Fond «%s» feilet: %s", f["name"], e)
            continue
        old = prev.get(f["id"])
        a["prev_level"] = old
        good_now = a["level"] in ("Gunstig", "Svært gunstig")
        good_before = old in ("Gunstig", "Svært gunstig")
        if old is not None and good_now and (not good_before or (a["level"] == "Svært gunstig" and old == "Gunstig")):
            alerts.append({"id": f["id"], "name": f["name"], "level": a["level"], "prev_level": old, "kind": "inngang",
                           "text": f"{f['name']}: {a['level'].lower()} inngang – {a['why'][0]}" + (f"; {a['why'][-1]}" if len(a["why"]) > 1 else "")})
        elif old is not None and good_before and not good_now:
            alerts.append({"id": f["id"], "name": f["name"], "level": a["level"], "prev_level": old, "kind": "tilbake",
                           "text": f"{f['name']}: ikke lenger gunstig inngang ({a['why'][0]})"})
        levels[f["id"]] = a["level"]
        funds.append(a)
    store.save_snapshot("funds", "levels", levels)
    funds.sort(key=lambda x: -x["score"])
    return clean_for_json({
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base": fcfg.get("base_currency", "NOK"),
        "funds": funds,
        "alerts": alerts,
        "thresholds": th,
    })
