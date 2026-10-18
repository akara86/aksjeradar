"""
Aksjeradar – dashboard (Streamlit).

    streamlit run dashboard.py

Viser siste kjøring fra databasen: dagens ideer, en sorterbar screener og
detaljer per aksje med kursgraf, indikatorer, analytikere og innsidehandler.
Kjør `python run.py` (eller `python run.py --demo`) først, så det finnes data.
"""
from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from aksjeradar.config import load_config
from aksjeradar.report import num, pct
from aksjeradar.scoring import CATEGORIES
from aksjeradar.signals import compute_indicators
from aksjeradar.storage import Storage

st.set_page_config(page_title="Aksjeradar", page_icon="📡", layout="wide")

# Farger som fungerer i både lyst og mørkt tema
C_UP, C_DOWN = "#2e9e6b", "#d9534f"
C_FAST, C_SLOW, C_LINE = "#4a7bd0", "#c77d1f", "#8a8a8a"


@st.cache_resource
def get_store(path: str) -> Storage:
    return Storage(path)


cfg = load_config()
store = get_store(cfg["data"]["db_path"])
dates = store.run_dates()

st.title("📡 Aksjeradar")
if not dates:
    st.warning("Ingen kjøringer funnet ennå. Kjør `python run.py` (eller `python run.py --demo`) i terminalen først.")
    st.stop()

run_date = st.sidebar.selectbox("Kjøring", dates, index=0)
df = store.load_scores(run_date)
ideas = store.load_ideas(run_date)

markets = sorted(df["market"].dropna().unique().tolist())
sel_markets = st.sidebar.multiselect("Marked", markets, default=markets)
min_score = st.sidebar.slider("Minste samlet score", 0, 100, 0, 5)
st.sidebar.caption("Rapporten ligger i `reports/latest.html`. Kjør `python run.py` for å oppdatere.")

view = df[df["market"].isin(sel_markets) & (pd.to_numeric(df["score"], errors="coerce").fillna(0) >= min_score)]

tab_ideas, tab_screen, tab_stock, tab_about = st.tabs(["Dagens ideer", "Screener", "Aksje", "Om scoringen"])

# ---------------------------------------------------------------- Ideer
with tab_ideas:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Aksjer analysert", len(df))
    c2.metric("Ideer i dag", sum(len(ideas.get(k) or []) for k, _ in CATEGORIES))
    c3.metric("Varsler", len(ideas.get("warnings") or []))
    top = df.iloc[0] if len(df) else None
    c4.metric("Høyest score", f"{top['ticker']} ({top['score']:.0f})" if top is not None else "–")

    st.subheader(f"Topp {cfg['report']['top_n']} – samlet score")
    top_df = view.head(int(cfg["report"]["top_n"]))
    st.dataframe(
        top_df[["rank", "ticker", "name", "market", "price", "currency", "change_1d", "score",
                "score_technical", "score_analyst", "score_fundamental", "score_insider", "upside"]],
        hide_index=True, use_container_width=True,
        column_config={
            "rank": "#", "ticker": "Ticker", "name": "Navn", "market": "Marked",
            "price": st.column_config.NumberColumn("Kurs", format="%.2f"), "currency": "Val.",
            "change_1d": st.column_config.NumberColumn("1d", format="%+.1f%%"),
            "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
            "score_technical": st.column_config.NumberColumn("Tekn.", format="%.0f"),
            "score_analyst": st.column_config.NumberColumn("Anal.", format="%.0f"),
            "score_fundamental": st.column_config.NumberColumn("Fund.", format="%.0f"),
            "score_insider": st.column_config.NumberColumn("Innsid.", format="%.0f"),
            "upside": st.column_config.NumberColumn("Kursmål", format="%+.1f%%"),
        },
    )

    cols = st.columns(2)
    for i, (key, title) in enumerate(CATEGORIES):
        items = [it for it in (ideas.get(key) or []) if it["market"] in sel_markets]
        with cols[i % 2]:
            st.markdown(f"#### {title}")
            if not items:
                st.caption("Ingen treff i dag.")
            for it in items:
                st.markdown(
                    f"**{it['ticker']}** {it['name']} · {num(it['price'], 2)} {it.get('currency') or ''} · score {it.get('score') or '–'}  \n"
                    f"<span style='opacity:.8'>{'; '.join(it['reasons'])}</span>", unsafe_allow_html=True,
                )
    warns = [it for it in (ideas.get("warnings") or []) if it["market"] in sel_markets]
    if warns:
        st.markdown("#### ⚠️ Varsler – svakhetstegn")
        for it in warns:
            st.markdown(f"**{it['ticker']}** {it['name']} – {'; '.join(it['reasons'])}")

