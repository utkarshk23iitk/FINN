// FINN push side: a triage queue, not a feed.
// Everything is computed here from data/feed.json, so changing a rule
// (what counts as "unusual") re-sorts the queue instantly, with no server.

const WINDOWS = [
  { key: "24h", label: "24h", hours: 24, sessions: 1 },
  { key: "3d", label: "3 days", hours: 72, sessions: 3 },
  { key: "7d", label: "Week", hours: 168, sessions: 5 },
  { key: "30d", label: "Month", hours: 720, sessions: 22 },
];

const LABEL = {
  results: "Results", "M&A": "M&A", management_change: "Management", fund_raise: "Fund raise",
  litigation: "Legal / regulator", pledging: "Pledge", credit_rating: "Credit rating",
  insider_trading: "Insider trade", capex: "Capex", press_release: "Update",
  bonus_split: "Bonus / split", dividend: "Dividend", earnings_call: "Earnings call",
  investor_meetings: "Investor meet", agm_egm: "AGM / EGM", postal_ballot: "Postal ballot",
  unclassified: "Paperwork",
};

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem("finn." + key); return v ? JSON.parse(v) : fallback; }
    catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem("finn." + key, JSON.stringify(value)); } catch { /* private mode */ }
  },
};

const app = document.getElementById("app");
const sheet = document.getElementById("sheet");
let feed, state;

// ---------- helpers ----------

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
// Times are IST wall-clock strings without a zone. Parsing and printing both
// in the viewer's local zone keeps the wall clock unchanged.
const parse = (s) => new Date(s.length === 10 ? s + "T00:00:00" : s);
const DAY = 864e5;
const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const pct = (v) => (v == null ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`);
const clip = (s, n) => (s.length <= n ? s : s.slice(0, n - 1).replace(/\s+\S*$/, "") + "…");
const tone = (v) => (v == null || Math.abs(v) < 0.05 ? "flat" : v > 0 ? "up" : "down");
const shortDate = (d) => d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
const clock = (d) => d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });

function when(t) {
  const d = parse(t), ago = (parse(feed.as_of) - d) / 36e5;
  if (ago < 1) return "just now";
  if (ago < 24) return `${Math.floor(ago)}h ago`;
  return shortDate(d);
}

// ---------- the model ----------

function groupFilings(list) {
  // One results day often brings 3-5 filings (outcome, results, deck, press
  // release). Same company + same type + same day = one card.
  const groups = new Map();
  for (const a of list) {
    const key = `${a.symbol}|${a.category}|${a.time.slice(0, 10)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(a);
  }
  return [...groups].map(([key, items]) => {
    items.sort((x, y) => y.priority - x.priority || y.time.localeCompare(x.time));
    const lead = items[0];
    return { kind: "filing", key, lead, rest: items.slice(1), score: lead.priority, time: lead.time };
  });
}

function contextFor(symbol, date) {
  // The filing most likely behind a move: from 3 days before the session to
  // the morning after (results often land after market close).
  const day = parse(date), lo = +day - 3 * DAY, hi = +day + DAY + 10 * 36e5;
  return feed.announcements
    .filter((a) => a.symbol === symbol && a.tier !== "low" && +parse(a.time) >= lo && +parse(a.time) <= hi)
    .sort((x, y) => y.priority - x.priority || y.time.localeCompare(x.time))[0];
}

function moves(sessions) {
  const { volume_multiple: vm, price_move_pct: pm } = state.rules;
  const out = [];
  for (const c of feed.companies) {
    if (state.symbol && c.symbol !== state.symbol) continue;
    const hits = c.sessions.slice(-sessions).filter((s) =>
      (s.change_pct != null && Math.abs(s.change_pct) >= pm) || (s.volume_ratio != null && s.volume_ratio >= vm));
    if (!hits.length) continue;
    const s = hits[hits.length - 1];
    const price = s.change_pct != null && Math.abs(s.change_pct) >= pm;
    const vol = s.volume_ratio != null && s.volume_ratio >= vm;
    const score = price && vol ? 88 : price ? 82 : 72 + Math.min(12, (s.volume_ratio - vm) * 2);
    out.push({ kind: "move", key: `move|${c.symbol}|${s.date}`, company: c, s, price, vol,
      extra: hits.length - 1, score, time: s.date + "T15:30:00", context: contextFor(c.symbol, s.date) });
  }
  return out;
}

