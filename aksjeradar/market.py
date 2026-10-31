"""
Markedsanalyse: hvilke sektorer er i vinden, hvilke faller, og hvilke modellen tror er best posisjonert fremover.

Kildene er gratis kurser fra Yahoo:
  - sektor-ETF-er (SPDR, USA) og noen tema-ETF-er – sammenlignet mot S&P 500 (SPY)
  - regionale ETF-er omregnet til NOK
  - nøkkeltall: VIX (uro), amerikansk 10-årsrente, Brent-olje, gull, USD/NOK og EUR/NOK
  - aksjeanalysen i Aksjeradar per sektor: andel aksjer i opptrend, analytikernes kursmål, prising og vekst

«Status» beskriver hva som skjer nå (trend og relativ styrke). «Fremover-score» er en mekanisk vurdering
som veier momentum (som historisk har en tendens til å vare noen måneder), analytikernes forventninger,
prising, inntjeningsvekst og bredde. Det er ingen spådom – og ikke investeringsråd.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .storage import clean_for_json

log = logging.getLogger("aksjeradar.market")

STATUS_ORDER = ["I vinden", "Snur opp", "Nøytral", "Svekkes", "Nedgående"]


def _num(x):
    try:
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return None


def _close(df: pd.DataFrame | None) -> pd.Series | None:
    if df is None or df.empty or "Close" not in df:
        return None
    s = df["Close"].astype(float).copy()
    s.index = pd.to_datetime(s.index).normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index().dropna()
    return s if len(s) > 30 else None


def _ret(s: pd.Series, n: int):
    return (float(s.iloc[-1]) / float(s.iloc[-1 - n]) - 1) if s is not None and len(s) > n else None


def _clip01(x):
    return max(0.0, min(1.0, x))


def _trend(s: pd.Series) -> dict:
    sma200 = s.rolling(200).mean()
    sma50 = s.rolling(50).mean()
    last = float(s.iloc[-1])
    v200 = _num(last / sma200.iloc[-1] - 1) if len(s) >= 200 else None
    v50 = _num(last / sma50.iloc[-1] - 1) if len(s) >= 50 else None
    golden = bool(len(s) >= 200 and sma50.iloc[-1] > sma200.iloc[-1])
    slope50 = _num(sma50.iloc[-1] / sma50.iloc[-21] - 1) if len(s) >= 71 else None
    return {"vs_sma200": v200, "vs_sma50": v50, "sma50_over_200": golden, "sma50_slope_1m": slope50}


def _status(rel1m, rel3m, tr) -> str:
    v200, v50, gold = tr.get("vs_sma200"), tr.get("vs_sma50"), tr.get("sma50_over_200")
    if v200 is None:
        return "Nøytral"
    if v200 > 0 and gold and (rel3m or 0) > 0.02:
        return "I vinden" if (v50 or 0) > -0.02 else "Svekkes"
    if v200 < 0 and (not gold or (rel3m or 0) < -0.02):
        return "Snur opp" if ((v50 or 0) > 0 and (rel1m or 0) > 0.01) else "Nedgående"
    if v200 > 0 and (v50 or 0) < -0.01 and (rel1m or 0) < -0.01:
        return "Svekkes"
    if v200 < 0 and (v50 or 0) > 0:
        return "Snur opp"
    return "Nøytral"


def _universe_view(table: pd.DataFrame | None, sector: str | None) -> dict | None:
    if table is None or table.empty or not sector or "sector" not in table:
        return None
    sub = table[table["sector"] == sector]
    if len(sub) < 4:
        return None
    col = lambda c: pd.to_numeric(sub[c], errors="coerce") if c in sub else pd.Series(dtype=float)  # noqa: E731
    pe = col("forwardPE"); pe = pe[(pe > 0) & (pe < 200)]
    pe_all = pd.to_numeric(table["forwardPE"], errors="coerce") if "forwardPE" in table else pd.Series(dtype=float)
    pe_all = pe_all[(pe_all > 0) & (pe_all < 200)]
    eg, rg, up = col("earningsGrowth").dropna(), col("revenueGrowth").dropna(), col("upside").dropna()
    med = lambda s: float(s.median()) if len(s) >= 3 else None  # noqa: E731
    return {
        "n": int(len(sub)),
        "breadth": float(sub["above_sma_slow"].fillna(False).astype(bool).mean()) if "above_sma_slow" in sub else None,
        "buy_share": float(sub["verdict"].isin(["Kjøp", "Sterkt kjøp"]).mean()) if "verdict" in sub else None,
        "avg_score": float(col("score").mean()) if "score" in sub else None,
        "median_upside": med(up),
        "median_fwd_pe": med(pe), "universe_fwd_pe": med(pe_all),
        "median_earnings_growth": med(eg.clip(-1, 3)), "median_revenue_growth": med(rg.clip(-1, 3)),
        "top": [{"ticker": r["ticker"], "name": str(r.get("name") or r["ticker"]), "verdict": r.get("verdict"), "score": _num(r.get("score"))}
                for _, r in sub.sort_values("score", ascending=False).head(5).iterrows()] if "score" in sub else [],
    }


def _forward_score(mom_rank: float | None, tr: dict, uv: dict | None) -> tuple[float, dict, list[str]]:
    parts, why = {}, []
    parts["momentum"] = None if mom_rank is None else 100 * mom_rank
    t = 0.0
    if tr.get("vs_sma200") is not None:
        t += 40 if tr["vs_sma200"] > 0 else 0
        t += 30 if tr.get("sma50_over_200") else 0
        t += 30 if (tr.get("sma50_slope_1m") or 0) > 0 else 0
        parts["trend"] = t
    else:
        parts["trend"] = None
    if uv:
        if uv.get("median_upside") is not None:
            parts["analysts"] = 100 * _clip01(uv["median_upside"] / 0.25)
            why.append(f"analytikernes kursmål {uv['median_upside'] * 100:+.0f} % (median)")
        if uv.get("median_fwd_pe") and uv.get("universe_fwd_pe"):
            rel = uv["median_fwd_pe"] / uv["universe_fwd_pe"]
            parts["valuation"] = 100 * _clip01((1.4 - rel) / 0.8)
            why.append(f"forventet P/E {uv['median_fwd_pe']:.0f} mot {uv['universe_fwd_pe']:.0f} i snitt" + (" – billig" if rel < 0.85 else " – dyrt" if rel > 1.2 else ""))
        g = uv.get("median_earnings_growth")
        if g is None:
            g = uv.get("median_revenue_growth")
        if g is not None:
            parts["growth"] = 100 * _clip01((g + 0.05) / 0.30)
            why.append(f"inntjeningsvekst {g * 100:+.0f} % (median)")
        if uv.get("breadth") is not None:
            parts["breadth"] = 100 * uv["breadth"]
            why.append(f"{uv['breadth'] * 100:.0f} % av {uv['n']} aksjer i opptrend")
    weights = {"momentum": 0.25, "trend": 0.15, "analysts": 0.20, "valuation": 0.15, "growth": 0.15, "breadth": 0.10}
    total = sum(w * (parts.get(k) if parts.get(k) is not None else 50.0) for k, w in weights.items())
    return round(total, 1), {k: (None if v is None else round(v, 1)) for k, v in parts.items()}, why


def _hist(s: pd.Series, bench: pd.Series | None, days: int) -> dict:
    h = s.tail(days)
    b = bench.reindex(h.index).ffill() if bench is not None else None
    sma = s.rolling(200).mean().reindex(h.index)
    r = lambda v: None if pd.isna(v) else round(float(v), 3)  # noqa: E731
    return {"dates": [d.strftime("%Y-%m-%d") for d in h.index], "nok": [r(v) for v in h],
            "idx": [r(v) for v in b] if b is not None else None, "sma200": [r(v) for v in sma]}


def run_market(cfg: dict, frames: dict[str, pd.DataFrame], table: pd.DataFrame | None = None) -> dict:
    mc = cfg.get("market") or {}
    days = int(mc.get("history_days", 520))
    bench_t = mc.get("benchmark", "SPY")
    bench = _close(frames.get(bench_t))
    usdnok = _close(frames.get("USDNOK=X"))

    # ---- sektorer og tema (i USD, mot S&P 500) ----
    rows = []
    for item in (mc.get("sectors") or []) + (mc.get("themes") or []):
        s = _close(frames.get(item["etf"]))
        if s is None:
            log.warning("Marked: mangler kurser for %s", item["etf"])
            continue
        r = {k: _ret(s, n) for k, n in (("1d", 1), ("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252))}
        b = {k: _ret(bench, n) for k, n in (("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252))} if bench is not None else {}
        rel = {k: (r[k] - b[k]) if (r.get(k) is not None and b.get(k) is not None) else None for k in ("1m", "3m", "6m", "1y")}
        mom = None
        if len(s) > 253 and bench is not None and len(bench) > 253:
            mom = (float(s.iloc[-22]) / float(s.iloc[-253]) - 1) - (float(bench.iloc[-22]) / float(bench.iloc[-253]) - 1)
        tr = _trend(s)
        rows.append({"id": item["id"], "name": item["name"], "etf": item["etf"], "kind": "tema" if item in (mc.get("themes") or []) else "sektor",
                     "sector": item.get("sector"), "note": item.get("note", ""), "funds": item.get("funds", []),
                     "ret": r, "rel": rel, "mom_12_1": mom, "trend": tr, "status": _status(rel["1m"], rel["3m"], tr),
                     "_s": s})
    # momentum-rangering (12–1 mnd, relativt til S&P 500)
    moms = sorted([x["mom_12_1"] for x in rows if x["mom_12_1"] is not None])
    for x in rows:
        mr = None
        if x["mom_12_1"] is not None and len(moms) > 1:
            mr = moms.index(x["mom_12_1"]) / (len(moms) - 1)
        uv = _universe_view(table, x["sector"])
        x["universe"] = uv
        x["forward"], x["forward_parts"], fwhy = _forward_score(mr, x["trend"], uv)
        why = []
        if x["rel"]["3m"] is not None:
            why.append(f"{x['rel']['3m'] * 100:+.1f} pp mot S&P 500 siste 3 mnd")
        if x["trend"]["vs_sma200"] is not None:
            why.append(("over" if x["trend"]["vs_sma200"] > 0 else "under") + f" 200-dagers snitt ({x['trend']['vs_sma200'] * 100:+.1f} %)")
        x["why_now"] = why
        x["why_forward"] = fwhy
        x["history"] = _hist(x.pop("_s"), bench, days)

    # ---- regioner (i NOK) ----
    regions = []
    for item in mc.get("regions") or []:
        s = _close(frames.get(item["etf"]))
        if s is None:
            continue
        cur = item.get("currency", "USD")
        if cur != "NOK" and not item.get("local"):
            fx = _close(frames.get(f"{cur}NOK=X"))
            if fx is not None:
                s = (s * fx.reindex(s.index, method="ffill")).dropna()
        tr = _trend(s)
        r = {k: _ret(s, n) for k, n in (("1d", 1), ("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252))}
        regions.append({"id": item["id"], "name": item["name"], "etf": item["etf"], "ret": r, "trend": tr,
                        "status": _status(None, None, tr) if tr["vs_sma200"] is not None else "Nøytral",
                        "funds": item.get("funds", []), "history": _hist(s, None, days)})
    for x in regions:   # regionstatus uten relativ styrke: enkel trendregel
        tr, r3 = x["trend"], x["ret"]["3m"] or 0
        if tr["vs_sma200"] is None:
            x["status"] = "Nøytral"
        elif tr["vs_sma200"] > 0 and tr["sma50_over_200"] and r3 > 0:
            x["status"] = "I vinden"
        elif tr["vs_sma200"] < 0 and r3 < 0:
            x["status"] = "Nedgående"
        elif tr["vs_sma200"] < 0:
            x["status"] = "Snur opp" if (tr["vs_sma50"] or 0) > 0 else "Nøytral"
        else:
            x["status"] = "Svekkes" if (tr["vs_sma50"] or 0) < -0.01 else "Nøytral"

    # ---- nøkkeltall og markedsregime ----
    macro = {}
    for item in mc.get("macro") or []:
        s = _close(frames.get(item["ticker"]))
        if s is None:
            continue
        macro[item["id"]] = {"name": item["name"], "ticker": item["ticker"], "last": float(s.iloc[-1]), "unit": item.get("unit", ""),
                             "chg_1m": _ret(s, 21), "chg_3m": _ret(s, 63), "chg_1y": _ret(s, 252),
                             "abs_1m": float(s.iloc[-1] - s.iloc[-22]) if len(s) > 22 else None,
                             "spark": [round(float(v), 3) for v in s.tail(66)]}
    breadth = None
    if table is not None and not table.empty and "above_sma_slow" in table:
        breadth = float(table["above_sma_slow"].fillna(False).astype(bool).mean())
    spx_tr = _trend(bench) if bench is not None else {}
    vix = (macro.get("vix") or {}).get("last")
    pts = 0
    pts += 1 if (spx_tr.get("vs_sma200") or 0) > 0 else -1
    pts += 1 if spx_tr.get("sma50_over_200") else -1
    if breadth is not None:
        pts += 1 if breadth > 0.55 else (-1 if breadth < 0.40 else 0)
    if vix is not None:
        pts += 1 if vix < 17 else (-1 if vix > 25 else 0)
    regime = "Risikovilje" if pts >= 2 else ("Forsiktig" if pts <= -2 else "Blandet")
    n_up = sum(1 for x in rows if x["kind"] == "sektor" and x["status"] in ("I vinden", "Snur opp"))
    n_dn = sum(1 for x in rows if x["kind"] == "sektor" and x["status"] in ("Nedgående", "Svekkes"))

    # ---- oppsummering i tekst ----
    sect = [x for x in rows if x["kind"] == "sektor"]
    lead = sorted([x for x in sect if x["rel"]["3m"] is not None], key=lambda x: -x["rel"]["3m"])
    fwd = sorted(sect, key=lambda x: -x["forward"])
    txt = []
    spx_1m = _ret(bench, 21) if bench is not None else None
    t0 = f"Markedet er i en fase med {regime.lower()}" if regime != "Blandet" else "Markedsbildet er blandet"
    if spx_1m is not None:
        t0 += f": S&P 500 er {spx_1m * 100:+.1f} % siste måned"
    if spx_tr.get("vs_sma200") is not None:
        t0 += f" og {'over' if spx_tr['vs_sma200'] > 0 else 'under'} 200-dagers snittet"
    t0 += "."
    if breadth is not None:
        t0 += f" {breadth * 100:.0f} % av aksjene Aksjeradar følger er i opptrend."
    if vix is not None:
        t0 += f" Uroindeksen VIX står i {vix:.0f} ({'rolig' if vix < 17 else 'urolig' if vix > 25 else 'normalt'})."
    txt.append(t0)
    if lead:
        txt.append("Sterkest siste 3 måneder: " + ", ".join(f"{x['name'].lower()} ({x['rel']['3m'] * 100:+.0f} pp)" for x in lead[:3])
                   + ". Svakest: " + ", ".join(f"{x['name'].lower()} ({x['rel']['3m'] * 100:+.0f} pp)" for x in lead[-3:][::-1]) + " – målt mot S&P 500.")
    rate = macro.get("rate10")
    if rate and rate.get("abs_1m") is not None:
        txt.append(f"Den amerikanske 10-årsrenten er {rate['last']:.2f} % ({rate['abs_1m']:+.2f} prosentpoeng siste måned)"
                   + (" – stigende renter er motvind for teknologi og eiendom." if rate["abs_1m"] > 0.15 else " – fallende renter er medvind for vekstaksjer og eiendom." if rate["abs_1m"] < -0.15 else "."))
    usd = macro.get("usdnok")
    if usd and usd.get("chg_1m") is not None:
        txt.append(f"Dollaren koster {usd['last']:.2f} kr ({usd['chg_1m'] * 100:+.1f} % siste måned)"
                   + (" – en sterkere krone trekker ned avkastningen på utenlandske fond målt i NOK." if usd["chg_1m"] < -0.015 else " – en svakere krone løfter utenlandske fond målt i NOK." if usd["chg_1m"] > 0.015 else "."))
    if fwd:
        txt.append("Modellen gir høyest fremover-score til " + ", ".join(f"{x['name'].lower()} ({x['forward']:.0f})" for x in fwd[:3])
                   + " – en blanding av momentum, analytikernes forventninger, prising og vekst.")

    import re
    nf = lambda t: re.sub(r"(?<![\w.])-(?=\d)", "−", re.sub(r"(\d)\.(\d)", r"\1,\2", t))  # norsk tallformat  # noqa: E731
    txt = [nf(t) for t in txt]
    for x in rows:
        x["why_now"] = [nf(t) for t in x["why_now"]]
        x["why_forward"] = [nf(t) for t in x["why_forward"]]
    rows.sort(key=lambda x: -x["forward"])
    return clean_for_json({
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": bench.index[-1].strftime("%Y-%m-%d") if bench is not None else None,
        "benchmark": bench_t,
        "regime": regime, "regime_points": pts, "breadth": breadth, "spx": {"ret_1m": spx_1m, "ret_1y": _ret(bench, 252) if bench is not None else None, **spx_tr},
        "n_up": n_up, "n_down": n_dn,
        "summary": txt, "macro": macro, "sectors": rows, "regions": regions,
        "status_order": STATUS_ORDER,
    })