# ---------------------------------------------------------------- Screener
with tab_screen:
    f1, f2, f3, f4 = st.columns(4)
    only_trend = f1.checkbox("Kun i opptrend (over SMA200)")
    only_cov = f2.checkbox("Kun med analytikerdekning")
    only_ins = f3.checkbox("Kun med innsidekjøp siste 90 d")
    sector = f4.selectbox("Sektor", ["Alle"] + sorted(view["sector"].dropna().unique().tolist()))

    s = view.copy()
    if only_trend:
        s = s[s["above_sma_slow"] == True]  # noqa: E712
    if only_cov:
        s = s[pd.to_numeric(s["score_analyst"], errors="coerce").notna()]
    if only_ins:
        s = s[pd.to_numeric(s["insider_buys_90d"], errors="coerce").fillna(0) >= 1]
    if sector != "Alle":
        s = s[s["sector"] == sector]

    show = ["rank", "ticker", "name", "market", "sector", "price", "change_1d", "score", "score_technical",
            "score_analyst", "score_fundamental", "score_insider", "rsi", "ret_1m", "ret_3m", "ret_6m",
            "pct_from_52w_high", "n_analysts", "rec_mean", "upside", "forwardPE", "enterpriseToEbitda",
            "revenueGrowth", "profitMargins", "dividendYield", "insider_buys_90d"]
    st.caption(f"{len(s)} aksjer. Klikk på en kolonneoverskrift for å sortere.")
    st.dataframe(
        s[show], hide_index=True, use_container_width=True, height=600,
        column_config={
            "rank": "#", "ticker": "Ticker", "name": "Navn", "market": "Marked", "sector": "Sektor",
            "price": st.column_config.NumberColumn("Kurs", format="%.2f"),
            "change_1d": st.column_config.NumberColumn("1d", format="%+.1f%%"),
            "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
            "score_technical": st.column_config.NumberColumn("Tekn.", format="%.0f"),
            "score_analyst": st.column_config.NumberColumn("Anal.", format="%.0f"),
            "score_fundamental": st.column_config.NumberColumn("Fund.", format="%.0f"),
            "score_insider": st.column_config.NumberColumn("Innsid.", format="%.0f"),
            "rsi": st.column_config.NumberColumn("RSI", format="%.0f"),
            "ret_1m": st.column_config.NumberColumn("1 mnd", format="%+.1f%%"),
            "ret_3m": st.column_config.NumberColumn("3 mnd", format="%+.1f%%"),
            "ret_6m": st.column_config.NumberColumn("6 mnd", format="%+.1f%%"),
            "pct_from_52w_high": st.column_config.NumberColumn("Fra 52u-topp", format="%+.1f%%"),
            "n_analysts": "Analyt.", "rec_mean": st.column_config.NumberColumn("Konsensus", format="%.1f"),
            "upside": st.column_config.NumberColumn("Kursmål", format="%+.1f%%"),
            "forwardPE": st.column_config.NumberColumn("Fwd P/E", format="%.1f"),
            "enterpriseToEbitda": st.column_config.NumberColumn("EV/EBITDA", format="%.1f"),
            "revenueGrowth": st.column_config.NumberColumn("Oms.vekst", format="%+.1f%%"),
            "profitMargins": st.column_config.NumberColumn("Margin", format="%.1f%%"),
            "dividendYield": st.column_config.NumberColumn("Utbytte", format="%.1f%%"),
            "insider_buys_90d": "Innsidekjøp 90d",
        },
    )
    st.download_button("Last ned som CSV", s[show].to_csv(index=False).encode("utf-8"),
                       file_name=f"aksjeradar_screener_{run_date}.csv", mime="text/csv")

