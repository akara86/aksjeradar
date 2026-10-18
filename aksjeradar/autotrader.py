"""
Autotrader – en virtuell portefølje som følger anbefalingene automatisk, hver handelsdag.

Reglene (alle i config.yaml under `autotrader:`):
  Kjøp:  dagens kjøpskandidater (Sterkt kjøp / Kjøp) med score >= min_score og minst delvis datagrunnlag,
         best score først, like store posisjoner (total verdi / max_positions), inntil max_positions.
  Selg:  anbefalingen faller til Avvent/Unngå, trendbrudd (death cross / brudd under SMA200),
         eller kursen er stop_loss_pct under snittkursen. Tidligst etter min_hold_days.
  Kost:  kurtasje (commission_pct) på hver handel og slippage_pct i disfavør, slik at tallene ikke lyver.
  En aksje som er solgt kan ikke kjøpes igjen før etter cooldown_days.

Handlene skjer til sluttkursen i dagens data (kjøringen går om morgenen, så det er gårsdagens
sluttkurs). Hver sluttkursdato behandles bare én gang, selv om analysen kjøres flere ganger samme dag.

Tilstanden ligger i databasen (data/aksjeradar.db) OG i docs/autotrader.json som publiseres med appen.
Mangler databasen (f.eks. ny maskin), hentes siste publiserte tilstand fra nettsiden.
"""
from __future__ import annotations

import logging
import math
import os
from datetime import date, datetime, timezone

import pandas as pd
import requests

from .storage import Storage, clean_for_json

log = logging.getLogger("aksjeradar.autotrader")

BUY_VERDICTS = {"Sterkt kjøp", "Kjøp"}
SELL_VERDICTS = {"Avvent", "Unngå"}


def _num(x):
    try:
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def new_state(acfg: dict, start_date: str) -> dict:
    return {
        "version": 1,
        "start_date": start_date,
        "start_cash": float(acfg["start_cash"]),
        "base": acfg.get("base_currency", "NOK"),
        "cash": float(acfg["start_cash"]),
        "holdings": {},        # ticker -> {shares, avg_price, currency, bought, buy_score, buy_verdict, name}
        "trades": [],          # kronologisk
        "history": [],         # [{date, total, bench}]
        "cooldown": {},        # ticker -> dato solgt
        "bench": 1.0,          # likevektet univers-indeks (1.0 ved start)
        "last_price_date": None,
    }


