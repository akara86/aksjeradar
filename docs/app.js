/* Aksjeradar – fondsapp. Leser funds.json (daglig analyse, laget av run.py) og funds_now.json
   (estimat hvert kvarter i børstiden). Ingen rammeverk, ingen avhengigheter. */
(function () {
  "use strict";

  const $ = (sel, el) => (el || document).querySelector(sel);
  const PREVIEW = !!window.__PREVIEW__;

  const TABS = [["idag", "I dag"], ["verdi", "Verdi"], ["fond", "Fond"], ["mer", "Mer"]];
  const state = { data: null, tab: "idag", error: null };
  try { state.tab = localStorage.getItem("ar.tab") || state.tab; } catch (e) { /* lagring utilgjengelig – ignorer */ }
  if (!TABS.some(t => t[0] === state.tab)) state.tab = "idag";

  // ---------- formatering ----------
  const isNum = x => typeof x === "number" && isFinite(x);
  const nbsp = " ";
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
  const money = v => (isNum(v) ? num(v, 0) + nbsp + "kr" : "–");
  const signed = v => (isNum(v) ? (v >= 0 ? "+" : "") + money(v) : "–");
  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("nb-NO", { day: "numeric", month: "short" });
  }
  function fmtClock(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    return isNaN(d) ? "–" : d.toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit" });
  }
  function fmtUpdated(d) {
    if (!d) return "";
    const gen = d.generated_at ? new Date(d.generated_at) : null;
    const today = new Date().toISOString().slice(0, 10);
    const when = d.run_date === today ? "i dag" : fmtDate(d.run_date);
    const clock = gen ? " " + gen.toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit" }) : "";
    return `Oppdatert ${when}${clock} · ${fundsData().length} fond`;
  }
  const today = () => new Date().toISOString().slice(0, 10);

  // ---------- ikoner ----------
  const I = {
    radar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12 19 6"/><circle cx="12" cy="12" r="1" fill="currentColor"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v5h-5"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/></svg>',
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 5-7 7 7 7"/></svg>',
    idag: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    verdi: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18M16 15h2"/></svg>',
    fond: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
    mer: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  };

  // ---------- data ----------
  async function load(force) {
    const btn = $("#refresh");
    if (btn) btn.classList.add("spin");
    state.error = null;
    try {
      const r = await fetch("funds.json" + (force ? "?t=" + Date.now() : ""), { cache: force ? "reload" : "default" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      state.data = await r.json();
    } catch (e) {
      if (window.__DATA__) state.data = window.__DATA__;
      else state.error = e;
    }
    if (btn) btn.classList.remove("spin");
    if (force && fundsNow) loadFundsNow(true);
    render();
  }
  const fundsData = () => (state.data && state.data.funds && state.data.funds.funds) || [];
  const ownedFunds = () => fundsData().filter(f => f.owned).slice().sort((a, b) => (a.rank || 99) - (b.rank || 99));
  const goodFunds = () => fundsData().filter(f => f.level === "Gunstig" || f.level === "Svært gunstig");
  const fundJournal = () => (state.data && state.data.funds && state.data.funds.journal) || [];
  const fundActions = () => (state.data && state.data.funds && state.data.funds.actions) || {};
  const fundById = id => fundsData().find(f => f.id === id);

  // Estimat nå (liten fil, skrives på serveren hvert 15. min i børstiden)
  let fundsNow = null, fundsNowLoading = false, fundsTimer = null;
  const needsNow = () => state.tab === "verdi" || state.tab === "idag";
  async function loadFundsNow(force) {
    if (fundsNowLoading) return;
    fundsNowLoading = true;
    try {
      const r = await fetch("funds_now.json" + (force ? "?t=" + Date.now() : ""), { cache: force ? "reload" : "default" });
      if (r.ok) fundsNow = await r.json();
      else if (!fundsNow) fundsNow = { funds: {} };
    } catch (e) { if (!fundsNow) fundsNow = { funds: {} }; }
    fundsNowLoading = false;
    if (needsNow()) render();
  }
  function scheduleFundsRefresh() {
    if (fundsTimer) clearInterval(fundsTimer);
    fundsTimer = setInterval(() => { if (document.visibilityState === "visible" && needsNow()) loadFundsNow(true); }, 5 * 60 * 1000);
  }

  // ---------- lagring: fondene dine (bare på denne enheten) ----------
  const PF_KEY = "ar.portfolio.v1";   // samme nøkkel som før, så registrerte verdier beholdes
  function pfLoad() {
    let p = null;
    try { p = JSON.parse(localStorage.getItem(PF_KEY) || "null"); } catch (e) { /* ignorer */ }
    if (!p || typeof p !== "object") p = {};
    if (!Array.isArray(p.funds)) p.funds = [];
    return p;
  }
  function pfSave() { try { localStorage.setItem(PF_KEY, JSON.stringify(pf)); } catch (e) { /* ignorer */ } }
  let pf = pfLoad();
  const fundHoldings = () => pf.funds;

  // ---------- byggeklosser ----------
  function sectionHead(title, count) {
    return `<div class="section-head"><h2>${title}</h2>${count != null ? `<span class="count">${count}</span>` : ""}</div>`;
  }
  function summaryCard(items) {
    return `<div class="summary">${items.map(([l, v, cls, sub]) => `<div><span class="s-l">${esc(l)}</span><span class="s-v mono ${cls || ""}">${v}</span>${sub ? `<small class="mono ${cls || ""}">${sub}</small>` : ""}</div>`).join("")}</div>`;
  }
  const LEVEL_CLASS = { "Svært gunstig": "v-strong", "Gunstig": "v-buy", "Nøytral": "v-hold", "Dyr": "v-wait" };
  const AV = { "Attraktiv": "v-strong", "Nøytral": "v-hold", "Lite attraktiv": "v-wait" };
  const DEP_CLASS = { boost: "v-strong", consider: "v-buy", regular: "v-hold", wait: "v-wait" };
  const depBadge = (d, big) => d ? `<span class="vb ${DEP_CLASS[d.code] || ""} ${big ? "big" : ""}">${esc(d.action)}</span>` : "";

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
      <text x="${W - padR + 6}" y="${(y(v) + 4).toFixed(1)}" font-size="10" fill="var(--muted)">${hi >= 2000 ? num(v / 1000, 1) + "k" : num(v, 0)}</text>`).join("");
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Verdiutvikling">${grid}
      ${series.map(s => `<path d="${path(s.values)}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} stroke-linejoin="round" stroke-linecap="round"/>`).join("")}
      <text x="${padL}" y="${H - 6}" font-size="10" fill="var(--muted)">${fmtDate(dates[0])}</text>
      <text x="${W - padR}" y="${H - 6}" font-size="10" fill="var(--muted)" text-anchor="end">${fmtDate(dates[dates.length - 1])}</text></svg>`;
  }
  function fundChart(h) {
    // to linjer, hver indeksert til 100 ved start: fondet i NOK og indeksen i egen valuta
    if (!h || !h.nok || h.nok.length < 5) return "";
    const n0 = h.nok[0], i0 = h.idx[0];
    const nok = h.nok.map(v => v / n0 * 100), idx = h.idx.map(v => v / i0 * 100);
    return lineChart([{ values: idx, color: "var(--muted)", width: 1.3, dash: "4 3" }, { values: nok, color: "var(--accent)", width: 2.2 }], h.dates);
  }

  // Rangeringskort (alle fond)
  function fundCard(f, compact) {
    const fxLine = f.fx_relevant && isNum(f.fx_vs_sma200)
      ? `<span><i>Krone mot ${esc(f.currency)}</i><b class="mono ${f.fx_vs_sma200 < 0 ? "pos" : "neg"}">${pct(-f.fx_vs_sma200)}</b><small>${f.fx_vs_sma200 < 0 ? "sterkere enn snitt" : "svakere enn snitt"}</small></span>`
      : `<span><i>Valuta</i><b class="mono">–</b><small>${f.hedged ? "valutasikret" : "ikke relevant"}</small></span>`;
    const parts = f.attr_parts || {};
    const partRow = (l, v) => `<span class="lbl">${l}</span><span class="bar"><i style="width:${isNum(v) ? Math.max(2, v) : 0}%;${isNum(v) ? "" : "opacity:.3"}"></i></span><span class="val">${isNum(v) ? sc(v) : "–"}</span>`;
    return `<div class="fund ${AV[f.attr_verdict] || LEVEL_CLASS[f.level] || ""}">
      <div class="su-top"><span class="rank-no mono">#${f.rank || "–"}</span>${f.attr_verdict ? `<span class="vb ${AV[f.attr_verdict]}">${esc(f.attr_verdict)}</span>` : ""}<span class="vb ${LEVEL_CLASS[f.level] || ""}">Inngang · ${esc(f.level)}</span>${f.owned ? `<span class="vb own">Ditt</span>` : ""}<span class="su-mkt mono" style="margin-left:auto;margin-right:0">${esc(f.proxy)}${f.hedged ? " · sikret" : ""}</span><span class="pill ${scClass(f.attr_score)}" title="Attraktivitet">${sc(f.attr_score)}</span></div>
      <div class="fund-name">${esc(f.name)}</div>
      ${f.deposit ? `<div class="advice">→ ${esc(f.deposit.action)}</div>` : ""}
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
      <button class="linkbtn" data-fundinfo="${esc(f.id)}" style="margin-top:8px;padding:0">Les dagens analyse ›</button>
    </div>`;
  }

  // Dagens rapportkort (fond du eier)
  function fundReportCard(f) {
    const d = f.deposit || {};
    const prev = d.changed ? fundActions()[d.prev_code] : null;
    const key = (d.reasons || [])[0] || (d.cautions || [])[0] || "";
    return `<button class="fund fr ${DEP_CLASS[d.code] || ""}" data-fundinfo="${esc(f.id)}">
      <span class="su-top">${depBadge(d)}${d.changed ? `<span class="chip on">Nytt råd i dag</span>` : ""}<span class="mono muted" style="margin-left:auto;font-size:12px">${fmtDate(f.last_date)}</span></span>
      <span class="fund-name" style="margin-top:6px">${esc(f.name)}</span>
      ${key ? `<span class="fr-key">${esc(key.charAt(0).toUpperCase() + key.slice(1))}${prev ? ` · var «${esc(prev)}»` : ""}</span>` : ""}
      <span class="levels" style="margin-top:8px">
        <span><i>I dag</i><b class="mono ${sign(f.change_1d)}">${pct(f.change_1d)}</b></span>
        <span><i>Fra topp</i><b class="mono ${sign(f.dd_52w)}">${pct(f.dd_52w)}</b></span>
        <span><i>Inngang</i><b style="font-size:12.5px">${esc(f.level === "Svært gunstig" ? "Sv. gunstig" : f.level)}</b></span>
        <span><i>Trend</i><b style="font-size:12.5px">${isNum(f.vs_sma200) ? (f.vs_sma200 > 0 ? "opp" : "svak") : "–"}</b></span>
      </span>
      <span class="fr-more">Les dagens analyse ›</span>
    </button>`;
  }
  function fundJournalList(limitDays, onlyId) {
    const days = fundJournal().slice(0, limitDays || 14);
    if (!days.length) return `<div class="empty">Loggen bygges opp fra og med neste daglige kjøring.</div>`;
    return `<div class="card" style="margin-top:0"><div class="lines jl">${days.map(day => {
      const rows = day.funds.filter(r => !onlyId || r.id === onlyId);
      if (!rows.length) return "";
      return rows.map((r, i) => `<div class="ln"><span class="d">${i === 0 ? fmtDate(day.date) : ""}</span><span class="t">${onlyId ? "" : `<b>${esc(r.name)}</b>`}<span class="jl-act"><span class="${DEP_CLASS[r.code] ? "vb " + DEP_CLASS[r.code] : ""}">${esc(r.action)}</span>${r.changed ? `<span class="chip on">endret</span>` : ""}</span></span><span class="v mono ${sign(r.change_1d)}">${pct(r.change_1d)}<small class="muted">${pct(r.dd_52w)} fra topp</small></span></div>`).join("");
    }).join("")}</div></div>`;
  }

  // ---------- estimert verdi nå: dine registrerte verdier × utvikling (daglig kurve + intradag) ----------
  function navFactor(f, fromDate) {
    const h = f && f.history;
    if (!h || !h.dates || !h.nok || !h.nok.length) return { factor: 1, from: null, to: null, note: "ingen historikk" };
    const i = h.dates.findIndex(d => d >= fromDate);
    if (i < 0) return { factor: 1, from: h.dates[h.dates.length - 1], to: h.dates[h.dates.length - 1], note: "registrert etter siste kurs" };
    const note = h.dates[0] > fromDate ? `historikken starter ${fmtDate(h.dates[0])}` : null;
    return { factor: h.nok[h.nok.length - 1] / h.nok[i], from: h.dates[i], to: h.dates[h.dates.length - 1], note };
  }
  function fundEstimate(hold) {
    const f = fundById(hold.id);
    if (!f) return null;
    const nf = navFactor(f, hold.date);
    const est = fundsNow && fundsNow.funds ? fundsNow.funds[hold.id] : null;
    // Intradag-estimatet gjelder mot forrige børsdag. Unngå dobbelttelling hvis den daglige kurven allerede dekker dagen.
    let todayChg = 0, useIntra = false;
    if (est && isNum(est.est_change_today) && est.session && nf.to && est.session > nf.to) { todayChg = est.est_change_today; useIntra = true; }
    const base = hold.value * nf.factor;
    const now = base * (1 + todayChg);
    return { f, nf, est, useIntra, base, now, today: todayChg, todayKr: now - base, sinceKr: now - hold.value, sincePct: hold.value ? now / hold.value - 1 : null };
  }
  function estimates() { return fundHoldings().map(h => ({ h, e: fundEstimate(h) })).filter(x => x.e); }
  function totals(ests) {
    const totNow = ests.reduce((a, x) => a + x.e.now, 0), totBase = ests.reduce((a, x) => a + x.e.base, 0), totStart = ests.reduce((a, x) => a + (x.h.value || 0), 0);
    const fresh = ests.some(x => x.e.useIntra && x.e.est.fresh);
    const anyOpen = ests.some(x => x.e.useIntra && x.e.est.market_open);
    const asOf = ests.map(x => x.e.est && x.e.useIntra ? x.e.est.as_of : null).filter(Boolean).sort().pop();
    return { totNow, totBase, totStart, todayKr: totNow - totBase, since: totNow - totStart, fresh, anyOpen, asOf };
  }

  // ---------- fane: I dag ----------
  function viewIdag() {
    const d = state.data.funds || {};
    const owned = ownedFunds();
    const alerts = d.alerts || [];
    let html = "";
    if (d.demo || state.data.demo) html += `<div class="banner demo" style="margin-top:12px"><span><b>Demo-data.</b> Tallene er tilfeldige. Kjør <span class="mono">python run.py</span> for ekte data.</span></div>`;
    if (alerts.length) html += `<div class="alert" style="margin-top:12px">💱 <b>Nytt siden sist:</b> ${alerts.map(a => esc(a.text)).join(" · ")}</div>`;
    const ests = estimates();
    if (ests.length) {
      const t = totals(ests);
      html += `<button class="summary tap" data-gototab="verdi" style="margin-top:12px">
        <div><span class="s-l">Fondene dine nå</span><span class="s-v mono">${money(t.totNow)}</span><small class="muted">${t.asOf ? "kl. " + fmtClock(t.asOf) : "siste sluttkurs"} · se Verdi ›</small></div>
        <div><span class="s-l">I dag</span><span class="s-v mono ${sign(t.todayKr)}">${signed(t.todayKr)}</span><small class="mono ${sign(t.todayKr)}">${pct(t.totBase ? t.todayKr / t.totBase : null)}</small></div>
        <div><span class="s-l">Siden registrert</span><span class="s-v mono ${sign(t.since)}">${signed(t.since)}</span><small class="mono ${sign(t.since)}">${pct(t.totStart ? t.since / t.totStart : null)}</small></div>
      </button>`;
    }
    if (owned.length) {
      const act = owned.filter(f => f.deposit && (f.deposit.code === "boost" || f.deposit.code === "consider"));
      html += `<div class="section">${sectionHead("Dine fond i dag", owned.length)}<p class="hint">${act.length ? `${act.map(f => esc(f.name)).join(" og ")}: gunstig inngang for ekstrainnskudd.` : "Ingen ekstrainnskudd anbefales i dag – fortsett spareavtalen."} Trykk på et fond for dagens analyse.</p>${owned.map(fundReportCard).join("")}</div>`;
    } else {
      html += `<div class="empty-card" style="margin-top:14px"><b>Ingen fond er merket som dine.</b><p>Sett <span class="mono">owned: true</span> på fondene dine under <span class="mono">funds.list</span> i config.yaml, så får du dagens råd her.</p></div>`;
    }
    const gf = goodFunds().filter(f => !f.owned);
    if (gf.length) {
      html += `<div class="section">${sectionHead("Andre fond – gunstig inngang nå", gf.length)}${gf.slice(0, 4).map(f => fundCard(f, true)).join("")}
        <button class="more" data-gototab="fond">Se alle fond</button></div>`;
    }
    html += `<p class="note">Rådene gjelder nye penger og sier aldri «selg». De er en mekanisk vurdering ut fra indeks-ETF, valuta, trend og aksjeanalysen for sektoren – ikke investeringsråd. Trykk <b>i</b> øverst for å se hvordan de regnes ut.</p>`;
    return html;
  }

  // ---------- fane: Verdi ----------
  function viewVerdi() {
    const hs = fundHoldings();
    if (!fundsData().length) return `<div class="empty-card" style="margin-top:14px"><b>Ingen fond er satt opp i appen.</b></div>`;
    const ests = estimates();
    let html = "";
    if (!ests.length) {
      html += `<div class="empty-card" style="margin-top:14px"><b>Registrer fondene dine.</b><p>Skriv inn verdien du ser i banken/plattformen og datoen den gjelder. Appen regner deretter ut et estimat av verdien akkurat nå – oppdatert hvert kvarter i børstiden – ut fra indeksen fondet følger og valutakursen.</p><button class="btn" data-fundadd="1">Legg til fond</button></div>`;
    } else {
      const t = totals(ests);
      html += `<div style="margin-top:12px">${summaryCard([
        ["Estimert verdi nå", money(t.totNow)],
        ["I dag", signed(t.todayKr), sign(t.todayKr), pct(t.totBase ? t.todayKr / t.totBase : null)],
        ["Siden registrert", signed(t.since), sign(t.since), pct(t.totStart ? t.since / t.totStart : null)],
        ["Oppdatert", t.asOf ? fmtClock(t.asOf) + (t.fresh ? "" : t.anyOpen ? " (forsinket)" : " · børs stengt") : "siste sluttkurs", ""],
      ])}</div>`;
      html += `<p class="hint" style="margin-top:8px">${t.asOf ? (t.anyOpen ? `Intradag-kurser ca. 15 min forsinket. ` : `Børsene er stengt – viser dagens sluttkurs. `) : `Intradag-data mangler – viser siste sluttkurs fra den daglige analysen. `}Estimatet bruker indeksen fondet følger, ikke fondets egen kurs.</p>`;
      html += `<div class="section">${sectionHead("Dine fond", ests.length)}${ests.map(({ h, e }) => `
        <div class="fund v-hold" style="border-left-color:var(--accent)">
          <div class="su-top"><span class="fund-name" style="margin:0;font-size:15px">${esc(e.f.name)}</span><button class="linkbtn" data-fundedit="${esc(h.id)}" style="margin-left:auto">Endre</button></div>
          <div class="levels two" style="margin-top:8px">
            <span><i>Nå (est.)</i><b class="mono">${money(e.now)}</b><small>reg. ${money(h.value)}</small></span>
            <span><i>I dag</i><b class="mono ${sign(e.todayKr)}">${pct(e.today)}</b><small class="mono ${sign(e.todayKr)}">${signed(e.todayKr)}</small></span>
            <span><i>Siden ${fmtDate(h.date)}</i><b class="mono ${sign(e.sinceKr)}">${pct(e.sincePct)}</b><small class="mono ${sign(e.sinceKr)}">${signed(e.sinceKr)}</small></span>
            <span><i>Kilde</i><b class="mono" style="font-size:12px">${e.useIntra ? esc(e.est.proxy) : esc(e.f.proxy)}</b><small>${e.useIntra ? `${esc(e.est.as_of_local)} · ${e.est.fresh ? "fersk" : e.est.market_open ? e.est.age_min + " min gammel" : "stengt"}` : "sluttkurs " + fmtDate(e.nf.to)}</small></span>
          </div>
          ${e.useIntra && e.est.fx ? `<p class="muted" style="margin:8px 0 0;font-size:12.5px">Indeks ${pct(e.est.proxy_change)} i ${esc(e.est.proxy_currency)} · valuta ${esc(e.est.fx.pair)} ${pct(e.est.fx.change)} → ${pct(e.today)} i NOK</p>` : ""}
          ${e.f.deposit ? `<button class="linkbtn" data-fundinfo="${esc(e.f.id)}" style="margin-top:8px;padding:0;text-align:left">Dagens råd: ${depBadge(e.f.deposit)} <span class="muted">analyse ›</span></button>` : ""}
          ${e.nf.note ? `<p class="muted" style="margin:6px 0 0;font-size:12.5px">${esc(e.nf.note)}</p>` : ""}
        </div>`).join("")}</div>
        <div class="btn-row"><button class="btn" data-fundadd="1">Legg til fond</button><button class="btn secondary" id="pf-backup">Sikkerhetskopi</button></div>`;
    }
    html += `<p class="note">Fondskursen settes offisielt én gang per dag av fondsselskapet. Tallene her er et estimat basert på en ETF som følger samme indeks (15-minutters kurser) og dagens valutakurs. Aktive fond avviker fra indeksen. Verdiene du registrerer lagres bare på denne enheten – bruk «Sikkerhetskopi» for å flytte dem til en annen telefon.</p>`;
    return html;
  }

  // ---------- fane: Fond (rangering) ----------
  function viewFond() {
    const fs = fundsData();
    if (!fs.length) return `<div class="empty-card" style="margin-top:16px"><b>Ingen fond er satt opp.</b><p>Fond kobles til en indeks-ETF i config.yaml under <span class="mono">funds.list</span>.</p></div>`;
    const sorted = fs.slice().sort((a, b) => (a.rank || 99) - (b.rank || 99));
    let html = `<p class="hint" style="margin-top:12px">Hvert fond følges via en ETF som speiler samme indeks, omregnet til NOK med dagens valutakurs. Rangeringen sier hvor attraktivt det er å sette <i>nye</i> penger i fondet nå – relativt til de andre fondene i listen.</p>`;
    html += `<div class="section">${sectionHead("Rangering etter attraktivitet", sorted.length)}${sorted.map(f => fundCard(f, false)).join("")}</div>`;
    const th = state.data.funds.thresholds || {};
    html += `<div class="card"><h3>Slik vurderes fondene</h3><ul class="reasons" style="margin:0;padding-left:18px">
      <li><b>Attraktivitet</b> (0–100) veier fire deler: <b>Inngang</b> 20 % (hvor «på salg» fondet er i NOK, som bonus), <b>Trend</b> 35 % (over 200-dagers snitt, 50-dagers over 200, positive 3 mnd, 1 år mot globalt indeksfond), <b>Sektor/marked</b> 30 % (andel aksjer i opptrend, snittscore og andel kjøpsanbefalinger i aksjeanalysen for den sektoren/børsen) og <b>Risiko/prising</b> 15 % (årlige svingninger og forventet P/E mot hele universet). ≥ 60 = Attraktiv, ≥ 45 = Nøytral.</li>
      <li><b>Inngangsscore</b> (0–100): fall fra 52-ukers topp i NOK (20 % = fullt utslag), avstand under 200-dagers snitt, RSI, og hvor sterk kronen er mot sitt 200-dagers snitt i fondets valuta (sterk krone = billigere inngang).</li>
      <li><b>Gunstig</b> = score ≥ 45 eller fall ≥ ${pct(-(th.good_drawdown || -0.08), false, 0)} fra topp. <b>Svært gunstig</b> = score ≥ 70 eller fall ≥ ${pct(-(th.strong_drawdown || -0.15), false, 0)}. <b>Dyr</b> = nær topp, langt over 200d-snitt og svak krone.</li>
      <li><b>Innskuddsrådet</b> kombinerer inngang og attraktivitet: Svært gunstig inngang gir «Ekstrainnskudd anbefales» (med mindre trend og sektor er svake), Gunstig gir «Ekstrainnskudd anbefales» ved attraktiv trend ellers «Vurder», Nøytral gir «Fortsett vanlig sparing», Dyr gir «Avvent». Rådene gjelder nye penger – de sier aldri «selg», fordi fondssparing er langsiktig og salg utløser skatt.</li>
      <li>Valutasikrede fond vurderes uten valutaeffekt. Norske fond: valutaen nøytraliseres når ETF-en regnes om til NOK.</li>
    </ul></div>
    <p class="note">Rangeringen er en mekanisk sammenligning – den vet ikke hva som skjer i morgen. En sunn fondsportefølje har et bredt globalt indeksfond som kjerne og sektor-/regionsfond som mindre satellitter uansett hva rangeringen sier denne uken. Et fall kan fortsette. Ikke investeringsråd. ETF-ene avviker litt fra fondene (honorar, én dags forsinkelse i andelskurs).</p>`;
    return html;
  }

  // ---------- fane: Mer ----------
  function viewMer() {
    let html = `<div class="section" style="margin-top:14px"><div class="list">
      <button class="row menu" id="push-menu"><span class="l"><span class="l1"><span class="tick" style="font-family:var(--font-ui)">Push-varsler</span></span><span class="l2"><span class="info" style="font-family:var(--font-ui)">Få dagens råd på låseskjermen – oppsett på to minutter</span></span></span><span class="mid"></span><span class="r">›</span></button>
      <button class="row menu" id="pf-backup"><span class="l"><span class="l1"><span class="tick" style="font-family:var(--font-ui)">Sikkerhetskopi</span></span><span class="l2"><span class="info" style="font-family:var(--font-ui)">Flytt de registrerte fondsverdiene til en annen telefon</span></span></span><span class="mid"></span><span class="r">›</span></button>
      <button class="row menu" id="info-menu"><span class="l"><span class="l1"><span class="tick" style="font-family:var(--font-ui)">Om Aksjeradar</span></span><span class="l2"><span class="info" style="font-family:var(--font-ui)">Hvordan rådene og estimatene regnes ut</span></span></span><span class="mid"></span><span class="r">›</span></button>
    </div></div>`;
    html += `<div class="section">${sectionHead("Logg – slik har rådene utviklet seg", fundJournal().length)}<p class="hint">Ett innslag per børsdag for fondene dine. «Endret» markerer dagene rådet skiftet.</p>${fundJournalList(21)}</div>`;
    return html;
  }

  // ---------- ark (detaljer, skjema, info) ----------
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
  function sheetTop(title, subtitle, right) {
    return `<div class="sheet-top"><div class="gutter bar">
        <button class="back" id="back" aria-label="Tilbake">${I.back}Tilbake</button>
        <div class="ttl"><b>${title}</b><span>${subtitle}</span></div>${right || ""}
      </div></div>`;
  }
  function closeSheet() {
    const sheet = $("#sheet");
    if (sheet.hidden) return;
    sheet.classList.remove("open");
    document.body.style.overflow = "";
    setTimeout(() => { if (!sheet.classList.contains("open")) sheet.hidden = true; }, 300);
  }
  window.addEventListener("popstate", e => {
    if (e.state && e.state.info) openInfo(false);
    else if (e.state && e.state.backup) openBackup(false);
    else if (e.state && e.state.pushinfo) openPush(false);
    else if (e.state && e.state.fundform !== undefined) openFundForm(e.state.fundform || null, false);
    else if (e.state && e.state.fundinfo) openFundAnalysis(e.state.fundinfo, false);
    else closeSheet();
  });

  function openFundAnalysis(id, push) {
    const f = fundById(id);
    if (!f) return;
    const d = f.deposit || {}, an = f.analysis || {};
    showSheet(`
      ${sheetTop(esc(f.name), `Dagens analyse · ${fmtDate(f.last_date)}`)}
      <div class="gutter sheet-body">
        <div class="badges" style="margin-top:4px">${depBadge(d, true)}${f.owned ? `<span class="vb own">Ditt</span>` : ""}</div>
        <div class="badges" style="margin-top:8px"><span class="vb ${LEVEL_CLASS[f.level] || ""}">Inngang · ${esc(f.level)}</span>${f.attr_verdict ? `<span class="vb ${AV[f.attr_verdict]}">Attraktivitet · ${esc(f.attr_verdict)}</span>` : ""}<span class="vb" style="background:var(--surface-2);color:var(--muted)">#${f.rank || "–"} av ${fundsData().length}</span></div>
        ${d.changed ? `<div class="alert" style="margin-top:10px">Rådet er endret i dag${d.prev_code && fundActions()[d.prev_code] ? ` – var «${esc(fundActions()[d.prev_code])}»` : ""}.</div>` : ""}
        <div class="levels" style="margin-top:12px">
          <span><i>Kurs (NOK)</i><b class="mono">${num(f.price_nok, 0)}</b><small class="${sign(f.change_1d)}">${pct(f.change_1d)} i dag</small></span>
          <span><i>Fra topp</i><b class="mono ${sign(f.dd_52w)}">${pct(f.dd_52w)}</b><small>52 uker</small></span>
          <span><i>1 mnd</i><b class="mono ${sign(f.ret_1m)}">${pct(f.ret_1m)}</b></span>
          <span><i>1 år</i><b class="mono ${sign(f.ret_1y)}">${pct(f.ret_1y)}</b></span>
        </div>
        <div class="analysis" style="margin-top:14px">${(an.sections || []).map(sx => sx.h === "Hva som ville endret vurderingen" && (an.triggers || []).length
          ? `<h3>${esc(sx.h)}</h3><ul class="reasons" style="margin:0;padding-left:18px">${an.triggers.map(t => `<li>${esc(t)}</li>`).join("")}</ul>`
          : `<h3>${esc(sx.h)}</h3><p>${esc(sx.t)}</p>`).join("")}</div>
        ${d.size ? `<div class="card"><h3>Hvor mye?</h3><p style="margin:0">${esc(d.size.charAt(0).toUpperCase() + d.size.slice(1))}. Rådene gjelder <i>nye</i> penger – fast sparing fortsetter uansett.</p></div>` : ""}
        <div class="chart" style="margin-top:12px">${fundChart(f.history)}<div class="legend"><span><i style="background:var(--accent)"></i>Fondet i NOK</span><span><i style="background:var(--muted)"></i>Indeksen i ${esc(f.currency)}</span><span>begge = 100 ved start</span></div></div>
        <div class="section">${sectionHead("Tidligere vurderinger", fundJournal().filter(dd => dd.funds.some(r => r.id === id)).length)}${fundJournalList(14, id)}</div>
        <p class="note">Analysen skrives automatisk hver morgen ut fra tallene (ETF som følger samme indeks × valutakurs, trend, aksjeanalysen for sektoren/markedet, svingninger). Den vet ikke hva som skjer i morgen, og et fall kan fortsette – derfor sier rådene aldri «alt på én gang». Ikke investeringsråd.</p>
      </div>`, push, { fundinfo: id });
  }

  function openFundForm(id, push) {
    const avail = fundsData();
    const existing = id ? fundHoldings().find(h => h.id === id) : null;
    const options = avail.map(f => `<option value="${esc(f.id)}" ${existing && existing.id === f.id ? "selected" : ""}>${esc(f.name)}${f.owned ? " (ditt)" : ""}</option>`).join("");
    showSheet(`
      ${sheetTop(existing ? "Endre fond" : "Legg til fond", "Verdi slik banken viser den, og datoen den gjelder")}
      <div class="gutter sheet-body">
        <div class="form">
          <label class="field"><span>Fond</span><select id="ff-id" class="search-input" ${existing ? "disabled" : ""}>${options}</select></label>
          <label class="field"><span>Verdi (NOK)</span><input id="ff-value" type="number" inputmode="decimal" min="0" step="1" value="${existing ? existing.value : ""}" placeholder="f.eks. 367437"></label>
          <label class="field"><span>Verdien gjelder dato</span><input id="ff-date" type="date" value="${existing ? existing.date : today()}"></label>
          <p id="ff-msg" class="neg" style="margin:0"></p>
          <div class="btn-row"><button class="btn" id="ff-ok" data-id="${esc(existing ? existing.id : "")}">${existing ? "Lagre" : "Legg til"}</button>${existing ? `<button class="btn danger" id="ff-remove" data-id="${esc(existing.id)}">Fjern</button>` : ""}</div>
          <p class="muted" style="font-size:13px;margin:0">Tips: registrer verdien på en dag fondet er kurssatt (en ukedag), så blir estimatet mest presist. Oppdater verdien av og til, f.eks. etter innskudd.</p>
        </div>
      </div>`, push, { fundform: id || "" });
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
          <li><b>Hver morgen</b> ca. 08:40–09:00: dagens råd for hvert av fondene dine, og fond med gunstig inngang.</li>
          <li><b>Når rådet endres</b> for et av fondene dine (f.eks. fra «vanlig sparing» til «vurder ekstrainnskudd»).</li>
          <li><b>Når et fond</b> skifter til eller fra gunstig inngang.</li>
        </ul><p class="muted" style="font-size:13px">Hva som sendes styres i config.yaml under <span class="mono">notify.push</span>.</p></div>`
        : `<div class="card"><h3>Push er ikke satt opp</h3><p>Slå på <span class="mono">notify.push</span> i config.yaml og legg inn et ntfy-emne, så vises oppskriften her.</p></div>`}
      </div>`, push, { pushinfo: true });
  }

  function openBackup(push) {
    showSheet(`
      ${sheetTop("Sikkerhetskopi", "Kopier ut – eller lim inn for å gjenopprette")}
      <div class="gutter sheet-body">
        <div class="card"><h3>Dine registrerte fond</h3>
          <textarea id="bk-out" class="ta" readonly>${esc(JSON.stringify(pf))}</textarea>
          <div class="btn-row"><button class="btn" id="bk-copy">Kopier</button></div>
          <p class="muted" style="font-size:13px">Lim teksten inn i Notater eller en e-post til deg selv. Da kan du flytte verdiene til en annen telefon.</p>
        </div>
        <div class="card"><h3>Gjenopprett</h3>
          <textarea id="bk-in" class="ta" placeholder="Lim inn en sikkerhetskopi her"></textarea>
          <p id="bk-msg" class="neg" style="margin:0"></p>
          <div class="btn-row"><button class="btn secondary" id="bk-restore">Gjenopprett</button></div>
        </div>
      </div>`, push, { backup: true });
  }

  function openInfo(push) {
    showSheet(`
      ${sheetTop("Om Aksjeradar", "Slik regnes rådene og estimatene ut")}
      <div class="gutter sheet-body">
        <div class="card"><h3>Hvordan fondene følges</h3>
          <p>Norske fond finnes knapt hos gratis datakilder, så hvert fond kobles til en børsnotert ETF som følger samme indeks (f.eks. MSCI World for et globalt indeksfond). ETF-kursen ganget med valutakursen gir fondets kurs i kroner – minus honorar, og med én dags forsinkelse i den offisielle andelskursen. Aktive fond (Gambak, Global Solutions, DNB Teknologi) avviker noe fra indeksen de måles mot.</p>
        </div>
        <div class="card"><h3>Dagens råd</h3>
          <p>Hver morgen regnes en <b>inngangsscore</b> (hvor «på salg» fondet er: fall fra 52-ukers topp i NOK, avstand under 200-dagers snitt, RSI og hvor sterk kronen er) og en <b>attraktivitet</b> (inngang, trend, sektor/marked fra aksjeanalysen, risiko og prising). Sammen gir de et innskuddsråd:</p>
          <div class="rules">${["boost", "consider", "regular", "wait"].map((c, i) => `<div>${depBadge({ code: c, action: ["Ekstrainnskudd anbefales", "Vurder ekstrainnskudd", "Fortsett vanlig sparing", "Avvent ekstrainnskudd"][i] })}<span>${["svært gunstig inngang (eller gunstig + attraktiv trend)", "gunstig inngang, men nøytral eller svak trend", "nøytral inngang – spareavtalen gjør jobben", "dyrt: nær topp, langt over snitt, svak krone"][i]}</span></div>`).join("")}</div>
          <p>Analysen under hvert fond viser tallene bak, og konkrete nivåer for når rådet ville endret seg. Rådene gjelder <i>nye</i> penger og sier aldri «selg» – fondssparing er langsiktig, og salg utløser skatt.</p>
        </div>
        <div class="card"><h3>Verdi nå</h3>
          <p>Du registrerer verdien fra banken og datoen den gjelder. Appen regner videre med fondets kurve i NOK fram til siste sluttkurs, og legger på dagens bevegelse i indeks-ETF-en (15-minutters kurser) ganget med dagens valutaendring – oppdatert hvert kvarter i børstiden. Verdiene lagres bare på telefonen din.</p>
        </div>
        <div class="card"><h3>Begrensninger</h3>
          <p>Data fra Yahoo Finance er ca. 15 minutter forsinket. Reglene er ikke backtestet, og en mekanisk «på salg»-måling vet ikke om et fall er over. Bruk rådene som et utgangspunkt for egen vurdering – dette er ikke investeringsråd.</p>
        </div>
      </div>`, push, { info: true });
  }

  // ---------- rammen ----------
  function renderHeader() {
    const d = state.data;
    $("#brand-sub").textContent = d ? fmtUpdated(d) : "";
    const banners = [];
    let dismissed = false;
    try { dismissed = localStorage.getItem("ar.hint") === "1"; } catch (e) { /* ignorer */ }
    const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
    const standalone = window.navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;
    if (!PREVIEW && ios && !standalone && !dismissed) {
      banners.push(`<div class="banner hint"><span>Legg til som app: trykk <b>Del</b> i Safari og velg <b>«Legg til på Hjem-skjerm»</b>.</span><button id="hint-close" aria-label="Lukk">✕</button></div>`);
    }
    $("#banners").innerHTML = banners.join("");
    const act = state.data ? ownedFunds().filter(f => f.deposit && (f.deposit.code === "boost" || f.deposit.code === "consider")).length : 0;
    $("#tabs").innerHTML = TABS.map(([k, label]) => {
      const badge = k === "idag" && act ? `<span class="badge ok">${act}</span>` : "";
      return `<button data-tab="${k}" aria-current="${k === state.tab ? "page" : "false"}">${I[k]}${label}${badge}</button>`;
    }).join("");
  }
  function render() {
    renderHeader();
    const main = $("#view");
    if (state.error || !state.data) {
      main.innerHTML = `<div class="error"><p><b>Fant ingen data.</b></p><p>Kjør <code>python run.py</code> i prosjektmappen – da lages <code>docs/funds.json</code>. Åpner du filen lokalt: start <code>python -m http.server 8000 -d docs</code> og gå til <code>http://localhost:8000</code>.</p>${state.error ? `<p class="muted">${esc(state.error.message || state.error)}</p>` : ""}</div>`;
      return;
    }
    if (needsNow() && !fundsNow && !fundsNowLoading) loadFundsNow(false);
    const views = { idag: viewIdag, verdi: viewVerdi, fond: viewFond, mer: viewMer };
    main.innerHTML = views[state.tab]();
  }
  function goTab(k) {
    state.tab = k;
    try { localStorage.setItem("ar.tab", k); } catch (x) { /* ignorer */ }
    render(); window.scrollTo(0, 0);
  }

  document.addEventListener("click", e => {
    const fi = e.target.closest("[data-fundinfo]");
    if (fi) { openFundAnalysis(fi.dataset.fundinfo); return; }
    const gt = e.target.closest("[data-gototab]");
    if (gt) { goTab(gt.dataset.gototab); return; }
    if (e.target.closest("#info-menu") || e.target.closest("#info")) { openInfo(); return; }
    if (e.target.closest("#push-menu")) { openPush(); return; }
    if (e.target.closest("#pf-backup")) { openBackup(); return; }
    if (e.target.closest("#push-copy")) {
      const txt = $("#push-topic").textContent;
      const done = () => { $("#push-copy").textContent = "Kopiert ✓"; };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(done).catch(() => {});
      return;
    }
    if (e.target.closest("[data-fundadd]")) { openFundForm(null); return; }
    const fe = e.target.closest("[data-fundedit]");
    if (fe) { openFundForm(fe.dataset.fundedit); return; }
    const ffo = e.target.closest("#ff-ok");
    if (ffo) {
      const id = ffo.dataset.id || $("#ff-id").value, value = parseFloat($("#ff-value").value), date = $("#ff-date").value || today();
      if (!id) { $("#ff-msg").textContent = "Velg et fond."; return; }
      if (!(value > 0)) { $("#ff-msg").textContent = "Skriv inn verdien i kroner."; return; }
      const hs = fundHoldings(); const ex = hs.find(h => h.id === id);
      if (ex) { ex.value = value; ex.date = date; } else hs.push({ id, value, date });
      pfSave(); state.tab = "verdi"; try { localStorage.setItem("ar.tab", state.tab); } catch (x) { /* ignorer */ }
      render(); history.back(); return;
    }
    const ffr = e.target.closest("#ff-remove");
    if (ffr) { pf.funds = fundHoldings().filter(h => h.id !== ffr.dataset.id); pfSave(); render(); history.back(); return; }
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
        if (!obj || typeof obj !== "object" || !Array.isArray(obj.funds)) throw new Error("ugyldig");
        pf = obj; pfSave();
        $("#bk-msg").className = "pos"; $("#bk-msg").textContent = "Gjenopprettet. Gå tilbake for å se fondene.";
        render();
      } catch (x) { $("#bk-msg").textContent = "Dette ser ikke ut som en sikkerhetskopi fra Aksjeradar."; }
      return;
    }
    const tab = e.target.closest("[data-tab]");
    if (tab) { goTab(tab.dataset.tab); return; }
    if (e.target.closest("#refresh")) { load(true); return; }
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
  scheduleFundsRefresh();
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && needsNow()) loadFundsNow(true); });
  load(false);
})();
