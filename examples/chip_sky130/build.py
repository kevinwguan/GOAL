"""Compose §3.4 macro routing and the §3.5 manifest-defined pad harness."""

import argparse
import json
import runpy
from pathlib import Path

from goal.harness import build_ring, check_ring, sky130_example
from goal.lef.verilog import identifier
from goal.openroad import FlowSpec, locate, run
from goal.openroad.gds import merge_gds
from goal.pdk import PDK
from goal.signoff import magic_drc
from goal.signoff.connectivity import Connectivity, macro_terminals

# Explicit placement/spec policy, not an optimizer or a fitted paper result.
OTA_LOCATION = (400, 400)
SUPPLIES = {"vdd": "VDDA", "vss": "VSSA"}


def read_json(path):
    return json.loads(Path(path).read_text())


def build(out: Path, ring_dir: Path | None = None, ota_dir: Path | None = None) -> dict:
    """Build fresh inputs by default; optional paths reuse retained raw artifacts."""
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    pdk = PDK.load("sky130A")
    tools = locate(pdk)
    if ring_dir is None:
        ring_dir = out / "ring"
        manifest = build_ring(sky130_example(), pdk, ring_dir)
        check_ring(manifest, pdk, ring_dir)
    else:
        manifest = read_json(ring_dir / "manifest.json")
    if ota_dir is None:
        ota_dir = out / "ota"
        runpy.run_path(str(Path(__file__).parents[1] / "ota5/build.py"))["build"](
            ota_dir
        )
    ota = read_json(ota_dir / "hardened/goal_ota5.json")
    nets = sorted({p["net"] for p in manifest["core_ports"]})
    text = "module goal_chip();\n" + "".join(f"  wire {identifier(n)};\n" for n in nets)
    text += "  goal_pad_ring ring (" + ", ".join(f".{n}({n})" for n in nets) + ");\n"
    text += (
        "  goal_ota5 ota ("
        + ", ".join(f".{p}({SUPPLIES.get(n, n)})" for p, n in ota["pins"].items())
        + ");\nendmodule\n"
    )
    (out / "top.v").write_text(text)
    w, h = manifest["spec"]["die"]
    spec = FlowSpec(
        [ring_dir / "pad_ring.lef", ota_dir / "hardened/goal_ota5.lef"],
        [out / "top.v"],
        top="goal_chip",
        die=(0, 0, w, h),
        core=(0, 0, w, h),
        placements={"ota": OTA_LOCATION},
        peripheral_placements={"ring": (0, 0)},
        place_io=False,
        # Coarse global bins at the fixed VSSA pin have zero capacity; retain
        # their report and require successful detailed routing/physical checks.
        allow_global_congestion=True,
        routing_layers=("met1", "met5"),
        timeout=600,
    )
    # IFP requires every BLOCK bbox inside its floorplan core. The ring is a
    # full-die BLOCK; its OBS enforce the manifest's actual analog core area.
    result = run(spec, tools, out / "route")
    if result["drc_violations"] != 0:
        raise RuntimeError("Chip detailed routing has DRC violations")
    result["global_congestion_report"] = "route/global_congestion.rpt"
    result["global_congestion_allowed"] = spec.allow_global_congestion
    result["manifest_core"] = manifest["spec"]["core"]
    result["openroad_floorplan_core"] = [0, 0, w, h]
    result["gds"] = merge_gds(
        out / "route/routed.def",
        [ring_dir / "pad_ring.gds", ota_dir / "hardened/goal_ota5.gds"],
        spec.macro_lefs,
        tools,
        spec.top,
        out / "route/final.gds",
    )
    terminals = manifest["bus_terminals"] + manifest["tie_terminals"]
    # Ring-side core access and physical external bond-pad metal.
    terminals += [
        dict(p, net=SUPPLIES.get(p["net"], p["net"])) for p in manifest["core_ports"]
    ]
    terminals += manifest["package_terminals"]
    external = macro_terminals(ota, OTA_LOCATION)
    terminals += [dict(t, net=SUPPLIES.get(t["net"], t["net"])) for t in external]
    # Preserve the original device landings through OTA hardening's normalization.
    devices = read_json(ota_dir / "placed/ota5_devices.json")
    dx, dy = ota["source_origin"]
    location = (OTA_LOCATION[0] + 40 - dx, OTA_LOCATION[1] + 40 - dy)
    for terminal in macro_terminals(devices, location):
        alias = terminal["net"]
        terminal["net"] = SUPPLIES.get(
            alias, alias if alias in ota["pins"] else "ota_internal_" + alias
        )
        terminals.append(terminal)
    (out / "connectivity_terminals.json").write_text(
        json.dumps(terminals, indent=2) + "\n"
    )
    result["connectivity"] = Connectivity(out / "route/final.gds", pdk).check(terminals)
    result["magic_drc"] = magic_drc(
        pdk, out / "route/final.gds", spec.top, out / "magic", timeout=600
    )
    result["not_done"] = [
        "LVS",
        "ESD sizing/verification",
        "seal ring",
        "density fill",
        "antenna",
    ]
    result["placement"] = {"ring": [0, 0], "ota": list(OTA_LOCATION), "status": "FIXED"}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ring", type=Path)
    parser.add_argument("--ota", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.out, args.ring, args.ota), indent=2))
