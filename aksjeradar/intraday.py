"""
Intradag-modul: kortsiktige «setups» på 15-minutters kurser, med nivåer og etterprøving.

Kjøres hvert 15. minutt i børstiden (intraday_run.py). For hver aksje i intradag-universet:
  - gap ved åpning, åpningsintervall (første 30 min), VWAP, relativt volum mot samme klokkeslett
    tidligere dager, 15m-RSI, momentum siste time, nye dagshøyder
  - fire setup-typer (bare long): Gap-and-go, Åpningsbrudd, VWAP-reclaim, Trenddag
  - hvert setup får inngang, stop, mål (target_r × risiko), score og utløpstid (børsens stenging)

Etterprøving: hvert setup logges første gang det ses. Etter stenging sjekkes kursene som fulgte:
traff stoppen først (-1 R), målet først (+target_r R), eller ingen av delene (resultat ved stenging).
Statistikken (treffprosent, snitt R) vises i appen – det er det som avslører om reglene virker.

Kursdata fra Yahoo er ca. 15 min forsinket. Dette er ikke investeringsråd.
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from .config import market_of
from .storage import Storage, clean_for_json

log = logging.getLogger("aksjeradar.intraday")

MARKETS = {
    "Oslo": {"tz": "Europe/Oslo", "open": time(9, 0), "close": time(16, 20)},
    "Stockholm": {"tz": "Europe/Stockholm", "open": time(9, 0), "close": time(17, 30)},
    "København": {"tz": "Europe/Copenhagen", "open": time(9, 0), "close": time(17, 0)},
    "Helsinki": {"tz": "Europe/Helsinki", "open": time(10, 0), "close": time(18, 30)},
    "USA": {"tz": "America/New_York", "open": time(9, 30), "close": time(16, 0)},
}
TYPES = {
    "gap": "Gap-and-go",
    "orb": "Åpningsbrudd",
    "vwap": "VWAP-reclaim",
    "trend": "Trenddag",
}


def _num(x):
    try:
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return None


EXTRA_TZ = {".DE": "Europe/Berlin", ".AS": "Europe/Amsterdam", ".PA": "Europe/Paris", ".L": "Europe/London",
            ".MI": "Europe/Rome", ".SW": "Europe/Zurich", "=X": "Europe/Oslo"}


def tz_for(ticker: str) -> str:
    t = ticker.upper()
    for suf, tz in EXTRA_TZ.items():
        if t.endswith(suf):
            return tz
    return MARKETS[market_of(t)]["tz"]


# --------------------------------------------------------------------------
# Marked: åpent/stengt
# --------------------------------------------------------------------------
def market_status(market: str, now_utc: datetime) -> dict:
    m = MARKETS[market]
    tz = ZoneInfo(m["tz"])
    local = now_utc.astimezone(tz)
    is_weekday = local.weekday() < 5
    open_dt = local.replace(hour=m["open"].hour, minute=m["open"].minute, second=0, microsecond=0)
    close_dt = local.replace(hour=m["close"].hour, minute=m["close"].minute, second=0, microsecond=0)
    is_open = is_weekday and open_dt <= local < close_dt
    return {
        "market": market, "open": is_open, "local_time": local.strftime("%H:%M"),
        "opens_at": m["open"].strftime("%H:%M"), "closes_at": m["close"].strftime("%H:%M"), "tz": m["tz"],
        "close_utc": close_dt.astimezone(timezone.utc).isoformat() if is_weekday else None,
        "session_date": local.strftime("%Y-%m-%d"),
    }


# --------------------------------------------------------------------------
# Datahenting (15m)
# --------------------------------------------------------------------------
def fetch_intraday(tickers: list[str], interval: str = "15m", period: str = "5d", batch_size: int = 60) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), batch_size):
        chunk = tickers[i:i + batch_size]
        try:
            raw = yf.download(chunk, period=period, interval=interval, group_by="ticker",
                              auto_adjust=True, threads=True, progress=False, prepost=False)
        except Exception as e:  # noqa: BLE001
            log.warning("Intradag-nedlasting feilet for %s: %s", chunk, e)
            continue
        if raw is None or raw.empty:
            continue
        for t in chunk:
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                if isinstance(raw.columns, pd.MultiIndex) and t not in raw.columns.get_level_values(0):
                    continue
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"]).copy()
                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")
                df.index = df.index.tz_convert(ZoneInfo(tz_for(t)))
                if len(df) >= 20:
                    out[t] = df.sort_index()
            except Exception as e:  # noqa: BLE001
                log.debug("Kunne ikke tolke intradag-data for %s: %s", t, e)
    return out


# --------------------------------------------------------------------------
# Signaler per aksje
# --------------------------------------------------------------------------
def _rsi(close: pd.Series, n: int = 14) -> float | None:
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    if l.empty or pd.isna(l.iloc[-1]):
        return None
    if l.iloc[-1] == 0:
        return 100.0
    return float(100 - 100 / (1 + g.iloc[-1] / l.iloc[-1]))


def analyze_ticker(ticker: str, df: pd.DataFrame, now_utc: datetime, status: dict) -> dict | None:
    """Dagens intradag-bilde for én aksje (siste økt i dataene)."""
    days = sorted(set(df.index.date))
    if not days:
        return None
    today = days[-1]
    bars = df[df.index.date == today]
    prev_days = [d for d in days if d < today]
    if bars.empty or len(bars) < 2:
        return None
    prev_close = _num(df[df.index.date == prev_days[-1]]["Close"].iloc[-1]) if prev_days else None
    o = float(bars["Open"].iloc[0])
    last = float(bars["Close"].iloc[-1])
    hi, lo = float(bars["High"].max()), float(bars["Low"].min())
    typical = (bars["High"] + bars["Low"] + bars["Close"]) / 3
    vol = bars["Volume"].fillna(0)
    vwap = float((typical * vol).sum() / vol.sum()) if vol.sum() > 0 else None
    orb = bars.iloc[:2]
    orb_high, orb_low = float(orb["High"].max()), float(orb["Low"].min())
    n_bars = len(bars)

    # Relativt volum: akkumulert volum i dag mot snittet ved samme antall barer tidligere dager
    cum_today = float(vol.sum())
    prev_cums = []
    for d in prev_days[-4:]:
        pb = df[df.index.date == d]["Volume"].fillna(0)
        if len(pb) >= n_bars:
            prev_cums.append(float(pb.iloc[:n_bars].sum()))
    rel_vol = (cum_today / (sum(prev_cums) / len(prev_cums))) if prev_cums and sum(prev_cums) > 0 else None

    # Intradag-ATR (15m) over siste 20 barer i hele vinduet
    prev_c = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev_c).abs(), (df["Low"] - prev_c).abs()], axis=1).max(axis=1)
    atr = _num(tr.tail(20).mean())
    rsi = _rsi(df["Close"].tail(80))
    one_hour_ago = float(bars["Close"].iloc[-5]) if n_bars >= 5 else o
    above_vwap_all = bool(vwap and (bars["Close"] >= vwap * 0.998).all())
    crossed_up = bool(vwap and n_bars >= 3 and bars["Close"].iloc[-3] < vwap and last > vwap)
    new_high = bool(last >= hi * 0.999 and n_bars >= 3)
    session_is_today = (today.strftime("%Y-%m-%d") == status["session_date"])

    return {
        "ticker": ticker, "market": market_of(ticker), "session": today.strftime("%Y-%m-%d"), "session_is_today": session_is_today,
        "last": last, "open": o, "high": hi, "low": lo, "prev_close": prev_close,
        "gap_pct": (o / prev_close - 1) if prev_close else None,
        "change_pct": (last / prev_close - 1) if prev_close else None,
        "from_open_pct": (last / o - 1) if o else None,
        "vwap": vwap, "vs_vwap_pct": (last / vwap - 1) if vwap else None,
        "orb_high": orb_high, "orb_low": orb_low, "orb_breakout": bool(last > orb_high and n_bars > 2),
        "rel_volume": rel_vol, "atr": atr, "rsi15": rsi,
        "momentum_1h": (last / one_hour_ago - 1) if one_hour_ago else None,
        "above_vwap_all": above_vwap_all, "vwap_cross_up": crossed_up, "new_high": new_high,
        "bars": n_bars, "last_bar": bars.index[-1].strftime("%H:%M"),
    }


# --------------------------------------------------------------------------
# Setups
# --------------------------------------------------------------------------
def make_setups(a: dict, rules: dict, status: dict, now_utc: datetime) -> list[dict]:
    """Setups (long) for én aksje ut fra analysen. Tom liste hvis ingen regel slår til."""
    if not a or not status["open"] or not a["session_is_today"]:
        return []
    last, vwap, atr = a["last"], a["vwap"], a["atr"]
    if not (last and vwap and atr):
        return []
    rv = a["rel_volume"] or 0
    gap = a["gap_pct"] or 0
    rsi = a["rsi15"]
    tr = float(rules.get("target_r", 2.0))
    out = []

    def build(kind: str, stop: float, score: float, why: list[str]) -> None:
        stop = min(stop, last * 0.998)
        risk = last - stop
        if risk <= 0:
            return
        stop_pct = risk / last
        if stop_pct < float(rules.get("min_stop_pct", 0.004)) or stop_pct > float(rules.get("max_stop_pct", 0.04)):
            return
        target = last + tr * risk
        out.append({
            "ticker": a["ticker"], "market": a["market"], "type": kind, "type_label": TYPES[kind],
            "entry": round(last, 4), "stop": round(stop, 4), "target": round(target, 4), "rr": tr,
            "stop_pct": round(-stop_pct, 4), "target_pct": round(tr * stop_pct, 4),
            "score": int(max(0, min(100, round(score)))), "why": why,
            "session": a["session"], "seen_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "expires": status["close_utc"],
            "last_bar": a["last_bar"], "rel_volume": a["rel_volume"], "change_pct": a["change_pct"], "vwap": round(vwap, 4),
        })

    min_rv = float(rules.get("min_rel_volume", 1.3))
    rsi_ok = rsi is None or rsi <= float(rules.get("max_rsi", 80))

    # Gap-and-go: gap opp, holder gevinsten, over VWAP, høyt volum
    if gap >= float(rules.get("min_gap_pct", 0.02)) and last >= a["open"] and last > vwap and rv >= 1.5 and rsi_ok:
        score = 55 + min(gap, 0.08) * 250 + min(rv, 4) * 5 + (8 if a["new_high"] else 0)
        build("gap", max(vwap - 0.3 * atr, a["low"]), score,
              [f"gap {gap * 100:+.1f} %", f"volum {rv:.1f}× normalt", f"{a['vs_vwap_pct'] * 100:+.1f} % over VWAP"])
    # Åpningsbrudd: over høyeste i første 30 min, med volum, i første del av dagen
    elif a["orb_breakout"] and last > vwap and rv >= min_rv and a["bars"] <= 16 and rsi_ok:
        score = 50 + min(rv, 4) * 7 + (a["from_open_pct"] or 0) * 300 + (6 if a["new_high"] else 0)
        build("orb", max(a["orb_low"], vwap - 0.5 * atr), score,
              [f"brudd over åpningsintervallet ({a['orb_high']:.2f})", f"volum {rv:.1f}× normalt", f"{(a['from_open_pct'] or 0) * 100:+.1f} % siden åpning"])
    # VWAP-reclaim: krysset over VWAP siste barer, med volum, ikke overkjøpt
    elif a["vwap_cross_up"] and rv >= 1.2 and (rsi is None or 45 <= rsi <= 70):
        score = 45 + min(rv, 4) * 6 + ((a["momentum_1h"] or 0) * 400)
        build("vwap", vwap - 0.8 * atr, score,
              ["krysset over VWAP", f"volum {rv:.1f}× normalt", f"RSI15 {rsi:.0f}" if rsi else "RSI ukjent"])
    # Trenddag: over VWAP hele dagen, ny dagshøyde, volum
    elif a["above_vwap_all"] and a["new_high"] and rv >= min_rv and (a["change_pct"] or 0) >= 0.015 and a["bars"] >= 6 and rsi_ok:
        score = 50 + min(rv, 4) * 6 + min((a["change_pct"] or 0), 0.06) * 300
        build("trend", vwap - 0.3 * atr, score,
              ["over VWAP hele dagen", "ny dagshøyde", f"volum {rv:.1f}× normalt", f"{(a['change_pct'] or 0) * 100:+.1f} % i dag"])
    return out


# --------------------------------------------------------------------------
# Logg og etterprøving
# --------------------------------------------------------------------------
def setup_id(s: dict) -> str:
    return f"{s['session']}|{s['ticker']}|{s['type']}"


def load_log(store: Storage) -> dict:
    payload, _ = store.load_snapshot("intraday", "log")
    log_ = payload or {"setups": {}}
    # Slå sammen med sist publiserte logg (hvis databasen har mistet noe)
    url = os.getenv("AKSJERADAR_PAGES_URL", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if not url and "/" in repo:
        owner, name = repo.split("/", 1)
        url = f"https://{owner}.github.io/{name}/"
    if url and not os.getenv("AKSJERADAR_NO_FETCH"):
        try:
            r = requests.get(url.rstrip("/") + "/intraday.json", timeout=15)
            if r.ok:
                for k, v in (r.json().get("log") or {}).items():
                    if k not in log_["setups"] or (v.get("outcome") and not log_["setups"][k].get("outcome")):
                        log_["setups"][k] = v
        except Exception as e:  # noqa: BLE001
            log.info("Fant ingen publisert intradag-logg (%s)", e)
    return log_


def evaluate_pending(log_: dict, frames: dict[str, pd.DataFrame], now_utc: datetime) -> int:
    """Avgjør utfallet for setups hvis økt er over. Returnerer antall avgjort."""
    n = 0
    for k, s in log_["setups"].items():
        if s.get("outcome"):
            continue
        exp = s.get("expires")
        if not exp or now_utc < datetime.fromisoformat(exp):
            continue
        df = frames.get(s["ticker"])
        if df is None:
            if (now_utc - datetime.fromisoformat(exp)).days >= 6:
                s["outcome"] = "ukjent"; s["r"] = None; n += 1
            continue
        seen = datetime.fromisoformat(s["seen_at"].replace("Z", "+00:00"))
        day = df[(df.index.date == datetime.fromisoformat(s["session"]).date()) & (df.index.tz_convert("UTC") > seen)]
        if day.empty:
            if (now_utc - datetime.fromisoformat(exp)).days >= 6:
                s["outcome"] = "ukjent"; s["r"] = None; n += 1
            continue
        risk = s["entry"] - s["stop"]
        outcome, r = None, None
        for _, b in day.iterrows():
            if float(b["Low"]) <= s["stop"]:
                outcome, r = "stop", -1.0   # konservativt: stop før mål hvis begge i samme bar
                break
            if float(b["High"]) >= s["target"]:
                outcome, r = "mål", float(s["rr"])
                break
        if outcome is None:
            close = float(day["Close"].iloc[-1])
            r = (close - s["entry"]) / risk if risk else 0.0
            outcome = "stenging"
        s["outcome"], s["r"], s["evaluated_at"] = outcome, round(r, 3), now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        n += 1
    return n


def stats_from_log(log_: dict) -> dict:
    done = [s for s in log_["setups"].values() if s.get("outcome") and s["outcome"] != "ukjent" and s.get("r") is not None]
    def block(items: list[dict]) -> dict:
        if not items:
            return {"n": 0}
        rs = [s["r"] for s in items]
        return {
            "n": len(items),
            "hit_rate": round(sum(1 for s in items if s["outcome"] == "mål") / len(items), 4),
            "win_rate": round(sum(1 for r in rs if r > 0) / len(items), 4),
            "avg_r": round(sum(rs) / len(rs), 3),
            "sum_r": round(sum(rs), 2),
            "stop_rate": round(sum(1 for s in items if s["outcome"] == "stop") / len(items), 4),
        }
    return {
        "all": block(done),
        "by_type": {k: block([s for s in done if s["type"] == k]) for k in TYPES},
        "pending": sum(1 for s in log_["setups"].values() if not s.get("outcome")),
    }


# --------------------------------------------------------------------------
# Hovedfunksjon
# --------------------------------------------------------------------------
def run_intraday(store: Storage, tickers: list[str], cfg: dict, frames: dict[str, pd.DataFrame] | None = None,
                 now_utc: datetime | None = None, names: dict[str, str] | None = None) -> dict:
    icfg = cfg["intraday"]
    rules = icfg.get("rules", {})
    now_utc = now_utc or datetime.now(timezone.utc)
    if frames is None:
        frames = fetch_intraday(tickers, icfg.get("interval", "15m"))
    statuses = {m: market_status(m, now_utc) for m in MARKETS}

    log_ = load_log(store)
    analyses, setups, movers = {}, [], []
    for t, df in frames.items():
        st = statuses[market_of(t)]
        try:
            a = analyze_ticker(t, df, now_utc, st)
        except Exception as e:  # noqa: BLE001
            log.debug("Intradag-analyse feilet for %s: %s", t, e)
            continue
        if not a:
            continue
        analyses[t] = a
        if a["session_is_today"] and a["change_pct"] is not None:
            movers.append({"ticker": t, "name": (names or {}).get(t, t), "market": a["market"], "last": round(a["last"], 4),
                           "change_pct": round(a["change_pct"], 4), "rel_volume": a["rel_volume"], "vs_vwap_pct": a["vs_vwap_pct"],
                           "gap_pct": a["gap_pct"], "last_bar": a["last_bar"]})
        for s in make_setups(a, rules, st, now_utc):
            s["name"] = (names or {}).get(t, t)
            k = setup_id(s)
            if k in log_["setups"]:
                # allerede logget i dag – behold første inngang/stop/mål, men vis ferske tall
                first = log_["setups"][k]
                s.update({kk: first[kk] for kk in ("entry", "stop", "target", "seen_at", "stop_pct", "target_pct") if kk in first})
                s["first_seen"] = first["seen_at"]
            else:
                log_["setups"][k] = {kk: s[kk] for kk in ("ticker", "name", "market", "type", "type_label", "entry", "stop", "target",
                                                           "rr", "stop_pct", "target_pct", "score", "session", "seen_at", "expires", "why")}
                s["first_seen"] = s["seen_at"]
            setups.append(s)

    decided = evaluate_pending(log_, frames, now_utc)
    # Hold loggen håndterbar: behold siste 60 dager
    cutoff = (now_utc - timedelta(days=60)).strftime("%Y-%m-%d")
    log_["setups"] = {k: v for k, v in log_["setups"].items() if v.get("session", "") >= cutoff}
    store.save_snapshot("intraday", "log", log_)

    setups.sort(key=lambda s: -s["score"])
    movers.sort(key=lambda m: -abs(m["change_pct"]))
    recent = sorted([s for s in log_["setups"].values() if s.get("outcome")], key=lambda s: s.get("evaluated_at") or "", reverse=True)[:25]
    payload = {
        "generated_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_delay_min": 15,
        "interval": icfg.get("interval", "15m"),
        "universe": len(frames),
        "markets": statuses,
        "setups": setups,
        "movers": movers[:16],
        "stats": stats_from_log(log_),
        "recent": recent,
        "decided_now": decided,
        "rules": rules,
        "log": log_["setups"],  # varig logg – leses tilbake hvis databasen mangler
    }
    log.info("Intradag: %d aksjer, %d setups, %d utfall avgjort nå", len(frames), len(setups), decided)
    out = clean_for_json(payload)
    out["_frames"] = frames  # til per-aksje intradag-filer (fjernes før skriving)
    return out


def session_change(df: pd.DataFrame, now_utc: datetime) -> dict | None:
    """Endring i siste økt mot forrige økts sluttkurs, pluss tidspunkt for siste bar."""
    if df is None or df.empty:
        return None
    days = sorted(set(df.index.date))
    if len(days) < 2:
        return None
    today, prev = days[-1], days[-2]
    cur = df[df.index.date == today]
    prv = df[df.index.date == prev]
    if cur.empty or prv.empty:
        return None
    last, prev_close = float(cur["Close"].iloc[-1]), float(prv["Close"].iloc[-1])
    as_of = cur.index[-1]
    age_min = (now_utc - as_of.tz_convert("UTC").to_pydatetime()).total_seconds() / 60
    return {"change": last / prev_close - 1, "last": last, "prev_close": prev_close, "session": today.strftime("%Y-%m-%d"),
            "prev_session": prev.strftime("%Y-%m-%d"), "as_of": as_of.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
            "as_of_local": as_of.strftime("%H:%M"), "age_min": round(age_min), "fresh": age_min <= 45}


def fund_estimates(funds_cfg: list[dict], frames: dict[str, pd.DataFrame], now_utc: datetime) -> dict:
    """Estimert endring i dag per fond: beste (ferskeste) intradag-proxy × valutaendring."""
    out = {}
    for f in funds_cfg or []:
        fid = f.get("id")
        if not fid:
            continue
        proxies = list(f.get("intraday_proxies") or []) + [{"ticker": f["proxy"], "currency": f.get("currency", "USD")}]
        best = None
        for p in proxies:
            sc = session_change(frames.get(p["ticker"]), now_utc)
            if not sc:
                continue
            cand = {**sc, "proxy": p["ticker"], "currency": p.get("currency", "USD")}
            if best is None or cand["as_of"] > best["as_of"]:
                best = cand
        if not best:
            continue
        fx_chg, fx_info = 0.0, None
        cur = best["currency"]
        if cur != "NOK" and not f.get("hedged") and f.get("fx_relevant", True):
            fx = session_change(frames.get(f"{cur}NOK=X"), now_utc)
            if fx:
                fx_chg, fx_info = fx["change"], {"pair": f"{cur}NOK", "change": fx["change"], "as_of": fx["as_of"]}
        elif cur != "NOK" and not f.get("fx_relevant", True) and not f.get("hedged"):
            # fondet er i NOK-aksjer, men proxyen handles i utenlandsk valuta: nøytraliser valutaen
            fx = session_change(frames.get(f"{cur}NOK=X"), now_utc)
            if fx:
                fx_chg = fx["change"]
        est = (1 + best["change"]) * (1 + fx_chg) - 1
        out[fid] = {"est_change_today": round(est, 5), "proxy": best["proxy"], "proxy_change": round(best["change"], 5),
                    "proxy_currency": cur, "fx": fx_info, "as_of": best["as_of"], "as_of_local": best["as_of_local"],
                    "age_min": best["age_min"], "fresh": best["fresh"], "session": best["session"], "ref_date": best["prev_session"]}
    return out


def write_intraday_bars(frames: dict[str, pd.DataFrame], out_dir, days: int = 2) -> int:
    """Skriver 15m-barer for siste `days` økter per aksje: <out_dir>/<TICKER>.json (til 1D-grafen i appen)."""
    from pathlib import Path

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for t, df in frames.items():
        try:
            sessions = sorted(set(df.index.date))[-days:]
            part = df[[d in sessions for d in df.index.date]]
            if part.empty:
                continue
            payload = {
                "ticker": t, "interval": "15m", "tz": str(part.index.tz),
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "t": [ts.strftime("%Y-%m-%dT%H:%M") for ts in part.index],
                "o": [round(float(x), 4) for x in part["Open"]], "h": [round(float(x), 4) for x in part["High"]],
                "l": [round(float(x), 4) for x in part["Low"]], "c": [round(float(x), 4) for x in part["Close"]],
                "v": [int(x) if not pd.isna(x) else 0 for x in part["Volume"]],
            }
            (out_dir / f"{t.replace('/', '_')}.json").write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            n += 1
        except Exception as e:  # noqa: BLE001
            log.debug("Kunne ikke skrive intradag-barer for %s: %s", t, e)
    return n
