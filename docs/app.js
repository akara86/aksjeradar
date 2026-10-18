/* Aksjeradar – mobil-app. Leser data.json (laget av run.py) og viser ideer, topp, screener, varsler
   og detaljer per aksje. Ingen rammeverk, ingen avhengigheter. */
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
  const TABS = [
    ["ideer", "Ideer"], ["topp", "Topp"], ["screener", "Screener"], ["varsler", "Varsler"],
  ];

  const state = { data: null, tab: "ideer", market: "alle", sort: "score", query: "", error: null };
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
  const scClass = x => (!isNum(x) ? "" : x >= 70 ? "hi" : x >= 50 ? "mid" : "");
  const sign = x => (!isNum(x) || x === 0 ? "" : x > 0 ? "pos" : "neg");
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("nb-NO", { day: "numeric", month: "short" });
  }
  function fmtValue(key, kind, s) {
    const v = s[key];
    if (kind === "score") return sc(v);
    if (kind === "pct") return pct(v);
    if (kind === "pctu") return pct(v, false);
    if (kind === "num0") return num(v, 0);
    return num(v, 1);
  }

  // ---------- ikoner ----------
  const I = {
    radar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12 19 6"/><circle cx="12" cy="12" r="1" fill="currentColor"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v5h-5"/></svg>',
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 5-7 7 7 7"/></svg>',
    ext: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></svg>',
    ideer: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.1 1 1.8V16h5v-.3c0-.7.4-1.3 1-1.8A6 6 0 0 0 12 3z"/></svg>',
    topp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 18 10 11l4 4 6-8"/><path d="M15 7h5v5"/></svg>',
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

  // ---------- byggeklosser ----------
  function row(s, opts) {
    opts = opts || {};
    const st = byTicker(s.ticker) || s;
    const right = opts.right != null ? opts.right : `<span class="metric ${sign(st.change_1d)}">${pct(st.change_1d)}</span>`;
    const sub = opts.sub ? `<span class="sub">${opts.sub}</span>` : "";
    const rank = opts.rank ? `<span class="rank">${opts.rank}</span>` : "";
    return `<button class="row" data-ticker="${esc(st.ticker)}">
      <span class="l">${rank}<span class="tick">${esc(st.ticker)}</span><span class="name">${esc(st.name)}</span></span>
      <span class="r">${right}<span class="pill ${scClass(st.score)}">${sc(st.score)}</span></span>${sub}
    </button>`;
  }
  function list(html, emptyText) {
    return html ? `<div class="list">${html}</div>` : `<div class="empty">${emptyText || "Ingen treff."}</div>`;
  }
  function sectionHead(title, count) {
    return `<div class="section-head"><h2>${esc(title)}</h2>${count != null ? `<span class="count">${count}</span>` : ""}</div>`;
  }

  // ---------- faner ----------
  function viewIdeer() {
    let html = "";
    for (const [key, title] of CATEGORIES) {
      const items = ideaItems(key);
      html += `<div class="section">${sectionHead(title, items.length)}${list(
        items.map(it => row(it, { sub: esc(it.reasons.join(" · ")) })).join(""), "Ingen treff i dag."
      )}</div>`;
    }
    return html;
  }

  function viewTopp() {
    const rows = filtered().slice().sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 30);
    const html = rows.map(s => {
      let arrow = "";
      if (isNum(s.rank_prev) && isNum(s.rank)) {
        const d = s.rank_prev - s.rank;
        arrow = d > 0 ? `<span class="arrow pos">▲${d}</span>` : d < 0 ? `<span class="arrow neg">▼${-d}</span>` : `<span class="arrow muted">–</span>`;
      }
      const sub = `<span class="delta ${sign(s.change_1d)}">${pct(s.change_1d)} i dag</span> · kursmål ${pct(s.upside)} · RSI ${num(s.rsi, 0)}` +
        (isNum(s.score_prev) ? ` · score ${sc(s.score_prev)} → ${sc(s.score)}` : "");
      return row(s, { rank: s.rank, right: arrow, sub });
    }).join("");
    return `<div class="section">${sectionHead("Høyest samlet score", rows.length)}${list(html)}</div>`;
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
      right: `<span class="metric ${kind === "pct" ? sign(s[key]) : ""}">${fmtValue(key, kind, s)}</span>`,
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
    const up = last >= h.close[0];
    const col = up ? "var(--up)" : "var(--down)";
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

  function openSheet(ticker, push) {
    const s = byTicker(ticker);
    if (!s) return;
    const sheet = $("#sheet");
    const w = (state.data && state.data.weights) || {};
    const reasons = [];
    for (const [key] of CATEGORIES.concat([["warnings"]])) {
      const it = ((state.data.ideas || {})[key] || []).find(x => x.ticker === ticker);
      if (it) reasons.push(...it.reasons);
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

    sheet.innerHTML = `
      <div class="sheet-top"><div class="gutter bar">
        <button class="back" id="back" aria-label="Tilbake">${I.back}Tilbake</button>
        <div class="ttl"><b>${esc(s.ticker)}</b><span>${esc(s.name)} · ${esc(s.market)}</span></div>
        <span class="pill ${scClass(s.score)}">${sc(s.score)}</span>
      </div></div>
      <div class="gutter sheet-body">
        <div class="price-row">
          <span class="price">${num(s.price, 2)}</span><span class="cur">${esc(s.currency || "")}</span>
          <span class="chg ${sign(s.change_1d)}">${pct(s.change_1d)}</span>
          <span class="asof">Sluttkurs ${fmtDate(s.last_date)}${isNum(s.rank) ? ` · plass ${s.rank} av ${stocks().length}` : ""}</span>
        </div>
        <div class="chart">${chartSVG(s.history)}
          <div class="legend"><span><i style="background:var(--accent)"></i>SMA50</span><span><i style="background:var(--warn)"></i>SMA200</span><span><i style="background:var(--muted)"></i>Sluttkurs</span></div>
        </div>
        ${reasons.length ? `<div class="card"><h3>Hvorfor den dukker opp</h3><ul class="reasons" style="margin:0;padding-left:18px">${[...new Set(reasons)].map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>` : ""}
        <div class="card"><h3>Score</h3><div class="scores">${scoreRows.map(([l, v, cls]) =>
          `<span class="lbl ${cls || ""}">${esc(l)}</span><span class="bar ${cls || ""}"><i style="width:${isNum(v) ? Math.max(2, v) : 0}%"></i></span><span class="val ${cls || ""}">${sc(v)}</span>`).join("")}</div></div>
        <div class="card"><h3>Tekniske signaler</h3><div class="chips">${chips.map(([l, on, bad]) => `<span class="chip ${on ? "on" : ""} ${bad || ""}">${esc(l)}</span>`).join("")}</div></div>
        <div class="card"><h3>Analytikere</h3>${analyst}${upgrades}</div>
        <div class="card"><h3>Nøkkeltall</h3><dl class="kv" style="margin:0">${kv.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl></div>
        <div class="card"><h3>Innsidehandler (180 d)</h3>${insider}</div>
        <a class="ext" href="https://finance.yahoo.com/quote/${encodeURIComponent(s.ticker)}" target="_blank" rel="noopener">Åpne i Yahoo Finance ${I.ext}</a>
      </div>`;
    sheet.hidden = false;
    requestAnimationFrame(() => sheet.classList.add("open"));
    sheet.scrollTop = 0;
    document.body.style.overflow = "hidden";
    $("#back").addEventListener("click", () => history.back());
    if (push !== false) history.pushState({ ticker }, "", "");
  }

  function closeSheet() {
    const sheet = $("#sheet");
    if (sheet.hidden) return;
    sheet.classList.remove("open");
    document.body.style.overflow = "";
    setTimeout(() => { if (!sheet.classList.contains("open")) sheet.hidden = true; }, 300);
  }
  window.addEventListener("popstate", e => {
    if (e.state && e.state.ticker) openSheet(e.state.ticker, false);
    else closeSheet();
  });

  // ---------- rammen ----------
  function renderHeader() {
    const d = state.data;
    const sub = d ? `${fmtDate(d.run_date)}${d.prev_run_date ? "" : ""} · ${d.universe} aksjer` : "";
    $("#brand-sub").textContent = sub;
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
    $("#tabs").innerHTML = TABS.map(([k, label]) =>
      `<button data-tab="${k}" aria-current="${k === state.tab ? "page" : "false"}">${I[k]}${label}${k === "varsler" && warnCount ? `<span class="badge">${warnCount}</span>` : ""}</button>`).join("");
  }

  function render() {
    renderHeader();
    const main = $("#view");
    if (state.error || !state.data) {
      main.innerHTML = `<div class="error"><p><b>Fant ingen data.</b></p><p>Kjør <code>python run.py</code> i prosjektmappen – da lages <code>docs/data.json</code>. Åpner du filen lokalt: start <code>python -m http.server 8000 -d docs</code> og gå til <code>http://localhost:8000</code>.</p>${state.error ? `<p class="muted">${esc(state.error.message || state.error)}</p>` : ""}</div>`;
      return;
    }
    const views = { ideer: viewIdeer, topp: viewTopp, screener: viewScreener, varsler: viewVarsler };
    main.innerHTML = views[state.tab]();
    if (state.tab === "screener") {
      const q = $("#q");
      q.addEventListener("input", () => { state.query = q.value; const pos = q.selectionStart; render(); const q2 = $("#q"); q2.focus(); q2.setSelectionRange(pos, pos); });
      $("#sort").addEventListener("change", e => { state.sort = e.target.value; render(); });
    }
  }

  document.addEventListener("click", e => {
    const row = e.target.closest(".row[data-ticker]");
    if (row) { openSheet(row.dataset.ticker); return; }
    const seg = e.target.closest("[data-market]");
    if (seg) { state.market = seg.dataset.market; try { localStorage.setItem("ar.market", state.market); } catch (x) { /* ignorer */ } render(); return; }
    const tab = e.target.closest("[data-tab]");
    if (tab) { state.tab = tab.dataset.tab; try { localStorage.setItem("ar.tab", state.tab); } catch (x) { /* ignorer */ } render(); window.scrollTo(0, 0); return; }
    if (e.target.closest("#refresh")) { load(true); return; }
    if (e.target.closest("#hint-close")) { try { localStorage.setItem("ar.hint", "1"); } catch (x) { /* ignorer */ } renderHeader(); }
  });

  // Service worker gir offline-støtte og raskere oppstart (ikke i forhåndsvisning)
  if (!PREVIEW && "serviceWorker" in navigator && /^https?:/.test(location.protocol)) {
    navigator.serviceWorker.register("sw.js").catch(() => { /* ikke støttet her – appen virker likevel */ });
  }

  $("#brand-icon").innerHTML = I.radar;
  $("#refresh").innerHTML = I.refresh;
  load(false);
})();
