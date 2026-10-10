# GreenIQ — Demo guide (judges and presenters)

GreenIQ answers the four questions in Lloyds PS2: **how green is this home, what should be improved, how much
energy and carbon could be saved, and could the home's value increase?** For one home, and for a whole portfolio.
Every number is computed by documented code; the AI only explains those numbers, and a checker blocks any
sentence that does not match them.

## 1. Setup (once)

```bash
git clone https://github.com/SHARMA-AtharvaIIIT/Absolut.git
cd Absolut && git checkout beautiful
uv sync --extra llm        # Python 3.11+; --extra llm adds the Claude SDK
```

## 2. Start it — pick the AI provider

| Mode | Command | What the AI card says |
|---|---|---|
| **Claude (demo default)** | `ANTHROPIC_API_KEY=sk-ant-... uv run python -m greeniq serve` | "Written by Claude (claude-opus-5-5)" |
| Ollama (local, free) | `ollama pull qwen2.5:7b` then `GREENIQ_LLM_PROVIDER=ollama uv run python -m greeniq serve` | "Written by Ollama (qwen2.5:7b)" |
| Any OpenAI-compatible server (e.g. llama.cpp) | `GREENIQ_LLM_PROVIDER=openai_compatible GREENIQ_LLM_BASE_URL=http://127.0.0.1:8081/v1 GREENIQ_LLM_MODEL=<name> uv run python -m greeniq serve` | "Written by Local model (<name>)" |
| No AI (always works) | `uv run python -m greeniq serve` | "Plain-language summary from a fixed template" |

Open **http://127.0.0.1:8000**. The first start analyses all 3,000 homes (~20–60 s); later starts take seconds.
Optional: `GREENIQ_LLM_MODEL=claude-sonnet-5-5` for a faster/cheaper Claude model. If the Claude call fails or
times out, the template appears automatically and the card says why — the demo never breaks.

## 3. Demo homes (verified against the running data)

| Home | Why it is a good example | Where to look |
|---|---|---|
| **P02129** | Very poor detached house: the top-ranked poor home, a six-upgrade plan incl. heat pump and solar | Priority "Act now", tab *Energy & carbon* (electricity rises, gas falls) |
| **P00007** | Poor terraced house built before 1919: loft insulation first, value range shown | *Green Home Score*, *Improvements*, *Property value* |
| **P00004** | A home we cannot score exactly: heating system unknown | Score shown as a **range** 48–63, priority "Check first", the AI does not guess |

All homes are **simulated** (the brief allows synthetic data); peer comparisons and real-world savings corrections
come from **50,000 real homes in DESNZ NEED** (Open Government Licence).

## 4. The 4-minute script

1. **Start page** (0:00) — "GreenIQ answers the brief's four questions. Every figure links to how it was worked out."
   Click the first example (the top poor home).
2. **The decision strip** (0:20) — read left to right, like an insurer's case file:
   *Green Home Score* (number, band, "Poor efficiency" flag, standing among similar homes) → *Priority* (Act now /
   Check first / Worth doing / No action) → *Next best action* with cost, CO₂e and confidence → *Before you act*
   (missing or conflicting facts). Below it, the whole plan's outcome: score before → after, energy, CO₂e, cost, value.
3. **Tab: Green Home Score** (0:50) — the AI card explains the score (point at "✓ every figure checked against the
   engine"). Show the band scale, the 7 weighted parts with the sum written out, key issues, and the two comparisons
   (portfolio standing; real UK homes from NEED).
4. **Tab: Improvements** (1:30) — the Next Best Action, its cost, per-fuel change in words, three reasons, and
   *Also considered* with the actual comparison ("67 vs 106 kg CO₂e per £1k"). Then the AI card explaining the
   recommendations, and the ordered feasible upgrades (suitability, reason, saving, cost, real-home evidence line),
   "Check first" and "Not recommended" with reasons.
5. **Tab: Energy & carbon** (2:10) — electricity and gas before → after; improvement potential with the brief's
   formula filled in with this home's numbers; carbon fuel by fuel (gas kg less, electricity kg more, net);
   per-upgrade table, switch "Each on its own" to show savings don't add up.
6. **Tab: Property value** (2:40) — today's estimate, EPC band before → after, indicative range, potential value
   range, the caveat (association, not a promise).
7. **Tab: What if…** (3:00) — click "+ Air source heat pump" only: the engine re-runs; electricity goes **up**.
   Ask "What if I do everything but skip the solar panels?". Open *How the AI is kept honest*: an invented number,
   a flipped direction and a value promise are **blocked**.
8. **Many homes** (3:30) — *Overview*: the worklist tiers and portfolio outputs. *Priority list*: click "Act now",
   click a row for the quick view, tick two homes → *Compare selected*. *Compare*: group by Heating to show the
   heat-pump trade-off across the portfolio.
9. **How it works** (if asked) — every formula from the brief with our parameters, validation results vs simple
   baselines, and every judgement call we made.

## 5. What to say if asked

- *"Does the AI calculate anything?"* No. It receives the computed facts only; a checker verifies every number,
  unit, fuel direction, scenario and value wording; failing text is replaced by the template.
- *"Is this real data?"* Homes are simulated (with a hidden truth used only for grading). Real data (DESNZ NEED,
  50,000 homes) is used for peer comparisons and to correct savings to what real homes achieved.
- *"How is the next action chosen?"* A fixed, documented rule: blockers first (conflicts, unknown heating, no
  meter data), then feasible upgrades whose prerequisites are done, ranked by the chosen objective × suitability.

## 6. Do not claim

- That value changes are causal or market-proven (they come from simulated sales; method demonstration only).
- That heat-pump savings are validated on real UK homes (no such data in NEED; engineering estimate).
- That the AI meets the brief's 90% targets unless the latest `reports/GROUNDING_VALIDATION.md` shows it.
- Mobile layout: the demo is designed for a desktop/laptop screen.