function compute() {
  const w = WINDOWS.find((x) => x.key === state.win) || WINDOWS[0];
  const asOf = parse(feed.as_of), since = new Date(+asOf - w.hours * 36e5);
  const inWindow = feed.announcements.filter((a) => {
    const t = parse(a.time);
    return t >= since && t <= asOf && (!state.symbol || a.symbol === state.symbol);
  });
  const alertOn = new Set(state.rules.alert_categories);
  const groups = groupFilings(inWindow.filter((a) => a.tier !== "low"));
  const byScore = (x, y) => y.score - x.score || y.time.localeCompare(x.time);

  const needs = [...moves(w.sessions), ...groups.filter((g) => g.lead.tier === "high" && alertOn.has(g.lead.category))]
    .sort(byScore);
  const worth = groups.filter((g) => !(g.lead.tier === "high" && alertOn.has(g.lead.category))).sort(byScore);
  const routine = inWindow.filter((a) => a.tier === "low");
  const open = needs.filter((n) => !state.done.has(n.key));
  const cleared = needs.filter((n) => state.done.has(n.key));
  return { w, since, open, cleared, worth, routine, total: inWindow.length };
}

// ---------- views ----------

function spark(values, w = 52, h = 20) {
  if (values.length < 2) return "";
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - ((v - lo) / span) * (h - 4)}`);
  const cls = tone(values.at(-1) - values[0]);
  return `<svg class="spark ${cls}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">
    <polyline points="${pts.join(" ")}" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
}

function volumeBars(sessions, date) {
  const recent = sessions.slice(-22), w = 132, h = 30, gap = 1.5;
  const max = Math.max(...recent.map((s) => s.volume)), bw = (w - gap * (recent.length - 1)) / recent.length;
  const hit = recent.find((s) => s.date === date);
  const avg = hit && hit.volume_ratio ? hit.volume / hit.volume_ratio : null;
  const bars = recent.map((s, i) => {
    const bh = Math.max(1.5, (s.volume / max) * h);
    return `<rect x="${(i * (bw + gap)).toFixed(1)}" y="${(h - bh).toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="1" class="${s.date === date ? "hit" : ""}"/>`;
  }).join("");
  const line = avg ? `<line x1="0" x2="${w}" y1="${(h - (avg / max) * h).toFixed(1)}" y2="${(h - (avg / max) * h).toFixed(1)}" class="avg"/>` : "";
  return `<svg class="bars" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="Volume, last 22 sessions">${bars}${line}</svg>`;
}

const tag = (cat, strong, label) =>
  `<span class="tag ${strong ? "strong" : ""}" data-cat="${esc(cat)}">${esc(label || LABEL[cat] || cat)}</span>`;
const who = (sym) => {
  const c = feed.companies.find((x) => x.symbol === sym);
  return `<span class="sym">${esc(sym)}</span>${c?.sector ? `<span class="sector">${esc(c.sector)}</span>` : ""}`;
};
const filingLink = (url) => url ? `<a class="filing" href="${esc(url)}" target="_blank" rel="noopener">Filing ↗</a>` : "";

