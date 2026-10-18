/* Aksjeradar – mobil-app. Leser data.json (laget av run.py) og viser kjøpsanbefalinger, ideer,
   screener, varsler og detaljer per aksje. Ingen rammeverk, ingen avhengigheter. */
(function () {
  "use strict";

  const $ = (sel, el) => (el || document).querySelector(sel);
  const PREVIEW = !!window.__PREVIEW__;

  const MARKETS = {
    alle: { label: "Alle", set: null },
    oslo: { label: "Oslo", set: ["Oslo"] },
    norden: { label: "Norden", set: ["Stockholm", "København", "Helsinki"] },
    usa: { label: "USA", set: ["USA"] },
  };
  const CATEGORIES = [
    ["momentum", "Momentum – sterk trend"],
    ["analyst_upside", "Analytiker-oppside"],
    ["upgrades", "Nylige oppgraderinger"],
    ["breakout", "Utbrudd / nær 52-ukers topp"],
    ["oversold_quality", "Oversolgt kvalitet"],
    ["insider_buying", "Innsidekjøp"],
  ];
  const VERDICTS = ["Sterkt kjøp", "Kjøp", "Hold", "Avvent", "Unngå"];
  const VCLASS = { "Sterkt kjøp": "v-strong", "Kjøp": "v-buy", "Hold": "v-hold", "Avvent": "v-wait", "Unngå": "v-avoid" };
  const VHINT = {
    "Sterkt kjøp": "Høy samlet score, bekreftet opptrend og ingen risikoflagg.",
    "Kjøp": "God samlet score og opptrend – verdt å undersøke nærmere.",
    "Hold": "Middels bilde, eller et risikoflagg som holder igjen.",
    "Avvent": "Svak score eller nylig trendbrudd – vent på bedre inngang.",
    "Unngå": "Svak score på tvers av teknisk, fundamentalt og analytikere.",
  };
  const SORTS = [
    ["score", "Samlet score", "score"],
    ["score_technical", "Teknisk", "score"],
    ["score_analyst", "Analytiker", "score"],
    ["score_fundamental", "Fundamental", "score"],
    ["score_insider", "Innsider", "score"],
    ["change_1d", "Endring i dag", "pct"],
    ["ret_1m", "1 måned", "pct"],
    ["ret_3m", "3 måneder", "pct"],
    ["ret_6m", "6 måneder", "pct"],
    ["upside", "Kursmål-oppside", "pct"],
    ["pct_from_52w_high", "Fra 52-ukers topp", "pct"],
    ["rsi", "RSI", "num0"],
    ["forwardPE", "Forventet P/E (lav først)", "num1", "asc"],
    ["dividendYield", "Direkteavkastning", "pctu"],
  ];
  const TABS = [["ideer", "Ideer"], ["kjop", "Kjøp"], ["screener", "Screener"], ["varsler", "Varsler"]];

  const state = { data: null, tab: "ideer", market: "alle", sort: "score", query: "", verdictFilter: null, error: null };
  try {
    state.tab = localStorage.getItem("ar.tab") || state.tab;
    state.market = localStorage.getItem("ar.market") || state.market;
  } catch (e) { /* lagring utilgjengelig – ignorer */ }
  if (!MARKETS[state.market]) state.market = "alle";
  if (!TABS.some(t => t[0] === state.tab)) state.tab = "ideer";

  // ---------- formatering ----------
  const isNum = x => typeof x === "number" && isFinite(x);
  const nbsp = " ";
  function num(x, d) {
    if (!isNum(x)) return "–";
    return x.toLocaleString("nb-NO", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function pct(x, signed, d) {
    if (!isNum(x)) return "–";
    const v = x * 100, s = num(v, d == null ? 1 : d);
    return (signed !== false && v > 0 ? "+" : "") + s + nbsp + "%";
  }
  const sc = x => (isNum(x) ? String(Math.round(x)) : "–");
  const scClass = x => (!isNum(x) ? "" : x >= 70 ? "hi" : x >= 50 ? "mid" : "lo");
  const sign = x => (!isNum(x) || x === 0 ? "" : x > 0 ? "pos" : "neg");
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("nb-NO", { day: "numeric", month: "short" });
  }
  function fmtUpdated(d) {
    if (!d) return "";
    const gen = d.generated_at ? new Date(d.generated_at) : null;
    const today = new Date().toISOString().slice(0, 10);
    const when = d.run_date === today ? "i dag" : fmtDate(d.run_date);
    const clock = gen ? " " + gen.toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit" }) : "";
    return `Oppdatert ${when}${clock} · ${d.universe} aksjer`;
  }
  function fmtValue(key, kind, s) {
    const v = s[key];
    if (kind === "score") return sc(v);
    if (kind === "pct") return pct(v);
    if (kind === "pctu") return pct(v, false);
    if (kind === "num0") return num(v, 0);
    return num(v, 1);
  }
  const vbadge = (v, big) => v ? `<span class="vb ${VCLASS[v] || ""} ${big ? "big" : ""}">${esc(v)}</span>` : "";

  // ---------- ikoner ----------
  const I = {
    radar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12 19 6"/><circle cx="12" cy="12" r="1" fill="currentColor"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v5h-5"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/></svg>',
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 5-7 7 7 7"/></svg>',
    ext: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></svg>',
    ideer: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.1 1 1.8V16h5v-.3c0-.7.4-1.3 1-1.8A6 6 0 0 0 12 3z"/></svg>',
    kjop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.5 2.5L16 9.5"/></svg>',
    screener: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M7 12h10M10 18h4"/></svg>',
    varsler: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2.5 19.5h19L12 3z"/><path d="M12 10v4M12 17.5v.5"/></svg>',
  };

  // ---------- data ----------
  async function load(force) {
    const btn = $("#refresh");
    if (btn) btn.classList.add("spin");
    state.error = null;
    try {
      const url = "data.json" + (force ? "?t=" + Date.now() : "");
      const r = await fetch(url, { cache: force ? "reload" : "default" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      state.data = await r.json();
    } catch (e) {
      if (window.__DATA__) state.data = window.__DATA__;
      else state.error = e;
    }
    if (btn) btn.classList.remove("spin");
    render();
  }

  const stocks = () => (state.data && state.data.stocks) || [];
  const byTicker = t => stocks().find(s => s.ticker === t);
  function inMarket(s) {
    const set = MARKETS[state.market].set;
    return !set || set.includes(s.market);
  }
  const filtered = () => stocks().filter(inMarket);
  function ideaItems(key) {
    const items = (state.data && state.data.ideas && state.data.ideas[key]) || [];
    return items.filter(inMarket);
  }
  const buyCandidates = () => filtered().filter(s => s.verdict === "Sterkt kjøp" || s.verdict === "Kjøp")
    .sort((a, b) => (b.score || 0) - (a.score || 0));

  // ---------- byggeklosser ----------
  function sparkline(h, W, H) {
    if (!h || !h.close || h.close.length < 5) return "";
    const pts = h.close.slice(-45);
    const lo = Math.min.apply(null, pts), hi = Math.max.apply(null, pts), span = hi - lo || 1;
    const x = i => (i / (pts.length - 1)) * (W - 2) + 1;
    const y = v => H - 2 - ((v - lo) / span) * (H - 4);
    const d = pts.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join("");
    const col = pts[pts.length - 1] >= pts[0] ? "var(--up)" : "var(--down)";
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">
      <path d="${d}L${x(pts.length - 1).toFixed(1)} ${H}L1 ${H}Z" fill="${col}" opacity="0.14"/>
      <path d="${d}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${x(pts.length - 1).toFixed(1)}" cy="${y(pts[pts.length - 1]).toFixed(1)}" r="2" fill="${col}"/></svg>`;
  }

  function row(s, opts) {
    opts = opts || {};
    const st = byTicker(s.ticker) || s;
    const info = opts.info != null ? opts.info : `<span class="${sign(st.change_1d)}">${pct(st.change_1d)} i dag</span> · kursmål ${pct(st.upside)}`;
    const sub = opts.sub ? `<span class="sub">${opts.sub}</span>` : "";
    const rank = opts.rank ? `<span class="rank">${opts.rank}</span>` : "";
    return `<button class="row" data-ticker="${esc(st.ticker)}">
      <span class="l">
        <span class="l1">${rank}<span class="tick">${esc(st.ticker)}</span><span class="name">${esc(st.name)}</span></span>
        <span class="l2">${vbadge(st.verdict)}<span class="info mono">${info}</span></span>
      </span>
      <span class="mid">${sparkline(st.history, 64, 26)}</span>
      <span class="r"><span class="pill ${scClass(st.score)}">${sc(st.score)}</span></span>${sub}
    </button>`;
  }
  function list(html, emptyText) {
    return html ? `<div class="list">${html}</div>` : `<div class="empty">${emptyText || "Ingen treff."}</div>`;
  }
  function sectionHead(title, count) {
    return `<div class="section-head"><h2>${esc(title)}</h2>${count != null ? `<span class="count">${count}</span>` : ""}</div>`;
  }
  function heroCard(s) {
    const reasons = (s.verdict_reasons || []).slice(1, 4);
    return `<button class="hero-card" data-ticker="${esc(s.ticker)}">
      <span class="hc-top">${vbadge(s.verdict)}<span class="pill ${scClass(s.score)}">${sc(s.score)}</span></span>
      <span class="hc-tick">${esc(s.ticker)}</span>
      <span class="hc-name">${esc(s.name)} · ${esc(s.market)}</span>
      <span class="hc-spark">${sparkline(s.history, 240, 56)}</span>
      <span class="hc-price"><b class="mono">${num(s.price, 2)}</b> <span class="muted">${esc(s.currency || "")}</span> <span class="mono ${sign(s.change_1d)}">${pct(s.change_1d)}</span></span>
      <span class="hc-why">${reasons.map(r => `<span>${esc(r)}</span>`).join("")}</span>
    </button>`;
  }

  // ---------- faner ----------
  function viewIdeer() {
    const cands = buyCandidates().slice(0, 5);
    let html = `<div class="section">${sectionHead("Dagens kjøpskandidater", cands.length)}`;
    html += cands.length
      ? `<div class="hero">${cands.map(heroCard).join("")}</div>`
      : `<div class="empty">Ingen aksjer oppfyller kjøpskravene i dette markedet i dag.</div>`;
    html += `</div>`;
    for (const [key, title] of CATEGORIES) {
      const items = ideaItems(key);
      html += `<div class="section">${sectionHead(title, items.length)}${list(
        items.map(it => row(it, { sub: esc(it.reasons.join(" · ")) })).join(""), "Ingen treff i dag."
      )}</div>`;
    }
    html += `<p class="note">Anbefalingene er regelbaserte signaler, ikke investeringsråd. Trykk <b>i</b> øverst for å se reglene.</p>`;
    return html;
  }

  function viewKjop() {
    const all = filtered();
    const counts = {};
    VERDICTS.forEach(v => { counts[v] = all.filter(s => s.verdict === v).length; });
    let html = `<div class="tiles">${VERDICTS.map(v =>
      `<button class="tile ${VCLASS[v]} ${state.verdictFilter === v ? "on" : ""}" data-verdict="${esc(v)}"><b class="mono">${counts[v]}</b><span>${esc(v)}</span></button>`).join("")}</div>`;
    const show = state.verdictFilter ? [state.verdictFilter] : VERDICTS;
    for (const v of show) {
      const rows = all.filter(s => s.verdict === v).sort((a, b) => (b.score || 0) - (a.score || 0));
      html += `<div class="section">${sectionHead(v, rows.length)}<p class="hint">${esc(VHINT[v])}</p>${list(
        rows.map(s => row(s, { rank: s.rank, sub: esc((s.verdict_reasons || []).slice(1, 4).join(" · ")) })).join(""), "Ingen i dette markedet.")}</div>`;
    }
    html += `<p class="note">Reglene: score ≥ 75 gir Sterkt kjøp, ≥ 65 Kjøp, ≥ 50 Hold, ≥ 40 Avvent, ellers Unngå. Kjøp krever kurs over SMA200; death cross, sterkt overkjøpt RSI, negative analytikere eller kurs over kursmål trekker ned. Ikke investeringsråd.</p>`;
    return html;
  }

  function viewScreener() {
    const sortDef = SORTS.find(x => x[0] === state.sort) || SORTS[0];
    const [key, label, kind, dir] = sortDef;
    const q = state.query.trim().toLowerCase();
    let rows = filtered().filter(s => !q || s.ticker.toLowerCase().includes(q) || String(s.name).toLowerCase().includes(q));
    rows.sort((a, b) => {
      const av = isNum(a[key]) ? a[key] : (dir === "asc" ? Infinity : -Infinity);
      const bv = isNum(b[key]) ? b[key] : (dir === "asc" ? Infinity : -Infinity);
      return dir === "asc" ? av - bv : bv - av;
    });
    const options = SORTS.map(x => `<option value="${x[0]}" ${x[0] === state.sort ? "selected" : ""}>${esc(x[1])}</option>`).join("");
    const html = rows.map(s => row(s, {
      rank: s.rank,
      info: `${esc(label)}: <b class="${kind === "pct" ? sign(s[key]) : ""}">${fmtValue(key, kind, s)}</b>`,
    })).join("");
    return `<div class="tools">
        <input id="q" type="search" placeholder="Søk ticker eller navn" value="${esc(state.query)}" autocomplete="off">
        <select id="sort" aria-label="Sorter etter">${options}</select>
      </div>
      <div class="section">${sectionHead(label, rows.length)}${list(html)}</div>`;
  }

  function viewVarsler() {
    const items = ideaItems("warnings");
    const html = items.map(it => row(it, { sub: esc(it.reasons.join(" · ")) })).join("");
    return `<div class="section">${sectionHead("Svakhetstegn", items.length)}${list(html, "Ingen varsler i dag.")}</div>
      <p class="note">Varsler er aksjer i universet som viser svakhet: death cross, brudd under SMA200, flere nedgraderinger, sterkt overkjøpt RSI eller mange innsidesalg. Nyttig for aksjer du eier.</p>`;
  }

  // ---------- detaljark ----------
  function chartSVG(h) {
    if (!h || !h.close || h.close.length < 10) return "";
    const W = 360, H = 170, padL = 6, padR = 46, padT = 10, padB = 22;
    const n = h.close.length;
    const all = h.close.concat(h.sma_fast.filter(isNum), h.sma_slow.filter(isNum));
    const lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    const span = hi - lo || 1;
    const x = i => padL + (i / (n - 1)) * (W - padL - padR);
    const y = v => padT + (1 - (v - lo) / span) * (H - padT - padB);
    const path = arr => {
      let d = "", started = false;
      arr.forEach((v, i) => { if (!isNum(v)) { started = false; return; } d += (started ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); started = true; });
      return d;
    };
    const closePath = path(h.close);
    const area = closePath + `L${x(n - 1).toFixed(1)} ${(H - padB).toFixed(1)}L${x(0).toFixed(1)} ${(H - padB).toFixed(1)}Z`;
    const last = h.close[n - 1];
    const col = last >= h.close[0] ? "var(--up)" : "var(--down)";
    const gridY = [lo, lo + span / 2, hi];
    const grid = gridY.map(v => `<line x1="${padL}" x2="${W - padR}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="var(--line)" stroke-width="1"/>
      <text x="${W - padR + 6}" y="${(y(v) + 4).toFixed(1)}" font-size="10" fill="var(--muted)" font-family="var(--font-mono)">${num(v, v > 500 ? 0 : 1)}</text>`).join("");
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Kursgraf siste ${n} handelsdager">
      ${grid}
      <path d="${area}" fill="${col}" opacity="0.12"/>
      <path d="${path(h.sma_slow)}" fill="none" stroke="var(--warn)" stroke-width="1.3" stroke-dasharray="3 3"/>
      <path d="${path(h.sma_fast)}" fill="none" stroke="var(--accent)" stroke-width="1.3"/>
      <path d="${closePath}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${x(n - 1).toFixed(1)}" cy="${y(last).toFixed(1)}" r="3.5" fill="${col}" stroke="var(--surface)" stroke-width="2"/>
      <text x="${padL}" y="${H - 6}" font-size="10" fill="var(--muted)">${fmtDate(h.dates[0])}</text>
      <text x="${W - padR}" y="${H - 6}" font-size="10" fill="var(--muted)" text-anchor="end">${fmtDate(h.dates[n - 1])}</text>
    </svg>`;
  }

  function showSheet(html, push, key) {
    const sheet = $("#sheet");
    sheet.innerHTML = html;
    sheet.hidden = false;
    requestAnimationFrame(() => sheet.classList.add("open"));
    sheet.scrollTop = 0;
    document.body.style.overflow = "hidden";
    $("#back").addEventListener("click", () => history.back());
    if (push !== false) history.pushState(key, "", "");
  }
  function sheetTop(title, subtitle, right) {
    return `<div class="sheet-top"><div class="gutter bar">
        <button class="back" id="back" aria-label="Tilbake">${I.back}Tilbake</button>
        <div class="ttl"><b>${title}</b><span>${subtitle}</span></div>${right || ""}
      </div></div>`;
  }

  function openStock(ticker, push) {
    const s = byTicker(ticker);
    if (!s) return;
    const w = (state.data && state.data.weights) || {};
    const ideaReasons = [];
    for (const [key] of CATEGORIES.concat([["warnings"]])) {
      const it = ((state.data.ideas || {})[key] || []).find(x => x.ticker === ticker);
      if (it) ideaReasons.push(...it.reasons);
    }
    const chips = [
      ["Over SMA50", s.above_sma_fast], ["Over SMA200", s.above_sma_slow], ["SMA50 > SMA200", s.fast_gt_slow],
      ["Golden cross", s.golden_cross], ["MACD positiv", isNum(s.macd_hist) && s.macd_hist > 0], ["MACD krysset opp", s.macd_cross_up],
      ["Utbrudd", s.breakout], ["Nær 52-ukers topp", s.near_52w_high], ["Volumhopp", s.volume_spike],
      ["Oversolgt (RSI<30)", s.oversold, "bad"], ["Overkjøpt (RSI>70)", s.overbought, "bad"],
      ["Death cross", s.death_cross, "bad"], ["Brutt under SMA200", s.broke_below_slow, "bad"],
    ];
    const kv = [
      ["Markedsverdi", isNum(s.market_cap) ? num(s.market_cap / 1e9, 1) + " mrd" : "–"],
      ["Sektor", s.sector || "–"],
      ["P/E", num(s.trailingPE, 1)], ["Forventet P/E", num(s.forwardPE, 1)],
      ["EV/EBITDA", num(s.enterpriseToEbitda, 1)], ["PEG", num(s.trailingPegRatio, 2)],
      ["Omsetningsvekst", pct(s.revenueGrowth)], ["Resultatvekst", pct(s.earningsGrowth)],
      ["Netto margin", pct(s.profitMargins, false)], ["Egenkapitalavk.", pct(s.returnOnEquity, false)],
      ["Gjeld/EK", num(s.debtToEquity, 0)], ["FCF-yield", pct(s.fcf_yield, false)],
      ["Direkteavkastning", pct(s.dividendYield, false)], ["Beta", num(s.beta, 2)],
      ["1 mnd", pct(s.ret_1m)], ["3 mnd", pct(s.ret_3m)], ["6 mnd", pct(s.ret_6m)], ["12 mnd", pct(s.ret_12m)],
      ["RSI", num(s.rsi, 0)], ["Fra 52-ukers topp", pct(s.pct_from_52w_high)],
    ];
    const scoreRows = [
      ["Samlet", s.score, "total"],
      [`Teknisk (${Math.round((w.technical || 0) * 100)}%)`, s.score_technical],
      [`Analytiker (${Math.round((w.analyst || 0) * 100)}%)`, s.score_analyst],
      [`Fundamental (${Math.round((w.fundamental || 0) * 100)}%)`, s.score_fundamental],
      [`Innsider (${Math.round((w.insider || 0) * 100)}%)`, s.score_insider],
    ];
    const analyst = s.n_analysts > 0
      ? `<p style="margin:0 0 6px">${s.n_analysts} analytikere · konsensus <b class="mono">${num(s.rec_mean, 1)}</b> (${esc(s.rec_key || "–")}) · snittkursmål <b class="mono">${num(s.target_mean, 2)}</b> <span class="mono ${sign(s.upside)}">${pct(s.upside)}</span></p>
         <p class="muted" style="margin:0 0 8px;font-size:13px">Oppgraderinger siste 90 d: ${s.upgrades_90d || 0} · nedgraderinger: ${s.downgrades_90d || 0}</p>`
      : `<p class="muted" style="margin:0">Ingen analytikerdekning i Yahoo-data.</p>`;
    const upgrades = (s.upgrades || []).length
      ? `<div class="lines">${s.upgrades.map(u => `<div class="ln"><span class="d">${fmtDate(u.date)}</span><span class="t">${esc(u.firm)}: ${esc(u.from || "–")} → ${esc(u.to)}</span><span class="v ${u.action === "up" ? "pos" : u.action === "down" ? "neg" : "muted"}">${u.action === "up" ? "opp" : u.action === "down" ? "ned" : esc(u.action)}</span></div>`).join("")}</div>`
      : "";
    const insider = (s.insider || []).length
      ? `<div class="lines">${s.insider.map(t => `<div class="ln"><span class="d">${fmtDate(t.date)}</span><span class="t">${esc(t.insider || "")}${t.position ? " · " + esc(t.position) : ""}</span><span class="v ${t.kind === "buy" ? "pos" : "neg"}">${t.kind === "buy" ? "Kjøp" : "Salg"} ${isNum(t.value) ? num(t.value / 1e6, 1) + " mill" : isNum(t.shares) ? num(t.shares, 0) + " aksjer" : ""}</span></div>`).join("")}</div>`
      : `<p class="muted" style="margin:0">Ingen registrerte innsidehandler i Yahoo-data.</p>`;
    const vr = s.verdict_reasons || [];

    showSheet(`
      ${sheetTop(esc(s.ticker), `${esc(s.name)} · ${esc(s.market)}`, `<span class="pill ${scClass(s.score)}">${sc(s.score)}</span>`)}
      <div class="gutter sheet-body">
        <div class="price-row">
          <span class="price">${num(s.price, 2)}</span><span class="cur">${esc(s.currency || "")}</span>
          <span class="chg ${sign(s.change_1d)}">${pct(s.change_1d)}</span>
          <span class="asof">Sluttkurs ${fmtDate(s.last_date)}${isNum(s.rank) ? ` · plass ${s.rank} av ${stocks().length}` : ""}</span>
        </div>
        <div class="verdict ${VCLASS[s.verdict] || ""}">
          <div class="vd-head">${vbadge(s.verdict, true)}<span class="vd-meta">Risiko: <b>${esc(s.risk || "–")}</b> · Datagrunnlag: <b>${esc(s.coverage || "–")}</b></span></div>
          <p class="vd-hint">${esc(VHINT[s.verdict] || "")}</p>
          ${vr.length ? `<ul class="vd-why">${vr.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
        </div>
        <div class="chart">${chartSVG(s.history)}
          <div class="legend"><span><i style="background:var(--accent)"></i>SMA50</span><span><i style="background:var(--warn)"></i>SMA200</span><span><i style="background:var(--muted)"></i>Sluttkurs</span></div>
        </div>
        ${ideaReasons.length ? `<div class="card"><h3>Signaler i dag</h3><ul class="reasons" style="margin:0;padding-left:18px">${[...new Set(ideaReasons)].map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>` : ""}
        <div class="card"><h3>Score</h3><div class="scores">${scoreRows.map(([l, v, cls]) =>
          `<span class="lbl ${cls || ""}">${esc(l)}</span><span class="bar ${cls || ""}"><i style="width:${isNum(v) ? Math.max(2, v) : 0}%"></i></span><span class="val ${cls || ""}">${sc(v)}</span>`).join("")}</div></div>
        <div class="card"><h3>Tekniske signaler</h3><div class="chips">${chips.map(([l, on, bad]) => `<span class="chip ${on ? "on" : ""} ${bad || ""}">${esc(l)}</span>`).join("")}</div></div>
        <div class="card"><h3>Analytikere</h3>${analyst}${upgrades}</div>
        <div class="card"><h3>Nøkkeltall</h3><dl class="kv" style="margin:0">${kv.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl></div>
        <div class="card"><h3>Innsidehandler (180 d)</h3>${insider}</div>
        <a class="ext" href="https://finance.yahoo.com/quote/${encodeURIComponent(s.ticker)}" target="_blank" rel="noopener">Åpne i Yahoo Finance ${I.ext}</a>
        <p class="note">Mekaniske signaler fra offentlige data – ikke investeringsråd. Gjør egen vurdering før du handler.</p>
      </div>`, push, { ticker });
  }

  function openInfo(push) {
    const w = (state.data && state.data.weights) || { technical: 0.35, analyst: 0.25, fundamental: 0.25, insider: 0.15 };
    showSheet(`
      ${sheetTop("Om Aksjeradar", "Slik regnes anbefalingene ut")}
      <div class="gutter sheet-body">
        <div class="card"><h3>Anbefalingen</h3>
          <p>Hver aksje får en samlet score fra 0 til 100. Den setter utgangspunktet:</p>
          <div class="rules">${VERDICTS.map((v, i) => `<div>${vbadge(v)}<span>${["score 75 eller høyere", "score 65–74", "score 50–64", "score 40–49", "score under 40"][i]}</span></div>`).join("")}</div>
          <p>Deretter justeres den: <b>Kjøp krever at kursen er over SMA200</b> (bekreftet opptrend), ellers ett hakk ned. Death cross eller brudd under SMA200 gir høyst Avvent. Sterkt overkjøpt RSI (over 78), negative analytikere, kurs over analytikernes kursmål eller flere nedgraderinger gir høyst Hold. Tynt datagrunnlag gir aldri Sterkt kjøp.</p>
          <p><b>Risiko</b> er daglig svingning (ATR i prosent av kursen): lav under 1,5 %, middels til 3 %, høy over. <b>Datagrunnlag</b> sier hvor mange av de fire delscorene som finnes.</p>
        </div>
        <div class="card"><h3>Delscorene</h3>
          <dl class="kv one" style="margin:0">
            <div><dt>Teknisk · ${Math.round(w.technical * 100)} %</dt><dd class="txt">Trend (kurs mot SMA50/200, golden/death cross), MACD, RSI, utbrudd over 60-dagers topp, nærhet til 52-ukers topp, volumhopp og 6-måneders styrke mot resten av universet.</dd></div>
            <div><dt>Analytiker · ${Math.round(w.analyst * 100)} %</dt><dd class="txt">Yahoo-konsensus (1 = sterkt kjøp … 5 = selg), oppside til snittkursmål og opp-/nedgraderinger siste 90 dager. Krever minst tre analytikere.</dd></div>
            <div><dt>Fundamental · ${Math.round(w.fundamental * 100)} %</dt><dd class="txt">P/E, forventet P/E, EV/EBITDA, PEG, P/B, gjeld, vekst, marginer, egenkapitalavkastning og FCF-yield, rangert mot de andre aksjene.</dd></div>
            <div><dt>Innsider · ${Math.round(w.insider * 100)} %</dt><dd class="txt">Kjøp mot salg (i kroner) blant innsidere siste 180 dager.</dd></div>
          </dl>
          <p class="muted" style="font-size:13px">Mangler en delscore, fordeles vekten på de andre.</p>
        </div>
        <div class="card"><h3>Idékategoriene</h3>
          <ul class="reasons" style="margin:0;padding-left:18px">
            <li><b>Momentum</b> – teknisk score ≥ 65, over SMA200, RSI ≤ 75.</li>
            <li><b>Analytiker-oppside</b> – konsensus ≤ 2,5 og minst 15 % oppside til kursmål.</li>
            <li><b>Nylige oppgraderinger</b> – minst én oppgradering siste 30 dager.</li>
            <li><b>Utbrudd</b> – over 60-dagers topp på høyt volum, eller nær 52-ukers topp med volumhopp.</li>
            <li><b>Oversolgt kvalitet</b> – RSI under 35, god fundamental score, ikke ned mer enn 25 % siste år.</li>
            <li><b>Innsidekjøp</b> – innsiderscore ≥ 70 og minst ett kjøp siste 90 dager.</li>
          </ul>
        </div>
        <div class="card"><h3>Begrensninger</h3>
          <p>Data fra Yahoo Finance er ca. 15 minutter forsinket, og analytikerdekningen på mindre nordiske selskaper er tynn. Reglene er ikke backtestet. Bruk listene som et utgangspunkt for egen vurdering – dette er ikke investeringsråd.</p>
        </div>
      </div>`, push, { info: true });
  }

  function closeSheet() {
    const sheet = $("#sheet");
    if (sheet.hidden) return;
    sheet.classList.remove("open");
    document.body.style.overflow = "";
    setTimeout(() => { if (!sheet.classList.contains("open")) sheet.hidden = true; }, 300);
  }
  window.addEventListener("popstate", e => {
    if (e.state && e.state.ticker) openStock(e.state.ticker, false);
    else if (e.state && e.state.info) openInfo(false);
    else closeSheet();
  });

  // ---------- rammen ----------
  function renderHeader() {
    const d = state.data;
    $("#brand-sub").textContent = d ? fmtUpdated(d) : "";
    $("#seg").innerHTML = Object.entries(MARKETS).map(([k, m]) =>
      `<button data-market="${k}" aria-pressed="${k === state.market}">${m.label}</button>`).join("");
    const banners = [];
    if (d && d.demo) banners.push(`<div class="banner demo"><span><b>Demo-data.</b> Tallene er tilfeldige. Kjør <span class="mono">python run.py</span> for ekte data.</span></div>`);
    let dismissed = false;
    try { dismissed = localStorage.getItem("ar.hint") === "1"; } catch (e) { /* ignorer */ }
    const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
    const standalone = window.navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;
    if (!PREVIEW && ios && !standalone && !dismissed) {
      banners.push(`<div class="banner hint"><span>Legg til som app: trykk <b>Del</b> i Safari og velg <b>«Legg til på Hjem-skjerm»</b>.</span><button id="hint-close" aria-label="Lukk">✕</button></div>`);
    }
    $("#banners").innerHTML = banners.join("");
    const warnCount = state.data ? ideaItems("warnings").length : 0;
    const buyCount = state.data ? buyCandidates().length : 0;
    $("#tabs").innerHTML = TABS.map(([k, label]) => {
      const badge = k === "varsler" && warnCount ? `<span class="badge">${warnCount}</span>` : k === "kjop" && buyCount ? `<span class="badge ok">${buyCount}</span>` : "";
      return `<button data-tab="${k}" aria-current="${k === state.tab ? "page" : "false"}">${I[k]}${label}${badge}</button>`;
    }).join("");
  }

  function render() {
    renderHeader();
    const main = $("#view");
    if (state.error || !state.data) {
      main.innerHTML = `<div class="error"><p><b>Fant ingen data.</b></p><p>Kjør <code>python run.py</code> i prosjektmappen – da lages <code>docs/data.json</code>. Åpner du filen lokalt: start <code>python -m http.server 8000 -d docs</code> og gå til <code>http://localhost:8000</code>.</p>${state.error ? `<p class="muted">${esc(state.error.message || state.error)}</p>` : ""}</div>`;
      return;
    }
    const views = { ideer: viewIdeer, kjop: viewKjop, screener: viewScreener, varsler: viewVarsler };
    main.innerHTML = views[state.tab]();
    if (state.tab === "screener") {
      const q = $("#q");
      q.addEventListener("input", () => { state.query = q.value; const pos = q.selectionStart; render(); const q2 = $("#q"); q2.focus(); q2.setSelectionRange(pos, pos); });
      $("#sort").addEventListener("change", e => { state.sort = e.target.value; render(); });
    }
  }

  document.addEventListener("click", e => {
    const row = e.target.closest("[data-ticker]");
    if (row) { openStock(row.dataset.ticker); return; }
    const tile = e.target.closest("[data-verdict]");
    if (tile) { state.verdictFilter = state.verdictFilter === tile.dataset.verdict ? null : tile.dataset.verdict; render(); return; }
    const seg = e.target.closest("[data-market]");
    if (seg) { state.market = seg.dataset.market; try { localStorage.setItem("ar.market", state.market); } catch (x) { /* ignorer */ } render(); return; }
    const tab = e.target.closest("[data-tab]");
    if (tab) { state.tab = tab.dataset.tab; try { localStorage.setItem("ar.tab", state.tab); } catch (x) { /* ignorer */ } render(); window.scrollTo(0, 0); return; }
    if (e.target.closest("#refresh")) { load(true); return; }
    if (e.target.closest("#info")) { openInfo(); return; }
    if (e.target.closest("#hint-close")) { try { localStorage.setItem("ar.hint", "1"); } catch (x) { /* ignorer */ } renderHeader(); }
  });

  // Service worker gir offline-støtte og raskere oppstart (ikke i forhåndsvisning)
  if (!PREVIEW && "serviceWorker" in navigator && /^https?:/.test(location.protocol)) {
    navigator.serviceWorker.register("sw.js").catch(() => { /* ikke støttet her – appen virker likevel */ });
  }

  $("#brand-icon").innerHTML = I.radar;
  $("#refresh").innerHTML = I.refresh;
  $("#info").innerHTML = I.info;
  $("#view").innerHTML = `<div class="skeleton"><span></span><span></span><span></span></div>`;
  load(false);
})();