def load_state(store: Storage, acfg: dict) -> dict | None:
    payload, _ = store.load_snapshot("autotrader", "state")
    if payload and payload.get("holdings") is not None:
        return payload
    # Fallback: siste publiserte tilstand på nettsiden (GitHub Pages)
    url = os.getenv("AKSJERADAR_PAGES_URL", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if not url and "/" in repo:
        owner, name = repo.split("/", 1)
        url = f"https://{owner}.github.io/{name}/"
    if url:
        try:
            r = requests.get(url.rstrip("/") + "/autotrader.json", timeout=20)
            if r.ok:
                p = r.json().get("state")
                if p and p.get("holdings") is not None:
                    log.info("Autotrader: hentet tilstand fra %s", url)
                    return p
        except Exception as e:  # noqa: BLE001
            log.info("Autotrader: fant ingen publisert tilstand (%s)", e)
    return None


def run_autotrader(store: Storage, table: pd.DataFrame, cfg: dict, fx: dict) -> dict:
    """Behandler én dag (hvis ny sluttkursdato) og returnerer det som skal publiseres."""
    acfg = cfg["autotrader"]
    base = acfg.get("base_currency", "NOK")
    if table.empty:
        return {}
    price_date = str(table["last_date"].max())
    state = load_state(store, acfg) or new_state(acfg, price_date)

    def rate(cur: str | None) -> float | None:
        cur = cur or base
        a = 1.0 if cur == "NOK" else _num((fx or {}).get(cur))
        b = 1.0 if base == "NOK" else _num((fx or {}).get(base))
        return (a / b) if (a and b) else None

    rows = {r["ticker"]: r for r in table.to_dict(orient="records")}
    comm = float(acfg.get("commission_pct", 0.0005))
    slip = float(acfg.get("slippage_pct", 0.002))
    already = state.get("last_price_date") == price_date

    if not already:
        # ---------- 1. selg ----------
        for t, h in list(state["holdings"].items()):
            r = rows.get(t)
            if not r or _num(r.get("price")) is None:
                continue  # ingen kurs i dag – behold
            p = float(r["price"])
            fxr = rate(r.get("currency") or h.get("currency"))
            if not fxr:
                continue
            held = _days(h["bought"], price_date)
            reason = None
            if p <= h["avg_price"] * (1 - float(acfg.get("stop_loss_pct", 0.12))):
                reason = f"stop-loss ({(p / h['avg_price'] - 1) * 100:+.1f} %)"
            elif held >= int(acfg.get("min_hold_days", 5)):
                if r.get("verdict") in SELL_VERDICTS:
                    reason = f"anbefaling {r['verdict']}"
                elif r.get("death_cross") or r.get("broke_below_slow"):
                    reason = "trendbrudd"
            if not reason:
                continue
            eff = p * (1 - slip)
            proceeds = h["shares"] * eff * fxr * (1 - comm)
            cost = h["shares"] * h["avg_price"] * fxr
            state["cash"] += proceeds
            state["trades"].append({
                "date": price_date, "kind": "sell", "ticker": t, "name": h.get("name", t),
                "shares": h["shares"], "price": round(eff, 4), "currency": r.get("currency") or h.get("currency"),
                "value_base": round(proceeds, 2), "pnl": round(proceeds - cost, 2),
                "pnl_pct": round((proceeds - cost) / cost, 4) if cost else None,
                "reason": reason, "held_days": held, "buy_score": h.get("buy_score"),
            })
            state["cooldown"][t] = price_date
            del state["holdings"][t]
            log.info("Autotrader SELG %s – %s", t, reason)

        # ---------- 2. kjøp ----------
        held_value = 0.0
        for t, h in state["holdings"].items():
            r = rows.get(t)
            p = float(r["price"]) if r and _num(r.get("price")) is not None else h["avg_price"]
            held_value += h["shares"] * p * (rate((r or h).get("currency")) or 0)
        total = state["cash"] + held_value
        max_pos = int(acfg.get("max_positions", 10))
        target = total / max_pos
        cooldown_days = int(acfg.get("cooldown_days", 10))
        cands = [
            r for r in rows.values()
            if r.get("verdict") in BUY_VERDICTS and r.get("coverage") != "tynt"
            and (_num(r.get("score")) or 0) >= float(acfg.get("min_score", 65))
            and r["ticker"] not in state["holdings"]
            and _days(state["cooldown"].get(r["ticker"], "2000-01-01"), price_date) >= cooldown_days
        ]
        cands.sort(key=lambda r: -(_num(r.get("score")) or 0))
        max_per_market = int(acfg.get("max_per_market", 0))
        for r in cands:
            if len(state["holdings"]) >= max_pos:
                break
            if max_per_market and sum(1 for h in state["holdings"].values() if h.get("market") == r.get("market")) >= max_per_market:
                continue
            p = _num(r.get("price"))
            fxr = rate(r.get("currency"))
            if not p or not fxr:
                continue
            budget = min(target, state["cash"])
            if budget < target * 0.5:
                break  # for lite kontanter igjen til en meningsfull posisjon
            eff = p * (1 + slip)
            shares = math.floor(budget / (eff * fxr * (1 + comm)))
            if shares < 1:
                continue
            cost = shares * eff * fxr * (1 + comm)
            state["cash"] -= cost
            state["holdings"][r["ticker"]] = {
                "shares": shares, "avg_price": round(eff, 4), "currency": r.get("currency"), "market": r.get("market"),
                "bought": price_date, "buy_score": round(float(r.get("score")), 1), "buy_verdict": r.get("verdict"),
                "name": r.get("name"), "cost_base": round(cost, 2),
            }
            state["trades"].append({
                "date": price_date, "kind": "buy", "ticker": r["ticker"], "name": r.get("name"),
                "shares": shares, "price": round(eff, 4), "currency": r.get("currency"), "value_base": round(cost, 2),
                "reason": f"{r.get('verdict')} · score {float(r.get('score')):.0f}",
                "buy_score": round(float(r.get("score")), 1),
            })
            log.info("Autotrader KJØP %s – %s", r["ticker"], r.get("verdict"))

        # ---------- 3. markedsindeks (likevektet univers) ----------
        ch = [c for c in (_num(r.get("change_1d")) for r in rows.values() if str(r.get("last_date")) == price_date) if c is not None]
        if ch and state["history"]:
            state["bench"] = state["bench"] * (1 + sum(ch) / len(ch))

    # ---------- 4. verdsett og loggfør ----------
    holdings_view = []
    held_value = 0.0
    for t, h in state["holdings"].items():
        r = rows.get(t) or {}
        p = _num(r.get("price")) if r else None
        p = p if p is not None else h["avg_price"]
        fxr = rate(r.get("currency") or h.get("currency")) or 0
        value = h["shares"] * p * fxr
        cost = h.get("cost_base") or h["shares"] * h["avg_price"] * fxr
        held_value += value
        holdings_view.append({
            "ticker": t, "name": h.get("name") or r.get("name") or t, "market": h.get("market") or r.get("market"),
            "shares": h["shares"], "avg_price": h["avg_price"], "currency": h.get("currency"),
            "price": p, "value_base": round(value, 2), "pnl": round(value - cost, 2),
            "pnl_pct": round((value - cost) / cost, 4) if cost else None,
            "bought": h["bought"], "days": _days(h["bought"], price_date),
            "buy_score": h.get("buy_score"), "score": _num(r.get("score")), "verdict": r.get("verdict"),
            "change_1d": _num(r.get("change_1d")),
        })
    total = state["cash"] + held_value
    bench_value = state["start_cash"] * state["bench"]
    point = {"date": price_date, "total": round(total, 2), "bench": round(bench_value, 2)}
    if state["history"] and state["history"][-1]["date"] == price_date:
        state["history"][-1] = point
    else:
        state["history"].append(point)
    state["last_price_date"] = price_date
    store.save_snapshot("autotrader", "state", state)

    # ---------- 5. statistikk ----------
    closed = [tr for tr in state["trades"] if tr["kind"] == "sell"]
    wins = [tr for tr in closed if (tr.get("pnl") or 0) > 0]
    peak, mdd = -1.0, 0.0
    for pt in state["history"]:
        peak = max(peak, pt["total"])
        if peak > 0:
            mdd = max(mdd, 1 - pt["total"] / peak)
    stats = {
        "n_trades": len(state["trades"]),
        "n_closed": len(closed),
        "win_rate": round(len(wins) / len(closed), 4) if closed else None,
        "avg_pnl_pct": round(sum(tr.get("pnl_pct") or 0 for tr in closed) / len(closed), 4) if closed else None,
        "realized_pnl": round(sum(tr.get("pnl") or 0 for tr in closed), 2),
        "max_drawdown_pct": round(mdd, 4),
        "best": max(closed, key=lambda tr: tr.get("pnl_pct") or -9, default=None),
        "worst": min(closed, key=lambda tr: tr.get("pnl_pct") or 9, default=None),
        "days_running": _days(state["start_date"], price_date),
    }
    view = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "price_date": price_date,
        "traded_today": not already,
        "start_date": state["start_date"], "start_cash": state["start_cash"], "base": base,
        "cash": round(state["cash"], 2), "holdings_value": round(held_value, 2), "total": round(total, 2),
        "return_pct": round(total / state["start_cash"] - 1, 4) if state["start_cash"] else None,
        "bench_return_pct": round(state["bench"] - 1, 4),
        "holdings": sorted(holdings_view, key=lambda x: -x["value_base"]),
        "trades": list(reversed(state["trades"][-150:])),
        "history": state["history"],
        "stats": stats,
        "rules": {k: acfg.get(k) for k in ("start_cash", "max_positions", "min_score", "stop_loss_pct", "min_hold_days",
                                            "cooldown_days", "commission_pct", "slippage_pct", "max_per_market")},
        "state": state,  # varig tilstand – leses tilbake hvis databasen mangler
    }
    return clean_for_json(view)
