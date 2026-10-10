# START HERE — prompt for the build session

> **For the human:** open a fresh Claude Code session (Opus 5.5, highest effort) on a
> machine whose GitHub login can access this repo. Paste **everything in the box below**
> as the first message. If it pauses, reply: **"Continue. Follow the pack, keep the clean
> run green, don't skip tests."**

---

```text
You are the founding engineer of GreenIQ, our team's solution to Lloyds Problem
Statement 2 ("Green Home Score and Retrofit Recommendation Engine"). Your job in
this session: RESEARCH, DECIDE, and BUILD a clean, extensible
STARTER BUILD that satisfies every requirement of the problem statement at a credible,
transparent baseline, with clean plug-in points for the advanced features we'll add
afterwards.

== SOURCE OF TRUTH ==
Repo: https://github.com/SHARMA-AtharvaIIIT/Absolut  (clone it; build inside it)
Read these first, in this order. They are the plan and the law:
  docs/reference/LLOYDS-ps2.pdf      the problem statement (wins any conflict)
  docs/01_GUARDRAILS.md              binding rules
  docs/02_PROBLEM_DECODED.md         requirement IDs: FR / DR / ER / SR
  docs/03_ARCHITECTURE.md            the shape: layers, contract, seams, trust boundary
  docs/04_RUNTIME_FLOWS.md           required behaviours (analyse, explain, what-if, ...)
  docs/05_RESEARCH_PLAYBOOK.md       what to research and how to decide
  docs/06_BUILD_FRAMEWORK.md         phases, exit gates, definition of done
  docs/07_TRUST_AND_EVALUATION.md    hallucination defences + evaluation framework
  docs/08_EXTENSIBILITY_ROADMAP.md   seams the starter must expose
  docs/09_SUBMISSION_AND_DEMO.md     submission checklist + readiness checks
  docs/10_MECHANISMS_HANDBOOK.md     18 proven mechanisms + lessons, PRE-DISTILLED for you
  docs/adr/                          decision records (ADR-001 is already accepted)
The pack deliberately gives you the WHAT and the SHAPE, not the implementation. You own
the HOW: research it, decide it, record it, build it.

== PROVEN MECHANISMS (already done for you; don't re-derive) ==
docs/10_MECHANISMS_HANDBOOK.md distils the team's earlier projects into 18 mechanisms
(contract + state wrapper, pipeline spine, provider seams, receipts, grounding gate +
template fallback, query-first answers, decision layer, completeness checklist,
baselines-as-data, peer lane, leaderboard, golden + fake-provider tests, verification
sheet, ensemble protocol, one-command run, persistence, visible provenance, decision
log) with sketches, gotchas, and the tests that prove each one. Treat it as your
starting toolkit: re-implement those mechanisms for the home-energy domain and port
the listed tests. Do NOT go looking for or analysing the team's old repositories;
everything useful from them is already in the handbook. Spend research credits only on
NEW external knowledge.

== RESEARCH (focused, parallel, external only) ==
Answer RQ-1..RQ-11 from the research playbook. Look widely: GitHub and open source,
official methodologies and advice tools, open datasets, papers. Use parallel subagents
for independent questions if you have them. Score candidates with the scorecard. Verify
every figure, licence and claim at its source; if you can't verify it, don't ship it.
Record findings in docs/research/RESEARCH_NOTES.md + docs/research/SOURCES.md and each
significant choice as an ADR. Once an option is clearly verified and good enough, decide
and build. If research doesn't beat the transparent baseline, ship the baseline. Be
economical: answer each question just deeply enough to decide, then build.

== NON-NEGOTIABLES (from the guardrails) ==
- Code computes every number; the language model only explains computed facts and
  answers what-ifs AFTER the engines rerun. Enforce with a grounding gate +
  deterministic template fallback. Hallucinated numbers must never reach the user.
- The PS-fixed weights, bands and formulas are exact (see guardrails G4).
- Electricity and gas stay separate end to end; increases are negative savings.
- Value impact is an indicative RANGE, explicitly non-causal.
- "Insufficient information" is a valid, explained output; never fabricate or zero-fill.
- Property-level splits, no leakage, documented synthetic label rules.
- A clean clone runs with NO API keys and NO model downloads (baseline + template mode).
- Every number carries a receipt (inputs, method/version, source).

== HOW TO WORK (maximum efficiency) ==
1. Orient (P0): read the pack; write a requirement checklist from 02.
2. Research and decide (P1–P2): focused; ADRs; choose a stack that gives a fast,
   reproducible, one-command starter.
3. Build in the phase order of docs/06 with its exit gates: contract + data → walking
   skeleton end to end → baseline engines for every FR → trust layer (template,
   gate, LLM behind gate, what-if recompute + diff) → dashboard → evaluation + docs →
   harden (fresh-clone run).
4. Keep the product runnable at every step. Make small, described commits as you go and
   push them to the repo regularly (use the team's attribution conventions if any).
5. Don't ask me to choose things you can decide with research and the pack. Only stop
   for genuinely destructive or irreversible actions. No scheduling, timers, cron jobs or
   recurring tasks are needed. Just build.
6. Test what the judges will probe: monotonicity, exact PS formulas, baseline-zero →
   unavailable, heating change raising electricity, package != sum, infeasible retrofit
   refused, no split leakage, gate rejects an invented number, app runs with no key.
7. Keep docs/03 diagrams true. If the design changes, update the diagrams and add an ADR.

== DELIVERABLE: the starter build ==
Meets the "Definition of Done — the starter build" in docs/06 §3, including:
- Working dashboard + API covering FR-1..FR-8 (FR-9 memory at least seamed or minimal).
- Exposed seams: score mapping, energy, retrofit ranking, value, narrator, memory.
- One-command run, one-command eval; tests green; README written for a stranger.
- docs: research notes, sources, ADRs, data card, scoring methodology, LLM prompts +
  model details, evaluation report (metrics vs baselines + grounding metrics),
  Responsible-AI note, architecture diagram, held-out predictions + schema.

== WHEN YOU FINISH ==
Print: (a) what you built, in plain English for a non-technical teammate; (b) the exact
commands to run the app (no key, then with a key) and the evaluation; (c) the key
decisions and their ADRs; (d) honest limitations; (e) the recommended next 5 advanced
features from docs/08, in order, with which seam each plugs into.

Begin: print your requirement checklist and research plan, then execute.
```
