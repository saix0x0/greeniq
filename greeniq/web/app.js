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

// ── one canonical baseline for the whole UI (fixes the 15,871 vs 15,880 split).
// The package baseline is what savings / before-after / improvement-% all reference, so use it
// everywhere a home has a feasible package; fall back to the precise annualised baseline otherwise.
function energyView(f) {
  const im = f.package?.impact;
  const elec = im ? im.electricity.baseline_kwh : (f.baseline?.electricity?.annual_kwh ?? null);
  const gas = im ? im.gas.baseline_kwh : (f.baseline?.gas?.annual_kwh ?? null);
  return { elec, gas, total: (elec ?? 0) + (gas ?? 0), basis: f.baseline_basis, source: im ? "package" : "annualised" };
}
// Indicative money overlay. Ofgem Jan–Mar 2025 price cap unit rates (GB average, single rate),
// a documented presentation assumption — NOT an engine figure, always labelled "indicative".
const TARIFF = { elec: 0.2497, gas: 0.0625, source: "Ofgem price cap, Jan–Mar 2025 (GB avg unit rates)" };
const poundsPerYear = (elecKwh, gasKwh) => (elecKwh || 0) * TARIFF.elec + (gasKwh || 0) * TARIFF.gas;
// Relatable carbon: illustrative equivalents, shown as ranges, never as offsets.
const carbonEquiv = (tonnes) => tonnes > 0 ? `≈ ${fmt(tonnes * 4.2, 0)} return London–Edinburgh flights` : "";

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

let HEALTH = null, PROPS = null, PORTFOLIO = null;
async function getHealth() { return HEALTH || (HEALTH = await api("/api/health")); }
async function getProps() { return PROPS || (PROPS = (await api("/api/properties?limit=3000&sort=property_id")).items); }
async function getPortfolio() { return PORTFOLIO || (PORTFOLIO = await api("/api/portfolio")); }

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
  overview:     { group: "YOUR HOME", ico: "🏠", label: "Overview", needs: "home", render: pageOverview },
  property:     { group: "YOUR HOME", ico: "📊", label: "Score Breakdown", needs: "home", render: pageProperty },
  improvements: { group: "UPGRADES", ico: "🔧", label: "Recommended Upgrades", needs: "home", render: pageImprovements },
  plans:        { group: "UPGRADES", ico: "⚖", label: "Compare Options", needs: "home", render: pagePlans },
  advisor:      { group: "ADVISOR", ico: "✦", label: "AI Advisor", needs: "home", render: pageAdvisor },
  lender:       { group: "PORTFOLIO", ico: "🏦", label: "Ranking", render: pageLender },
  compare:      { group: "PORTFOLIO", ico: "🏘", label: "Compare Homes", needs: "home", render: pageCompareHomes },
  methods:      { group: "TRUST", ico: "📑", label: "Methods & Evidence", render: pageMethods },
  settings:     { group: "PREFERENCES", ico: "⚙", label: "Settings", render: pageSettings },
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
  // deferred container fills (run on every render incl. the initial one, each once)
  const fill = (sel, fn) => { const el = $(sel); if (el && !el.dataset.filled) { el.dataset.filled = "1"; fn(); } };
  if ($("#sample-homes", root)) fillSampleHomes();
  fill("#rank-body", fillRanking);
  fill("#ghg", fillGrid);
  fill("#group-table", () => fillGroups("region"));
  fill("#custom-result", recomputeCustom);
  fill("#pareto", drawPareto);
  fill("#torn", drawTorn);
  if ($("#set-obj")) $("#set-obj").value = S.objective;
  if ($("#set-theme")) $("#set-theme").value = S.theme;
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

