// GreenIQ — home energy command centre.
// The engine (FastAPI) computes every number. This UI only presents computed facts and
// gated explanations. No business logic, no invented numbers. One failed fetch never blanks the app.

// ──────────────────────────────────────────────────────────── helpers
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const words = (v) => String(v ?? "—").replace(/_/g, " ");
// read a {value,basis,note} input field (facts.inputs.*)
const iv = (field) => (field && typeof field === "object" && "value" in field) ? field.value : field;
const ib = (field) => (field && typeof field === "object" && "basis" in field) ? field.basis : undefined;
const store = {
  get: (k, d) => { try { const v = localStorage.getItem("giq." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem("giq." + k, JSON.stringify(v)); } catch {} },
};

const S = {
  pid: store.get("pid", null),
  objective: store.get("objective", "value_for_money"),
  labels: store.get("labels", false),   // show evidence word-tags inline
  theme: store.get("theme", "system"),
};
// repair any stale objective from older builds
if (!["value_for_money", "carbon", "energy"].includes(S.objective)) { S.objective = "value_for_money"; store.set("objective", S.objective); }

const OBJ_NAME = { value_for_money: "value for money (CO₂e saved per £)", carbon: "the most carbon saved", energy: "the most energy saved" };

// ── formatters
const fmt = (n, d = 0) => (n == null || Number.isNaN(n)) ? "—" : Number(n).toLocaleString("en-GB", { maximumFractionDigits: d, minimumFractionDigits: d });
const gbp = (n) => n == null ? "—" : "£" + Number(Math.round(n)).toLocaleString("en-GB");
const gbpK = (n) => n == null ? "—" : (Math.abs(n) >= 1000 ? "£" + fmt(n / 1000, n % 1000 ? 1 : 0) + "k" : gbp(n));
const pct = (n, d = 1) => n == null ? "—" : fmt(n, d) + "%";
const pctRange = (a, b) => (a == null || b == null) ? "—" : (a === b ? pct(a) : `${fmt(a, 1)}–${fmt(b, 1)}%`);
const kwh = (n) => n == null ? "—" : fmt(Math.round(n)) + " kWh";
const signed = (n, unit = "") => (n > 0 ? "−" : n < 0 ? "+" : "") + fmt(Math.abs(n)) + unit; // saving positive → shown as reduction

const BAND_VAR = { "Very poor": "--b-vp", "Poor": "--b-p", "Moderate": "--b-m", "Good": "--b-g", "Highly efficient": "--b-he" };
const bandCol = (b) => `var(${BAND_VAR[b] || "--b-u"})`;

// evidence basis → honest tag
const BASIS_TAG = { observed: "measured", metered: "measured", measured: "measured", estimated: "estimated", assumed: "assumed", unavailable: "unavailable" };
function tag(basis, why) {
  const t = BASIS_TAG[basis] || basis || "estimated";
  return S.labels || true ? `<span class="tag ${t}" title="${esc(why || t)}">${t}</span>` : "";
}

// receipt-linked number (opens drawer)
let RECEIPTS = {}; let rcSeq = 0;
function rc(text, receipt) {
  if (!receipt) return `<span class="num">${text}</span>`;
  const id = "r" + (rcSeq++); RECEIPTS[id] = receipt;
  return `<span class="rc num" data-receipt="${id}" role="button" tabindex="0" title="How this was worked out">${text}</span>`;
}

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2600);
}

// ──────────────────────────────────────────────────────────── data layer
async function api(path, body) {
  const opt = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined;
  const res = await fetch(path, opt);
  let data = null;
  try { data = await res.json(); } catch { /* non-json */ }
  if (!res.ok) {
    const msg = data?.error?.message || `${res.status} ${res.statusText}`;
    const e = new Error(msg); e.code = data?.error?.code || res.status; e.status = res.status; throw e;
  }
  return data;
}

// facts for the recommended package under the current objective
const factsCache = new Map();
async function loadFacts(pid, { fresh = false } = {}) {
  const key = pid + "|" + S.objective;
  if (!fresh && factsCache.has(key)) return factsCache.get(key);
  let out;
  if (S.objective === "value_for_money") out = await api(`/api/properties/${encodeURIComponent(pid)}`);
  else out = await api(`/api/properties/${encodeURIComponent(pid)}/scenarios`, { objective: S.objective, name: "Recommended package" });
  factsCache.set(key, out);
  return out;
}
const clearFacts = () => factsCache.clear();

let HEALTH = null, PROPS = null;
async function getHealth() { return HEALTH || (HEALTH = await api("/api/health")); }
async function getProps() { return PROPS || (PROPS = (await api("/api/properties?limit=500&sort=score")).items); }

// async render into a container with loading / error / retry
async function mount(el, fn, { label = "the engine" } = {}) {
  el.innerHTML = `<div class="loading"><span class="spinner"></span> Loading ${esc(label)}…</div>`;
  try { el.innerHTML = await fn(); afterRender(el); }
  catch (e) {
    el.innerHTML = `<div class="errbox"><b>Could not load ${esc(label)}.</b>${esc(e.message)}
      <div class="btn-row" style="margin-top:10px"><button class="btn sm" data-retry>Try again</button></div></div>`;
    $("[data-retry]", el)?.addEventListener("click", () => mount(el, fn, { label }));
  }
}

// ──────────────────────────────────────────────────────────── shared components
function bandChip(band, score, status) {
  if (!band) return `<span class="band-chip" style="background:var(--b-u)">Undetermined</span>`;
  return `<span class="band-chip" style="background:${bandCol(band)}">${esc(band)}</span>`;
}
function scoreRing(score, band, range) {
  const v = score != null ? score : (range ? (range[0] + range[1]) / 2 : 0);
  const disp = score != null ? score : (range ? `${range[0]}–${range[1]}` : "—");
  const small = score != null ? "/ 100" : "range";
  return `<div class="score-ring" style="--band-col:${bandCol(band)};--v:${v}">
    <div class="inner"><b style="font-size:${score != null ? 30 : 20}px">${disp}</b><small>${small}</small></div></div>`;
}
function dispositionPill(d) {
  const map = {
    recommend: ["worth", "Recommended now"], do_now: ["act", "Act now"],
    refer_for_survey: ["check", "Check first"], ask: ["check", "Needs info"],
    blocked: ["check", "Blocked"], no_action: ["none", "No action needed"],
  };
  const [cls, label] = map[d] || ["worth", d];
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}
function stateView(ico, title, msg) {
  return `<div class="state"><div class="ico">${ico}</div><h3>${esc(title)}</h3><p>${esc(msg)}</p></div>`;
}

// per-fuel before→after bar block
function fuelBlock(name, cssVar, b) {
  if (!b) return "";
  const max = Math.max(b.baseline_kwh, b.after_kwh, 1);
  const sav = b.saving_kwh;
  const dir = sav > 0 ? `<span class="delta good">${kwh(sav)} less</span>` : sav < 0 ? `<span class="delta bad">${kwh(-sav)} more</span>` : `<span class="muted">no change</span>`;
  return `<div class="fuel-block" style="--c:${cssVar}">
    <div class="fuel-head"><span class="name">${esc(name)}</span>${dir}</div>
    <div class="fuel-bars">
      <div class="fuel-bar"><span class="muted">Now</span><div class="track"><span style="width:${b.baseline_kwh / max * 100}%"></span></div><b class="num">${kwh(b.baseline_kwh)}</b></div>
      <div class="fuel-bar"><span class="muted">After</span><div class="track"><span style="width:${b.after_kwh / max * 100}%"></span></div><b class="num">${kwh(b.after_kwh)}</b></div>
    </div></div>`;
}

// the AI explanation card (score or recommendations) — gated, provider-labelled.
// Rendered as a pending placeholder; afterRender() fires renderAi once it's in the DOM.
function aiCard(pid, scope, title) {
  const id = "ai" + (rcSeq++);
  return `<div class="card" id="${id}" data-ai-pending data-ai-pid="${esc(pid)}" data-ai-scope="${esc(scope)}">
    <div class="nba-head"><span class="pill"><span class="ai-mark">✦</span> AI explanation</span><b>${esc(title)}</b></div>
    <div class="loading" style="padding:10px 0"><span class="spinner"></span> Writing from the computed facts…</div></div>`;
}
async function renderAi(id, pid, scope) {
  const el = document.getElementById(id); if (!el) return;
  try {
    const r = await api(`/api/properties/${encodeURIComponent(pid)}/explain?scope=${scope}&objective=${S.objective}`);
    const ex = r.explanation, prov = r.provider || {};
    const gateOk = ex.gate ? ex.gate.passed : true;
    const by = ex.mode === "llm" ? `${esc(prov.name)} model` : "checked template";
    el.querySelector(".loading")?.remove();
    el.insertAdjacentHTML("beforeend",
      `<div class="bubble" style="box-shadow:none;border:none;padding:0">
        ${ex.sentences.map((s) => `<p>${esc(s.text)}${S.labels ? ` <span class="muted small">← ${esc(s.refs.join(", "))}</span>` : ""}</p>`).join("")}
        <div class="by" style="margin-top:8px">Written by ${by} · <span class="ok">✓ every figure checked against the engine</span></div>
      </div>`);
  } catch (e) {
    el.querySelector(".loading")?.remove();
    el.insertAdjacentHTML("beforeend", `<div class="callout warn">The explanation service did not respond (${esc(e.message)}). The computed figures above are unaffected. <button class="btn sm ghost" data-reai="${id}|${pid}|${scope}">Retry</button></div>`);
  }
}

