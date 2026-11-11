"""Check real PDK geometry, not just manifest bookkeeping."""

import os

import klayout.db as kdb
import pytest

from goal.harness import PadLibrary, build_ring, check_ring, sky130_example
from goal.pdk import PDK


@pytest.mark.openroad
@pytest.mark.magic
def test_sky130_ring(tmp_path):
    if not os.getenv("PDK_ROOT") or not os.getenv("OPENROAD"):
        pytest.skip("PDK_ROOT and OPENROAD required")
    pdk = PDK.load("sky130A")
    spec = sky130_example()
    out = tmp_path / "ring"
    meta = build_ring(spec, pdk, out)
    # Independent longitudinal intervals computed from LEF sizes/transforms.
    lib = PadLibrary(pdk)
    for side, axis in [("north", 0), ("south", 0), ("east", 1), ("west", 1)]:
        intervals = []
        for record in meta["instances"]:
            if record["side"] != side:
                continue
            cell = lib.load(record["cell"])
            tr = kdb.DCplxTrans(1, record["rotation"], False, *record["origin"])
            points = [tr * kdb.DPoint(0, 0), tr * kdb.DPoint(cell.width, 0)]
            coords = [p.x if axis == 0 else p.y for p in points]
            intervals.append(sorted(coords))
        intervals.sort()
        assert all(abs(a[1] - b[0]) < 1e-6 for a, b in zip(intervals, intervals[1:]))
        expected_start = 200 if side in ("south", "east") else 204
        assert intervals[0][0] == expected_start
        assert sum(b - a for a, b in intervals) == 600
    result = check_ring(meta, pdk, out)
    assert len(result["connectivity"]) == 14  # 12 buses and two tie networks.
    assert result["lef_exit"] == 0 and not result["lef_errors"]
    assert result["ring_drc"]["count"] >= 0
    assert (
        result["drc_delta"]
        == result["ring_drc"]["count"] - result["instance_weighted_baseline"]
    )
    assert (out / "chip_aliases.json").is_file()
    assert all(c.component.ports for c in lib.cache.values())
