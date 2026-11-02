// FINN pull side: "promised vs delivered" over the last four earnings calls.
// The view leads with the verdict count, then the misses, because a missed
// promise is the thing an investor most needs to see and least likely to hear.

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const ORDER = ["missed", "partly", "dropped", "delivered", "pending"];
const VERDICT = {
  missed: "Missed", partly: "Partly", dropped: "Dropped", delivered: "Delivered", pending: "Pending",
};

let index = null;
const cache = new Map();

async function getJSON(url) {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(res.status);
  return res.json();
}

function scoreBar(c) {
  const settled = c.delivered + c.partly + c.missed;
  const total = settled + c.pending + c.dropped;
  const seg = (k) => (c[k] ? `<span class="seg ${k}" style="flex:${c[k]}" title="${VERDICT[k]} ${c[k]}"></span>` : "");
  const line = settled
    ? `<b>${c.delivered} of ${settled}</b> settled promises delivered${c.partly ? `, ${c.partly} partly` : ""}${c.missed ? `, <span class="missed-t">${c.missed} missed</span>` : ""}.`
    : "<b>No promise has come due yet.</b>";
  const rest = [c.pending ? `${c.pending} still open` : "", c.dropped ? `${c.dropped} quietly dropped` : ""].filter(Boolean).join(", ");
  return `<p class="score">${line}${rest ? ` <span>${rest}.</span>` : ""}</p>
    <div class="scorebar" aria-hidden="true">${ORDER.map(seg).join("")}</div>
    <p class="legend">${ORDER.filter((k) => c[k]).map((k) => `<span class="dot ${k}"></span>${VERDICT[k]} ${c[k]}`).join("")}</p>`;
}

function numbers(n) {
  // Reported revenue per quarter with margin underneath: the "numbers" the
  // narrative is judged against.
  const rev = n.rows.Sales || n.rows.Revenue;
  if (!rev) return "";
  const margin = n.rows["OPM %"] || n.rows["Financing Margin %"];
  const max = Math.max(...rev.filter((v) => v != null));
  const cols = n.periods.map((p, i) => {
    const h = rev[i] == null ? 0 : Math.max(4, (rev[i] / max) * 56);
    return `<div class="qcol"><span class="qv">${rev[i] == null ? "" : Math.round(rev[i]).toLocaleString("en-IN")}</span>
      <span class="qbar" style="height:${h.toFixed(0)}px"></span>
      <span class="qm">${margin && margin[i] != null ? margin[i] + "%" : ""}</span>
      <span class="ql">${esc(p.slice(0, 3))}<br>’${esc(p.slice(-2))}</span></div>`;
  }).join("");
  return `<section><h2>Reported numbers <span>revenue ₹ cr per quarter, ${margin === n.rows["OPM %"] ? "operating margin" : "margin"} below</span></h2>
    <div class="qchart">${cols}</div></section>`;
}

function target(p) {
  const u = p.unit === "%" ? "%" : ` ${p.unit || ""}`;
  const f = (v) => `${Number(v).toLocaleString("en-IN")}${u}`;
  const both = p.target_low != null && p.target_high != null;
  const t = p.direction === "within" && both ? `${f(p.target_low)} to ${f(p.target_high)}`
    : p.direction === "at_most" ? `≤ ${f(p.target_high ?? p.target_low)}` : `≥ ${f(p.target_low ?? p.target_high)}`;
  return { t, a: f(p.actual) };
}

function check(p) {
  if (p.verdict_by !== "numbers") return "";
  const { t, a } = target(p);
  return `<p class="p-check">Target ${esc(t)} · actual ${esc(a)}. Verdict set by the numbers${p.model_verdict ? `, not the model (it said “${esc(p.model_verdict)}”)` : ""}.</p>`;
}

