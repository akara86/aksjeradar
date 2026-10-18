"""
Rapporter: Markdown (lesbar i hvilken som helst editor), HTML (åpnes i nettleser)
og et kort Telegram-sammendrag.
"""
from __future__ import annotations

import html
from pathlib import Path

import pandas as pd

from .scoring import CATEGORIES

DISCLAIMER = (
    "Dette er et personlig analyseverktøy, ikke investeringsråd. Signalene er mekaniske og "
    "bør sjekkes mot egen vurdering. Datakilde: Yahoo Finance via yfinance (ca. 15 min forsinket)."
)


# ---------- små formateringshjelpere ----------
def pct(x, signed: bool = True) -> str:
    if x is None or pd.isna(x):
        return "–"
    return f"{x * 100:+.1f} %" if signed else f"{x * 100:.1f} %"


def num(x, dec: int = 1) -> str:
    if x is None or pd.isna(x):
        return "–"
    return f"{x:,.{dec}f}".replace(",", " ")


def score_fmt(x) -> str:
    return "–" if (x is None or pd.isna(x)) else f"{x:.0f}"


def price_fmt(r) -> str:
    cur = r.get("currency") or ""
    return f"{num(r.get('price'), 2)} {cur}".strip()


# ---------- Markdown ----------
def _md_table(df: pd.DataFrame) -> str:
    cols = [
        ("#", lambda r: str(int(r["rank"]))),
        ("Ticker", lambda r: r["ticker"]),
        ("Navn", lambda r: str(r["name"])[:28]),
        ("Marked", lambda r: r["market"]),
        ("Kurs", price_fmt),
        ("1d", lambda r: pct(r.get("change_1d"))),
        ("Anbefaling", lambda r: str(r.get("verdict") or "–")),
        ("Score", lambda r: score_fmt(r.get("score"))),
        ("Tekn.", lambda r: score_fmt(r.get("score_technical"))),
        ("Anal.", lambda r: score_fmt(r.get("score_analyst"))),
        ("Fund.", lambda r: score_fmt(r.get("score_fundamental"))),
        ("Innsid.", lambda r: score_fmt(r.get("score_insider"))),
        ("RSI", lambda r: num(r.get("rsi"), 0)),
        ("6 mnd", lambda r: pct(r.get("ret_6m"))),
        ("Kursmål", lambda r: pct(r.get("upside"))),
    ]
    lines = ["| " + " | ".join(c for c, _ in cols) + " |",
             "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(fn(r) for _, fn in cols) + " |")
    return "\n".join(lines)


def _md_ideas(items: list[dict]) -> str:
    if not items:
        return "_Ingen treff i dag._"
    out = []
    for it in items:
        cur = it.get("currency") or ""
        verdict = f" · **{it['verdict']}**" if it.get("verdict") else ""
        head = f"- **{it['ticker']}** {it['name']} · {num(it['price'], 2)} {cur} · score {score_fmt(it.get('score'))}{verdict}"
        if it.get("reasons"):
            head += "  \n  " + "; ".join(it["reasons"])
        out.append(head)
    return "\n".join(out)


def render_markdown(df: pd.DataFrame, ideas: dict, run_date: str, cfg: dict, demo: bool = False) -> str:
    top_n = int(cfg["report"].get("top_n", 10))
    rows = int(cfg["report"].get("screener_rows", 40))
    lines = [f"# Aksjeradar – {run_date}", ""]
    if demo:
        lines += ["> **DEMO-DATA.** Tallene er tilfeldig generert. Kjør `python run.py` uten `--demo` for ekte data.", ""]
    if df.empty:
        lines += ["Ingen aksjer kunne analyseres i denne kjøringen.", "", f"_{DISCLAIMER}_"]
        return "\n".join(lines)

    counts = df["market"].value_counts().to_dict()
    counts_txt = ", ".join(f"{k} {v}" for k, v in counts.items())
    last_date = df["last_date"].max() if "last_date" in df else run_date
    lines += [f"Univers: **{len(df)} aksjer** ({counts_txt}). Sluttkurser t.o.m. {last_date}.", ""]

    lines += [f"## Topp {top_n} – samlet score", "", _md_table(df.head(top_n)), ""]

    for key, title in CATEGORIES:
        lines += [f"## {title}", "", _md_ideas(ideas.get(key, [])), ""]

    lines += ["## Varsler – svakhetstegn", "", _md_ideas(ideas.get("warnings", [])), ""]

    lines += [f"## Screener – topp {rows}", "", _md_table(df.head(rows)), ""]
    lines += ["### Slik leses anbefalingen og scoren", "",
              "- **Anbefaling** er regelbasert: samlet score setter utgangspunktet (≥75 Sterkt kjøp, ≥65 Kjøp, ≥50 Hold, ≥40 Avvent, ellers Unngå); "
              "kjøp krever at kursen er over SMA200, og death cross, sterkt overkjøpt RSI, negative analytikere eller kurs over kursmål trekker ned.",
              "- **Tekn.** trend (SMA50/200), MACD, RSI, utbrudd og volum. ",
              "- **Anal.** analytikerkonsensus (1 = sterkt kjøp … 5 = selg), oppside til snittkursmål og opp-/nedgraderinger.",
              "- **Fund.** P/E, EV/EBITDA, PEG, vekst, marginer, egenkapitalavkastning og gjeld – rangert mot de andre aksjene i universet.",
              "- **Innsid.** andel kjøp vs. salg blant innsidere siste 180 dager.",
              "- Delscore som mangler (f.eks. ingen analytikerdekning) teller som nøytral 50 i den samlede scoren.", "",
              f"_{DISCLAIMER}_"]
    return "\n".join(lines)


def render_html(markdown_text: str, title: str = "Aksjeradar") -> str:
    import markdown as md

    body = md.markdown(markdown_text, extensions=["tables"])
    return f"""<!doctype html>
<html lang="no"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; line-height: 1.45; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.86rem; margin: 0.5rem 0 1.5rem; }}
  th, td {{ border-bottom: 1px solid #8884; padding: 4px 8px; text-align: right; white-space: nowrap; }}
  th:nth-child(-n+4), td:nth-child(-n+4) {{ text-align: left; }}
  th {{ background: #8882; position: sticky; top: 0; }}
  tr:hover td {{ background: #8881; }}
  blockquote {{ border-left: 4px solid #e0a800; padding: .3rem 1rem; background: #e0a8001a; }}
  h2 {{ margin-top: 2rem; border-bottom: 1px solid #8884; padding-bottom: .2rem; }}
  li {{ margin: .35rem 0; }}
  em {{ opacity: .75; }}
</style></head><body>{body}</body></html>"""


# ---------- Telegram ----------
def render_telegram(df: pd.DataFrame, ideas: dict, run_date: str, top_n: int = 5, demo: bool = False) -> str:
    """Kort HTML-formatert melding (Telegram støtter <b>, <i>, <code>)."""
    e = html.escape
    lines = [f"📡 <b>Aksjeradar {e(run_date)}</b>"]
    if demo:
        lines.append("<i>(demo-data)</i>")
    if df.empty:
        lines.append("Ingen aksjer kunne analyseres.")
        return "\n".join(lines)

    lines.append(f"\n<b>Topp {top_n}</b>")
    for _, r in df.head(top_n).iterrows():
        lines.append(f"{int(r['rank'])}. <b>{e(r['ticker'])}</b> {e(str(r['name'])[:22])} – {score_fmt(r['score'])} · {e(str(r.get('verdict') or ''))} "
                     f"({pct(r.get('change_1d'))} i dag, kursmål {pct(r.get('upside'))})")

    for key, title in CATEGORIES:
        items = ideas.get(key) or []
        if not items:
            continue
        lines.append(f"\n<b>{e(title)}</b>")
        for it in items[:3]:
            reason = "; ".join(it["reasons"][:3]) if it.get("reasons") else ""
            lines.append(f"• <b>{e(it['ticker'])}</b> – {e(reason)}")

    warns = ideas.get("warnings") or []
    if warns:
        lines.append("\n⚠️ <b>Varsler</b>")
        for it in warns[:4]:
            lines.append(f"• <b>{e(it['ticker'])}</b> – {e('; '.join(it['reasons'][:2]))}")

    lines.append("\n<i>Ikke investeringsråd. Full rapport i reports/-mappen.</i>")
    return "\n".join(lines)


# ---------- lagring ----------
def write_reports(markdown_text: str, run_date: str, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / f"aksjeradar_{run_date}.md"
    html_path = out / f"aksjeradar_{run_date}.html"
    md_path.write_text(markdown_text, encoding="utf-8")
    html_text = render_html(markdown_text, title=f"Aksjeradar {run_date}")
    html_path.write_text(html_text, encoding="utf-8")
    (out / "latest.md").write_text(markdown_text, encoding="utf-8")
    (out / "latest.html").write_text(html_text, encoding="utf-8")
    return md_path, html_path
