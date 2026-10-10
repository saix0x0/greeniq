// GreenIQ web app — no build step. Every number shown comes from the API (ComputedFacts and
// portfolio aggregates computed on the server); this file only formats and draws.
//
// Two views, as PS2 asks: ONE HOME answers the brief's four questions (how green is it, what to
// improve, how much energy and carbon could be saved, could it increase the value) plus what-ifs;
// MANY HOMES compares homes and groups of homes on every PS2 dimension. "How it works" shows each
// formula from the brief with the parameters we use.

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (x, d = 0) => (x == null || Number.isNaN(x) ? "—" : Number(x).toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d }));
const gbp = (x) => (x == null ? "—" : "£" + fmt(x));
const nice = (s) => String(s ?? "").replaceAll("_", " ");
const cap = (s) => { s = nice(s); return s.charAt(0).toUpperCase() + s.slice(1); };
const signed = (x, d = 0) => (x == null ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + fmt(Math.abs(x), d));

// ---------- settings (per-viewer conveniences only) ----------
const store = {
  get(k, d) { try { const v = localStorage.getItem("greeniq." + k); return v == null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("greeniq." + k, v); } catch { /* private mode */ } },
};
// mode "evidence" = evidence labels written out; "demo" = coloured dots (the calmer default)
const S = { mode: store.get("labels", "demo"), objective: store.get("objective", "value_for_money"), theme: store.get("theme", "system") };
function applyTheme() { if (S.theme === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = S.theme; }
applyTheme();

// ---------- API ----------
async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data?.error?.message || `HTTP ${res.status}`), { status: res.status });
  return data;
}
const cache = {};
const once = (k, f) => (cache[k] ??= f().catch((e) => { delete cache[k]; throw e; }));

// ---------- evidence tags & receipts ----------
const BASIS = {
  observed: ["m", "measured"], metered: ["m", "metered"], derived: ["m", "derived"], zero: ["m", "metered: zero"],
  assumed: ["a", "assumed"], estimated: ["e", "estimate"], estimate: ["e", "estimate"], not_applicable: ["a", "n/a"],
  missing: ["u", "unavailable"], unavailable: ["u", "unavailable"], synthetic: ["e", "synthetic"],
  complete: ["m", "complete"], provisional: ["e", "provisional"], partial: ["u", "partial"],
};
function tag(basis, note) {
  const [c, l] = BASIS[basis] || ["a", nice(basis)];
  const title = esc(l + (note ? " · " + note : ""));
  return S.mode === "evidence" ? `<span class="tag ${c}" title="${title}">${esc(l)}</span>` : `<span class="dot ${c}" title="${title}"></span>`;
}
const RECEIPTS = new Map();
let rid = 0;
function rc(receipt, html) {
  if (!receipt) return html;
  const id = "r" + ++rid;
  RECEIPTS.set(id, receipt);
  return `<span class="rcpt" data-r="${id}" title="How was this worked out?">${html}</span>`;
}
function receiptHtml(r) {
  const val = typeof r.value === "number" ? fmt(r.value, Math.abs(r.value) < 10 ? 2 : 0) : JSON.stringify(r.value);
  const show = (v) => (v != null && typeof v === "object" ? `<pre>${esc(JSON.stringify(v, null, 2))}</pre>`
    : esc(typeof v === "number" ? fmt(v, Math.abs(v) < 1 && v % 1 ? 3 : Math.abs(v) < 100 && v % 1 ? 1 : 0) : v));
  const inputs = Object.entries(r.inputs || {}).map(([k, v]) => `<dt>${esc(cap(k))}</dt><dd class="num">${show(v)}</dd>`).join("");
  return `<div class="evi-title">${esc(r.output.split(".").map(cap).join(" › "))}</div>
    <div class="evi-value num">${esc(val)} <small>${esc(r.unit || "")}</small></div>
    <h4>How it was worked out</h4><p class="evi-method">${esc(r.method)}</p>
    ${inputs ? `<h4>Using</h4><dl class="kv">${inputs}</dl>` : ""}
    ${r.sources?.filter(Boolean).length ? `<h4>Sources</h4><ul class="small">${r.sources.filter(Boolean).map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
    ${r.notes?.length ? `<h4>Notes</h4><ul class="small">${r.notes.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
    <p class="small muted">Worked out by ${esc(r.provider || "deterministic code")} · <code>${esc(r.method_version)}</code></p>`;
}
let eviHome = null; // () => overview html for the open home
function openReceipt(r) {
  const pane = $("#evi");
  if (pane) {
    pane.innerHTML = `<div class="evi-head"><button class="linkbtn" id="evi-back">← Back to this home's evidence</button><button class="linkbtn evi-x" id="evi-x" aria-label="Close">✕</button></div>${receiptHtml(r)}`;
    pane.classList.add("on");
    pane.scrollTop = 0;
    return;
  }
  const d = $("#drawer");
  d.innerHTML = `<div class="evi-head"><b>How it was worked out</b><button class="linkbtn" id="drawer-x">Close ✕</button></div>${receiptHtml(r)}`;
  d.classList.add("on");
}
function eviReset() { const p = $("#evi"); if (p && eviHome) p.innerHTML = eviHome(); }
document.addEventListener("click", (e) => {
  const r = e.target.closest(".rcpt");
  if (r) { document.querySelectorAll(".rcpt.sel").forEach((x) => x.classList.remove("sel")); r.classList.add("sel"); openReceipt(RECEIPTS.get(r.dataset.r)); return; }
  if (e.target.closest("#evi-back")) { eviReset(); document.querySelectorAll(".rcpt.sel").forEach((x) => x.classList.remove("sel")); return; }
  if (e.target.closest("#evi-x")) { $("#evi").classList.remove("on"); eviReset(); return; }
  if (e.target.closest("#drawer-x")) $("#drawer").classList.remove("on");
  if (!e.target.closest("#menu, #menu-btn")) closeMenu();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { $("#drawer").classList.remove("on"); $("#evi")?.classList.remove("on"); closeMenu(); } });

// ---------- tooltip ----------
const tip = $("#tip");
document.addEventListener("mousemove", (e) => {
  const t = e.target.closest?.("[data-tip]");
  if (!t) { tip.classList.remove("on"); return; }
  tip.innerHTML = t.dataset.tip;
  tip.classList.add("on");
  tip.style.left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8) + "px";
  tip.style.top = Math.max(e.clientY - tip.offsetHeight - 10, 8) + "px";
});

// ---------- top bar: search + settings ----------
function closeMenu() { $("#menu").hidden = true; $("#menu-btn").setAttribute("aria-expanded", "false"); }
$("#menu-btn").onclick = () => { const m = $("#menu"); m.hidden = !m.hidden; $("#menu-btn").setAttribute("aria-expanded", String(!m.hidden)); };
function syncSettings() {
  $("#src-switch").setAttribute("aria-checked", String(S.mode === "evidence"));
  $("#obj").value = S.objective;
  $("#theme").value = S.theme;
  document.body.classList.toggle("demo", S.mode !== "evidence");
}
$("#src-switch").onclick = (e) => { e.preventDefault(); S.mode = S.mode === "evidence" ? "demo" : "evidence"; store.set("labels", S.mode); syncSettings(); route(); };
$("#obj").onchange = (e) => { S.objective = e.target.value; store.set("objective", S.objective); route(); };
$("#theme").onchange = (e) => { S.theme = e.target.value; store.set("theme", S.theme); applyTheme(); route(); };
syncSettings();
function homeRef(q) {
  q = q.trim().toUpperCase();
  return /^P?\d{1,5}$/.test(q) ? "P" + q.replace(/^P/, "").padStart(5, "0") : null;
}
function goFind(q) {
  if (!q.trim()) return;
  const id = homeRef(q);
  location.hash = id ? "#/home/" + id : "#/homes?tab=all&q=" + encodeURIComponent(q.trim());
}
$("#find").addEventListener("submit", (e) => { e.preventDefault(); goFind($("#find-q").value); $("#find-q").blur(); });

// ---------- shared vocabulary ----------
const BANDS = ["Very poor", "Poor", "Moderate", "Good", "Highly efficient"];
const BAND_VAR = { "Very poor": "--b-vp", Poor: "--b-p", Moderate: "--b-m", Good: "--b-g", "Highly efficient": "--b-he", Undetermined: "--b-u" };
const bandColor = (b) => `var(${BAND_VAR[b] || "--b-u"})`;
const darkText = (b) => ["Good", "Highly efficient", "Moderate"].includes(b) && !matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "dark";
function scoreDot(score, band) {
  const fg = darkText(band) ? "#fff" : "var(--ink)";
  return `<span class="score-dot" style="background:${bandColor(band)};color:${fg}" data-tip="${esc(band || "band not certain yet")}">${score ?? "?"}</span>`;
}
const bandBadge = (b) => `<span class="badge"><span class="band-sw" style="background:${bandColor(b)}"></span>${esc(b || "Not certain yet")}</span>`;
const DISP = { recommend: "Ready to act", refer_for_survey: "Check first", no_action: "Nothing needed" };
const disp = (d) => `<span class="disp ${d}">${DISP[d] || d}</span>`;
function fuelChange(saving, cls, name, d = 0) {
  if (saving == null) return `<span class="fuel ${cls}">${name} —</span>`;
  const ch = -saving;
  const arrow = ch > 0 ? "▲" : ch < 0 ? "▼" : "";
  return `<span class="fuel ${cls}">${name} <span class="${ch > 0 ? "up" : ch < 0 ? "down" : ""}">${arrow} ${fmt(Math.abs(ch), d)}</span></span>`;
}
// a saving shown the PS2 way: positive = less use, negative = more use (an increase is a negative saving)
// a value range with its own signs: "+1.9% to +4.7%", "−3.4% to +1.9%"
const pctRange = (lo, hi) => `${signed(lo, 1)}% to ${signed(hi, 1)}%`;
const saveCell = (s, d = 0) => (s == null ? "—" : `<span class="${s > 0 ? "down" : s < 0 ? "up" : ""}">${signed(s, d)}</span>`);
function pagehead(title, sub, right = "") {
  return `<div class="pagehead"><div><h1>${title}</h1>${sub ? `<div class="sub">${sub}</div>` : ""}</div>${right}</div>`;
}
const synthNote = `<span class="pill-note" title="Homes, meters and sales are simulated (data/DATA_CARD.md). Peer comparisons and retrofit evidence come from real UK homes (DESNZ NEED, Open Government Licence).">Simulated homes · real-home checks · estimates labelled</span>`;
const TYPE = { detached: "Detached house", semi_detached: "Semi-detached house", terraced: "Terraced house", bungalow: "Bungalow", flat: "Flat" };
const typeName = (t) => TYPE[t] || cap(t);
const HEAT = { gas_boiler_condensing: "Condensing gas boiler", gas_boiler_noncondensing: "Older gas boiler", electric_storage: "Storage heaters",
  electric_direct: "Direct electric", air_source_heat_pump: "Air source heat pump", ground_source_heat_pump: "Ground source heat pump" };
function ageName(a) {
  if (!a) return "";
  let m = a.match(/^pre_(\d{4})$/); if (m) return "built before " + m[1];
  m = a.match(/^(\d{4})_(\d{4})$/); if (m) return `built ${m[1]}–${m[2]}`;
  m = a.match(/^post_(\d{4})$/); if (m) return `built after ${m[1]}`;
  return "built " + nice(a);
}
function groupName(by, g) {
  if (by === "property_type") return typeName(g);
  if (by === "heating_system") return HEAT[g] || cap(g);
  if (by === "age_band") return cap(ageName(g));
  if (by === "epc_band") return g === "unknown" ? "No EPC" : "EPC " + g;
  if (by === "baseline_basis") return { metered: "Meter readings", estimated: "Estimated (few readings)", unavailable: "No energy data" }[g] || cap(g);
  return cap(g);
}
function describe(ps) {
  return [typeName(ps.property_type) + (ps.flat_position ? ` (${nice(ps.flat_position)} floor)` : ""), cap(ps.region), ageName(ps.age_band),
    ps.floor_area_m2 ? fmt(ps.floor_area_m2) + " m²" : ""].filter(Boolean).join(" · ");
}
function recent() { try { return JSON.parse(store.get("recent", "[]")); } catch { return []; } }
function remember(f) {
  const r = recent().filter((x) => x.id !== f.property_id);
  r.unshift({ id: f.property_id, label: describe(f.property_summary) });
  store.set("recent", JSON.stringify(r.slice(0, 5)));
}
function tabs(sel, onPick) {
  const el = $(sel);
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]");
    if (!b) return;
    el.querySelectorAll("button[data-v]").forEach((x) => x.classList.toggle("on", x === b));
    onPick(b.dataset.v);
  });
}
const bar = (pct, cls = "") => `<span class="mbar ${cls}"><span style="width:${Math.max(0, Math.min(100, pct || 0))}%"></span></span>`;

// ---------- router ----------
let token = 0;
const ROUTES = {
  "": start, home: (m, id, live, qs) => (id ? home(m, id, live, qs) : start(m, id, live)), homes, compare, how,
  // older addresses keep working
  property: (m, id) => location.replace("#/home/" + (id || "")),
  lab: (m, id) => location.replace("#/home/" + (id || "") + "?tab=whatif"),
  properties: () => location.replace("#/homes?tab=all"),
  analytics: () => location.replace("#/how#quality"), evidence: () => location.replace("#/how"),
  settings: () => { location.replace("#/"); setTimeout(() => $("#menu-btn").click(), 0); },
};
async function route() {
  const [, page0 = "", arg] = location.hash.split("?")[0].split("/");
  const page = page0.split("#")[0]; // "#/how#quality" → page "how", anchor handled by the page
  const qs = new URLSearchParams(location.hash.split("?")[1] || "");
  const fn = ROUTES[page] || start;
  const nav = page === "" ? "home" : page === "compare" ? "homes" : page;
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === nav));
  const my = ++token;
  const main = $("#main");
  RECEIPTS.clear();
  eviHome = null;
  $("#drawer").classList.remove("on");
  main.innerHTML = `<div class="loading">Loading…</div>`;
  try { await fn(main, arg ? decodeURIComponent(arg) : undefined, () => my === token, qs); }
  catch (e) { if (my === token) main.innerHTML = errorPage(e, page, arg); }
}
function errorPage(e, page, arg) {
  if (page === "home" && e.status === 404) {
    return `<div class="landing"><div class="landing-card"><h1>We couldn't find “${esc(arg)}”.</h1>
      <p>Home references look like the ones in the list of homes. You can also search by region or type.</p>
      <p><a class="nav-btn primary" href="#/homes?tab=all&q=${encodeURIComponent(arg || "")}">Search all homes</a> <a class="nav-btn" href="#/">Start again</a></p></div></div>`;
  }
  return `<div class="page"><div class="err">${esc(e.message)}</div></div>`;
}
addEventListener("hashchange", route);
queueMicrotask(route);