// ──────────────────────────────────────────────────────────── ROUTES
const ROUTES = {
  overview:     { group: "YOUR HOME", ico: "🏠", label: "Home overview", needs: "home", render: pageOverview },
  property:     { group: "YOUR HOME", ico: "📋", label: "My property", needs: "home", render: pageProperty },
  advisor:      { group: "YOUR HOME", ico: "✦", label: "AI energy advisor", needs: "home", render: pageAdvisor },
  improvements: { group: "YOUR HOME", ico: "🔧", label: "Improvements", needs: "home", render: pageImprovements },
  plans:        { group: "YOUR HOME", ico: "⚖", label: "Compare plans", needs: "home", render: pagePlans },
  energy:       { group: "YOUR HOME", ico: "⚡", label: "Energy & carbon", needs: "home", render: pageEnergy },
  value:        { group: "YOUR HOME", ico: "🏷", label: "Home value", needs: "home", render: pageValue },
  evidence:     { group: "YOUR HOME", ico: "📑", label: "Evidence & reports", needs: "home", render: pageEvidence },
  settings:     { group: "PREFERENCES", ico: "⚙", label: "Settings", render: pageSettings },
  help:         { group: "PREFERENCES", ico: "?", label: "Help & methodology", render: pageHelp },
  lender:       { group: "LENDER WORKSPACE", ico: "🏦", label: "Portfolio ranking", render: pageLender },
};

function buildNav() {
  const nav = $("#nav"); const groups = {};
  for (const [key, r] of Object.entries(ROUTES)) (groups[r.group] ||= []).push([key, r]);
  nav.innerHTML = Object.entries(groups).map(([g, items]) =>
    `<div class="nav-group">${esc(g)}</div>` +
    items.map(([key, r]) => `<a href="#/${key}" data-route="${key}"><span class="ico">${r.ico}</span>${esc(r.label)}</a>`).join("")
  ).join("");
}

function currentRoute() {
  const h = (location.hash.replace(/^#\//, "") || "overview").split("/");
  return { key: ROUTES[h[0]] ? h[0] : "overview", arg: h[1] };
}

async function route() {
  const { key } = currentRoute();
  const r = ROUTES[key];
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === key));
  $("#crumb").innerHTML = `<b>${esc(r.label)}</b>${S.pid && r.needs === "home" ? ` · ${esc(S.pid)}` : ""}`;
  $("#sidebar").classList.remove("open");
  const main = $("#main"); main.scrollTop = 0; window.scrollTo(0, 0);
  RECEIPTS = {};

  if (r.needs === "home" && !S.pid) { main.innerHTML = noHomeState(); afterRender(main); return; }
  try {
    main.innerHTML = `<div class="loading"><span class="spinner"></span> Loading…</div>`;
    main.innerHTML = await r.render();
    afterRender(main);
  } catch (e) {
    main.innerHTML = `<div class="errbox"><b>Something went wrong loading this page.</b>${esc(e.message)}
      <div class="btn-row" style="margin-top:10px"><button class="btn sm" onclick="location.reload()">Reload</button></div></div>`;
  }
}

function noHomeState() {
  return `<div class="page-head"><h1>Choose a home to begin</h1><div class="sub">Pick a property from the switcher on the left, or start with one of these examples.</div></div>
    <div class="grid cols-3" id="sample-homes"><div class="loading"><span class="spinner"></span> Loading examples…</div></div>`;
}

// wire up receipt links, retries, and any page-specific handlers after each render
function afterRender(root) {
  $$("[data-receipt]", root).forEach((el) => {
    const open = () => openReceipt(RECEIPTS[el.dataset.receipt]);
    el.onclick = open; el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
  });
  $$("[data-reai]", root).forEach((el) => el.onclick = () => { const [id, pid, scope] = el.dataset.reai.split("|"); const c = document.getElementById(id); if (c) { c.querySelector(".callout")?.remove(); c.insertAdjacentHTML("beforeend", `<div class="loading" style="padding:8px 0"><span class="spinner"></span> Retrying…</div>`); renderAi(id, pid, scope); } });
  $$("[data-goto]", root).forEach((el) => el.onclick = () => { location.hash = "#/" + el.dataset.goto; });
  // pending AI explanation cards (now that they're in the DOM)
  $$("[data-ai-pending]", root).forEach((el) => { el.removeAttribute("data-ai-pending"); renderAi(el.id, el.dataset.aiPid, el.dataset.aiScope); });
  // sample homes on the no-home state
  if ($("#sample-homes", root)) fillSampleHomes();
}

async function fillSampleHomes() {
  try {
    const props = await getProps();
    const pick = [props.find((p) => (p.score || 0) > 0 && p.score < 35), props.find((p) => p.band === "Moderate"), props.find((p) => p.band === "Good")].filter(Boolean);
    $("#sample-homes").innerHTML = pick.map((p) => `<div class="card" style="cursor:pointer" data-pick="${p.property_id}">
      <div class="score-hero"><div style="--band-col:${bandCol(p.band)}">${scoreRing(p.score, p.band, p.score_range)}</div>
      <div><h3>${esc(p.property_id)}</h3><div class="small muted">${esc(p.property_type || "")} · ${esc(p.region || "")} · ${fmt(p.floor_area_m2)} m²</div>
      <div style="margin-top:6px">${bandChip(p.band)}</div></div></div>
      <div class="small muted" style="margin-top:10px">${esc(p.top_issue || "")}</div></div>`).join("");
    $$("[data-pick]").forEach((el) => el.onclick = () => selectHome(el.dataset.pick));
  } catch (e) { $("#sample-homes").innerHTML = `<div class="errbox">${esc(e.message)}</div>`; }
}

// ──────────────────────────────────────────────────────────── PAGES
function pageHead(title, sub) { return `<div class="page-head"><h1>${esc(title)}</h1>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`; }