function moveCard(m, done) {
  const { s, company: c } = m;
  const what = [m.price ? `${pct(s.change_pct)} in a day` : "", m.vol ? `${s.volume_ratio.toFixed(1)}× usual volume` : ""]
    .filter(Boolean).join(" · ");
  const why = m.context
    ? `<p class="why"><span>Likely why</span> ${tag(m.context.category)} ${esc(clip(m.context.headline, 90))} <time>${shortDate(parse(m.context.time))}</time></p>`
    : `<p class="why muted">No filing around this date. Worth asking why.</p>`;
  return `<article class="card move ${done ? "done" : ""}">
    <header>${m.price ? tag("price", true, "Price move") : tag("volume", true, "Volume spike")}${who(c.symbol)}
      <time>${shortDate(parse(s.date))} close</time></header>
    <div class="move-body">
      <div><p class="big ${m.price ? tone(s.change_pct) : ""}">${esc(what)}</p>
        <p class="sub">₹${inr.format(s.close)} <span class="${tone(s.change_pct)}">${pct(s.change_pct)}</span>${m.extra ? ` · ${m.extra} more unusual day${m.extra > 1 ? "s" : ""} in window` : ""}</p></div>
      ${volumeBars(c.sessions, s.date)}
    </div>
    ${why}
    ${actions(m, done)}
  </article>`;
}

function filingCard(g, done) {
  const a = g.lead;
  const rest = g.rest.length
    ? `<details class="rest"><summary>+${g.rest.length} related filing${g.rest.length > 1 ? "s" : ""}</summary>
        ${g.rest.map((r) => `<p>${esc(r.headline)} ${filingLink(r.url)}</p>`).join("")}</details>` : "";
  return `<article class="card ${done ? "done" : ""}">
    <header>${tag(a.category, true)}${who(a.symbol)}<time>${when(a.time)}</time></header>
    <p class="headline">${esc(a.headline)}</p>
    ${rest}
    ${actions(g, done, a.url)}
  </article>`;
}

function actions(item, done, url) {
  return `<footer>${filingLink(url)}
    <button class="clear" data-action="${done ? "undo" : "done"}" data-key="${esc(item.key)}">${done ? "Undo" : "Done"}</button></footer>`;
}

function row(g) {
  const a = g.lead;
  return `<li class="row">
    <div class="row-top">${who(a.symbol)}${tag(a.category)}<time>${when(a.time)}</time></div>
    <p>${esc(a.headline)}${g.rest.length ? ` <span class="muted">+${g.rest.length}</span>` : ""} ${filingLink(a.url)}</p></li>`;
}

function routineBlock(list) {
  if (!list.length) return "";
  const counts = {};
  for (const a of list) counts[a.category] = (counts[a.category] || 0) + 1;
  const mix = Object.entries(counts).sort((a, b) => b[1] - a[1])
    .map(([c, n]) => `${esc(LABEL[c] || c).toLowerCase()} ${n}`).join(" · ");
  return `<details class="routine"><summary><b>${list.length} routine filings, folded</b><span>${mix}</span></summary>
    <ul>${list.map((a) => `<li><span class="sym">${esc(a.symbol)}</span> ${esc(a.headline)} ${filingLink(a.url)}</li>`).join("")}</ul></details>`;
}

function pulse(view) {
  // Companies with something going on come first, quiet ones after.
  const active = new Map();
  for (const n of [...view.open, ...view.cleared]) {
    const sym = n.kind === "move" ? n.company.symbol : n.lead.symbol;
    active.set(sym, (active.get(sym) || 0) + 10);
  }
  for (const g of view.worth) active.set(g.lead.symbol, (active.get(g.lead.symbol) || 0) + 1);
  const list = [...feed.companies].sort((a, b) => (active.get(b.symbol) || 0) - (active.get(a.symbol) || 0));
  const chips = list.map((c) => {
    const last = c.sessions.at(-1);
    const hot = (active.get(c.symbol) || 0) >= 10;
    return `<button class="chip ${state.symbol === c.symbol ? "on" : ""} ${hot ? "hot" : ""}" data-action="symbol" data-sym="${esc(c.symbol)}">
      ${esc(c.symbol)} <span class="${tone(last?.change_pct)}">${pct(last?.change_pct)}</span></button>`;
  }).join("");
  return `<div class="pulse" role="toolbar" aria-label="Filter by company">
    <button class="chip ${state.symbol ? "" : "on"}" data-action="symbol" data-sym="">All 18</button>${chips}</div>`;
}

