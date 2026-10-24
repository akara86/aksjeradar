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
            why.append(f"siste måned: indeks {idx_ret['1m'] * 100:+.1f} %, kronen {abs(fx_ret_1m) * 100:.1f} % {'sterkere' if fx_ret_1m < 0 else 'svakere'} (sum {nok_ret['1m'] * 100:+.1f} % i NOK)")
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


# --------------------------------------------------------------------------
# Attraktivitet: inngang + trend + sektor/marked (fra aksjeanalysen) + risiko
# --------------------------------------------------------------------------
ATTR_VERDICTS = ["Attraktiv", "Nøytral", "Lite attraktiv"]


def _clip01(x):
    return max(0.0, min(1.0, x))


def market_view(f: dict, table: pd.DataFrame | None) -> dict | None:
    """Hvordan ser sektoren/markedet fondet dekker ut i aksjeuniverset? None hvis ingen kobling."""
    if table is None or table.empty:
        return None
    markets = f.get("markets") or []
    sectors = f.get("sectors") or []
    if not markets and not sectors:
        return None
    sub = table
    if markets and "alle" not in markets:
        sub = sub[sub["market"].isin(markets)]
    if sectors:
        sub = sub[sub["sector"].isin(sectors)]
    if len(sub) < 5:
        return None
    sc = pd.to_numeric(sub["score"], errors="coerce")
    up = pd.to_numeric(sub["upside"], errors="coerce")
    pe = pd.to_numeric(sub["forwardPE"], errors="coerce")
    pe = pe[(pe > 0) & (pe < 200)]
    pe_all = pd.to_numeric(table["forwardPE"], errors="coerce")
    pe_all = pe_all[(pe_all > 0) & (pe_all < 200)]
    breadth = float(sub["above_sma_slow"].fillna(False).astype(bool).mean())
    buy_share = float(sub["verdict"].isin(["Kjøp", "Sterkt kjøp"]).mean())
    weak_share = float(sub["verdict"].isin(["Avvent", "Unngå"]).mean())
    return {
        "n": int(len(sub)), "breadth": breadth, "buy_share": buy_share, "weak_share": weak_share,
        "avg_score": float(sc.mean()) if sc.notna().any() else None,
        "median_upside": float(up.median()) if up.notna().any() else None,
        "median_fwd_pe": float(pe.median()) if len(pe) else None,
        "universe_fwd_pe": float(pe_all.median()) if len(pe_all) else None,
        "golden": int(sub["golden_cross"].fillna(False).astype(bool).sum()),
        "death": int(sub["death_cross"].fillna(False).astype(bool).sum()),
    }


