"""GreenIQ command line: ``greeniq <command>``.

    generate   simulate the synthetic world, write data/, validate, split, annualise
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="greeniq", description="GreenIQ: Green Home Score & Retrofit Engine")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="simulate the synthetic dataset into data/")
    g.add_argument("--n", type=int, default=3000, help="number of homes")
    g.add_argument("--seed", type=int, default=42)
    g.set_defaults(func=cmd_generate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