function portfolio() {
  const rows = feed.companies.map((c) => {
    const last = c.sessions.at(-1) || {};
    const vr = last.volume_ratio;
    return `<li><button data-action="symbol" data-sym="${esc(c.symbol)}">
      <span class="pf-name">${who(c.symbol)}</span>${spark(c.spark)}
      <span class="num">${last.close ? inr.format(last.close) : "–"}</span>
      <span class="num ${tone(last.change_pct)}">${pct(last.change_pct)}</span>
      <span class="num vol ${vr >= state.rules.volume_multiple ? "hot" : ""}">${vr ? vr.toFixed(1) + "×" : "–"}</span></button></li>`;
  }).join("");
  const lastDate = feed.companies[0]?.sessions.at(-1)?.date;
  return `<section><h2>Portfolio <span>close ${lastDate ? shortDate(parse(lastDate)) : ""} · 30-day trend · volume vs 20-day avg</span></h2>
    <ul class="pf">${rows}</ul></section>`;
}

function render() {
  const v = compute();
  const asOf = parse(feed.as_of);
  const n = v.open.length;
  const verdict = n
    ? `<b>${n} ${n === 1 ? "thing needs" : "things need"} you.</b>`
    : `<b>${v.cleared.length ? "All clear." : "Nothing needs you."}</b>`;
  const focus = state.symbol
    ? `<p class="focus">Showing ${esc(state.symbol)} only <button data-action="symbol" data-sym="">Show all</button></p>` : "";

  app.innerHTML = `
    <header class="top">
      <div class="brand"><span class="logo">FINN</span><span class="asof">as of ${shortDate(asOf)}, ${clock(asOf)}</span></div>
      <button class="rules-btn" data-action="rules" aria-label="Alert rules">
        <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><path d="M3 6h9M15 6h2M3 14h3M9 14h8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="13.5" cy="6" r="1.8" fill="none" stroke="currentColor" stroke-width="1.6"/><circle cx="7.5" cy="14" r="1.8" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>
        Rules</button>
    </header>
    <nav class="windows" aria-label="Time window">${WINDOWS.map((w) =>
      `<button class="${w.key === state.win ? "on" : ""}" data-action="win" data-win="${w.key}">${w.label}</button>`).join("")}</nav>
    <p class="verdict">${verdict} <span>${v.worth.length} worth a look · ${v.routine.length} routine, folded · ${v.total} filings in all</span></p>
    ${pulse(v)}
    ${focus}
    <section class="needs">
      <h2>Needs you <span>your rules: ${state.rules.volume_multiple}× volume · ±${state.rules.price_move_pct}% move · ${state.rules.alert_categories.length} filing types</span></h2>
      ${n ? v.open.map((x) => (x.kind === "move" ? moveCard(x) : filingCard(x))).join("")
        : `<p class="empty">${v.cleared.length ? "You've cleared everything that mattered in this window." : "Nothing crossed your rules in this window."}</p>`}
      ${v.cleared.length ? `<details class="cleared"><summary>${v.cleared.length} cleared</summary>
        ${v.cleared.map((x) => (x.kind === "move" ? moveCard(x, true) : filingCard(x, true))).join("")}</details>` : ""}
    </section>
    ${v.worth.length ? `<section><h2>Worth a look <span>one line each</span></h2><ul class="rows">${v.worth.map(row).join("")}</ul></section>` : ""}
    <section>${routineBlock(v.routine)}</section>
    ${portfolio()}
    <footer class="foot">Filings: NSE. Prices: Yahoo Finance end-of-day. Ranking is rule-based and runs free; no model reads your feed.</footer>`;
}