def attractiveness(a: dict, mv: dict | None, global_ret_1y: float | None, nok_series: pd.Series | None) -> dict:
    """Setter sammen attraktivitetsscore (0–100) av fire deler, med forklaring."""
    parts, why = {}, []

    # 1. Inngang (20 %) – «på salg»-scoren som bonus oppå et nøytralt nivå: nær topp = 40, dypt fall = 100
    parts["entry"] = 40 + 0.6 * float(a["score"])

    # 2. Trend (30 %)
    t = 0.0
    if a.get("vs_sma200") is not None:
        t += 40 if a["vs_sma200"] > 0 else 0
    if a.get("vs_sma50") is not None and a.get("vs_sma200") is not None:
        t += 20 if a["vs_sma50"] > a["vs_sma200"] * 0.5 and a["vs_sma50"] > -0.02 else 0
    if a.get("ret_3m") is not None:
        t += 20 if a["ret_3m"] > 0 else 0
    rel = None
    if a.get("ret_1y") is not None and global_ret_1y is not None:
        rel = a["ret_1y"] - global_ret_1y
        t += 20 * _clip01(0.5 + rel / 0.30)   # ±15 pp mot global = 0/20
    parts["trend"] = t
    if a.get("vs_sma200") is not None:
        why.append(("i opptrend (over 200-dagers snitt)" if a["vs_sma200"] > 0 else "under 200-dagers snitt – svak trend"))
    if rel is not None and abs(rel) >= 0.05:
        why.append(f"{'bedre' if rel > 0 else 'svakere'} enn globalt indeksfond siste år ({rel * 100:+.0f} pp)")

    # 3. Sektor/marked fra aksjeanalysen (25 %)
    if mv:
        m = 50 * mv["breadth"] + 30 * _clip01(((mv["avg_score"] or 50) - 40) / 25) + 20 * _clip01(mv["buy_share"] / 0.15)
        if mv["death"] > mv["golden"] + 2:
            m -= 10
        parts["market"] = max(0.0, min(100.0, m))
        why.append(f"sektor/marked: {mv['breadth'] * 100:.0f} % av {mv['n']} aksjer i opptrend, {mv['buy_share'] * 100:.0f} % med kjøpsanbefaling")
        if mv.get("median_upside") is not None:
            why.append(f"analytikernes kursmål {mv['median_upside'] * 100:+.0f} % (median)")
    else:
        parts["market"] = None
        why.append("ingen aksjedekning av dette markedet i universet – sektordelen holdes nøytral")

    # 4. Risiko og prising (15 %)
    vol = None
    if nok_series is not None and len(nok_series) > 70:
        r = nok_series.pct_change().tail(60).dropna()
        vol = float(r.std() * math.sqrt(252)) if len(r) > 20 else None
    rs = 100 * _clip01(1 - ((vol or 0.2) - 0.10) / 0.30)
    vs = 50.0
    if mv and mv.get("median_fwd_pe") and mv.get("universe_fwd_pe"):
        pe_rel = mv["median_fwd_pe"] / mv["universe_fwd_pe"]
        vs = 100 * _clip01((1.35 - pe_rel) / 0.7)   # 0,65× universet = 100, 1,35× = 0
        why.append(f"prising: forventet P/E {mv['median_fwd_pe']:.0f} mot {mv['universe_fwd_pe']:.0f} i hele universet")
    parts["risk"] = 0.6 * rs + 0.4 * vs
    if vol is not None:
        why.append(f"svingninger {vol * 100:.0f} % årlig" + (" – høy risiko" if vol > 0.28 else " – lav risiko" if vol < 0.14 else ""))

    weights = {"entry": 0.20, "trend": 0.35, "market": 0.30, "risk": 0.15}
    num = den = 0.0
    for k, w in weights.items():
        v = parts.get(k)
        if v is None:
            num += w * 50
        else:
            num += w * float(v)
        den += w
    total = round(num / den, 1)
    verdict = "Attraktiv" if total >= 60 else "Nøytral" if total >= 45 else "Lite attraktiv"
    return {"attr_score": total, "attr_verdict": verdict, "attr_parts": {k: (None if v is None else round(float(v), 1)) for k, v in parts.items()},
            "attr_why": why, "vol_1y": vol, "market_view": mv}


def advice_for(a: dict) -> str:
    """Kort, handlingsrettet råd for et fond du eier (langsiktig sparing – aldri «selg alt»)."""
    good_entry = a["level"] in ("Gunstig", "Svært gunstig")
    if a["attr_verdict"] == "Attraktiv":
        return "Godt tidspunkt å øke innskuddet" if good_entry else "Fortsett spareavtalen som planlagt"
    if a["attr_verdict"] == "Nøytral":
        return "Behold – vanlig sparing" if not good_entry else "Behold – prisen er grei, men trenden er svak"
    return "Vurder å pause nye innskudd til trenden snur" if not good_entry else "Billig, men svak trend – små, spredte kjøp"


# --------------------------------------------------------------------------
# Innskuddsråd: bør du sette inn ekstra penger i fondet nå?
# --------------------------------------------------------------------------
ACTIONS = {
    "boost": "Ekstrainnskudd anbefales",
    "consider": "Vurder ekstrainnskudd",
    "regular": "Fortsett vanlig sparing",
    "wait": "Avvent ekstrainnskudd",
}


def _pct(x, nd=0, sign=True):
    if x is None:
        return "–"
    return (f"{x * 100:+.{nd}f} %" if sign else f"{abs(x) * 100:.{nd}f} %").replace("-", "−").replace(".", ",")


def _kr(x):
    return "–" if x is None else f"{x:,.0f} kr".replace(",", " ")


