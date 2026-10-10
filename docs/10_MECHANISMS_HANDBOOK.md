# 10 · Mechanisms Handbook (pre-distilled — do not re-derive)

> The team's two earlier hackathon projects (a contract-intelligence engine and a
> multi-model voice-analytics pipeline) were **already analysed for you.** Their
> **domains are irrelevant** to GreenIQ (Guardrail G2), but they contain **battle-tested
> mechanisms** and **lessons paid for in bugs.** Everything worth keeping is below,
> translated into GreenIQ terms. **Don't spend research time on those repos. Use this page.**
>
> Each entry gives: **Pattern** (what it is) → **For GreenIQ** (how it maps) →
> **Sketch** (interface-level, language-agnostic) → **Gotchas** (learned the hard way) →
> **Prove it** (the test that shows it works).

```mermaid
flowchart LR
    subgraph FOUND["Foundation"]
        M1["M1 Contract + state wrapper"]
        M2["M2 Pipeline spine"]
        M3["M3 Provider seams"]
        M4["M4 Receipts"]
    end
    subgraph TRUST["Trust"]
        M5["M5 Grounding gate"]
        M6["M6 Query-first answers"]
        M7["M7 Decision layer"]
        M8["M8 Completeness checklist"]
    end
    subgraph INSIGHT["Insight"]
        M9["M9 Baselines as data"]
        M10["M10 Peer comparison lane"]
    end
    subgraph EVID["Evidence"]
        M11["M11 Experiment leaderboard"]
        M12["M12 Golden + fake-provider tests"]
        M13["M13 Verification sheet"]
        M14["M14 Fusion / ensemble protocol"]
    end
    subgraph OPS["Ops & UX"]
        M15["M15 One-command run"]
        M16["M16 Persistence pattern"]
        M17["M17 Visible provenance"]
        M18["M18 Plain-English decision log"]
    end
    FOUND --> TRUST --> INSIGHT --> EVID --> OPS
```

---

## Foundation

### M1 · Contract + state wrapper
**Pattern.** One shared, typed schema is the team contract. On top of it, a **state
wrapper** takes the computed analysis, builds lookup indexes, and answers deterministic
questions. Nothing downstream reads raw inputs. Everything reads through the wrapper.
Schema changes are **additive and versioned** (new optional fields, never renames), so
old data and old consumers keep working.

**For GreenIQ.** `HomeState` (inputs + derived features + data-quality flags) →
engines → `ComputedFacts`. A `HomeProfile`-style wrapper exposes `component(name)`,
`retrofit(id)`, `fuel(f)`, `receipt_for(output)` and similar.

**Sketch.**
```
HomeProfile.from_facts(facts) -> builds indexes {component→sub-score, retrofit→plan item, fuel→energy}
HomeProfile.receipt_for(item) -> item.receipt  OR  its parent's receipt  OR  []   # fallback chain
```
**Gotchas.**
- Keep the **deterministic statement** and any **AI wording** in *separate fields*
  (e.g. `finding` vs `narrative`). The deterministic one is the audit record and is
  never overwritten by model output.
- Treat "unknown" as a value, not a missing key. Downstream code shouldn't have to guess.

**Prove it.** Contract round-trip test (serialise → deserialise → equal); a test that an
old-version payload still loads.

### M2 · Pipeline spine (orchestrator)
**Pattern.** One function runs the whole analysis in dependency order. It **records
which backend/provider actually ran**, collects human-readable **warnings**, wraps every
optional/AI step in try/except that **falls back** to the baseline (with a warning)
rather than crashing, and is also **runnable as a CLI** for quick checks. The
orchestrator is a thin layer: **pure mapping functions, no scoring of its own**, with
a `--dry-run` self-test that builds everything from a synthetic input.

**For GreenIQ.** `analyse_home(home, scenario=None) -> ComputedFacts` runs features →
score → retrofit plan → per-fuel energy → carbon → value → flags → facts. It records
`providers_used` and `warnings` (e.g. "3 months of gas data missing; annualised from 9").

**Sketch.**
```
analyse_home(home, scenario):
    warnings = []; providers = {}
    hs = features.build(home, warnings)
    for engine in [score, plan, energy, carbon, value, flags]:   # dependency order
        out, providers[engine.name] = engine.run(hs, scenario) with fallback→baseline (+warning)
    return assemble_facts(outputs, providers, warnings)
CLI: python -m <pkg>.pipeline <home_id> [--json out.json] [--no-llm]
```
**Gotchas.** Write files with an **explicit UTF-8 encoding** (units like "m²" and "≈"
crashed a default Windows codec before). Log one summary line per run (which providers,
counts).

