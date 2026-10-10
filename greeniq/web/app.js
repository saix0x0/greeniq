// GreenIQ web app — no build step. Every number shown comes from the API (ComputedFacts);
// this file only formats and draws. Nothing here computes energy, carbon, cost or score.

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (x, d = 0) => (x == null || Number.isNaN(x) ? "—" : Number(x).toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d }));
const gbp = (x) => (x == null ? "—" : "£" + fmt(x));
const nice = (s) => String(s ?? "").replaceAll("_", " ");
const cap = (s) => { s = nice(s); return s.charAt(0).toUpperCase() + s.slice(1); };

// ---------- settings (per-viewer conveniences only) ----------
const store = {
  get(k, d) { try { const v = localStorage.getItem("greeniq." + k); return v == null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("greeniq." + k, v); } catch { /* private mode */ } },
};
const S = { mode: store.get("mode", "evidence"), objective: store.get("objective", "value_for_money"), theme: store.get("theme", "system") };
function applyTheme() { if (S.theme === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = S.theme; }
applyTheme();

// ---------- API ----------
async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.error?.message || `HTTP ${res.status}`);
  return data;
}

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
  return `<span class="rcpt" data-r="${id}">${html}</span>`;
}
function openReceipt(r) {
  const d = $("#drawer");
  d.innerHTML = `<div class="card-head"><h3>Receipt</h3><button class="btn" id="drawer-x">Close</button></div>
    <dl class="kv"><dt>Output</dt><dd><code>${esc(r.output)}</code></dd>
    <dt>Value</dt><dd class="num"><b>${esc(typeof r.value === "number" ? fmt(r.value, Math.abs(r.value) < 10 ? 2 : 0) : JSON.stringify(r.value))}</b> ${esc(r.unit || "")}</dd>
    <dt>Method</dt><dd>${esc(r.method)}</dd><dt>Version</dt><dd><code>${esc(r.method_version)}</code></dd>
    <dt>Provider</dt><dd>${esc(r.provider || "deterministic")}</dd></dl>
    <h4>Inputs</h4><pre>${esc(JSON.stringify(r.inputs, null, 2))}</pre>
    ${r.sources?.length ? `<h4>Sources</h4><ul class="small">${r.sources.filter(Boolean).map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
    ${r.notes?.length ? `<h4>Notes</h4><ul class="small">${r.notes.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}`;
  d.classList.add("on");
  $("#drawer-x").onclick = () => d.classList.remove("on");
}
document.addEventListener("click", (e) => {
  const r = e.target.closest(".rcpt");
  if (r && S.mode === "evidence") openReceipt(RECEIPTS.get(r.dataset.r));
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#drawer").classList.remove("on"); });

// ---------- tooltip ----------
const tip = $("#tip");
document.addEventListener("mousemove", (e) => {
  const t = e.target.closest?.("[data-tip]");
  if (!t) { tip.classList.remove("on"); return; }
  tip.innerHTML = t.dataset.tip;
  tip.classList.add("on");
  const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + "px";
  tip.style.top = Math.max(e.clientY - tip.offsetHeight - 10, 8) + "px";
});

// ---------- mode toggle ----------
function syncMode() {
  const on = S.mode === "evidence";
  $("#mode-switch").setAttribute("aria-checked", String(on));
  $("#mode-label").textContent = on ? "Evidence mode" : "Demo mode";
  $("#mode-help").textContent = on ? "Every number shows its evidence tag; click a dotted number for its receipt."
    : "Clean view for presenting. Evidence stays as coloured dots (hover them).";
  document.body.classList.toggle("demo", !on);
}
$("#mode-switch").onclick = () => { S.mode = S.mode === "evidence" ? "demo" : "evidence"; store.set("mode", S.mode); syncMode(); route(); };
syncMode();

// ---------- shared bits ----------
const BANDS = ["Very poor", "Poor", "Moderate", "Good", "Highly efficient"];
const BAND_VAR = { "Very poor": "--b-vp", Poor: "--b-p", Moderate: "--b-m", Good: "--b-g", "Highly efficient": "--b-he", Undetermined: "--b-u" };
const bandColor = (b) => `var(${BAND_VAR[b] || "--b-u"})`;
const darkText = (b) => ["Good", "Highly efficient", "Moderate"].includes(b) && !matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "dark";
function scoreDot(score, band) {
  const fg = darkText(band) ? "#fff" : "var(--ink)";
  return `<span class="score-dot" style="background:${bandColor(band)};color:${fg}" data-tip="${esc(band || "band undetermined")}">${score ?? "?"}</span>`;
}
const bandBadge = (b) => `<span class="badge"><span class="band-sw" style="background:${bandColor(b)}"></span>${esc(b || "Undetermined")}</span>`;
const DISP = { recommend: "Recommend", refer_for_survey: "Refer", no_action: "No action" };
const disp = (d) => `<span class="disp ${d}">${DISP[d] || d}</span>`;
// consumption change from a saving (saving > 0 means use goes DOWN)
function fuelChange(saving, cls, name, d = 0) {
  if (saving == null) return `<span class="fuel ${cls}">${name} —</span>`;
  const ch = -saving;
  const arrow = ch > 0 ? "▲" : ch < 0 ? "▼" : "";
  return `<span class="fuel ${cls}">${name} <span class="${ch > 0 ? "up" : ch < 0 ? "down" : ""}">${arrow} ${fmt(Math.abs(ch), d)}</span></span>`;
}
function topbar(title, sub, right = "") {
  return `<div class="topbar"><div><h1>${title}</h1>${sub ? `<div class="sub">${sub}</div>` : ""}</div>${right}</div>`;
}
const synthNote = `<span class="pill-note" title="All homes, meters and sales are simulated (data/DATA_CARD.md)">Synthetic dataset · engine estimates, labelled</span>`;

// ---------- router ----------
let token = 0;
const ROUTES = { "": dashboard, properties, property, lab, analytics, evidence, settings };
async function route() {
  const [, page = "", arg] = location.hash.split("?")[0].split("/");
  const fn = ROUTES[page] || dashboard;
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on",
    a.dataset.nav === (page || "dashboard") || (page === "property" && a.dataset.nav === "properties")));
  const my = ++token;
  const main = $("#main");
  RECEIPTS.clear();
  if (!main.dataset.keep) main.innerHTML = `<div class="loading">Loading…</div>`;
  try { await fn(main, arg ? decodeURIComponent(arg) : undefined, () => my === token); }
  catch (e) { if (my === token) main.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
}
addEventListener("hashchange", route);
queueMicrotask(route); // after the whole module has evaluated (later consts are in their TDZ until then)

// =====================================================================================
// 1 · Dashboard
// =====================================================================================
async function dashboard(main, _arg, live) {
  const p = await api("/api/portfolio");
  if (!live()) return;
  const k = p.kpis;
  const op = k.opportunity;
  main.innerHTML = `
    ${topbar("Portfolio overview", `${fmt(p.n_homes)} homes · Green Home Score, improvement potential and next actions`, synthNote)}
    <div class="with-rail">
      <div class="stack">
        <div class="kpis">
          <div class="card kpi"><div class="label">Avg Green Home Score ${tag("estimated", k.avg_score.note)}</div>
            <div class="big num">${fmt(k.avg_score.value, 1)}<small> /100</small></div>
            <div class="foot"><span class="down">▲ ${fmt(k.avg_score_after.value - k.avg_score_after.before_same_homes, 1)}</span> possible with recommended packages</div></div>
          <div class="card kpi"><div class="label">Improvement opportunity ${tag("estimated", op.note)}</div>
            <div class="big num">${fmt(op.gwh, 1)}<small> GWh/yr</small></div>
            <div class="foot num">${fmt(op.tco2e)} tCO₂e/yr · ${fmt(op.n)} metered homes</div>
            ${fuelSplitMini(op)}</div>
          <div class="card kpi"><div class="label">Poor or Very poor ${tag("estimated", "share of homes whose band can be determined")}</div>
            <div class="big num">${fmt(k.poor_pct.value, 1)}<small> %</small></div>
            <div class="foot num">${fmt(k.poor_pct.count)} of ${fmt(k.poor_pct.n)} homes</div></div>
          <div class="card kpi"><div class="label">Data coverage ${tag("observed", "share of homes with each kind of evidence")}</div>
            <div class="big num">${fmt(k.coverage.metered_pct, 0)}<small> % metered</small></div>
            <div class="foot num">EPC on record ${fmt(k.coverage.epc_pct, 0)}% · fully observed score ${fmt(k.coverage.complete_score_pct, 0)}%</div></div>
        </div>
        <div class="card">
          <div class="card-head"><div><h3>Score band distribution</h3><p class="hint">How many homes sit in each Green Home Score band.</p></div>
            <div class="tabs" id="band-tabs">${[["all", "All"], ["region", "Region"], ["property_type", "Type"], ["age_band", "Age"]].map(([v, l], i) => `<button data-v="${v}" class="${i ? "" : "on"}">${l}</button>`).join("")}</div></div>
          <div id="band-chart"></div>
        </div>
        <div class="three">
          <div class="card"><h3>Portfolio goal</h3><p class="hint">Average score today vs. if every home installed its recommended package.</p>
            ${goal(k.avg_score_after)}
            <div class="small muted">${fmt(k.avg_score_after.n)} homes with a modelled package · estimate, not a forecast</div></div>
          <div class="card"><h3>Where the opportunity sits</h3><p class="hint">Share of the portfolio's carbon saving by region.</p>
            ${p.opportunity_by_region.map((r) => `<div class="hbar" data-tip="${esc(cap(r.region))}: ${fmt(r.tco2e)} tCO₂e/yr"><span>${esc(cap(r.region))}</span><div class="track"><div class="fill" style="width:${r.share_pct}%"></div></div><span class="num">${fmt(r.share_pct, 0)}%</span></div>`).join("")}</div>
          <div class="card"><h3>Quick actions</h3><p class="hint">Jump into the work.</p>
            <div style="display:grid;gap:8px">
              ${p.ranking.top[0] ? `<a class="btn primary" href="#/property/${p.ranking.top[0].property_id}">Open the top-ranked poor home →</a>
              <a class="btn" href="#/lab/${p.ranking.top[0].property_id}">Decision Lab for it ⚡</a>` : ""}
              <a class="btn" href="#/properties?disposition=refer_for_survey">Review the refer queue (${fmt(p.triage.refer_for_survey)})</a>
              <a class="btn" href="#/evidence">How every number is made ✓</a>
            </div></div>
        </div>
      </div>
      <div class="card" style="position:sticky;top:16px">
        <div class="card-head"><div><h3>Triage queue</h3><p class="hint">Poor homes by improvement potential, each with its Next Best Action.</p></div></div>
        <div class="tabs" id="tri-tabs"><button data-v="" class="on">All</button><button data-v="recommend">Recommend</button><button data-v="refer_for_survey">Refer</button></div>
        <div class="feed" id="feed"><div class="loading">Loading…</div></div>
      </div>
    </div>`;
  const drawBands = (v) => { $("#band-chart").innerHTML = v === "all" ? bandBars(p.band_distribution.all) : bandStacks(p.band_distribution[v]); };
  drawBands("all");
  tabs("#band-tabs", drawBands);
  const loadFeed = async (d) => {
    const q = d === "refer_for_survey" ? `disposition=${d}&sort=potential&limit=12` : `poor_only=true&sort=potential&limit=12${d ? "&disposition=" + d : ""}`;
    const r = await api("/api/properties?" + q);
    if (!live()) return;
    $("#feed").innerHTML = r.items.length ? r.items.map(feedItem).join("") : `<div class="empty">No homes here.</div>`;
  };
  loadFeed("");
  tabs("#tri-tabs", loadFeed);
}

function tabs(sel, onPick) {
  const el = $(sel);
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    el.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    onPick(b.dataset.v);
  });
}

function feedItem(r) {
  const pot = r.potential_status === "available" ? `${fmt(r.potential_pct, 0)}%` : "—";
  return `<a class="feed-item" href="#/property/${r.property_id}">
    ${scoreDot(r.score ?? (r.score_range ? r.score_range.join("–") : "?"), r.band)}
    <div style="min-width:0"><div class="t1">${r.property_id} <span class="muted small">· ${esc(cap(r.property_type))}, ${esc(cap(r.region))}</span></div>
      <div class="t2">${disp(r.nba_disposition)} ${esc(r.nba_label)}</div></div>
    <div class="num small" style="text-align:right" data-tip="Improvement potential: share of purchased energy the recommended package could save (estimate)"><b>${pot}</b><div class="muted">potential</div></div></a>`;
}

function fuelSplitMini(op) {
  // Answers "greener means lower bills everywhere": gas falls a lot, electricity can rise.
  return `<div class="small" style="margin-top:8px;display:flex;gap:12px;flex-wrap:wrap">
    <span>${fuelChange(op.gas_gwh, "gs", "Gas", 1)} <span class="muted">GWh</span></span>
    <span data-tip="Heat pumps raise electricity while cutting gas by more">${fuelChange(op.electricity_gwh, "el", "Electricity", 2)} <span class="muted">GWh ⓘ</span></span></div>`;
}

function goal(a) {
  const now = a.before_same_homes, after = a.value;
  return `<div class="prog"><div class="ghost" style="width:${after}%"></div><div class="fill" style="width:${now}%"></div>
    <span class="mk num" style="left:${now}%">${fmt(now, 1)} now</span><span class="mk num" style="left:${after}%;color:var(--accent)">${fmt(after, 1)}</span></div>
    <div class="small num" style="display:flex;justify-content:space-between" class="muted"><span>0</span><span>Moderate 55</span><span>100</span></div>`;
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
function bandStacks(groups) {
  const cats = [...BANDS, "Undetermined"];
  const rows = Object.entries(groups);
  const W = 640, rowH = 26, labW = 110, H = rows.length * (rowH + 10) + 4;
  const body = rows.map(([g, d], i) => {
    const total = cats.reduce((s, c) => s + (d[c] || 0), 0) || 1;
    let x = labW;
    const y = i * (rowH + 10);
    const segs = cats.map((c) => {
      const w = ((W - labW - 46) * (d[c] || 0)) / total;
      const s = w > 0 ? `<rect x="${x}" y="${y}" width="${w}" height="${rowH}" rx="3" style="fill:${bandColor(c)};stroke:var(--card);stroke-width:2"
        data-tip="<b>${esc(cap(g))}</b> · ${esc(c)}<br>${fmt(d[c])} homes · ${fmt((100 * d[c]) / total, 1)}%"/>` : "";
      x += w;
      return s;
    }).join("");
    const poor = (100 * ((d["Very poor"] || 0) + (d.Poor || 0))) / total;
    return `<text x="0" y="${y + 17}">${esc(cap(g))}</text>${segs}<text class="val num" x="${W - 40}" y="${y + 17}">${fmt(poor, 0)}%</text>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Score bands by group">${body}</svg>
    <div class="legend">${cats.map((c) => `<span><span class="band-sw" style="background:${bandColor(c)}"></span>${c}</span>`).join("")}<span class="muted">· right: % Poor or Very poor</span></div>`;
}

// =====================================================================================
// 2 · Properties
// =====================================================================================
async function properties(main, _arg, live) {
  const qs = new URLSearchParams(location.hash.split("?")[1] || "");
  const f = { q: qs.get("q") || "", band: qs.get("band") || "", region: qs.get("region") || "", property_type: qs.get("property_type") || "",
    disposition: qs.get("disposition") || "", sort: qs.get("sort") || "potential", offset: +(qs.get("offset") || 0) };
  const opt = (name, vals, label) => `<select data-f="${name}"><option value="">${label}</option>${vals.map(([v, l]) => `<option value="${v}" ${f[name] === v ? "selected" : ""}>${l}</option>`).join("")}</select>`;
  main.innerHTML = `${topbar("Properties", "Search, filter and open any home", synthNote)}
    <div class="card">
      <div class="filters">
        <input type="search" placeholder="Search ID, customer, region, type…" value="${esc(f.q)}" data-f="q">
        ${opt("band", BANDS.map((b) => [b, b]), "Any band")}
        ${opt("region", ["london", "south_east", "south_west", "midlands", "north", "wales", "scotland"].map((r) => [r, cap(r)]), "Any region")}
        ${opt("property_type", ["detached", "semi_detached", "terraced", "bungalow", "flat"].map((r) => [r, cap(r)]), "Any type")}
        ${opt("disposition", Object.entries(DISP), "Any next action")}
        ${opt("sort", [["potential", "Sort: improvement potential"], ["score", "Sort: lowest score"], ["property_id", "Sort: ID"]], "Sort")}
      </div>
      <div id="tbl" style="margin-top:14px"><div class="loading">Loading…</div></div>
    </div>`;
  const go = (patch) => {
    const n = { ...f, ...patch };
    const s = new URLSearchParams(Object.entries(n).filter(([, v]) => v !== "" && v !== 0));
    location.hash = "#/properties?" + s.toString();
  };
  main.querySelectorAll("[data-f]").forEach((el) => {
    el.addEventListener("change", () => go({ [el.dataset.f]: el.value, offset: 0 }));
  });
  const p = new URLSearchParams({ ...Object.fromEntries(Object.entries(f).filter(([, v]) => v !== "")), limit: 25 });
  const r = await api("/api/properties?" + p);
  if (!live()) return;
  $("#tbl").innerHTML = `<div class="small muted" style="margin-bottom:8px">${fmt(r.total)} homes</div>
    <div class="table-wrap"><table class="t"><thead><tr><th>Home</th><th>Type · region</th><th>Floor area</th><th>Score</th><th>Confidence</th><th>Baseline</th><th>Potential</th><th>Next best action</th></tr></thead><tbody>
    ${r.items.map((x) => `<tr data-id="${x.property_id}"><td><b>${x.property_id}</b></td><td>${esc(cap(x.property_type))} · ${esc(cap(x.region))}</td>
      <td class="num">${x.floor_area_m2 == null ? "—" : fmt(x.floor_area_m2) + " m²"}</td>
      <td>${x.score != null ? `<b class="num">${x.score}</b>` : `<span class="num">${x.score_range ? x.score_range.join("–") : "—"}</span>`} ${bandBadge(x.band)}</td>
      <td>${esc(x.confidence)}</td><td>${tag(x.baseline_basis)}</td>
      <td class="num">${x.potential_status === "available" ? fmt(x.potential_pct, 0) + "%" : `<span class="muted" title="${esc(x.potential_reason)}">n/a</span>`}</td>
      <td>${disp(x.nba_disposition)} ${esc(x.nba_label)}</td></tr>`).join("")}
    </tbody></table></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
      <button class="btn" ${f.offset <= 0 ? "disabled" : ""} id="prev">← Prev</button>
      <span class="small muted" style="align-self:center">${fmt(f.offset + 1)}–${fmt(Math.min(f.offset + 25, r.total))}</span>
      <button class="btn" ${f.offset + 25 >= r.total ? "disabled" : ""} id="next">Next →</button></div>`;
  $("#tbl tbody").addEventListener("click", (e) => { const tr = e.target.closest("tr"); if (tr) location.hash = "#/property/" + tr.dataset.id; });
  $("#prev").onclick = () => go({ offset: Math.max(f.offset - 25, 0) });
  $("#next").onclick = () => go({ offset: f.offset + 25 });
  const search = main.querySelector('[data-f="q"]');
  search.addEventListener("keydown", (e) => { if (e.key === "Enter") go({ q: search.value, offset: 0 }); });
}

// =====================================================================================
// 3 · Property view
// =====================================================================================
async function loadFacts(id) {
  if (S.objective === "value_for_money") return api(`/api/properties/${encodeURIComponent(id)}`);
  return api(`/api/properties/${encodeURIComponent(id)}/scenarios`, { objective: S.objective, name: "Recommended package" });
}

async function property(main, id, live) {
  if (!id) { location.hash = "#/properties"; return; }
  const { facts: f, explanation } = await loadFacts(id);
  if (!live()) return;
  const ps = f.property_summary;
  const state = { picked: new Set(), result: null };
  main.innerHTML = `
    ${topbar(`${f.property_id} <span class="muted" style="font-weight:500">· ${esc(cap(ps.property_type))}${ps.flat_position ? " (" + esc(ps.flat_position) + " floor)" : ""}, ${esc(cap(ps.region))}</span>`,
      `${ps.floor_area_m2 ? fmt(ps.floor_area_m2) + " m² · " : ""}${ps.age_band ? "built " + esc(nice(ps.age_band)) + " · " : ""}heating: ${esc(nice(ps.heating_system_recorded || "unknown"))} · customer ${esc(ps.customer_id)}`,
      `<div style="display:flex;gap:8px;flex-wrap:wrap">${synthNote}<a class="btn primary" href="#/lab/${f.property_id}">Open in Decision Lab ⚡</a></div>`)}
    ${f.warnings.length ? `<div class="banner">${f.warnings.map(esc).join(" · ")}</div>` : ""}
    <div class="with-rail">
      <div class="stack">
        <div class="kpis">${propertyKpis(f)}</div>
        <div class="card" id="decomp-card"></div>
        <div class="card explain"><div class="card-head"><h3>In plain English</h3><span class="src">template narrator · every sentence built from computed facts</span></div>
          ${explanation.sentences.map((s, i) => `<p ${i > 3 ? "hidden data-more" : ""}>${esc(s.text)}${S.mode === "evidence" ? ` <span class="ref" style="display:inline">← ${esc(s.refs.join(", "))}</span>` : ""}</p>`).join("")}
          ${explanation.sentences.length > 4 ? `<button class="btn" id="more">Show the full explanation</button>` : ""}</div>
        <div class="three">
          <div class="card">${nbaCard(f.next_best_action)}</div>
          <div class="card">${energySplit(f)}</div>
          <div class="card" id="try"></div>
        </div>
        <div class="card" id="try-result" hidden></div>
      </div>
      <div class="card" style="position:sticky;top:16px">${recRail(f)}</div>
    </div>`;
  $("#more")?.addEventListener("click", (e) => { main.querySelectorAll("[data-more]").forEach((p) => (p.hidden = false)); e.target.remove(); });
  const drawDecomp = () => { $("#decomp-card").innerHTML = decomposition(f, state.result); };
  drawDecomp();
  tabs("#rec-tabs", (v) => { main.querySelectorAll("[data-pane]").forEach((p) => (p.hidden = p.dataset.pane !== v)); });

  const drawTry = () => {
    $("#try").innerHTML = `<h3>Try a change</h3><p class="hint">Pick measures; the engine re-runs this home and everything updates.</p>
      ${f.plan.length ? `<div style="display:flex;gap:6px;flex-wrap:wrap">${f.plan.map((r) => `<button class="chip ${state.picked.has(r.measure_id) ? "on" : ""}" data-m="${r.measure_id}">${esc(r.name.replace(/ \(.*\)/, ""))}</button>`).join("")}</div>
        <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap"><button class="btn" data-all>Whole recommended package</button>${state.picked.size ? `<button class="btn" data-clear>Clear</button>` : ""}</div>`
        : `<div class="empty">No feasible measures to try for this home.</div>`}`;
  };
  drawTry();
  let seq = 0;
  const run = async () => {
    const mine = ++seq;
    const out = $("#try-result");
    if (!state.picked.size) { state.result = null; out.hidden = true; drawDecomp(); return; }
    out.hidden = false;
    out.innerHTML = `<div class="loading">Re-running the engine…</div>`;
    try {
      const r = await api(`/api/properties/${f.property_id}/scenarios`, { measures: [...state.picked], objective: S.objective, name: "What-if" });
      if (mine !== seq || !live()) return;
      state.result = r.facts;
      out.innerHTML = scenarioResult(f, r);
      drawDecomp();
    } catch (e) { out.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  };
  $("#try").addEventListener("click", (e) => {
    const c = e.target.closest("[data-m]");
    if (c) { state.picked.has(c.dataset.m) ? state.picked.delete(c.dataset.m) : state.picked.add(c.dataset.m); }
    else if (e.target.closest("[data-all]")) f.plan.forEach((r) => state.picked.add(r.measure_id));
    else if (e.target.closest("[data-clear]")) state.picked.clear();
    else return;
    drawTry();
    run();
  });
}

function propertyKpis(f) {
  const s = f.score, b = f.baseline, el = b.electricity, gs = b.gas, v = f.value;
  const total = el.annual_kwh != null && gs.annual_kwh != null ? el.annual_kwh + gs.annual_kwh : null;
  const scoreBig = s.score != null ? `${rc(s.receipt, s.score)}<small> /100</small>` : `${s.score_range[0]}–${s.score_range[1]}<small> range</small>`;
  const em = f.baseline_emissions_kg;
  return `
    <div class="card kpi"><div class="label">Green Home Score ${tag(s.status, s.status === "complete" ? "all components from observed data" : "some inputs assumed or missing")}</div>
      <div class="big num">${scoreBig}</div>
      <div class="foot">${bandBadge(s.band)} <span class="muted">confidence ${esc(f.confidence.level)}</span></div></div>
    <div class="card kpi"><div class="label">Purchased energy ${tag(f.baseline_basis)}</div>
      <div class="big num">${total == null ? "—" : fmt(total)}<small> kWh/yr</small></div>
      <div class="foot num"><span class="fuel el">${el.annual_kwh == null ? "—" : rc(el.receipt, fmt(el.annual_kwh))}</span> ${tag(el.basis, el.provider)}
        &nbsp; <span class="fuel gs">${gs.annual_kwh == null ? "—" : rc(gs.receipt, fmt(gs.annual_kwh))}</span> ${tag(gs.basis, gs.provider)}
        <div class="muted">${f.intensity_kwh_m2.value == null ? "intensity unavailable" : fmt(f.intensity_kwh_m2.value) + " kWh/m²/yr"}</div></div></div>
    <div class="card kpi"><div class="label">Carbon ${tag(em.basis, em.note)}</div>
      <div class="big num">${em.value == null ? "—" : fmt(em.value / 1000, 1)}<small> tCO₂e/yr</small></div>
      <div class="foot">${f.package ? `<span class="down">▼ ${fmt(f.package.impact.carbon.total_tonnes, 2)} t</span> with the recommended package` : "no package modelled"}</div></div>
    <div class="card kpi"><div class="label">Value estimate ${tag(v && v.status === "available" ? "estimated" : "unavailable", v?.caveat)}</div>
      ${v && v.status === "available" ? `<div class="big num">${rc(v.receipt, gbp(v.current_value))}</div>
        <div class="foot num">range ${gbp(v.current_range[0])}–${gbp(v.current_range[1])}${v.uplift_pct_range ? `<div><span class="down">▲ ${fmt(v.uplift_pct_range[0], 1)}% to ${fmt(v.uplift_pct_range[1], 1)}%</span> indicative, not a promise</div>` : ""}</div>`
        : `<div class="big">—</div><div class="foot muted">${esc(v?.reason || "unavailable")}</div>`}</div>`;
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

function nbaCard(n) {
  if (!n) return `<div class="empty">No next best action.</div>`;
  return `<div class="card-head"><h3>Next best action</h3>${disp(n.disposition)}</div>
    <div class="nba-head">${esc(n.headline)}</div>
    <div class="small muted">confidence ${esc(n.confidence)}${n.benefit != null ? ` · ${fmt(n.benefit)} ${esc(n.benefit_unit)}` : ""}</div>
    ${n.reasons.map((r, i) => `<div class="reason"><span class="n">${i + 1}</span><div>${esc(r.text)}${S.mode === "evidence" ? `<span class="ref">← ${esc(r.fact_ref)}</span>` : ""}</div></div>`).join("")}
    ${n.blocked_by ? `<div class="banner" style="margin:8px 0 0">${esc(n.blocked_by)}</div>` : ""}
    ${n.alternatives.length ? `<div class="sep"></div><div class="small muted">Then: ${n.alternatives.map((a) => `${esc(a.action.label)} <i>(${esc(a.why_not_first)})</i>`).join(" · ")}</div>` : ""}`;
}

function energySplit(f) {
  const rows = [["electricity", "el", "Electricity"], ["gas", "gs", "Gas"]].map(([k, cls, name]) => {
    const b = f.baseline[k];
    if (b.annual_kwh == null) return `<div class="small"><span class="fuel ${cls}">${name}</span> unavailable ${tag(b.basis)}</div>`;
    if (!b.annual_kwh) return `<div class="small"><span class="fuel ${cls}">${name}</span> 0 kWh ${tag(b.basis)}</div>`;
    const heat = b.heating_kwh ?? null, base = b.baseload_kwh ?? (heat != null ? b.annual_kwh - heat : null);
    const hp = heat == null ? 0 : (100 * heat) / b.annual_kwh;
    return `<div style="margin:12px 0"><div class="small" style="display:flex;justify-content:space-between"><span class="fuel ${cls}">${name}</span><span class="num">${rc(b.receipt, fmt(b.annual_kwh))} kWh ${tag(b.basis)}</span></div>
      <div style="display:flex;height:12px;border-radius:6px;overflow:hidden;margin-top:6px;gap:2px">
        <div style="width:${hp}%;background:var(--${cls === "el" ? "elec" : "gas"})" data-tip="Space heating (weather-dependent): ${fmt(heat)} kWh"></div>
        <div style="flex:1;background:color-mix(in srgb, var(--${cls === "el" ? "elec" : "gas"}) 35%, var(--card))" data-tip="Baseload (hot water, cooking, appliances): ${fmt(base)} kWh"></div></div>
      <div class="small muted num" style="display:flex;justify-content:space-between;margin-top:3px"><span>heating ${fmt(heat)}</span><span>baseload ${fmt(base)}</span></div></div>`;
  }).join("");
  return `<h3>Where the energy goes</h3><p class="hint">Weather-normalised year, split by degree-day regression into heating vs. baseload.</p>${rows}`;
}

function recRail(f) {
  const n = f.next_best_action;
  const refer = f.excluded.filter((e) => e.status === "needs_survey");
  const notSuit = f.excluded.filter((e) => e.status !== "needs_survey");
  const recs = f.plan.map((r) => `<div class="rec ${n?.action.ref === r.measure_id ? "lead" : ""}">
      <div class="r1"><span>${r.order}. ${esc(r.name)}</span><span class="badge">${esc(r.suitability)}</span></div>
      <div class="r2">${esc(r.stage_label)}${r.depends_on.length ? ` · after ${esc(r.depends_on.map(nice).join(", "))}` : ""}</div>
      <div class="r2 num" style="display:flex;gap:12px;flex-wrap:wrap" data-tip="In-package change per year (this measure after the ones before it). ▲ = more use.">
        ${fuelChange(r.in_package.electricity.saving_kwh, "el", "Elec")} ${fuelChange(r.in_package.gas.saving_kwh, "gs", "Gas")} <span class="muted">kWh/yr</span> ${tag("estimated", "engine estimate, not a guarantee")}</div>
      <div class="r2 num">${rc(r.receipt, `${gbp(r.cost_low)}–${gbp(r.cost_high)}`)} <span class="muted">indicative</span></div></div>`).join("");
  return `<div class="card-head"><div><h3>Recommendations</h3><p class="hint">Led by the Next Best Action; feasible measures only, in a sensible order.</p></div></div>
    <div class="tabs" id="rec-tabs"><button data-v="rec" class="on">Recommend (${f.plan.length})</button><button data-v="refer">Refer (${refer.length + f.questions.length})</button><button data-v="ns">Not suitable (${notSuit.length})</button></div>
    <div data-pane="rec">${recs || `<div class="empty" style="margin-top:10px">No feasible measures.</div>`}</div>
    <div data-pane="refer" hidden>${refer.map((e) => `<div class="rec"><div class="r1">${esc(e.name)}<span class="disp refer_for_survey">survey</span></div><div class="r2">${esc(e.reason)}</div></div>`).join("")}
      ${f.questions.map((q) => `<div class="rec"><div class="r1">${esc(q.question)}<span class="badge">${esc(q.importance)}</span></div><div class="r2">${esc(q.why)}</div></div>`).join("") || (refer.length ? "" : `<div class="empty" style="margin-top:10px">Nothing to refer.</div>`)}</div>
    <div data-pane="ns" hidden>${notSuit.map((e) => `<div class="rec"><div class="r1">${esc(e.name)}<span class="badge">${esc(nice(e.status))}</span></div><div class="r2">${esc(e.reason)}</div></div>`).join("") || `<div class="empty" style="margin-top:10px">Everything is feasible.</div>`}</div>`;
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

// =====================================================================================
// 4 · Decision Lab — the showpiece. Everything reads the Lab result (engine run per
// feasible package) plus one engine re-run for the selected package.
// =====================================================================================
const SHORT = { loft_insulation: "Loft", cavity_wall_insulation: "Cavity wall", solid_wall_insulation: "Solid wall",
  glazing_upgrade: "Glazing", smart_controls: "Controls", air_source_heat_pump: "Heat pump", solar_pv: "Solar PV" };
const short = (m) => SHORT[m] || nice(m);
const LS = { budget: +store.get("budget", 10000) };

async function lab(main, id, live) {
  if (!id) {
    const p = await api("/api/portfolio");
    if (!live()) return;
    id = p.ranking.top[0]?.property_id;
    if (id) { location.replace("#/lab/" + id); return; }
    main.innerHTML = `<div class="empty">No homes.</div>`;
    return;
  }
  const [rep, L] = await Promise.all([loadFacts(id), api(`/api/properties/${encodeURIComponent(id)}/lab?budget=${LS.budget}&objective=${S.objective}`)]);
  if (!live()) return;
  const f = rep.facts, ps = f.property_summary;
  const byKey = Object.fromEntries(L.packages.map((o) => [o.key, o]));
  const order = f.plan.map((r) => r.measure_id);
  const keyOf = (set) => order.filter((m) => set.has(m)).join("+");
  const best = L.plans.find((p) => p.id === "best_value" && p.package_key) || L.plans.find((p) => p.package_key);
  const st = { sel: new Set(best ? byKey[best.package_key].measures : []), plan: best?.id || null, view: "plans", out: "net_kwh", res: null };

  main.innerHTML = `
    ${topbar(`Decision Lab <span class="muted" style="font-weight:500">· ${esc(f.property_id)}</span>`,
      `${esc(cap(ps.property_type))}, ${esc(cap(ps.region))} · score ${f.score.score ?? "range"} (${esc(f.score.band || "undetermined")}) · ${L.packages.length} feasible packages, each run through the engine`,
      `<div class="filters"><input id="goto" placeholder="Go to home, e.g. P00007" style="min-width:170px">
        <label class="small muted">Budget £ <input id="budget" type="number" min="500" step="500" value="${LS.budget}" style="width:110px;min-width:0"></label>
        <a class="btn" href="#/property/${esc(f.property_id)}">Property view</a></div>`)}
    ${L.notes.length ? `<div class="banner">${L.notes.map(esc).join(" ")}</div>` : ""}
    <div class="card" style="margin-bottom:18px">${nbaStrip(f.next_best_action)}</div>
    <div class="card" style="margin-bottom:18px">
      <div class="card-head"><div><h3>Choose your plan</h3><p class="hint">There is no single best option — four honest answers to four different priorities, all from the same feasible set.</p></div>
        <div class="tabs" id="plan-view"><button data-v="plans" class="on">Plans</button><button data-v="frontier">Cost vs carbon</button></div></div>
      <div id="plans"></div>
    </div>
    <div class="two" style="margin-bottom:18px">
      <div class="card"><h3>What depends on what</h3><p class="hint">Click a measure to add or remove it. Arrows: do the first before the second.</p><div id="dep"></div></div>
      <div class="card"><div class="card-head"><div><h3>Where the energy goes</h3><p class="hint">Purchased energy by end use, today vs. the selected package (same scale).</p></div>${tag("estimated", "engine end-use model anchored on the metered baseline")}</div><div id="sankey"></div></div>
    </div>
    <div class="card" id="sel-card" style="margin-bottom:18px"></div>
    <div class="card">
      <div class="card-head"><div><h3>Detail</h3><p class="hint">Why savings don't add up, and which assumptions could change the decision.</p></div>
        <div class="tabs" id="detail-tabs"><button data-v="int" class="on">Interactions</button><button data-v="sens">Sensitivity</button></div></div>
      <div id="detail"></div>
    </div>`;

  $("#goto").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.value.trim()) location.hash = "#/lab/" + e.target.value.trim().toUpperCase(); });
  $("#budget").addEventListener("change", (e) => { LS.budget = Math.max(500, +e.target.value || 10000); store.set("budget", LS.budget); route(); });

  const drawPlans = () => { $("#plans").innerHTML = st.view === "plans" ? planCards(L, byKey, st) : frontier(L, byKey, keyOf(st.sel)); };
  const drawDep = () => { $("#dep").innerHTML = depGraph(f, st.sel); };
  let seq = 0;
  const select = async (set, planId = null) => {
    st.sel = set; st.plan = planId;
    drawPlans(); drawDep();
    const mine = ++seq;
    if (!set.size) { st.res = null; $("#sankey").innerHTML = sankeyPair(f, null); $("#sel-card").innerHTML = `<div class="empty">Pick a plan or a measure to see its effect.</div>`; return; }
    $("#sel-card").innerHTML = `<div class="loading">Re-running the engine…</div>`;
    const r = await api(`/api/properties/${f.property_id}/scenarios`, { measures: [...set], objective: S.objective, name: planId ? L.plans.find((p) => p.id === planId).title : "Custom package" });
    if (mine !== seq || !live()) return;
    st.res = r;
    $("#sankey").innerHTML = sankeyPair(f, r.facts);
    $("#sel-card").innerHTML = selectedSummary(f, r, byKey[keyOf(set)]);
  };
  const drawDetail = (v) => { $("#detail").innerHTML = v === "sens" ? sensitivityView(L) : heatmap(L, st.out); };

  tabs("#plan-view", (v) => { st.view = v; drawPlans(); });
  tabs("#detail-tabs", (v) => drawDetail(v));
  $("#plans").addEventListener("click", (e) => {
    const c = e.target.closest("[data-plan]");
    if (c && c.dataset.key) return select(new Set(byKey[c.dataset.key].measures), c.dataset.plan);
    const pt = e.target.closest("[data-pkg]");
    if (pt) select(new Set(byKey[pt.dataset.pkg].measures), null);
  });
  $("#dep").addEventListener("click", (e) => {
    const n = e.target.closest("[data-node]");
    if (!n) return;
    const s = new Set(st.sel);
    s.has(n.dataset.node) ? s.delete(n.dataset.node) : s.add(n.dataset.node);
    select(s, null);
  });
  $("#detail").addEventListener("click", (e) => {
    const b = e.target.closest("[data-out]");
    if (b) { st.out = b.dataset.out; drawDetail("int"); }
  });
  drawDetail("int");
  select(st.sel, st.plan);
}

function nbaStrip(n) {
  if (!n) return "";
  return `<div style="display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap">
    <div style="min-width:220px"><div class="small muted">Next best action ${disp(n.disposition)}</div><div class="nba-head">${esc(n.headline)}</div>
      <div class="small muted">confidence ${esc(n.confidence)}</div></div>
    <div style="flex:1;min-width:280px;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:4px 16px">
      ${n.reasons.map((r, i) => `<div class="reason" style="margin:4px 0"><span class="n">${i + 1}</span><div class="small">${esc(r.text)}${S.mode === "evidence" ? `<span class="ref">← ${esc(r.fact_ref)}</span>` : ""}</div></div>`).join("")}</div></div>`;
}

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

function depGraph(f, sel) {
  if (!f.plan.length) return `<div class="empty">No feasible measures.</div>`;
  // fabric (1) and controls (2) have no prerequisites, so they share the "do first" column
  const colOf = (r) => (r.stage <= 2 ? 1 : r.stage);
  const stages = [...new Set(f.plan.map(colOf))].sort();
  const cols = Object.fromEntries(stages.map((s) => [s, f.plan.filter((r) => colOf(r) === s)]));
  const W = 520, nodeW = 104, nodeH = 40, colGap = (W - nodeW * stages.length) / Math.max(stages.length - 1, 1);
  const rows = Math.max(...Object.values(cols).map((c) => c.length));
  const H = Math.max(rows * (nodeH + 18) + 34, 140);
  const pos = {};
  stages.forEach((s, i) => cols[s].forEach((r, j) => {
    const n = cols[s].length;
    pos[r.measure_id] = { x: i * (nodeW + colGap), y: 28 + (H - 28 - n * (nodeH + 18)) / 2 + j * (nodeH + 18) };
  }));
  const edges = f.plan.flatMap((r) => r.depends_on.filter((d) => pos[d]).map((d) => {
    const a = pos[d], b = pos[r.measure_id];
    const bad = sel.has(r.measure_id) && !sel.has(d);
    const x1 = a.x + nodeW, y1 = a.y + nodeH / 2, x2 = b.x - 4, y2 = b.y + nodeH / 2, mx = (x1 + x2) / 2;
    return `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" marker-end="url(#arr${bad ? "b" : ""})"
      style="fill:none;stroke:${bad ? "var(--bad)" : "var(--line-2)"};stroke-width:${bad ? 2 : 1.5};${bad ? "stroke-dasharray:5 4" : ""}"
      data-tip="${esc(bad ? `${short(r.measure_id)} without ${short(d)}: it would be sized for the leakier home and save less per £.` : `Do ${short(d)} before ${short(r.measure_id)}.`)}"/>`;
  })).join("");
  const nodes = f.plan.map((r) => {
    const p = pos[r.measure_id], on = sel.has(r.measure_id);
    const missing = on && r.depends_on.some((d) => pos[d] && !sel.has(d));
    return `<g data-node="${r.measure_id}" style="cursor:pointer" data-tip="<b>${esc(r.name)}</b><br>${esc(r.suitability)} suitability · ${gbp(r.cost_low)}–${gbp(r.cost_high)}${r.depends_on.length ? "<br>after: " + esc(r.depends_on.map(short).join(", ")) : ""}">
      <rect x="${p.x}" y="${p.y}" width="${nodeW}" height="${nodeH}" rx="10" style="fill:${on ? "var(--accent)" : "var(--card)"};stroke:${missing ? "var(--bad)" : on ? "var(--accent)" : "var(--line-2)"};stroke-width:${missing ? 2 : 1}"/>
      <text x="${p.x + nodeW / 2}" y="${p.y + nodeH / 2 + 4}" text-anchor="middle" style="fill:${on ? "var(--accent-ink)" : "var(--ink)"};font-weight:600;font-size:12px">${esc(short(r.measure_id))}${missing ? " !" : ""}</text></g>`;
  }).join("");
  const heads = stages.map((s, i) => `<text x="${i * (nodeW + colGap) + nodeW / 2}" y="12" text-anchor="middle" style="fill:var(--ink-3)">${s === 1 ? "Do first" : esc(f.plan.find((r) => colOf(r) === s).stage_label.split(":")[0])}</text>`).join("");
  const excl = f.excluded.filter((e) => ["infeasible", "needs_survey", "declined"].includes(e.status));
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Measure dependencies">
    <defs><marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" style="fill:var(--line-2)"/></marker>
    <marker id="arrb" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" style="fill:var(--bad)"/></marker></defs>
    ${heads}${edges}${nodes}</svg>
    ${excl.length ? `<div class="small muted">Not available here: ${excl.map((e) => `${esc(short(e.measure_id))} (${esc(e.reason)})`).join(" · ")}</div>` : ""}`;
}

function sankey(flows, scaleKwh, title) {
  const W = 300, H = 250, nodeW = 10, gap = 8;
  const srcOrder = ["Grid electricity", "Solar (self-used)", "Gas"];
  const tgtOrder = ["Space heating", "Hot water", "Appliances & lighting", "Cooking (gas)"];
  const col = { "Grid electricity": "var(--elec)", "Solar (self-used)": "var(--solar)", Gas: "var(--gas)" };
  const total = flows.reduce((s, x) => s + x.kwh, 0);
  if (!total) return `<div><div class="small" style="font-weight:600">${title}</div><div class="empty">No purchased energy.</div></div>`;
  const k = (H - 50 - gap * 3) / scaleKwh;
  const sum = (key, name) => flows.filter((x) => x[key] === name).reduce((s, x) => s + x.kwh, 0);
  const place = (names, key) => { let y = 14; const out = {}; names.forEach((n) => { const v = sum(key, n); if (v > 0) { out[n] = { y, h: v * k, v, off: 0 }; y += v * k + gap; } }); return out; };
  const S_ = place(srcOrder, "source"), T_ = place(tgtOrder, "target");
  const x0 = 96, x1 = W - 96 - nodeW;
  const links = [...flows].sort((a, b) => srcOrder.indexOf(a.source) - srcOrder.indexOf(b.source) || tgtOrder.indexOf(a.target) - tgtOrder.indexOf(b.target)).map((fl) => {
    const s = S_[fl.source], t = T_[fl.target], h = fl.kwh * k;
    const ys = s.y + s.off, yt = t.y + t.off; s.off += h; t.off += h;
    const xa = x0 + nodeW, xb = x1, xm = (xa + xb) / 2;
    return `<path d="M${xa},${ys} C${xm},${ys} ${xm},${yt} ${xb},${yt} L${xb},${yt + h} C${xm},${yt + h} ${xm},${ys + h} ${xa},${ys + h} Z"
      style="fill:${col[fl.source]};opacity:.42" data-tip="${esc(fl.source)} → ${esc(fl.target)}<br><b>${fmt(fl.kwh)} kWh/yr</b>"/>`;
  }).join("");
  let bottom = H;
  const nodes = (o, x, anchor, tx) => {
    let last = -Infinity;
    return Object.entries(o).map(([n, v]) => {
      const ly = Math.max(v.y + v.h / 2 - 2, last + 27); // labels need ~27px; push down instead of overlapping
      last = ly;
      bottom = Math.max(bottom, ly + 20);
      const lead = Math.abs(ly - (v.y + v.h / 2 - 2)) > 3 ? `<line x1="${anchor === "end" ? tx + 2 : tx - 2}" x2="${anchor === "end" ? x : x + nodeW}" y1="${ly}" y2="${v.y + v.h / 2}" style="stroke:var(--line-2)"/>` : "";
      return `<rect x="${x}" y="${v.y}" width="${nodeW}" height="${Math.max(v.h, 1.5)}" rx="2" style="fill:${col[n] || "var(--ink-3)"}"/>${lead}
        <text x="${tx}" y="${ly}" text-anchor="${anchor}"><tspan>${esc(n.replace(" (self-used)", "").replace(" & lighting", ""))}</tspan><tspan class="val" x="${tx}" dy="12">${fmt(v.v)}</tspan></text>`;
    }).join("");
  };
  return `<div><div class="small" style="font-weight:600;margin-bottom:4px">${title} <span class="muted num" style="font-weight:400">· ${fmt(total)} kWh</span></div>
    ${(() => { const body = links + nodes(S_, x0, "end", x0 - 6) + nodes(T_, x1, "start", x1 + nodeW + 6);
      return `<svg viewBox="0 0 ${W} ${bottom}" width="100%" role="img" aria-label="${esc(title)} energy flows">${body}</svg>`; })()}</div>`;
}

function sankeyPair(f, after) {
  const base = f.baseline_flows, aft = after?.package?.flows_after || null;
  if (!base.length) return `<div class="empty">No end-use breakdown: the heating system or baseline is unknown.</div>`;
  const tot = (fl) => fl.reduce((s, x) => s + x.kwh, 0);
  const scale = Math.max(tot(base), aft ? tot(aft) : 0);
  return `<div class="two" style="gap:10px">${sankey(base, scale, "Today")}${aft ? sankey(aft, scale, "After the selected package") : `<div class="empty">Select a package.</div>`}</div>
    <div class="legend"><span><span class="band-sw" style="background:var(--elec)"></span>Grid electricity</span><span><span class="band-sw" style="background:var(--gas)"></span>Gas</span><span><span class="band-sw" style="background:var(--solar)"></span>Solar used at home</span></div>`;
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

function heatmap(L, out) {
  const ms = [...new Set(L.interactions.flatMap((i) => [i.a, i.b]))];
  const outs = [["net_kwh", "Energy (kWh/yr)"], ["carbon_kg", "Carbon (kg/yr)"], ["score_points", "Score (points)"]];
  const sel = `<div class="tabs">${outs.map(([v, l]) => `<button data-out="${v}" class="${v === out ? "on" : ""}">${l}</button>`).join("")}</div>`;
  if (ms.length < 2) return sel + `<div class="empty" style="margin-top:12px">Needs at least two feasible measures.</div>`;
  const val = (a, b) => L.interactions.find((i) => (i.a === a && i.b === b) || (i.a === b && i.b === a))?.[out];
  const vals = L.interactions.map((i) => Math.abs(i[out] ?? 0));
  const mx = Math.max(...vals, 1e-9);
  // upper triangle only: rows are all but the last measure, columns all but the first
  const rowsM = ms.slice(0, -1), colsM = ms.slice(1);
  const cell = 64, lab = 92, W = lab + cell * colsM.length, H = 26 + cell * rowsM.length;
  const cells = rowsM.flatMap((a, i) => colsM.map((b, jj) => {
    const j = jj;
    if (jj + 1 <= i) return "";
    const v = val(a, b);
    if (v == null) return "";
    const t = Math.min(Math.abs(v) / mx, 1);
    const colr = v < 0 ? "var(--bad)" : v > 0 ? "var(--elec)" : "var(--line)";
    const unit = out === "net_kwh" ? "kWh/yr" : out === "carbon_kg" ? "kg CO₂e/yr" : "points";
    const meaning = v < 0 ? "together they save LESS than the sum (overlap: the same heat can't be saved twice)" : v > 0 ? "together they save MORE than the sum" : "effects add up";
    return `<g data-tip="<b>${esc(short(a))} + ${esc(short(b))}</b><br>${v > 0 ? "+" : ""}${fmt(v, out === "score_points" ? 0 : 0)} ${unit}<br>${meaning}">
      <rect x="${lab + j * cell + 1}" y="${26 + i * cell + 1}" width="${cell - 2}" height="${cell - 2}" rx="6" style="fill:color-mix(in srgb, ${colr} ${Math.round(12 + 70 * t)}%, var(--card))"/>
      <text x="${lab + j * cell + cell / 2}" y="${26 + i * cell + cell / 2 + 4}" text-anchor="middle" class="val num">${v > 0 ? "+" : ""}${fmt(v)}</text></g>`;
  })).join("");
  const heads = colsM.map((m, j) => `<text x="${lab + j * cell + cell / 2}" y="16" text-anchor="middle">${esc(short(m))}</text>`).join("")
    + rowsM.map((m, i) => `<text x="${lab - 8}" y="${26 + i * cell + cell / 2 + 4}" text-anchor="end">${esc(short(m))}</text>`).join("");
  return `${sel}<div style="display:grid;grid-template-columns:minmax(0,${W}px) minmax(220px,1fr);gap:18px;margin-top:12px;align-items:start">
    <svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Pairwise interactions">${heads}${cells}</svg>
    <div class="small"><p><b>Savings don't add up.</b> Each cell is <i>joint saving − standalone A − standalone B</i>, from paired engine runs on the same baseline.</p>
      <p><span class="badge"><span class="band-sw" style="background:var(--bad)"></span>negative</span> overlap: e.g. insulating first leaves less heat for a heat pump to save.</p>
      <p><span class="badge"><span class="band-sw" style="background:var(--elec)"></span>positive</span> synergy: e.g. a heat pump gives solar panels more daytime electricity to offset.</p>
      <p class="muted">Labelled per output: score ≠ energy ≠ carbon. Score cells move in whole points (rounding).</p></div></div>`;
}

function sensitivityView(L) {
  const rows = L.sensitivity;
  if (!rows.length) return `<div class="empty">All key inputs are observed — nothing to vary.</div>`;
  const all = rows.flatMap((r) => [r.carbon_low, r.carbon_high]).concat(L.base_carbon_kg).filter((v) => v != null).map((v) => v / 1000);
  const lo = Math.min(...all), hi = Math.max(...all), pad = (hi - lo) * 0.1 || 0.1;
  const X = (v) => (100 * (v / 1000 - (lo - pad))) / (hi - lo + 2 * pad);
  return `<p class="hint">Each assumed or missing input is set to plausible alternatives and the engine re-runs the whole home. <b>Fragile</b> = the Next Best Action or the recommended package changes. This shows what to verify — it is not a statistical confidence interval.</p>
    ${rows.map((r) => `<div style="display:grid;grid-template-columns:minmax(160px,220px) minmax(0,1fr) minmax(200px,280px);gap:14px;align-items:center;padding:10px 0;border-top:1px solid var(--line)">
      <div><b class="small">${esc(r.label)}</b><div class="small muted">now: ${esc(r.current)} ${tag(r.basis)}</div></div>
      <div style="position:relative;height:22px" data-tip="${esc(r.variants.map((v) => `${v.label}: ${v.carbon_kg == null ? "—" : fmt(v.carbon_kg / 1000, 2) + " t/yr"}, next: ${v.nba_ref ? short(v.nba_ref) : v.nba_kind}`).join("<br>"))}">
        <div style="position:absolute;top:10px;left:0;right:0;height:2px;background:var(--line)"></div>
        ${r.carbon_low != null ? `<div style="position:absolute;top:4px;height:14px;border-radius:4px;left:${X(r.carbon_low)}%;width:${Math.max(X(r.carbon_high) - X(r.carbon_low), 0.6)}%;background:${r.fragile ? "var(--warn)" : "var(--accent)"};opacity:.75"></div>` : ""}
        ${L.base_carbon_kg != null ? `<div style="position:absolute;top:0;height:22px;width:2px;background:var(--ink);left:${X(L.base_carbon_kg)}%"></div>` : ""}</div>
      <div class="small">${r.fragile ? `<span class="disp refer_for_survey">fragile</span> ` : `<span class="disp recommend">robust</span> `}${esc(r.action)}
        ${r.nba_changes ? `<div class="muted">next action becomes: ${esc([...new Set(r.variants.map((v) => v.nba_ref ? short(v.nba_ref) : v.nba_kind))].join(" / "))}</div>` : ""}</div></div>`).join("")}
    <div class="legend"><span><span style="width:2px;height:12px;background:var(--ink);display:inline-block"></span>recommended package today (${L.base_carbon_kg == null ? "—" : fmt(L.base_carbon_kg / 1000, 2) + " t/yr"})</span><span>bar = range of its carbon saving across the alternatives</span></div>`;
}

// =====================================================================================
// 5 · Analytics & Evidence
// =====================================================================================
async function analytics(main, _a, live) {
  const e = await api("/api/evidence");
  if (!live()) return;
  const m = e.metrics;
  main.innerHTML = `${topbar("Analytics", "How the models and the ranking perform against simple baselines (held-out test split)", synthNote)}
    ${m ? `<div class="two">${energyTable(m)}${rankingTable(m)}</div>` : `<div class="empty">Run <code>uv run greeniq evaluate</code> to generate metrics.</div>`}
    <div class="banner" style="margin-top:18px">Benchmarking scatter and outlier residuals are deliberately deferred (priority P2 in the design) until the reference data is defensible.</div>`;
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

async function evidence(main, _a, live) {
  const e = await api("/api/evidence");
  if (!live()) return;
  const ef = e.emission_factors.factors, m = e.metrics;
  main.innerHTML = `${topbar("Evidence", "Data sources, methods, versions and model quality — the receipts behind every number", synthNote)}
    <div class="banner">All homes, meters and sales are <b>synthetic</b> (a simulated world with hidden truth the engines never see; see <code>data/DATA_CARD.md</code>).
      Agreement with it shows the method works; it is not evidence of real-world accuracy.</div>
    <div class="two">
      <div class="card"><h3>Emission factors</h3><p class="hint">ΔC = ΔE<sub>elec</sub> × EF<sub>elec</sub> + ΔE<sub>gas</sub> × EF<sub>gas</sub></p>
        <dl class="kv">${Object.entries(ef).map(([k, v]) => `<dt>${cap(k)}</dt><dd><b class="num">${v.value}</b> ${esc(v.unit)}<div class="small muted">${esc(v.source)}</div>${v.verification ? `<div class="small muted">${esc(v.verification)}</div>` : ""}</dd>`).join("")}</dl></div>
      <div class="card"><h3>Engine versions</h3><p class="hint">Cached results are keyed by these; change any and the cache rebuilds (key <code>${esc(e.engine_key)}</code>).</p>
        <dl class="kv">${Object.entries(e.versions).map(([k, v]) => `<dt>${esc(nice(k))}</dt><dd><code>${esc(v)}</code></dd>`).join("")}</dl></div>
      <div class="card"><h3>Retrofit costs</h3><p class="hint">Indicative ranges with sources; shown as ranges, never a quote.</p>
        <div class="table-wrap"><table class="t"><thead><tr><th>Measure</th><th>Cost</th><th>Source</th></tr></thead><tbody>
        ${Object.values(e.measures).map((x) => `<tr><td>${esc(x.name)}</td><td class="num">£${fmt(x.cost.low)}–£${fmt(x.cost.high)} ${esc(x.cost.basis)}</td><td class="small muted" style="white-space:normal">${esc(x.cost_source || "")}</td></tr>`).join("")}</tbody></table></div></div>
      <div class="card"><h3>Model quality (held-out test split)</h3><p class="hint">Generated by <code>uv run greeniq evaluate</code> → <code>reports/EVALUATION.md</code></p>
        ${m ? `<dl class="kv">
          <dt>Savings</dt><dd>calibrated engine MAE gas ${fmt(m.savings.methods.cal.gas.mae)} kWh vs rule-of-thumb ${fmt(m.savings.methods.naive.gas.mae)}; heat-pump electricity sign correct ${fmt(100 * m.savings.methods.cal.hp_electricity_sign_correct)}% vs ${fmt(100 * m.savings.methods.naive.hp_electricity_sign_correct)}%</dd>
          <dt>Score</dt><dd>band agreement ${fmt(100 * m.score.band_agreement, 1)}% with true inputs; partial-score ranges cover the truth ${fmt(100 * m.score.partial_range_coverage)}%</dd>
          <dt>Conflicts</dt><dd>${m.conflicts.detected}/${m.conflicts.heating_record_errors_planted} planted heating-record errors caught, ${m.conflicts.false_alarms} false alarms</dd>
          <dt>Feasibility</dt><dd>recall ${fmt(100 * m.feasibility.recall, 1)}%; violation rate ${fmt(100 * m.feasibility.violation_rate, 1)}% (most flagged for survey)</dd>
          <dt>Speed</dt><dd>${fmt(m.ms_per_home_with_models, 1)} ms per home with models</dd></dl>` : `<div class="empty">No metrics yet.</div>`}</div>
    </div>`;
}

// =====================================================================================
// Settings
// =====================================================================================
async function settings(main) {
  main.innerHTML = `${topbar("Settings", "Saved in this browser only")}
    <div class="card" style="max-width:560px"><h3>Objective for the Next Best Action</h3>
      <p class="hint">How the engine ranks feasible measures when picking one thing to do next.</p>
      <select class="inp" id="obj">${[["value_for_money", "Value for money (carbon per £, £1k floor)"], ["carbon", "Most carbon saved"], ["energy", "Most energy saved"]].map(([v, l]) => `<option value="${v}" ${S.objective === v ? "selected" : ""}>${l}</option>`).join("")}</select>
      <div class="sep"></div><h3>Theme</h3>
      <select class="inp" id="theme">${["system", "light", "dark"].map((v) => `<option ${S.theme === v ? "selected" : ""}>${v}</option>`).join("")}</select></div>`;
  $("#obj").onchange = (e) => { S.objective = e.target.value; store.set("objective", S.objective); };
  $("#theme").onchange = (e) => { S.theme = e.target.value; store.set("theme", S.theme); applyTheme(); };
}
