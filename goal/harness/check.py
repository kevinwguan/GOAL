"""Raw pad-ring assembly checks, including inherited Magic DRC accounting."""

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import klayout.db as kdb

from goal.openroad import locate
from goal.signoff import magic_drc
from goal.signoff.connectivity import Connectivity

from .library import PadLibrary


def check_ring(meta: dict, pdk, out: Path) -> dict:
    """Check zero longitudinal gaps, physical buses, raw DRC and LEF loading."""
    gaps = {s: r["gaps_um"] for s, r in meta["abutments"].items()}
    if any(abs(g) > 1e-6 for row in gaps.values() for g in row):
        raise ValueError(f"Nonzero ring gaps: {gaps}")
    connectivity = Connectivity(out / "pad_ring.gds", pdk).check(
        meta["bus_terminals"] + meta.get("tie_terminals", [])
    )
    library = PadLibrary(pdk)
    counts = Counter(r["cell"] for r in meta["instances"])
    baseline = {}
    for cell, multiplicity in counts.items():
        source = library.load(cell)
        baseline_dir = out / "magic_baseline" / cell
        baseline_dir.mkdir(parents=True, exist_ok=True)
        original = kdb.Layout()
        original.read(str(source.gds))
        single = kdb.Layout()
        single.dbu = original.dbu
        single.create_cell(cell).copy_tree(original.cell(cell))
        standalone = baseline_dir / "standalone.gds"
        single.write(str(standalone))
        baseline[cell] = magic_drc(pdk, standalone, cell, baseline_dir) | dict(
            instances=multiplicity
        )
    ring = magic_drc(pdk, out / "pad_ring.gds", meta["top"], out / "magic_ring")
    inherited = sum(r["count"] * r["instances"] for r in baseline.values())
    tools = locate(pdk)
    script = out / "read_lef.tcl"
    script.write_text(
        f"read_lef {{{tools.tech_lef}}}\nread_lef {{{(out / 'core_area.lef').resolve()}}}\nread_lef {{{(out / 'pad_ring.lef').resolve()}}}\nexit\n"
    )
    proc = subprocess.run(
        [str(tools.binary), "-no_init", "-exit", str(script.resolve())],
        capture_output=True,
        text=True,
        timeout=180,
    )
    log = proc.stdout + proc.stderr
    (out / "read_lef.log").write_text(log)
    errors = re.findall(r"\[ERROR[^\n]*", log)
    result = dict(
        gaps=gaps,
        connectivity=connectivity,
        baseline_drc=baseline,
        ring_drc=ring,
        instance_weighted_baseline=inherited,
        drc_delta=ring["count"] - inherited,
        lef_exit=proc.returncode,
        lef_errors=errors,
    )
    (out / "checks.json").write_text(json.dumps(result, indent=2) + "\n")
    if proc.returncode or errors:
        raise RuntimeError(f"OpenROAD rejected ring abstracts: {errors}")
    return result