function promise(p, calls) {
  const call = calls.find((c) => p.made_in.startsWith(c.quarter));
  const evCall = calls.find((c) => (p.evidence_from || "").startsWith(c.quarter));
  const link = (c, label) => (c ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(label || c.quarter + " transcript")} ↗</a>` : "");
  return `<li class="promise">
    <details>
      <summary>
        <span class="pill ${p.verdict}">${VERDICT[p.verdict]}</span>
        <span class="p-text"><b>${esc(p.promise)}</b>
          <span class="p-meta">Said in ${esc(p.made_in.replace(/ call$/, ""))}${p.horizon ? ` · for ${esc(p.horizon)}` : ""}</span>
          <span class="p-ev">→ ${p.model_verdict
            // The model's prose argued for its own verdict; when the numbers
            // overrule it, show the numbers instead.
            ? `Actual ${esc(target(p).a)} against ${esc(target(p).t)}.`
            : esc(p.evidence)}</span></span>
      </summary>
      <div class="p-body">
        ${check(p)}
        <blockquote>“${esc(p.quote)}”<cite>${link(call, (call ? call.quarter : "") + " call")}</cite></blockquote>
        ${p.evidence_quote ? `<blockquote class="ev">“${esc(p.evidence_quote)}”<cite>${link(evCall, (evCall ? evCall.quarter : "") + " call")}</cite></blockquote>`
          : `<p class="p-src">Evidence: ${esc(p.evidence_from)}</p>`}
      </div>
    </details></li>`;
}

function shifts(list) {
  if (!list.length) return "";
  return `<section><h2>Where the story moved</h2><ul class="shifts">${list.map((s) => `<li>
    <p class="s-topic">${esc(s.topic)} <span>${esc(s.from_quarter.replace(/ call$/, ""))} → ${esc(s.to_quarter.replace(/ call$/, ""))}</span></p>
    <p>${esc(s.change)}</p></li>`).join("")}</ul></section>`;
}

function provenance(r) {
  const unverified = r.calls.reduce((n, c) => n + c.dropped_unverified, 0) + (r.dropped_from_review || 0);
  const tokens = r.usage.reduce((n, u) => n + u.input_tokens + u.output_tokens, 0);
  const models = [...new Set(r.usage.map((u) => u.model.replace("gemini-", "")))].join(", ");
  return `<footer class="prov">
    <p><b>Sources:</b> ${r.calls.map((c) => `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.quarter)} call</a>`).join(" · ")}, and the filed quarterly results. No news, broker notes or outside knowledge.</p>
    <p>Every quote is checked word for word against the transcript. ${unverified ? `${unverified} model claim${unverified > 1 ? "s were" : " was"} dropped because the quote wasn't there.` : "All quotes checked out."}</p>
    <p>${r.usage.length} model calls (${esc(models)}), ${Math.round(tokens / 1000)}k tokens.</p></footer>`;
}

function picker(current) {
  const chips = (index || []).map((r) =>
    `<a class="chip ${r.symbol === current ? "on" : ""}" href="#research/${esc(r.symbol)}">${esc(r.symbol)}</a>`).join("");
  return `<div class="pulse">${chips}</div>
    <form class="ask" data-form="ticker"><input name="sym" placeholder="Any NSE ticker, e.g. TITAN" autocapitalize="characters"
      autocomplete="off" spellcheck="false" aria-label="NSE ticker"><button>Check</button></form>`;
}

export async function renderResearch(app, symbol) {
  try {
    index = index || await getJSON("data/research/index.json");
  } catch {
    index = [];
  }
  symbol = (symbol || index[0]?.symbol || "").toUpperCase();
  const head = `<header class="top"><div class="brand"><span class="logo">FINN</span><span class="asof">research</span></div></header>
    <p class="verdict"><b>Promised vs delivered.</b> <span>Last four earnings calls against what the company then reported. Primary sources only.</span></p>`;
  if (!symbol) {
    app.innerHTML = `${head}${picker("")}<p class="empty">No company analysed yet.</p>`;
    return;
  }
  app.innerHTML = `${head}${picker(symbol)}<p class="loading">Reading ${esc(symbol)}…</p>`;
  let r = cache.get(symbol);
  if (!r) {
    try {
      r = await getJSON(`data/research/${encodeURIComponent(symbol)}.json`);
    } catch {
      // Not prepared in advance: read its four calls now. Slow the first
      // time (about a minute); the server keeps the answer for a day.
      app.innerHTML = `${head}${picker(symbol)}<div class="empty working"><p><b>Reading ${esc(symbol)}'s last four earnings calls…</b></p>
        <p>First look takes about a minute: fetch the transcripts, pull out every piece of guidance, check each quote, then compare with what was reported.</p></div>`;
      try {
        const res = await fetch(`api/research?symbol=${encodeURIComponent(symbol)}`);
        const body = await res.json();
        if (!res.ok) throw new Error(body.error || res.status);
        r = body;
      } catch (err) {
        if (location.hash.split("/")[1]?.toUpperCase() !== symbol) return;  // user moved on
        app.innerHTML = `${head}${picker(symbol)}<div class="empty"><p><b>Couldn't analyse ${esc(symbol)}.</b></p>
          <p>${esc(err.message)}</p><p>It needs an NSE symbol with concall transcripts on screener.in.</p></div>`;
        return;
      }
    }
    cache.set(symbol, r);
  }
  if (location.hash.split("/")[1]?.toUpperCase() !== symbol && location.hash !== "#research") return;
  const sorted = [...r.promises].sort((a, b) => ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict));
  app.innerHTML = `${head}${picker(symbol)}
    <section class="research">
      <h1 class="r-sym">${esc(r.symbol)}</h1>
      ${scoreBar(r.counts)}
      <p class="r-head">${esc(r.headline)}</p>
    </section>
    <section><h2>Promises <span>tap one for the exact words and the source</span></h2>
      <ul class="promises">${sorted.map((p) => promise(p, r.calls)).join("")}</ul></section>
    ${shifts(r.shifts)}
    ${numbers(r.numbers)}
    ${provenance(r)}`;
}