**Prove it.** The `--dry-run` / CLI run on a fixture home prints a full summary with no
network or keys.

### M3 · Provider seams
**Pattern.** Each intelligent step is an **interface** (a protocol) with a `name`. An
**active registry** maps slot → provider. An env var picks the mode:
`off | auto | <specific>`. **`auto` means "use the advanced provider if it's
available, else the baseline"**, with availability checked by a fast probe (a
short-timeout reachability check). Every candidate exposes
`available() -> (ok, reason)`, so unavailable ones are **skipped with a reason**, not
crashed on. The first default wraps the existing behaviour unchanged (a strangler-fig
default), and the benchmark decides whether a replacement stays.

**For GreenIQ.** Slots: `score_mapping`, `energy`, `retrofit_ranking`, `value`,
`narrator`, `memory`.

**Sketch.**
```
interface EnergyProvider { name; available()->(bool,str); predict(hs, scenario)->PerFuelEnergy }
ACTIVE = { "energy": select(env.ENERGY_PROVIDER or "auto", candidates=[ml, baseline]) }
select(mode, candidates): mode=="auto" → first candidate with available()==ok; always ends with baseline
```
**Gotchas.** The probe must be **fast** (≈1–2 s timeout) or startup and requests hang.
Narration and other "polish" providers must **never** break the pipeline: return
`None` on any error.

**Prove it.** A test with the advanced provider forced unavailable shows the output
still complete, with `providers_used.energy == "baseline"`.

### M4 · Receipts (provenance on every output)
**Pattern.** Every finding carries **evidence**: the exact source it rests on,
narrower than the whole input where possible. The UI just renders the receipt. It does
no fragile matching of its own. Compound results also carry **components**: which
factors contributed and their fraction of the total, so a combined score is auditable,
not asserted.

**For GreenIQ.** `Receipt { output_ref, inputs_used, method, method_version, provider,
source/citation }`. The score's **components** are the seven `wₖ·sₖ` contributions.
A package saving's components are its per-retrofit marginal contributions *after*
interactions.

**Gotchas.** Make receipts **optional/additive** in the schema so early data isn't
invalidated. Prefer a fallback chain (item → parent → none) over crashing.

**Prove it.** A test that every numeric field in `ComputedFacts` has a receipt.

---

## Trust

### M5 · Grounding gate + template fallback ⭐ (the crown jewel)
> **Base-product upgrade:** GreenIQ implements this gate with **structured outputs and
> per-sentence `fact_ids` citations** (`11` §8.3). Numbers must match a fact *the
> sentence cites*, which is stricter than the allow-list matching described below. The
> gotchas below still apply.

**Pattern.** The engine derives facts. The model **only phrases** them, and its output is
**accepted only if it passes a gate**: (1) **every number** in the text appears in the
facts payload, (2) **every reference** (an entity the facts can name) points at
something in the payload, and (3) the length is within bounds. Otherwise it's
**rejected and the deterministic template stands.** The gate **never raises**; with no
provider, or every draft rejected, the template is simply the answer. The system prompt
states the strict rules too, but **the gate is the enforcement, not the prompt.**

**For GreenIQ.** The payload = the subset of `ComputedFacts` relevant to the question or
what-if diff. Entities = component names, retrofit names, fuel names, band names.

**Sketch.**
```
payload  = facts_for(question or diff)                       # small, relevant subset
allowed  = numeric_tokens(serialise(payload, ascii=False)) ∪ numeric_tokens(display_strings(payload))
grounded(text) = text and len(text) <= MAX
                 and all(n in allowed for n in numeric_tokens(text))
                 and all(e in payload_entities for e in entities(text))
                 and not forbidden_claim(text)                 # "guaranteed", causal value claims
explain(): draft = narrator.narrate(payload) (None on error)
           return draft if grounded(draft) else template(payload)
```
**Gotchas (real bugs from before).**
- **Escaped serialisation corrupts the allow-list.** Serialising the payload with
  ASCII-escaping turned "§" into a `§` escape whose hex digits ("00", "7") became
  "allowed numbers". **Serialise with non-ASCII preserved** (or tokenise the
  structured values directly). Same risk with "£", "²" and "≈".
- **Formatting mismatches cause false rejections:** "£357,000" vs `357000`, "1.2 t" vs
  `1200 kg`, "38/100", "25%". Fix it by **pre-rendering display strings in the payload**
  (exactly as the UI shows them) and matching against both raw and display forms. Don't
  "fuzzy-match" numbers. Tolerance is a loophole for invented values.