def deposit_advice(a: dict, th: dict) -> dict:
    """Konkret råd om ekstrainnskudd ut fra inngang (hvor «på salg» fondet er) og attraktivitet (trend, sektor, risiko)."""
    level, attr = a["level"], a.get("attr_verdict") or "Nøytral"
    good = level in ("Gunstig", "Svært gunstig")
    strong = level == "Svært gunstig"
    dd = a.get("dd_52w") or 0.0
    reasons, cautions = [], []

    if good:
        reasons.append(f"fondet er {_pct(dd, 0, False)} under 52-ukers topp i NOK" if dd < -0.005 else "inngangsscoren er høy")
    if a.get("fx_relevant") and a.get("fx_vs_sma200") is not None:
        if a["fx_vs_sma200"] <= -0.02:
            reasons.append(f"kronen er {_pct(-a['fx_vs_sma200'], 1, False)} sterkere enn snittet – du får mer for pengene")
        elif a["fx_vs_sma200"] >= 0.03:
            cautions.append(f"kronen er {_pct(a['fx_vs_sma200'], 1, False)} svakere enn snittet – valutaen er dyr")
    if a.get("vs_sma200") is not None:
        (reasons if a["vs_sma200"] > 0 else cautions).append(
            "i opptrend (over 200-dagers snitt)" if a["vs_sma200"] > 0 else f"under 200-dagers snitt ({_pct(a['vs_sma200'], 1)}) – trenden er svak")
    mv = a.get("market_view")
    if mv:
        if mv["breadth"] >= 0.6:
            reasons.append(f"{mv['breadth'] * 100:.0f} % av aksjene i sektoren/markedet er i opptrend")
        elif mv["breadth"] <= 0.4:
            cautions.append(f"bare {mv['breadth'] * 100:.0f} % av aksjene i sektoren/markedet er i opptrend")
    if a.get("ret_1m") is not None and a["ret_1m"] <= -0.08:
        cautions.append(f"fallet er bratt ({_pct(a['ret_1m'], 0)} siste måned) – det kan fortsette")
    if a.get("rsi") is not None and a["rsi"] < 32:
        reasons.append(f"RSI {a['rsi']:.0f} – oversolgt på kort sikt")
    if a.get("vol_1y") is not None and a["vol_1y"] > 0.28:
        cautions.append(f"høye svingninger ({a['vol_1y'] * 100:.0f} % årlig) – hold posisjonen som satellitt")

    if strong and attr != "Lite attraktiv":
        code, size = "boost", "f.eks. 2–3 ganger det du sparer månedlig, gjerne delt i to kjøp med noen ukers mellomrom"
    elif strong:
        code, size = "consider", "et mindre beløp delt i flere kjøp – billig, men trenden er svak"
    elif good and attr == "Attraktiv":
        code, size = "boost", "f.eks. 1–2 ganger det du sparer månedlig"
    elif good and attr == "Nøytral":
        code, size = "consider", "f.eks. én ekstra månedssparing – eller vent på et dypere fall"
    elif good:
        code, size = "consider", "små, spredte kjøp – prisen er grei, men trenden og sektoren er svak"
    elif level == "Dyr":
        code, size = "wait", None
        cautions.insert(0, "fondet er nær toppen, langt over 200-dagers snitt" + (" og kronen er svak" if a.get("fx_relevant") else ""))
    else:
        code, size = "regular", None
        if attr == "Lite attraktiv":
            cautions.insert(0, "ikke på salg, og trend/sektor er svak, så ingen grunn til å forsere")
        else:
            reasons.insert(0, "ikke spesielt billig nå, spareavtalen gjør jobben")

    summary = ACTIONS[code]
    key = (cautions or reasons) if code == "wait" else (reasons or cautions)
    if key:
        summary += " – " + key[0]
    return {"code": code, "action": ACTIONS[code], "size": size, "reasons": reasons[:4], "cautions": cautions[:3], "summary": summary}