// ──────────────────────────────────────────────────────────── comparison charts
// Every value comes from the engine (/standing, facts.peer, /portfolio). Opower-style
// peer comparison, framed as guidance; no dual-axis, no pie.
function peerCompare(fuels) {
  const rows = (fuels || []).filter((f) => f.actual_kwh != null && f.peer_median_kwh != null);
  if (!rows.length) return `<p class="muted small">No metered peer comparison for this home.</p>`;
  const max = Math.max(...rows.flatMap((f) => [f.actual_kwh, f.peer_median_kwh]), 1);
  return rows.map((f) => {
    const col = f.fuel === "gas" ? "var(--gas)" : "var(--elec)";
    const above = f.actual_kwh > f.peer_median_kwh;
    const diff = Math.abs((f.ratio_to_median ?? 1) - 1) * 100;
    return `<div class="cmp-fuel">
      <div class="cmp-fuel-head"><span class="cmp-dot" style="background:${col}"></span><b>${f.fuel[0].toUpperCase() + f.fuel.slice(1)}</b>
        <span class="muted small">${above ? `<b style="color:var(--bad)">${fmt(diff)}% above</b>` : `<b style="color:var(--good)">${fmt(diff)}% below</b>`} the typical similar home · ${f.percentile}th percentile of ${fmt(f.n_peers)} peers</span></div>
      <div class="fuel-bar" title="Your home: ${kwh(f.actual_kwh)}"><span class="muted">You</span><div class="track"><span style="width:${f.actual_kwh / max * 100}%;background:${col}"></span></div><b class="num">${kwh(f.actual_kwh)}</b></div>
      <div class="fuel-bar" title="Typical similar home: ${kwh(f.peer_median_kwh)}"><span class="muted">Typical</span><div class="track"><span style="width:${f.peer_median_kwh / max * 100}%;background:var(--line-2)"></span></div><b class="num muted">${kwh(f.peer_median_kwh)}</b></div>
    </div>`;
  }).join("") + `<div class="cmp-legend"><span><i style="background:var(--elec)"></i>Your home</span><span><i style="background:var(--line-2)"></i>Typical similar home (DESNZ NEED median)</span></div>`;
}
function distChart(bandDist, hiBand) {
  const bands = ["Very poor", "Poor", "Moderate", "Good", "Highly efficient"];
  const counts = bands.map((b) => bandDist[b] || 0);
  const max = Math.max(...counts, 1);
  const W = 360, H = 118, bw = W / bands.length;
  return `<svg viewBox="0 0 ${W} ${H + 30}" class="cmp-svg" role="img" aria-label="Score distribution across scored homes, your band highlighted">
    ${bands.map((b, i) => {
      const h = Math.max(counts[i] / max * H, counts[i] ? 2 : 0), x = i * bw + 7, w = bw - 14, hi = b === hiBand;
      return `<g><rect x="${x}" y="${H - h}" width="${w}" height="${h}" rx="4" fill="${hi ? "var(--accent)" : "var(--line-2)"}"><title>${b}: ${fmt(counts[i])} homes</title></rect>
        <text x="${x + w / 2}" y="${H - h - 4}" class="cmp-cnt">${fmt(counts[i])}</text>
        <text x="${x + w / 2}" y="${H + 14}" class="cmp-axis">${esc(b.split(" ")[0])}</text>
        ${b.includes(" ") ? `<text x="${x + w / 2}" y="${H + 25}" class="cmp-axis">${esc(b.split(" ")[1])}</text>` : ""}</g>`;
    }).join("")}
  </svg>${hiBand ? `<p class="small muted" style="margin-top:2px">Your home is in the <b style="color:var(--accent)">${esc(hiBand)}</b> band.</p>` : ""}`;
}
function standingStrip(st, score) {
  if (!st?.available || !st.similar) return `<p class="muted small">Not enough similar homes to rank this one.</p>`;
  const sim = st.similar, sc = score?.score ?? (score?.score_range ? (score.score_range[0] + score.score_range[1]) / 2 : null);
  const pos = Math.max(2, Math.min(98, sc ?? 0)), med = Math.max(2, Math.min(98, sim.median_score));
  return `<div class="pct-track"><div class="pct-rail"></div>
    <div class="pct-tick" style="left:${med}%" data-label="typical ${fmt(sim.median_score)}"></div>
    <div class="pct-mark" style="left:${pos}%" data-label="you ${score?.score ?? "range"}"></div></div>
    <p class="small">This home scores higher than <b>${fmt(sim.percentile)}%</b> of ${fmt(sim.homes)} ${esc(sim.definition)} homes. The typical similar home scores <b>${fmt(sim.median_score)}</b>${st.all ? `; the portfolio median is <b>${fmt(st.all.median_score)}</b>` : ""}.</p>`;
}
function comparisonSection(f, st, pf) {
  const dist = pf?.band_distribution?.all || {};
  return `<div class="section">
    <div class="section-eyebrow">How your home compares</div>
    <div class="cmp-grid">
      <div class="card"><h3>Standing among similar homes</h3>
        <div class="card-sub">${st?.similar ? esc(st.similar.definition) : "similar homes"} · ranked by the same engine</div>
        ${standingStrip(st, f.score)}</div>
      <div class="card"><h3>Where you sit in the portfolio</h3>
        <div class="card-sub">Score distribution across all scored homes.</div>
        ${distChart(dist, f.score?.band)}</div>
      <div class="card" style="grid-column:1/-1"><h3>Energy use vs the typical similar home</h3>
        <div class="card-sub">Real peer medians from DESNZ NEED <span class="tag real">real data</span> — ${esc(f.peer?.peer_group || "")}. Guidance, not judgement.</div>
        ${peerCompare(f.peer?.fuels)}</div>
    </div></div>`;
}
// ── Compare Homes (full peer comparison, moved out of the overview) ──
async function pageCompareHomes() {
  const { facts: f } = await loadFacts(S.pid);
  const [st, pf] = await Promise.all([
    api(`/api/properties/${encodeURIComponent(S.pid)}/standing`).catch(() => null),
    getPortfolio().catch(() => null),
  ]);
  return `${pageHead("Compare Homes", `How <b>${esc(S.pid)}</b> stacks up against similar homes and the wider portfolio — the same engine, plus real DESNZ NEED peer medians.`)}
    <div class="card" style="margin-bottom:16px"><div class="grid cols-3" style="gap:14px">
      <div class="stat"><span class="k">Energy intensity</span><span class="v sm">${fmt(f.intensity_kwh_m2?.value)}<span class="muted" style="font-size:13px"> kWh/m²</span></span><span class="foot">${tag(f.intensity_kwh_m2?.basis)} · the fair size-adjusted measure</span></div>
      <div class="stat"><span class="k">Peer group</span><span class="v sm" style="font-size:15px">${esc(f.peer?.peer_group || "—")}</span><span class="foot">${fmt((f.peer?.fuels || [])[0]?.n_peers)} real homes</span></div>
      <div class="stat"><span class="k">Standing</span><span class="v sm">${st?.similar ? `top ${fmt(100 - st.similar.percentile)}%` : "—"}</span><span class="foot">among ${st?.similar ? fmt(st.similar.homes) : "—"} similar homes</span></div>
    </div></div>
    ${comparisonSection(f, st, pf)}
    <div class="callout info" style="margin-top:4px">A larger home isn't automatically inefficient: the comparisons here use <b>energy intensity</b> (kWh/m²) and peers of the same size band, never raw total consumption.</div>`;
}

// ──────────────────────────────────────────────────────────── Decision-Lab charts
// All from the engine's /lab output (packages, interactions, sensitivity) and facts.flows.
// No business logic recomputed; non-dominance is a geometric property of given points.
let LAB = null;
const LABKEY = { pareto: "carbon_kg", torn: "carbon_kg" };
const PARETO_AXES = {
  carbon_kg: { label: "Carbon saved (kg CO₂e/yr)", fmt: (v) => fmt(v) + " kg", get: (p) => p.carbon_kg },
  net_saving_kwh: { label: "Net energy saved (kWh/yr)", fmt: (v) => kwh(v), get: (p) => p.net_saving_kwh },
  score_after: { label: "Green Home Score after", fmt: (v) => fmt(v), get: (p) => p.score_after },
};
function measureShort(m) { return (m || "").replace(/_/g, " ").replace("insulation", "insul.").replace("air source heat pump", "heat pump").replace("solar pv", "solar").replace("smart controls", "controls").replace("glazing upgrade", "glazing"); }