- **Structural numbers** (7 components, band edges like 30/49, the PS weights) should be
  in the payload, or legitimate sentences get rejected.
- Cap output length. An overlong draft is a smell.

**Prove it (port these tests, using fake providers so no LLM is needed):**
1. A grounded draft is accepted, and the deterministic statement stays untouched.
2. A draft that references a non-existent retrofit or component is rejected.
3. A draft with an **invented number** ("saves £2,500 a year") is rejected.
4. Empty and oversized drafts are rejected.
5. No provider configured → a clean no-op, template only.
6. *(new for GreenIQ)* A "guaranteed" or causal value claim is rejected.

### M6 · Query-first answering
**Pattern.** A single `answer(question, state)` routes each question to the **cheapest
correct answer**. Plain factual questions are answered **deterministically from state,
with zero AI** (so they can't be hallucinated). Only genuinely open questions go to a
model. Every answer records `method` (deterministic | model), its `evidence`, and its
`confidence`. Deterministic answers are certain.

**For GreenIQ.** The four customer questions all have **deterministic routes**: "how
green" → score + band + top contributions; "what to improve" → the plan; "how much
saved" → per-fuel + net + carbon; "is it worth more" → value range + caveat. What-if
phrasing is parsed into a **Scenario** (deterministically where possible) → recompute
→ diff. The model is used for **fluency** and for **open follow-ups**, always behind M5.

**Gotchas.** Route ordering matters: specific intents before generic ones. Always return
an honest "needs X" answer when no route fits and no model is available.

**Prove it.** Each of the four customer questions answers correctly **with the model
disabled.**

### M7 · Decision layer (computed on read)
**Pattern.** Score, confidence and buckets are **derived on read, never stored**, so
they can't go stale. **Confidence is additive from evidence** (e.g. base + has receipts
+ multiple corroborating signals + empirical baseline) and **capped** below certainty
and above zero (*"never claims certainty"*). Findings go into **action buckets**
(act-first / worth-considering / informational), ordered by impact × confidence.

**For GreenIQ.** Per-estimate confidence comes from **data coverage** (months
available, fields known), **provider** (evaluated model vs baseline) and **conflict
flags**. Retrofit plan buckets: *do first* (high suitability × high confidence) /
*consider* / *later or not applicable*.

**Gotchas (two lessons that cost a demo).**
- **"Silence is not safety."** An empty result can mean "genuinely fine" *or* "outside
  what we can assess". When issues are absent **because data is missing**, don't output
  something that reads as "efficient". Output **"not fully assessed"** and say what's
  missing.
- **Labels must never contradict numbers.** A band, verdict or headline must agree with
  the score and the flags. Add explicit consistency rules (e.g. a home scored 31 can't
  be headlined "in good shape").

**Prove it.** A test where key inputs are missing gives a "not fully assessed" output,
not a clean bill of health. A consistency test checks band/headline vs score across
fixtures.

### M8 · Completeness checklist → questions to ask
**Pattern.** A declarative list of **expected inputs**, each with a label, why it
matters and an importance level. It reports **what's missing** (often more valuable than
what's present) and turns findings into **the questions a reviewer should ask**,
deduplicated and prioritised.

**For GreenIQ.** Expected inputs: rating, floor area, wall/loft/floor insulation,
glazing, heating type and age, solar, controls, and ≥N months of each fuel. Missing →
"We couldn't assess your insulation. Do you know if your loft is insulated?" Answers
feed **customer memory** (FR-9) and trigger a recompute. That's a natural, visible
memory loop.

**Prove it.** A fixture home missing two fields lists exactly those two, with questions
ranked by importance.

---

## Insight

### M9 · Baselines as data, with provenance and cold-start shrinkage
**Pattern.** "What normal looks like" is **data with provenance, not magic numbers in
code**, in three trust states: **seed** (documented priors, so nothing regresses on day
one) → **computed** (derived from a reference dataset, with `n`) → **adapted** (blended
toward live data **with shrinkage toward the prior**, so small samples can't
destabilise it; the seed is a floor). Below a **minimum count** the prior holds. The
displayed text surfaces the provenance ("computed over N homes"), so nothing reads as
an unbacked claim.

**For GreenIQ.** Peer-group **intensity benchmarks** (by property type, size band,
age, region) feeding the consumption-intensity sub-score (fair to large homes, FR-2),
and **value premiums** for the baseline value engine.

**Gotchas.** If a judge asks "where does this threshold come from?", the answer must
never be "we made it up". Store `source`, `n` and `computed` flags.