# ---------------------------------------------------------------- Aksje
with tab_stock:
    options = [f"{r['ticker']} – {r['name']}" for _, r in df.iterrows()]
    pick = st.selectbox("Velg aksje", options)
    ticker = pick.split(" – ")[0]
    r = df[df["ticker"] == ticker].iloc[0]

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Kurs", f"{num(r['price'], 2)} {r.get('currency') or ''}", pct(r.get("change_1d")))
    m2.metric("Samlet score", f"{r['score']:.0f}" if pd.notna(r["score"]) else "–")
    m3.metric("RSI", f"{r['rsi']:.0f}" if pd.notna(r.get("rsi")) else "–")
    m4.metric("6 mnd", pct(r.get("ret_6m")))
    m5.metric("Fra 52u-topp", pct(r.get("pct_from_52w_high")))
    m6.metric("Kursmål-oppside", pct(r.get("upside")))

    hist = store.load_prices(ticker)
    if hist.empty:
        st.info("Ingen kurshistorikk lagret for denne aksjen.")
    else:
        ind = compute_indicators(hist, cfg["signals"]["rsi_period"], cfg["signals"]["sma_fast"], cfg["signals"]["sma_slow"]).tail(260)
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03)
        fig.add_trace(go.Candlestick(x=ind.index, open=ind["Open"], high=ind["High"], low=ind["Low"], close=ind["Close"],
                                     name="Kurs", increasing_line_color=C_UP, decreasing_line_color=C_DOWN), row=1, col=1)
        fig.add_trace(go.Scatter(x=ind.index, y=ind["sma_fast"], name=f"SMA{cfg['signals']['sma_fast']}", line=dict(color=C_FAST, width=1.3)), row=1, col=1)
        fig.add_trace(go.Scatter(x=ind.index, y=ind["sma_slow"], name=f"SMA{cfg['signals']['sma_slow']}", line=dict(color=C_SLOW, width=1.3)), row=1, col=1)
        fig.add_trace(go.Scatter(x=ind.index, y=ind["bb_upper"], name="Bollinger", line=dict(color=C_LINE, width=0.7, dash="dot"), showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=ind.index, y=ind["bb_lower"], name="Bollinger", line=dict(color=C_LINE, width=0.7, dash="dot")), row=1, col=1)
        vol_colors = [C_UP if c >= o else C_DOWN for c, o in zip(ind["Close"], ind["Open"])]
        fig.add_trace(go.Bar(x=ind.index, y=ind["Volume"], name="Volum", marker_color=vol_colors, opacity=0.6), row=2, col=1)
        fig.add_trace(go.Scatter(x=ind.index, y=ind["rsi"], name="RSI", line=dict(color=C_FAST, width=1.2)), row=3, col=1)
        fig.add_hline(y=70, line=dict(color=C_DOWN, width=0.8, dash="dash"), row=3, col=1)
        fig.add_hline(y=30, line=dict(color=C_UP, width=0.8, dash="dash"), row=3, col=1)
        fig.update_layout(height=680, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10),
                          legend=dict(orientation="h", y=1.02, x=0), hovermode="x unified")
        fig.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1)
        st.plotly_chart(fig, use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.markdown("#### Tekniske signaler")
        flags = {
            "Over SMA50": r.get("above_sma_fast"), "Over SMA200": r.get("above_sma_slow"),
            "SMA50 > SMA200": r.get("fast_gt_slow"), "Golden cross (siste 10 d)": r.get("golden_cross"),
            "Death cross (siste 10 d)": r.get("death_cross"), "MACD positiv": (r.get("macd_hist") or 0) > 0,
            "MACD krysset opp (siste 5 d)": r.get("macd_cross_up"), "Utbrudd": r.get("breakout"),
            "Nær 52-ukers topp": r.get("near_52w_high"), "Volumhopp": r.get("volume_spike"),
            "Oversolgt (RSI<30)": r.get("oversold"), "Overkjøpt (RSI>70)": r.get("overbought"),
        }
        st.table(pd.DataFrame({"Signal": list(flags.keys()), "Status": ["✅" if v else "–" for v in flags.values()]}))

        st.markdown("#### Fundamentalt")
        fund = {
            "Sektor": r.get("sector") or "–",
            "Markedsverdi": f"{num((r.get('market_cap') or 0) / 1e9, 1)} mrd {r.get('currency') or ''}" if r.get("market_cap") else "–",
            "P/E (siste 12 mnd)": num(r.get("trailingPE"), 1), "P/E (forventet)": num(r.get("forwardPE"), 1),
            "EV/EBITDA": num(r.get("enterpriseToEbitda"), 1), "PEG": num(r.get("trailingPegRatio"), 2),
            "Omsetningsvekst": pct(r.get("revenueGrowth")), "Resultatvekst": pct(r.get("earningsGrowth")),
            "Netto margin": pct(r.get("profitMargins"), signed=False), "Egenkapitalavkastning": pct(r.get("returnOnEquity"), signed=False),
            "Gjeld/EK": num(r.get("debtToEquity"), 0), "FCF-yield": pct(r.get("fcf_yield"), signed=False),
            "Direkteavkastning": pct(r.get("dividendYield"), signed=False),
        }
        st.table(pd.DataFrame({"Nøkkeltall": list(fund.keys()), "Verdi": list(fund.values())}))

    with right:
        st.markdown("#### Analytikere")
        if int(r.get("n_analysts") or 0) == 0:
            st.caption("Ingen analytikerdekning i Yahoo-data.")
        else:
            st.write(f"**{int(r['n_analysts'])} analytikere** · konsensus **{r.get('rec_mean'):.1f}** "
                     f"({r.get('rec_key') or '-'}) · snittkursmål **{num(r.get('target_mean'), 2)}** ({pct(r.get('upside'))})")
            st.write(f"Oppgraderinger siste 90 d: {int(r.get('upgrades_90d') or 0)} · nedgraderinger: {int(r.get('downgrades_90d') or 0)}")
            if r.get("last_upgrade"):
                st.caption(f"Siste oppgradering: {r['last_upgrade']}")

        snap, _ = store.load_snapshot("details", ticker)
        snap = snap or {}
        ups = snap.get("upgrades") or []
        if ups:
            st.dataframe(pd.DataFrame(ups).rename(columns={"date": "Dato", "firm": "Meglerhus", "from": "Fra", "to": "Til", "action": "Handling"}),
                         hide_index=True, use_container_width=True, height=220)

        st.markdown("#### Innsidehandler (siste 180 d)")
        ins = snap.get("insider") or []
        if not ins:
            st.caption("Ingen registrerte innsidehandler i Yahoo-data.")
        else:
            idf = pd.DataFrame(ins)
            idf["kind"] = idf["kind"].map({"buy": "Kjøp", "sell": "Salg"})
            st.dataframe(idf.rename(columns={"date": "Dato", "kind": "Type", "insider": "Innsider", "position": "Rolle", "shares": "Aksjer", "value": "Verdi"}),
                         hide_index=True, use_container_width=True, height=260)

        st.markdown("#### Delscore")
        sc = {"Teknisk": r.get("score_technical"), "Analytiker": r.get("score_analyst"),
              "Fundamental": r.get("score_fundamental"), "Innsider": r.get("score_insider")}
        bar = go.Figure(go.Bar(x=list(sc.keys()), y=[0 if (v is None or pd.isna(v)) else v for v in sc.values()],
                               marker_color=C_FAST, text=[("–" if (v is None or pd.isna(v)) else f"{v:.0f}") for v in sc.values()], textposition="outside"))
        bar.update_layout(height=260, yaxis=dict(range=[0, 110], title="0–100"), margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(bar, use_container_width=True)

# ---------------------------------------------------------------- Om
with tab_about:
    w = cfg["scoring"]["weights"]
    st.markdown(f"""
### Slik beregnes scoren

Hver aksje får fire delscore fra 0 til 100. Samlet score er et vektet snitt – vektene kan endres i `config.yaml`:

| Delscore | Vekt | Hva den måler |
|---|---|---|
| Teknisk | {w['technical']:.0%} | Trend (kurs mot SMA50/SMA200, golden/death cross), MACD, RSI, utbrudd over 60-dagers topp, nærhet til 52-ukers topp, volumhopp og 6-måneders relativ styrke mot resten av universet. |
| Analytiker | {w['analyst']:.0%} | Yahoo-konsensus (1 = sterkt kjøp … 5 = selg), oppside til snittkursmål (30 %+ gir full score) og opp-/nedgraderinger siste 90 dager. Krever minst {cfg['scoring']['min_analysts']} analytikere. |
| Fundamental | {w['fundamental']:.0%} | P/E, forventet P/E, EV/EBITDA, PEG, P/B, gjeld/EK (lavere er bedre) og omsetningsvekst, resultatvekst, marginer, egenkapitalavkastning, FCF-yield (høyere er bedre). Hver aksje rangeres mot de andre i universet. Selskaper med underskudd får lavest rang på P/E. |
| Innsider | {w['insider']:.0%} | Andel kjøp vs. salg (i kroner) blant innsidere siste 180 dager. Små beløp i forhold til markedsverdi teller mindre. |

Mangler en delscore (f.eks. ingen analytikere følger aksjen), fordeles vekten på de som finnes – aksjen straffes ikke for manglende data.

### Idékategoriene
- **Momentum** – teknisk score ≥ 65, over SMA200, RSI ≤ 75.
- **Analytiker-oppside** – minst {cfg['scoring']['min_analysts']} analytikere, konsensus ≤ 2,5 og minst 15 % oppside til kursmål.
- **Nylige oppgraderinger** – minst én oppgradering siste 30 dager.
- **Utbrudd** – kurs over 60-dagers topp på ≥ 1,5× normalt volum, eller nær 52-ukers topp med volumhopp.
- **Oversolgt kvalitet** – RSI under 35, fundamental score ≥ 55 og ikke ned mer enn 25 % siste år.
- **Innsidekjøp** – innsiderscore ≥ 70 og minst ett kjøp siste 90 dager.
- **Varsler** – death cross, brudd under SMA200, flere nedgraderinger, RSI over 80 eller mange innsidesalg.

### Begrensninger
- Gratisdata fra Yahoo Finance er ca. 15 minutter forsinket, og analytikerdekningen på mindre nordiske selskaper er tynn.
- Signalene er mekaniske regler, ikke en modell som er testet historisk. Bruk dem som en liste å undersøke videre, ikke som kjøpsordrer.
- Dette er ikke investeringsråd.
""")
