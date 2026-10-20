"""
Skriver en lesbar analyse per aksje – automatisk, fra tallene.

Hver analyse har:
  - sammendrag (to–tre setninger)
  - avsnitt: Selskapet · Trend og teknisk bilde · Prising og lønnsomhet · Analytikere · Innsidere · Risiko
  - argumenter for og imot kjøp
  - konklusjon med anbefalingen og hva som ville endret den

Alt bygger på det som faktisk er målt (kurser, nøkkeltall, konsensus, innsidehandler) og sammenlignes
med sektoren og børsen aksjen hører til. Tekstene er malbaserte og nøkterne med vilje: de forteller
hva tallene sier, ikke hva som kommer til å skje.
"""
from __future__ import annotations

import math

import pandas as pd

SECTOR_NO = {
    "Technology": "teknologi", "Healthcare": "helse", "Financial Services": "finans", "Energy": "energi",
    "Industrials": "industri", "Consumer Cyclical": "sykliske forbruksvarer", "Consumer Defensive": "stabile forbruksvarer",
    "Basic Materials": "råvarer", "Real Estate": "eiendom", "Utilities": "kraft og forsyning",
    "Communication Services": "kommunikasjon og medier",
}


def _n(x):
    try:
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return None


def _pct(x, d=1, signed=True):
    v = _n(x)
    if v is None:
        return "–"
    return f"{v * 100:{'+' if signed else ''}.{d}f} %"


def _num(x, d=1):
    v = _n(x)
    return "–" if v is None else f"{v:,.{d}f}".replace(",", " ")


def _mcap(v, cur):
    v = _n(v)
    if v is None:
        return None
    if v >= 1e12:
        return f"{v / 1e12:.1f} billioner {cur}"
    if v >= 1e9:
        return f"{v / 1e9:.0f} milliarder {cur}"
    return f"{v / 1e6:.0f} millioner {cur}"


def sector_stats(table: pd.DataFrame) -> dict:
    """Medianer per sektor og per børs – brukes til å si om en aksje er dyr/billig/sterk relativt."""
    out = {"sector": {}, "market": {}}
    for key, col in (("sector", "sector"), ("market", "market")):
        for name, g in table.groupby(col):
            if name is None or len(g) < 5:
                continue
            pe = pd.to_numeric(g["forwardPE"], errors="coerce")
            pe = pe[(pe > 0) & (pe < 200)]
            ev = pd.to_numeric(g["enterpriseToEbitda"], errors="coerce")
            ev = ev[(ev > 0) & (ev < 100)]
            out[key][name] = {
                "n": int(len(g)),
                "fwd_pe": float(pe.median()) if len(pe) else None,
                "ev_ebitda": float(ev.median()) if len(ev) else None,
                "ret_6m": float(pd.to_numeric(g["ret_6m"], errors="coerce").median()),
                "ret_1y": float(pd.to_numeric(g["ret_12m"], errors="coerce").median()),
                "breadth": float(g["above_sma_slow"].fillna(False).astype(bool).mean()),
                "margin": float(pd.to_numeric(g["profitMargins"], errors="coerce").median()),
                "growth": float(pd.to_numeric(g["revenueGrowth"], errors="coerce").median()),
                "score": float(pd.to_numeric(g["score"], errors="coerce").median()),
            }
    return out


def _rel(v, ref, better_low=False):
    """Returnerer ('under'/'over'/'på linje med', forhold) for en verdi mot referanse."""
    v, ref = _n(v), _n(ref)
    if v is None or ref is None or ref == 0:
        return None, None
    ratio = v / ref
    if ratio < 0.85:
        return "klart under", ratio
    if ratio < 0.95:
        return "litt under", ratio
    if ratio <= 1.05:
        return "på linje med", ratio
    if ratio <= 1.2:
        return "litt over", ratio
    return "klart over", ratio