**Prove it.** A test that a peer group below the minimum count uses the prior, and a
safety test showing the data-driven version reproduces the seed version's outputs on
fixtures.

### M10 · Peer-comparison lane ("how unusual is this home?")
**Pattern.** A **separate question** from the main score: how does this item compare to
a **book of peers**? It reports base rates or percentiles, a rare/uncommon/common band,
and one distinctiveness number. With enough of the user's own data, it compares against
**their** book; below a minimum, it falls back to the reference book. Unmatched items
are shown honestly as **"not comparable"** rather than force-fitted, and novel ones as
**"new"** rather than dropped.

**For GreenIQ.** "Compare to similar homes": percentile of intensity and score within
the peer group; "homes like yours that did X". For a lender, a portfolio view of where a
home sits.

**Prove it.** Percentiles are monotonic in intensity, and the fallback triggers below
the minimum peer count.

---

## Evidence

### M11 · Experiment framework + leaderboard
**Pattern.** Each candidate run on a task stores a **Result record**: metrics, a
primary metric, latency, peak memory, units scored, **git commit, library versions,
dataset slice, hyperparameters** and a timestamp, as JSON on disk. A **leaderboard** is
just "best result per candidate". A **candidate registry** checks `available()` and
skips unavailable ones with a reason. A short curated **RESULTS.md** records what won
**and what was rejected, and why** (a fine-tuned model that lost to the simpler one was
rejected, and the leaderboard "did its job").

**For GreenIQ.** Tasks: `energy_elec`, `energy_gas`, `value`, `ranking`, `grounding`.
Candidates: baseline vs each advanced provider. **Promotion rule:** an advanced
provider becomes the default only if it beats the baseline on held-out data (M3).