// ── Home overview ──────────────────────────────────────────
async function pageOverview() {
  const { facts: f } = await loadFacts(S.pid);
  const sum = f.property_summary, sc = f.score, pkg = f.package, nba = f.next_best_action, val = f.value;
  const purchased = (f.baseline?.electricity?.annual_kwh || 0) + (f.baseline?.gas?.annual_kwh || 0);
  const issues = (sc.issues || []).slice(0, 3);
  const recs = (f.plan || []).slice(0, 3);

  return `${pageHead("Home overview", `A plain-language read of <b>${esc(S.pid)}</b> — where it stands today and the single most useful next step.`)}

  <div class="section-eyebrow">01 · Your home today</div>
  <div class="card pad-lg">
    <div class="hero-identity">
      <div class="score-hero">
        ${scoreRing(sc.score, sc.band, sc.score_range)}
        <div>
          <div style="margin-bottom:6px">${bandChip(sc.band, sc.score)} ${sc.is_poor ? `<span class="pill act" style="margin-left:6px">Poor energy efficiency</span>` : ""}</div>
          <h2>Green Home Score ${sc.status === "provisional" ? `<span class="tag assumed" title="Some inputs are assumed">provisional</span>` : sc.status === "partial" ? `<span class="tag estimated">range only</span>` : ""}</h2>
          <div class="small muted">${sc.score != null ? `${sc.band} band` : `Not enough data for a point score — shown as a range`} · <a href="#/property">see the full breakdown →</a></div>
        </div>
      </div>
      <div class="identity-facts">
        <div><span class="k">Property</span><b>${esc(sum.property_type || "—")}</b></div>
        <div><span class="k">Region</span><b>${esc(sum.region || "—")}</b></div>
        <div><span class="k">Floor area</span><b>${fmt(sum.floor_area_m2)} m²</b></div>
        <div><span class="k">Age</span><b>${esc((sum.age_band || "").replace(/_/g, " "))}</b></div>
        <div><span class="k">Heating</span><b>${esc((sum.heating_system_recorded || "—").replace(/_/g, " "))}</b></div>
        <div><span class="k">EPC rating</span><b>${esc(f.epc_band || "—")}</b></div>
      </div>
    </div>
    <div class="grid cols-3" style="margin-top:18px">
      <div class="card" style="box-shadow:none"><div class="stat"><span class="k">Energy purchased now</span><span class="v">${rc(kwh(purchased), f.baseline?.electricity?.receipt)}<span style="font-size:14px" class="muted">/yr</span></span><span class="foot">electricity + gas · ${tag(f.baseline_basis)} · ${fmt(f.intensity_kwh_m2?.value)} kWh/m²</span></div></div>
      <div class="card" style="box-shadow:none"><div class="stat"><span class="k">Annual carbon now</span><span class="v">${rc(fmt(f.baseline_emissions_kg?.value / 1000, 2), f.baseline_emissions_kg && { output: "baseline carbon", value: f.baseline_emissions_kg.value, unit: "kg CO2e/yr", method: f.baseline_emissions_kg.note })} <span style="font-size:14px" class="muted">t CO₂e</span></span><span class="foot">${tag(f.baseline_emissions_kg?.basis)} from per-fuel use</span></div></div>
      <div class="card" style="box-shadow:none"><div class="stat"><span class="k">Confidence</span><span class="v sm" style="text-transform:capitalize">${esc(f.confidence?.level || "—")}</span><span class="foot">${esc((f.confidence?.reasons || [])[0] || "all key inputs measured")}</span></div></div>
    </div>
  </div>

  <div class="section">
    <div class="section-eyebrow">02 · Your most important next step</div>
    <div class="card nba-card">
      <div class="nba-head">${dispositionPill(nba.disposition)}<h2>${esc(nba.headline)}</h2></div>
      <ul class="nba-reasons">${(nba.reasons || []).map((r) => `<li><span class="rico">›</span><span>${esc(r.text)}</span></li>`).join("")}</ul>
      ${nba.benefit != null ? `<div class="small muted" style="margin-top:10px">Expected benefit: <b>${fmt(nba.benefit, 1)} ${esc(nba.benefit_unit || "")}</b> · confidence ${esc(nba.confidence || "")}</div>` : ""}
      <div class="btn-row" style="margin-top:14px">
        ${nba.action?.kind === "retrofit" ? `<button class="btn primary" data-goto="improvements">View recommendation</button>` : `<button class="btn primary" data-goto="property">What we need to confirm</button>`}
        <button class="btn" data-ask="${esc(nba.headline)}">Ask the advisor why</button>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-eyebrow">03 · Understand your home</div>
    <div class="grid cols-2">
      <div class="card"><h3>What's holding your home back?</h3><div class="card-sub">The components losing the most points.</div>
        ${issues.length ? `<ul class="issue-list">${issues.map((i) => `<li><b>${esc(i.label)}</b><span class="muted small" style="flex:1">${esc((i.text || "").replace(i.label + ": ", "").split(" (")[0])}</span><span class="pts">−${fmt(i.points_available, 1)} pts</span></li>`).join("")}</ul>`
          : `<p class="muted">No component scores below the issue threshold — this home is well balanced.</p>`}
        <div class="btn-row" style="margin-top:12px"><button class="btn sm" data-goto="property">Score breakdown</button></div>
      </div>
      <div class="card"><h3>Outcomes if you act</h3><div class="card-sub">Baseline vs the recommended plan (an estimate, not a selected job).</div>
        ${pkg ? `<div class="grid cols-2" style="gap:12px">
          <div class="stat"><span class="k">Score</span><span class="v sm">${sc.score ?? "—"} → ${rc(pkg.score_after, pkg.improvement_potential?.receipt)}</span><span class="foot">${esc(sc.band || "—")} → ${esc(pkg.band_after || "—")}</span></div>
          <div class="stat"><span class="k">Purchased energy</span><span class="v sm delta good">−${pct(pkg.improvement_potential?.pct)}</span><span class="foot">${rc(kwh(pkg.impact?.net_saving_kwh), pkg.impact?.carbon?.receipt)} less a year</span></div>
          <div class="stat"><span class="k">Carbon</span><span class="v sm delta good">−${fmt(pkg.impact?.carbon?.total_tonnes, 2)} t</span><span class="foot">CO₂e a year</span></div>
          <div class="stat"><span class="k">Indicative value</span><span class="v sm">${val?.status === "available" && val.uplift_pct_range ? `+${pctRange(val.uplift_pct_range[0], val.uplift_pct_range[1])}` : "—"}</span><span class="foot">${val?.status === "available" ? "range, not a promise" : "no band change → no uplift"}</span></div>
        </div><div class="btn-row" style="margin-top:12px"><button class="btn sm" data-goto="plans">Compare plans</button><button class="btn sm ghost" data-goto="energy">Energy & carbon detail</button></div>`
          : `<p class="muted">No feasible package for this home yet.</p>`}
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-eyebrow">04 · Explore your options</div>
    <div class="grid cols-3">
      ${recs.length ? recs.map((p) => `<div class="rec-card"><div style="display:flex;justify-content:space-between;align-items:center"><h4>${esc(p.name)}</h4><span class="suit ${p.suitability}">${esc(p.suitability)}</span></div>
        <div class="effect">${esc(p.rationale || "")}</div>
        <div class="small muted">${p.standalone ? perFuelMini(p.standalone) : ""}</div>
        <div class="btn-row" style="margin-top:4px"><button class="btn sm ghost" data-goto="improvements">Details →</button></div></div>`).join("")
        : `<p class="muted">No feasible improvements identified.</p>`}
    </div>
  </div>

  <div class="section">
    <div class="section-eyebrow">05 · Ask GreenIQ</div>
    <div class="card">
      <h3>What would you like to understand?</h3><div class="card-sub">Ask about your score, energy use, a retrofit, or a what-if. Every answer is computed first, then explained.</div>
      <form class="ai-entry" id="ov-ask"><input placeholder="e.g. What if I install a heat pump and solar?" aria-label="Ask the advisor"><button class="btn primary" type="submit">Ask</button></form>
      <div class="starter-chips">
        ${["Why do I score this?", "What should I do first?", "What if I install a heat pump?", "Could it raise my home's value?"].map((q) => `<button class="chip" data-ask="${esc(q)}">${esc(q)}</button>`).join("")}
      </div>
    </div>
  </div>`;
}
function perFuelMini(s) {
  const bits = [];
  if (s.gas?.saving_kwh) bits.push(`gas ${s.gas.saving_kwh > 0 ? "−" : "+"}${kwh(Math.abs(s.gas.saving_kwh))}`);
  if (s.electricity?.saving_kwh) bits.push(`elec ${s.electricity.saving_kwh > 0 ? "−" : "+"}${kwh(Math.abs(s.electricity.saving_kwh))}`);
  if (s.carbon?.total_tonnes) bits.push(`${fmt(s.carbon.total_tonnes, 2)} t CO₂e`);
  return bits.join(" · ");
}

// ── My property (facts + score breakdown + before-you-act + evidence) ──────
async function pageProperty() {
  const { facts: f } = await loadFacts(S.pid);
  const sc = f.score, sum = f.property_summary;
  const sumContrib = (sc.components || []).reduce((a, c) => a + c.contribution, 0);
  const openItems = [...(f.conflicts || []).map((c) => ({ kind: "conflict", ...c })), ...(f.questions || []).map((q) => ({ kind: "question", ...q }))];

  return `${pageHead("My property", `Every input, every sub-score, and anything still unresolved for <b>${esc(S.pid)}</b>.`)}

  <div class="card pad-lg"><div class="hero-identity">
    <div class="score-hero">${scoreRing(sc.score, sc.band, sc.score_range)}<div><div>${bandChip(sc.band, sc.score)}</div><h2 style="margin-top:6px">${sc.score != null ? `${sc.score}/100` : (sc.score_range ? `${sc.score_range[0]}–${sc.score_range[1]}` : "—")}</h2><div class="small muted">${esc(sc.status)} · confidence ${esc(f.confidence?.level)}</div></div></div>
    <div class="identity-facts">
      <div><span class="k">Type</span><b>${esc(words(sum.property_type))}</b></div>
      <div><span class="k">Age band</span><b>${esc(words(sum.age_band))} ${tag(ib(f.inputs?.age_band))}</b></div>
      <div><span class="k">Walls</span><b>${esc(words(iv(f.inputs?.wall_type)))}${iv(f.inputs?.wall_insulated) ? ", insulated" : ", uninsulated"} ${tag(ib(f.inputs?.wall_type))}</b></div>
      <div><span class="k">Loft</span><b>${iv(f.inputs?.loft_insulation_mm) != null ? iv(f.inputs.loft_insulation_mm) + " mm" : "—"} ${tag(ib(f.inputs?.loft_insulation_mm))}</b></div>
      <div><span class="k">Glazing</span><b>${esc(words(iv(f.inputs?.glazing)))} ${tag(ib(f.inputs?.glazing))}</b></div>
      <div><span class="k">EPC</span><b>${esc(f.epc_band || "—")} ${sum.epc_year ? `(${sum.epc_year})` : ""}</b></div>
    </div>
  </div></div>

  <div class="section"><h2>Score breakdown</h2>
    <div class="card">
      <div class="card-sub">Score = Σ (weight × sub-score). A better state never lowers a sub-score. Each contribution reconciles to the total.</div>
      ${(sc.components || []).map((c) => `<div class="comp-row">
        <div class="comp-name">${esc(c.label)} <span class="muted small">(${pct(c.weight * 100, 0)})</span> ${tag(c.basis, c.explanation)}
          <small>${esc(c.input_display || "")}</small></div>
        <div class="comp-bar"><div class="bar"><span style="width:${c.sub_score}%;background:${bandCol(sc.band)}"></span></div><div class="small muted" style="margin-top:3px">sub-score ${fmt(c.sub_score, 0)}/100</div></div>
        <div class="comp-contrib">${rc("+" + fmt(c.contribution, 1), c.receipt)}<small>points</small></div>
      </div>`).join("")}
      <div class="comp-row" style="border-top:2px solid var(--line-2);font-weight:700"><div>Total</div><div></div><div class="comp-contrib">${fmt(sumContrib, 1)}<small>→ ${sc.score ?? "range"}</small></div></div>
    </div>
  </div>

  <div class="section"><h2>Before you act</h2>
    <div class="card">
      ${openItems.length ? `<div class="card-sub">Unresolved facts that affect the recommendation. Each links to how to clear it.</div>
        <ul class="issue-list">${openItems.map((o) => o.kind === "conflict"
          ? `<li><span class="tag assumed">conflict</span><span style="flex:1">${esc(o.message || o.text || "Conflicting inputs")}</span></li>`
          : `<li><span class="tag ${o.importance === "high" ? "assumed" : "estimated"}">${esc(o.importance)} priority</span><span style="flex:1"><b>${esc(o.question)}</b><br><span class="muted small">${esc(o.why)}</span></span><button class="btn sm ghost" data-ask="${esc(o.question)}">Ask</button></li>`).join("")}</ul>`
        : `<p class="muted">No open questions or conflicts — the recommendation rests only on measured inputs.</p>`}
    </div>
  </div>

  <div class="section">${aiCard(S.pid, "home", "Why this home scores what it does")}</div>`;
}

