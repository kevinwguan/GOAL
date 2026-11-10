"""Command-line entry points for local LEF generation, routing and flows."""

import argparse
import json
import sys
from pathlib import Path

from .cells import diffpair, mosfet
from .flow import format_table, run_flow
from .lef import write_abstract
from .lef.verilog import write_wrapper
from .openroad import FlowSpec, locate, run
from .pdk import PDK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="goal", description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    lef = subs.add_parser("lef", help="emit a built-in cell's LEF/GDS/Verilog/aliases")
    lef.add_argument("--pdk", default="sky130A")
    lef.add_argument("--cell", choices=("diffpair", "nmos", "pmos"), default="diffpair")
    lef.add_argument("--mode", choices=("merged", "per_finger"), default="per_finger")
    lef.add_argument("--macro-name", default="goal_pair")
    lef.add_argument("--out", type=Path, required=True)
    lef.add_argument("--tech-lef", type=Path)
    lef.add_argument(
        "--cap-split",
        action="store_true",
        help="split wrapper nets; LEF mode is unchanged",
    )
    route = subs.add_parser(
        "route", help="route a JSON FlowSpec (paths relative to spec file)"
    )
    route.add_argument("spec", type=Path)
    route.add_argument("--pdk", default="sky130A")
    route.add_argument("--out", type=Path, required=True)
    flow = subs.add_parser("flow", help="run a trusted Python CONFIG file")
    flow.add_argument("config", type=Path)
    flow.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        pdk = PDK.load(getattr(args, "pdk", "sky130A"))
        if args.command == "lef":
            if args.out.exists():
                raise FileExistsError("Choose a new --out directory")
            cell = (
                diffpair(pdk)
                if args.cell == "diffpair"
                else mosfet(pdk, kind=args.cell)
            )
            meta = write_abstract(
                cell, pdk, args.out, args.mode, args.macro_name, args.tech_lef
            )
            write_wrapper(
                args.macro_name, meta["pins"], args.out / "top.v", args.cap_split
            )
            print(json.dumps(meta, indent=2))
        elif args.command == "route":
            data = json.loads(args.spec.read_text())
            for key in ("macro_lefs", "verilog"):
                data[key] = [
                    (args.spec.parent / filename).resolve()
                    for filename in data.get(key, [])
                ]
            if data.get("placed_def"):
                data["placed_def"] = (args.spec.parent / data["placed_def"]).resolve()
            print(json.dumps(run(FlowSpec(**data), locate(pdk), args.out), indent=2))
        else:
            print(format_table(run_flow(args.config, args.out)))
    except (OSError, ValueError, RuntimeError) as error:
        print(f"goal: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
