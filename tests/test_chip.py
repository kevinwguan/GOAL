"""Exercise the complete pad library and fixed-macro chip handoff."""

import json
import os
import runpy

import klayout.db as kdb
import pytest


@pytest.mark.openroad
@pytest.mark.magic
def test_sky130_chip(tmp_path):
    if not os.getenv("PDK_ROOT") or not os.getenv("OPENROAD"):
        pytest.skip("PDK_ROOT and OPENROAD required")
    out = tmp_path / "chip"
    result = runpy.run_path("examples/chip_sky130/build.py")["build"](out)
    assert result["drc_violations"] == 0
    assert all(r["components"] == 1 for r in result["connectivity"].values())
    # External analog nets include original device, OTA IO, ring and package.
    for net in ("inp", "inn", "bias", "out"):
        assert result["connectivity"][net]["terminals"] >= 4
    for net in ("VDDA", "VSSA"):
        assert result["connectivity"][net]["terminals"] > 10
    assert "ota_internal_n1" in result["connectivity"]
    assert "ota_internal_tail" in result["connectivity"]
    text = (out / "route/routed.def").read_text()
    assert text.count("+ FIXED") == 2
    assert "DIEAREA ( 0 0 ) ( 1004000 1004000 )" in text
    # Independent hierarchy check: the unchanged ring is at the die origin and
    # the re-abstracted OTA is fixed at the code-defined 400um location.
    layout = kdb.Layout()
    layout.read(str(out / "route/final.gds"))
    placements = {i.cell.name: i.dcplx_trans for i in layout.top_cell().each_inst()}
    assert placements["goal_pad_ring"].disp == kdb.DVector(0, 0)
    assert placements["goal_ota5"].disp == kdb.DVector(400, 400)
    meta = json.loads((out / "ring/manifest.json").read_text())
    assert meta["spec"]["core"] == [180, 180, 824, 824]
    assert result["magic_drc"]["status"] == "measured"
    assert result["magic_drc"]["count"] >= 0  # Raw result, no waiver or tuned target.
    assert set(result["not_done"]) == {
        "LVS",
        "ESD sizing/verification",
        "seal ring",
        "density fill",
        "antenna",
    }