// =====================================================================================
// Start — "Check a home."
// =====================================================================================
async function start(main, _a, live) {
  const rec = recent();
  main.innerHTML = `<div class="landing"><div class="landing-card">
    <h1>Check a home.</h1>
    <p>Open a home to see <b>how green it is today</b>, <b>what to improve</b> (and what to do first), <b>how much energy and carbon</b>
      it could save, and <b>whether that could change its value</b>. Every figure links to how it was worked out.</p>
    <form class="bigfind" id="bigfind"><input id="bigfind-q" placeholder="Home reference" autocomplete="off" aria-label="Home reference">
      <button class="nav-btn primary" type="submit">Open this home</button></form>
    <div class="examples"><small class="muted">Or start from one of these (picked live from the data):</small><div id="ex"><div class="loading small">Finding examples…</div></div></div>
    ${rec.length ? `<div class="examples"><small class="muted">You recently opened:</small><div>${rec.map((r) =>
      `<a class="existing-btn" href="#/home/${esc(r.id)}"><b>${esc(r.id)}</b><span class="muted">${esc(r.label)}</span></a>`).join("")}</div></div>` : ""}
    <p class="fine muted">Looking after many homes? <a href="#/homes">Compare them all</a> — ranked by how much each could improve, grouped by region, type, age, heating and more.</p>
  </div></div>`;
  $("#bigfind").addEventListener("submit", (e) => { e.preventDefault(); goFind($("#bigfind-q").value); });
  const [p, survey, good] = await Promise.all([
    once("portfolio", () => api("/api/portfolio")),
    api("/api/properties?disposition=refer_for_survey&limit=1").catch(() => null),
    api("/api/properties?band=Good&disposition=recommend&sort=potential&limit=1").catch(() => null),
  ]);
  if (!live()) return;
  const ex = [[p.ranking.top[0], "Biggest improvement potential of all poor homes"],
    [survey?.items[0], "Needs a check before we can advise"], [good?.items[0], "Already in good shape — one step left"]].filter(([x]) => x);
  $("#ex").innerHTML = ex.map(([x, why]) => `<a class="existing-btn" href="#/home/${x.property_id}">${scoreDot(x.score ?? (x.score_range ? x.score_range.join("–") : "?"), x.band)}
    <span><b>${x.property_id}</b> · ${esc(typeName(x.property_type))}, ${esc(cap(x.region))}<br><span class="muted">${esc(why)}</span></span></a>`).join("");
}

// =====================================================================================
// ONE HOME — a case file: identity and data quality → decision strip → five PS2 tabs; evidence pane
// =====================================================================================
async function loadFacts(id) {
  if (S.objective === "value_for_money") return api(`/api/properties/${encodeURIComponent(id)}`);
  return api(`/api/properties/${encodeURIComponent(id)}/scenarios`, { objective: S.objective, name: "Recommended package" });
}
const TIER_FALLBACK = { act_now: "Act now", check_first: "Check first", worth_doing: "Worth doing", no_action: "No action now" };
const issueText = (i) => i.text.replace(/\s*\([^()]*points available\)\s*$/, "");
const HOME_TABS = [["score", "Green Home Score"], ["improve", "Improvements"], ["savings", "Energy & carbon"], ["value", "Property value"], ["whatif", "What if…"]];
const objName = () => ({ value_for_money: "value for money (CO₂e saved per £)", carbon: "the most CO₂e saved", energy: "the most energy saved" }[S.objective]);

async function home(main, id, live, qs) {
  const [{ facts: f, explanation }, rowRes, stand, p] = await Promise.all([
    loadFacts(id), api(`/api/properties?ids=${encodeURIComponent(id)}&limit=1`).catch(() => null),
    api(`/api/properties/${encodeURIComponent(id)}/standing`).catch(() => null), once("portfolio", () => api("/api/portfolio"))]);
  if (!live()) return;
  remember(f);
  const row = rowRes?.items?.[0] || {};
  const tierInfo = (p.tiers || []).find((t) => t.key === row.tier) || { key: row.tier, label: TIER_FALLBACK[row.tier] || "—", meaning: "" };
  const s = f.score, n = f.next_best_action, pk = f.package, v = f.value, ps = f.property_summary;
  const lead = n?.action?.kind === "retrofit" ? f.plan.find((r) => r.measure_id === n.action.ref) : null;
  const refer = f.excluded.filter((e) => e.status === "needs_survey");
  const flags = [
    ...f.conflicts.map((c) => ["bad", "Records disagree: " + c.message]),
    ...(f.baseline_basis !== "metered" ? [["warn", f.baseline_basis === "estimated" ? "Energy use is estimated (too few meter readings)" : "No energy data"]] : []),
    ...(s.score == null ? [["warn", "Score is a range: an input is missing"]] : []),
    ...(refer.length ? [["warn", `${refer.length} upgrade${refer.length > 1 ? "s" : ""} need a check before we can advise`]] : []),
    ...(f.questions.length ? [["info", `${f.questions.length} question${f.questions.length > 1 ? "s" : ""} would make the result more certain`]] : []),
  ];
  const ip = pk?.improvement_potential;
  const stdTxt = stand?.available && stand.similar?.percentile != null
    ? `Scores higher than ${fmt(stand.similar.percentile)}% of ${fmt(stand.similar.homes)} similar homes in this portfolio` : "";
  const chip = (label, basis, note) => `<span class="dq">${label} ${tag(basis, note)}</span>`;
  let tab = HOME_TABS.some((t) => t[0] === qs.get("tab")) ? qs.get("tab") : "score";

  main.innerHTML = `<div class="layout">
    <section class="left">
      <div class="case-id">
        <div><h1>${esc(f.property_id)}</h1><div class="sub">${esc(describe(ps))} · ${esc(HEAT[ps.heating_system_recorded] || "heating not recorded")}</div></div>
        <div class="dqs">${chip("Energy use", f.baseline_basis === "metered" ? "metered" : f.baseline_basis)}${chip("Energy rating", ps.epc_band_recorded ? "observed" : "estimated", ps.epc_band_recorded ? "EPC on record" : "no EPC: estimated")}${chip("Score inputs", s.status)}</div>
      </div>
      <div class="dstrip">
        <div class="dcell"><small>Green Home Score</small>
          <div class="big-score">${s.score != null ? `${rc(s.receipt, s.score)}<span>/100</span>` : `${s.score_range[0]}–${s.score_range[1]}<span> possible</span>`}</div>
          ${bandBadge(s.band)} ${s.is_poor ? `<span class="flag bad">Poor efficiency</span>` : ""}
          ${stdTxt ? `<div class="tiny">${esc(stdTxt)}</div>` : ""}</div>
        <div class="dcell tier ${esc(tierInfo.key || "")}"><small>Priority</small><b>${esc(tierInfo.label)}</b><div class="tiny">${esc(tierInfo.meaning)}</div></div>
        <div class="dcell nba"><small>Next best action ${n ? disp(n.disposition) : ""}</small>
          <b>${esc(n?.action?.kind === "retrofit" ? n.action.label : n?.headline || "—")}</b>
          ${lead ? `<div class="tiny num">${rc(lead.receipt, `${gbp(lead.cost_low)}–${gbp(lead.cost_high)}`)} · saves ${fmt(lead.standalone.carbon.total_tonnes, 2)} t CO₂e a year · confidence ${esc(n.confidence)}</div>` : n ? `<div class="tiny">confidence ${esc(n.confidence)}</div>` : ""}
          <button class="linkbtn" data-goto="improve">Why this, and what else was considered →</button></div>
        <div class="dcell"><small>Before you act</small>
          ${flags.length ? `<ul class="flags">${flags.map(([c, t]) => `<li class="${c}">${esc(t)}</li>`).join("")}</ul>` : `<div class="tiny">No open questions: the key facts are on record.</div>`}</div>
      </div>
      ${pk ? `<div class="outcome"><small>If the whole plan (${pk.measures.length} upgrade${pk.measures.length > 1 ? "s" : ""}) is done</small>
        <button data-goto="score">Score <b>${s.score ?? "?"} → ${pk.score_after ?? "?"}</b> ${esc(pk.band_after || "")}</button>
        <button data-goto="savings">Energy bought <b>${ip?.status === "available" ? "−" + fmt(ip.pct, 0) + "%" : "n/a"}</b></button>
        <button data-goto="savings">CO₂e <b>−${fmt(pk.impact.carbon.total_tonnes, 2)} t</b> a year</button>
        <button data-goto="improve">Cost <b>${gbp(pk.cost_low)}–${gbp(pk.cost_high)}</b></button>
        <button data-goto="value">Value <b>${v?.uplift_pct_range && v.uplift_pct_range[1] ? `${pctRange(v.uplift_pct_range[0], v.uplift_pct_range[1])}` : "no change"}</b> <span class="muted">indicative</span></button></div>` : ""}
      <div class="toolbar"><button class="tool-btn" id="print">⬇ Download report</button><button class="tool-btn" id="cmp">⇄ Compare with other homes</button><button class="tool-btn" id="copy">🔗 Copy link</button></div>
      <nav class="mtabs" id="mtabs" role="tablist">${HOME_TABS.map(([k, l]) => `<button role="tab" data-v="${k}" class="${k === tab ? "on" : ""}">${l}</button>`).join("")}</nav>
      <div class="panel" id="panel"></div>
    </section>
    <aside class="right evi" id="evi" aria-label="How the numbers were worked out"></aside>
  </div>`;
  eviHome = () => eviOverview(f, explanation);
  eviReset();
  const show = (k) => {
    tab = k;
    main.querySelectorAll("#mtabs button").forEach((x) => x.classList.toggle("on", x.dataset.v === k));
    history.replaceState(null, "", `#/home/${f.property_id}${k === "score" ? "" : "?tab=" + k}`);
    const el = $("#panel");
    el.innerHTML = "";
    ({ score: tabScore, improve: tabImprove, savings: tabSavings, value: tabValue, whatif: tabWhatIf })[k](el, f, explanation, live, stand);
  };
  tabs("#mtabs", show);
  main.addEventListener("click", (e) => {
    const g = e.target.closest("[data-goto]");
    if (g) { e.preventDefault(); show(g.dataset.goto); $("#mtabs").scrollIntoView({ behavior: "smooth", block: "start" }); }
  });
  $("#print").onclick = () => print();
  $("#cmp").onclick = () => { picked.add(f.property_id); location.hash = "#/homes?tab=list"; };
  $("#copy").onclick = async (e) => { try { await navigator.clipboard.writeText(location.href); e.target.textContent = "✓ Link copied"; } catch { e.target.textContent = location.href; } };
  show(tab);
}

function eviOverview(f, ex) {
  const s = f.score, c = f.confidence, p = f.peer, ps = f.property_summary;
  const bases = { metered: "Meter readings, corrected for weather", estimated: "Estimated from the home's features (too few meter readings)" };
  return `<div class="evi-head"><b>Evidence</b><button class="linkbtn evi-x" id="evi-x" aria-label="Close">✕</button></div>
    <p class="evi-hint">Click any <span class="rcpt">underlined number</span> to see exactly how it was worked out: inputs, formula and source.</p>
    <h4>This home's data</h4>
    <dl class="kv">
      <dt>Energy use</dt><dd>${esc(bases[f.baseline_basis] || cap(f.baseline_basis))} ${tag(f.baseline_basis)}</dd>
      <dt>Energy rating</dt><dd>${ps.epc_band_recorded ? `EPC ${esc(ps.epc_band_recorded)}${ps.epc_year ? " (" + esc(ps.epc_year) + ")" : ""} on record` : "No EPC on record — estimated"}</dd>
      <dt>Score</dt><dd>${s.status === "complete" ? "Every part from recorded data" : s.score == null ? "A range: an input is missing" : `${s.estimated_components.length + s.missing_components.length} of 7 parts use assumed inputs`} ${tag(s.status)}</dd>
      <dt>Confidence</dt><dd><b>${esc(cap(c.level))}</b>${c.reasons.length ? `<div class="small muted">${c.reasons.map(esc).join(" ")}</div>` : ""}</dd>
      ${p ? `<dt>Real-home check</dt><dd>${fmt(Math.max(...p.fuels.map((x) => x.n_peers)))} real ${esc(p.peer_group)} homes <span class="badge">DESNZ NEED</span></dd>` : ""}
      <dt>Savings model</dt><dd class="small">${esc(f.providers_used?.savings_calibration || "engineering model")}</dd>
    </dl>
    <h4>EPC rating vs Green Home Score</h4>
    <p class="small">The <b>EPC rating</b> is an official certificate from a standard assessment (letter A–G). The <b>Green Home Score</b> is ours: it combines that rating (25%) with this home's actual energy use and six other parts, as the brief specifies.</p>
    <h4>Labels</h4>
    <div class="legend col">${[["m", "measured", "from records or meters"], ["e", "estimate", "modelled; not a guarantee"],
      ["a", "assumed", "a typical value, because it wasn't recorded"], ["u", "unavailable", "missing; we don't guess"]]
      .map(([c2, l, d]) => `<span>${S.mode === "evidence" ? `<span class="tag ${c2}">${l}</span>` : `<span class="dot ${c2}"></span> <b>${l}</b>`} ${d}</span>`).join("")}</div>
    <p class="fine">${synthNote}</p>`;
}

// ---- the AI explanation card: the model explains, the engine's facts are the only source ----
const providerLabel = (pr) => (pr?.name === "anthropic" ? `Claude (${esc(pr.detail.split(" ")[0])})` : pr?.name === "ollama" ? `Ollama (${esc(pr.detail.split(" ")[0])})`
  : pr?.name === "openai_compatible" ? `Local model (${esc(pr.detail.split(" ")[0])})` : "no AI model configured");
