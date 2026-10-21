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
  const TABS = [["ideer", "Ideer"], ["kjop", "Kjøp"], ["intradag", "Intradag"], ["guruer", "Guruer"], ["portefolje", "Portefølje"], ["auto", "Autotrader"], ["mer", "Mer"]];

  const state = { data: null, tab: "ideer", market: "alle", sort: "score", query: "", verdictFilter: null, error: null, limit: 80, expand: {} };
  const detailCache = {};
  let searchQuery = "";
  let currentTicker = null;
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
    search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.3-4.3"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/></svg>',
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 5-7 7 7 7"/></svg>',
    ext: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></svg>',
    ideer: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.1 1 1.8V16h5v-.3c0-.7.4-1.3 1-1.8A6 6 0 0 0 12 3z"/></svg>',
    kjop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.5 2.5L16 9.5"/></svg>',
    portefolje: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18"/></svg>',
    auto: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4M8 4h8M9 14h.01M15 14h.01M9 17h6"/></svg>',
    intradag: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/></svg>',
    guruer: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18h18M4 17 3 7l5 4 4-6 4 6 5-4-1 10z"/></svg>',
    mer: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
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
    if (force && auto) loadAuto(true);
    if (force && intra) loadIntra(true);
    if (force && gurus) loadGurus(true);
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
  function sparkline(arr, W, H) {
    if (!arr || arr.length < 5) return "";
    const pts = arr.slice(-45);
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
      <span class="mid">${sparkline(st.spark, 64, 26)}</span>
      <span class="r"><span class="pill ${scClass(st.score)}">${sc(st.score)}</span></span>${sub}
    </button>`;
  }
  function list(html, emptyText) {
    return html ? `<div class="list">${html}</div>` : `<div class="empty">${emptyText || "Ingen treff."}</div>`;
  }
  function more(remaining, key) {
    return remaining > 0 ? `<button class="more" data-more="${esc(key)}">Vis flere (${remaining} til)</button>` : "";
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
      <span class="hc-spark">${sparkline(s.spark, 240, 56)}</span>
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
    const gf = goodFunds();
    if (gf.length) {
      html += `<div class="section">${sectionHead("Fond – gunstig inngang nå", gf.length)}${gf.slice(0, 4).map(f => fundCard(f, true)).join("")}
        <button class="more" data-sub="fond">Se alle fond</button></div>`;
    }
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
      const cap = state.expand[v] ? rows.length : 40;
      html += `<div class="section">${sectionHead(v, rows.length)}<p class="hint">${esc(VHINT[v])}</p>${list(
        rows.slice(0, cap).map(s => row(s, { rank: s.rank, sub: esc((s.verdict_reasons || []).slice(1, 4).join(" · ")) })).join(""), "Ingen i dette markedet.")}${more(rows.length - cap, "verdict:" + v)}</div>`;
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
    const html = rows.slice(0, state.limit).map(s => row(s, {
      rank: s.rank,
      info: `${esc(label)}: <b class="${kind === "pct" ? sign(s[key]) : ""}">${fmtValue(key, kind, s)}</b>`,
    })).join("");
    return `<div class="tools">
        <input id="q" type="search" placeholder="Filtrer på ticker eller navn" value="${esc(state.query)}" autocomplete="off">
        <select id="sort" aria-label="Sorter etter">${options}</select>
      </div>
      <div class="section">${sectionHead(label, rows.length)}${list(html)}${more(rows.length - state.limit, "screener")}</div>`;
  }

  function viewVarsler() {
    const items = ideaItems("warnings");
    const html = items.map(it => row(it, { sub: esc(it.reasons.join(" · ")) })).join("");
    return `<div class="section">${sectionHead("Svakhetstegn", items.length)}${list(html, "Ingen varsler i dag.")}</div>
      <p class="note">Varsler er aksjer i universet som viser svakhet: death cross, brudd under SMA200, flere nedgraderinger, sterkt overkjøpt RSI eller mange innsidesalg. Nyttig for aksjer du eier.</p>`;
  }

  // ---------- kursgraf med tidsvelger (1D · 1U · 1M · 3M · 6M · 1Å · 2Å) ----------
  const RANGES = [["1D", "1 dag"], ["1W", "1 uke"], ["1M", "1 måned"], ["3M", "3 mnd"], ["6M", "6 mnd"], ["1Y", "1 år"], ["2Y", "2 år"]];
  const RANGE_DAYS = { "1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252, "2Y": 520 };
  const chartState = { range: "3M", sma: true, bars: {}, barsLoading: {} };
  try { chartState.range = localStorage.getItem("ar.range") || "3M"; chartState.sma = localStorage.getItem("ar.sma") !== "0"; } catch (e) { /* ignorer */ }
  if (!RANGES.some(r => r[0] === chartState.range)) chartState.range = "3M";

  async function loadBars(ticker) {
    if (chartState.bars[ticker] !== undefined || chartState.barsLoading[ticker]) return;
    chartState.barsLoading[ticker] = true;
    try {
      const r = await fetch("intraday/" + encodeURIComponent(ticker) + ".json", { cache: "reload" });
      chartState.bars[ticker] = r.ok ? await r.json() : null;
    } catch (e) { chartState.bars[ticker] = null; }
    chartState.barsLoading[ticker] = false;
    if (currentTicker === ticker) rerenderChart(ticker);
  }

  // Lager serien for valgt periode: {t: etiketter, c: slutt, o,h,l, v, sma20, sma50, sma200, prev: referansekurs, intraday}
  function seriesFor(s, range) {
    const h = s.history;
    if (range === "1D") {
      const b = chartState.bars[s.ticker];
      if (b === undefined) { loadBars(s.ticker); return { loading: true }; }
      if (!b || !b.c || b.c.length < 2) return { none: true, reason: "Ingen 15-minutters kurser for denne aksjen (intradag-universet dekker ~120 av aksjene)." };
      const days = [...new Set(b.t.map(x => x.slice(0, 10)))];
      const last = days[days.length - 1];
      const idx = b.t.map((x, i) => i).filter(i => b.t[i].startsWith(last));
      const prevIdx = b.t.map((x, i) => i).filter(i => !b.t[i].startsWith(last));
      const prev = prevIdx.length ? b.c[prevIdx[prevIdx.length - 1]] : (h && h.close.length > 1 ? h.close[h.close.length - 2] : b.o[idx[0]]);
      return {
        intraday: true, date: last, tz: b.tz,
        t: idx.map(i => b.t[i].slice(11)), c: idx.map(i => b.c[i]), o: idx.map(i => b.o[i]), h: idx.map(i => b.h[i]), l: idx.map(i => b.l[i]), v: idx.map(i => b.v[i]),
        prev, generated: b.generated_at,
      };
    }
    if (!h || !h.close || h.close.length < 2) return { none: true, reason: "Ingen kurshistorikk." };
    const n = Math.min(RANGE_DAYS[range] || 63, h.close.length - 1);
    const sl = a => (a ? a.slice(-n) : null);
    const prev = h.close[h.close.length - 1 - n];
    return {
      t: sl(h.dates), c: sl(h.close), o: sl(h.open), hi: sl(h.high), lo: sl(h.low), v: sl(h.volume),
      sma20: sl(h.sma20), sma50: sl(h.sma_fast), sma200: sl(h.sma_slow), prev,
    };
  }

  function bigChart(ser, cur) {
    const W = 360, H = 230, padL = 6, padR = 50, padT = 12, padB = 16, volH = 36;
    const n = ser.c.length;
    const highs = ser.hi || ser.h || ser.c, lows = ser.lo || ser.l || ser.c;
    let vals = highs.concat(lows).filter(isNum);
    if (chartState.sma && !ser.intraday) vals = vals.concat([ser.sma20, ser.sma50, ser.sma200].flatMap(a => (a || []).filter(isNum)));
    if (isNum(ser.prev)) vals.push(ser.prev);
    const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), span = hi - lo || 1;
    const top = padT, bottom = H - padB - volH - 6;
    const x = i => padL + (n === 1 ? 0 : (i / (n - 1)) * (W - padL - padR));
    const y = v => top + (1 - (v - lo) / span) * (bottom - top);
    const path = arr => { let d = "", on = false; arr.forEach((v, i) => { if (!isNum(v)) { on = false; return; } d += (on ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); on = true; }); return d; };
    const last = ser.c[n - 1], up = isNum(ser.prev) ? last >= ser.prev : last >= ser.c[0];
    const col = up ? "var(--up)" : "var(--down)";
    const closeP = path(ser.c);
    const area = closeP + `L${x(n - 1).toFixed(1)} ${bottom.toFixed(1)}L${x(0).toFixed(1)} ${bottom.toFixed(1)}Z`;
    const dec = hi > 500 ? 0 : hi > 20 ? 1 : 2;
    const ticks = [lo, lo + span * 0.25, lo + span * 0.5, lo + span * 0.75, hi];
    const grid = ticks.map(v => `<line x1="${padL}" x2="${W - padR}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="var(--line)" stroke-width="1"/>
      <text x="${W - padR + 5}" y="${(y(v) + 3.5).toFixed(1)}" font-size="9.5" fill="var(--muted)" font-family="var(--font-mono)">${num(v, dec)}</text>`).join("");
    const prevLine = isNum(ser.prev) && ser.prev >= lo && ser.prev <= hi
      ? `<line x1="${padL}" x2="${W - padR}" y1="${y(ser.prev).toFixed(1)}" y2="${y(ser.prev).toFixed(1)}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="2 3"/>` : "";
    // volum
    const vols = (ser.v || []).map(v => (isNum(v) ? v : 0));
    const vmax = Math.max.apply(null, vols.concat([1]));
    const bw = Math.max(1, (W - padL - padR) / n - 1);
    const volBars = vols.map((v, i) => {
      const hgt = (v / vmax) * volH;
      const c = ser.c[i] >= (i ? ser.c[i - 1] : (ser.o ? ser.o[i] : ser.c[i])) ? "var(--up)" : "var(--down)";
      return `<rect x="${(x(i) - bw / 2).toFixed(1)}" y="${(H - padB - hgt).toFixed(1)}" width="${bw.toFixed(1)}" height="${hgt.toFixed(1)}" fill="${c}" opacity="0.45"/>`;
    }).join("");
    const smaPaths = (chartState.sma && !ser.intraday)
      ? `<path d="${path(ser.sma200 || [])}" fill="none" stroke="var(--warn)" stroke-width="1.3" stroke-dasharray="3 3"/>
         <path d="${path(ser.sma50 || [])}" fill="none" stroke="var(--accent)" stroke-width="1.3"/>
         <path d="${path(ser.sma20 || [])}" fill="none" stroke="var(--muted)" stroke-width="1" opacity="0.8"/>` : "";
    // x-etiketter: 3–4 jevnt fordelt
    const labelIdx = [0, Math.round((n - 1) / 3), Math.round(2 * (n - 1) / 3), n - 1].filter((v, i, a) => a.indexOf(v) === i);
    const xl = labelIdx.map((i, k) => `<text x="${x(i).toFixed(1)}" y="${H - 3}" font-size="9.5" fill="var(--muted)" text-anchor="${k === 0 ? "start" : k === labelIdx.length - 1 ? "end" : "middle"}">${ser.intraday ? esc(ser.t[i]) : fmtDate(ser.t[i])}</text>`).join("");
    return `<svg id="bigchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Kursgraf">
      ${grid}${prevLine}
      <path d="${area}" fill="${col}" opacity="0.10"/>
      ${smaPaths}
      <path d="${closeP}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${x(n - 1).toFixed(1)}" cy="${y(last).toFixed(1)}" r="3.5" fill="${col}" stroke="var(--surface)" stroke-width="2"/>
      ${volBars}${xl}
      <g id="xh" hidden><line id="xh-l" y1="${top}" y2="${H - padB}" stroke="var(--fg)" stroke-width="1" opacity="0.5"/><circle id="xh-c" r="4" fill="var(--fg)" stroke="var(--surface)" stroke-width="2"/></g>
    </svg>`;
  }

  function periodStats(ser, cur) {
    const n = ser.c.length, last = ser.c[n - 1];
    const ref = isNum(ser.prev) ? ser.prev : ser.c[0];
    const chg = last / ref - 1;
    const highs = ser.hi || ser.h || ser.c, lows = ser.lo || ser.l || ser.c;
    const hi = Math.max.apply(null, highs.filter(isNum)), lo = Math.min.apply(null, lows.filter(isNum));
    const vols = (ser.v || []).filter(isNum);
    const avgVol = vols.length ? vols.reduce((a, b) => a + b, 0) / vols.length : null;
    const fmtVol = v => (!isNum(v) ? "–" : v >= 1e9 ? num(v / 1e9, 1) + " mrd" : v >= 1e6 ? num(v / 1e6, 1) + " mill" : v >= 1e3 ? num(v / 1e3, 0) + " k" : num(v, 0));
    return `<div class="pstats">
      <div><i>Endring</i><b class="mono ${sign(chg)}">${pct(chg)}</b><small class="mono ${sign(last - ref)}">${(last - ref >= 0 ? "+" : "") + num(last - ref, 2)}</small></div>
      <div><i>Høyeste</i><b class="mono">${num(hi, 2)}</b><small class="mono">${pct(last / hi - 1)} under</small></div>
      <div><i>Laveste</i><b class="mono">${num(lo, 2)}</b><small class="mono">${pct(last / lo - 1)} over</small></div>
      <div><i>${ser.intraday ? "Volum i dag" : "Snittvolum"}</i><b class="mono">${ser.intraday ? fmtVol(vols.reduce((a, b) => a + b, 0)) : fmtVol(avgVol)}</b><small>${ser.intraday ? (ser.generated ? "oppd. " + fmtClock(ser.generated) : "") : "per dag"}</small></div>
    </div>`;
  }

  function chartBlock(s) {
    const ser = seriesFor(s, chartState.range);
    const tabs = `<div class="rng">${RANGES.map(([k, l]) => `<button data-range="${k}" aria-pressed="${k === chartState.range}" title="${esc(l)}">${k === "1W" ? "1U" : k === "1Y" ? "1Å" : k === "2Y" ? "2Å" : k}</button>`).join("")}</div>`;
    let body;
    if (ser.loading) body = `<div class="skeleton" style="margin:0"><span style="height:230px"></span></div>`;
    else if (ser.none) body = `<p class="muted" style="margin:14px 8px;font-size:13.5px">${esc(ser.reason)}</p>`;
    else body = `${periodStats(ser, s.currency)}<div class="bc-wrap">${bigChart(ser, s.currency)}<div id="xh-tip" class="xh-tip" hidden></div></div>`;
    const legend = ser.intraday
      ? `<div class="legend"><span>15-min-kurser ${esc(ser.date ? fmtDate(ser.date) : "")} · stiplet = forrige sluttkurs · ca. 15 min forsinket</span></div>`
      : `<div class="legend"><button class="lg-toggle" id="sma-toggle" aria-pressed="${chartState.sma}">${chartState.sma ? "Skjul" : "Vis"} snitt</button>${chartState.sma ? `<span><i style="background:var(--muted)"></i>SMA20</span><span><i style="background:var(--accent)"></i>SMA50</span><span><i style="background:var(--warn)"></i>SMA200</span>` : ""}<span>stiplet = kurs ved periodestart</span></div>`;
    return `<div class="chart big" id="chart-box" data-chart="${esc(s.ticker)}">${tabs}${body}${legend}</div>`;
  }

  function rerenderChart(ticker) {
    const box = $("#chart-box");
    if (!box || box.dataset.chart !== ticker) return;
    const s = detailCache[ticker];
    if (!s) return;
    box.outerHTML = chartBlock(s);
    bindCrosshair();
  }

  // dra fingeren/musa over grafen for å lese av kurs og tidspunkt
  function bindCrosshair() {
    const svg = $("#bigchart"), box = $("#chart-box");
    if (!svg || !box) return;
    const ticker = box.dataset.chart, s = detailCache[ticker];
    if (!s) return;
    const ser = seriesFor(s, chartState.range);
    if (!ser.c) return;
    const n = ser.c.length, W = 360, padL = 6, padR = 50, padT = 12, padB = 16, volH = 36;
    const highs = ser.hi || ser.h || ser.c, lows = ser.lo || ser.l || ser.c;
    let vals = highs.concat(lows).filter(isNum);
    if (chartState.sma && !ser.intraday) vals = vals.concat([ser.sma20, ser.sma50, ser.sma200].flatMap(a => (a || []).filter(isNum)));
    if (isNum(ser.prev)) vals.push(ser.prev);
    const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), span = hi - lo || 1;
    const top = padT, bottom = 230 - padB - volH - 6;
    const x = i => padL + (n === 1 ? 0 : (i / (n - 1)) * (W - padL - padR));
    const y = v => top + (1 - (v - lo) / span) * (bottom - top);
    const g = $("#xh"), ln = $("#xh-l"), c = $("#xh-c"), tip = $("#xh-tip");
    const move = ev => {
      const r = svg.getBoundingClientRect();
      const px = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left;
      const fx = px / r.width * W;
      const i = Math.max(0, Math.min(n - 1, Math.round((fx - padL) / (W - padL - padR) * (n - 1))));
      const v = ser.c[i];
      g.hidden = false;
      ln.setAttribute("x1", x(i).toFixed(1)); ln.setAttribute("x2", x(i).toFixed(1));
      c.setAttribute("cx", x(i).toFixed(1)); c.setAttribute("cy", y(v).toFixed(1));
      const ref = isNum(ser.prev) ? ser.prev : ser.c[0];
      const o = ser.o ? ser.o[i] : null, h_ = highs[i], l_ = lows[i], vol = ser.v ? ser.v[i] : null;
      tip.hidden = false;
      tip.innerHTML = `<b class="mono">${num(v, 2)}</b> <span class="mono ${sign(v / ref - 1)}">${pct(v / ref - 1)}</span><br><span class="muted">${ser.intraday ? esc(ser.t[i]) : fmtDate(ser.t[i])}${isNum(o) ? ` · åpn ${num(o, 2)} · h ${num(h_, 2)} · l ${num(l_, 2)}` : ""}${isNum(vol) ? ` · vol ${vol >= 1e6 ? num(vol / 1e6, 1) + " mill" : num(vol, 0)}` : ""}</span>`;
      const left = Math.min(Math.max(px, 70), r.width - 70);
      tip.style.left = left + "px";
      if (ev.cancelable && ev.touches) ev.preventDefault();
    };
    const end = () => { g.hidden = true; tip.hidden = true; };
    svg.addEventListener("mousemove", move); svg.addEventListener("mouseleave", end);
    svg.addEventListener("touchstart", move, { passive: false }); svg.addEventListener("touchmove", move, { passive: false }); svg.addEventListener("touchend", end);
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

  function showSheet(html, push, key, replace) {
    const sheet = $("#sheet");
    const top = replace ? sheet.scrollTop : 0;
    sheet.innerHTML = html;
    sheet.hidden = false;
    requestAnimationFrame(() => sheet.classList.add("open"));
    sheet.scrollTop = top;
    document.body.style.overflow = "hidden";
    $("#back").addEventListener("click", () => history.back());
    if (push !== false && !replace) history.pushState(key, "", "");
  }

  // ---------- søk ----------
  function searchStocks(q) {
    q = q.trim().toLowerCase();
    if (!q) return [];
    const all = stocks();
    const score = s => {
      const t = s.ticker.toLowerCase(), base = t.split(".")[0], n = String(s.name || "").toLowerCase(), sec = String(s.sector || "").toLowerCase();
      if (t === q || base === q) return 0;
      if (base.startsWith(q)) return 1;
      if (n.startsWith(q)) return 2;
      if (n.split(/\s+/).some(w => w.startsWith(q))) return 3;
      if (n.includes(q) || t.includes(q)) return 4;
      if (sec.includes(q)) return 5;
      return 99;
    };
    return all.map(s => [score(s), s]).filter(x => x[0] < 99)
      .sort((a, b) => a[0] - b[0] || (b[1].score || 0) - (a[1].score || 0)).map(x => x[1]);
  }
  function renderSearchResults() {
    const box = $("#search-results");
    if (!box) return;
    const hits = searchStocks(searchQuery);
    const n = stocks().length;
    if (!searchQuery.trim()) {
      box.innerHTML = `<p class="note" style="margin-top:14px">Søk blant ${n} aksjer på ticker (f.eks. <span class="mono">EQNR</span>), navn (<span class="mono">Equinor</span>) eller sektor (<span class="mono">Energy</span>). Universet dekker Oslo Børs, Stockholm, København, Helsinki og hele S&P 500.</p>`;
      return;
    }
    if (!hits.length) {
      box.innerHTML = `<div class="empty" style="margin-top:14px">Ingen treff på «${esc(searchQuery)}» blant de ${n} aksjene som følges. Vil du ha den med, kan tickeren legges til i <span class="mono">config.yaml</span>.</div>`;
      return;
    }
    box.innerHTML = `<div class="section">${sectionHead("Treff", hits.length)}${list(hits.slice(0, 60).map(s => row(s, { rank: s.rank })).join(""))}</div>`;
  }
  function openSearch(push) {
    showSheet(`
      ${sheetTop("Søk", "Finn en bestemt aksje")}
      <div class="gutter sheet-body" style="padding-top:10px">
        <input id="search-input" class="search-input" type="search" placeholder="Ticker, navn eller sektor" value="${esc(searchQuery)}" autocomplete="off" autocorrect="off" autocapitalize="characters" spellcheck="false">
        <div id="search-results"></div>
      </div>`, push, { search: true });
    const inp = $("#search-input");
    inp.addEventListener("input", () => { searchQuery = inp.value; renderSearchResults(); });
    inp.addEventListener("keydown", e => { if (e.key === "Enter") { const h = searchStocks(searchQuery); if (h.length) openStock(h[0].ticker); } });
    renderSearchResults();
    setTimeout(() => { try { inp.focus(); } catch (e) { /* ignorer */ } }, 50);
  }
  function sheetTop(title, subtitle, right) {
    return `<div class="sheet-top"><div class="gutter bar">
        <button class="back" id="back" aria-label="Tilbake">${I.back}Tilbake</button>
        <div class="ttl"><b>${title}</b><span>${subtitle}</span></div>${right || ""}
      </div></div>`;
  }

  async function openStock(ticker, push) {
    const idx = byTicker(ticker);
    if (!idx) return;
    currentTicker = ticker;
    let s = detailCache[ticker];
    if (s) { renderStock(s, push, false); return; }
    renderStock(Object.assign({ _loading: true }, idx), push, false);
    try {
      const r = await fetch("stocks/" + encodeURIComponent(ticker) + ".json");
      if (r.ok) { s = await r.json(); detailCache[ticker] = s; }
    } catch (e) { /* uten nett eller fil – vis det vi har */ }
    if (currentTicker !== ticker) return;
    renderStock(s || Object.assign({ _nodetail: true }, idx), false, true);
  }

  function renderStock(s, push, replace) {
    const ticker = s.ticker;
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
        ${s._loading ? `<div class="chart big"><div class="skeleton" style="margin:0"><span style="height:230px"></span></div></div>` : s.history ? chartBlock(s) : `<div class="chart big"><p class="muted" style="margin:6px 8px">Kursgrafen er ikke tilgjengelig akkurat nå.</p></div>`}
        ${analysisCard(s)}
        ${stockPortfolioCard(s)}
        ${ideaReasons.length ? `<div class="card"><h3>Signaler i dag</h3><ul class="reasons" style="margin:0;padding-left:18px">${[...new Set(ideaReasons)].map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>` : ""}
        <div class="card"><h3>Score</h3><div class="scores">${scoreRows.map(([l, v, cls]) =>
          `<span class="lbl ${cls || ""}">${esc(l)}</span><span class="bar ${cls || ""}"><i style="width:${isNum(v) ? Math.max(2, v) : 0}%"></i></span><span class="val ${cls || ""}">${sc(v)}</span>`).join("")}</div></div>
        <div class="card"><h3>Tekniske signaler</h3><div class="chips">${chips.map(([l, on, bad]) => `<span class="chip ${on ? "on" : ""} ${bad || ""}">${esc(l)}</span>`).join("")}</div></div>
        <div class="card"><h3>Analytikere</h3>${analyst}${upgrades}</div>
        <div class="card"><h3>Nøkkeltall</h3><dl class="kv" style="margin:0">${kv.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl></div>
        <div class="card"><h3>Innsidehandler (180 d)</h3>${insider}</div>
        <a class="ext" href="https://finance.yahoo.com/quote/${encodeURIComponent(s.ticker)}" target="_blank" rel="noopener">Åpne i Yahoo Finance ${I.ext}</a>
        <p class="note">Mekaniske signaler fra offentlige data – ikke investeringsråd. Gjør egen vurdering før du handler.</p>
      </div>`, push, { ticker }, replace);
    bindCrosshair();
  }

  // ---------- analysetekst per aksje ----------
  function md(txt) { return esc(txt).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>"); }
  function analysisCard(s) {
    const a = s.analysis;
    if (!a) return s._loading ? "" : `<div class="card"><h3>Analyse</h3><p class="muted" style="margin:0">Analysen skrives ved neste daglige kjøring.</p></div>`;
    const open_ = (() => { try { return localStorage.getItem("ar.analysis") !== "0"; } catch (e) { return true; } })();
    return `<div class="card analysis"><h3>Analyse</h3>
      <p class="lead">${md(a.summary || "")}</p>
      <div class="procon">
        <div><h4 class="pos">For kjøp</h4><ul>${(a.pros || []).map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
        <div><h4 class="neg">Mot kjøp</h4><ul>${(a.cons || []).map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
      </div>
      <p class="concl">${md(a.conclusion || "")}</p>
      ${(a.would_change || []).length ? `<p class="wc"><b>Hva som ville endret vurderingen:</b> ${a.would_change.map(esc).join(" · ")}</p>` : ""}
      <button class="linkbtn" id="an-toggle" aria-expanded="${open_}">${open_ ? "Skjul" : "Les"} hele analysen</button>
      <div id="an-body" ${open_ ? "" : "hidden"}>
        ${(a.sections || []).map(sec => `<h4>${esc(sec.title)}</h4><p>${md(sec.text)}</p>`).join("")}
        ${a.about ? `<h4>Om selskapet <span class="muted" style="font-weight:400">(fra Yahoo, engelsk)</span></h4><p class="muted">${esc(a.about)}</p>` : ""}
      </div>
      <p class="note" style="margin-top:10px">Analysen er skrevet automatisk fra tallene og sammenligner med ${a.sector_ref && a.sector_ref.n ? `${a.sector_ref.n} aksjer i samme sektor` : "universet"}. Den beskriver hva dataene sier – ikke hva som kommer til å skje.</p>
    </div>`;
  }

  function openInfo(push) {
    const w = (state.data && state.data.weights) || { technical: 0.35, analyst: 0.25, fundamental: 0.25, insider: 0.15 };
    showSheet(`
      ${sheetTop("Om Aksjeradar", "Slik regnes anbefalingene ut")}
      <div class="gutter sheet-body">
        <div class="card"><h3>Anbefalingen</h3>
          <p>Hver aksje får en samlet score fra 0 til 100. Den setter utgangspunktet:</p>
          <div class="rules">${VERDICTS.map((v, i) => `<div>${vbadge(v)}<span>${["score 75 eller høyere", "score 65–74", "score 50–64", "score 40–49", "score under 40"][i]}</span></div>`).join("")}</div>
          <p>Deretter justeres den: <b>Kjøp krever at kursen er over SMA200</b> (bekreftet opptrend), ellers ett hakk ned. Death cross eller brudd under SMA200 gir høyst Avvent. Sterkt overkjøpt RSI (over 78), negative analytikere, kurs over analytikernes kursmål eller flere nedgraderinger gir høyst Hold. Datagrunnlaget teller også: bare teknisk bilde gir høyst Hold, og manglende delscorer regnes som nøytrale 50 i den samlede scoren.</p>
          <p><b>Risiko</b> er daglig svingning (ATR i prosent av kursen): lav under 1,5 %, middels til 3 %, høy over. <b>Datagrunnlag</b> sier hvor mange av de fire delscorene som finnes.</p>
        </div>
        <div class="card"><h3>Delscorene</h3>
          <dl class="kv one" style="margin:0">
            <div><dt>Teknisk · ${Math.round(w.technical * 100)} %</dt><dd class="txt">Trend (kurs mot SMA50/200, golden/death cross), MACD, RSI, utbrudd over 60-dagers topp, nærhet til 52-ukers topp, volumhopp og 6-måneders styrke mot resten av universet.</dd></div>
            <div><dt>Analytiker · ${Math.round(w.analyst * 100)} %</dt><dd class="txt">Yahoo-konsensus (1 = sterkt kjøp … 5 = selg), oppside til snittkursmål og opp-/nedgraderinger siste 90 dager. Krever minst tre analytikere.</dd></div>
            <div><dt>Fundamental · ${Math.round(w.fundamental * 100)} %</dt><dd class="txt">P/E, forventet P/E, EV/EBITDA, PEG, P/B, gjeld, vekst, marginer, egenkapitalavkastning og FCF-yield, rangert mot de andre aksjene.</dd></div>
            <div><dt>Innsider · ${Math.round(w.insider * 100)} %</dt><dd class="txt">Kjøp mot salg (i kroner) blant innsidere siste 180 dager.</dd></div>
          </dl>
          <p class="muted" style="font-size:13px">Mangler en delscore (f.eks. ingen analytikere), teller den som nøytral 50 – mindre data gir en score nærmere midten.</p>
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
        <div class="card"><h3>Portefølje og lekepenger</h3>
          <p><b>Mine aksjer</b> er det du faktisk eier: legg inn antall og kjøpskurs, så får du verdi, avkastning og et varsel når en av aksjene får Avvent/Unngå eller viser trendbrudd.</p>
          <p><b>Lekepenger</b> er en virtuell portefølje med fiktiv startkapital. Kjøp og salg skjer til siste sluttkurs i appen, og avkastningskurven bygges dag for dag. Bruk den til å prøve ut anbefalingene en stund før du handler med ekte penger.</p>
          <p>Begge lagres bare på denne enheten. Bruk «Sikkerhetskopi» nederst i Portefølje-fanen for å flytte dem til en annen telefon.</p>
        </div>
        <div class="card"><h3>Autotrader</h3>
          <p>En virtuell portefølje som følger anbefalingene helt automatisk, hver handelsdag, på serveren – uavhengig av om du åpner appen. Den kjøper dagens beste kjøpskandidater med like store posisjoner og selger ved Avvent/Unngå, trendbrudd eller stop-loss, med kurtasje og slippage trukket fra. Avkastningen måles mot et likevektet gjennomsnitt av hele universet, så du ser om reglene faktisk slår markedet over tid.</p>
        </div>
        <div class="card"><h3>Fond</h3>
          <p>Aksjefond følges via en indeks-ETF som speiler samme indeks, omregnet til NOK med dagens valutakurs. For hvert fond ser du fall fra 52-ukers topp i kroner, hvor mye som skyldes indeksen og hvor mye kronekursen, og et nivå (Svært gunstig / Gunstig / Nøytral / Dyr). Varsel når nivået skifter. Fondene du eier kan legges til i config.yaml under <span class="mono">funds.list</span>.</p>
        </div>
        <div class="card"><h3>Guruer</h3>
          <p>Porteføljene til kjente investorer (Buffett, Druckenmiller, Burry, Ackman, Tepper, Klarman, Li Lu m.fl.) hentes fra deres 13F-rapporter til SEC hvert kvartal. Fanen viser hva de eier, hva de kjøpte og solgte siste kvartal, og konsensus på tvers – hvilke aksjer flest eier og kjøper. Rapportene kommer inntil 45 dager etter kvartalsslutt og dekker bare amerikanske long-posisjoner.</p>
        </div>
        <div class="card"><h3>Intradag</h3>
          <p>Kortsiktige setups på 15-minutters kurser for ~120 likvide aksjer, oppdatert hvert kvarter i børstiden: Gap-and-go, Åpningsbrudd, VWAP-reclaim og Trenddag, hver med inngang, stop og mål. Hvert setup etterprøves etter stenging, og treffprosent og snitt per setup vises i fanen. Kursene er ca. 15 minutter forsinket.</p>
        </div>
        <div class="card"><h3>Begrensninger</h3>
          <p>Data fra Yahoo Finance er ca. 15 minutter forsinket, og analytikerdekningen på mindre nordiske selskaper er tynn. Reglene er ikke backtestet. Bruk listene som et utgangspunkt for egen vurdering – dette er ikke investeringsråd.</p>
        </div>
      </div>`, push, { info: true });
  }

  function closeSheet() {
    const sheet = $("#sheet");
    currentSubview = null;
    if (sheet.hidden) return;
    sheet.classList.remove("open");
    document.body.style.overflow = "";
    setTimeout(() => { if (!sheet.classList.contains("open")) sheet.hidden = true; }, 300);
  }
  window.addEventListener("popstate", e => {
    if (e.state && e.state.ticker) openStock(e.state.ticker, false);
    else if (e.state && e.state.info) openInfo(false);
    else if (e.state && e.state.search) openSearch(false);
    else if (e.state && e.state.trade) openTrade(e.state.trade, e.state.ticker, false);
    else if (e.state && e.state.backup) openBackup(false);
    else if (e.state && e.state.pushinfo) openPush(false);
    else if (e.state && e.state.sub) openSubview(e.state.sub, false);
    else { currentTicker = null; currentSubview = null; closeSheet(); }
  });

  // ---------- portefølje: «Mine aksjer» og «Lekepenger» (lagres lokalt på enheten) ----------
  const PF_KEY = "ar.portfolio.v1";
  const DEFAULT_CASH = 100000;
  const BASES = ["NOK", "SEK", "DKK", "EUR", "USD"];
  const today = () => new Date().toISOString().slice(0, 10);
  function pfDefault() {
    return { base: "NOK", mode: "real", real: { holdings: [] },
      paper: { cash: DEFAULT_CASH, startCash: DEFAULT_CASH, startDate: today(), holdings: [], trades: [], history: [] } };
  }
  function pfLoad() {
    let p = null;
    try { p = JSON.parse(localStorage.getItem(PF_KEY) || "null"); } catch (e) { /* ignorer */ }
    if (!p || !p.real || !p.paper) p = pfDefault();
    if (!BASES.includes(p.base)) p.base = "NOK";
    return p;
  }
  function pfSave() { try { localStorage.setItem(PF_KEY, JSON.stringify(pf)); } catch (e) { /* ignorer */ } }
  let pf = pfLoad();

  function fxToBase(cur) {
    const fx = (state.data && state.data.fx) || {};
    const toNok = c => (c === "NOK" ? 1 : fx[c]);
    const a = toNok(cur || "NOK"), b = toNok(pf.base);
    return (isNum(a) && isNum(b) && b) ? a / b : null;
  }
  const money = (v, cur) => (isNum(v) ? num(v, Math.abs(v) >= 1000 ? 0 : 2) + nbsp + (cur || pf.base) : "–");

  function enrich(holdings) {
    return holdings.map(h => {
      const s = byTicker(h.ticker);
      const cur = (s && s.currency) || h.currency || pf.base;
      const price = s ? s.price : h.lastPrice;
      const rate = fxToBase(cur);
      const value = isNum(price) && rate ? price * h.shares * rate : null;
      const cost = rate ? h.price * h.shares * rate : null;
      const gain = (isNum(value) && isNum(cost)) ? value - cost : null;
      const day = (s && isNum(s.change_1d) && isNum(value)) ? value - value / (1 + s.change_1d) : 0;
      return { ...h, s, cur, curPrice: price, rate, value, cost, gain, gainPct: (isNum(gain) && cost) ? gain / cost : null, day, missing: !s };
    });
  }
  const sum = (arr, k) => arr.reduce((a, x) => a + (isNum(x[k]) ? x[k] : 0), 0);

  function holdingRow(h, mode) {
    const base = h.s || { ticker: h.ticker, name: h.name || h.ticker, market: "", verdict: null, score: null };
    const info = `${num(h.shares, 0)} stk · ${money(h.value)} · <b class="${sign(h.gain)}">${isNum(h.gain) ? (h.gain >= 0 ? "+" : "") + money(h.gain) : "–"}</b> (${pct(h.gainPct)})`;
    const flags = [];
    if (h.missing) flags.push("ikke lenger i universet – viser kjøpskurs");
    if (h.s && (h.s.verdict === "Avvent" || h.s.verdict === "Unngå")) flags.push("anbefaling " + h.s.verdict);
    if (h.s && (h.s.death_cross || h.s.broke_below_slow)) flags.push("trendbrudd");
    if (h.s && isNum(h.s.rsi) && h.s.rsi > 78) flags.push("sterkt overkjøpt");
    return row(base, { info, sub: flags.length ? `<span class="warn">⚠ ${esc(flags.join(" · "))}</span>` : `Snittkurs ${num(h.price, 2)} ${esc(h.cur)} · nå ${num(h.curPrice, 2)}` });
  }

  function summaryCard(items) {
    return `<div class="summary">${items.map(([l, v, cls]) => `<div><span class="s-l">${esc(l)}</span><span class="s-v mono ${cls || ""}">${v}</span></div>`).join("")}</div>`;
  }

  function viewPortefolje() {
    const mode = pf.mode;
    const seg = `<div class="seg" style="margin-top:12px"><button data-pfmode="real" aria-pressed="${mode === "real"}">Mine aksjer</button><button data-pfmode="paper" aria-pressed="${mode === "paper"}">Lekepenger</button></div>`;
    const base = `<div class="pf-tools"><label>Vis i <select id="pf-base">${BASES.map(b => `<option ${b === pf.base ? "selected" : ""}>${b}</option>`).join("")}</select></label><button class="linkbtn" id="pf-backup">Sikkerhetskopi</button></div>`;
    return seg + (mode === "real" ? viewReal() : viewPaper()) + base +
      `<p class="note">Porteføljene lagres bare på denne enheten. Kurser er siste sluttkurs fra morgenens kjøring; valuta omregnes med dagens kurser. Ikke investeringsråd.</p>`;
  }

  function viewReal() {
    const hs = enrich(pf.real.holdings);
    if (!hs.length) {
      return `<div class="empty-card"><b>Ingen aksjer registrert ennå.</b><p>Legg inn aksjene du eier, så får du samlet verdi, avkastning og et varsel når en av dem får Avvent/Unngå eller viser trendbrudd.</p><button class="btn" data-trade="add">Legg til aksje</button></div>`;
    }
    const value = sum(hs, "value"), cost = sum(hs, "cost"), day = sum(hs, "day");
    const gain = value - cost;
    let html = summaryCard([
      ["Verdi", money(value)],
      ["I dag", (day >= 0 ? "+" : "") + money(day), sign(day)],
      ["Avkastning", (gain >= 0 ? "+" : "") + money(gain) + ` (${pct(cost ? gain / cost : null)})`, sign(gain)],
    ]);
    const flagged = hs.filter(h => h.s && (h.s.verdict === "Avvent" || h.s.verdict === "Unngå" || h.s.death_cross || h.s.broke_below_slow));
    if (flagged.length) html += `<div class="alert">⚠ <b>Følg med:</b> ${flagged.map(h => esc(h.ticker) + (h.s.verdict ? " (" + esc(h.s.verdict) + ")" : "")).join(", ")}</div>`;
    html += `<div class="section">${sectionHead("Beholdning", hs.length)}${list(hs.sort((a, b) => (b.value || 0) - (a.value || 0)).map(h => holdingRow(h, "real")).join(""))}</div>`;
    html += `<div class="btn-row"><button class="btn" data-trade="add">Legg til aksje</button></div>`;
    return html;
  }

  function viewPaper() {
    const p = pf.paper;
    const hs = enrich(p.holdings);
    const holdingsValue = sum(hs, "value"), day = sum(hs, "day");
    const total = p.cash + holdingsValue;
    const ret = total - p.startCash;
    // Én målepunkt per dag til avkastningskurven
    if (state.data && (!p.history.length || p.history[p.history.length - 1][0] !== today())) {
      p.history.push([today(), Math.round(total)]); pfSave();
    } else if (p.history.length) { p.history[p.history.length - 1][1] = Math.round(total); }
    let html = summaryCard([
      ["Total verdi", money(total)],
      ["Kontanter", money(p.cash)],
      ["Avkastning", (ret >= 0 ? "+" : "") + money(ret) + ` (${pct(p.startCash ? ret / p.startCash : null)})`, sign(ret)],
      ["I dag", (day >= 0 ? "+" : "") + money(day), sign(day)],
    ]);
    const curve = p.history.map(x => x[1]);
    html += `<div class="chart"><div class="legend" style="padding-top:0">Siden ${fmtDate(p.startDate)} · start ${money(p.startCash)}</div>${curve.length >= 2 ? sparkline(curve, 340, 70) : `<p class="muted" style="margin:6px 8px;font-size:13px">Avkastningskurven fylles dag for dag – åpne appen jevnlig.</p>`}</div>`;
    html += `<div class="section">${sectionHead("Beholdning", hs.length)}${hs.length ? list(hs.sort((a, b) => (b.value || 0) - (a.value || 0)).map(h => holdingRow(h, "paper")).join("")) : `<div class="empty">Ingen aksjer ennå. Du har ${money(p.cash)} å handle for – finn en aksje via søk eller Kjøp-fanen, og trykk «Kjøp for lekepenger».</div>`}</div>`;
    html += `<div class="btn-row"><button class="btn" data-trade="buy">Kjøp aksje</button><button class="btn secondary" id="pf-reset">Start på nytt</button></div>`;
    if (p.trades.length) {
      html += `<div class="section">${sectionHead("Handler", p.trades.length)}<div class="card" style="margin-top:0"><div class="lines">${p.trades.slice(-12).reverse().map(t =>
        `<div class="ln"><span class="d">${fmtDate(t.date)}</span><span class="t"><b>${t.kind === "buy" ? "Kjøp" : "Salg"}</b> ${esc(t.ticker)} · ${num(t.shares, 0)} stk à ${num(t.price, 2)} ${esc(t.currency)}</span><span class="v ${t.kind === "buy" ? "" : sign(t.pnl)}">${t.kind === "buy" ? money(t.valueBase) : (isNum(t.pnl) ? (t.pnl >= 0 ? "+" : "") + money(t.pnl) : "")}</span></div>`).join("")}</div></div></div>`;
    }
    return html;
  }

  // ---------- skjema: legg til / kjøp / selg / rediger ----------
  function openTrade(kind, ticker, push) {
    const s = ticker ? byTicker(ticker) : null;
    const isPaper = kind === "buy" || kind === "sell";
    const list_ = isPaper ? pf.paper.holdings : pf.real.holdings;
    const owned = ticker ? list_.find(h => h.ticker === ticker) : null;
    const titles = { add: "Legg til aksje", edit: "Rediger beholdning", buy: "Kjøp for lekepenger", sell: "Selg (lekepenger)" };
    const price = s ? s.price : (owned ? owned.price : "");
    const cur = s ? s.currency : (owned ? owned.currency : pf.base);
    const picker = s ? `<div class="picked"><span class="tick mono">${esc(s.ticker)}</span><span class="muted">${esc(s.name)} · ${num(s.price, 2)} ${esc(s.currency)}</span>${vbadge(s.verdict)}</div>`
      : `<label class="field"><span>Aksje</span><input id="f-q" type="search" placeholder="Søk ticker eller navn" autocomplete="off" autocapitalize="characters"><div id="f-hits" class="hits"></div></label>`;
    const cashInfo = kind === "buy" ? `<p class="muted" style="margin:0 0 8px">Kontanter: <b class="mono">${money(pf.paper.cash)}</b></p>` : "";
    const ownedInfo = kind === "sell" && owned ? `<p class="muted" style="margin:0 0 8px">Du eier <b class="mono">${num(owned.shares, 0)}</b> stk à ${num(owned.price, 2)} ${esc(owned.currency)}</p>` : "";
    showSheet(`
      ${sheetTop(esc(titles[kind]), isPaper ? "Handles til siste sluttkurs i appen" : "Det du faktisk eier")}
      <div class="gutter sheet-body">
        ${cashInfo}${ownedInfo}${picker}
        <div class="form" ${s ? "" : "hidden"} id="f-form">
          <label class="field"><span>Antall aksjer</span><input id="f-shares" type="number" inputmode="decimal" min="0" step="1" value="${kind === "sell" && owned ? owned.shares : (owned && kind === "edit" ? owned.shares : "")}"></label>
          <label class="field"><span>Kurs (${esc(cur || "")})</span><input id="f-price" type="number" inputmode="decimal" min="0" step="0.01" value="${kind === "edit" && owned ? owned.price : (isNum(price) ? price : "")}" ${isPaper ? "readonly" : ""}></label>
          ${isPaper ? "" : `<label class="field"><span>Dato</span><input id="f-date" type="date" value="${kind === "edit" && owned ? owned.date : today()}"></label>`}
          <p id="f-sum" class="muted" style="margin:0"></p>
          <p id="f-msg" class="neg" style="margin:0"></p>
          <div class="btn-row"><button class="btn" id="f-ok" data-kind="${kind}" data-tkr="${esc(ticker || "")}">${esc(titles[kind])}</button>${kind === "edit" ? `<button class="btn danger" id="f-remove" data-tkr="${esc(ticker)}">Fjern</button>` : ""}</div>
        </div>
      </div>`, push, { trade: kind, ticker: ticker || null });
    const upd = () => {
      const sh = parseFloat($("#f-shares").value), pr = parseFloat($("#f-price").value);
      const t = $("#f-ok").dataset.tkr, st = byTicker(t);
      const rate = fxToBase(st ? st.currency : cur) || 1;
      $("#f-sum").textContent = (sh > 0 && pr > 0) ? `Sum: ${money(sh * pr * rate)}` : "";
    };
    if (!s) {
      const q = $("#f-q");
      q.addEventListener("input", () => {
        const hits = searchStocks(q.value).slice(0, 8);
        $("#f-hits").innerHTML = hits.map(h => `<button class="hit" data-pick="${esc(h.ticker)}"><span class="tick mono">${esc(h.ticker)}</span><span class="muted">${esc(h.name)} · ${num(h.price, 2)} ${esc(h.currency)}</span></button>`).join("");
      });
      setTimeout(() => { try { q.focus(); } catch (e) { /* ignorer */ } }, 50);
    }
    $("#f-shares").addEventListener("input", upd);
    $("#f-price").addEventListener("input", upd);
    upd();
  }

  function pickStock(ticker) {
    const s = byTicker(ticker);
    if (!s) return;
    const ok = $("#f-ok");
    ok.dataset.tkr = ticker;
    $("#f-q").closest(".field").outerHTML = `<div class="picked"><span class="tick mono">${esc(s.ticker)}</span><span class="muted">${esc(s.name)} · ${num(s.price, 2)} ${esc(s.currency)}</span>${vbadge(s.verdict)}</div>`;
    const form = $("#f-form");
    form.hidden = false;
    $("#f-price").value = s.price;
    const lbl = $("#f-price").closest(".field").querySelector("span");
    if (lbl) lbl.textContent = `Kurs (${s.currency || ""})`;
    try { $("#f-shares").focus(); } catch (e) { /* ignorer */ }
  }

  function submitTrade(kind, ticker) {
    const msg = $("#f-msg");
    const s = byTicker(ticker);
    const shares = parseFloat($("#f-shares").value);
    const price = parseFloat($("#f-price").value);
    if (!ticker) { msg.textContent = "Velg en aksje først."; return; }
    if (!(shares > 0)) { msg.textContent = "Antall må være større enn 0."; return; }
    if (!(price > 0)) { msg.textContent = "Kursen må være større enn 0."; return; }
    const cur = s ? s.currency : pf.base;
    const rate = fxToBase(cur);
    if (!rate) { msg.textContent = "Mangler valutakurs for " + cur + " – prøv igjen etter neste oppdatering."; return; }
    const valueBase = shares * price * rate;
    if (kind === "add" || kind === "edit") {
      const date = $("#f-date").value || today();
      const list_ = pf.real.holdings;
      const ex = list_.find(h => h.ticker === ticker);
      if (ex && kind === "add") { // slå sammen til nytt snitt
        const tot = ex.shares + shares;
        ex.price = (ex.shares * ex.price + shares * price) / tot; ex.shares = tot; ex.date = date;
      } else if (ex) { ex.shares = shares; ex.price = price; ex.date = date; }
      else list_.push({ ticker, name: s ? s.name : ticker, currency: cur, shares, price, date, lastPrice: s ? s.price : price });
    } else if (kind === "buy") {
      if (valueBase > pf.paper.cash + 0.005) { msg.textContent = `Ikke nok kontanter: dette koster ${money(valueBase)}, du har ${money(pf.paper.cash)}.`; return; }
      pf.paper.cash -= valueBase;
      const ex = pf.paper.holdings.find(h => h.ticker === ticker);
      if (ex) { const tot = ex.shares + shares; ex.price = (ex.shares * ex.price + shares * price) / tot; ex.shares = tot; }
      else pf.paper.holdings.push({ ticker, name: s ? s.name : ticker, currency: cur, shares, price, date: today(), lastPrice: price });
      pf.paper.trades.push({ date: today(), kind: "buy", ticker, shares, price, currency: cur, valueBase });
    } else if (kind === "sell") {
      const ex = pf.paper.holdings.find(h => h.ticker === ticker);
      if (!ex) { msg.textContent = "Du eier ikke denne aksjen i lekeporteføljen."; return; }
      if (shares > ex.shares + 1e-9) { msg.textContent = `Du har bare ${num(ex.shares, 0)} stk.`; return; }
      const pnl = (price - ex.price) * shares * rate;
      pf.paper.cash += valueBase;
      ex.shares -= shares;
      if (ex.shares <= 1e-9) pf.paper.holdings = pf.paper.holdings.filter(h => h !== ex);
      pf.paper.trades.push({ date: today(), kind: "sell", ticker, shares, price, currency: cur, valueBase, pnl });
    }
    pf.mode = (kind === "buy" || kind === "sell") ? "paper" : "real";
    pfSave();
    state.tab = "portefolje";
    try { localStorage.setItem("ar.tab", state.tab); } catch (e) { /* ignorer */ }
    render();
    history.back();
  }

  function openPush(push) {
    const p = (state.data && state.data.push) || {};
    const topic = p.topic || "";
    const server = (p.server || "https://ntfy.sh").replace(/\/$/, "");
    showSheet(`
      ${sheetTop("Push-varsler", "Via ntfy – gratis og uten konto")}
      <div class="gutter sheet-body">
        ${p.enabled && topic ? `<div class="card"><h3>Slik slår du på varsler</h3>
          <ol class="reasons" style="margin:0;padding-left:20px">
            <li>Installer appen <b>ntfy</b> fra App Store (gratis, laget av ntfy.sh).</li>
            <li>Åpne ntfy, trykk <b>+</b> (Subscribe to topic) og lim inn emnet under.</li>
            <li>Tillat varsler når iPhonen spør. Ferdig – varslene åpner Aksjeradar når du trykker på dem.</li>
          </ol>
          <div class="picked" style="margin-top:12px"><span class="tick mono" id="push-topic">${esc(topic)}</span><button class="btn small" id="push-copy">Kopier</button></div>
          <p class="muted" style="font-size:13px">Server: ${esc(server)}. Emnet er en tilfeldig kode – del den ikke, så får ingen andre varslene dine.</p>
        </div>
        <div class="card"><h3>Dette varsles</h3><ul class="reasons" style="margin:0;padding-left:18px">
          <li><b>Hver morgen</b> ca. 08:40–09:00: dagens kjøpskandidater, antall per anbefaling, fond med gunstig inngang og autotraderens status.</li>
          <li><b>Fond</b>: når et fond skifter til eller fra gunstig inngang.</li>
          <li><b>Autotrader</b>: hver gang den kjøper eller selger.</li>
          <li><b>Intradag</b>: nye setups i børstiden, maks 6 per dag.</li>
        </ul><p class="muted" style="font-size:13px">Hva som sendes styres i config.yaml under <span class="mono">notify.push</span>.</p></div>`
        : `<div class="card"><h3>Push er ikke satt opp</h3><p>Slå på <span class="mono">notify.push</span> i config.yaml og legg inn et ntfy-emne, så vises oppskriften her.</p></div>`}
      </div>`, push, { pushinfo: true });
  }

  function openBackup(push) {
    showSheet(`
      ${sheetTop("Sikkerhetskopi", "Kopier ut – eller lim inn for å gjenopprette")}
      <div class="gutter sheet-body">
        <div class="card"><h3>Dine data</h3>
          <textarea id="bk-out" class="ta" readonly>${esc(JSON.stringify(pf))}</textarea>
          <div class="btn-row"><button class="btn" id="bk-copy">Kopier</button></div>
          <p class="muted" style="font-size:13px">Lim teksten inn i Notater eller en e-post til deg selv. Da kan du flytte porteføljene til en annen telefon.</p>
        </div>
        <div class="card"><h3>Gjenopprett</h3>
          <textarea id="bk-in" class="ta" placeholder="Lim inn en sikkerhetskopi her"></textarea>
          <p id="bk-msg" class="neg" style="margin:0"></p>
          <div class="btn-row"><button class="btn secondary" id="bk-restore">Gjenopprett</button></div>
        </div>
      </div>`, push, { backup: true });
  }

  function stockPortfolioCard(s) {
    const real = pf.real.holdings.find(h => h.ticker === s.ticker);
    const paper = pf.paper.holdings.find(h => h.ticker === s.ticker);
    const rate = fxToBase(s.currency);
    const line = (h, label) => {
      const v = rate && isNum(s.price) ? h.shares * s.price * rate : null;
      const g = rate ? v - h.shares * h.price * rate : null;
      return `<p style="margin:0 0 6px">${label}: <b class="mono">${num(h.shares, 0)} stk</b> · ${money(v)} · <span class="mono ${sign(g)}">${isNum(g) ? (g >= 0 ? "+" : "") + money(g) : "–"}</span></p>`;
    };
    return `<div class="card"><h3>Portefølje</h3>
      ${real ? line(real, "Mine aksjer") : ""}${paper ? line(paper, "Lekepenger") : ""}
      <div class="btn-row wrap">
        <button class="btn secondary small" data-trade="${real ? "edit" : "add"}" data-tkr="${esc(s.ticker)}">${real ? "Rediger i mine aksjer" : "Legg til i mine aksjer"}</button>
        <button class="btn small" data-trade="buy" data-tkr="${esc(s.ticker)}">Kjøp for lekepenger</button>
        ${paper ? `<button class="btn danger small" data-trade="sell" data-tkr="${esc(s.ticker)}">Selg</button>` : ""}
      </div></div>`;
  }

  // ---------- autotrader (kjører på serveren hver handelsdag – appen viser resultatet) ----------
  let auto = null, autoLoading = false, autoError = null;
  async function loadAuto(force) {
    autoLoading = true; autoError = null;
    try {
      const r = await fetch("autotrader.json" + (force ? "?t=" + Date.now() : ""), { cache: force ? "reload" : "default" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      auto = await r.json();
    } catch (e) { autoError = e; }
    autoLoading = false;
    if (state.tab === "auto") render();
  }

  function lineChart(series, dates) {
    // series: [{values, color, width, dash}] – samme skala for alle
    const W = 360, H = 170, padL = 6, padR = 52, padT = 10, padB = 22;
    const all = series.flatMap(s => s.values).filter(isNum);
    if (all.length < 2) return "";
    const n = Math.max.apply(null, series.map(s => s.values.length));
    const lo = Math.min.apply(null, all), hi = Math.max.apply(null, all), span = hi - lo || 1;
    const x = i => padL + (n === 1 ? 0 : (i / (n - 1)) * (W - padL - padR));
    const y = v => padT + (1 - (v - lo) / span) * (H - padT - padB);
    const path = arr => arr.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join("");
    const grid = [lo, lo + span / 2, hi].map(v => `<line x1="${padL}" x2="${W - padR}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="var(--line)"/>
      <text x="${W - padR + 6}" y="${(y(v) + 4).toFixed(1)}" font-size="10" fill="var(--muted)">${num(v / 1000, 1)}k</text>`).join("");
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Verdiutvikling">${grid}
      ${series.map(s => `<path d="${path(s.values)}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} stroke-linejoin="round" stroke-linecap="round"/>`).join("")}
      <text x="${padL}" y="${H - 6}" font-size="10" fill="var(--muted)">${fmtDate(dates[0])}</text>
      <text x="${W - padR}" y="${H - 6}" font-size="10" fill="var(--muted)" text-anchor="end">${fmtDate(dates[dates.length - 1])}</text></svg>`;
  }

  function viewAuto() {
    if (!auto && !autoError) { if (!autoLoading) loadAuto(false); return `<div class="skeleton"><span></span><span></span></div>`; }
    if (!auto) return `<div class="empty-card" style="margin-top:16px"><b>Autotraderen har ikke kjørt ennå.</b><p>Den starter ved neste daglige analyse og vises her etterpå.</p></div>`;
    const a = auto, base = a.base || "NOK";
    const m = (v, d) => (isNum(v) ? num(v, d == null ? 0 : d) + nbsp + base : "–");
    const ret = isNum(a.total) ? a.total - a.start_cash : null;
    const diff = (isNum(a.return_pct) && isNum(a.bench_return_pct)) ? a.return_pct - a.bench_return_pct : null;
    let html = summaryCard([
      ["Total verdi", m(a.total)],
      ["Avkastning", `${isNum(ret) ? (ret >= 0 ? "+" : "") + m(ret) : "–"} (${pct(a.return_pct)})`, sign(ret)],
      ["Markedet (likevektet univers)", pct(a.bench_return_pct), sign(a.bench_return_pct)],
      ["Mot markedet", pct(diff), sign(diff)],
    ]);
    html += `<p class="hint" style="margin-top:8px">Startet ${fmtDate(a.start_date)} med ${m(a.start_cash)} · sist handlet på sluttkurs ${fmtDate(a.price_date)} · kontanter ${m(a.cash)} · ${a.stats.days_running} dager</p>`;
    const hist = a.history || [];
    html += `<div class="chart">${hist.length >= 2
      ? lineChart([{ values: hist.map(h => h.bench), color: "var(--muted)", width: 1.4, dash: "4 3" }, { values: hist.map(h => h.total), color: "var(--accent)", width: 2.2 }], hist.map(h => h.date))
      : `<p class="muted" style="margin:6px 8px;font-size:13px">Kurven fylles dag for dag – første punkt er satt.</p>`}
      <div class="legend"><span><i style="background:var(--accent)"></i>Autotrader</span><span><i style="background:var(--muted)"></i>Markedet (likevektet)</span></div></div>`;

    const hs = a.holdings || [];
    html += `<div class="section">${sectionHead("Beholdning", hs.length)}${hs.length ? list(hs.map(h => {
      const idx = byTicker(h.ticker) || { ticker: h.ticker, name: h.name, market: h.market, verdict: h.verdict, score: h.score };
      const info = `${num(h.shares, 0)} stk · ${m(h.value_base)} · <b class="${sign(h.pnl)}">${isNum(h.pnl) ? (h.pnl >= 0 ? "+" : "") + m(h.pnl) : "–"}</b> (${pct(h.pnl_pct)})`;
      return row(idx, { info, sub: `Kjøpt ${fmtDate(h.bought)} med score ${num(h.buy_score, 0)} · ${h.days} dager · nå ${esc(h.verdict || "–")}` });
    }).join("")) : `<div class="empty">Ingen posisjoner akkurat nå – venter på kjøpskandidater som oppfyller kravene.</div>`}</div>`;

    const st = a.stats || {};
    html += `<div class="card"><h3>Statistikk</h3><dl class="kv" style="margin:0">
      <div><dt>Handler</dt><dd>${st.n_trades || 0}</dd></div><div><dt>Avsluttede</dt><dd>${st.n_closed || 0}</dd></div>
      <div><dt>Treffprosent</dt><dd>${pct(st.win_rate, false, 0)}</dd></div><div><dt>Snitt per avsluttet</dt><dd class="${sign(st.avg_pnl_pct)}">${pct(st.avg_pnl_pct)}</dd></div>
      <div><dt>Realisert</dt><dd class="${sign(st.realized_pnl)}">${isNum(st.realized_pnl) ? (st.realized_pnl >= 0 ? "+" : "") + m(st.realized_pnl) : "–"}</dd></div><div><dt>Største fall fra topp</dt><dd>${pct(st.max_drawdown_pct, false)}</dd></div>
      ${st.best ? `<div><dt>Beste handel</dt><dd class="pos">${esc(st.best.ticker)} ${pct(st.best.pnl_pct)}</dd></div>` : ""}${st.worst ? `<div><dt>Svakeste handel</dt><dd class="neg">${esc(st.worst.ticker)} ${pct(st.worst.pnl_pct)}</dd></div>` : ""}
    </dl></div>`;

    const tr = a.trades || [];
    if (tr.length) {
      html += `<div class="section">${sectionHead("Handler", tr.length)}<div class="card" style="margin-top:0"><div class="lines">${tr.slice(0, 30).map(t =>
        `<div class="ln"><span class="d">${fmtDate(t.date)}</span><span class="t"><b>${t.kind === "buy" ? "Kjøp" : "Salg"}</b> <span class="mono">${esc(t.ticker)}</span> · ${num(t.shares, 0)} stk à ${num(t.price, 2)} ${esc(t.currency || "")}<br><span class="muted" style="font-size:12px">${esc(t.reason || "")}${t.kind === "sell" && isNum(t.held_days) ? ` · ${t.held_days} dager` : ""}</span></span><span class="v ${t.kind === "buy" ? "" : sign(t.pnl)}">${t.kind === "buy" ? m(t.value_base) : (isNum(t.pnl) ? (t.pnl >= 0 ? "+" : "") + m(t.pnl) : "")}</span></div>`).join("")}</div></div></div>`;
    }
    const r = a.rules || {};
    html += `<div class="card"><h3>Reglene</h3><ul class="reasons" style="margin:0;padding-left:18px">
      <li><b>Kjøper</b> dagens kjøpskandidater (Sterkt kjøp/Kjøp) med score ≥ ${r.min_score} og minst delvis datagrunnlag, best score først, like store posisjoner (verdi delt på ${r.max_positions})${r.max_per_market ? `, maks ${r.max_per_market} per børs` : ""}.</li>
      <li><b>Selger</b> når anbefalingen faller til Avvent/Unngå eller ved trendbrudd (tidligst etter ${r.min_hold_days} dager), og alltid ved ${pct(r.stop_loss_pct, false, 0)} stop-loss.</li>
      <li>Kurtasje ${pct(r.commission_pct, false, 2)} per handel og ${pct(r.slippage_pct, false, 1)} slippage i disfavør. Solgte aksjer kjøpes ikke igjen før etter ${r.cooldown_days} dager.</li>
      <li>Handler til sluttkursen i morgenens data – i praksis gårsdagens sluttkurs. Markedet = likevektet gjennomsnitt av hele universet.</li>
    </ul></div>
    <p class="note">Autotraderen kjører på serveren hver ukedag kl. 08:40 og handler bare med lekepenger. Den er en ærlig test av reglene, ikke investeringsråd. Reglene justeres i <span class="mono">config.yaml</span>.</p>`;
    return html;
  }

  // ---------- intradag (oppdateres hvert 15. min på serveren i børstiden) ----------
  let intra = null, intraLoading = false, intraError = null, intraTimer = null;
  const TYPE_CLASS = { gap: "t-gap", orb: "t-orb", vwap: "t-vwap", trend: "t-trend" };
  async function loadIntra(force) {
    if (intraLoading) return;
    intraLoading = true; intraError = null;
    try {
      const r = await fetch("intraday.json" + (force ? "?t=" + Date.now() : ""), { cache: force ? "reload" : "default" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      intra = await r.json();
    } catch (e) { intraError = e; }
    intraLoading = false;
    if (state.tab === "intradag") render();
  }
  function fmtClock(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    return isNaN(d) ? "–" : d.toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit" });
  }
  function ageMinutes(iso) {
    const d = new Date(iso);
    return isNaN(d) ? null : Math.round((Date.now() - d.getTime()) / 60000);
  }
  function setupCard(s) {
    const idx = byTicker(s.ticker);
    const exp = s.expires ? fmtClock(s.expires) : "stenging";
    const why = (s.why || []).map(w => `<span class="chip on">${esc(w)}</span>`).join("");
    return `<button class="setup ${TYPE_CLASS[s.type] || ""}" data-ticker="${esc(s.ticker)}" ${idx ? "" : 'data-nodetail="1"'}>
      <span class="su-top"><span class="tb">${esc(s.type_label)}</span><span class="su-mkt">${esc(s.market)}</span><span class="pill ${scClass(s.score)}">${s.score}</span></span>
      <span class="su-name"><span class="tick mono">${esc(s.ticker)}</span><span class="name">${esc(s.name || "")}</span>
        <span class="mono ${sign(s.change_pct)}" style="margin-left:auto;font-size:13px">${pct(s.change_pct)} i dag</span></span>
      <span class="levels">
        <span><i>Inngang</i><b class="mono">${num(s.entry, 2)}</b></span>
        <span><i>Stop</i><b class="mono neg">${num(s.stop, 2)}</b><small class="mono">${pct(s.stop_pct)}</small></span>
        <span><i>Mål</i><b class="mono pos">${num(s.target, 2)}</b><small class="mono">${pct(s.target_pct)}</small></span>
        <span><i>R:R</i><b class="mono">${num(s.rr, 1)}</b></span>
      </span>
      <span class="chips" style="margin-top:8px">${why}</span>
      <span class="su-meta">Sett ${fmtClock(s.first_seen || s.seen_at)} · gyldig til ${exp} · siste bar ${esc(s.last_bar || "")}${s.vwap ? ` · VWAP ${num(s.vwap, 2)}` : ""}</span>
    </button>`;
  }
  function viewIntradag() {
    if (!intra && !intraError) { if (!intraLoading) loadIntra(false); return `<div class="skeleton"><span></span><span></span></div>`; }
    if (!intra) return `<div class="empty-card" style="margin-top:16px"><b>Intradag-modulet har ikke kjørt ennå.</b><p>Det starter neste ukedag når Oslo Børs åpner (kl. 09:00) og oppdaterer seg hvert kvarter til USA stenger.</p></div>`;
    const a = intra;
    const age = ageMinutes(a.generated_at);
    const mk = a.markets || {};
    const openMarkets = Object.values(mk).filter(m => m.open);
    let html = `<p class="hint" style="margin-top:12px">Oppdatert ${fmtClock(a.generated_at)}${isNum(age) ? ` (${age} min siden)` : ""} · kurser ca. ${a.data_delay_min || 15} min forsinket · ${a.universe} aksjer · ${a.interval || "15m"}-barer</p>`;
    html += `<div class="mkts">${["Oslo", "Stockholm", "København", "Helsinki", "USA"].map(m => mk[m] ? `<span class="mkt ${mk[m].open ? "on" : ""}">${esc(m)}: ${mk[m].open ? `åpen til ${esc(mk[m].closes_at)}` : `stengt (${esc(mk[m].opens_at)}–${esc(mk[m].closes_at)})`}</span>` : "").join("")}</div>`;
    if (a.demo) html += `<div class="banner demo" style="margin-top:10px"><span><b>Demo-data.</b> Setupene er laget av tilfeldige kurser.</span></div>`;

    const setups = (a.setups || []).filter(s => inMarket({ market: s.market }));
    html += `<div class="section">${sectionHead("Aktive setups", setups.length)}`;
    if (!openMarkets.length) {
      html += `<div class="empty-card"><b>Børsene er stengt.</b><p>Nye setups kommer når Oslo åpner kl. 09:00. Under ser du hvordan de siste setupene gikk.</p></div>`;
    } else if (!setups.length) {
      html += `<div class="empty">Ingen setups oppfyller reglene akkurat nå. Det er normalt – de fleste kvarter er stille.</div>`;
    } else {
      html += setups.map(setupCard).join("");
    }
    html += `</div>`;

    const mv = (a.movers || []).filter(m => inMarket(m));
    if (mv.length) {
      html += `<div class="section">${sectionHead("Dagens bevegelser", mv.length)}<div class="list">${mv.slice(0, 12).map(m => {
        const idx = byTicker(m.ticker);
        return `<button class="row" data-ticker="${esc(m.ticker)}" ${idx ? "" : 'data-nodetail="1"'}>
          <span class="l"><span class="l1"><span class="tick">${esc(m.ticker)}</span><span class="name">${esc(m.name || "")}</span></span>
          <span class="l2"><span class="info mono">volum ${isNum(m.rel_volume) ? num(m.rel_volume, 1) + "×" : "–"} · ${isNum(m.vs_vwap_pct) ? pct(m.vs_vwap_pct) + " mot VWAP" : ""}${isNum(m.gap_pct) ? ` · gap ${pct(m.gap_pct)}` : ""}</span></span></span>
          <span class="mid"></span><span class="r"><span class="metric mono ${sign(m.change_pct)}" style="min-width:64px;text-align:right">${pct(m.change_pct)}</span></span></button>`;
      }).join("")}</div></div>`;
    }

    const st = (a.stats || {}).all || { n: 0 };
    const bt = (a.stats || {}).by_type || {};
    html += `<div class="card"><h3>Etterprøving</h3>
      ${st.n ? `<dl class="kv" style="margin:0">
        <div><dt>Setups evaluert</dt><dd>${st.n}</dd></div><div><dt>Venter på stenging</dt><dd>${(a.stats || {}).pending || 0}</dd></div>
        <div><dt>Traff målet</dt><dd class="pos">${pct(st.hit_rate, false, 0)}</dd></div><div><dt>Traff stoppen</dt><dd class="neg">${pct(st.stop_rate, false, 0)}</dd></div>
        <div><dt>Positive (inkl. stenging)</dt><dd>${pct(st.win_rate, false, 0)}</dd></div><div><dt>Snitt per setup</dt><dd class="${sign(st.avg_r)}">${isNum(st.avg_r) ? (st.avg_r >= 0 ? "+" : "") + num(st.avg_r, 2) + " R" : "–"}</dd></div>
        <div><dt>Sum</dt><dd class="${sign(st.sum_r)}">${isNum(st.sum_r) ? (st.sum_r >= 0 ? "+" : "") + num(st.sum_r, 1) + " R" : "–"}</dd></div>
      </dl>
      <div class="lines" style="margin-top:12px">${Object.entries(bt).filter(([, v]) => v.n).map(([k, v]) => `<div class="ln"><span class="t"><span class="tb ${TYPE_CLASS[k]}" style="display:inline-block">${esc(({ gap: "Gap-and-go", orb: "Åpningsbrudd", vwap: "VWAP-reclaim", trend: "Trenddag" })[k])}</span></span><span class="v">${v.n} stk · mål ${pct(v.hit_rate, false, 0)} · snitt ${isNum(v.avg_r) ? (v.avg_r >= 0 ? "+" : "") + num(v.avg_r, 2) : "–"} R</span></div>`).join("")}</div>`
      : `<p class="muted" style="margin:0">Ingen setups er evaluert ennå. Hvert setup sjekkes etter stenging: traff det målet (+${num((a.rules || {}).target_r || 2, 1)} R), stoppen (−1 R), eller endte det ved stenging? Etter noen uker ser du her om reglene har noe for seg.</p>`}
    </div>`;
    const rec = a.recent || [];
    if (rec.length) {
      html += `<div class="section">${sectionHead("Siste utfall", rec.length)}<div class="card" style="margin-top:0"><div class="lines">${rec.slice(0, 20).map(r =>
        `<div class="ln"><span class="d">${fmtDate(r.session)}</span><span class="t"><span class="mono">${esc(r.ticker)}</span> · ${esc(r.type_label || r.type)}<br><span class="muted" style="font-size:12px">inngang ${num(r.entry, 2)} · ${esc(r.outcome)}</span></span><span class="v ${sign(r.r)}">${isNum(r.r) ? (r.r >= 0 ? "+" : "") + num(r.r, 1) + " R" : "–"}</span></div>`).join("")}</div></div></div>`;
    }
    const ru = a.rules || {};
    html += `<div class="card"><h3>Slik lages setupene</h3><ul class="reasons" style="margin:0;padding-left:18px">
      <li><b>Gap-and-go</b> – gap opp ≥ ${pct(ru.min_gap_pct, false, 0)}, holder gevinsten, over VWAP, volum ≥ 1,5× normalt.</li>
      <li><b>Åpningsbrudd</b> – brudd over høyeste i de første 30 minuttene, over VWAP, volum ≥ ${num(ru.min_rel_volume, 1)}×, i første del av dagen.</li>
      <li><b>VWAP-reclaim</b> – kursen krysser opp gjennom VWAP med volum, 15m-RSI 45–70.</li>
      <li><b>Trenddag</b> – over VWAP hele dagen, ny dagshøyde, volum ≥ ${num(ru.min_rel_volume, 1)}×, opp ≥ 1,5 %.</li>
      <li>Stop legges under VWAP/åpningsintervallet (${pct(ru.min_stop_pct, false, 1)}–${pct(ru.max_stop_pct, false, 0)} unna), mål = ${num(ru.target_r, 1)}× risikoen. Bare long. Gyldig til børsen stenger.</li>
    </ul></div>
    <p class="note">Kursene er ca. 15 minutter forsinket og oppdateres hvert kvarter – dette er ikke sanntid, og det er ikke investeringsråd. Daytrading er der flest småsparere taper penger; bruk setupene som struktur og etterprøvingen som dommer, på lekepenger, lenge før ekte penger.</p>`;
    return html;
  }
  function scheduleIntraRefresh() {
    if (intraTimer) clearInterval(intraTimer);
    intraTimer = setInterval(() => {
      if (state.tab === "intradag" && document.visibilityState === "visible") loadIntra(true);
    }, 5 * 60 * 1000);
  }

  // ---------- fond: gunstige innganger (proxy-ETF × valuta) ----------
  const LEVEL_CLASS = { "Svært gunstig": "v-strong", "Gunstig": "v-buy", "Nøytral": "v-hold", "Dyr": "v-wait" };
  const fundsData = () => (state.data && state.data.funds && state.data.funds.funds) || [];
  const goodFunds = () => fundsData().filter(f => f.level === "Gunstig" || f.level === "Svært gunstig");

  function fundChart(h) {
    // to linjer, hver indeksert til 100 ved start: fondet i NOK og indeksen i egen valuta
    if (!h || !h.nok || h.nok.length < 5) return "";
    const n0 = h.nok[0], i0 = h.idx[0];
    const nok = h.nok.map(v => v / n0 * 100), idx = h.idx.map(v => v / i0 * 100);
    return lineChart([{ values: idx, color: "var(--muted)", width: 1.3, dash: "4 3" }, { values: nok, color: "var(--accent)", width: 2.2 }], h.dates);
  }
  function fundCard(f, compact) {
    const fxLine = f.fx_relevant && isNum(f.fx_vs_sma200)
      ? `<span><i>Krone mot ${esc(f.currency)}</i><b class="mono ${f.fx_vs_sma200 < 0 ? "pos" : "neg"}">${pct(-f.fx_vs_sma200)}</b><small>${f.fx_vs_sma200 < 0 ? "sterkere enn snitt" : "svakere enn snitt"}</small></span>`
      : `<span><i>Valuta</i><b class="mono">–</b><small>${f.hedged ? "valutasikret" : "ikke relevant"}</small></span>`;
    const AV = { "Attraktiv": "v-strong", "Nøytral": "v-hold", "Lite attraktiv": "v-wait" };
    const parts = f.attr_parts || {};
    const partRow = (l, v) => `<span class="lbl">${l}</span><span class="bar"><i style="width:${isNum(v) ? Math.max(2, v) : 0}%;${isNum(v) ? "" : "opacity:.3"}"></i></span><span class="val">${isNum(v) ? sc(v) : "–"}</span>`;
    return `<div class="fund ${AV[f.attr_verdict] || LEVEL_CLASS[f.level] || ""}" data-fund="${esc(f.id)}">
      <div class="su-top"><span class="rank-no mono">#${f.rank || "–"}</span>${f.attr_verdict ? `<span class="vb ${AV[f.attr_verdict]}">${esc(f.attr_verdict)}</span>` : ""}${vbadge(f.level)}${f.owned ? `<span class="vb own">Ditt</span>` : ""}<span class="su-mkt mono" style="margin-left:auto;margin-right:0">${esc(f.proxy)}${f.hedged ? " · sikret" : ""}</span><span class="pill ${scClass(f.attr_score)}" title="Attraktivitet">${sc(f.attr_score)}</span></div>
      <div class="fund-name">${esc(f.name)}</div>
      ${f.advice ? `<div class="advice">→ ${esc(f.advice)}</div>` : ""}
      ${f.examples ? `<div class="fund-ex">${esc(f.examples)}</div>` : ""}
      <div class="levels">
        <span><i>Fra 52u-topp</i><b class="mono ${sign(f.dd_52w)}">${pct(f.dd_52w)}</b><small>i NOK</small></span>
        <span><i>Mot 200d</i><b class="mono ${sign(f.vs_sma200)}">${pct(f.vs_sma200)}</b><small>snitt</small></span>
        <span><i>1 mnd</i><b class="mono ${sign(f.ret_1m)}">${pct(f.ret_1m)}</b><small>indeks ${pct(f.idx_ret_1m)}</small></span>
        ${fxLine}
      </div>
      ${compact ? "" : `<div class="scores fund-scores">${partRow("Inngang (20 %)", parts.entry)}${partRow("Trend (35 %)", parts.trend)}${partRow("Sektor/marked (30 %)", parts.market)}${partRow("Risiko/prising (15 %)", parts.risk)}</div>
      ${(f.attr_why || []).length ? `<ul class="vd-why" style="margin-top:8px">${f.attr_why.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
      <div class="chart" style="margin-top:10px">${fundChart(f.history)}<div class="legend"><span><i style="background:var(--accent)"></i>Fondet i NOK</span><span><i style="background:var(--muted)"></i>Indeksen i ${esc(f.currency)}</span><span>begge = 100 ved start</span></div></div>
      <ul class="vd-why" style="margin-top:10px">${(f.why || []).map(w => `<li>${esc(w)}</li>`).join("")}</ul>
      <div class="su-meta">Sist ${fmtDate(f.last_date)} · 1 år ${pct(f.ret_1y)} i NOK (indeks ${pct(f.idx_ret_1y)}) · RSI ${num(f.rsi, 0)}${f.prev_level && f.prev_level !== f.level ? ` · var ${esc(f.prev_level)} i går` : ""}</div>`}
    </div>`;
  }
  function viewFond() {
    const fs = fundsData();
    if (!fs.length) return `<div class="empty-card" style="margin-top:16px"><b>Ingen fond er satt opp.</b><p>Fond kobles til en indeks-ETF i config.yaml under <span class="mono">funds.list</span>.</p></div>`;
    const alerts = (state.data.funds.alerts || []);
    let html = `<p class="hint" style="margin-top:12px">Hvert fond følges via en ETF som speiler samme indeks, omregnet til NOK med dagens valutakurs. Nivået sier om fondet er «på salg» målt mot egen historikk – ikke om fallet er over.</p>`;
    if (alerts.length) html += `<div class="alert">💱 <b>Nytt siden sist:</b> ${alerts.map(a => esc(a.text)).join(" · ")}</div>`;
    const owned = fs.filter(f => f.owned);
    if (owned.length) {
      html += `<div class="section">${sectionHead("Dine fond", owned.length)}<div class="list">${owned.map(f => `<div class="row" style="cursor:default"><span class="l"><span class="l1"><span class="rank-no mono">#${f.rank}</span><span class="tick" style="font-family:var(--font-ui);font-size:13.5px">${esc(f.name)}</span></span><span class="l2"><span class="info" style="font-family:var(--font-ui)">${esc(f.advice || "")}</span></span></span><span class="mid"></span><span class="r"><span class="vb ${({ "Attraktiv": "v-strong", "Nøytral": "v-hold", "Lite attraktiv": "v-wait" })[f.attr_verdict] || ""}">${esc(f.attr_verdict || "")}</span></span></div>`).join("")}</div></div>`;
    }
    const sorted = fs.slice().sort((a, b) => (a.rank || 99) - (b.rank || 99));
    html += `<div class="section">${sectionHead("Rangering etter attraktivitet", sorted.length)}<p class="hint">Hvor attraktivt det er å sette nye penger i fondet nå – relativt til de andre fondene i listen. Trykk på et kort for detaljer.</p>${sorted.map(f => fundCard(f, false)).join("")}</div>`;
    const th = state.data.funds.thresholds || {};
    html += `<div class="card"><h3>Slik vurderes fondene</h3><ul class="reasons" style="margin:0;padding-left:18px">
      <li><b>Attraktivitet</b> (0–100) veier fire deler: <b>Inngang</b> 20 % (hvor «på salg» fondet er i NOK, som bonus), <b>Trend</b> 35 % (over 200-dagers snitt, 50-dagers over 200, positive 3 mnd, 1 år mot globalt indeksfond), <b>Sektor/marked</b> 30 % (andel aksjer i opptrend, snittscore og andel kjøpsanbefalinger i aksjeuniverset for den sektoren/børsen) og <b>Risiko/prising</b> 15 % (årlige svingninger og forventet P/E mot hele universet). ≥ 60 = Attraktiv, ≥ 45 = Nøytral.</li>
      <li><b>Råd for dine fond</b> kombinerer attraktivitet og inngang: «øk innskuddet», «fortsett spareavtalen», «behold» eller «pause nye innskudd». Rådene gjelder <i>nye</i> penger – de sier aldri «selg», fordi fondssparing er langsiktig og salg utløser skatt.</li>
      <li><b>Inngangsscore</b> (0–100): fall fra 52-ukers topp i NOK (20 % = fullt utslag), avstand under 200-dagers snitt, RSI, og hvor sterk kronen er mot sitt 200-dagers snitt i fondets valuta (sterk krone = billigere inngang).</li>
      <li><b>Gunstig</b> = score ≥ 45 eller fall ≥ ${pct(-(th.good_drawdown || -0.08), false, 0)} fra topp. <b>Svært gunstig</b> = score ≥ 70 eller fall ≥ ${pct(-(th.strong_drawdown || -0.15), false, 0)}. <b>Dyr</b> = nær topp, langt over 200d-snitt og svak krone.</li>
      <li>Varsel sendes (Telegram, hvis satt opp) når et fond skifter til eller fra gunstig inngang.</li>
      <li>Valutasikrede fond vurderes uten valutaeffekt. Norske fond: valutaen nøytraliseres når ETF-en regnes om til NOK.</li>
    </ul></div>
    <p class="note">Rangeringen er en mekanisk sammenligning – den vet ikke hva som skjer i morgen. En sunn fondsportefølje har et bredt globalt indeksfond som kjerne og sektor-/regionsfond som mindre satellitter uansett hva rangeringen sier denne uken. Et fall kan fortsette. Dette er en mekanisk «på salg»-måling for langsiktig sparing (f.eks. ekstra innskudd ved fall), ikke en spådom – og ikke investeringsråd. ETF-ene avviker litt fra fondene (honorar, én dags forsinkelse i andelskurs).</p>`;
    return html;
  }

  // ---------- guruer: kjente investorers porteføljer (SEC 13F) ----------
  let gurus = null, gurusLoading = false, gurusError = null;
  const guruState = { open: {}, view: "konsensus" };
  async function loadGurus(force) {
    if (gurusLoading) return;
    gurusLoading = true; gurusError = null;
    try {
      const r = await fetch("gurus.json" + (force ? "?t=" + Date.now() : ""), { cache: force ? "reload" : "default" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      gurus = await r.json();
    } catch (e) { gurusError = e; }
    gurusLoading = false;
    if (state.tab === "guruer") render();
  }
  const MOVE_CLASS = { "ny": "v-strong", "økt": "v-buy", "redusert": "v-wait", "solgt": "v-avoid" };
  const MOVE_LABEL = { "ny": "Ny", "økt": "Økt", "redusert": "Redusert", "solgt": "Solgt" };
  const bigMoney = v => (!isNum(v) ? "–" : v >= 1e9 ? num(v / 1e9, 1) + " mrd $" : v >= 1e6 ? num(v / 1e6, 0) + " mill $" : num(v, 0) + " $");

  function holdingRowG(h, extra) {
    const idx = h.ticker ? byTicker(h.ticker) : null;
    const attrs = idx ? `data-ticker="${esc(h.ticker)}"` : `data-nodetail="1"`;
    return `<button class="row" ${attrs}>
      <span class="l"><span class="l1">${h.ticker ? `<span class="tick">${esc(h.ticker)}</span>` : ""}<span class="name">${esc(h.name)}</span></span>
      <span class="l2">${h.verdict ? vbadge(h.verdict) : ""}<span class="info" style="font-family:var(--font-ui)">${extra}</span></span></span>
      <span class="mid"></span><span class="r">${isNum(h.weight) && h.weight > 0 ? `<span class="pill mid">${pct(h.weight, false, 1)}</span>` : (idx ? `<span class="pill ${scClass(idx.score)}">${sc(idx.score)}</span>` : "")}</span>
    </button>`;
  }
  function investorCard(inv) {
    const open_ = !!guruState.open[inv.id];
    const nm = inv.n_moves || {};
    const movesHtml = (inv.moves || []).length ? `<div class="list" style="margin-top:8px">${inv.moves.slice(0, 20).map(m =>
      `<button class="row" ${m.ticker && byTicker(m.ticker) ? `data-ticker="${esc(m.ticker)}"` : 'data-nodetail="1"'}>
        <span class="l"><span class="l1"><span class="vb ${MOVE_CLASS[m.move]}">${MOVE_LABEL[m.move]}</span>${m.ticker ? `<span class="tick">${esc(m.ticker)}</span>` : ""}<span class="name">${esc(m.name)}</span></span>
        <span class="l2">${m.verdict ? vbadge(m.verdict) : ""}<span class="info" style="font-family:var(--font-ui)">${m.move === "ny" ? `ny posisjon · ${pct(m.weight, false, 1)} av porteføljen` : m.move === "solgt" ? "hele posisjonen solgt" : `${pct(m.change_shares)} antall aksjer · nå ${pct(m.weight, false, 1)}`}</span></span></span>
        <span class="mid"></span><span class="r"><span class="metric mono ${m.move === "ny" || m.move === "økt" ? "pos" : "neg"}" style="min-width:40px;text-align:right">${m.move === "ny" ? "+" : m.move === "solgt" ? "−" : (m.change_shares >= 0 ? "▲" : "▼")}</span></span>
      </button>`).join("")}</div>` : `<div class="empty">Ingen bevegelser siden forrige kvartal.</div>`;
    return `<div class="guru">
      <button class="guru-head" data-guru="${esc(inv.id)}" aria-expanded="${open_}">
        <span class="g-name">${esc(inv.name)}<small>${esc(inv.firm)}</small></span>
        <span class="g-meta mono">${bigMoney(inv.total_value)}<small>${inv.n_positions} posisjoner · per ${fmtDate(inv.report_date)}</small></span>
        <span class="chev">${open_ ? "▾" : "▸"}</span>
      </button>
      <div class="g-tags"><span class="chip">${esc(inv.style)}</span><span class="chip">topp 10 = ${pct(inv.top10_weight, false, 0)}</span>${nm.ny ? `<span class="chip on">${nm.ny} nye</span>` : ""}${nm.solgt ? `<span class="chip on bad">${nm.solgt} solgt</span>` : ""}</div>
      <div ${open_ ? "" : "hidden"}>
        <p class="g-bio">${esc(inv.bio)}</p>
        <div class="section-head" style="margin-top:10px"><h2>Bevegelser siste kvartal</h2><span class="count">${fmtDate(inv.prev_report_date)} → ${fmtDate(inv.report_date)}</span></div>
        ${movesHtml}
        <div class="section-head" style="margin-top:14px"><h2>Største posisjoner</h2><span class="count">${inv.holdings.length} av ${inv.n_positions}</span></div>
        <div class="list">${inv.holdings.map(h => holdingRowG(h, `${bigMoney(h.value)}${h.in_universe ? "" : " · utenfor universet"}`)).join("")}</div>
        <p class="note">Rapportert til SEC ${fmtDate(inv.filing_date)} for beholdning per ${fmtDate(inv.report_date)}. Bare amerikanske aksjer (long). Trykk på en aksje for Aksjeradars analyse.</p>
      </div>
    </div>`;
  }
  function viewGuruer() {
    if (!gurus && !gurusError) { if (!gurusLoading) loadGurus(false); return `<div class="skeleton"><span></span><span></span></div>`; }
    if (!gurus) return `<div class="empty-card" style="margin-top:16px"><b>Guru-porteføljene er ikke hentet ennå.</b><p>De hentes fra SEC i den daglige kjøringen.</p></div>`;
    const g = gurus;
    let html = `<p class="hint" style="margin-top:12px">Porteføljene til ${g.investors.length} kjente investorer, fra deres kvartalsvise 13F-rapporter til det amerikanske finanstilsynet (SEC). Rapportene kommer inntil 45 dager etter kvartalsslutt.${g.demo ? " <b>Demo-data.</b>" : ""}</p>`;
    if ((g.alerts || []).length) html += `<div class="alert">👑 <b>Nye rapporter:</b> ${g.alerts.map(a => esc(a.text)).join(" · ")}</div>`;
    html += `<div class="seg" style="margin-top:10px">${[["konsensus", "Konsensus"], ["investorer", "Investorer"]].map(([k, l]) => `<button data-gview="${k}" aria-pressed="${guruState.view === k}">${l}</button>`).join("")}</div>`;
    const c = g.consensus || {};
    if (guruState.view === "konsensus") {
      const sec = (title, items, fmt) => `<div class="section">${sectionHead(title, (items || []).length)}${(items || []).length ? `<div class="list">${items.map(x => holdingRowG({ ...x, weight: null }, fmt(x))).join("")}</div>` : `<div class="empty">Ingen.</div>`}</div>`;
      html += sec("Flest guruer eier", c.owned, x => `${x.n} av ${g.investors.length} · snittvekt ${pct(x.avg_weight, false, 1)} · ${esc(x.investors.slice(0, 4).join(", "))}${x.investors.length > 4 ? " …" : ""}`);
      html += sec("Flest kjøpte siste kvartal", c.bought, x => `${x.n} kjøpte (${x.kinds.filter(k => k === "ny").length} nye) · ${esc(x.investors.slice(0, 4).join(", "))}${x.investors.length > 4 ? " …" : ""}`);
      html += sec("Flest solgte siste kvartal", c.sold, x => `${x.n} solgte/reduserte · ${esc(x.investors.slice(0, 4).join(", "))}${x.investors.length > 4 ? " …" : ""}`);
      html += `<p class="note">Konsensus teller hvor mange av investorene som eier, kjøpte eller solgte en aksje. Aksjer som også er i Aksjeradars univers viser anbefalingen vår og kan åpnes. Merk at 13F ikke viser short-posisjoner – en «guru» kan være netto short i noe som står oppført som eid.</p>`;
    } else {
      html += (g.investors || []).map(investorCard).join("");
      html += `<p class="note">Investorene og beskrivelsene er satt opp i config.yaml under <span class="mono">gurus.list</span>. Historisk avkastning er hentet fra offentlige kilder og er ingen garanti for fremtiden – flere av dem har hatt store tapsår.</p>`;
    }
    return html;
  }

  // ---------- «Mer»: screener, varsler, om ----------
  let currentSubview = null;
  function viewMer() {
    const warnCount = ideaItems("warnings").length;
    const good = goodFunds().length;
    return `<div class="section" style="margin-top:14px"><div class="list">
      <button class="row menu" data-sub="fond"><span class="l"><span class="l1"><span class="tick" style="font-family:var(--font-ui)">Fond</span>${good ? `<span class="pill hi">${good}</span>` : ""}</span><span class="l2"><span class="info" style="font-family:var(--font-ui)">Gunstige innganger i aksjefond – fall i NOK og valuta</span></span></span><span class="mid"></span><span class="r">›</span></button>
      <button class="row menu" data-sub="screener"><span class="l"><span class="l1"><span class="tick" style="font-family:var(--font-ui)">Screener</span></span><span class="l2"><span class="info" style="font-family:var(--font-ui)">Sorter og filtrer alle ${stocks().length} aksjene</span></span></span><span class="mid"></span><span class="r">›</span></button>
      <button class="row menu" data-sub="varsler"><span class="l"><span class="l1"><span class="tick" style="font-family:var(--font-ui)">Varsler</span>${warnCount ? `<span class="pill lo">${warnCount}</span>` : ""}</span><span class="l2"><span class="info" style="font-family:var(--font-ui)">Aksjer i universet som viser svakhet</span></span></span><span class="mid"></span><span class="r">›</span></button>
      <button class="row menu" id="push-menu"><span class="l"><span class="l1"><span class="tick" style="font-family:var(--font-ui)">Push-varsler</span></span><span class="l2"><span class="info" style="font-family:var(--font-ui)">Få varsler på låseskjermen – oppsett på to minutter</span></span></span><span class="mid"></span><span class="r">›</span></button>
      <button class="row menu" id="info-menu"><span class="l"><span class="l1"><span class="tick" style="font-family:var(--font-ui)">Om Aksjeradar</span></span><span class="l2"><span class="info" style="font-family:var(--font-ui)">Hvordan score, anbefalinger og autotrader regnes ut</span></span></span><span class="mid"></span><span class="r">›</span></button>
    </div></div>`;
  }
  function openSubview(key, push) {
    const titles = { screener: ["Screener", "Sorter og filtrer"], varsler: ["Varsler", "Svakhetstegn i universet"], fond: ["Fond", "Gunstige innganger i aksjefond"] };
    currentSubview = key;
    showSheet(`${sheetTop(titles[key][0], titles[key][1])}<div class="gutter sheet-body" id="subview"></div>`, push, { sub: key });
    rerenderSubview();
  }
  function rerenderSubview() {
    const box = $("#subview");
    if (!box || !currentSubview) return;
    const views = { screener: viewScreener, varsler: viewVarsler, fond: viewFond };
    box.innerHTML = views[currentSubview]();
    if (currentSubview === "screener") {
      const q = $("#q");
      q.addEventListener("input", () => { state.query = q.value; state.limit = 80; const pos = q.selectionStart; rerenderSubview(); const q2 = $("#q"); q2.focus(); q2.setSelectionRange(pos, pos); });
      $("#sort").addEventListener("change", e => { state.sort = e.target.value; rerenderSubview(); });
    }
  }

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
      const intraCount = intra && intra.setups ? intra.setups.filter(x => inMarket({ market: x.market })).length : 0;
      const badge = k === "mer" && warnCount ? `<span class="badge">${warnCount}</span>` : k === "kjop" && buyCount ? `<span class="badge ok">${buyCount}</span>` : k === "intradag" && intraCount ? `<span class="badge ok">${intraCount}</span>` : "";
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
    const views = { ideer: viewIdeer, kjop: viewKjop, intradag: viewIntradag, guruer: viewGuruer, portefolje: viewPortefolje, auto: viewAuto, mer: viewMer, screener: viewScreener, varsler: viewVarsler };
    main.innerHTML = views[state.tab]();
    if (state.tab === "screener") {
      const q = $("#q");
      q.addEventListener("input", () => { state.query = q.value; state.limit = 80; const pos = q.selectionStart; render(); const q2 = $("#q"); q2.focus(); q2.setSelectionRange(pos, pos); });
      $("#sort").addEventListener("change", e => { state.sort = e.target.value; render(); });
    }
  }

  document.addEventListener("click", e => {
    const rb = e.target.closest("[data-range]");
    if (rb) { chartState.range = rb.dataset.range; try { localStorage.setItem("ar.range", chartState.range); } catch (x) { /* ignorer */ } const cb = $("#chart-box"); if (cb) rerenderChart(cb.dataset.chart); return; }
    if (e.target.closest("#sma-toggle")) { chartState.sma = !chartState.sma; try { localStorage.setItem("ar.sma", chartState.sma ? "1" : "0"); } catch (x) { /* ignorer */ } const cb = $("#chart-box"); if (cb) rerenderChart(cb.dataset.chart); return; }
    const row = e.target.closest("[data-ticker]");
    if (row) { if (!row.dataset.nodetail) openStock(row.dataset.ticker); return; }
    const sub = e.target.closest("[data-sub]");
    if (sub) { openSubview(sub.dataset.sub); return; }
    const fc = e.target.closest("[data-fund]");
    if (fc && !currentSubview) { openSubview("fond"); return; }
    if (e.target.closest("#info-menu")) { openInfo(); return; }
    if (e.target.closest("#push-menu")) { openPush(); return; }
    if (e.target.closest("#an-toggle")) {
      const body = $("#an-body"), btn = $("#an-toggle");
      body.hidden = !body.hidden;
      btn.textContent = (body.hidden ? "Les" : "Skjul") + " hele analysen";
      try { localStorage.setItem("ar.analysis", body.hidden ? "0" : "1"); } catch (x) { /* ignorer */ }
      return;
    }
    if (e.target.closest("#push-copy")) {
      const txt = $("#push-topic").textContent;
      const done = () => { $("#push-copy").textContent = "Kopiert ✓"; };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(done).catch(() => {});
      return;
    }
    const gh = e.target.closest("[data-guru]");
    if (gh) { guruState.open[gh.dataset.guru] = !guruState.open[gh.dataset.guru]; render(); return; }
    const gv = e.target.closest("[data-gview]");
    if (gv) { guruState.view = gv.dataset.gview; render(); window.scrollTo(0, 0); return; }
    const pick = e.target.closest("[data-pick]");
    if (pick) { e.preventDefault(); pickStock(pick.dataset.pick); return; }
    const trade = e.target.closest("[data-trade]");
    if (trade) { openTrade(trade.dataset.trade, trade.dataset.tkr || null); return; }
    const ok = e.target.closest("#f-ok");
    if (ok) { submitTrade(ok.dataset.kind, ok.dataset.tkr); return; }
    const rm = e.target.closest("#f-remove");
    if (rm) { pf.real.holdings = pf.real.holdings.filter(h => h.ticker !== rm.dataset.tkr); pfSave(); render(); history.back(); return; }
    const pm = e.target.closest("[data-pfmode]");
    if (pm) { pf.mode = pm.dataset.pfmode; pfSave(); render(); return; }
    if (e.target.closest("#pf-backup")) { openBackup(); return; }
    if (e.target.closest("#pf-reset")) {
      $("#pf-reset").outerHTML = `<span class="confirm">Startkapital <input id="reset-cash" class="mini" type="number" inputmode="numeric" value="${pf.paper.startCash || DEFAULT_CASH}"> <button class="btn danger small" id="reset-ok">Nullstill</button> <button class="btn secondary small" id="reset-cancel">Avbryt</button></span>`;
      return;
    }
    if (e.target.closest("#reset-cancel")) { render(); return; }
    if (e.target.closest("#reset-ok")) {
      const cash = parseFloat($("#reset-cash").value) || DEFAULT_CASH;
      pf.paper = { cash, startCash: cash, startDate: today(), holdings: [], trades: [], history: [] };
      pfSave(); render(); return;
    }
    if (e.target.closest("#bk-copy")) {
      const txt = $("#bk-out").value;
      const done = () => { $("#bk-copy").textContent = "Kopiert ✓"; };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(done).catch(() => { $("#bk-out").select(); });
      else { $("#bk-out").select(); }
      return;
    }
    if (e.target.closest("#bk-restore")) {
      try {
        const obj = JSON.parse($("#bk-in").value);
        if (!obj || !obj.real || !obj.paper) throw new Error("ugyldig");
        pf = obj; if (!BASES.includes(pf.base)) pf.base = "NOK"; pfSave();
        $("#bk-msg").className = "pos"; $("#bk-msg").textContent = "Gjenopprettet. Gå tilbake for å se porteføljen.";
        render();
      } catch (x) { $("#bk-msg").textContent = "Dette ser ikke ut som en sikkerhetskopi fra Aksjeradar."; }
      return;
    }
    const mb = e.target.closest("[data-more]");
    if (mb) {
      const k = mb.dataset.more;
      if (k === "screener") state.limit += 100; else if (k.startsWith("verdict:")) state.expand[k.slice(8)] = true;
      if (currentSubview && !$("#sheet").hidden) rerenderSubview(); else render();
      return;
    }
    const tile = e.target.closest("[data-verdict]");
    if (tile) { state.verdictFilter = state.verdictFilter === tile.dataset.verdict ? null : tile.dataset.verdict; state.expand = {}; render(); return; }
    const seg = e.target.closest("[data-market]");
    if (seg) { state.market = seg.dataset.market; state.limit = 80; state.expand = {}; try { localStorage.setItem("ar.market", state.market); } catch (x) { /* ignorer */ } render(); return; }
    const tab = e.target.closest("[data-tab]");
    if (tab) { state.tab = tab.dataset.tab; state.limit = 80; state.expand = {}; try { localStorage.setItem("ar.tab", state.tab); } catch (x) { /* ignorer */ } render(); window.scrollTo(0, 0); return; }
    if (e.target.closest("#refresh")) { load(true); return; }
    if (e.target.closest("#info")) { openInfo(); return; }
    if (e.target.closest("#search")) { openSearch(); return; }
    if (e.target.closest("#hint-close")) { try { localStorage.setItem("ar.hint", "1"); } catch (x) { /* ignorer */ } renderHeader(); }
  });

  document.addEventListener("change", e => {
    if (e.target && e.target.id === "pf-base") { pf.base = e.target.value; pfSave(); render(); }
  });

  // Service worker gir offline-støtte og raskere oppstart (ikke i forhåndsvisning)
  if (!PREVIEW && "serviceWorker" in navigator && /^https?:/.test(location.protocol)) {
    navigator.serviceWorker.register("sw.js").catch(() => { /* ikke støttet her – appen virker likevel */ });
  }

  $("#brand-icon").innerHTML = I.radar;
  $("#refresh").innerHTML = I.refresh;
  $("#info").innerHTML = I.info;
  $("#search").innerHTML = I.search;
  $("#view").innerHTML = `<div class="skeleton"><span></span><span></span><span></span></div>`;
  scheduleIntraRefresh();
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && state.tab === "intradag") loadIntra(true); });
  load(false);
})();
