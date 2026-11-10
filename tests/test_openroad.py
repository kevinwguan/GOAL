from pathlib import Path
import os
import pytest
from goal.cells import diffpair
from goal.lef import write_abstract
from goal.lef.verilog import write_wrapper
from goal.openroad import locate, FlowSpec, run
from goal.openroad.gds import merge_gds
from goal.openroad.metrics import scrub, parse_metrics
from goal.pdk import PDK


def test_missing_tool(monkeypatch):
    monkeypatch.setenv("OPENROAD", "/missing/openroad")
    with pytest.raises(FileNotFoundError, match="OPENROAD"):
        locate(PDK.load("sky130A"))


def test_metrics():
    result = parse_metrics(
        "",
        {"route__wirelength": 42, "route__vias": 3, "route__drc_errors": 0},
        1.5,
        "openrcx",
    )
    assert result["wirelength_um"] == 42
    assert result["drc_violations"] == 0
    assert parse_metrics("", {}, 1, "estimated")["wirelength_um"] is None
    assert scrub("/Users/example/private/file") == "$PRIVATE_PATH"


@pytest.mark.openroad
@pytest.mark.parametrize("fallback", [False, True])
def test_route_and_final_gds(tmp_path, fallback):
    pdk = PDK.load("sky130A")
    try:
        tools = locate(pdk)
    except FileNotFoundError as error:
        if os.getenv("OPENROAD"):
            raise
        pytest.skip(str(error))
    meta = write_abstract(
        diffpair(pdk), pdk, tmp_path, macro_name="goal_pair", tech_lef=tools.tech_lef
    )
    write_wrapper("goal_pair", meta["pins"], tmp_path / "top.v")
    spec = FlowSpec(
        [tmp_path / "goal_pair.lef"],
        [tmp_path / "top.v"],
        die=(0, 0, 110, 90),
        core=(0, 0, 110, 90),
        placements={"pair": (40, 40)},
        io_pins={
            "drn_p": (45, 89.5),
            "drn_n": (60, 89.5),
            "tail": (50, 0.5),
            "gate_p": (0.5, 60),
            "gate_n": (109.5, 60),
            "bulk": (0.5, 20),
        },
    )
    if fallback:
        # Exercise DEF input with exactly the same verified placement/netlist.
        first = run(spec, tools, tmp_path / "first")
        spec.placed_def = tmp_path / "first/routed.def"
    result = run(spec, tools, tmp_path / "route")
    assert result["drc_violations"] == 0
    assert result["wirelength_um"] > 0 and result["via_count"] > 0
    assert result["parasitics"] == (
        "openrcx" if tools.rc_rules else "estimated_global_routing"
    )
    assert "+ FIXED" in (tmp_path / "route/routed.def").read_text()
    final = merge_gds(
        tmp_path / "route/routed.def",
        [tmp_path / "goal_pair.gds"],
        spec.macro_lefs,
        tools,
        spec.top,
        tmp_path / "route/final.gds",
    )
    assert "goal_pair" in final["macros"]
    with pytest.raises(FileExistsError):
        run(spec, tools, tmp_path / "route")