function aiCard(title) {
  return `<div class="ai-card" aria-live="polite"><div class="ai-head"><span class="ai-mark">AI</span><b>${title}</b><span class="ai-src" data-ai-src>asking…</span></div><div data-ai-body><div class="loading small">Writing an explanation from the computed facts…</div></div></div>`;
}
async function loadAI(el, f, scope, live) {
  const box = el.querySelector(".ai-card");
  if (!box) return;
  try {
    const r = await api(`/api/properties/${encodeURIComponent(f.property_id)}/explain?scope=${scope}&objective=${S.objective}`);
    if (!live() || !box.isConnected) return;
    const ex = r.explanation, llm = ex.mode === "llm";
    box.classList.toggle("template", !llm);
    box.querySelector("[data-ai-src]").innerHTML = llm ? `Written by ${providerLabel(r.provider)} · <span class="ok">✓ every figure checked against the engine</span>`
      : `Plain-language summary from a fixed template · ${esc(r.provider.name === "off" ? r.provider.detail : (ex.note || ""))}`;
    box.querySelector("[data-ai-body]").innerHTML = ex.sentences.map((x, i) => `<p ${i > 3 ? "hidden data-more" : ""}>${esc(x.text)}${S.mode === "evidence" && x.refs.length ? ` <span class="ref" style="display:inline">← ${esc(x.refs.join(", "))}</span>` : ""}</p>`).join("")
      + (ex.sentences.length > 4 ? `<button class="linkbtn" data-more-btn>Read the rest (${ex.sentences.length - 4} more)</button>` : "");
    box.querySelector("[data-more-btn]")?.addEventListener("click", (e) => { box.querySelectorAll("[data-more]").forEach((p) => (p.hidden = false)); e.target.remove(); });
  } catch (e) { if (box.isConnected) box.querySelector("[data-ai-body]").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
}

// ---- 1 · Green Home Score (PS2 §2) and the poor-efficiency check (§3) ----
function tabScore(el, f, ex, live, stand) {
  const s = f.score;
  const pos = s.score ?? (s.score_range ? (s.score_range[0] + s.score_range[1]) / 2 : null);
  const scale = `<div class="bandscale">${[["Very poor", 0, 29], ["Poor", 30, 49], ["Moderate", 50, 64], ["Good", 65, 79], ["Highly efficient", 80, 100]]
    .map(([bn, lo, hi]) => `<div style="flex:${hi - lo + 1};background:${bandColor(bn)}" class="${bn === s.band ? "here" : ""} ${["Good", "Highly efficient"].includes(bn) ? "dark" : ""}"><span>${bn}</span><small>${lo}–${hi}</small></div>`).join("")}
    ${pos != null ? `<i class="marker" style="left:${pos}%"><b>${s.score ?? s.score_range.join("–")}</b></i>` : ""}</div>`;
  const rows = s.components.map((c) => `<tr>
      <td><b>${esc(c.label)}</b><div class="small muted">${esc(c.input_display)}</div></td>
      <td class="num">${fmt(c.weight * 100)}%</td>
      <td class="num">${c.sub_score == null ? "—" : rc(c.receipt, fmt(c.sub_score, 0))}<span class="muted">/100</span> ${tag(c.basis)}</td>
      <td class="num"><b>${c.contribution == null ? "—" : fmt(c.contribution, 1)}</b><span class="muted"> of ${fmt(c.weight * 100)}</span>
        <div>${bar(c.contribution == null ? 0 : (100 * c.contribution) / (c.weight * 100))}</div></td>
      <td class="num">${c.points_available == null ? "—" : fmt(c.points_available, 1)}</td></tr>`).join("");
  el.innerHTML = `<div class="pad">
    ${aiCard("Why this home scores " + (s.score != null ? s.score : "a range"))}
    <h3 class="sec">Where ${s.score != null ? s.score : "the score"} sits</h3>
    ${scale}
    <p class="hint">${s.is_poor ? `<b>Flagged as poor energy efficiency</b> (Poor and Very poor homes are flagged and ranked by how much they could improve). ` : ""}
      Score = the sum of seven parts, each scored 0–100 and multiplied by its fixed weight from the brief.
      ${s.raw_score != null ? `Here: ${s.components.map((c) => fmt(c.contribution, 2)).join(" + ")} = <b>${fmt(s.raw_score, 2)}</b>, rounded to <b>${s.score}</b>.` : "One part is missing, so we show the range the score could take instead of guessing."}</p>
    <div class="table-wrap"><table class="t plain"><thead><tr><th>Part of the score</th><th>Weight</th><th>Sub-score</th><th>Points earned</th><th>Points missed <span class="muted" data-tip="Weight × (100 − sub-score): what this part could still add">ⓘ</span></th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <h3 class="sec">Key issues</h3>
    ${s.issues.length ? `<ol class="issues">${s.issues.map((i) => `<li><b>${esc(i.label)}</b> — ${esc(issueText(i).replace(i.label + ": ", ""))} <span class="muted small">(${fmt(i.points_available, 1)} points missed)</span></li>`).join("")}</ol>` : `<p class="muted">No part scores below the issue threshold.</p>`}
    <h3 class="sec">Compared with similar homes</h3>
    <div class="grid2">
      <div class="card"><h4 class="h4">Green Home Score, within this portfolio</h4>
        ${stand?.available ? `<p class="small">Scores higher than <b>${fmt(stand.similar?.percentile ?? stand.all.percentile)}%</b> of ${fmt(stand.similar?.homes ?? stand.all.homes)} ${esc(stand.similar?.definition || "homes")} (median ${fmt(stand.similar?.median_score ?? stand.all.median_score)}),
          and ${fmt(stand.all.percentile)}% of all ${fmt(stand.all.homes)} homes.</p><p class="tiny">${esc(stand.method)}. Relative rank among ${esc(stand.population)}; not a probability.</p>`
          : `<p class="small muted">${esc(stand?.reason || "Not available.")}</p>`}</div>
      <div class="card"><h4 class="h4">Energy use, vs real UK homes</h4>${f.peer ? peerCard(f).replace('<div class="card">', "<div>") : `<p class="small muted">No comparison: this home has no usable meter readings, and an estimate cannot be compared with real use.</p>`}</div>
    </div>
  </div>`;
  loadAI(el, f, "home", live);
}

// ---- 2 · Improvements (PS2 §4) with the Next Best Action decision ----
function tabImprove(el, f, ex, live) {
  const n = f.next_best_action, lead = n?.action?.ref;
  const refer = f.excluded.filter((e) => e.status === "needs_survey");
  const notSuit = f.excluded.filter((e) => e.status !== "needs_survey");
  const L = n?.action?.kind === "retrofit" ? f.plan.find((r) => r.measure_id === lead) : null;
  const steps = f.plan.map((r) => `<div class="step ${lead === r.measure_id ? "lead" : ""}">
      <div class="step-n">${r.order}</div>
      <div class="step-body">
        <div class="r1"><span>${esc(r.name)}</span>${lead === r.measure_id ? `<span class="badge first">Do this first</span>` : ""}<span class="suit ${r.suitability}">${esc(r.suitability)} suitability</span></div>
        <div class="r2">${esc(r.rationale)}${r.depends_on.length ? ` <span class="muted">Do after: ${esc(r.depends_on.map(short).join(", "))}.</span>` : ""}</div>
        <div class="r3 num">${fuelLine(r.in_package)} <span>CO₂e ${saveCell(r.in_package.carbon.total_tonnes, 2)} t a year</span>
          <span>${rc(r.receipt, `${gbp(r.cost_low)}–${gbp(r.cost_high)}`)} <span class="muted">typical cost</span></span></div>
        ${r.evidence.length ? `<div class="r2 small muted">Because: ${r.evidence.map(esc).join(" · ")}</div>` : ""}
        ${r.real_evidence ? `<div class="r2 evidence-real"><span class="badge">real homes</span> ${esc(r.real_evidence)}</div>` : ""}
        ${r.uncertainty?.length ? `<div class="r2 small muted">ⓘ ${r.uncertainty.map(esc).join(" ")}</div>` : ""}
      </div></div>`).join("");
  el.innerHTML = `<div class="pad">
    ${n ? `<div class="decision-card"><div class="dc-head"><small>Next best action</small> ${disp(n.disposition)}</div>
      <h3>${esc(n.headline)}</h3>
      ${L ? `<div class="dc-metrics">
        <div><small>Typical cost</small><b>${gbp(L.cost_low)}–${gbp(L.cost_high)}</b></div>
        <div><small>Electricity a year</small><b>${changeText(L.standalone.electricity.saving_kwh)}</b></div>
        <div><small>Gas a year</small><b>${changeText(L.standalone.gas.saving_kwh)}</b></div>
        <div><small>CO₂e saved a year</small><b>${fmt(L.standalone.carbon.total_tonnes, 2)} t</b></div>
        <div><small>Suitability · confidence</small><b>${esc(L.suitability)} · ${esc(n.confidence)}</b></div></div>` : ""}
      <h4 class="h4">Why</h4>
      ${n.reasons.map((r, i) => `<div class="reason"><span class="n">${i + 1}</span><div>${esc(r.text)}${S.mode === "evidence" ? `<span class="ref">← ${esc(r.fact_ref)}</span>` : ""}</div></div>`).join("")}
      ${n.blocked_by ? `<div class="note warn">${esc(n.blocked_by)}</div>` : ""}
      ${n.alternatives.length ? `<h4 class="h4">Also considered</h4><div class="table-wrap"><table class="t plain"><tbody>${n.alternatives.map((a) => `<tr><td>${esc(a.action.label)}</td><td class="small muted wrap">${esc(a.why_not_first)}</td></tr>`).join("")}</tbody></table></div>` : ""}
      <p class="tiny">Chosen by a fixed, documented rule (not by the AI): feasible upgrades whose prerequisites are done, ranked by ${esc(objName())} × suitability. Change the priority in ⚙.</p></div>` : ""}
    ${f.plan.length ? aiCard("Why these recommendations") : ""}
    <h3 class="sec">Recommended upgrades, in the order to do them (${f.plan.length})</h3>
    <p class="hint">Only upgrades that are feasible for this home. The order reflects how they interact: keep the heat in first, then controls, then the heating system (sized for the improved home), then solar (sized for the new demand). Savings shown are each upgrade's addition once the ones before it are done.</p>
    ${f.plan.length ? `<div class="steps">${steps}</div>` : `<div class="empty">No upgrades to suggest${f.warnings.length ? ": " + esc(f.warnings[0]) : "."}</div>`}
    ${refer.length || f.questions.length || f.conflicts.length ? `<h3 class="sec">Check first</h3>
      ${f.conflicts.map((c) => `<div class="check"><span class="disp refer_for_survey">records disagree</span><div><b>${esc(c.message)}</b><div class="small muted">${esc(c.resolution)}</div></div></div>`).join("")}
      ${refer.map((e) => `<div class="check"><span class="disp refer_for_survey">survey / consent</span><div><b>${esc(e.name)}</b><div class="small muted">${esc(e.reason)}</div></div></div>`).join("")}
      ${f.questions.map((q) => `<div class="check"><span class="badge">${esc(q.importance)} importance</span><div><b>${esc(q.question)}</b><div class="small muted">${esc(q.why)}</div></div></div>`).join("")}` : ""}
    ${notSuit.length ? `<h3 class="sec">Not recommended for this home</h3>
      <div class="table-wrap"><table class="t plain"><tbody>${notSuit.map((e) => `<tr><td><b>${esc(e.name)}</b></td><td><span class="badge">${esc(nice(e.status))}</span></td><td class="wrap small">${esc(e.reason)}</td></tr>`).join("")}</tbody></table></div>` : ""}
  </div>`;
  if (f.plan.length) loadAI(el, f, "package", live);
}
// direction in words, never only an arrow or a colour
const changeText = (saving) => (saving == null ? "—" : saving > 0 ? `${fmt(saving)} kWh less` : saving < 0 ? `${fmt(-saving)} kWh more` : "no change");
const fuelLine = (x) => `<span class="fuel el">Electricity ${changeText(x.electricity.saving_kwh)}</span> <span class="fuel gs">Gas ${changeText(x.gas.saving_kwh)}</span>`;

// ---- 3 · Energy & carbon (PS2 §3 potential, §5 savings, §6 carbon) ----
function tabSavings(el, f) {
  const pk = f.package;
  if (!pk) { el.innerHTML = `<div class="pad"><div class="empty">No savings to estimate: ${esc(f.warnings[0] || "no feasible upgrades or no energy baseline.")}</div></div>`; return; }
  const im = pk.impact, ip = pk.improvement_potential, ci = im.carbon.receipt?.inputs || {};
  let mode = "in_package";
  const draw = () => {
    const rows = f.plan.filter((r) => pk.measures.includes(r.measure_id)).map((r) => {
      const x = r[mode];
      return `<tr><td>${r.order}. ${esc(r.name)}</td><td class="num">${saveCell(x.electricity.saving_kwh)}</td><td class="num">${saveCell(x.gas.saving_kwh)}</td>
        <td class="num"><b>${saveCell(x.net_saving_kwh)}</b></td><td class="num">${rc(x.carbon.receipt, saveCell(x.carbon.total_tonnes, 2))}</td></tr>`;
    }).join("");
    $("#sv-body").innerHTML = rows + (mode === "standalone"
      ? `<tr class="sum"><td>Sum of the individual savings</td><td></td><td></td><td class="num"><b>${saveCell(pk.sum_of_standalone_net_kwh)}</b></td><td></td></tr>` : "")
      + `<tr class="total"><td><b>Whole plan together</b> ${tag("estimated", "engine estimate, not a guarantee")}</td><td class="num"><b>${saveCell(im.electricity.saving_kwh)}</b></td>
        <td class="num"><b>${saveCell(im.gas.saving_kwh)}</b></td><td class="num"><b>${rc(pk.receipt, saveCell(im.net_saving_kwh))}</b></td><td class="num"><b>${rc(im.carbon.receipt, saveCell(im.carbon.total_tonnes, 2))}</b></td></tr>`;
  };
  const kg = (x) => `${x >= 0 ? fmt(x) + " kg less" : fmt(-x) + " kg more"}`;
  el.innerHTML = `<div class="pad">
    <div class="kpis4">
      <div class="kpi-mini"><small>Electricity bought a year</small><b class="num">${fmt(im.electricity.baseline_kwh)} → ${fmt(im.electricity.after_kwh)}</b><span class="small">${changeText(im.electricity.saving_kwh)}</span></div>
      <div class="kpi-mini"><small>Gas bought a year</small><b class="num">${fmt(im.gas.baseline_kwh)} → ${fmt(im.gas.after_kwh)}</b><span class="small">${changeText(im.gas.saving_kwh)}</span></div>
      <div class="kpi-mini"><small>Improvement potential</small><b class="num">${ip.status === "available" ? rc(ip.receipt, fmt(ip.pct, 1) + "%") : "unavailable"}</b><span class="muted small">${ip.status === "available" ? "less energy bought" + (ip.basis === "estimated" ? " (estimated baseline)" : "") : esc(ip.reason)}</span></div>
      <div class="kpi-mini"><small>CO₂e a year</small><b class="num">${rc(im.carbon.receipt, fmt(im.carbon.total_tonnes, 2))} t less</b><span class="muted small">from the per-fuel changes</span></div>
    </div>
    ${im.electricity.saving_kwh < 0 ? `<div class="note">Electricity goes <b>up</b> by ${fmt(-im.electricity.saving_kwh)} kWh a year (shown as a negative saving) because a heat pump makes heat from electricity instead of gas; gas falls by ${fmt(im.gas.saving_kwh)} kWh, so energy bought and CO₂e still fall.</div>` : ""}
    <h3 class="sec">Carbon, fuel by fuel</h3>
    <div class="carbon-split">
      <div><small>Gas</small><b>${kg(im.carbon.gas_kg)}</b><span class="tiny">${signed(ci.delta_gas_kwh)} kWh × ${ci.ef_gas} kg/kWh</span></div>
      <div><small>Electricity</small><b>${kg(im.carbon.electricity_kg)}</b><span class="tiny">${signed(ci.delta_electricity_kwh)} kWh × ${ci.ef_electricity} kg/kWh</span></div>
      <div class="net"><small>Net, per year</small><b>${kg(im.carbon.total_kg)}</b><span class="tiny">ΔC = ΔE<sub>gas</sub>×EF<sub>gas</sub> + ΔE<sub>elec</sub>×EF<sub>elec</sub></span></div>
    </div>
    <div class="card-head" style="margin-top:16px"><div><h3>Saving per upgrade, by fuel (kWh a year)</h3>
      <p class="hint">Positive = less used; negative = more used. Savings don't simply add up: an upgrade saves less once another has already cut the same heat loss.</p></div>
      <div class="tabs" id="sv-mode" role="group" aria-label="How to count each upgrade"><button data-v="in_package" class="on">In this plan's order</button><button data-v="standalone">Each on its own</button></div></div>
    <div class="table-wrap"><table class="t plain savings"><thead><tr><th>Upgrade</th><th>Electricity</th><th>Gas</th><th>Net energy</th><th>CO₂e (t)</th></tr></thead><tbody id="sv-body"></tbody></table></div>
    <p class="small muted">Together the upgrades save ${fmt(im.net_saving_kwh)} kWh; done one at a time on today's home they would add up to ${fmt(pk.sum_of_standalone_net_kwh)} kWh (${signed(pk.interaction_kwh)} kWh lost to overlap).</p>
    <div class="formula"><b>Improvement potential</b> = 100 × (E<sub>before</sub> − E<sub>after</sub>) / E<sub>before</sub>
      ${ip.status === "available" ? `= 100 × (${fmt(ip.e_baseline_kwh)} − ${fmt(ip.e_after_kwh)}) / ${fmt(ip.e_baseline_kwh)} = <b>${fmt(ip.pct, 1)}%</b>` : `— ${esc(ip.reason)}`}
      <div class="small muted">E = grid electricity imported + gas, kWh a year. Solar lowers imports, not the home's demand. All figures are estimates, not guarantees.</div></div>
  </div>`;
  tabs("#sv-mode", (m) => { mode = m; draw(); });
  draw();
}

// ---- 4 · Property value (PS2 §7) ----
function tabValue(el, f) {
  const v = f.value;
  if (!v || v.status !== "available") { el.innerHTML = `<div class="pad"><div class="empty">No value estimate: ${esc(v?.reason || "not enough information.")}</div></div>`; return; }
  const none = !v.uplift_pct_range || (v.uplift_pct_range[0] === 0 && v.uplift_pct_range[1] === 0);
  el.innerHTML = `<div class="pad">
    <div class="kpis4">
      <div class="kpi-mini"><small>Estimated value today</small><b class="num">${rc(v.receipt, gbp(v.current_value))}</b><span class="muted small">range ${gbp(v.current_range?.[0])}–${gbp(v.current_range?.[1])}</span></div>
      <div class="kpi-mini"><small>Energy rating</small><b class="num">EPC ${esc(v.band_before || "?")} → ${esc(v.band_after || "?")}</b><span class="muted small">after the full plan (estimate)</span></div>
      <div class="kpi-mini"><small>Indicative change</small><b class="num">${none ? "none" : `${pctRange(v.uplift_pct_range[0], v.uplift_pct_range[1])}`}</b><span class="muted small">${none ? "the EPC band does not change" : `${gbp(v.uplift_gbp_range?.[0])}–${gbp(v.uplift_gbp_range?.[1])}`}</span></div>
      <div class="kpi-mini"><small>Potential value</small><b class="num">${none ? gbp(v.current_value) : `${gbp(v.value_after_range?.[0])}–${gbp(v.value_after_range?.[1])}`}</b><span class="muted small">a range, not a single number</span></div>
    </div>
    <div class="note warn"><b>Indicative, not a promise.</b> ${esc(v.caveat)}</div>
    <h3 class="sec">How this is estimated</h3>
    <ol class="howto">
      <li>Today's value: a regression on type, size, age, region and energy rating, fitted to historical sales brought to today's market with a regional index. ${tag("estimated")}</li>
      <li>The same home is compared before and after the plan with everything else held constant; only the EPC band changes (${esc(v.band_before || "?")} → ${esc(v.band_after || "?")}).</li>
      <li>The change is the historical price difference between those bands in the sales data, as a range (10th–90th percentile of a bootstrap).</li>
      <li>A past association, not proof that retrofitting causes a price rise. In this prototype the sales are simulated, so the range shows the method working, not a market fact.</li>
    </ol>
    <p class="small muted">Model: ${esc(v.provider)}</p></div>`;
}

// ---- What if… (PS2 §1/§8: rerun the calculations, then explain) ----
function tabWhatIf(el, f, ex, live) {
  const st = { picked: new Set() };
  el.innerHTML = `<div class="pad">
    <div class="note">Every change re-runs the savings, carbon, score and value calculations for this home first; only then is the result explained, and the explanation is checked against the new numbers.</div>
    <h3 class="sec">Build a plan</h3><div id="try"></div><div id="try-result"></div>
    <h3 class="sec">Or ask in your own words</h3>
    <form id="ask-form" class="row"><label class="sr-only" for="ask-q">Your question</label><input id="ask-q" class="inp grow" placeholder="What if I only add a heat pump?" autocomplete="off"><button class="nav-btn primary" type="submit">Ask</button></form>
    <div class="chips">${["What if I only add a heat pump?", "What if I do everything but skip the solar panels?", "What if I already have loft insulation?"]
      .map((q) => `<button class="chip" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>
    <div id="ask-out"></div>
    <h3 class="sec">Compare whole plans</h3><div id="lab"><button class="tool-btn" id="lab-run">Compare the four standard plans for this home</button></div>
    <details class="sec-details"><summary>How the AI is kept honest — see the checker block made-up sentences</summary>
      <p class="hint">A checker compares every sentence with the computed facts: each number and what it measures, whether each fuel goes up or down, promises about value, and which upgrades are meant. Failing text is never shown.</p>
      <button class="tool-btn" id="gate-run">Run the checker on four sentences</button><div id="gate-out"></div></details></div>`;
  const drawTry = () => {
    $("#try").innerHTML = f.plan.length ? `<div class="chips" role="group" aria-label="Upgrades in this plan">${f.plan.map((r) => `<button class="chip ${st.picked.has(r.measure_id) ? "on" : ""}" aria-pressed="${st.picked.has(r.measure_id)}" data-m="${r.measure_id}">${st.picked.has(r.measure_id) ? "✓ " : "+ "}${esc(r.name.replace(/ \(.*\)/, ""))}</button>`).join("")}
      <button class="chip ghost" data-all>All of them</button>${st.picked.size ? `<button class="chip ghost" data-clear>Reset to today</button>` : ""}</div>`
      : `<div class="empty">No upgrades to try for this home.</div>`;
  };
  drawTry();
  let seq = 0;
  const run = async () => {
    const mine = ++seq, out = $("#try-result");
    if (!st.picked.size) { out.innerHTML = ""; return; }
    out.innerHTML = `<div class="loading">Re-running the numbers…</div>`;
    try {
      const r = await api(`/api/properties/${f.property_id}/scenarios`, { measures: [...st.picked], objective: S.objective, name: "What-if" });
      if (mine !== seq || !live()) return;
      out.innerHTML = `<div class="card" style="margin-top:12px">${scenarioResult(f, r)}${gateBadge(r.explanation)}</div>`;
    } catch (e) { out.innerHTML = `<div class="err">Could not recalculate: ${esc(e.message)}. The previous result was cleared so it is not mistaken for this plan.</div>`; }
  };
  $("#try").addEventListener("click", (e) => {
    const c = e.target.closest("[data-m]");
    if (c) st.picked.has(c.dataset.m) ? st.picked.delete(c.dataset.m) : st.picked.add(c.dataset.m);
    else if (e.target.closest("[data-all]")) f.plan.forEach((r) => st.picked.add(r.measure_id));
    else if (e.target.closest("[data-clear]")) st.picked.clear();
    else return;
    drawTry(); run();
  });
  let askSeq = 0;
  const ask = async (q) => {
    const mine = ++askSeq, out = $("#ask-out");
    out.innerHTML = `<div class="loading">Re-running the numbers…</div>`;
    try {
      const r = await api(`/api/properties/${f.property_id}/ask`, { question: q, objective: S.objective });
      if (mine !== askSeq || !live()) return;
      out.innerHTML = `<p class="small" style="margin-top:12px">${esc(r.interpretation.message)}</p>` + (r.facts ? `<div class="card" style="margin-top:8px">${scenarioResult(f, r)}${gateBadge(r.explanation)}</div>` : "");
    } catch (e) { out.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  };
  $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#ask-q").value.trim(); if (q) ask(q); });
  el.addEventListener("click", (e) => { const c = e.target.closest("[data-q]"); if (c) { $("#ask-q").value = c.dataset.q; ask(c.dataset.q); } });
  $("#lab-run").onclick = () => labPanel($("#lab"), f, live);
  $("#gate-run").addEventListener("click", async () => {
    const out = $("#gate-out");
    out.innerHTML = `<div class="loading">Checking…</div>`;
    try {
      const r = await api(`/api/properties/${f.property_id}/gate-demo`);
      if (!live()) return;
      out.innerHTML = r.cases.length ? r.cases.map((c) => `<div class="rec"><div class="r1"><span>${esc(c.label)}</span><span class="disp ${c.gate.passed ? "recommend" : "refer_for_survey"}">${c.gate.passed ? "✓ shown" : "✗ blocked"}</span></div>
          <div class="r2">${esc(c.text)}</div>${c.gate.violations.length ? `<div class="r2 up">${c.gate.violations.map((x) => esc(x.detail)).join(" · ")}</div>` : ""}</div>`).join("")
        : `<div class="empty">${esc(r.note || "Nothing to check.")}</div>`;
    } catch (e) { out.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  });
}

async function labPanel(el, f, live) {
  el.innerHTML = `<div class="loading">Running every feasible combination of upgrades for this home…</div>`;
  let L;
  try { L = await api(`/api/properties/${encodeURIComponent(f.property_id)}/lab?budget=${LS.budget}&objective=${S.objective}`); }
  catch (e) { el.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  if (!live() || !el.isConnected) return;
  const byKey = Object.fromEntries(L.packages.map((o) => [o.key, o]));
  const order = f.plan.map((r) => r.measure_id);
  const keyOf = (set) => order.filter((m) => set.has(m)).join("+");
  const best = L.plans.find((p) => p.id === "best_value" && p.package_key) || L.plans.find((p) => p.package_key);
  const st = { sel: new Set(best ? byKey[best.package_key].measures : []), plan: best?.id || null, view: "plans" };
  el.innerHTML = `${L.notes.length ? `<div class="note">${L.notes.map(esc).join(" ")}</div>` : ""}
    <div class="card-head"><p class="hint">Four plans for four priorities, picked from ${L.packages.length} feasible combinations that were each run through the engine. Click one to see what it does.</p>
      <div class="row"><label class="small muted">Budget £ <input id="budget" class="inp" type="number" min="500" step="500" value="${LS.budget}" style="width:100px"></label>
      <div class="tabs" id="plan-view"><button data-v="plans" class="on">Plans</button><button data-v="frontier">Cost vs CO₂e</button></div></div></div>
    <div id="plans"></div><div class="card" id="sel-card" style="margin-top:14px"></div>`;
  $("#budget").addEventListener("change", (e) => { LS.budget = Math.max(500, +e.target.value || 10000); store.set("budget", LS.budget); labPanel(el, f, live); });
  const drawPlans = () => { $("#plans").innerHTML = st.view === "plans" ? planCards(L, byKey, st) : frontier(L, byKey, keyOf(st.sel)); };
  let seq = 0;
  const select = async (set, planId = null) => {
    st.sel = set; st.plan = planId; drawPlans();
    const mine = ++seq;
    if (!set.size) { $("#sel-card").innerHTML = `<div class="empty">Pick a plan.</div>`; return; }
    $("#sel-card").innerHTML = `<div class="loading">Re-running the numbers…</div>`;
    try {
      const r = await api(`/api/properties/${f.property_id}/scenarios`, { measures: [...set], objective: S.objective, name: planId ? L.plans.find((p) => p.id === planId).title : "Custom plan" });
      if (mine !== seq || !live() || !el.isConnected) return;
      $("#sel-card").innerHTML = selectedSummary(f, r, byKey[keyOf(set)]);
    } catch (e) { $("#sel-card").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  };
  tabs("#plan-view", (k) => { st.view = k; drawPlans(); });
  $("#plans").addEventListener("click", (e) => {
    const c = e.target.closest("[data-plan]");
    if (c && c.dataset.key) return select(new Set(byKey[c.dataset.key].measures), c.dataset.plan);
    const pt = e.target.closest("[data-pkg]");
    if (pt) select(new Set(byKey[pt.dataset.pkg].measures), null);
  });
  select(st.sel, st.plan);
}

// =====================================================================================
// MANY HOMES — an adviser's worklist: overview, priority list (with quick view), compare
// =====================================================================================
const MANY_TABS = [["overview", "Overview"], ["list", "Priority list"], ["compare", "Compare"]];
const picked = new Set();

async function homes(main, _arg, live, qs) {
  const p = await once("portfolio", () => api("/api/portfolio"));
  if (!live()) return;
  const legacy = { poor: "list", all: "list", groups: "compare" };
  let tab = legacy[qs.get("tab")] || (MANY_TABS.some((t) => t[0] === qs.get("tab")) ? qs.get("tab") : "overview");
  if (qs.get("tab") === "poor" && !qs.get("tier")) qs.set("poor", "1");
  const k = p.kpis, op = k.opportunity, val = k.value;
  main.innerHTML = `<div class="page">
    ${pagehead(`Many homes <span class="muted" style="font-weight:500">· ${fmt(p.n_homes)} assessed</span>`, "Which homes perform poorly, what to do about each, and what the whole portfolio could save.", synthNote)}
    <div class="summary flat">
      <div class="stat num"><b>${fmt(k.avg_score.value, 1)} → ${fmt(k.avg_score_after.value, 1)}</b><small>Average Green Home Score, now → with every plan</small></div>
      <div class="stat num danger"><b>${fmt(k.poor_pct.count)}</b><small>Poor or Very poor (${fmt(k.poor_pct.value, 1)}% of homes)</small></div>
      <div class="stat num"><b>${fmt(op.gas_gwh, 1)} GWh</b><small>Gas saved a year</small></div>
      <div class="stat num"><b>${op.electricity_gwh < 0 ? fmt(-op.electricity_gwh, 1) + " GWh more" : fmt(op.electricity_gwh, 1) + " GWh"}</b><small>Electricity a year${op.electricity_gwh < 0 ? " (heat pumps)" : " saved"}</small></div>
      <div class="stat num"><b>${fmt(op.tco2e)} t</b><small>CO₂e saved a year</small></div>
      <div class="stat num"><b>${val.median_uplift_pct[0] != null ? `${pctRange(val.median_uplift_pct[0], val.median_uplift_pct[1])}` : "—"}</b><small>Typical indicative value change</small></div>
    </div>
    <nav class="mtabs" id="mtabs">${MANY_TABS.map(([t, l]) => `<button data-v="${t}" class="${t === tab ? "on" : ""}">${l}</button>`).join("")}
      <span class="spacer"></span><button class="tool-btn" id="cmp-go" ${picked.size < 2 ? "disabled" : ""}>⇄ Compare selected (<span id="cmp-n">${picked.size}</span>)</button></nav>
    <div class="panel" id="panel"></div></div>`;
  const show = (t) => {
    tab = t;
    main.querySelectorAll("#mtabs button[data-v]").forEach((x) => x.classList.toggle("on", x.dataset.v === t));
    const keep = new URLSearchParams(qs); keep.set("tab", t);
    history.replaceState(null, "", "#/homes?" + keep.toString());
    ({ overview: manyOverview, list: manyList, compare: manyCompare })[t]($("#panel"), p, live, qs);
  };
  tabs("#mtabs", show);
  $("#cmp-go").onclick = () => { location.hash = "#/compare?ids=" + [...picked].join(","); };
  main.addEventListener("click", (e) => {
    const t = e.target.closest("[data-tier-go]");
    if (t) { qs.set("tier", t.dataset.tierGo); qs.delete("poor"); show("list"); }
  });
  show(tab);
}
function syncPicked() {
  const n = $("#cmp-n"); if (n) n.textContent = picked.size;
  const b = $("#cmp-go"); if (b) b.disabled = picked.size < 2;
}

function manyOverview(el, p) {
  const k = p.kpis;
  el.innerHTML = `<div class="pad">
    <h3 class="sec" style="margin-top:0">Worklist at a glance</h3>
    <div class="tiers">${p.tiers.map((t) => `<button class="tier-card ${t.key}" data-tier-go="${t.key}"><b class="num">${fmt(t.homes)}</b><span>${esc(t.label)}</span><small>${esc(t.meaning)}</small></button>`).join("")}</div>
    <div class="grid2" style="margin-top:14px">
      <div class="card"><h3>How green are the homes?</h3><p class="hint">Homes in each Green Home Score band.</p>${bandBars(p.band_distribution.all)}</div>
      <div class="card"><h3>Poorest homes with the most to gain</h3><p class="hint">Poor or Very poor, ranked by improvement potential.</p>
        <ol class="toplist">${p.ranking.top.slice(0, 6).map((r) => `<li><a href="#/home/${r.property_id}">${scoreDot(r.score, r.band)} <b>${r.property_id}</b> ${esc(typeName(r.property_type))}, ${esc(cap(r.region))}</a>
          <span class="num"><b>${fmt(r.potential_pct, 0)}%</b> less energy possible</span><span class="small muted">${esc((r.issues || []).slice(0, 2).join(", ").toLowerCase())}</span></li>`).join("")}</ol>
        <button class="linkbtn" data-tier-go="act_now">Open the full priority list →</button></div>
      <div class="card"><h3>Most recommended first steps</h3><p class="hint">The next best action chosen for each home.</p>
        ${p.next_actions.slice(0, 6).map((a) => `<div class="hbar"><span class="wrap">${esc(a.label)}</span><div class="track"><div class="fill" style="width:${(100 * a.count) / p.next_actions[0].count}%"></div></div><span class="num">${fmt(a.count)}</span></div>`).join("")}</div>
      <div class="card"><h3>Where the savings are</h3><p class="hint">CO₂e that every home's plan would save, by region. ${tag("estimated", k.opportunity.note)}</p>
        ${p.opportunity_by_region.map((r) => `<div class="hbar"><span>${esc(cap(r.region))}</span><div class="track"><div class="fill" style="width:${r.share_pct}%"></div></div><span class="num">${fmt(r.tco2e)} t</span></div>`).join("")}
        <p class="small">All plans together: gas ${fmt(k.opportunity.gas_gwh, 1)} GWh less a year; electricity ${k.opportunity.electricity_gwh < 0 ? fmt(-k.opportunity.electricity_gwh, 1) + " GWh more (heat pumps run on electricity)" : fmt(k.opportunity.electricity_gwh, 1) + " GWh less"}.</p></div>
    </div>
    <p class="small muted" style="margin-top:12px">Data behind these figures: ${fmt(k.coverage.metered_pct, 0)}% of homes have meter readings, ${fmt(k.coverage.epc_pct, 0)}% have an EPC on record, ${fmt(k.coverage.complete_score_pct, 0)}% have a score fully from records. ${esc(k.value.note)}.</p>
  </div>`;
}

function listTable(items, offset) {
  return `<div class="table-wrap"><table class="t homes"><thead><tr><th><span class="sr-only">Select to compare</span>⇄</th><th>#</th><th>Priority</th><th>Home</th><th>Score</th><th>Main issue</th><th>Next best action</th>
    <th>Improvement <span class="muted" data-tip="100 × (energy bought before − after) / before, with this home's feasible plan">ⓘ</span></th><th>CO₂e saved</th><th>Value</th></tr></thead><tbody>
    ${items.map((x, i) => `<tr data-id="${x.property_id}" tabindex="0">
      <td><input type="checkbox" data-pick="${x.property_id}" ${picked.has(x.property_id) ? "checked" : ""} aria-label="Compare ${x.property_id}"></td>
      <td class="num muted">${offset + i + 1}</td>
      <td><span class="tier-pill ${x.tier}">${esc(TIER_FALLBACK[x.tier] || "")}</span></td>
      <td><b>${x.property_id}</b><div class="small muted">${esc(typeName(x.property_type))} · ${esc(cap(x.region))}</div></td>
      <td>${scoreDot(x.score ?? (x.score_range ? x.score_range.join("–") : "?"), x.band)}</td>
      <td class="wrap small">${esc((x.issues || [])[0] || "—")}</td>
      <td class="wrap small">${esc(x.nba_label)}</td>
      <td class="num">${x.potential_status === "available" ? `<b>${fmt(x.potential_pct, 0)}%</b>${x.potential_basis === "estimated" ? " " + tag("estimated", "on a model-estimated baseline") : ""}` : `<span class="muted" title="${esc(x.potential_reason)}">n/a</span>`}</td>
      <td class="num small">${x.carbon_saving_kg == null ? "—" : fmt(x.carbon_saving_kg / 1000, 2) + " t"}</td>
      <td class="num small">${x.value_uplift_pct_high ? `${pctRange(x.value_uplift_pct_low, x.value_uplift_pct_high)}` : x.value_status === "available" ? "none" : "—"}</td></tr>`).join("")}
    </tbody></table></div>`;
}

function quickView(x) {
  const d = $("#drawer");
  d.innerHTML = `<div class="evi-head"><b>${x.property_id}</b><button class="linkbtn" id="drawer-x">Close ✕</button></div>
    <div class="small muted">${esc(typeName(x.property_type))} · ${esc(cap(x.region))} · ${esc(ageName(x.age_band))} · ${x.floor_area_m2 ? fmt(x.floor_area_m2) + " m²" : ""}</div>
    <div class="qv-score">${scoreDot(x.score ?? (x.score_range ? x.score_range.join("–") : "?"), x.band)} ${bandBadge(x.band)} <span class="tier-pill ${x.tier}">${esc(TIER_FALLBACK[x.tier] || "")}</span></div>
    <dl class="kv">
      <dt>Key issues</dt><dd>${esc((x.issues || []).join(", ") || "none")}</dd>
      <dt>Next best action</dt><dd>${disp(x.nba_disposition)} ${esc(x.nba_headline || x.nba_label)}</dd>
      <dt>Whole plan</dt><dd>${(x.package_measures || []).map((m) => esc(short(m))).join(" → ") || "—"}</dd>
      <dt>Improvement</dt><dd>${x.potential_status === "available" ? fmt(x.potential_pct, 1) + "% less energy bought" : esc(x.potential_reason || "n/a")}</dd>
      <dt>Electricity</dt><dd>${changeText(x.electricity_saving_kwh)} a year</dd>
      <dt>Gas</dt><dd>${changeText(x.gas_saving_kwh)} a year</dd>
      <dt>CO₂e</dt><dd>${x.carbon_saving_kg == null ? "—" : fmt(x.carbon_saving_kg / 1000, 2) + " t less a year"}</dd>
      <dt>Score after plan</dt><dd>${x.score ?? "?"} → ${x.score_after ?? "?"} ${esc(x.band_after || "")}</dd>
      <dt>Typical cost</dt><dd>${x.cost_low != null ? `${gbp(x.cost_low)}–${gbp(x.cost_high)}` : "—"}</dd>
      <dt>Value</dt><dd>${x.value_uplift_pct_high ? `${pctRange(x.value_uplift_pct_low, x.value_uplift_pct_high)} indicative` : "no indicative change"}</dd>
      <dt>Data</dt><dd>${tag(x.baseline_basis)} energy ${esc(x.baseline_basis)} · confidence ${esc(x.confidence)}</dd></dl>
    <a class="nav-btn primary" href="#/home/${x.property_id}" style="margin-top:12px">Open the full home →</a>`;
  d.classList.add("on");
  $("#drawer-x").focus();
}

async function manyList(el, p, live, qs) {
  const f = { q: qs.get("q") || "", tier: qs.get("tier") || "", region: qs.get("region") || "", property_type: qs.get("property_type") || "",
    sort: qs.get("sort") || "priority", group_by: qs.get("group_by") || "", group: qs.get("group") || "", poor_only: qs.get("poor") ? "true" : "", offset: 0 };
  const regions = Object.keys(p.band_distribution.region), types = Object.keys(p.band_distribution.property_type);
  const opt = (name, vals, label) => `<label class="sr-only" for="f-${name}">${label}</label><select id="f-${name}" data-f="${name}" class="inp"><option value="">${label}</option>${vals.map(([v, l]) => `<option value="${esc(v)}" ${f[name] === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  el.innerHTML = `<div class="pad">
    <div class="chips" role="group" aria-label="Priority">${[["", "All homes", p.n_homes], ...p.tiers.map((t) => [t.key, t.label, t.homes])].map(([key, l, c]) => `<button class="chip tierchip ${key} ${f.tier === key && !(key === "" && f.poor_only) ? "on" : ""}" data-tier="${key}">${esc(l)} <span class="num">${fmt(c)}</span></button>`).join("")}
      <button class="chip ${f.poor_only ? "on" : ""}" data-poor>Poor or Very poor only</button></div>
    <div class="filters" style="margin-top:10px">
      <label class="sr-only" for="f-q">Search</label><input id="f-q" type="search" class="inp" placeholder="Search reference, region, type…" value="${esc(f.q)}" data-f="q">
      ${opt("region", regions.map((r) => [r, cap(r)]), "Any region")}${opt("property_type", types.map((t) => [t, typeName(t)]), "Any type")}
      ${opt("sort", [["priority", "Priority, then improvement"], ["potential", "Biggest improvement first"], ["score", "Lowest score first"], ["carbon", "Most CO₂e saved first"], ["value", "Largest value change first"]], "Sort")}
    </div>
    ${f.group_by ? `<div class="note">Showing ${esc(p.group_keys[f.group_by] || f.group_by)}: <b>${esc(groupName(f.group_by, f.group))}</b> · <a href="#/homes?tab=list">show all</a></div>` : ""}
    <p class="small muted">Click a row for a quick view; tick up to four homes to compare them side by side.</p><div id="tbl"><div class="loading">Loading…</div></div></div>`;
  const apply = () => {
    const keep = new URLSearchParams(Object.entries({ ...f, poor: f.poor_only ? "1" : "" }).filter(([k2, v]) => v !== "" && !["offset", "poor_only"].includes(k2))); keep.set("tab", "list");
    history.replaceState(null, "", "#/homes?" + keep.toString());
    f.offset = 0; load();
  };
  el.querySelectorAll("[data-tier]").forEach((b) => (b.onclick = () => { f.tier = b.dataset.tier; f.poor_only = ""; el.querySelectorAll("[data-tier],[data-poor]").forEach((x) => x.classList.toggle("on", x === b)); apply(); }));
  el.querySelector("[data-poor]").onclick = (e) => { f.poor_only = f.poor_only ? "" : "true"; f.tier = ""; el.querySelectorAll("[data-tier]").forEach((x) => x.classList.remove("on")); e.target.classList.toggle("on", !!f.poor_only); apply(); };
  el.querySelectorAll("select[data-f]").forEach((x) => x.addEventListener("change", () => { f[x.dataset.f] = x.value; apply(); }));
  const search = el.querySelector('[data-f="q"]');
  search.addEventListener("keydown", (e) => { if (e.key === "Enter") { f.q = search.value; apply(); } });
  const tbl = $("#tbl");
  let items = [];
  tbl.addEventListener("click", (e) => {
    const cb = e.target.closest("[data-pick]");
    if (cb) {
      if (cb.checked && picked.size >= 4) { cb.checked = false; return; }
      cb.checked ? picked.add(cb.dataset.pick) : picked.delete(cb.dataset.pick);
      syncPicked(); return;
    }
    const tr = e.target.closest("tr[data-id]");
    if (tr) quickView(items.find((x) => x.property_id === tr.dataset.id));
  });
  tbl.addEventListener("keydown", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr && e.key === "Enter") quickView(items.find((x) => x.property_id === tr.dataset.id)); });
  const load = async () => {
    const params = Object.fromEntries(Object.entries(f).filter(([k2, v]) => v !== "" && k2 !== "offset"));
    const r = await api("/api/properties?" + new URLSearchParams({ ...params, limit: 25, offset: f.offset }));
    if (!live()) return;
    items = r.items;
    tbl.innerHTML = `<div class="small muted" style="margin-bottom:6px">${fmt(r.total)} homes</div>${r.items.length ? listTable(r.items, f.offset) : `<div class="empty">No homes match these filters.</div>`}${pager(r, f.offset)}`;
    pagerWire(tbl, r, (o) => { f.offset = o; load(); });
  };
  load();
}
function pager(r, offset) {
  return `<div class="pager"><button class="tool-btn" data-off="${Math.max(offset - 25, 0)}" ${offset <= 0 ? "disabled" : ""}>← Previous</button>
    <span class="small muted">${fmt(Math.min(offset + 1, r.total))}–${fmt(Math.min(offset + 25, r.total))} of ${fmt(r.total)}</span>
    <button class="tool-btn" data-off="${offset + 25}" ${offset + 25 >= r.total ? "disabled" : ""}>Next →</button></div>`;
}
function pagerWire(el, r, go) { el.querySelectorAll("[data-off]").forEach((b) => (b.onclick = () => go(+b.dataset.off))); }

async function manyCompare(el, p, live, qs) {
  let by = p.group_keys[qs.get("by")] ? qs.get("by") : "region";
  el.innerHTML = `<div class="pad">
    <div class="card" style="margin-bottom:14px"><h3>Selected homes</h3>
      ${picked.size ? `<p class="small">${[...picked].map((x) => `<span class="badge">${esc(x)} <button class="linkbtn small" data-unpick="${esc(x)}" aria-label="Remove ${esc(x)}">✕</button></span>`).join(" ")}</p>
        <button class="nav-btn primary" id="cmp-now" ${picked.size < 2 ? "disabled" : ""}>Compare these ${picked.size} side by side</button>` : `<p class="small muted">Tick homes in the Priority list (up to four), then compare them here side by side.</p>`}</div>
    <div class="row"><span class="small muted">Compare groups of homes by</span><div class="tabs" id="by">${Object.entries(p.group_keys).map(([k2, l]) => `<button data-v="${k2}" class="${k2 === by ? "on" : ""}">${esc(l)}</button>`).join("")}</div></div>
    <div id="groups"><div class="loading">Loading…</div></div></div>`;
  el.querySelector("#cmp-now")?.addEventListener("click", () => { location.hash = "#/compare?ids=" + [...picked].join(","); });
  el.querySelectorAll("[data-unpick]").forEach((b) => (b.onclick = () => { picked.delete(b.dataset.unpick); syncPicked(); manyCompare(el, p, live, qs); }));
  const load = async () => {
    const g = await api("/api/portfolio/groups?by=" + by);
    if (!live()) return;
    const mC = Math.max(...g.groups.map((x) => x.carbon_saving_t_per_home || 0), 1e-9);
    $("#groups").innerHTML = `<div class="table-wrap" style="margin-top:12px"><table class="t groups"><thead><tr><th>${esc(g.label)}</th><th>Homes</th><th>Average score<br><span class="muted">now → with plans</span></th><th>Poor or Very poor</th>
        <th>Median improvement</th><th>Electricity</th><th>Gas</th><th>CO₂e saved<br><span class="muted">per home a year</span></th><th>Value change<br><span class="muted">median range</span></th><th>With meter data</th></tr></thead><tbody>
      ${g.groups.map((x) => `<tr data-group="${esc(x.group)}" tabindex="0">
        <td><b>${esc(groupName(by, x.group))}</b></td><td class="num">${fmt(x.homes)}</td>
        <td class="num">${x.avg_score == null ? "—" : `${fmt(x.avg_score, 1)} → <b>${fmt(x.avg_score_after, 1)}</b>`}<div>${bar(x.avg_score)}</div></td>
        <td class="num">${x.poor_pct == null ? "—" : `${fmt(x.poor_pct, 0)}% <span class="muted small">(${fmt(x.poor_homes)})</span>`}<div>${bar(x.poor_pct || 0, "bad")}</div></td>
        <td class="num">${x.median_potential_pct == null ? "—" : fmt(x.median_potential_pct, 0) + "%"}</td>
        <td class="num small">${x.electricity_saving_mwh < 0 ? fmt(-x.electricity_saving_mwh) + " MWh more" : fmt(x.electricity_saving_mwh) + " MWh less"}</td>
        <td class="num small">${fmt(x.gas_saving_mwh)} MWh less</td>
        <td class="num">${x.carbon_saving_t_per_home == null ? "—" : fmt(x.carbon_saving_t_per_home, 2) + " t"}<div>${bar((100 * (x.carbon_saving_t_per_home || 0)) / mC, "good")}</div></td>
        <td class="num small">${x.median_uplift_pct ? `${pctRange(x.median_uplift_pct[0], x.median_uplift_pct[1])}` : "—"}</td>
        <td class="num small">${fmt(x.metered_pct, 0)}%</td></tr>`).join("")}</tbody></table></div>
      <p class="small muted">${esc(g.note)} "Poor or Very poor" is the share of homes whose band is known. Click a row to list its homes.</p>`;
    $("#groups tbody").onclick = (e) => { const tr = e.target.closest("tr[data-group]"); if (tr) location.hash = `#/homes?tab=list&group_by=${by}&group=${encodeURIComponent(tr.dataset.group)}`; };
  };
  tabs("#by", (k2) => { by = k2; load(); });
  load();
}

async function compare(main, _a, live, qs) {
  const ids = (qs.get("ids") || "").split(",").map((x) => x.trim()).filter(Boolean).slice(0, 4);
  if (ids.length < 2) { location.replace("#/homes?tab=all"); return; }
  const reps = await Promise.all(ids.map((id) => loadFacts(id).catch(() => null)));
  if (!live()) return;
  const F = reps.filter(Boolean).map((r) => r.facts);
  const row = (label, cell, hint = "") => `<tr><th>${label}${hint ? ` <span class="muted small" data-tip="${esc(hint)}">ⓘ</span>` : ""}</th>${F.map((f) => `<td>${cell(f)}</td>`).join("")}</tr>`;
  const sec = (t) => `<tr class="secrow"><th colspan="${F.length + 1}">${t}</th></tr>`;
  const comps = F[0].score.components.map((c) => c.key);
  const best = (vals, hi = true) => { const ok = vals.filter((x) => x != null); return ok.length ? (hi ? Math.max(...ok) : Math.min(...ok)) : null; };
  const mark = (v, b) => (v != null && v === b ? " best" : "");
  const sc = best(F.map((f) => f.score.score)), ip = best(F.map((f) => f.package?.improvement_potential?.pct)), co = best(F.map((f) => f.package?.impact.carbon.total_tonnes));
  main.innerHTML = `<div class="page">
    ${pagehead("Compare homes", `${F.length} homes side by side, on every PS2 output. Green marks the best in each row.`, `<a class="nav-btn" href="#/homes?tab=all">← Back to all homes</a>`)}
    <div class="table-wrap"><table class="t compare"><thead><tr><th></th>${F.map((f) => `<th><a href="#/home/${f.property_id}">${f.property_id}</a><div class="small muted">${esc(describe(f.property_summary))}</div>
      <button class="linkbtn small" data-drop="${f.property_id}">remove</button></th>`).join("")}</tr></thead><tbody>
    ${sec("1 · How green is it?")}
    ${row("Green Home Score", (f) => `<span class="cell${mark(f.score.score, sc)}">${scoreDot(f.score.score ?? (f.score.score_range || []).join("–"), f.score.band)} ${bandBadge(f.score.band)}</span>`)}
    ${comps.map((k2) => row(`&nbsp;&nbsp;${esc(F[0].score.components.find((c) => c.key === k2).label)} <span class="muted small">(${fmt(F[0].score.components.find((c) => c.key === k2).weight * 100)}%)</span>`,
      (f) => { const c = f.score.components.find((x) => x.key === k2); return c.contribution == null ? "—" : `<span class="num">${fmt(c.contribution, 1)}</span> <span class="small muted">${esc(c.input_display)}</span>`; })).join("")}
    ${row("Key issues", (f) => esc(f.score.issues.slice(0, 3).map((i) => i.label).join(", ") || "none"))}
    ${row("Energy bought a year", (f) => `<span class="num">${fmt(f.baseline.electricity.annual_kwh)} elec · ${fmt(f.baseline.gas.annual_kwh)} gas kWh</span> ${tag(f.baseline_basis)}`)}
    ${row("Energy per m²", (f) => `<span class="num">${fmt(f.intensity_kwh_m2.value)} kWh/m²</span>`)}
    ${sec("2 · What should be improved?")}
    ${row("Do this first", (f) => `${disp(f.next_best_action?.disposition)} ${esc(f.next_best_action?.headline || "—")}`)}
    ${row("Plan, in order", (f) => f.plan.map((r) => `${r.order}. ${esc(short(r.measure_id))} <span class="suit ${r.suitability}">${r.suitability[0]}</span>`).join("<br>") || "—")}
    ${row("Not recommended", (f) => esc(f.excluded.filter((e) => e.status !== "needs_survey").map((e) => short(e.measure_id)).join(", ") || "—"))}
    ${sec("3 · Energy & carbon")}
    ${row("Improvement potential", (f) => { const x = f.package?.improvement_potential; return x?.status === "available" ? `<b class="num${mark(x.pct, ip)}">${fmt(x.pct, 1)}%</b>` : "n/a"; }, "100 × (before − after) / before, energy bought")}
    ${row("Electricity saved a year", (f) => f.package ? saveCell(f.package.impact.electricity.saving_kwh) + " kWh" : "—")}
    ${row("Gas saved a year", (f) => f.package ? saveCell(f.package.impact.gas.saving_kwh) + " kWh" : "—")}
    ${row("CO₂e saved a year", (f) => f.package ? `<b class="num${mark(f.package.impact.carbon.total_tonnes, co)}">${fmt(f.package.impact.carbon.total_tonnes, 2)} t</b>` : "—")}
    ${row("Score after the plan", (f) => f.package ? `${f.score.score ?? "?"} → <b>${f.package.score_after ?? "?"}</b> ${bandBadge(f.package.band_after)}` : "—")}
    ${row("Typical cost", (f) => f.package ? `${gbp(f.package.cost_low)}–${gbp(f.package.cost_high)}` : "—")}
    ${sec("4 · Property value")}
    ${row("Estimated value today", (f) => f.value?.status === "available" ? gbp(f.value.current_value) : "—")}
    ${row("Indicative change", (f) => f.value?.uplift_pct_range ? (f.value.uplift_pct_range[1] ? `${pctRange(f.value.uplift_pct_range[0], f.value.uplift_pct_range[1])} (EPC ${esc(f.value.band_before)} → ${esc(f.value.band_after)})` : "none (band unchanged)") : "—")}
    ${sec("Data quality")}
    ${row("Confidence", (f) => `${esc(cap(f.confidence.level))} <span class="small muted">${esc(f.confidence.reasons[0] || "")}</span>`)}
    </tbody></table></div>
    <p class="small muted">Value changes are indicative ranges from historical sales, not promises. Savings are engine estimates.</p></div>`;
  main.querySelectorAll("[data-drop]").forEach((b) => (b.onclick = () => { picked.delete(b.dataset.drop); location.hash = "#/compare?ids=" + ids.filter((x) => x !== b.dataset.drop).join(","); }));
}

// =====================================================================================
// HOW IT WORKS — every formula from the brief, with the parameters we use
// =====================================================================================
async function how(main, _a, live) {
  const e = await once("evidence", () => api("/api/evidence"));
  if (!live()) return;
  const sc = e.score, ef = e.emission_factors.factors, m = e.metrics, v = m?.validation, rd = e.real_data, cal = e.calibration;
  const knots = (k) => k.map(([x, y]) => `${fmt(x)}→${fmt(y)}`).join(", ");
  const ladder = (l) => l.map(([x, y]) => `${esc(cap(x))} ${fmt(y)}`).join(" · ");
  const SECTIONS = [["score", "Score"], ["poor", "Poor homes"], ["retrofits", "Upgrades"], ["savings", "Savings"], ["carbon", "Carbon"], ["value", "Value"],
    ["ai", "AI explanations"], ["data", "Data"], ["quality", "How well it works"], ["assumptions", "Assumptions"]];
  const cmp = (a, b, lower = true) => (a == null || b == null ? "" : (lower ? a < b : a > b) ? `<span class="disp recommend">better</span>` : `<span class="disp refer_for_survey">not better</span>`);
  main.innerHTML = `<div class="page how">
    ${pagehead("How GreenIQ works", "Every number is computed by documented code from the brief's formulas. Language is only used to explain the numbers, and is checked.", synthNote)}
    <nav class="chips toc">${SECTIONS.map(([id, l]) => `<a class="chip" href="#/how" data-jump="${id}">${l}</a>`).join("")}</nav>

    <section id="s-score" class="card"><h2>Green Home Score (PS2 §2)</h2>
      <div class="formula big">Score = Σ weight<sub>k</sub> × sub-score<sub>k</sub>, rounded to the nearest whole number (halves up)</div>
      <div class="two"><div><table class="t plain"><thead><tr><th>Part</th><th>Weight</th><th>How the 0–100 sub-score is set</th></tr></thead><tbody>
        <tr><td>${esc(sc.labels.energy_efficiency)}</td><td class="num">${fmt(sc.weights.energy_efficiency * 100)}%</td><td class="small wrap">The recorded energy rating (SAP), one-to-one; band midpoint if only the letter is known; a model estimate if there is no EPC.</td></tr>
        <tr><td>${esc(sc.labels.consumption_intensity)}</td><td class="num">${fmt(sc.weights.consumption_intensity * 100)}%</td><td class="small wrap">Annualised energy bought per m² (kWh/m²→score): ${knots(sc.mappings.intensity_kwh_m2)}</td></tr>
        <tr><td>${esc(sc.labels.insulation)}</td><td class="num">${fmt(sc.weights.insulation * 100)}%</td><td class="small wrap">Walls ${fmt(sc.mappings.insulation_element_weights.walls * 100)}% (${sc.mappings.walls.map(([k2, v2]) => `${esc(k2)} ${v2}`).join(", ")}) · loft ${fmt(sc.mappings.insulation_element_weights.loft * 100)}% (mm→score ${knots(sc.mappings.loft_mm)}) · floor ${fmt(sc.mappings.insulation_element_weights.floor * 100)}%</td></tr>
        <tr><td>${esc(sc.labels.heating_system)}</td><td class="num">${fmt(sc.weights.heating_system * 100)}%</td><td class="small wrap">${ladder(sc.mappings.heating)}; gas boilers lose up to ${fmt(sc.mappings.boiler_age_penalty.at(-1)[1])} points with age</td></tr>
        <tr><td>${esc(sc.labels.glazing)}</td><td class="num">${fmt(sc.weights.glazing * 100)}%</td><td class="small wrap">${ladder(sc.mappings.glazing)}</td></tr>
        <tr><td>${esc(sc.labels.renewables)}</td><td class="num">${fmt(sc.weights.renewables * 100)}%</td><td class="small wrap">Solar kWp→score: ${knots(sc.mappings.solar_kwp)}</td></tr>
        <tr><td>${esc(sc.labels.smart_controls)}</td><td class="num">${fmt(sc.weights.smart_controls * 100)}%</td><td class="small wrap">${ladder(sc.mappings.controls)}</td></tr>
      </tbody></table></div>
      <div><table class="t plain"><thead><tr><th>Score</th><th>Classification</th></tr></thead><tbody>${sc.bands.map(([lo, hi, l]) => `<tr><td class="num">${lo}–${hi}</td><td>${bandBadge(l)}</td></tr>`).join("")}</tbody></table>
        <p class="small">A better state never gives a lower sub-score (tested). If an input is missing, we show the range the score could take, not a guess.
        The energy rating and the per-m² use overlap in what they reflect; the rating is the recorded certificate and the intensity is this home's actual metered use, as the brief asks.</p>
        <p class="small muted">Mappings version <code>${esc(sc.version)}</code>. Full rationale: docs/SCORING_METHOD.md.</p></div></div></section>

    <section id="s-poor" class="card"><h2>Poor homes and improvement potential (PS2 §3)</h2>
      <div class="formula big">Improvement potential = 100 × (E<sub>before</sub> − E<sub>after</sub>) / E<sub>before</sub> &nbsp; where E = grid electricity imported + gas (kWh/yr)</div>
      <ul class="small"><li>Homes scoring <b>Poor</b> or <b>Very poor</b> are flagged, with key issues: parts of the score below ${fmt(sc.issue_threshold)}/100, ordered by points missed.</li>
        <li>E<sub>after</sub> uses the home's full feasible plan. Before and after use the same accounting; solar lowers imports, not demand.</li>
        <li>Zero or missing baseline → "unavailable" with the reason. A model-estimated baseline is reported and labelled "estimate".</li>
        <li>Ranking is by this percentage, not total use, so a big home isn't ranked high just for being big.</li></ul></section>

    <section id="s-retrofits" class="card"><h2>Upgrade recommendations (PS2 §4)</h2>
      <p class="small">Only feasible upgrades are listed, each with suitability, estimated saving and reason, in this order: ${Object.values(e.stages).map(esc).join(" → ")}.</p>
      <div class="table-wrap"><table class="t plain"><thead><tr><th>Upgrade</th><th>When it applies</th><th>Impact: brief's illustration · our engine (median, validation homes) · real UK homes</th><th>Typical cost</th></tr></thead><tbody>
      ${Object.entries(e.measures).map(([mk, x]) => { const ri = m?.retrofit_impacts?.measures?.[mk]; return `<tr><td><b>${esc(x.name)}</b></td><td class="small wrap">${(x.applicability?.conditions || []).map(esc).join("<br>")}</td>
        <td class="small wrap">${x.ps2_illustrative_impact ? `Brief: ${x.ps2_illustrative_impact.low_pct}–${x.ps2_illustrative_impact.high_pct}% of ${esc(x.ps2_illustrative_impact.quantity)}` : "—"}
          ${ri?.engine_median_pct != null ? `<br>Ours: <b>${fmt(ri.engine_median_pct, 1)}%</b> <span class="muted">(middle half ${fmt(ri.engine_p25_p75_pct[0], 1)}–${fmt(ri.engine_p25_p75_pct[1], 1)}%, ${fmt(ri.homes)} homes)</span>` : ""}
          ${ri?.real_homes ? `<br>Real homes: ${fmt(ri.real_homes.saving_pct, 1)}% of ${esc(ri.real_homes.of)} <span class="muted">(n=${fmt(ri.real_homes.n)})</span>` : ""}</td>
        <td class="small wrap">£${fmt(x.cost.low)}–£${fmt(x.cost.high)} ${esc(x.cost.basis)}<div class="muted">${esc(x.cost_source || "")}</div></td></tr>`; }).join("")}</tbody></table></div>
      <p class="small muted">${esc(e.impact_note || "")} ${esc(e.price_basis || "")}</p></section>

    <section id="s-savings" class="card"><h2>Energy savings (PS2 §5)</h2>
      <ul class="small"><li>Saving per fuel = baseline − after, kWh a year, for each upgrade and for the plan. An increase is a negative saving (a heat pump raises electricity).</li>
        <li>The plan applies upgrades one after another to one home model, so overlapping savings are not double counted; the plan total is not the sum of the parts.</li>
        <li>The model is anchored on the home's own weather-corrected meter readings, split into heating and everything else by a degree-day regression.</li>
        <li><b>Real-world correction:</b> ${esc(cal.name)}.</li></ul>
      <table class="t plain"><thead><tr><th>Upgrade</th><th>Share of the engineering saving realised</th><th>From</th></tr></thead><tbody>
      ${Object.entries(cal.rates).map(([k2, r]) => `<tr><td>${esc(e.measures[k2]?.name || k2)}</td><td class="num">${fmt(r * 100)}%</td><td class="small wrap">${esc(cal.sources[k2] || "")}</td></tr>`).join("")}</tbody></table></section>

    <section id="s-carbon" class="card"><h2>Carbon (PS2 §6)</h2>
      <div class="formula big">ΔC = ΔE<sub>elec</sub> × EF<sub>elec</sub> + ΔE<sub>gas</sub> × EF<sub>gas</sub> &nbsp; (positive ΔE = a saving; positive ΔC = less CO₂e)</div>
      <dl class="kv">${Object.entries(ef).map(([k2, x]) => `<dt>${cap(k2)}</dt><dd><b class="num">${x.value}</b> ${esc(x.unit)}<div class="small muted">${esc(x.source)}</div></dd>`).join("")}</dl></section>

    <section id="s-value" class="card"><h2>Property value (PS2 §7)</h2>
      <ul class="small"><li>Today's value: regression on type, size, age, region and energy rating, fitted to historical sales brought to today's prices with a regional index; an 80% interval is shown.</li>
        <li>Change: the same home before and after the plan, all else constant; only the EPC band changes. The price difference between bands in past sales gives a range (bootstrap 10th–90th percentile).</li>
        <li>Always a range and always labelled indicative: past association, not proof that retrofitting causes a price rise.</li></ul>
      ${m?.value ? `<p class="small">Check on held-out sales: typical error ${fmt(m.value.test_chosen?.median_ape_pct, 1)}%; the 80% interval contained the price ${fmt(100 * m.value.interval_80.coverage)}% of the time.</p>` : ""}</section>

    <section id="s-ai" class="card"><h2>AI explanations and what-ifs (PS2 §1, §8)</h2>
      <ul class="small"><li>The score, savings, carbon and value always come from the calculations above. A language model never computes them.</li>
        <li>A what-if re-runs those calculations for the changed plan first; only then is the result explained.</li>
        <li>Every explanation passes a checker before it is shown: each number must match a computed fact with the right meaning; each fuel's direction must be right; no promise of value; only the upgrades in the plan. If it fails, a plain template is shown.</li>
        <li>With no model configured, the template is used and the app still works. An optional free local model can reword the meaning; the engine still states every figure.</li></ul></section>

    <section id="s-data" class="card"><h2>Data (PS2 §9)</h2>
      <ul class="small"><li><b>Homes, meters, retrofits and sales are simulated</b> (a test world with hidden truth that the engine never sees). Splits are by customer: no home or customer appears in two splits. Missing months are never treated as zero.</li>
        ${rd ? `<li><b>Real check:</b> ${fmt(rd.summary.homes)} anonymised real homes from DESNZ NEED (Open Government Licence) give the peer comparisons and the measured real-world savings: ${Object.entries(rd.retrofit_evidence).map(([k2, x]) => `${esc(nice(k2))} ${x.estimate.saving_pct}% of ${esc(x.fuel)} (n=${fmt(x.estimate.n)})`).join(", ")}.</li>` : ""}
        <li>No real personal or customer data is used.</li></ul></section>

    <section id="s-quality" class="card"><h2>How well it works — validation set vs simple baselines (PS2 §11)</h2>
      ${v ? `<div class="table-wrap"><table class="t plain"><thead><tr><th>What</th><th>GreenIQ</th><th>Simple baseline</th><th></th></tr></thead><tbody>
        ${["electricity", "gas"].map((fu) => { const t = v.energy[fu].validation; return `<tr><td>Annual ${fu} when meters are missing (error, kWh)</td><td class="num">${fmt(t.gbm.mae)}</td><td class="num">${fmt(t.peer_median.mae)} <span class="muted small">similar-homes median</span></td><td>${cmp(t.gbm.mae, t.peer_median.mae)}</td></tr>`; }).join("")}
        ${["electricity", "gas"].map((fu) => `<tr><td>Retrofit saving, ${fu} (error vs what homes actually saved, kWh)</td><td class="num">${fmt(v.savings.methods.cal[fu].mae)}</td><td class="num">${fmt(v.savings.methods.naive[fu].mae)} <span class="muted small">flat % rule of thumb</span></td><td>${cmp(v.savings.methods.cal[fu].mae, v.savings.methods.naive[fu].mae)}</td></tr>`).join("")}
        <tr><td>Heat pump: electricity direction right</td><td class="num">${fmt(100 * v.savings.methods.cal.hp_electricity_sign_correct)}%</td><td class="num">${fmt(100 * v.savings.methods.naive.hp_electricity_sign_correct)}%</td><td>${cmp(v.savings.methods.cal.hp_electricity_sign_correct, v.savings.methods.naive.hp_electricity_sign_correct, false)}</td></tr>
        <tr><td>Ranking poor homes (agreement with true potential)</td><td class="num">${fmt(v.ranking.methods.greeniq_improvement_potential.spearman_vs_true_potential, 2)}</td><td class="num">${fmt(v.ranking.methods["baseline_total_kwh (big-house trap)"].spearman_vs_true_potential, 2)} <span class="muted small">rank by total use</span></td><td>${cmp(v.ranking.methods.greeniq_improvement_potential.spearman_vs_true_potential, v.ranking.methods["baseline_total_kwh (big-house trap)"].spearman_vs_true_potential, false)}</td></tr>
        <tr><td>Energy rating when there is no EPC (error, SAP points)</td><td class="num">${fmt(v.rating.rating_model.mae, 1)}</td><td class="num">${fmt(v.rating.peer_median_baseline.mae, 1)}</td><td>${cmp(v.rating.rating_model.mae, v.rating.peer_median_baseline.mae)}</td></tr>
        <tr><td>Score band agrees with the true inputs</td><td class="num">${fmt(100 * v.score.band_agreement, 1)}%</td><td></td><td></td></tr>
        <tr><td>Recommended upgrades that were truly feasible</td><td class="num">${fmt(100 - 100 * v.feasibility.violation_rate, 1)}%</td><td></td><td></td></tr>
      </tbody></table></div>
      <p class="small muted">Scored against the simulated world's hidden truth on the validation split; the untouched test split is reported once in reports/EVALUATION.md. Agreement with simulated data shows the method works; it is not proof of real-world accuracy — that is what the real-home checks above are for.</p>` : `<div class="empty">Run <code>uv run greeniq evaluate</code> to generate these.</div>`}</section>

    <section id="s-assumptions" class="card"><h2>Judgement calls we made</h2>
      <p class="small muted">${esc(e.assumptions.note)}</p>
      <div class="table-wrap"><table class="t plain"><thead><tr><th>Assumption</th><th>Value</th><th>Used for</th><th>Why / source</th></tr></thead><tbody>
      ${Object.entries(e.assumptions.items).map(([k2, a]) => `<tr><td><code>${esc(k2)}</code></td><td class="num">${typeof a.value === "object" ? esc(Object.entries(a.value).map(([x, y]) => `${x} ${y}`).join(", ")) : fmt(a.value, a.value % 1 ? 2 : 0)} <span class="muted small">${esc(a.unit)}</span></td>
        <td class="small wrap">${esc(a.used_for)}</td><td class="small wrap">${esc(a.why)} <span class="muted">${esc(a.source)}</span></td></tr>`).join("")}</tbody></table></div></section>
  </div>`;
  main.querySelectorAll("[data-jump]").forEach((a) => (a.onclick = (ev) => { ev.preventDefault(); $("#s-" + a.dataset.jump).scrollIntoView({ behavior: "smooth" }); }));
  const want = location.hash.split("#")[2];
  if (want) $("#s-" + want)?.scrollIntoView();
}

// =====================================================================================
// Charts and renderers shared by the pages above
// =====================================================================================
function fuelSplitMini(op) {
  // Answers "greener means lower bills everywhere": gas falls a lot, electricity can rise.
  return `<div class="small" style="margin-top:8px;display:flex;gap:12px;flex-wrap:wrap">
    <span>${fuelChange(op.gas_gwh, "gs", "Gas", 1)} <span class="muted">GWh</span></span>
    <span data-tip="Heat pumps raise electricity while cutting gas by more">${fuelChange(op.electricity_gwh, "el", "Electricity", 2)} <span class="muted">GWh ⓘ</span></span></div>`;
}


// Vertical bars: one per band (identity by position + label; band colour is an ordinal ramp)
function bandBars(dist) {
  const cats = [...BANDS, "Undetermined"];
  const max = Math.max(...cats.map((c) => dist[c] || 0), 1);
  const W = 640, H = 230, padL = 8, padB = 34, padT = 22, bw = 64, gap = (W - padL * 2 - bw * cats.length) / (cats.length - 1);
  const total = cats.reduce((s, c) => s + (dist[c] || 0), 0);
  const bars = cats.map((c, i) => {
    const v = dist[c] || 0, h = ((H - padB - padT) * v) / max, x = padL + i * (bw + gap), y = H - padB - h;
    return `<g data-tip="<b>${esc(c)}</b><br>${fmt(v)} homes · ${fmt((100 * v) / total, 1)}%">
      <rect x="${x}" y="${padT}" width="${bw}" height="${H - padB - padT}" fill="transparent"/>
      <path d="M${x},${H - padB} v${-Math.max(h - 4, 0)} q0,-4 4,-4 h${bw - 8} q4,0 4,4 v${Math.max(h - 4, 0)} z" style="fill:${bandColor(c)}"/>
      <text class="val num" x="${x + bw / 2}" y="${y - 6}" text-anchor="middle">${fmt(v)}</text>
      <text x="${x + bw / 2}" y="${H - padB + 16}" text-anchor="middle">${esc(c === "Highly efficient" ? "Highly eff." : c)}</text></g>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Homes per score band">
    <line x1="0" x2="${W}" y1="${H - padB}" y2="${H - padB}" style="stroke:var(--line-2)"/>${bars}</svg>
    <p class="small muted">Undetermined = the score's possible range spans two bands because an input is missing; we don't guess.</p>`;
}

// 100% stacked rows per group

function gateBadge(ex) {
  if (!ex?.gate) return "";
  const cl = ex.gate.claims.filter((c) => c.status !== "exempt"), ok = cl.filter((c) => c.status === "grounded").length;
  return `<p class="small muted" style="margin-top:8px">${ex.mode === "llm" ? "Language model" : "Template narrator"} · grounding gate ${ex.gate.passed ? "✓ passed" : "✗"} · ${ok}/${cl.length} numbers traced to computed facts${ex.note ? ` · ${esc(ex.note)}` : ""}</p>`;
}

function peerCard(f) {
  const p = f.peer;
  if (!p) return "";
  const bar = (x) => `<div class="pbar"><div class="pfill" style="left:${x.percentile}%"></div></div>`;
  return `<div class="card"><div class="card-head"><div><h3>Homes like yours <span class="badge">real data</span></h3>
      <p class="hint">Compared with real ${esc(p.peer_group)} homes in England and Wales (DESNZ NEED, 2024 meter year).</p></div></div>
    ${p.fuels.map((x) => `<div style="margin:10px 0"><div class="small" style="display:flex;justify-content:space-between">
        <span class="fuel ${x.fuel === "gas" ? "gs" : "el"}">${cap(x.fuel)}</span>
        <span class="num">${fmt(x.actual_kwh)} kWh vs typical ${fmt(x.peer_median_kwh)} · uses more than ${x.percentile}% of ${fmt(x.n_peers)} similar real homes</span></div>
        ${bar(x)}</div>`).join("")}
    ${p.signals.map((s) => `<div class="banner" style="margin:8px 0 0">${esc(s)}</div>`).join("")}</div>`;
}

function decomposition(f, after) {
  const comps = f.score.components;
  const gapKey = comps.filter((c) => c.points_available != null).sort((a, b) => b.points_available - a.points_available)[0]?.key;
  const ca = after?.package?.components_after || null;
  const sa = after?.package?.score_after;
  const head = `<div class="card-head"><div><h3>Why the score is ${f.score.score ?? "a range"}</h3>
    <p class="hint">Each bar is one of the 7 fixed-weight parts: filled = points earned, dashed = points available.${ca ? " Outlined = after your change." : ""}</p></div>
    ${ca && sa != null ? `<div class="badge num" style="font-size:14px">${f.score.score} → <b style="color:var(--accent)">${sa}</b> ${bandBadge(after.package.band_after)}</div>` : ""}</div>`;
  const rows = comps.map((c) => {
    const max = c.weight * 100;
    const have = c.contribution;
    const aft = ca ? ca[c.key] : null;
    const pct = (x) => `${(100 * x) / 25}%`; // 25 = largest weight × 100, so bar lengths compare across rows
    return `<div class="drow" data-tip="<b>${esc(c.label)}</b> (weight ${fmt(c.weight * 100)}%)<br>${esc(c.input_display)}<br>sub-score ${c.sub_score == null ? "unavailable" : fmt(c.sub_score, 0) + "/100"} → ${have == null ? "—" : fmt(have, 1)} of ${fmt(max)} points${aft != null ? `<br>after: ${fmt(aft, 1)}` : ""}">
      <div class="lab">${esc(c.label)}${c.key === gapKey ? `<span class="gapmark">biggest gap</span>` : ""}<small>${esc(c.input_display)}</small></div>
      <div class="dtrack"><div class="max" style="width:${pct(max)}"></div>${have != null ? `<div class="have" style="width:${pct(have)}"></div>` : ""}
        ${aft != null ? `<div class="after" style="width:${pct(aft)}"></div>` : ""}</div>
      <div class="pts num">${have == null ? "—" : rc(c.receipt, fmt(have, 1))}<span class="muted">/${fmt(max)}</span> ${tag(c.basis)}</div></div>`;
  }).join("");
  return head + `<div class="decomp">${rows}</div>`;
}


function scenarioResult(base, r) {
  const f = r.facts, pk = f.package;
  if (!pk) return `<div class="empty">${esc(r.explanation.sentences.map((s) => s.text).join(" "))}</div>`;
  const im = pk.impact;
  const cell = (label, before, after, saving, cls) => `<div class="d"><span class="small ${cls ? "fuel " + cls : "muted"}">${label}</span>
    <b class="num">${fmt(before)} → ${fmt(after)}</b><span class="small num ${saving > 0 ? "down" : saving < 0 ? "up" : ""}">${saving > 0 ? "▼ " : saving < 0 ? "▲ " : ""}${fmt(Math.abs(saving))} kWh/yr</span></div>`;
  return `<div class="card-head"><div><h3>What-if result</h3><p class="hint">${esc(f.scenario?.name || "")} · engine re-run · facts ${esc(f.facts_id)}</p></div>${tag("estimated", "engine estimate, not a guarantee")}</div>
    <div class="delta-grid">
      ${cell("Electricity", im.electricity.baseline_kwh, im.electricity.after_kwh, im.electricity.saving_kwh, "el")}
      ${cell("Gas", im.gas.baseline_kwh, im.gas.after_kwh, im.gas.saving_kwh, "gs")}
      <div class="d"><span class="small muted">Carbon</span><b class="num">${rc(im.carbon.receipt, (im.carbon.total_tonnes >= 0 ? "▼ " : "▲ ") + fmt(Math.abs(im.carbon.total_tonnes), 2))} t</b><span class="small muted">CO₂e per year</span></div>
      <div class="d"><span class="small muted">Score</span><b class="num">${base.score.score ?? "—"} → ${pk.score_after ?? "—"}</b><span class="small muted">EPC ${esc(pk.epc_band_before || "?")} → ${esc(pk.epc_band_after || "?")}</span></div>
    </div>
    <div class="explain">${r.explanation.sentences.map((s) => `<p>${esc(s.text)}${S.mode === "evidence" ? ` <span class="ref" style="display:inline">← ${esc(s.refs.join(", "))}</span>` : ""}</p>`).join("")}</div>`;
}

const SHORT = { loft_insulation: "Loft", cavity_wall_insulation: "Cavity wall", solid_wall_insulation: "Solid wall",
  glazing_upgrade: "Glazing", smart_controls: "Controls", air_source_heat_pump: "Heat pump", solar_pv: "Solar PV" };
const short = (m) => SHORT[m] || nice(m);
const LS = { budget: +store.get("budget", 10000) };

function planCards(L, byKey, st) {
  return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px">${L.plans.map((p) => {
    const o = p.package_key ? byKey[p.package_key] : null;
    const on = st.plan === p.id;
    return `<div class="rec ${on ? "lead" : ""}" data-plan="${p.id}" data-key="${o ? o.key : ""}" style="cursor:${o ? "pointer" : "default"};margin:0">
      <div class="r1"><span>${esc(p.title)}</span>${on ? `<span class="badge">selected</span>` : ""}</div>
      <div class="small muted" style="margin:4px 0 10px">${esc(p.definition)}</div>
      ${o ? `<div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:10px">${o.measures.map((m) => `<span class="badge">${esc(short(m))}</span>`).join("")}</div>
        <div class="num"><b style="font-size:18px">${fmt(o.carbon_kg / 1000, 2)}</b> <span class="small muted">tCO₂e/yr saved</span></div>
        <div class="small num">${gbp(o.cost_low)}–${gbp(o.cost_high)} · score → <b>${o.score_after ?? "—"}</b> ${esc(o.band_after || "")} · EPC ${esc(o.epc_band_after || "?")}</div>
        <div class="small num" style="margin-top:4px">${fuelChange(o.electricity_saving_kwh, "el", "Elec")} ${fuelChange(o.gas_saving_kwh, "gs", "Gas")} <span class="muted">kWh/yr</span></div>`
        : `<div class="empty">${esc(p.note || "Not available")}</div>`}</div>`;
  }).join("")}</div>`;
}

function frontier(L, byKey, selKey) {
  const pts = L.packages;
  if (!pts.length) return `<div class="empty">No feasible packages.</div>`;
  const W = 760, H = 320, pl = 56, pr = 16, pt = 16, pb = 40;
  const xmax = Math.max(...pts.map((o) => o.cost_mid)) * 1.05;
  const ys = pts.map((o) => o.carbon_kg / 1000);
  const ymin = Math.min(0, ...ys), ymax = Math.max(...ys) * 1.08 || 1;
  const X = (v) => pl + ((W - pl - pr) * v) / xmax, Y = (v) => H - pb - ((H - pt - pb) * (v - ymin)) / (ymax - ymin);
  const ticks = (max, n) => Array.from({ length: n + 1 }, (_, i) => (max * i) / n);
  const named = {};
  L.plans.filter((p) => p.package_key).forEach((p) => { named[p.package_key] = named[p.package_key] ? named[p.package_key] + " · " + p.title : p.title; });
  const edge = pts.filter((o) => o.pareto_carbon).sort((a, b) => a.cost_mid - b.cost_mid);
  const grid = ticks(xmax, 4).map((t) => `<line x1="${X(t)}" x2="${X(t)}" y1="${pt}" y2="${H - pb}" style="stroke:var(--line)"/><text x="${X(t)}" y="${H - pb + 16}" text-anchor="middle">£${fmt(t / 1000, 0)}k</text>`).join("")
    + ticks(ymax, 4).map((t) => `<line x1="${pl}" x2="${W - pr}" y1="${Y(t)}" y2="${Y(t)}" style="stroke:var(--line)"/><text x="${pl - 8}" y="${Y(t) + 4}" text-anchor="end">${fmt(t, 1)}</text>`).join("");
  const dots = pts.map((o) => {
    const tipTxt = `<b>${o.measures.map(short).join(" + ")}</b><br>${gbp(o.cost_low)}–${gbp(o.cost_high)} · ${fmt(o.carbon_kg / 1000, 2)} t/yr${o.respects_prerequisites ? "" : `<br>skips: ${o.missing_prerequisites.map(short).join(", ")}`}${o.pareto_carbon ? "<br>efficient: nothing cheaper saves as much" : ""}`;
    const sel = o.key === selKey;
    return `<g data-pkg="${o.key}" data-tip="${esc(tipTxt)}" style="cursor:pointer"><circle cx="${X(o.cost_mid)}" cy="${Y(o.carbon_kg / 1000)}" r="12" fill="transparent"/>
      <circle cx="${X(o.cost_mid)}" cy="${Y(o.carbon_kg / 1000)}" r="${sel ? 7 : 5}" style="${o.respects_prerequisites ? "fill:var(--accent)" : "fill:var(--card);stroke:var(--ink-3);stroke-width:1.5"};${sel ? "stroke:var(--ink);stroke-width:2.5" : ""};opacity:${o.respects_prerequisites ? (o.pareto_carbon ? 1 : .45) : .9}"/></g>`;
  }).join("");
  const labels = Object.entries(named).map(([k, t]) => {
    const o = byKey[k], x = X(o.cost_mid), right = x > W - 170;
    return `<text class="val" x="${right ? x - 9 : x + 9}" y="${Y(o.carbon_kg / 1000) - 9}" text-anchor="${right ? "end" : "start"}">${esc(t)}</text>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Cost vs carbon for every feasible package">${grid}
    <polyline points="${edge.map((o) => `${X(o.cost_mid)},${Y(o.carbon_kg / 1000)}`).join(" ")}" style="fill:none;stroke:var(--accent);stroke-width:2"/>
    ${dots}${labels}<text x="${(W + pl) / 2}" y="${H - 4}" text-anchor="middle">Mid-point cost</text>
    <text transform="translate(14 ${(H - pb) / 2}) rotate(-90)" text-anchor="middle">tCO₂e saved per year</text></svg>
    <div class="legend"><span><span class="band-sw" style="background:var(--accent);border-radius:50%"></span>respects the install order</span>
    <span><span class="band-sw" style="border:1.5px solid var(--ink-3);border-radius:50%"></span>skips a prerequisite</span>
    <span><span style="width:16px;height:2px;background:var(--accent);display:inline-block"></span>efficient edge (Pareto)</span><span class="muted">· click a point to select it</span></div>
    ${pts.some((o) => !o.respects_prerequisites && o.carbon_kg > 0) ? `<p class="small muted" style="margin:8px 0 0">Hollow points skip a prerequisite, e.g. a heat pump before insulating.
      Some cut more carbon per £ today; we show them rather than hide them. The named plans follow fabric-first sequencing (UK whole-house retrofit guidance)
      because a heat pump fitted to the uninsulated home uses more electricity and can lower the EPC rating — select one to see it.</p>` : ""}`;
}




function selectedSummary(f, r, opt) {
  const pk = r.facts.package;
  if (!pk) return `<div class="empty">${esc(r.explanation.sentences.map((s) => s.text).join(" "))}</div>`;
  const im = pk.impact;
  const bar = (label, cls, b, a) => {
    const m = Math.max(b, a, 1);
    return `<div style="margin:8px 0"><div class="small" style="display:flex;justify-content:space-between"><span class="fuel ${cls}">${label}</span><span class="num">${fmt(b)} → <b>${fmt(a)}</b> kWh/yr</span></div>
      <div style="display:grid;gap:3px;margin-top:4px"><div style="height:8px;width:${(100 * b) / m}%;background:color-mix(in srgb, var(--${cls === "el" ? "elec" : "gas"}) 40%, var(--card));border-radius:4px" data-tip="Today: ${fmt(b)} kWh"></div>
      <div style="height:8px;width:${(100 * a) / m}%;background:var(--${cls === "el" ? "elec" : "gas"});border-radius:4px" data-tip="After: ${fmt(a)} kWh"></div></div></div>`;
  };
  return `<div class="card-head"><div><h3>Selected: ${esc(pk.measures.map(short).join(" + "))}</h3>
      <p class="hint">${esc(r.facts.scenario?.name || "")} · engine re-run · facts ${esc(r.facts.facts_id)}${opt && !opt.respects_prerequisites ? ` · <span class="up">skips ${esc(opt.missing_prerequisites.map(short).join(", "))}</span>` : ""}</p></div>${tag("estimated", "engine estimate, not a guarantee")}</div>
    <div class="two"><div>
      ${bar("Electricity", "el", im.electricity.baseline_kwh, im.electricity.after_kwh)}
      ${bar("Gas", "gs", im.gas.baseline_kwh, im.gas.after_kwh)}
      <div class="delta-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
        <div class="d"><span class="small muted">Carbon</span><b class="num">${rc(im.carbon.receipt, (im.carbon.total_tonnes >= 0 ? "▼ " : "▲ ") + fmt(Math.abs(im.carbon.total_tonnes), 2))} t/yr</b></div>
        <div class="d"><span class="small muted">Score · EPC</span><b class="num">${f.score.score ?? "—"} → ${pk.score_after ?? "—"}</b><span class="small muted">${esc(pk.epc_band_before || "?")} → ${esc(pk.epc_band_after || "?")}</span></div>
        <div class="d"><span class="small muted">Cost</span><b class="num">${rc(pk.receipt, `${gbp(pk.cost_low)}–${gbp(pk.cost_high)}`)}</b><span class="small muted">indicative</span></div></div>
      ${r.facts.value?.status === "available" && r.facts.value.uplift_pct_range ? `<div class="small">Value: ${tag("estimated", r.facts.value.caveat)} ${
        r.facts.value.uplift_pct_range[1] === 0 && r.facts.value.uplift_pct_range[0] === 0 ? "the EPC band does not change, so no indicative value uplift."
        : `indicative <b class="num">${fmt(r.facts.value.uplift_pct_range[0], 1)}% to ${fmt(r.facts.value.uplift_pct_range[1], 1)}%</b> — a range, not a promise.`}</div>` : ""}
    </div><div class="explain">${r.explanation.sentences.map((s) => `<p>${esc(s.text)}${S.mode === "evidence" ? ` <span class="ref" style="display:inline">← ${esc(s.refs.join(", "))}</span>` : ""}</p>`).join("")}</div></div>`;
}



function energyTable(m) {
  const row = (fuel) => {
    const t = m.energy[fuel].test;
    const names = { global_median: "Global median (naive)", peer_median: "Peer median × area (baseline)", physics: "Physics (RdSAP-lite)", gbm: "Gradient boosting (GreenIQ)" };
    return Object.entries(names).map(([k, l]) => t[k] ? `<tr><td>${cap(fuel)}</td><td>${l}</td><td class="num">${fmt(t[k].mae)}</td><td class="num">${fmt(t[k].r2, 3)}</td></tr>` : "").join("");
  };
  return `<div class="card"><h3>Baseline energy model vs. simple baselines</h3><p class="hint">Used only when a home lacks usable meter data; output is labelled “estimate”.</p>
    <div class="table-wrap"><table class="t"><thead><tr><th>Fuel</th><th>Method</th><th>MAE kWh</th><th>R²</th></tr></thead><tbody>${row("electricity")}${row("gas")}</tbody></table></div></div>`;
}
function rankingTable(m) {
  const r = m.ranking.methods;
  return `<div class="card"><h3>Ranking poor homes by improvement potential</h3><p class="hint">Agreement with the simulator's counterfactual truth (${fmt(m.ranking.poor_homes_ranked)} poor test homes).</p>
    <div class="table-wrap"><table class="t"><thead><tr><th>Method</th><th>Spearman vs truth</th><th>Top-20% precision</th><th>Correlation with size</th></tr></thead><tbody>
    ${Object.entries(r).map(([k, v]) => `<tr><td>${esc(nice(k))}</td><td class="num">${fmt(v.spearman_vs_true_potential, 3)}</td><td class="num">${fmt(v.top20pct_precision, 2)}</td><td class="num">${fmt(v.spearman_with_floor_area, 2)}</td></tr>`).join("")}
    </tbody></table></div><p class="small muted">The "big-house trap": ranking by total kWh mostly ranks by size. GreenIQ ranks by potential.</p></div>`;
}
