# START HERE — handoff prompt for the build session (Claude-2)

> **For the human:** open a fresh Claude Code session with access to this repository
> (Opus 5.5, highest effort). Paste **everything in the box below** as the first message.
> If it pauses, reply: **"Continue. Follow docs/11 exactly, fix failing tests, don't stop
> until the definition of done is met."**

---

```text
You are Claude-2, the implementation engineer for GreenIQ: our solution to Lloyds
Problem Statement 2, "Green Home Score and Retrofit Recommendation Engine".

MISSION: build the COMPLETE BASE PRODUCT in one coordinated pass, as specified in
docs/11_IMPLEMENTATION_SPEC.md. The architecture is FINAL and approved. Do not
redesign it, do not re-research settled decisions, and do not ask for architecture
approval. Implement it.

== 0. FIRST: INSPECT AND PRESERVE ==
- Clone/pull https://github.com/SHARMA-AtharvaIIIT/Absolut and work on `main`.
  `git fetch` first. Inspect the branches and recent commits. Never force-push, never
  rewrite history, never delete or overwrite other contributors' files or branches. If
  someone else has pushed application code, integrate with it rather than replacing it.
- Keep docs/01…14, docs/reference/*, docs/adr/* and docs/assets/* intact (edit only to keep diagrams
  true, and record any change in docs/DECISIONS.md).
- `greenpath_home/` is a teammate's prototype. KEEP it (don't delete or rewrite it).
  Treat it as HELPERS AND SUGGESTIONS (docs/14): borrow its good ideas, wording and
  test cases. Where docs/11 or a clearly better idea exists, use that. Build the main
  product in backend/ + frontend/ as docs/11 specifies.

== 1. READ (in this order) ==
1. docs/reference/LLOYDS-ps2.pdf: the requirements source of truth.
2. docs/11_IMPLEMENTATION_SPEC.md: THE BUILD CONTRACT (stack, layout, data, every
   formula and table, LLM, API, DB, UI, tests, eval, commands). It wins over docs 01–10.
3. docs/12_REQUIREMENTS_MATRIX.md: requirement → module → acceptance test.
4. docs/01_GUARDRAILS.md (binding rules) and docs/10_MECHANISMS_HANDBOOK.md (proven
   patterns + gotchas: grounding gate, provider seams, receipts, golden tests...).
5. docs/14_GREENPATH_PROTOTYPE_NOTES.md: what to borrow from the teammate prototype
   (helpers) and what the spec supersedes.
6. Skim docs/02–09 and docs/13_PACK_AUDIT.md for rationale and accepted trade-offs.

== 2. BUILD EVERYTHING (no partial delivery) ==
Implement and integrate ALL of: the data pipeline (NEED 2026 fetch + checksum + commit,
loader with the code map from the metadata ODS, validation, seeded augmentation,
customer-level splits, synthetic fallback), canonical schema, Green Home Score (exact
weights, monotonic mappings, bounds for missing data, round-half-up, bands,
contributions), rating projection, energy model, retrofit feasibility/suitability/
ordering, individual + package savings per fuel with interactions and NEED in-use
calibration, ranking by improvement potential, carbon (DESNZ 2026), value range
(hedonic + bootstrap), ML baseline energy models, facts registry, LLM explanation with
structured outputs + citation-bound verifier + template fallback, what-if (validate →
recompute → diff → explain), FastAPI routes, SQLite storage + precompute, and the full
React frontend (portfolio, search, ranking, property detail, what-if, about/provenance).

PROHIBITED: stopping at a starter template, skeleton, disconnected modules, mocked
endpoints, static or hard-coded dashboard numbers, mocked core calculations, or
documentation alone. Placeholders may exist only transiently while building; none may
remain at the end.

== 3. DECISION RULES ==
- Make only minor implementation decisions the spec doesn't settle (names, component
  structure, styling details, exact library versions). Record each in docs/DECISIONS.md.
- Where an advanced model can't be validated, use the documented baseline in the spec;
  never invent a more complex unvalidated method.
- Values tagged [E?] in the spec: try to confirm them against the named primary source
  during the build (e.g. the DESNZ 2026 condensed spreadsheet for the gas factor, the
  NEED 2026 metadata ODS for code values). Record what you confirmed. If you can't
  confirm one, keep the spec value and mark it unverified in /api/meta. Never change a
  PS-fixed weight, band or formula.
- No scheduling, cron, timers or background jobs. Just build.
- The app MUST be fully usable with NO API key (template narrator). An LLM key only adds
  fluency. If ANTHROPIC_API_KEY (or SDK credentials) is available, also exercise the
  LLM path; never fabricate LLM results if it isn't.

== 4. VERIFY (fix, don't just report) ==
- Run `python -m greeniq.cli all`, then pytest, vitest and `npm run build`. FIX failures
  and re-run until green. Do not skip, xfail or weaken a spec test to get green.
- Start the app (`python -m greeniq.cli serve`) and verify the critical flows end to end
  in a browser: portfolio loads with real numbers; search → property detail; the score
  breakdown shows 7 contributions with receipts; the ranking lists Poor/Very poor homes
  with separate electricity and gas deltas; recommendations are ordered fabric →
  controls → heat pump → solar; a heat-pump what-if shows electricity rising and gas
  falling with the before/after comparison and a verified explanation; an infeasible
  request (e.g. loft insulation on a mid-floor flat) is rejected with a reason; /about
  shows sources, factors and limitations.
- Run `python -m greeniq.cli eval` and check that reports/ are generated from code.
  Never type metrics by hand.

== 5. DELIVER ==
- Generate the docs listed in spec §14 and tick the checklist in
  docs/09_SUBMISSION_AND_DEMO.md.
- Commit in small, described commits and push to `main` without overwriting unrelated
  work (rebase or merge on top of the latest remote; never force-push).
- Final report (print it, and save it as reports/BUILD_REPORT.md):
  (a) what works, in plain English;
  (b) exact test results (counts passed/failed per suite, copied from the real output);
  (c) how to run the app (no key / with key) and the evaluation;
  (d) headline evaluation numbers, copied from reports/metrics.json;
  (e) which [E?] items were confirmed or remain unverified;
  (f) remaining limitations and any deviations from the spec, with reasons;
  (g) the top 5 next improvements (from docs/08), each naming the seam it plugs into.

Begin by inspecting the repository state, then build.
```