// ── AI energy advisor ──────────────────────────────────────
const CHAT = { pid: null, msgs: [] };
async function pageAdvisor() {
  if (CHAT.pid !== S.pid) { CHAT.pid = S.pid; CHAT.msgs = []; }
  const { facts: f } = await loadFacts(S.pid);
  const starters = ["Why do I score this?", "What should I improve first?", "What if I install a heat pump?", "What if I add solar panels too?", "How much energy and carbon could I save?", "Could it raise my home's value?"];
  return `${pageHead("AI energy advisor", `Ask anything about <b>${esc(S.pid)}</b>. Numbers are computed by the engine and checked before you see them — the model never invents figures.`)}
    <div class="chat" id="chat">
      ${CHAT.msgs.length ? CHAT.msgs.map(renderMsg).join("") : `<div class="card"><h3>Start the conversation</h3><div class="card-sub">Pick a question, or type your own below. A what-if re-runs the full calculation first, then explains it.</div>
        <div class="starter-chips">${starters.map((q) => `<button class="chip" data-ask="${esc(q)}">${esc(q)}</button>`).join("")}</div></div>`}
    </div>
    <div class="composer"><div class="composer-inner">
      <textarea id="chat-input" rows="1" placeholder="Ask about your score, a retrofit, or a what-if…" aria-label="Message"></textarea>
      <button class="btn primary" id="chat-send">Send</button>
    </div><div class="small muted" style="text-align:center;margin-top:6px">Grounded on this home's computed facts · what-ifs re-run the engine before answering</div></div>`;
}
function renderMsg(m) {
  if (m.role === "user") return `<div class="msg user"><div class="avatar">You</div><div class="bubble">${esc(m.text)}</div></div>`;
  return `<div class="msg ai"><div class="avatar">✦</div><div class="bubble">
    ${m.by ? `<div class="by">${esc(m.by)}${m.checked ? ` · <span class="ok">✓ checked against the engine</span>` : ""}</div>` : ""}
    ${m.paras.map((p) => `<p>${esc(p)}</p>`).join("")}
    ${m.facts ? `<div class="mini-facts">${m.facts.map((x) => `<div class="mini-fact"><div class="k">${esc(x.k)}</div><b>${esc(x.v)}</b></div>`).join("")}</div>` : ""}
    ${m.links ? `<div class="btn-row" style="margin-top:10px">${m.links.map((l) => `<button class="btn sm ghost" data-goto="${l.to}">${esc(l.label)} →</button>`).join("")}</div>` : ""}
  </div></div>`;
}
async function askAdvisor(question) {
  if (!question.trim()) return;
  // if not already on the advisor page, go there first
  if (currentRoute().key !== "advisor") { location.hash = "#/advisor"; await new Promise((r) => setTimeout(r, 60)); if (CHAT.pid !== S.pid) { CHAT.pid = S.pid; CHAT.msgs = []; } }
  CHAT.msgs.push({ role: "user", text: question });
  const chat = $("#chat"); const starterCard = $("#chat .card"); if (starterCard) starterCard.remove();
  chat.insertAdjacentHTML("beforeend", renderMsg(CHAT.msgs.at(-1)));
  const thinkId = "t" + rcSeq++;
  chat.insertAdjacentHTML("beforeend", `<div class="msg ai" id="${thinkId}"><div class="avatar">✦</div><div class="bubble"><div class="loading" style="padding:4px 10px"><span class="spinner"></span> Re-running the calculations…</div></div></div>`);
  chat.scrollIntoView(false); window.scrollTo(0, document.body.scrollHeight);
  let reply;
  try { reply = await answerQuestion(question); }
  catch (e) { reply = { role: "ai", by: "advisor", paras: [`I couldn't complete that: ${e.message}. The computed figures on your other pages are unaffected — try rephrasing, or ask about a specific measure.`] }; }
  document.getElementById(thinkId)?.remove();
  CHAT.msgs.push(reply);
  chat.insertAdjacentHTML("beforeend", renderMsg(reply));
  afterRender(chat);
  window.scrollTo(0, document.body.scrollHeight);
}
// route a question: what-if → /ask (engine reruns); otherwise explain from facts
async function answerQuestion(q) {
  const r = await api(`/api/properties/${encodeURIComponent(S.pid)}/ask`, { question: q, objective: S.objective });
  if (r.interpretation?.understood && r.facts) {
    const f = r.facts, pkg = f.package, im = pkg?.impact, ex = r.explanation;
    const facts = [];
    if (im) {
      facts.push({ k: "Electricity", v: `${kwh(im.electricity.baseline_kwh)} → ${kwh(im.electricity.after_kwh)}` });
      facts.push({ k: "Gas", v: `${kwh(im.gas.baseline_kwh)} → ${kwh(im.gas.after_kwh)}` });
      facts.push({ k: "Net purchased energy", v: `${im.net_saving_kwh > 0 ? "−" : "+"}${kwh(Math.abs(im.net_saving_kwh))}/yr` });
      facts.push({ k: "Carbon", v: `−${fmt(im.carbon.total_tonnes, 2)} t CO₂e/yr` });
      if (pkg.score_after != null) facts.push({ k: "Score", v: `${f.score?.score ?? "—"} → ${pkg.score_after} (${esc(pkg.band_after)})` });
      if (f.value?.status === "available" && f.value.uplift_pct_range) facts.push({ k: "Indicative value", v: `+${pctRange(f.value.uplift_pct_range[0], f.value.uplift_pct_range[1])}` });
    }
    return {
      role: "ai", by: ex?.mode === "llm" ? "Claude model" : "checked template", checked: true,
      paras: (ex?.sentences || []).map((s) => s.text),
      facts: facts.length ? facts : null,
      links: [{ to: "plans", label: "Compare this plan" }, { to: "energy", label: "Energy & carbon detail" }],
    };
  }
  // not a what-if — answer from the computed facts deterministically + show the gated score narration
  const { facts: f } = await loadFacts(S.pid);
  const ql = q.toLowerCase();
  let scope = "home", intro = [];
  if (/(improve|first|retrofit|recommend|do\b|upgrade|insulat|heat pump|solar|glaz)/.test(ql)) {
    scope = "package";
    const nba = f.next_best_action;
    intro.push(`For ${S.pid}, the first recommended step is: ${nba.headline}`);
  } else if (/(value|worth|price|sell)/.test(ql)) {
    const v = f.value;
    intro.push(v.status === "available" && v.uplift_pct_range
      ? `Indicatively, the recommended plan is associated with a ${pctRange(v.uplift_pct_range[0], v.uplift_pct_range[1])} change in value (EPC ${v.band_before} → ${v.band_after}) — a range from historical relationships, not a promise or a valuation.`
      : `An indicative value change can't be estimated for this home: ${v.reason || "the EPC band doesn't change, so no uplift is modelled."}`);
    return { role: "ai", by: "computed facts", checked: true, paras: intro, links: [{ to: "value", label: "Home value detail" }] };
  } else if (/(save|saving|energy|carbon|kwh|co2|bill)/.test(ql)) {
    scope = "package";
  }
  // fetch the matching gated explanation
  let sent = [];
  try { const r2 = await api(`/api/properties/${encodeURIComponent(S.pid)}/explain?scope=${scope}&objective=${S.objective}`); sent = (r2.explanation.sentences || []).map((s) => s.text); } catch {}
  return {
    role: "ai", by: "checked explanation", checked: true,
    paras: [...intro, ...sent, intro.length || sent.length ? "" : "I can explain your score, your recommended improvements, energy and carbon savings, or run a what-if (e.g. \"what if I install a heat pump?\")."].filter(Boolean),
    links: scope === "package" ? [{ to: "improvements", label: "See improvements" }] : [{ to: "property", label: "Score breakdown" }],
  };
}