function paretoChart(pkgs, yKey) {
  const ax = PARETO_AXES[yKey]; const pts = pkgs.filter((p) => ax.get(p) != null && p.cost_mid != null);
  if (pts.length < 2) return `<p class="muted small">Not enough feasible packages to plot a frontier.</p>`;
  const xs = pts.map((p) => p.cost_mid), ys = pts.map(ax.get);
  const xmin = 0, xmax = Math.max(...xs) * 1.08, ymin = Math.min(0, ...ys), ymax = Math.max(...ys) * 1.08 || 1;
  const W = 600, H = 300, m = { l: 58, r: 16, t: 14, b: 42 };
  const px = (x) => m.l + (x - xmin) / (xmax - xmin) * (W - m.l - m.r);
  const py = (y) => H - m.b - (y - ymin) / (ymax - ymin) * (H - m.t - m.b);
  // non-dominated: no other package has lower-or-equal cost AND higher-or-equal benefit
  const dom = pts.map((p, i) => pts.some((q, j) => j !== i && q.cost_mid <= p.cost_mid && ax.get(q) >= ax.get(p) && (q.cost_mid < p.cost_mid || ax.get(q) > ax.get(p))));
  const front = pts.map((p, i) => [p, i]).filter(([, i]) => !dom[i]).sort((a, b) => a[0].cost_mid - b[0].cost_mid);
  const gridY = [0, .25, .5, .75, 1].map((t) => ymin + t * (ymax - ymin));
  return `<svg viewBox="0 0 ${W} ${H}" class="cmp-svg" role="img" aria-label="Cost versus ${esc(ax.label)} for every feasible package">
    ${gridY.map((gy) => `<line x1="${m.l}" y1="${py(gy)}" x2="${W - m.r}" y2="${py(gy)}" stroke="var(--line)" stroke-width="1"/><text x="${m.l - 6}" y="${py(gy) + 3}" class="cmp-axis" text-anchor="end">${ax.fmt(gy)}</text>`).join("")}
    <polyline points="${front.map(([p]) => `${px(p.cost_mid)},${py(ax.get(p))}`).join(" ")}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-dasharray="4 3" opacity=".7"/>
    ${pts.map((p, i) => `<circle cx="${px(p.cost_mid)}" cy="${py(ax.get(p))}" r="${dom[i] ? 4 : 6}" fill="${dom[i] ? "var(--line-2)" : "var(--accent)"}" stroke="var(--card)" stroke-width="1.5" class="pareto-pt" data-plan="${p.measures.join(",")}" style="cursor:pointer"><title>${esc(p.measures.map(measureShort).join(" + ") || "—")}\nCost ≈ ${gbp(p.cost_mid)} · ${ax.label}: ${ax.fmt(ax.get(p))}${dom[i] ? "\n(dominated)" : "\n★ best value on this trade-off"}</title></circle>`).join("")}
    <text x="${m.l + (W - m.l - m.r) / 2}" y="${H - 6}" class="cmp-axis" text-anchor="middle">Indicative upfront cost (£, mid)</text>
  </svg>
  <div class="cmp-legend"><span><i style="background:var(--accent)"></i>Best-value frontier (non-dominated)</span><span><i style="background:var(--line-2)"></i>Dominated package</span><span class="muted">Click a point to load it below</span></div>`;
}

// Retrofit Dependency Graph (DAG): the engine's ordered, interacting plan made visible.
// Columns = stages (fabric → controls → heat → generation); arrows = "must come first".
const STAGE_LABEL = { 1: "Fabric first", 2: "Controls", 3: "Low-carbon heat", 4: "Generation" };
const SUIT_COL = { High: "var(--good)", Medium: "var(--warn)", Low: "var(--ink-3)" };
function dependencyGraph(plan, excluded) {
  if (!plan?.length) return `<p class="muted small">No feasible upgrades to sequence for this home.</p>`;
  const stages = [...new Set(plan.map((p) => p.stage))].sort((a, b) => a - b);
  const nodeW = 158, nodeH = 64, vGap = 16, colGap = 56, padT = 30;
  const pos = {}, count = {};
  stages.forEach((s) => (count[s] = 0));
  plan.forEach((p) => { const ci = stages.indexOf(p.stage), k = count[p.stage]++; pos[p.measure_id] = { x: ci * (nodeW + colGap), y: padT + k * (nodeH + vGap) }; });
  const colH = Math.max(...stages.map((s) => padT + plan.filter((p) => p.stage === s).length * (nodeH + vGap)));
  const W = stages.length * (nodeW + colGap) - colGap, H = colH + 4;
  const edges = plan.flatMap((p) => (p.depends_on || []).map((dep) => {
    const a = pos[dep], b = pos[p.measure_id]; if (!a || !b) return "";
    const x0 = a.x + nodeW, y0 = a.y + nodeH / 2, x1 = b.x, y1 = b.y + nodeH / 2, mx = (x0 + x1) / 2;
    return `<path d="M${x0},${y0} C${mx},${y0} ${mx},${y1} ${x1},${y1}" fill="none" stroke="var(--accent-dim,var(--accent))" stroke-width="1.6" marker-end="url(#dagarr)" opacity=".85"/>`;
  })).join("");
  const nodes = plan.map((p) => { const q = pos[p.measure_id], c = p.standalone?.carbon?.total_kg, nk = p.standalone?.net_saving_kwh;
    return `<div class="dag-node" data-goto="improvements" style="left:${q.x}px;top:${q.y}px;width:${nodeW}px;height:${nodeH}px;border-left-color:${SUIT_COL[p.suitability] || "var(--ink-3)"}" title="${esc(p.name)} · ${esc(p.suitability)} suitability">
      <div class="dag-step">Step ${p.order} · ${esc(p.suitability)}</div>
      <div class="dag-name">${esc(measureShort(p.name))}</div>
      <div class="dag-impact">${c ? `−${fmt(c)} kg` : ""}${nk ? ` · −${kwh(nk)}` : ""}</div></div>`;
  }).join("");
  const heads = stages.map((s, ci) => `<div class="dag-col-head" style="left:${ci * (nodeW + colGap)}px;width:${nodeW}px">${esc(STAGE_LABEL[s] || "Stage " + s)}</div>`).join("");
  const ex = (excluded || []).length ? `<div class="dag-excluded"><span class="muted small">Not in the path:</span> ${excluded.map((e) => `<span class="tag ${e.status === "infeasible" ? "assumed" : "unavailable"}" title="${esc(e.reason || "")}">${esc(measureShort(e.name))} — ${esc((e.status || "").replace(/_/g, " "))}</span>`).join(" ")}</div>` : "";
  return `<div class="dag-wrap"><div class="dag-inner" style="width:${W}px;height:${H}px">
    <svg viewBox="0 0 ${W} ${H}" class="dag-svg" width="${W}" height="${H}"><defs><marker id="dagarr" markerWidth="8" markerHeight="8" refX="6.5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="var(--accent-dim,var(--accent))"/></marker></defs>${edges}</svg>
    ${heads}${nodes}
  </div></div>${ex}
  <div class="cmp-legend"><span>→ must be installed first</span><span><i style="background:var(--good)"></i>High</span><span><i style="background:var(--warn)"></i>Medium</span><span><i style="background:var(--ink-3)"></i>Low suitability</span></div>`;
}

