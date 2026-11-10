"""Graph order → well tiling → internal routing → reusable macro abstract."""

import argparse
import json
import math
from pathlib import Path
from goal.lef import write_abstract
from goal.lef.defports import routed_component
from goal.lef.verilog import write_wrapper
from goal.openroad import FlowSpec, locate, run
from goal.openroad.gds import merge_gds
from goal.pdk import PDK
from goal.place import parse_spice, tile
from goal.signoff import magic_drc


def build(out: Path, pdk_name: str = "sky130A") -> dict:
    """Route internal n1/tail nets, then expose only the six subcircuit nets."""
    if out.exists():
        raise FileExistsError(f"Choose a fresh output directory: {out}")
    out.mkdir(parents=True)
    pdk = PDK.load(pdk_name)
    tools = locate(pdk)
    devices = parse_spice(Path(__file__).with_name("ota5.sp").read_text())
    placed, ordering = tile(devices, pdk)
    meta = write_abstract(
        placed, pdk, out / "placed", macro_name="ota5_devices", tech_lef=tools.tech_lef
    )
    ports = ["inp", "inn", "out", "vdd", "vss", "bias"]
    write_wrapper(
        meta["macro"],
        meta["pins"],
        out / "top.v",
        top="ota5_routed",
        external_nets=ports,
    )
    width = math.ceil((meta["width"] + 80) / 10) * 10
    height = math.ceil((meta["height"] + 80) / 10) * 10
    io = {
        "inp": (0.5, height * 0.7),
        "inn": (0.5, height * 0.5),
        "bias": (0.5, height * 0.3),
        "out": (width - 0.5, height * 0.5),
        "vdd": (width * 0.5, height - 0.5),
        "vss": (width * 0.5, 0.5),
    }
    layers = list(pdk.data["lef_layers"].values())
    spec = FlowSpec(
        [out / "placed/ota5_devices.lef"],
        [out / "top.v"],
        top="ota5_routed",
        die=(0, 0, width, height),
        core=(0, 0, width, height),
        placements={"pair": (40, 40)},
        io_pins=io,
        io_layer=pdk.lef_layer("met2"),
        routing_layers=(layers[0], layers[-1]),
    )
    result = run(spec, tools, out / "route")
    merge_gds(
        out / "route/routed.def",
        [out / "placed/ota5_devices.gds"],
        spec.macro_lefs,
        tools,
        spec.top,
        out / "route/final.gds",
    )
    component = routed_component(out / "route/routed.def", out / "route/final.gds", pdk)
    hardened = write_abstract(
        component,
        pdk,
        out / "hardened",
        mode="merged",
        macro_name="goal_ota5",
        tech_lef=tools.tech_lef,
    )
    result.update(
        ordering=ordering,
        external_nets=list(hardened["pins"]),
        magic_drc=magic_drc(
            pdk, out / "hardened/goal_ota5.gds", "goal_ota5", out / "magic"
        ),
        lvs="not tested: independent block LVS deck/reference not implemented",
    )
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build/ota5"))
    parser.add_argument("--pdk", default="sky130A")
    args = parser.parse_args()
    print(json.dumps(build(args.out, args.pdk), indent=2))