// ---------- rules sheet ----------

function renderSheet() {
  const r = state.rules;
  const cats = feed.alertable;
  sheet.innerHTML = `<div class="sheet-panel" role="dialog" aria-modal="true" aria-label="Alert rules">
    <header><h3>What counts as unusual</h3><button data-action="close" aria-label="Close">Done</button></header>
    <label class="slider"><span>Volume spike <b>${r.volume_multiple.toFixed(1)}×</b> the 20-day average</span>
      <input type="range" min="1.5" max="6" step="0.5" value="${r.volume_multiple}" data-rule="volume_multiple"></label>
    <label class="slider"><span>Price move <b>±${r.price_move_pct.toFixed(1)}%</b> in one day</span>
      <input type="range" min="1" max="10" step="0.5" value="${r.price_move_pct}" data-rule="price_move_pct"></label>
    <p class="sheet-label">Alert me on these filings</p>
    <div class="toggles">${cats.map((c) =>
      `<button class="${r.alert_categories.includes(c) ? "on" : ""}" data-action="cat" data-cat="${esc(c)}">${esc(LABEL[c] || c)}</button>`).join("")}</div>
    <p class="hint">Routine versions (a notice of a board meeting, an auditor appointment) stay out of alerts. Everything else still shows under "Worth a look".</p>
    <button class="reset" data-action="reset">Reset to defaults</button>
  </div>`;
}

function saveRules() {
  store.set("rules", state.rules);
  render();
  renderSheet();
}

// ---------- events ----------

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-action]");
  if (!el) {
    if (e.target === sheet) { sheet.hidden = true; }
    return;
  }
  const act = el.dataset.action;
  if (act === "win") { state.win = el.dataset.win; store.set("win", state.win); render(); }
  else if (act === "symbol") {
    state.symbol = el.dataset.sym && state.symbol !== el.dataset.sym ? el.dataset.sym : null;
    render(); window.scrollTo({ top: 0, behavior: "smooth" });
  } else if (act === "done" || act === "undo") {
    act === "done" ? state.done.add(el.dataset.key) : state.done.delete(el.dataset.key);
    store.set("done", [...state.done]); render();
  } else if (act === "rules") { renderSheet(); sheet.hidden = false; }
  else if (act === "close") { sheet.hidden = true; }
  else if (act === "cat") {
    const set = new Set(state.rules.alert_categories);
    set.has(el.dataset.cat) ? set.delete(el.dataset.cat) : set.add(el.dataset.cat);
    state.rules.alert_categories = feed.categories.filter((c) => set.has(c));
    saveRules();
  } else if (act === "reset") { state.rules = defaults(); saveRules(); }
});

sheet.addEventListener("input", (e) => {
  const key = e.target.dataset.rule;
  if (!key) return;
  state.rules[key] = parseFloat(e.target.value);
  store.set("rules", state.rules);
  render();
  e.target.previousElementSibling.querySelector("b").textContent =
    key === "volume_multiple" ? `${state.rules[key].toFixed(1)}×` : `±${state.rules[key].toFixed(1)}%`;
});

document.addEventListener("keydown", (e) => { if (e.key === "Escape") sheet.hidden = true; });

const defaults = () => ({
  volume_multiple: feed.defaults.volume_multiple,
  price_move_pct: feed.defaults.price_move_pct,
  alert_categories: [...feed.defaults.alert_categories],
});

async function main() {
  try {
    const res = await fetch("data/feed.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(res.status);
    feed = await res.json();
  } catch (err) {
    app.innerHTML = `<p class="loading">Couldn't load the portfolio data (${esc(err.message)}). Try reloading.</p>`;
    return;
  }
  state = {
    win: store.get("win", "24h"),
    symbol: null,
    rules: { ...defaults(), ...store.get("rules", {}) },
    done: new Set(store.get("done", [])),
  };
  render();
}

main();