// Score radar: the seven sub-scores (0–100) now vs after the recommended plan — strengths at a glance.
const RADAR_LABEL = { energy_efficiency: "Efficiency", consumption_intensity: "Intensity", insulation: "Insulation", heating_system: "Heating", glazing: "Glazing", renewables: "Renewables", smart_controls: "Controls" };
function scoreRadar(components, after) {
  const ax = components || []; const n = ax.length; if (n < 3) return "";
  const W = 320, H = 300, cx = W / 2, cy = H / 2 + 4, R = 100;
  const pt = (i, v) => { const a = -Math.PI / 2 + i * 2 * Math.PI / n, r = R * Math.max(0, Math.min(100, v)) / 100; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; };
  const poly = (vals) => vals.map((v, i) => pt(i, v).join(",")).join(" ");
  const nowV = ax.map((c) => c.sub_score);
  const aftV = ax.map((c) => after && after[c.key] != null && c.weight ? after[c.key] / c.weight : c.sub_score);
  const rings = [25, 50, 75, 100].map((v) => `<polygon points="${ax.map((_, i) => pt(i, v).join(",")).join(" ")}" fill="none" stroke="var(--line)" stroke-width="1"/>`).join("");
  const spokes = ax.map((_, i) => { const [x, y] = pt(i, 100); return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="var(--line)" stroke-width="1"/>`; }).join("");
  const labels = ax.map((c, i) => { const [x, y] = pt(i, 120); const anchor = Math.abs(x - cx) < 12 ? "middle" : (x > cx ? "start" : "end"); return `<text x="${x}" y="${y + 3}" class="cmp-axis" text-anchor="${anchor}">${esc(RADAR_LABEL[c.key] || words(c.key))}</text>`; }).join("");
  return `<svg viewBox="0 0 ${W} ${H + 16}" class="cmp-svg" role="img" aria-label="Score components now versus after the recommended plan">
    ${rings}${spokes}
    <polygon points="${poly(aftV)}" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="2"/>
    <polygon points="${poly(nowV)}" fill="none" stroke="var(--ink-3)" stroke-width="2" stroke-dasharray="4 3"/>
    ${ax.map((c, i) => { const [x, y] = pt(i, c.sub_score); return `<circle cx="${x}" cy="${y}" r="2.5" fill="var(--ink-3)"><title>${esc(RADAR_LABEL[c.key] || c.key)} now ${fmt(c.sub_score, 0)}/100</title></circle>`; }).join("")}
    ${labels}
  </svg>
  <div class="cmp-legend"><span><i style="background:var(--accent)"></i>After the plan</span><span><i style="background:var(--ink-3)"></i>Now</span></div>`;
}

function sensitivityTornado(sens, key) {
  const rows = (sens || []).map((s) => {
    const vals = s.variants.map((v) => v[key]).filter((v) => v != null);
    return vals.length ? { label: s.label, basis: s.basis, fragile: s.fragile, lo: Math.min(...vals), hi: Math.max(...vals), current: s.current } : null;
  }).filter(Boolean).sort((a, b) => (b.hi - b.lo) - (a.hi - a.lo));
  if (!rows.length) return `<p class="muted small">No sensitivity variants available for this home.</p>`;
  const gmin = Math.min(...rows.map((r) => r.lo)), gmax = Math.max(...rows.map((r) => r.hi)), span = gmax - gmin || 1;
  const W = 580, rowH = 50, m = { l: 14, r: 50, t: 6, b: 28 }, H = m.t + rows.length * rowH + m.b;
  const px = (v) => m.l + (v - gmin) / span * (W - m.l - m.r);
  const unit = key === "carbon_kg" ? " kg CO₂e" : " score pts";
  return `<svg viewBox="0 0 ${W} ${H}" class="cmp-svg" role="img" aria-label="Sensitivity tornado">
    ${rows.map((r, i) => { const yTop = m.t + i * rowH; const yBar = yTop + 20; const bl = px(r.lo), bw = Math.max(px(r.hi) - bl, 2); return `
      <text x="${m.l}" y="${yTop + 12}" class="cmp-axis" text-anchor="start" style="fill:var(--ink-2)">${esc(r.label)}${r.fragile ? ' <tspan fill="var(--warn)">⚠ a survey would resolve this</tspan>' : ""}</text>
      <rect x="${bl}" y="${yBar}" width="${bw}" height="16" rx="4" fill="${r.fragile ? "var(--warn)" : "var(--accent)"}" opacity=".9"><title>${esc(r.label)} (currently ${esc(r.current)}, ${esc(r.basis)}): output ranges ${fmt(r.lo, 0)}–${fmt(r.hi, 0)}${unit}</title></rect>
      ${bw > 48 ? `<text x="${bl + 6}" y="${yBar + 12}" class="cmp-cnt" style="fill:var(--accent-ink)" text-anchor="start">${fmt(r.lo, 0)}</text>` : ""}
      <text x="${px(r.hi) + 5}" y="${yBar + 12}" class="cmp-axis" text-anchor="start">${fmt(r.hi, 0)}</text>`; }).join("")}
    <text x="${m.l + (W - m.l - m.r) / 2}" y="${H - 7}" class="cmp-axis" text-anchor="middle">Range of ${key === "carbon_kg" ? "package carbon saving" : "score"} as each assumed input varies</text>
  </svg>
  <div class="cmp-legend"><span><i style="background:var(--warn)"></i>Fragile — a survey would resolve it</span><span class="muted">Wider bar = the result depends more on this input</span></div>`;
}

function sankey(flows, caption) {
  if (!flows?.length) return `<p class="muted small">No energy-flow breakdown for this home.</p>`;
  const srcs = [...new Set(flows.map((f) => f.source))], tgts = [...new Set(flows.map((f) => f.target))];
  const total = flows.reduce((a, f) => a + f.kwh, 0) || 1;
  const nRows = Math.max(srcs.length, tgts.length);
  const W = 600, H = Math.max(150, nRows * 44), m = { t: 10, b: 10, l: 104, r: 132 }, nodeW = 12, gap = 8;
  const plotH = H - m.t - m.b;
  const srcTot = {}, tgtTot = {}; flows.forEach((f) => { srcTot[f.source] = (srcTot[f.source] || 0) + f.kwh; tgtTot[f.target] = (tgtTot[f.target] || 0) + f.kwh; });
  const scale = (plotH - gap * (nRows - 1)) / total;
  const fuelCol = (s) => /elec|grid/i.test(s) ? "var(--elec)" : /gas/i.test(s) ? "var(--gas)" : /solar/i.test(s) ? "var(--solar)" : "var(--accent)";
  const xL = m.l, xR = W - m.r - nodeW;
  let sy = m.t; const sPos = {}; srcs.forEach((s) => { const h = srcTot[s] * scale; sPos[s] = { y: sy, h, off: 0 }; sy += h + gap; });
  let ty = m.t; const tPos = {}; tgts.forEach((t) => { const h = tgtTot[t] * scale; tPos[t] = { y: ty, h, off: 0 }; ty += h + gap; });
  const links = flows.map((f) => {
    const s = sPos[f.source], t = tPos[f.target], h = f.kwh * scale;
    const y0 = s.y + s.off + h / 2, y1 = t.y + t.off + h / 2; s.off += h; t.off += h;
    const x0 = xL + nodeW, x1 = xR, cx = (x0 + x1) / 2;
    return `<path d="M${x0},${y0} C${cx},${y0} ${cx},${y1} ${x1},${y1}" stroke="${fuelCol(f.source)}" stroke-width="${Math.max(h, 1)}" fill="none" opacity=".3"><title>${esc(f.source)} → ${esc(f.target)}: ${kwh(f.kwh)}</title></path>`;
  }).join("");
  const nodes = srcs.map((s) => `<rect x="${xL}" y="${sPos[s].y}" width="${nodeW}" height="${Math.max(sPos[s].h, 1)}" rx="2" fill="${fuelCol(s)}"/><text x="${xL - 6}" y="${sPos[s].y + sPos[s].h / 2 + 3}" class="cmp-axis" text-anchor="end">${esc(s)}</text>`).join("") +
    tgts.map((t) => `<rect x="${xR}" y="${tPos[t].y}" width="${nodeW}" height="${Math.max(tPos[t].h, 1)}" rx="2" fill="var(--line-2)"/><text x="${xR + nodeW + 6}" y="${tPos[t].y + tPos[t].h / 2 + 3}" class="cmp-axis" text-anchor="start">${esc(t)}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="cmp-svg" role="img" aria-label="${esc(caption)}">${links}${nodes}</svg>`;
}

// ──────────────────────────────────────────────────────────── PAGES
function pageHead(title, sub) { return `<div class="page-head"><h1>${esc(title)}</h1>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`; }

// ── Home overview ──────────────────────────────────────────
async function pageOverview() {
  const { facts: f } = await loadFacts(S.pid);
  const [st, pf] = await Promise.all([
    api(`/api/properties/${encodeURIComponent(S.pid)}/standing`).catch(() => null),
    getPortfolio().catch(() => null),
  ]);
  const sum = f.property_summary, sc = f.score, pkg = f.package, nba = f.next_best_action, val = f.value;
  const ev = energyView(f);
  const purchased = ev.total;
  const im = pkg?.impact;
  const savePounds = im ? poundsPerYear(im.electricity.saving_kwh, im.gas.saving_kwh) : 0;
  const saveTonnes = im?.carbon?.total_tonnes || 0;
  const issues = (sc.issues || []).slice(0, 3);
  const recs = (f.plan || []).slice(0, 3);

  return `${pageHead("Overview", `A plain-language read of <b>${esc(S.pid)}</b> — where it stands today and the single most useful next step.`)}

  ${im && savePounds > 0 ? `<div class="loss-banner">
    <div class="loss-ico">⚠</div>
    <div><b>This home is leaving about ${rc(gbp(savePounds), im.carbon?.receipt)} and ${fmt(saveTonnes, 2)} t CO₂ on the table every year.</b>
    <div class="small">That's the bill and carbon the recommended plan would stop wasting — ${esc(carbonEquiv(saveTonnes))}. Money figure indicative, at the Ofgem cap; energy &amp; carbon are engine-computed.</div></div>
    <button class="btn primary sm" data-goto="improvements">Stop the waste →</button>
  </div>` : ""}

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
        </div><div class="btn-row" style="margin-top:12px"><button class="btn sm" data-goto="plans">Compare options</button><button class="btn sm ghost" data-goto="improvements">Energy &amp; carbon detail</button></div>`
          : `<p class="muted">No feasible package for this home yet.</p>`}
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-eyebrow">How you compare</div>
    <div class="card"><div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">
      <div>${st?.similar ? `This home scores higher than <b>${fmt(st.similar.percentile)}%</b> of ${fmt(st.similar.homes)} ${esc(st.similar.definition)} homes; the typical similar home scores <b>${fmt(st.similar.median_score)}</b>.` : "Peer comparison available for this home."}</div>
      <button class="btn sm" data-goto="compare">See full comparison →</button>
    </div></div>
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
  // data completeness is distinct from calculation confidence — show both
  const comps = sc.components || [];
  const measured = comps.filter((c) => BASIS_TAG[c.basis] === "measured").length;
  const conf = f.confidence || {};
  const confReceipt = { output: "confidence", value: conf.value, unit: "0–1 (high ≥ 0.75)",
    method: "Starts at 0.90; −0.04 per assumed/estimated component, −0.15 if a component can't be assessed, −0.2/−0.1/−0.03 per conflict, −0.2 if baseline is only estimated",
    method_version: "pipeline/_confidence", provider: "deterministic", notes: conf.reasons };

  return `${pageHead("Score Breakdown", `Every input, every sub-score, and anything still unresolved for <b>${esc(S.pid)}</b>.`)}

  <div class="card pad-lg"><div class="hero-identity">
    <div class="score-hero">${scoreRing(sc.score, sc.band, sc.score_range)}<div><div>${bandChip(sc.band, sc.score)}</div><h2 style="margin-top:6px">${sc.score != null ? `${sc.score}/100` : (sc.score_range ? `${sc.score_range[0]}–${sc.score_range[1]}` : "—")}</h2>
      <div class="small muted">${esc(sc.status)} · confidence ${rc(`${esc(conf.level)} · ${fmt(conf.value, 2)}`, confReceipt)} · <b>${measured}/${comps.length}</b> components measured</div></div></div>
    <div class="identity-facts">
      <div><span class="k">Type</span><b>${esc(words(sum.property_type))}</b></div>
      <div><span class="k">Age band</span><b>${esc(words(sum.age_band))} ${tag(ib(f.inputs?.age_band))}</b></div>
      <div><span class="k">Walls</span><b>${esc(words(iv(f.inputs?.wall_type)))}${iv(f.inputs?.wall_insulated) ? ", insulated" : ", uninsulated"} ${tag(ib(f.inputs?.wall_type))}</b></div>
      <div><span class="k">Loft</span><b>${iv(f.inputs?.loft_insulation_mm) != null ? iv(f.inputs.loft_insulation_mm) + " mm" : "—"} ${tag(ib(f.inputs?.loft_insulation_mm))}</b></div>
      <div><span class="k">Glazing</span><b>${esc(words(iv(f.inputs?.glazing)))} ${tag(ib(f.inputs?.glazing))}</b></div>
      <div><span class="k">EPC</span><b>${esc(f.epc_band || "—")} ${sum.epc_year ? `(${sum.epc_year})` : ""}</b></div>
    </div>
  </div></div>

  <div class="section"><h2>Where this home stands</h2>
    <div class="grid cols-2">
      <div class="card"><h3>Score profile — now vs after the plan</h3>
        <div class="card-sub">Each of the seven components, 0–100. The dashed outline is today; the filled shape is after the recommended upgrades. Dents point to where the home is weakest.</div>
        ${scoreRadar(sc.components, f.package?.components_after)}</div>
      <div class="card"><h3>Biggest point gaps</h3>
        <div class="card-sub">Components losing the most against a perfect 100 — where the upgrades focus.</div>
        ${(sc.components || []).slice().sort((a, b) => (b.weight * (100 - b.sub_score)) - (a.weight * (100 - a.sub_score))).slice(0, 5).map((c) => { const gap = c.weight * (100 - c.sub_score); const max = Math.max(...sc.components.map((x) => x.weight * (100 - x.sub_score)), 1); return `<div class="comp-row" style="grid-template-columns:1.2fr 1fr auto;padding:8px 0"><div class="comp-name">${esc(c.label)}</div><div class="comp-bar"><div class="bar"><span style="width:${gap / max * 100}%;background:var(--bad)"></span></div></div><div class="comp-contrib">−${fmt(gap, 1)}<small>pts</small></div></div>`; }).join("")}</div>
    </div>
  </div>

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
  return `${pageHead("AI Advisor", `Ask anything about <b>${esc(S.pid)}</b>. Numbers are computed by the engine and checked before you see them — the model never invents figures.`)}
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
      links: [{ to: "plans", label: "Compare options" }, { to: "improvements", label: "Energy & carbon detail" }],
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
  const pkg = f.package, im = pkg?.impact;
  const savePounds = im ? poundsPerYear(im.electricity.saving_kwh, im.gas.saving_kwh) : 0;
  return `${pageHead("Recommended Upgrades", `A prioritised list of feasible upgrades for <b>${esc(S.pid)}</b> — ordered so each one is sized for the home the earlier steps leave behind. Savings are estimates, not guarantees.`)}

  ${pkg ? `<div class="card pad-lg" style="margin-bottom:18px"><div class="section-eyebrow">If you do the whole recommended package</div>
    <div class="grid cols-4" style="gap:14px">
      <div class="stat"><span class="k">Score</span><span class="v sm">${f.score?.score ?? "—"} → <b>${pkg.score_after}</b></span><span class="foot">${esc(f.score?.band || "")} → ${esc(pkg.band_after || "")}</span></div>
      <div class="stat"><span class="k">Purchased energy</span><span class="v sm delta good">−${pct(pkg.improvement_potential?.pct)}</span><span class="foot">${rc(kwh(im.net_saving_kwh), im.carbon?.receipt)} less/yr</span></div>
      <div class="stat"><span class="k">Carbon</span><span class="v sm delta good">−${fmt(im.carbon?.total_tonnes, 2)} t</span><span class="foot">CO₂e/yr${carbonEquiv(im.carbon?.total_tonnes) ? " · " + esc(carbonEquiv(im.carbon.total_tonnes)) : ""}</span></div>
      <div class="stat"><span class="k">Bill saving</span><span class="v sm">${savePounds > 0 ? gbp(savePounds) + "/yr" : "—"}</span><span class="foot">indicative, at the Ofgem cap</span></div>
    </div>
    <div class="readout warn" style="margin-top:4px">${savePounds > 0 ? `Every year you wait is about ${gbp(savePounds)} and ${fmt(im.carbon?.total_tonnes, 2)} t CO₂ not saved.` : ""}</div>
  </div>` : ""}

  ${pkg && f.score?.components ? `<div class="card" style="margin-bottom:18px"><div class="grid cols-2" style="align-items:center">
    <div><h3>Where you are vs where you could be</h3><div class="card-sub">Your seven score components today (dashed) and after the recommended upgrades (filled). The upgrades target the dents.</div>
      <div class="btn-row"><button class="btn sm" data-goto="property">Full score breakdown →</button></div></div>
    <div>${scoreRadar(f.score.components, f.package?.components_after)}</div>
  </div></div>` : ""}

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

  <div class="section">${aiCard(S.pid, "package", "Why these improvements, in this order")}</div>

  <div class="section"><h2>Energy &amp; carbon impact</h2>
    <div class="card-sub" style="margin-bottom:12px">Electricity and gas tracked separately, baseline vs the recommended package, with the carbon that follows. A heat pump can raise electricity while cutting gas — shown honestly.</div>
    ${energySection(f)}</div>

  <div class="section"><h2>Indicative property value</h2>
    <div class="card-sub" style="margin-bottom:12px">A range from historical EPC-band / sale-price relationships in our dataset — explicitly not a valuation, a guarantee, or proof that retrofitting causes a price rise.</div>
    ${valueSection(f)}</div>`;
}

// ── Compare Options (Decision Lab) ───────────────────────────
const PLAN = { picked: new Set(), budget: 15000 };
async function pagePlans() {
  const lab = await api(`/api/properties/${encodeURIComponent(S.pid)}/lab?budget=${PLAN.budget}&objective=${S.objective}`);
  LAB = lab;
  const feasible = [...new Set(lab.packages.flatMap((p) => p.measures))];
  const pfacts = (await loadFacts(S.pid)).facts;
  const measureName = {};
  pfacts.plan.forEach((p) => (measureName[p.measure_id] = p.name));
  if (!PLAN.picked.size && lab.base_package) lab.base_package.forEach((m) => PLAN.picked.add(m));

  return `${pageHead("Compare Options", `Build and compare retrofit packages for <b>${esc(S.pid)}</b>, each re-calculated by the engine — per fuel, carbon, and indicative value. Savings are never simply added; interactions are accounted for.`)}
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
    <h3>Best-value frontier <span class="muted" style="font-weight:400">· Pareto</span></h3>
    <div class="card-sub">Every feasible package the engine re-ran: upfront cost vs what you get. Points on the dashed line give the most benefit for the cost; click one to load it.</div>
    <div class="btn-row" id="pareto-tabs">${Object.entries(PARETO_AXES).map(([k, a]) => `<button class="btn sm ${k === LABKEY.pareto ? "primary" : ""}" data-pareto="${k}">${esc(a.label.split(" (")[0])}</button>`).join("")}</div>
    <div id="pareto" style="margin-top:12px"></div>
  </div></div>

  <div class="section"><div class="card">
    <h3>Retrofit order &amp; dependencies <span class="muted" style="font-weight:400">· the physics, not a list</span></h3>
    <div class="card-sub">The engine sequences upgrades through a dependency graph: fabric first, then controls, low-carbon heat, and generation. An arrow means "must come first" — a heat pump is sized for the home insulation leaves behind, which is why savings never simply add up.</div>
    ${dependencyGraph(pfacts.plan, pfacts.excluded)}
  </div></div>

  <div class="section"><div class="card"><h3>What the result depends on</h3><div class="card-sub">How far the outcome moves as each assumed input varies. Wider bar = more sensitive; ⚠ = a survey would resolve it.</div>
    <div class="btn-row" id="torn-tabs">${[["carbon_kg", "Carbon"], ["score", "Score"]].map(([k, l]) => `<button class="btn sm ${k === LABKEY.torn ? "primary" : ""}" data-torn="${k}">${l}</button>`).join("")}</div>
    <div id="torn" style="margin-top:12px"></div></div></div>`;
}
function drawPareto() { const el = $("#pareto"); if (el && LAB) { el.innerHTML = paretoChart(LAB.packages, LABKEY.pareto); afterRender(el); } }
function drawTorn() { const el = $("#torn"); if (el && LAB) el.innerHTML = sensitivityTornado(LAB.sensitivity, LABKEY.torn); }
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

// ── Energy & carbon (a section, folded into Recommended Upgrades) ──
function energySection(f) {
  const im = f.package?.impact, car = im?.carbon;
  const ef = car?.receipt?.inputs || {};
  return `<div class="grid cols-2">
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
  <div class="section"><div class="card"><h3>Where your energy goes</h3>
    <div class="card-sub">Purchased fuel → end use, in kWh/yr. Same accounting both sides; a heat pump shifts heating from gas to electricity, and the line widths are to scale.</div>
    <div class="grid cols-2" style="gap:22px">
      <div><div class="section-eyebrow" style="margin-bottom:2px">Now</div>${sankey(f.baseline_flows, "Energy flows, baseline")}</div>
      ${f.package?.flows_after?.length ? `<div><div class="section-eyebrow" style="margin-bottom:2px">After the recommended plan</div>${sankey(f.package.flows_after, "Energy flows after retrofit")}</div>` : ""}
    </div>
  </div></div>`;
}

// ── Home value (a section, folded into Recommended Upgrades) ──
function valueSection(f) {
  const v = f.value;
  return `<div class="grid cols-2">
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
  <div class="callout info" style="margin-top:16px">${esc(v.caveat)}</div>`;
}

// ── Methods & Evidence (merge of Evidence + Help) ──
async function pageMethods() {
  const ev = await api("/api/evidence");
  const m = ev.metrics || {};
  const labels = ev.score.labels || {};
  const factors = ev.emission_factors?.factors || {};
  const assumptions = Array.isArray(ev.assumptions?.items) ? ev.assumptions.items : [];
  const mScalars = Object.entries(m).filter(([, v]) => typeof v !== "object" && v != null);
  const psImpact = (i) => i && typeof i === "object" ? `${i.low_pct}–${i.high_pct}% of ${esc(i.quantity)}` : "—";
  return `${pageHead("Methods & Evidence", "How GreenIQ works, and the receipt behind every number. Nothing here is hand-typed — it reads the engine's own configuration.")}

  <div class="note law" style="margin-bottom:16px"><b>The one law.</b> Code computes every number. AI only explains. Every underlined number opens a receipt.</div>
  <div class="section-eyebrow">How it works</div>
  <div class="grid cols-2" style="margin-bottom:8px">
    <div class="card"><h3>How a home is scored</h3><p class="small">A weighted sum of seven sub-scores (PS2-fixed weights), each 0–100, each monotonic — a better state never lowers a sub-score. Energy efficiency uses the recorded EPC rating; intensity uses annualised metered kWh/m². Rounded to the nearest integer, then classified into five bands.</p></div>
    <div class="card"><h3>Savings, carbon, value</h3><p class="small">Savings are per fuel (electricity and gas separately), with interactions accounted for — never a simple sum. Carbon is ΔC = Σ ΔEⱼ × EFⱼ with DESNZ 2025 factors. Value is an indicative range from historical EPC/price relationships, explicitly non-causal.</p></div>
    <div class="card"><h3>The AI advisor</h3><p class="small">For a what-if, the engine re-runs the whole calculation first; only then does the model explain the new numbers. A grounding gate blocks any sentence containing a number or claim the engine didn't produce, and shows a checked template instead. It runs fully with no AI key.</p></div>
    <div class="card"><h3>Reading the labels</h3><div class="btn-row" style="margin-top:4px">${tag("measured")} measured · ${tag("estimated")} model estimate · ${tag("assumed")} assumed from age/type · ${tag("unavailable")} not available · <span class="tag real">real data</span> verified public dataset</div></div>
  </div>

  <div class="section-eyebrow" style="margin-top:20px">Evidence &amp; sources</div>
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
      ${Object.entries(ev.measures).map(([k, v]) => `<tr><td>${esc(v.name)}</td><td class="num">${esc(v.stage)}</td><td class="num small">${v.cost ? `${gbp(v.cost.low)}–${gbp(v.cost.high)} /${esc(v.cost.basis || "unit")}` : "—"}</td><td class="small muted">${esc((v.cost_source || "").slice(0, 44))}</td><td class="small">${psImpact(v.ps2_illustrative_impact)}</td></tr>`).join("")}
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

// ── Ranking (portfolio) ───────────────────────────
async function pageLender() {
  const p = await api("/api/portfolio");
  const k = p.kpis;
  const val = k.value || {};
  const dist = p.band_distribution.all || {};
  const classified = ["Very poor", "Poor", "Moderate", "Good", "Highly efficient"].reduce((a, b) => a + (dist[b] || 0), 0);
  const undetermined = dist.Undetermined || 0;
  const def = (t) => `class="k kpi-def" title="${esc(t)}"`;
  return `${pageHead("Ranking", `${fmt(p.n_homes)} homes · ${esc(p.data_label)}. The same engine and contracts as the single-home view. Hover any metric for its exact definition.`)}
  <div class="kpi-row">
    <div class="card"><div class="stat"><span ${def(`Mean of the point Green Home Score. Denominator: the ${fmt(k.avg_score?.n)} homes that have a point score; ${fmt(k.avg_score?.excluded)} homes with only a score range are excluded. Modelled, current state (no retrofits).`)}>Average score</span><span class="v">${fmt(k.avg_score?.value, 1)}</span><span class="foot">of ${fmt(k.avg_score?.n)} scored homes</span></div></div>
    <div class="card"><div class="stat"><span ${def(`Share flagged poor energy efficiency (Poor/Very poor, or a partial-score home the detector still flags). Numerator ${fmt(k.poor_pct?.count)}, denominator ${fmt(k.poor_pct?.n)} homes where the flag is determinable. Modelled, current state.`)}>Poor / very poor</span><span class="v">${pct(k.poor_pct?.value)}</span><span class="foot">${fmt(k.poor_pct?.count)} of ${fmt(k.poor_pct?.n)} homes</span></div></div>
    <div class="card"><div class="stat"><span ${def(`Total net purchased-energy saving if each home installed its recommended ${esc(OBJ_NAME[S.objective])} package. Denominator: ${fmt(k.opportunity?.n)} metered homes. Estimated (not observed); negative electricity means heat pumps add electricity while cutting gas.`)}>Opportunity</span><span class="v sm">${fmt(k.opportunity?.gwh, 1)} GWh</span><span class="foot">${fmt(k.opportunity?.tco2e)} t CO₂e/yr · ${fmt(k.opportunity?.n)} homes</span></div></div>
    <div class="card"><div class="stat"><span ${def(`Median indicative value uplift across homes whose EPC band improves under the recommended package (${val.band_improves != null ? fmt(val.band_improves) : "—"} homes). From historical EPC-band/price relationships in the synthetic sales data — indicative, not a valuation, not causal.`)}>Typical uplift</span><span class="v sm">${val.median_uplift_pct && val.median_uplift_pct[0] != null ? pctRange(val.median_uplift_pct[0], val.median_uplift_pct[1]) : "—"}</span><span class="foot">${val.band_improves != null ? fmt(val.band_improves) + " homes improve band" : "indicative"}</span></div></div>
  </div>

  <div class="section"><div class="card"><h3>Score band distribution</h3>
    <div class="card-sub">All ${fmt(p.n_homes)} homes. ${fmt(classified)} are classified into a band; ${fmt(undetermined)} are Undetermined (only a score range, no point band yet).</div>
    <table class="data"><thead><tr><th>Band</th><th class="num">Homes</th><th>Share</th></tr></thead><tbody>
      ${["Very poor", "Poor", "Moderate", "Good", "Highly efficient", "Undetermined"].map((b) => { const n = dist[b] || 0; const w = n / p.n_homes * 100; return `<tr><td><span class="band-dot" style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${bandCol(b)};margin-right:8px"></span>${esc(b)}</td><td class="num">${fmt(n)}</td><td class="bar-cell"><div class="bar"><span style="width:${w}%;background:${bandCol(b)}"></span></div></td></tr>`; }).join("")}
      <tr style="font-weight:700;border-top:2px solid var(--line-2)"><td>Total</td><td class="num">${fmt(p.n_homes)}</td><td class="muted small">${fmt(classified)} classified + ${fmt(undetermined)} undetermined</td></tr>
    </tbody></table>
    <div class="note small" style="margin-top:12px"><b>Why the counts differ by a little.</b> Three metrics use three deliberately different, documented populations:
      the <b>average</b> is over the ${fmt(k.avg_score?.n)} homes with a point score; the <b>band distribution</b> classifies ${fmt(classified)} homes
      (a few partial-score homes are banded because their range sits entirely in one band, yet are excluded from the average);
      and <b>poor/very poor</b> counts ${fmt(k.poor_pct?.count)} because the efficiency detector also flags some partial-score homes that have no final band.
      Every home is accounted for: ${fmt(classified)} classified + ${fmt(undetermined)} undetermined = ${fmt(p.n_homes)}.</div>
  </div></div>

  <div class="section"><div class="card"><h3>Green Home Grid</h3>
    <div class="card-sub">Every home is one tile, coloured by its score band. Synthetic demonstration portfolio — tiles are records, not map locations. Click a tile to open that home.</div>
    <div class="ghg-toolbar">
      <input class="inp sm" id="ghg-search" placeholder="Search id…" style="width:130px">
      <select class="inp sm" id="ghg-band"><option value="">All bands</option>${["Very poor", "Poor", "Moderate", "Good", "Highly efficient"].map((b) => `<option value="${b}">${b}</option>`).join("")}</select>
      <select class="inp sm" id="ghg-sort"><option value="score">Sort: score ↑</option><option value="potential">Sort: potential ↓</option><option value="id">Sort: id</option></select>
      <span class="muted small" id="ghg-count"></span>
    </div>
    <div class="ghg" id="ghg"><div class="loading"><span class="spinner"></span> Loading homes…</div></div>
    <div class="ghg-legend">${["Very poor", "Poor", "Moderate", "Good", "Highly efficient"].map((b) => `<span><i style="background:${bandCol(b)}"></i>${b}</span>`).join("")}</div>
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
    return;
  } catch (e) { body.innerHTML = `<tr><td colspan="6"><div class="errbox">${esc(e.message)}</div></td></tr>`; }
}
const GHG_MAX = 48;
const GHG = { q: "", band: "", sort: "score" };
async function fillGrid() {
  const box = $("#ghg"); if (!box) return;
  try {
    const props = await getProps();
    const draw = () => {
      let rows = props.filter((p) => (!GHG.band || p.band === GHG.band) && (!GHG.q || p.property_id.toLowerCase().includes(GHG.q.toLowerCase())));
      rows.sort((a, b) => GHG.sort === "id" ? a.property_id.localeCompare(b.property_id) : GHG.sort === "potential" ? (b.potential_pct || 0) - (a.potential_pct || 0) : (a.score ?? 999) - (b.score ?? 999));
      if ($("#ghg-count")) $("#ghg-count").textContent = rows.length > GHG_MAX ? `showing ${GHG_MAX} of ${rows.length}` : `${rows.length} homes`;
      box.innerHTML = rows.slice(0, GHG_MAX).map((p) => `<div class="ghg-tile ${p.is_poor ? "poor-flag" : ""}" data-pick="${p.property_id}" style="--bc:${bandCol(p.band)}" title="${esc(p.property_id)} · ${esc(p.band || "Undetermined")} · ${esc(p.property_type || "")}">
        <div class="ghg-score">${p.score ?? "–"}</div><div class="ghg-id">${esc(p.property_id)}</div>
        <div class="ghg-meta">${esc(p.property_type || "")} · ${fmt(p.floor_area_m2)}m²</div></div>`).join("") || `<p class="muted">No homes match.</p>`;
      $$("#ghg [data-pick]").forEach((el) => el.onclick = () => selectHome(el.dataset.pick));
    };
    draw();
    if ($("#ghg-search")) $("#ghg-search").oninput = (e) => { GHG.q = e.target.value; draw(); };
    if ($("#ghg-band")) $("#ghg-band").onchange = (e) => { GHG.band = e.target.value; draw(); };
    if ($("#ghg-sort")) $("#ghg-sort").onchange = (e) => { GHG.sort = e.target.value; draw(); };
  } catch (e) { box.innerHTML = `<div class="errbox">${esc(e.message)}</div>`; }
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

  renderPropLabel();

  // global events (delegation)
  document.addEventListener("click", (e) => {
    const askEl = e.target.closest("[data-ask]"); if (askEl) { e.preventDefault(); askAdvisor(askEl.dataset.ask); return; }
    const planEl = e.target.closest("[data-plan]"); if (planEl) { PLAN.picked = new Set(planEl.dataset.plan.split(",").filter(Boolean)); route().then(() => recomputeCustom()); return; }
    const grpEl = e.target.closest("[data-group]"); if (grpEl) { $$("#group-tabs .btn").forEach((b) => b.classList.toggle("primary", b === grpEl)); fillGroups(grpEl.dataset.group); return; }
    const pa = e.target.closest("[data-pareto]"); if (pa) { LABKEY.pareto = pa.dataset.pareto; $$("#pareto-tabs .btn").forEach((b) => b.classList.toggle("primary", b === pa)); drawPareto(); return; }
    const to = e.target.closest("[data-torn]"); if (to) { LABKEY.torn = to.dataset.torn; $$("#torn-tabs .btn").forEach((b) => b.classList.toggle("primary", b === to)); drawTorn(); return; }
    if (!e.target.closest("#prop-switch")) closePropPop();
  });
  $("#prop-btn").onclick = (e) => { e.stopPropagation(); $("#prop-pop").hidden ? openPropPop() : closePropPop(); };
  $("#menu-toggle").onclick = () => $("#sidebar").classList.toggle("open");
  $("#drawer-scrim").onclick = closeDrawer;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeDrawer(); closePropPop(); } });

  $("#obj").onchange = (e) => { S.objective = e.target.value; store.set("objective", S.objective); clearFacts(); toast(`Prioritising: ${OBJ_NAME[S.objective]}`); route(); };
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
}

boot();
