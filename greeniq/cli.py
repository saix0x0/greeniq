"""GreenIQ command line: ``greeniq <command>``.

    generate   simulate the synthetic world, write data/, validate, split, annualise
    analyse    analyse one home and print the score, plan and package
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
    if facts.value and facts.value.status == "available":
        v = facts.value
        print(f"  value: £{v.current_value:,}; indicative uplift {v.uplift_pct_range[0]:+.1f}% to {v.uplift_pct_range[1]:+.1f}%")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="greeniq", description="GreenIQ: Green Home Score & Retrofit Engine")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="simulate the synthetic dataset into data/")
    g.add_argument("--n", type=int, default=3000, help="number of homes")
    g.add_argument("--seed", type=int, default=42)
    g.set_defaults(func=cmd_generate)

    a = sub.add_parser("analyse", help="analyse one home from the dataset")
    a.add_argument("property_id")
    a.add_argument("--json", action="store_true", help="print the full ComputedFacts JSON")
    a.set_defaults(func=cmd_analyse)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