def build_narrative(r: dict, stats: dict, snap: dict | None = None) -> dict:
    snap = snap or {}
    f = snap.get("fundamentals") or {}
    name = r.get("name") or r["ticker"]
    cur = r.get("currency") or ""
    sector = r.get("sector")
    sec_no = SECTOR_NO.get(sector, (sector or "").lower() or "sektoren")
    sec = stats.get("sector", {}).get(sector, {})
    mkt = stats.get("market", {}).get(r.get("market"), {})
    pros, cons, would = [], [], []

    # ---------- Selskapet ----------
    bits = []
    industry = f.get("industry") or r.get("industry")
    mc = _mcap(r.get("market_cap"), cur)
    desc = f"{name} er notert på {r.get('market')}"
    if sector:
        desc += f" i sektoren {sec_no}" + (f" ({industry})" if industry and industry != "Demo" else "")
    desc += "."
    if mc:
        desc += f" Markedsverdien er om lag {mc}."
    emp = _n(f.get("fullTimeEmployees"))
    if emp and emp >= 50:
        desc += f" Selskapet har rundt {int(emp):,} ansatte.".replace(",", " ")
    bits.append(desc)
    summary = f.get("longBusinessSummary")
    company_text = " ".join(bits)
    about = None
    if isinstance(summary, str) and len(summary) > 40:
        about = summary.strip()
        if len(about) > 700:
            cut = about[:700]
            about = cut[: cut.rfind(". ") + 1] if ". " in cut else cut + "…"

    # ---------- Trend ----------
    t = []
    r6, r1, r12 = _n(r.get("ret_6m")), _n(r.get("ret_1m")), _n(r.get("ret_12m"))
    above200, above50, fast_gt = r.get("above_sma_slow"), r.get("above_sma_fast"), r.get("fast_gt_slow")
    if above200 and fast_gt:
        t.append("Kursen ligger over både 50- og 200-dagers glidende snitt, og det korte snittet ligger over det lange – det er en etablert opptrend.")
        pros.append("etablert opptrend (over SMA50 og SMA200)")
    elif above200:
        t.append("Kursen er over 200-dagers snitt, men under 50-dagers – den langsiktige trenden holder, mens det korte bildet er svakere.")
    elif above50:
        t.append("Kursen har løftet seg over 50-dagers snitt, men ligger fortsatt under 200-dagers – en mulig trendvending som ennå ikke er bekreftet.")
        would.append("brudd over 200-dagers snitt ville bekreftet en ny opptrend")
    else:
        t.append("Kursen ligger under både 50- og 200-dagers snitt – trenden er ned, og mekanisk sett er det ingen grunn til å kjøpe før det snur.")
        cons.append("nedtrend (under SMA50 og SMA200)")
        would.append("kursen må over 200-dagers snitt før anbefalingen kan løftes")
    if r.get("golden_cross"):
        t.append("De siste dagene har 50-dagers snitt krysset over 200-dagers (golden cross), som historisk ofte markerer starten på lengre oppganger.")
        pros.append("ferskt golden cross")
    if r.get("death_cross") or r.get("broke_below_slow"):
        t.append("Nylig death cross eller brudd under 200-dagers snitt er et tydelig svakhetstegn.")
        cons.append("nylig trendbrudd")
    if r6 is not None:
        comp = ""
        if sec.get("ret_6m") is not None:
            diff = r6 - sec["ret_6m"]
            comp = f", mot {_pct(sec['ret_6m'])} for {sec_no}-sektoren i universet" + (" – klart sterkere enn sektoren" if diff > 0.08 else " – klart svakere enn sektoren" if diff < -0.08 else "")
            if diff > 0.08:
                pros.append("sterkere enn sektoren siste 6 mnd")
            elif diff < -0.08:
                cons.append("svakere enn sektoren siste 6 mnd")
        t.append(f"Siste seks måneder er aksjen {_pct(r6)}{comp}; siste måned {_pct(r1)} og siste år {_pct(r12)}.")
    rsi = _n(r.get("rsi"))
    if rsi is not None:
        if rsi > 75:
            t.append(f"RSI på {rsi:.0f} sier at aksjen er overkjøpt på kort sikt – en rekyl er vanlig etter slike nivåer, så inngangen kan bli bedre om man venter.")
            cons.append(f"overkjøpt (RSI {rsi:.0f})")
            would.append("en rekyl ned mot 50-dagers snitt ville gitt en bedre inngang")
        elif rsi < 30:
            t.append(f"RSI på {rsi:.0f} er oversolgt – salgspresset kan være i ferd med å tømme seg, men oversolgt kan bli mer oversolgt i en nedtrend.")
        else:
            t.append(f"RSI {rsi:.0f} er nøytralt.")
    d52 = _n(r.get("pct_from_52w_high"))
    if d52 is not None:
        if d52 > -0.03:
            t.append("Kursen er nær 52-ukers topp.")
        elif d52 < -0.25:
            t.append(f"Kursen er {_pct(d52)} under 52-ukers topp – et stort fall som krever en forklaring før det er et kjøp.")
            cons.append(f"{_pct(d52, 0)} under 52-ukers topp")
    if r.get("breakout"):
        t.append("Dagens brudd over 60-dagers topp skjedde på høyt volum, som gir bruddet troverdighet.")
        pros.append("utbrudd på høyt volum")
    trend_text = " ".join(t)

    # ---------- Prising og lønnsomhet ----------
    v = []
    fpe, tpe = _n(r.get("forwardPE")), _n(r.get("trailingPE"))
    if fpe and fpe > 0:
        rel, ratio = _rel(fpe, sec.get("fwd_pe"))
        s_ = f"Aksjen prises til {fpe:.1f} ganger forventet inntjening"
        if rel:
            s_ += f", {rel} medianen på {sec['fwd_pe']:.1f} for {sec_no}-aksjene i universet"
            if ratio < 0.85:
                pros.append("lavere prising enn sektoren (forventet P/E)")
            elif ratio > 1.25:
                cons.append("høyere prising enn sektoren (forventet P/E)")
        v.append(s_ + ".")
    elif tpe is not None and tpe <= 0:
        v.append("Selskapet går med underskudd (negativ P/E), så prisingen hviler på forventninger om bedring, ikke på dagens inntjening.")
        cons.append("underskudd i dag")
    ev = _n(r.get("enterpriseToEbitda"))
    if ev and ev > 0 and sec.get("ev_ebitda"):
        rel, _ = _rel(ev, sec["ev_ebitda"])
        v.append(f"EV/EBITDA er {ev:.1f}, {rel} sektorens {sec['ev_ebitda']:.1f}.")
    g, m, roe = _n(r.get("revenueGrowth")), _n(r.get("profitMargins")), _n(r.get("returnOnEquity"))
    q = []
    if g is not None:
        gs = f"omsetningsvekst {_pct(g)}"
        if sec.get("growth") is not None:
            gs += f" (sektor {_pct(sec['growth'])})"
        q.append(gs)
        if g > 0.15:
            pros.append(f"høy omsetningsvekst ({_pct(g, 0)})")
        elif g < 0:
            cons.append(f"fallende omsetning ({_pct(g, 0)})")
    if m is not None:
        ms = f"nettomargin {_pct(m, 1, False)}"
        if sec.get("margin") is not None:
            ms += f" (sektor {_pct(sec['margin'], 1, False)})"
        q.append(ms)
        if sec.get("margin") is not None and m > sec["margin"] * 1.3 and m > 0.05:
            pros.append("høyere marginer enn sektoren")
    if roe is not None:
        q.append(f"egenkapitalavkastning {_pct(roe, 0, False)}")
        if roe > 0.20:
            pros.append(f"sterk egenkapitalavkastning ({_pct(roe, 0, False)})")
    if q:
        v.append("Lønnsomhet og vekst: " + ", ".join(q) + ".")
    de = _n(r.get("debtToEquity"))
    if de is not None:
        if de > 150:
            v.append(f"Gjeldsgraden er høy ({de:.0f} % av egenkapitalen), som gjør selskapet sårbart for høyere renter eller svakere inntjening.")
            cons.append("høy gjeldsgrad")
        elif de < 30:
            v.append(f"Balansen er solid med lav gjeld ({de:.0f} % av egenkapitalen).")
            pros.append("solid balanse")
    dy = _n(r.get("dividendYield"))
    if dy and dy > 0.03:
        v.append(f"Direkteavkastningen er {_pct(dy, 1, False)}.")
        pros.append(f"utbytte {_pct(dy, 1, False)}")
    fcf = _n(r.get("fcf_yield"))
    if fcf is not None and fcf > 0.06:
        v.append(f"Fri kontantstrøm tilsvarer {_pct(fcf, 1, False)} av markedsverdien – selskapet tjener reelle penger i forhold til prisen.")
        pros.append(f"høy kontantstrøm-yield ({_pct(fcf, 1, False)})")
    val_text = " ".join(v) if v else "Det finnes ikke nok fundamentaldata til å si noe om prisingen."

    # ---------- Analytikere ----------
    na = int(r.get("n_analysts") or 0)
    rec_mean, upside = _n(r.get("rec_mean")), _n(r.get("upside"))
    if na >= 3 and rec_mean is not None:
        lab = "sterkt kjøp" if rec_mean < 1.8 else "kjøp" if rec_mean < 2.5 else "hold" if rec_mean < 3.5 else "selg"
        a_ = f"{na} analytikere følger aksjen, med snittanbefaling {rec_mean:.1f} ({lab})"
        if upside is not None:
            a_ += f", og snittkursmålet ligger {_pct(upside)} fra dagens kurs"
        a_ += "."
        ups, downs = int(r.get("upgrades_90d") or 0), int(r.get("downgrades_90d") or 0)
        if ups or downs:
            a_ += f" Siste 90 dager: {ups} oppgradering(er) og {downs} nedgradering(er)."
        if rec_mean < 2.3 and upside is not None and upside > 0.12:
            pros.append(f"analytikerne anbefaler kjøp med {_pct(upside, 0)} oppside")
        if upside is not None and upside < 0:
            a_ += " Kursen er allerede over kursmålet – analytikerne ser begrenset oppside herfra."
            cons.append("kursen er over analytikernes kursmål")
            would.append("høyere kursmål fra analytikerne (eller en rekyl i kursen)")
        if rec_mean >= 3.5:
            cons.append("analytikerne er negative")
        if downs >= 2 and not ups:
            cons.append(f"{downs} nedgraderinger siste 90 dager")
        an_text = a_
    elif na > 0:
        an_text = f"Bare {na} analytiker(e) følger aksjen – for tynn dekning til å vektlegge konsensus."
    else:
        an_text = "Ingen analytikerdekning i Yahoo-dataene. Vurderingen hviler derfor på teknisk bilde og nøkkeltall."

    # ---------- Innsidere ----------
    buys, sells = int(r.get("insider_buys") or 0), int(r.get("insider_sells") or 0)
    bv, sv = _n(r.get("insider_buy_value")) or 0, _n(r.get("insider_sell_value")) or 0
    if buys + sells == 0:
        in_text = "Ingen registrerte innsidehandler siste 180 dager i datakilden."
    else:
        in_text = f"Siste 180 dager: {buys} innsidekjøp og {sells} innsidesalg"
        if bv or sv:
            in_text += f" (kjøp for ca. {bv / 1e6:.1f} mill, salg for ca. {sv / 1e6:.1f} mill {cur})"
        in_text += "."
        if buys >= 2 and bv > sv:
            in_text += " At ledelsen kjøper for egne penger er et av de mer pålitelige signalene som finnes."
            pros.append("innsiderne kjøper")
        elif sells >= 3 and sv > bv * 3:
            in_text += " Innsidesalg kan ha private årsaker, men mange salg og ingen kjøp er sjelden et godt tegn."
            cons.append("mange innsidesalg")

    # ---------- Risiko ----------
    rk = []
    atr = _n(r.get("atr_pct"))
    if atr is not None:
        lvl = "høy" if atr > 0.03 else "middels" if atr > 0.015 else "lav"
        rk.append(f"Daglige svingninger på {_pct(atr, 1, False)} av kursen gir {lvl} risiko" + (" – posisjonen bør være liten og stop-loss romslig." if lvl == "høy" else "."))
        if lvl == "høy":
            cons.append("høye svingninger")
    beta = _n(r.get("beta"))
    if beta is not None:
        rk.append(f"Beta {beta:.2f} betyr at aksjen {'svinger mer enn' if beta > 1.2 else 'svinger mindre enn' if beta < 0.8 else 'følger'} markedet.")
    if r.get("coverage") == "tynt":
        rk.append("Datagrunnlaget er tynt (bare teknisk bilde), så vurderingen er usikrere enn for aksjer med full dekning.")
        cons.append("tynt datagrunnlag")
    mc_v = _n(r.get("market_cap"))
    if mc_v is not None and mc_v < 3e9 and cur in ("NOK", "SEK", "DKK"):
        rk.append("Dette er et lite selskap med lav omsetning i aksjen – spreaden kan være stor, og kursen kan bevege seg mye på små volumer.")
    risk_text = " ".join(rk) if rk else "Ingen spesielle risikoflagg i dataene."

    # ---------- Konklusjon ----------
    verdict = r.get("verdict") or "Hold"
    score = _n(r.get("score"))
    strong = {"Sterkt kjøp", "Kjøp"}
    if verdict in strong:
        concl = f"Anbefalingen er **{verdict}**. Samlet score {score:.0f} med bekreftet opptrend" + (", analytikerstøtte" if na >= 3 and rec_mean is not None and rec_mean < 2.5 else "") + "."
        concl += " Det betyr at aksjen oppfyller kravene for en kjøpskandidat – ikke at den ikke kan falle. En fornuftig måte å handle på er å kjøpe i to–tre omganger og bruke 200-dagers snitt eller en fast prosent som stop."
        would.append("anbefalingen faller til Avvent/Unngå hvis kursen bryter under 200-dagers snitt, RSI går over 78, eller analytikerne snur")
    elif verdict == "Hold":
        why_hold = []
        if not above200:
            why_hold.append("mangler bekreftet opptrend")
        if rsi is not None and rsi > 78:
            why_hold.append("er sterkt overkjøpt")
        if upside is not None and upside < 0 and na >= 5:
            why_hold.append("handles over kursmålet")
        if r.get("coverage") == "tynt":
            why_hold.append("har tynt datagrunnlag")
        if score is not None and score < 65 and not why_hold:
            why_hold.append(f"har en samlet score ({score:.0f}) som ikke når kjøpsgrensen på 65")
        warn = bool(r.get("death_cross") or r.get("broke_below_slow") or (rsi is not None and rsi > 80))
        concl = f"Anbefalingen er **Hold** – aksjen {', '.join(why_hold) if why_hold else 'har et blandet bilde'}. "
        concl += ("Eier du den, bør du følge med: det er svakhetstegn i bildet. " if warn else "Eier du den, er det ingen grunn til å selge på disse tallene. ")
        concl += "Har du den ikke, er det bedre kandidater i Kjøp-fanen."
    elif verdict == "Avvent":
        concl = f"Anbefalingen er **Avvent**. Samlet score {score:.0f}" + (" og nedtrend" if not above200 else "") + " – det er ingen kjøpssignaler her nå. Vent på at trenden snur før aksjen vurderes igjen."
        would.append("brudd over 200-dagers snitt med stigende volum")
    else:
        concl = f"Anbefalingen er **Unngå**. Samlet score {score:.0f} – svakt på tvers av teknisk bilde, nøkkeltall og analytikere. Her er sannsynligheten for videre skuffelser høyere enn for en vending."
        would.append("det må både en trendvending og bedre nøkkeltall til før aksjen blir interessant")

    if not pros:
        pros.append("ingen tydelige positive signaler i dataene akkurat nå")
    if not cons:
        cons.append("ingen tydelige risikoflagg i dataene akkurat nå")

    lead = f"{name}: {verdict.lower()}. "
    lead += ("Opptrend" if above200 else "Nedtrend") + ", "
    if fpe and sec.get("fwd_pe"):
        rel, _ = _rel(fpe, sec["fwd_pe"])
        lead += f"prising {rel} sektoren, "
    lead += f"{'analytikerne anbefaler ' + ('kjøp' if rec_mean < 2.5 else 'hold' if rec_mean < 3.5 else 'salg') if (na >= 3 and rec_mean is not None) else 'ingen analytikerdekning'}."

    return {
        "summary": lead,
        "about": about,
        "sections": [
            {"title": "Selskapet", "text": company_text},
            {"title": "Trend og teknisk bilde", "text": trend_text},
            {"title": "Prising og lønnsomhet", "text": val_text},
            {"title": "Analytikere", "text": an_text},
            {"title": "Innsidere", "text": in_text},
            {"title": "Risiko", "text": risk_text},
        ],
        "pros": pros[:6],
        "cons": cons[:6],
        "conclusion": concl,
        "would_change": list(dict.fromkeys(would))[:4],
        "sector_ref": {"sector": sector, "n": sec.get("n"), "fwd_pe": sec.get("fwd_pe"), "ret_6m": sec.get("ret_6m"), "breadth": sec.get("breadth")},
    }