def fund_narrative(a: dict, dep: dict, th: dict) -> dict:
    """Daglig tekstanalyse per fond: status, indeks/krone, trend, sektor, risiko, konklusjon og hva som ville endret rådet."""
    secs = []
    cur = a.get("currency", "USD")
    name = a["name"]
    last = a.get("price_nok")
    good_dd = float(th.get("good_drawdown", -0.08))
    strong_dd = float(th.get("strong_drawdown", -0.15))
    high52 = a.get("high_52w")

    # Status
    t = f"{name} står i {_kr(last)} per andel (ETF-en {a['proxy']} omregnet til NOK), {_pct(a.get('change_1d'), 1)} siste dag. "
    t += f"Siste måned {_pct(a.get('ret_1m'), 1)}, tre måneder {_pct(a.get('ret_3m'), 1)} og ett år {_pct(a.get('ret_1y'), 1)} i NOK. "
    dd = a.get("dd_52w")
    if dd is not None:
        t += (f"Fondet er {_pct(dd, 1, False)} under toppen fra siste 52 uker" if dd < -0.005 else "Fondet er på eller nær toppen fra siste 52 uker")
        t += f" og {_pct(a.get('vs_sma200'), 1)} mot 200-dagers snitt." if a.get("vs_sma200") is not None else "."
    secs.append({"h": "Status", "t": t})

    # Indeks og krone
    if a.get("hedged"):
        t = f"Fondet er valutasikret, så kronekursen påvirker ikke avkastningen – bare indeksen teller. Indeksen er {_pct(a.get('idx_ret_1m'), 1)} siste måned."
    elif not a.get("fx_relevant"):
        t = f"Fondet eier norske aksjer, så valutaen spiller ingen rolle for deg. Indeksen er {_pct(a.get('idx_ret_1m'), 1)} siste måned og {_pct(a.get('idx_ret_1y'), 1)} siste år."
    else:
        fxm = a.get("fx_ret_1m")
        t = f"Indeksen i {cur} er {_pct(a.get('idx_ret_1m'), 1)} siste måned"
        if fxm is not None:
            t += f", mens kronen er {_pct(fxm, 1, False)} {'sterkere' if fxm < 0 else 'svakere'} mot {cur} – til sammen {_pct(a.get('ret_1m'), 1)} i NOK"
        t += ". "
        fx = a.get("fx_vs_sma200")
        if fx is not None:
            if fx <= -0.02:
                t += f"Kronen er {_pct(-fx, 1, False)} sterkere enn sitt 200-dagers snitt mot {cur}. En sterk krone betyr at du får flere {cur} for hver krone du setter inn – det er en fordel for nye kjøp i utenlandske fond, og en medvind for avkastningen hvis kronen senere svekker seg igjen."
            elif fx >= 0.03:
                t += f"Kronen er {_pct(fx, 1, False)} svakere enn sitt 200-dagers snitt mot {cur}. Da betaler du dyrt for valutaen, og en senere kronestyrking vil trekke ned avkastningen målt i NOK."
            else:
                t += f"Kronen ligger nær sitt 200-dagers snitt mot {cur} – valutaen gir verken med- eller motvind akkurat nå."
        rk = a.get("fx_rank_1y")
        if rk is not None:
            t += f" I løpet av siste år har kronen vært {'nær sitt sterkeste' if rk <= 0.2 else 'nær sitt svakeste' if rk >= 0.8 else 'midt i intervallet'} mot {cur}."
    secs.append({"h": "Indeks og krone", "t": t})

    # Trend
    v200, v50 = a.get("vs_sma200"), a.get("vs_sma50")
    if v200 is not None:
        t = ("Fondet er i opptrend: kursen ligger over 200-dagers snittet" if v200 > 0 else "Trenden er svak: kursen ligger under 200-dagers snittet")
        if v50 is not None:
            t += (", og 50-dagers snittet peker " + ("samme vei. " if (v50 > 0) == (v200 > 0) else "motsatt vei – trenden kan være i ferd med å snu. "))
        else:
            t += ". "
        r3 = a.get("ret_3m")
        if r3 is not None:
            t += f"Siste tre måneder er fondet {_pct(r3, 1)}. "
        rsi = a.get("rsi")
        if rsi is not None:
            t += f"RSI på {rsi:.0f} " + ("tyder på at fondet er oversolgt på kort sikt." if rsi < 32 else "tyder på at fondet er overkjøpt på kort sikt." if rsi > 70 else "er nøytralt.")
        secs.append({"h": "Trend", "t": t})

    # Sektor og marked
    mv = a.get("market_view")
    if mv:
        t = f"Blant de {mv['n']} aksjene i Aksjeradars univers som dekker dette markedet/sektoren er {mv['breadth'] * 100:.0f} % i opptrend og {mv['buy_share'] * 100:.0f} % har kjøpsanbefaling"
        if mv.get("avg_score") is not None:
            t += f" (snittscore {mv['avg_score']:.0f})"
        t += ". "
        if mv.get("median_upside") is not None:
            t += f"Analytikernes kursmål ligger i snitt {_pct(mv['median_upside'], 0)} over dagens kurser. "
        if mv.get("median_fwd_pe") and mv.get("universe_fwd_pe"):
            rel = mv["median_fwd_pe"] / mv["universe_fwd_pe"]
            t += f"Prisingen (forventet P/E {mv['median_fwd_pe']:.0f}) er {'høyere' if rel > 1.1 else 'lavere' if rel < 0.9 else 'omtrent som'} {'enn ' if rel > 1.1 or rel < 0.9 else ''}resten av universet ({mv['universe_fwd_pe']:.0f})."
        secs.append({"h": "Sektor og marked", "t": t})
    else:
        secs.append({"h": "Sektor og marked", "t": "Aksjeuniverset dekker ikke dette markedet, så sektordelen holdes nøytral i vurderingen."})

    # Risiko og rolle
    vol = a.get("vol_1y")
    t = ""
    if vol is not None:
        t += f"Fondet svinger {vol * 100:.0f} % årlig – " + ("høy risiko, egnet som en mindre satellitt. " if vol > 0.28 else "lav risiko. " if vol < 0.14 else "moderat risiko. ")
    role = a.get("role") or "satellitt"
    t += ("Som kjernefond bør det stå for brorparten av sparingen uansett timing." if role == "kjerne" else "Som satellitt bør det utgjøre en mindre del av fondsporteføljen, slik at et vedvarende fall ikke velter totalen.")
    secs.append({"h": "Risiko og rolle", "t": t})

    # Konklusjon
    t = f"{dep['action']}. "
    if dep["reasons"]:
        t += "For: " + "; ".join(dep["reasons"]) + ". "
    if dep["cautions"]:
        t += "Mot: " + "; ".join(dep["cautions"]) + ". "
    if dep["size"]:
        t += f"Størrelse: {dep['size']}. "
    if dep["code"] in ("boost", "consider"):
        t += "Et ekstrainnskudd er ikke en garanti for at bunnen er nådd – del gjerne opp beløpet, og hold deg til spareavtalen i tillegg."
    elif dep["code"] == "wait":
        t += "Spareavtalen fortsetter som normalt – det er ekstra penger som bør vente på et bedre tidspunkt."
    else:
        t += "Fast månedlig sparing fanger opp fallene automatisk; ekstra innskudd er først interessant når fondet er tydelig på salg."
    secs.append({"h": "Konklusjon", "t": t})

    # Hva som ville endret vurderingen (konkrete nivåer)
    triggers = []
    if high52 and last:
        lv_good = high52 * (1 + good_dd)
        lv_strong = high52 * (1 + strong_dd)
        if a["level"] not in ("Gunstig", "Svært gunstig"):
            triggers.append(f"Gunstig inngang ved ca. {_kr(lv_good)} ({_pct(lv_good / last - 1, 1)} fra i dag)")
        if a["level"] != "Svært gunstig":
            triggers.append(f"Svært gunstig ved ca. {_kr(lv_strong)} ({_pct(lv_strong / last - 1, 1)})")
        if a["level"] in ("Gunstig", "Svært gunstig"):
            triggers.append(f"Ikke lenger gunstig hvis kursen stiger over ca. {_kr(lv_good)} ({_pct(lv_good / last - 1, 1)})")
    if v200 is not None and last:
        sma = last / (1 + v200)
        triggers.append((f"Trenden regnes som svak hvis kursen faller under 200-dagers snittet på ca. {_kr(sma)}" if v200 > 0
                         else f"Trenden snur til positiv hvis kursen stiger over 200-dagers snittet på ca. {_kr(sma)}"))
    if a.get("fx_relevant") and a.get("fx_last") and a.get("fx_vs_sma200") is not None:
        sma_fx = a["fx_last"] / (1 + a["fx_vs_sma200"])
        triggers.append(f"Kronen regnes som sterk under {sma_fx * 0.98:.2f} {cur}NOK og svak over {sma_fx * 1.03:.2f} (nå {a['fx_last']:.2f})".replace(".", ","))
    if not a.get("hedged") and a.get("fx_relevant") and a.get("fx_vs_sma200") is not None and a["fx_vs_sma200"] >= 0.03:
        triggers.append("En sterkere krone ville gjort inngangen bedre")
    secs.append({"h": "Hva som ville endret vurderingen", "t": " · ".join(triggers) if triggers else "Nivåene oppdateres daglig."})

    return {"date": a.get("last_date"), "sections": secs, "triggers": triggers}