**Gotchas.** **Never quote a number you haven't regenerated** from the current code
(weights that weren't committed once produced a claimed score nobody could reproduce).
Store the commit hash with every result.

**Prove it.** One command runs all candidates and prints the leaderboard.

### M12 · Golden tests + fake providers
**Pattern.** Freeze the outputs for a few **golden fixtures** (the demo inputs). Any
refactor must reproduce them exactly, or the golden file is updated **deliberately**
in the same commit with a reason. Test every AI-dependent path with **fake
providers** that return canned text, so tests need no network, no key and no model.

**For GreenIQ.** Golden homes: the PS-style poor home, an efficient home, a large
detached home (fairness), a flat (feasibility), a missing-data home, a conflicting-data
home, and a heat-pump-switch home (electricity rises).

### M13 · Verification sheet (turn "is it right?" into a count)
**Pattern.** A deterministic report lists **every claim** the system made with its
source, plus tick-boxes `[ ] correct [ ] partial [ ] wrong` and a "**missed items**"
section. A human (or an independent auditor agent that blind-reads the input first)
marks it up. Precision comes from the ticks, recall from the missed items. An
**independent blind tester** reading the raw input and then comparing against the
tool's output proved very effective at catching false clearances.

**For GreenIQ.** The **explanation audit sheet** for ER-4: each atomic claim in an
explanation is listed with the fact it should map to, and ticked → grounded %,
factual accuracy %, unsupported %. It's also handy for a quick human sanity pass on
golden homes.

### M14 · Fusion / ensemble protocol (no leakage)
**Pattern.** When combining models (e.g. two regressors per fuel, or a model with a
rules prior), **tune the combination on validation only and report on test only.**
Report per-class (here, **per-fuel**) results and state explicitly "**every slice
improved, no regression**", or say which slice didn't.

**Gotchas (real bug).** **Join keys must be unique across splits.** An ID that repeats
across val and test silently dropped about half the validation rows when joined on ID
alone. Join on `(id, split)`, and assert the row counts. Keep feature/label **ordering
identical** across components.

**For GreenIQ.** Any blend of the energy or value models; rules + ML blends; calibrating
interaction factors.

---

## Ops & UX

### M15 · One-command run & ops hygiene
**Pattern.** One script **builds the UI once and serves API + UI on a single port**
("open this URL"). A launcher that starts several processes must **kill stale
instances first** and give **each child its own process group**, so shutdown kills the
whole tree. **Eager-load models at startup** so the first request isn't degraded. A
`/health` endpoint, **env-driven CORS**, a documented `.env.example`. The container is
multi-stage (build UI → slim runtime), runs as non-root, has a healthcheck, and bakes
any model weights in so runtime needs no downloads.

**Gotchas (real bugs).**
- Restarting by killing only the parent left children alive → **duplicate workers →
  doubled, garbled results.** Fix: stale-kill + process groups.
- **Cold start**: lazily loaded models produced a degraded first result. Fix: eager load
  (or a warm-up call) at startup.
- **Hardcoded CORS** blocked the UI from a different port. Fix: env-driven origins.

### M16 · Persistence pattern
**Pattern.** **SQLite by default** (zero-config), with Postgres optional through the
same ORM. Fields people **filter on** are real columns; **display-only blobs** go in
JSON. **Volatile, derived values are recomputed on read**, never stored (they go
stale).

**For GreenIQ.** Store homes, energy usage, scenarios, computed facts (versioned), and
memory events. Recompute anything derived from engine versions on read, or version it.

### M17 · Visible provenance in the UI
**Pattern.** Show **which model or provider produced each output** (live status chips as
each stage completes; a per-model "what each model found" section). It makes the
architecture tangible to judges and makes debugging instant.

**For GreenIQ.** Each card shows a subtle provider tag (baseline / model vX / template /
grounded ✓). Clicking a number opens its receipt (M4).

### M18 · Plain-English decision log + honest current state
**Pattern.** Alongside technical ADRs, keep a **plain-English `DECISIONS.md`** that a
non-technical owner can read ("what we changed and why, without jargon"). Keep an
**honest "current state"** section in the README (e.g. "precise but under-recalls, which
is the safe failure mode"), and name known gaps in priority order.

**For GreenIQ.** Judges read the README first. Lead with what's measured and what's
limited.

---

## Lessons learned the hard way (quick list)

| # | Lesson | Mechanism |
|---|---|---|
| L1 | ASCII-escaped JSON put fake digits into the gate's allow-list | M5 |
| L2 | An empty result was shown as a clean bill of health (false clearance) | M7 |
| L3 | A label contradicted its own score ("sign-with-care" at 18/100) | M7 |
| L4 | A claimed model score came from weights that weren't committed, so it couldn't be reproduced | M11 |
| L5 | A "better-sounding" model was adopted without measurement and was worse | M11 |
| L6 | Joining on a non-unique ID across splits silently dropped half the data | M14 |
| L7 | Killing only the parent process left duplicate workers → doubled outputs | M15 |
| L8 | Lazy model loading degraded the first result after restart | M15 |
| L9 | Hardcoded CORS broke the UI on another port | M15 |
| L10 | The default file encoding crashed on unit symbols | M2 |
| L11 | Hardcoded thresholds couldn't answer "where does this number come from?" | M9 |
| L12 | Two independent signals mis-joined (time-alignment) mislabelled everything; join where both signals exist | M2 |

## What NOT to bring over

Contract clauses, legal risk patterns, the legal datasets, obligation and date
extraction, PDF/OCR geometry, speech recognition, speaker diarisation, emotion models,
retail analytics, their prompts and their schemas. **Only the mechanisms above cross
the boundary**, re-implemented for homes.

## Mechanism → GreenIQ → requirement

| Mechanism | GreenIQ component | Requirements |
|---|---|---|
| M1 Contract + state | `HomeState` / `ComputedFacts` / profile wrapper | all |
| M2 Pipeline spine | `analyse_home` orchestrator | FR-1…FR-6 |
| M3 Provider seams | energy · value · ranking · narrator · memory | ER-2, extensibility |
| M4 Receipts | per-number provenance, score contributions | FR-1, explainability |
| M5 Grounding gate | narrator + what-if | FR-7, ER-4 |
| M6 Query-first | assistant routes for the four customer questions | FR-7, ER-4 |
| M7 Decision layer | confidence, plan buckets, "not fully assessed" | FR-2, FR-3, ER-5 |
| M8 Completeness | missing-input detection → questions → memory | DR-5, ER-5, FR-9 |
| M9 Baselines as data | peer intensity benchmarks, value premiums | FR-1, FR-2, FR-6 |
| M10 Peer lane | compare-to-similar homes | insight, UX, innovation |
| M11 Leaderboard | baseline-vs-model evidence | ER-1, ER-2, ML 20% |
| M12 Golden + fakes | regression safety, LLM-free tests | ER-3 |
| M13 Verification sheet | grounding/factuality audit | ER-4, SR-E |
| M14 Fusion protocol | model blends without leakage | DR-3, ER-1 |
| M15 One-command run | judge-proof start | ER-3, SR-A/B |
| M16 Persistence | homes, scenarios, facts, memory | FR-8, FR-9 |
| M17 Visible provenance | provider tags, receipts in the UI | UX, explainability |
| M18 Decision log | DECISIONS.md + honest README | data quality, reproducibility |