// ── Improvements ───────────────────────────────────────────
async function pageImprovements() {
  const { facts: f } = await loadFacts(S.pid);
  const plan = f.plan || [], excluded = f.excluded || [];
  return `${pageHead("Improvements", `A prioritised list of feasible retrofits for <b>${esc(S.pid)}</b> — ordered so each one is sized for the home the earlier steps leave behind. Savings are estimates, not guarantees.`)}
  ${plan.length ? plan.map((p, i) => `<div class="card" style="margin-bottom:14px">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
      <div><div class="small muted">Step ${p.order} · ${esc(p.stage_label || "")}</div><h3>${esc(p.name)}</h3></div>
      <span class="suit ${p.suitability}">${esc(p.suitability)} suitability</span>
    </div>
    <p style="margin-top:8px">${esc(p.rationale || "")}</p>
    <div class="grid cols-3" style="gap:12px;margin:12px 0">
      ${["electricity", "gas"].map((fu) => { const b = p.standalone?.[fu]; if (!b) return ""; const col = fu === "gas" ? "var(--gas)" : "var(--elec)"; return `<div class="card" style="box-shadow:none;padding:12px"><div class="stat"><span class="k" style="color:${col}">${fu[0].toUpperCase() + fu.slice(1)}</span><span class="v sm">${b.saving_kwh > 0 ? `−${kwh(b.saving_kwh)}` : b.saving_kwh < 0 ? `<span class="delta bad">+${kwh(-b.saving_kwh)}</span>` : "no change"}</span><span class="foot">${kwh(b.baseline_kwh)} → ${kwh(b.after_kwh)}</span></div></div>`; }).join("")}
      <div class="card" style="box-shadow:none;padding:12px"><div class="stat"><span class="k">Carbon</span><span class="v sm">${rc("−" + fmt(p.standalone?.carbon?.total_kg) + " kg", p.standalone?.carbon?.receipt)}</span><span class="foot">CO₂e a year</span></div></div>
    </div>
    ${p.depends_on?.length ? `<div class="callout info small">Do this after: ${p.depends_on.map(esc).join(", ")} — sequencing matters.</div>` : ""}
    ${p.uncertainty?.length ? `<div class="callout warn small" style="margin-top:6px">${p.uncertainty.map(esc).join(" ")}</div>` : ""}
    <div class="btn-row" style="margin-top:12px"><button class="btn sm" data-goto="plans">Add to a plan</button><button class="btn sm ghost" data-ask="Tell me more about ${esc(p.name)}">Ask the advisor</button></div>
  </div>`).join("") : `<div class="card">${stateView("✓", "Nothing to retrofit", "No feasible improvements were identified for this home.")}</div>`}

  ${excluded.length ? `<div class="section"><h2>Not recommended / check first</h2><div class="card"><ul class="issue-list">
    ${excluded.map((e) => `<li><span class="tag ${e.status === "completed" || e.status === "not_needed" ? "measured" : "assumed"}">${esc((e.status || "").replace(/_/g, " "))}</span><b>${esc(e.name)}</b><span class="muted small" style="flex:1">${esc(e.reason || "")}</span></li>`).join("")}
  </ul></div></div>` : ""}

  <div class="section">${aiCard(S.pid, "package", "Why these improvements, in this order")}</div>`;
}

// ── Compare plans (Decision Lab) ───────────────────────────
const PLAN = { picked: new Set(), budget: 15000 };
async function pagePlans() {
  const lab = await api(`/api/properties/${encodeURIComponent(S.pid)}/lab?budget=${PLAN.budget}&objective=${S.objective}`);
  const feasible = [...new Set(lab.packages.flatMap((p) => p.measures))];
  const measureName = {};
  (await loadFacts(S.pid)).facts.plan.forEach((p) => (measureName[p.measure_id] = p.name));
  if (!PLAN.picked.size && lab.base_package) lab.base_package.forEach((m) => PLAN.picked.add(m));

  return `${pageHead("Compare plans", `Build a plan for <b>${esc(S.pid)}</b> and see it re-calculated by the engine — per fuel, carbon, and indicative value. Savings are never simply added; interactions are accounted for.`)}
  <div class="card">
    <h3>Named plans</h3><div class="card-sub">Each is a real package the engine re-ran. Prioritising: <b>${esc(OBJ_NAME[S.objective])}</b>.</div>
    <div class="plan-grid" id="plan-grid">
      ${lab.plans.map((pl) => { const pkg = lab.packages.find((p) => p.key === pl.package_key); return planCard(pl, pkg, measureName); }).join("")}
    </div>
  </div>

  <div class="section"><div class="card">
    <h3>Build your own</h3><div class="card-sub">Pick measures; the engine recomputes the package (not a sum of parts).</div>
    <div class="measure-pick" id="measure-pick">
      ${feasible.map((m) => `<label class="${PLAN.picked.has(m) ? "on" : ""}"><input type="checkbox" value="${m}" ${PLAN.picked.has(m) ? "checked" : ""}>${esc(measureName[m] || m.replace(/_/g, " "))}</label>`).join("")}
    </div>
    <div id="custom-result" style="margin-top:16px"></div>
  </div></div>

  <div class="section"><div class="card">
    <h3>Cost vs carbon</h3><div class="card-sub">Every feasible package. Down-and-right is better value.</div>
    <div id="frontier">${frontierTable(lab.packages, measureName)}</div>
  </div></div>`;
}
function planCard(pl, pkg, names) {
  if (!pkg) return `<div class="plan-card"><h4>${esc(pl.title)}</h4><p class="muted small">${esc(pl.definition)}</p><p class="muted">No feasible package.</p></div>`;
  return `<div class="plan-card"><h4>${esc(pl.title)}</h4><div class="small muted" style="margin-bottom:8px">${esc(pl.definition)}</div>
    <div class="plan-metric"><span>Measures</span><b>${pkg.measures.length}</b></div>
    <div class="plan-metric"><span>Cost</span><b class="num">${gbpK(pkg.cost_low)}–${gbpK(pkg.cost_high)}</b></div>
    <div class="plan-metric"><span>Electricity</span><b class="num">${pkg.electricity_saving_kwh >= 0 ? "−" : "+"}${kwh(Math.abs(pkg.electricity_saving_kwh))}</b></div>
    <div class="plan-metric"><span>Gas</span><b class="num">${pkg.gas_saving_kwh >= 0 ? "−" : "+"}${kwh(Math.abs(pkg.gas_saving_kwh))}</b></div>
    <div class="plan-metric"><span>Net energy</span><b class="num delta good">−${kwh(pkg.net_saving_kwh)}</b></div>
    <div class="btn-row" style="margin-top:10px"><button class="btn sm" data-plan="${pkg.measures.join(",")}">Load this plan</button></div>
  </div>`;
}
function frontierTable(pkgs, names) {
  const sorted = [...pkgs].sort((a, b) => a.cost_mid - b.cost_mid);
  return `<table class="data"><thead><tr><th>Package</th><th class="num">Cost (mid)</th><th class="num">Net energy saved</th><th>Prereqs</th></tr></thead><tbody>
    ${sorted.slice(0, 12).map((p) => `<tr><td>${p.measures.map((m) => esc(names[m] || m.replace(/_/g, " "))).join(", ") || "—"}</td><td class="num">${gbpK(p.cost_mid)}</td><td class="num">−${kwh(p.net_saving_kwh)}</td><td>${p.respects_prerequisites ? `<span class="tag measured">ok</span>` : `<span class="tag assumed">missing</span>`}</td></tr>`).join("")}
  </tbody></table>`;
}
async function recomputeCustom() {
  const box = $("#custom-result"); if (!box) return;
  const measures = [...PLAN.picked];
  if (!measures.length) { box.innerHTML = `<p class="muted">Pick at least one measure to see its combined effect.</p>`; return; }
  box.innerHTML = `<div class="loading"><span class="spinner"></span> Re-running the engine for your plan…</div>`;
  try {
    const r = await api(`/api/properties/${encodeURIComponent(S.pid)}/scenarios`, { measures, objective: S.objective, name: "Custom plan" });
    const f = r.facts, im = f.package?.impact;
    box.innerHTML = `<div class="grid cols-4" style="gap:12px">
      <div class="stat"><span class="k">Score after</span><span class="v sm">${f.score?.score ?? "—"} → ${f.package?.score_after ?? "—"}</span><span class="foot">${esc(f.package?.band_after || "")}</span></div>
      <div class="stat"><span class="k">Electricity</span><span class="v sm">${im.electricity.saving_kwh >= 0 ? "−" : "+"}${kwh(Math.abs(im.electricity.saving_kwh))}</span><span class="foot">${kwh(im.electricity.baseline_kwh)} → ${kwh(im.electricity.after_kwh)}</span></div>
      <div class="stat"><span class="k">Gas</span><span class="v sm">${im.gas.saving_kwh >= 0 ? "−" : "+"}${kwh(Math.abs(im.gas.saving_kwh))}</span><span class="foot">${kwh(im.gas.baseline_kwh)} → ${kwh(im.gas.after_kwh)}</span></div>
      <div class="stat"><span class="k">Carbon</span><span class="v sm delta good">−${fmt(im.carbon.total_tonnes, 2)} t</span><span class="foot">CO₂e/yr</span></div>
    </div>
    <div class="note" style="margin-top:12px">Net purchased energy saved: <b>${rc(kwh(im.net_saving_kwh), im.carbon.receipt)}/yr</b> — interactions ${f.package.interaction_kwh < 0 ? `reduce the naive sum by ${kwh(-f.package.interaction_kwh)}` : "accounted for"}, not a simple addition. ${f.value?.status === "available" && f.value.uplift_pct_range ? `Indicative value +${pctRange(f.value.uplift_pct_range[0], f.value.uplift_pct_range[1])}.` : ""}</div>`;
    afterRender(box);
  } catch (e) { box.innerHTML = `<div class="errbox">${esc(e.message)}</div>`; }
}