def run_funds(store: Storage, cfg: dict, proxy_frames: dict[str, pd.DataFrame], fx_frames: dict[str, pd.DataFrame],
              table: pd.DataFrame | None = None) -> dict:
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
            a = analyze_fund(f, proxy, fx_series(fx_frames, f["currency"]), th, 130)  # fondskurven holdes på ~6 mnd (ligger i data.json)
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
        a["_cfg"] = f
        a["_nok"] = None
        try:
            px = proxy["Close"].astype(float).copy()
            px.index = pd.to_datetime(px.index).normalize()
            fxs = fx_series(fx_frames, f["currency"])
            a["_nok"] = (px * fxs.reindex(px.index, method="ffill")).dropna() if (fxs is not None and not f.get("hedged")) else px
        except Exception:  # noqa: BLE001
            pass
        funds.append(a)
    store.save_snapshot("funds", "levels", levels)

    # Attraktivitet og rangering
    glob = next((x for x in funds if x["id"] in ("klp_global", "global")), None)
    global_ret_1y = glob["ret_1y"] if glob else None
    for a in funds:
        f = a.pop("_cfg")
        nok = a.pop("_nok")
        mv = market_view(f, table)
        a.update(attractiveness(a, mv, global_ret_1y, nok))
        a["owned"] = bool(f.get("owned"))
        a["role"] = f.get("role") or ("kjerne" if f.get("core") else "satellitt")
        a["deposit"] = deposit_advice(a, th)
        a["advice"] = a["deposit"]["action"] if a["owned"] else None
        a["analysis"] = fund_narrative(a, a["deposit"], th)
    funds.sort(key=lambda x: -x["attr_score"])
    for i, a in enumerate(funds, start=1):
        a["rank"] = i

    # Dagbok: ett innslag per kursdato, så appen kan vise hvordan rådene har utviklet seg – og varsle når rådet endres
    journal, _ = store.load_snapshot("funds", "journal")
    journal = dict(journal or {})
    day = max((a["last_date"] for a in funds), default=None)
    if day:
        prev_days = sorted(d for d in journal if d < day)
        prev_entry = journal[prev_days[-1]] if prev_days else {}
        entry = {}
        for a in funds:
            pe = prev_entry.get(a["id"]) or {}
            a["deposit"]["prev_code"] = pe.get("code")
            a["deposit"]["changed"] = bool(pe.get("code")) and pe["code"] != a["deposit"]["code"]
            entry[a["id"]] = {"code": a["deposit"]["code"], "level": a["level"], "attr": a["attr_verdict"], "price_nok": a["price_nok"],
                              "change_1d": a.get("change_1d"), "dd_52w": a.get("dd_52w"), "owned": a["owned"], "name": a["name"]}
            if a["owned"] and a["deposit"]["changed"]:
                up = a["deposit"]["code"] in ("boost", "consider")
                alerts.append({"id": a["id"], "name": a["name"], "kind": "innskudd" if up else "innskudd_slutt", "level": a["level"],
                               "code": a["deposit"]["code"], "prev_code": pe["code"],
                               "text": f"{a['name']}: {a['deposit']['summary']}" + (f" (var: {ACTIONS.get(pe['code'], pe['code']).lower()})")})
        journal[day] = entry
        keep = sorted(journal)[-45:]
        journal = {d: journal[d] for d in keep}
        store.save_snapshot("funds", "journal", journal)
    journal_out = []
    for d in sorted(journal, reverse=True)[:30]:
        rows = []
        days_before = sorted(x for x in journal if x < d)
        before = journal[days_before[-1]] if days_before else {}
        for fid, e in journal[d].items():
            if not e.get("owned"):
                continue
            pc = (before.get(fid) or {}).get("code")
            rows.append({"id": fid, "name": e.get("name"), "code": e["code"], "action": ACTIONS.get(e["code"], e["code"]), "level": e["level"],
                         "price_nok": e.get("price_nok"), "change_1d": e.get("change_1d"), "dd_52w": e.get("dd_52w"), "changed": bool(pc) and pc != e["code"]})
        if rows:
            journal_out.append({"date": d, "funds": rows})
    return clean_for_json({
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base": fcfg.get("base_currency", "NOK"),
        "alerts": alerts,
        "journal": journal_out,
        "actions": ACTIONS,
        "thresholds": th,
        "funds": funds,   # den store lista sist, så resten er lett å lese i fila
    })
