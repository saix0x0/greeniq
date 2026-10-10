"""GreenIQ command line: ``greeniq <command>``.

    generate   simulate the synthetic world, write data/, validate, split, annualise
    train      fit models on train, tune and promote on validation (test untouched)
    evaluate   score the held-out test split once and write reports/
    analyse    analyse one home and print the score, plan and package
    serve      run the API + dashboard on one port (http://127.0.0.1:8000)
"""

from __future__ import annotations

import argparse
import json
import sys
import time


def cmd_generate(args) -> int:
    from .data import DATA_DIR, build_processed, write_world
    from .simulator.world import generate_world

    t = time.time()
    world = generate_world(n_properties=args.n, seed=args.seed)
    write_world(world, DATA_DIR)
    report = build_processed(DATA_DIR)
    print(f"generated {report['properties']} homes, {report['customers']} customers, "
          f"{report['meter_rows']} meter rows, {report['sales']} sales in {time.time() - t:.1f}s")
    print(f"validation passed: {report['passed']} · schema errors: {len(report['schema_errors'])}")
    print("splits:", json.dumps(report["split_counts"]))
    print("annualisation:", json.dumps(report["annualisation_status"]))
    return 0 if report["passed"] else 1


def cmd_analyse(args) -> int:
    from .context import load_context
    from .data import load_dataset
    from .pipeline import analyse_home

    ds = load_dataset()
    if args.property_id not in ds.property_ids:
        print(f"unknown property {args.property_id}; try one of {ds.property_ids[:5]}")
        return 1
    facts = analyse_home(ds.property(args.property_id), load_context())
    if args.json:
        print(facts.model_dump_json(indent=2))
        return 0
    s = facts.score
    head = f"{s.score}/100 · {s.band}" if s.score is not None else f"range {s.score_range} · {s.band or 'band undetermined'}"
    print(f"{facts.property_id}  Green Home Score {head}  [{s.status}, confidence {facts.confidence.level}]")
    for c in s.components:
        sub = "—" if c.sub_score is None else f"{c.sub_score:5.1f}"
        print(f"  {c.label:32s} {sub}  × {c.weight:.2f}  [{c.basis}]  {c.input_display}")
    for fuel, b in facts.baseline.items():
        print(f"  baseline {fuel:11s} {b.annual_kwh if b.annual_kwh is not None else '—'} kWh/yr ({b.basis})")
    for c in facts.conflicts:
        print(f"  ! {c.message}")
    for r in facts.plan:
        print(f"  {r.order}. {r.name} [{r.suitability}] elec {r.in_package.electricity.saving_kwh:+.0f} · gas "
              f"{r.in_package.gas.saving_kwh:+.0f} kWh/yr · £{r.cost_low:,}-£{r.cost_high:,}")
    if facts.package:
        pk = facts.package
        ip = pk.improvement_potential
        print(f"  package: net {pk.impact.net_saving_kwh:+,.0f} kWh/yr, carbon {pk.impact.carbon.total_tonnes:+.2f} t/yr, "
              f"potential {ip.pct if ip.status == 'available' else 'unavailable'}%, score after {pk.score_after} "
              f"({pk.band_after}), EPC {pk.epc_band_before}→{pk.epc_band_after}")
    if facts.next_best_action:
        n = facts.next_best_action
        print(f"  NEXT BEST ACTION [{n.disposition}, confidence {n.confidence}]: {n.headline}")
        for r in n.reasons:
            print(f"    - {r.text}  ← {r.fact_ref}")
        if n.blocked_by:
            print(f"    blocked by: {n.blocked_by}")
    if facts.value and facts.value.status == "available":
        v = facts.value
        print(f"  value: £{v.current_value:,}; indicative uplift {v.uplift_pct_range[0]:+.1f}% to {v.uplift_pct_range[1]:+.1f}%")
    return 0


def cmd_train(args) -> int:
    from .ml.train import train_all

    train_all()
    return 0


def cmd_evaluate(args) -> int:
    from .evaluation.evaluate import evaluate_all

    evaluate_all()
    return 0


def cmd_eval_grounding(args) -> int:
    from .evaluation.grounding import evaluate_grounding

    o = evaluate_grounding(n_homes=args.n, llm_homes=args.llm)
    c = o["clean_templates"]
    print(f"clean templates: {c['blocked']}/{c['texts']} wrongly blocked; corruptions caught: " +
          ", ".join(f"{k} {v['caught']}/{v['tried']}" for k, v in o["corruptions"].items()))
    print(f"language model: {'run on ' + str(o['llm']['homes']) + ' homes' if o['llm']['run'] else o['llm']['status']}")
    print("→ reports/GROUNDING.md")
    return 0


def cmd_edge_sweep(args) -> int:
    from .evaluation.edge_sweep import sweep

    o = sweep(lab_every=args.lab_every)
    print(f"{o['homes']} homes in {o['seconds']}s; checks {sum(o['checks'].values())}, violations {sum(o['violations'].values())}")
    for k, v in o["violations"].items():
        print(f"  {k}: {v}")
    print("→ reports/EDGE_CASES.md")
    return 0 if not o["violations"] else 1


def cmd_serve(args) -> int:
    import uvicorn

    print(f"GreenIQ on http://{args.host}:{args.port}  (first start analyses every home and caches it in var/)")
    uvicorn.run("greeniq.api:app", host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="greeniq", description="GreenIQ: Green Home Score & Retrofit Engine")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="simulate the synthetic dataset into data/")
    g.add_argument("--n", type=int, default=3000, help="number of homes")
    g.add_argument("--seed", type=int, default=42)
    g.set_defaults(func=cmd_generate)

    t = sub.add_parser("train", help="train models (fit on train, tune on validation) into models/")
    t.set_defaults(func=cmd_train)

    e = sub.add_parser("evaluate", help="score the held-out test split once → reports/")
    e.set_defaults(func=cmd_evaluate)

    a = sub.add_parser("analyse", help="analyse one home from the dataset")
    a.add_argument("property_id")
    a.add_argument("--json", action="store_true", help="print the full ComputedFacts JSON")
    a.set_defaults(func=cmd_analyse)

    gr = sub.add_parser("eval-grounding", help="evaluate the grounding gate (and the LLM if a key is set) → reports/")
    gr.add_argument("--n", type=int, default=200, help="test homes")
    gr.add_argument("--llm", type=int, default=0, help="homes to explain with the language model (costs API credits)")
    gr.set_defaults(func=cmd_eval_grounding)

    es = sub.add_parser("edge-sweep", help="run every PS2 scenario invariant over all homes → reports/EDGE_CASES.md")
    es.add_argument("--lab-every", type=int, default=15, help="also run the Decision Lab on every Nth home")
    es.set_defaults(func=cmd_edge_sweep)

    sv = sub.add_parser("serve", help="run the API and dashboard on one port")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
