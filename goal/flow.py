"""Component → abstract → route → SPEF/GDS orchestration."""

from collections import defaultdict
import json
import math
from pathlib import Path
import runpy
from .cells import diffpair
from .lef import write_abstract
from .lef.verilog import connections, write_wrapper
from .openroad import FlowSpec, locate, run
from .openroad.gds import merge_gds
from .pdk import PDK
from .rc import effective, parse_spef
from .signoff import magic_drc


MODES = ("conv", "cap", "cap_split")


def floorplan(meta: dict, split: bool, margin: float, pdk) -> dict:
    """Port the independent routing experiment's declared 40um-margin policy.

    Drain IOs go north, tail south, gates east/west, bulk west. Shared nets
    use the mean access x coordinate; split nets use their own access x.
    """
    width = math.ceil((meta["width"] + 2 * margin) / 10) * 10
    height = math.ceil((meta["height"] + 2 * margin) / 10) * 10
    grouped = defaultdict(list)
    mapping = connections(meta["pins"], split)
    for pin, net in mapping.items():
        grouped[net].append(pin)
    destinations = {}
    for net, pins in grouped.items():
        alias = meta["pins"][pins[0]]
        boxes = [box for pin in pins for box in meta["rectangles"][pin]]
        x = margin + sum((b[0] + b[2]) / 2 for b in boxes) / len(boxes)
        if alias.startswith("drn"):
            y = height - 0.5
        elif alias == "tail":
            y = 0.5
        elif alias == "gate_p":
            x, y = 0.5, height * 0.65
        elif alias == "gate_n":
            x, y = width - 0.5, height * 0.65
        else:
            x, y = 0.5, height * 0.25
        destinations[net] = (x, y)
    layers = list(pdk.data["lef_layers"].values())
    return dict(
        die=(0, 0, width, height),
        core=(0, 0, width, height),
        placements={"pair": (margin, margin)},
        io_pins=destinations,
        io_layer=pdk.lef_layer("met2"),
        routing_layers=(layers[0], layers[-1]),
    )


def measure(spef: Path, aliases: dict, split: bool) -> dict:
    """Short device and external boundaries, counting shared trunks once."""
    parsed = parse_spef(spef)
    groups = defaultdict(set)
    for pin, net in connections(aliases, split).items():
        groups[aliases[pin]].add(net)
    measured = {}
    for alias, names in groups.items():
        missing = names - parsed.keys()
        if missing:
            raise ValueError(f"SPEF lacks expected nets: {sorted(missing)}")
        chosen = [parsed[name] for name in sorted(names)]
        measured[alias] = effective(chosen) | dict(
            capacitance_fF=sum(net.capacitance for net in chosen) * 1e15,
            net_count=len(chosen),
            terminal_count=sum(len(net.instances) for net in chosen),
        )
    return measured


def run_flow(config: str | Path | dict, out_dir: str | Path | None = None) -> dict:
    """Run the diffpair vehicle. Python config files are trusted local code."""
    if not isinstance(config, dict):
        config = runpy.run_path(str(config))["CONFIG"]
    pdk = PDK.load(config.get("pdk", "sky130A"))
    tools = locate(pdk)
    dest = Path(out_dir or config.get("output", "build/diffpair"))
    if dest.exists():
        raise FileExistsError(f"Output exists: {dest}; choose a fresh --out directory")
    dest.mkdir(parents=True)
    results = {}
    component = diffpair(pdk)
    for mode in MODES:
        out = dest / mode
        meta = write_abstract(
            component,
            pdk,
            out,
            mode="merged" if mode == "conv" else "per_finger",
            macro_name="goal_pair",
            tech_lef=tools.tech_lef,
        )
        write_wrapper(
            "goal_pair", meta["pins"], out / "top.v", cap_split=mode == "cap_split"
        )
        spec = FlowSpec(
            [out / "goal_pair.lef"],
            [out / "top.v"],
            **floorplan(meta, mode == "cap_split", config.get("margin_um", 40), pdk),
        )
        spec.timeout = config.get("timeout_s", 300)
        metrics = run(spec, tools, out / "route")
        metrics["nets"] = measure(
            out / "route/routed.spef", meta["pins"], mode == "cap_split"
        )
        metrics["gds"] = merge_gds(
            out / "route/routed.def",
            [out / "goal_pair.gds"],
            spec.macro_lefs,
            tools,
            spec.top,
            out / "route/final.gds",
        )
        metrics["magic_drc"] = magic_drc(
            pdk, out / "route/final.gds", spec.top, out / "magic"
        )
        results[mode] = metrics
        (out / "measurement.json").write_text(json.dumps(metrics, indent=2) + "\n")
    ratios = {
        alias: results["conv"]["nets"][alias]["resistance_ohm"]
        / results["cap_split"]["nets"][alias]["resistance_ohm"]
        for alias in ("drn_p", "drn_n", "tail")
    }
    result = dict(
        pdk=pdk.name,
        modes=results,
        conv_over_split_R=ratios,
        direction_check=all(ratio > 1 for ratio in ratios.values()),
        all_routes_drc_clean=all(r["drc_violations"] == 0 for r in results.values()),
    )
    (dest / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    (dest / "metrics.md").write_text(format_table(result))
    return result


def format_table(result: dict) -> str:
    """Measured values alongside the distinct Table 3 routing-only vehicle."""
    text = "| mode | wirelength um | vias | route DRC | drain_p R ohm | tail R ohm | Magic DRC |\n"
    text += "| --- | ---: | ---: | ---: | ---: | ---: | ---: |\n"
    for mode, row in result["modes"].items():
        text += (
            f"| {mode} | {row['wirelength_um']} | {row['via_count']} | {row['drc_violations']} | "
            f"{row['nets']['drn_p']['resistance_ohm']:.6g} | {row['nets']['tail']['resistance_ohm']:.6g} | "
            f"{row['magic_drc'].get('count', 'not tested')} |\n"
        )
    text += (
        "\nMeasured conv/split R ratios: "
        + ", ".join(f"{k}={v:.6g}" for k, v in result["conv_over_split_R"].items())
        + ".\n"
    )
    text += "\nTable 3 reference: wirelength 153/165/605 um; vias 6/6/25; drain_p R 36.1/27.4/9.1 ohm; tail R 29.1/23.8/4.7 ohm; conv/split ratios 3.97 and 6.19. These use a different macro and estimated routing RC; they are context, not targets.\n"
    return text