// ── Energy & carbon ────────────────────────────────────────
async function pageEnergy() {
  const { facts: f } = await loadFacts(S.pid);
  const im = f.package?.impact, car = im?.carbon;
  const ef = car?.receipt?.inputs || {};
  return `${pageHead("Energy & carbon", `Electricity and gas tracked separately, baseline vs the recommended plan, with the carbon that follows. A heat pump can raise electricity while cutting gas — shown honestly.`)}
  <div class="grid cols-2">
    <div class="card"><h3>Energy purchased per fuel</h3><div class="card-sub">Baseline ${tag(f.baseline_basis)} → after the recommended package (estimate).</div>
      ${im ? fuelBlock("Gas", "var(--gas)", im.gas) + fuelBlock("Electricity", "var(--elec)", im.electricity) : `<p class="muted">No package to model.</p>`}
      ${im ? `<div class="note" style="margin-top:12px">Net purchased energy: <b>${kwh((im.electricity.baseline_kwh) + (im.gas.baseline_kwh))}</b> → <b>${kwh((im.electricity.after_kwh) + (im.gas.after_kwh))}</b> — a saving of ${rc(kwh(im.net_saving_kwh), car?.receipt)}/yr. Same accounting both sides; solar cuts imports, not demand.</div>` : ""}
    </div>
    <div class="card"><h3>Carbon</h3><div class="card-sub">ΔC = Σ ΔEⱼ × EFⱼ, per fuel, with documented factors.</div>
      ${car ? `<div class="grid cols-2" style="gap:12px">
        <div class="stat"><span class="k" style="color:var(--gas)">Gas saved</span><span class="v sm delta good">−${fmt(car.gas_kg)} kg</span><span class="foot">EF ${fmt(ef.ef_gas, 3)} kg/kWh</span></div>
        <div class="stat"><span class="k" style="color:var(--elec)">Electricity</span><span class="v sm ${car.electricity_kg < 0 ? "delta bad" : "delta good"}">${car.electricity_kg < 0 ? "+" + fmt(-car.electricity_kg) : "−" + fmt(car.electricity_kg)} kg</span><span class="foot">EF ${fmt(ef.ef_electricity, 3)} kg/kWh</span></div>
      </div>
      <div class="card" style="box-shadow:none;margin-top:12px;background:var(--accent-soft)"><div class="stat"><span class="k">Net carbon saved</span><span class="v">${rc("−" + fmt(car.total_tonnes, 2) + " t", car.receipt)}<span class="muted" style="font-size:14px"> CO₂e/yr</span></span><span class="foot">${fmt(car.total_kg)} kg a year · positive = reduction</span></div></div>
      ${im.electricity.saving_kwh < 0 ? `<div class="callout warn small" style="margin-top:10px">This plan raises electricity by ${kwh(-im.electricity.saving_kwh)} (a heat pump) while cutting gas by ${kwh(im.gas.saving_kwh)}. The net effect is still a carbon saving.</div>` : ""}`
        : `<p class="muted">No carbon delta to show.</p>`}
    </div>
  </div>
  <div class="section">${aiCard(S.pid, "package", "What these savings mean")}</div>`;
}

// ── Home value ─────────────────────────────────────────────
async function pageValue() {
  const { facts: f } = await loadFacts(S.pid);
  const v = f.value;
  return `${pageHead("Home value", "An indicative range from historical EPC-band / sale-price relationships in our dataset — explicitly not a valuation, a guarantee, or proof that retrofitting causes a price rise.")}
  <div class="grid cols-2">
    <div class="card"><h3>Current estimate</h3><div class="card-sub">Today's indicative value (the baseline the uplift is measured against).</div>
      <div class="stat"><span class="v">${rc(gbp(v.current_value), v.receipt)}</span><span class="foot">80% range ${gbp(v.current_range?.[0])} – ${gbp(v.current_range?.[1])} ${tag("estimated")}</span></div>
      <div class="note small" style="margin-top:12px">This is a current-value estimate, kept separate from any historical sale prices.</div>
    </div>
    <div class="card"><h3>After the recommended plan</h3>
      ${v.status === "available" && v.uplift_pct_range ? `<div class="card-sub">Same home, other characteristics held constant, EPC ${esc(v.band_before)} → ${esc(v.band_after)}.</div>
        <div class="grid cols-2" style="gap:12px">
          <div class="stat"><span class="k">Indicative uplift</span><span class="v sm delta good">+${pctRange(v.uplift_pct_range[0], v.uplift_pct_range[1])}</span><span class="foot">${gbp(v.uplift_gbp_range?.[0])} – ${gbp(v.uplift_gbp_range?.[1])}</span></div>
          <div class="stat"><span class="k">Value after</span><span class="v sm">${gbp(v.value_after_range?.[0])}–${gbp(v.value_after_range?.[1])}</span><span class="foot">a range, not a point</span></div>
        </div>`
        : `<div class="card-sub">Indicative uplift</div>${stateView("—", "No indicative uplift", v.reason || "The EPC band doesn't change under the recommended plan, so no value uplift is modelled.")}`}
    </div>
  </div>
  <div class="callout info" style="margin-top:16px">${esc(v.caveat)}</div>
  <div class="section">${aiCard(S.pid, "package", "How to read this estimate")}</div>`;
}

// ── Evidence & reports ─────────────────────────────────────
async function pageEvidence() {
  const ev = await api("/api/evidence");
  const m = ev.metrics || {};
  const labels = ev.score.labels || {};
  const factors = ev.emission_factors?.factors || {};
  const assumptions = Array.isArray(ev.assumptions?.items) ? ev.assumptions.items : [];
  const mScalars = Object.entries(m).filter(([, v]) => typeof v !== "object" && v != null);
  return `${pageHead("Evidence & reports", "Every number on this app traces to a documented method, factor, or model. This page is the index.")}
  <div class="grid cols-2">
    <div class="card"><h3>Green Home Score weights</h3>
      <table class="data"><tbody>
        ${Object.entries(ev.score.weights).map(([k, w]) => `<tr><td>${esc(labels[k] || words(k))}</td><td class="num">${pct(w * 100, 0)}</td></tr>`).join("")}
      </tbody></table>
      <div class="small muted" style="margin-top:8px">Mapping ${esc(ev.score.version)} · bands ${(ev.score.bands || []).map((b) => `${b[2]} ${b[0]}–${b[1]}`).join(" · ")}</div>
      <div class="btn-row" style="margin-top:8px"><a class="btn sm ghost" href="/${esc(ev.scoring_method)}" target="_blank">Scoring method doc</a></div>
    </div>
    <div class="card"><h3>Emission factors</h3>
      <table class="data"><thead><tr><th>Fuel</th><th class="num">kg CO₂e/kWh</th><th>Source</th></tr></thead><tbody>
        ${Object.entries(factors).map(([k, val]) => `<tr><td>${esc(k)}</td><td class="num">${fmt(val.value, 4)}</td><td class="small muted">${esc((val.source || "").split("(")[0])}</td></tr>`).join("")}
      </tbody></table>
      <div class="small muted" style="margin-top:8px">${esc(ev.emission_factors?.version || ev.versions.emission_factors)}</div>
    </div>
  </div>
  <div class="section"><div class="card"><h3>Retrofit catalogue</h3><div class="card-sub">${esc(ev.price_basis || "")} ${esc(ev.impact_note || "")}</div>
    <table class="data"><thead><tr><th>Measure</th><th class="num">Stage</th><th class="num">Cost basis</th><th>Cost source</th><th>PS2 illustrative</th></tr></thead><tbody>
      ${Object.entries(ev.measures).map(([k, v]) => `<tr><td>${esc(v.name)}</td><td class="num">${esc(v.stage)}</td><td class="num small">${v.cost ? `${gbp(v.cost.low)}–${gbp(v.cost.high)} /${esc(v.cost.basis || "unit")}` : "—"}</td><td class="small muted">${esc((v.cost_source || "").slice(0, 44))}</td><td class="small">${esc(v.ps2_illustrative_impact || "—")}</td></tr>`).join("")}
    </tbody></table>
  </div></div>
  <div class="section"><div class="grid cols-2">
    <div class="card"><h3>Model & evaluation</h3>
      ${mScalars.length ? `<table class="data"><tbody>${mScalars.slice(0, 8).map(([k, v]) => `<tr><td>${esc(words(k))}</td><td class="num">${typeof v === "number" ? fmt(v, 2) : esc(String(v))}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">Run <code>greeniq evaluate</code> to generate metrics.</p>`}
      <div class="btn-row" style="margin-top:8px"><a class="btn sm ghost" href="/${esc(ev.evaluation_report)}" target="_blank">Evaluation report</a></div>
    </div>
    <div class="card"><h3>Assumptions</h3><div class="card-sub">${esc(ev.assumptions?.note ? ev.assumptions.note.slice(0, 120) : "Every judgement call, with a reason.")}</div>
      <table class="data"><tbody>${assumptions.slice(0, 9).map((a) => `<tr><td>${esc(a.key || a.name || "")}</td><td class="num small">${esc(a.value != null ? a.value + " " + (a.unit || "") : "")}</td><td class="small muted">${esc((a.reason || a.note || "").slice(0, 60))}</td></tr>`).join("") || `<tr><td class="muted">documented in config/assumptions.json</td></tr>`}</tbody></table>
    </div>
  </div></div>
  <div class="section"><div class="card"><h3>Data & provenance</h3>
    <p class="small">Detailed homes are <b>synthetic</b> (documented simulator). Real benchmarks use <span class="tag real">real data</span> <b>DESNZ NEED</b> (50,000 homes, OGL v3.0). Engine key <code>${esc(ev.engine_key)}</code>.</p>
    <div class="btn-row"><a class="btn sm ghost" href="/static/../${esc(ev.data_card)}" target="_blank">Data card</a><a class="btn sm ghost" href="/static/../${esc(ev.methodology)}" target="_blank">Methodology</a></div>
  </div></div>`;
}

// ── Settings ───────────────────────────────────────────────
async function pageSettings() {
  return `${pageHead("Settings", "Preferences are stored on this device only.")}
  <div class="card" style="max-width:640px">
    <label class="comp-row" style="grid-template-columns:1fr auto"><div><b>Prioritise recommendations by</b><br><span class="muted small">Changes how “do this first” and the plans are ranked.</span></div>
      <select class="inp" id="set-obj"><option value="value_for_money">Value for money</option><option value="carbon">Most carbon saved</option><option value="energy">Most energy saved</option></select></label>
    <label class="comp-row" style="grid-template-columns:1fr auto"><div><b>Show evidence references</b><br><span class="muted small">Print the fact IDs each AI sentence is grounded on.</span></div>
      <button class="btn sm" id="set-labels">${S.labels ? "On" : "Off"}</button></label>
    <label class="comp-row" style="grid-template-columns:1fr auto"><div><b>Theme</b></div>
      <select class="inp" id="set-theme"><option value="system">Match device</option><option value="light">Light</option><option value="dark">Dark</option></select></label>
  </div>`;
}

// ── Help & methodology ─────────────────────────────────────
async function pageHelp() {
  return `${pageHead("Help & methodology", "How GreenIQ works, and the one rule it never breaks.")}
  <div class="note law" style="margin-bottom:16px"><b>The one law.</b> Code computes every number. AI only explains. Every number has a receipt you can open by clicking it.</div>
  <div class="grid cols-2">
    <div class="card"><h3>How a home is scored</h3><p class="small">A weighted sum of seven sub-scores (PS2-fixed weights), each 0–100, each monotonic — a better state never lowers a sub-score. Energy efficiency uses the recorded EPC rating; intensity uses annualised metered kWh/m². Rounded to the nearest integer, then classified into five bands.</p></div>
    <div class="card"><h3>Savings, carbon, value</h3><p class="small">Savings are per fuel (electricity and gas separately), with interactions accounted for — never a simple sum. Carbon is ΔC = Σ ΔEⱼ × EFⱼ with DESNZ 2025 factors. Value is an indicative range from historical EPC/price relationships, explicitly non-causal.</p></div>
    <div class="card"><h3>The AI advisor</h3><p class="small">For a what-if, the engine re-runs the whole calculation first; only then does the model explain the new numbers. A grounding gate blocks any sentence containing a number or claim the engine didn't produce, and shows a checked template instead. It runs fully with no AI key.</p></div>
    <div class="card"><h3>Honesty by design</h3><p class="small">Estimates are labelled. Value is a range. “Insufficient information” is a valid answer. Detailed homes are synthetic; real benchmarks carry a <span class="tag real">real data</span> badge.</p></div>
  </div>
  <div class="section"><div class="card"><h3>Reading the labels</h3><div class="btn-row">
    <span>${tag("measured")} measured input</span><span>${tag("estimated")} model estimate</span><span>${tag("assumed")} assumed from age/type</span><span>${tag("unavailable")} not available</span>
  </div></div></div>`;
}

// ── Lender workspace (portfolio) ───────────────────────────
async function pageLender() {
  const p = await api("/api/portfolio");
  const k = p.kpis;
  const val = k.value || {};
  return `${pageHead("Lender workspace — portfolio", `${fmt(p.n_homes)} homes · ${esc(p.data_label)}. The same engine and contracts as the homeowner view.`)}
  <div class="kpi-row">
    <div class="card"><div class="stat"><span class="k">Average score</span><span class="v">${fmt(k.avg_score?.value, 1)}</span><span class="foot">${fmt(k.avg_score?.n)} homes</span></div></div>
    <div class="card"><div class="stat"><span class="k">Poor / very poor</span><span class="v">${pct(k.poor_pct?.value)}</span><span class="foot">${fmt(k.poor_pct?.count)} homes</span></div></div>
    <div class="card"><div class="stat"><span class="k">Opportunity</span><span class="v sm">${fmt(k.opportunity?.gwh, 1)} GWh</span><span class="foot">${fmt(k.opportunity?.tco2e)} t CO₂e/yr</span></div></div>
    <div class="card"><div class="stat"><span class="k">Typical uplift</span><span class="v sm">${val.median_uplift_pct && val.median_uplift_pct[0] != null ? pctRange(val.median_uplift_pct[0], val.median_uplift_pct[1]) : "—"}</span><span class="foot">${val.band_improves != null ? fmt(val.band_improves) + " homes improve band" : "indicative"}</span></div></div>
  </div>

  <div class="section"><div class="card"><h3>Score band distribution</h3>
    <table class="data"><thead><tr><th>Band</th><th class="num">Homes</th><th>Share</th></tr></thead><tbody>
      ${["Very poor", "Poor", "Moderate", "Good", "Highly efficient", "Undetermined"].map((b) => { const n = (p.band_distribution.all || {})[b] || 0; const w = n / p.n_homes * 100; return `<tr><td><span class="band-dot" style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${bandCol(b)};margin-right:8px"></span>${esc(b)}</td><td class="num">${fmt(n)}</td><td class="bar-cell"><div class="bar"><span style="width:${w}%;background:${bandCol(b)}"></span></div></td></tr>`; }).join("")}
    </tbody></table>
  </div></div>

  <div class="section"><div class="card"><h3>Highest improvement potential</h3><div class="card-sub">Ranked by % reduction in purchased energy from the feasible package (PS2 §3). Click a home to open it.</div>
    <table class="data"><thead><tr><th>Home</th><th>Type</th><th>Region</th><th class="num">Score</th><th class="num">Potential</th><th class="num">Value uplift</th></tr></thead><tbody id="rank-body">
      <tr><td colspan="6" class="muted">Loading ranking…</td></tr>
    </tbody></table>
  </div></div>

  <div class="section"><div class="card"><h3>Compare groups</h3>
    <div class="btn-row" id="group-tabs">${["region", "property_type", "age_band", "epc_band"].map((g, i) => `<button class="btn sm ${i === 0 ? "primary" : ""}" data-group="${g}">${esc(g.replace(/_/g, " "))}</button>`).join("")}</div>
    <div id="group-table" style="margin-top:12px"><div class="loading"><span class="spinner"></span> Loading…</div></div>
  </div></div>`;
}
async function fillRanking() {
  const body = $("#rank-body"); if (!body) return;
  try {
    const d = await api("/api/properties?poor_only=true&sort=potential_pct&limit=15");
    body.innerHTML = d.items.filter((r) => r.potential_status === "available").slice(0, 12).map((r) => `<tr class="clickable" data-pick="${r.property_id}">
      <td><b>${esc(r.property_id)}</b></td><td>${esc(r.property_type || "")}</td><td>${esc(r.region || "")}</td>
      <td class="num">${r.score ?? "—"}</td><td class="num">${pct(r.potential_pct)}</td>
      <td class="num">${r.value_status === "available" && r.value_uplift_pct_high ? pctRange(r.value_uplift_pct_low, r.value_uplift_pct_high) : "—"}</td></tr>`).join("") || `<tr><td colspan="6" class="muted">No ranked homes.</td></tr>`;
    $$("#rank-body [data-pick]").forEach((el) => el.onclick = () => selectHome(el.dataset.pick));
  } catch (e) { body.innerHTML = `<tr><td colspan="6"><div class="errbox">${esc(e.message)}</div></td></tr>`; }
}
async function fillGroups(by = "region") {
  const box = $("#group-table"); if (!box) return;
  box.innerHTML = `<div class="loading"><span class="spinner"></span> Loading…</div>`;
  try {
    const d = await api(`/api/portfolio/groups?by=${by}`);
    box.innerHTML = `<table class="data"><thead><tr><th>${esc(d.label)}</th><th class="num">Homes</th><th class="num">Avg score</th><th class="num">Poor %</th><th class="num">Carbon/home</th><th class="num">Value uplift</th></tr></thead><tbody>
      ${d.groups.map((g) => `<tr><td>${esc(String(g.group).replace(/_/g, " "))}</td><td class="num">${fmt(g.homes)}</td><td class="num">${fmt(g.avg_score, 1)}</td><td class="num">${pct(g.poor_pct)}</td><td class="num">${fmt(g.carbon_saving_t_per_home, 2)} t</td><td class="num">${g.median_uplift_pct && g.median_uplift_pct[1] != null ? pctRange(g.median_uplift_pct[0], g.median_uplift_pct[1]) : "—"}</td></tr>`).join("")}
    </tbody></table>`;
  } catch (e) { box.innerHTML = `<div class="errbox">Could not load groups: ${esc(e.message)}</div>`; }
}

// ──────────────────────────────────────────────────────────── receipt drawer
function openReceipt(r) {
  if (!r) return;
  const d = $("#drawer");
  const inputs = r.inputs ? Object.entries(r.inputs).map(([k, v]) => `<dt>${esc(k)}</dt><dd class="num">${typeof v === "number" ? fmt(v, 3) : esc(String(v))}</dd>`).join("") : "";
  d.innerHTML = `<div class="drawer-head"><div><div class="small muted">Receipt</div><h2>${esc(r.output || "value")}</h2></div><button class="icon-btn" id="drawer-close">✕</button></div>
    <div class="stat" style="margin-bottom:12px"><span class="v">${typeof r.value === "number" ? fmt(r.value, 2) : esc(String(r.value ?? "—"))}</span><span class="foot">${esc(r.unit || "")}</span></div>
    ${inputs ? `<div class="kv"><h3 class="small">Inputs</h3><dl>${inputs}</dl></div>` : ""}
    <div class="kv"><h3 class="small">Method</h3><p class="small">${esc(r.method || "—")}</p><div class="small muted">${esc(r.method_version || "")} · ${esc(r.provider || "")}</div></div>
    ${r.sources?.length ? `<div class="kv"><h3 class="small">Sources</h3><ul class="small">${r.sources.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>` : ""}
    ${r.notes?.length ? `<div class="kv"><h3 class="small">Notes</h3><ul class="small">${r.notes.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>` : ""}`;
  d.hidden = false; $("#drawer-scrim").hidden = false;
  $("#drawer-close").onclick = closeDrawer;
}
function closeDrawer() { $("#drawer").hidden = true; $("#drawer-scrim").hidden = true; }

// ──────────────────────────────────────────────────────────── property switcher
async function renderPropLabel() {
  const label = $("#prop-label"), dot = $("#prop-dot");
  if (!S.pid) { label.textContent = "Choose a home…"; dot.style.background = "var(--b-u)"; return; }
  label.textContent = S.pid;
  try { const props = await getProps(); const p = props.find((x) => x.property_id === S.pid); if (p) dot.style.background = bandCol(p.band); $("#data-status").innerHTML = `${esc(S.pid)} · ${esc(p?.property_type || "")} · ${esc(p?.band || "")}`; }
  catch {}
}
function selectHome(pid) {
  S.pid = pid; store.set("pid", pid); clearFacts(); CHAT.pid = null; PLAN.picked.clear();
  renderPropLabel(); closePropPop();
  if (currentRoute().key === "lender" || !ROUTES[currentRoute().key].needs) location.hash = "#/overview"; else route();
}
function closePropPop() { $("#prop-pop").hidden = true; $("#prop-btn").setAttribute("aria-expanded", "false"); }
async function openPropPop() {
  const pop = $("#prop-pop"); pop.hidden = false; $("#prop-btn").setAttribute("aria-expanded", "true");
  pop.innerHTML = `<input placeholder="Search home reference…" id="prop-search" autocomplete="off"><div id="prop-list"><div class="loading" style="padding:10px"><span class="spinner"></span></div></div>`;
  const search = $("#prop-search"); search.focus();
  const props = await getProps();
  const draw = (q) => {
    const list = props.filter((p) => !q || p.property_id.toLowerCase().includes(q.toLowerCase())).slice(0, 40);
    $("#prop-list").innerHTML = list.map((p) => `<div class="prop-opt" data-pick="${p.property_id}"><span class="prop-dot" style="background:${bandCol(p.band)}"></span><b>${esc(p.property_id)}</b><small>${esc(p.band || "—")} · ${esc(p.property_type || "")}</small></div>`).join("") || `<div class="muted small" style="padding:10px">No match.</div>`;
    $$("#prop-list [data-pick]").forEach((el) => el.onclick = () => selectHome(el.dataset.pick));
  };
  draw(""); search.oninput = () => draw(search.value);
}

// ──────────────────────────────────────────────────────────── boot
function applyTheme() { document.documentElement.setAttribute("data-theme", S.theme === "system" ? "" : S.theme); if (S.theme === "system") document.documentElement.removeAttribute("data-theme"); }

async function boot() {
  applyTheme();
  buildNav();
  $("#obj").value = S.objective;
  $("#label-toggle").setAttribute("aria-pressed", String(S.labels));

  // health → llm pill + data status
  getHealth().then((h) => {
    const pill = $("#llm-pill"); const live = h.llm && !/no language model/.test(h.llm);
    pill.textContent = live ? `AI: ${h.llm}` : "AI: checked template"; pill.classList.toggle("live", !!live);
  }).catch(() => {});

  renderPropLabel();

  // global events (delegation)
  document.addEventListener("click", (e) => {
    const askEl = e.target.closest("[data-ask]"); if (askEl) { e.preventDefault(); askAdvisor(askEl.dataset.ask); return; }
    const planEl = e.target.closest("[data-plan]"); if (planEl) { PLAN.picked = new Set(planEl.dataset.plan.split(",").filter(Boolean)); route().then(() => recomputeCustom()); return; }
    const grpEl = e.target.closest("[data-group]"); if (grpEl) { $$("#group-tabs .btn").forEach((b) => b.classList.toggle("primary", b === grpEl)); fillGroups(grpEl.dataset.group); return; }
    if (!e.target.closest("#prop-switch")) closePropPop();
  });
  $("#prop-btn").onclick = (e) => { e.stopPropagation(); $("#prop-pop").hidden ? openPropPop() : closePropPop(); };
  $("#menu-toggle").onclick = () => $("#sidebar").classList.toggle("open");
  $("#drawer-scrim").onclick = closeDrawer;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeDrawer(); closePropPop(); } });

  $("#obj").onchange = (e) => { S.objective = e.target.value; store.set("objective", S.objective); clearFacts(); route(); };
  $("#label-toggle").onclick = () => { S.labels = !S.labels; store.set("labels", S.labels); $("#label-toggle").setAttribute("aria-pressed", String(S.labels)); route(); };
  $("#theme-toggle").onclick = () => { S.theme = S.theme === "dark" ? "light" : S.theme === "light" ? "system" : "dark"; store.set("theme", S.theme); applyTheme(); toast(`Theme: ${S.theme}`); };

  // page-specific delegated handlers that must survive re-render
  document.addEventListener("submit", (e) => {
    if (e.target.id === "ov-ask") { e.preventDefault(); const inp = e.target.querySelector("input"); askAdvisor(inp.value); inp.value = ""; }
  });
  document.addEventListener("input", (e) => {
    if (e.target.closest("#measure-pick")) { const cb = e.target; if (cb.checked) PLAN.picked.add(cb.value); else PLAN.picked.delete(cb.value); cb.closest("label").classList.toggle("on", cb.checked); recomputeCustom(); }
    if (e.target.id === "chat-input") { e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px"; }
  });
  document.addEventListener("click", (e) => {
    if (e.target.id === "chat-send") { const t = $("#chat-input"); askAdvisor(t.value); t.value = ""; t.style.height = "auto"; }
    if (e.target.id === "set-labels") { S.labels = !S.labels; store.set("labels", S.labels); route(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.id === "chat-input" && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); const t = e.target; askAdvisor(t.value); t.value = ""; t.style.height = "auto"; }
  });
  document.addEventListener("change", (e) => {
    if (e.target.id === "set-obj") { S.objective = e.target.value; $("#obj").value = e.target.value; store.set("objective", S.objective); clearFacts(); }
    if (e.target.id === "set-theme") { S.theme = e.target.value; store.set("theme", S.theme); applyTheme(); }
  });

  window.addEventListener("hashchange", route);
  await route();

  // post-render fills for lender page
  const obs = new MutationObserver(() => {
    if ($("#rank-body") && !$("#rank-body").dataset.filled) { $("#rank-body").dataset.filled = "1"; fillRanking(); }
    if ($("#group-table") && !$("#group-table").dataset.filled) { $("#group-table").dataset.filled = "1"; fillGroups("region"); }
    if ($("#custom-result") && !$("#custom-result").dataset.filled) { $("#custom-result").dataset.filled = "1"; recomputeCustom(); }
    if ($("#set-obj")) { $("#set-obj").value = S.objective; } if ($("#set-theme")) $("#set-theme").value = S.theme;
  });
  obs.observe($("#main"), { childList: true, subtree: true });
}

boot();
