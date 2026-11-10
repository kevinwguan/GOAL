import os
from pathlib import Path
import pytest
from goal.cli import main
from goal.flow import run_flow
from goal.openroad import locate
from goal.pdk import PDK


@pytest.mark.parametrize("command", [[], ["lef"], ["route"], ["flow"]])
def test_help(command):
    with pytest.raises(SystemExit) as error:
        main(command + ["--help"])
    assert error.value.code == 0


@pytest.mark.openroad
def test_three_modes(tmp_path):
    try:
        locate(PDK.load("sky130A"))
    except FileNotFoundError as error:
        if os.getenv("OPENROAD"):
            raise
        pytest.skip(str(error))
    result = run_flow({"pdk": "sky130A"}, tmp_path / "vehicle")
    assert result["all_routes_drc_clean"]
    assert result["direction_check"]
    assert all(ratio > 1 for ratio in result["conv_over_split_R"].values())
    for row in result["modes"].values():
        assert row["gds"]["macros"] == ["goal_pair"]
        assert row["parasitics"] in ("openrcx", "estimated_global_routing")
    with pytest.raises(FileExistsError):
        run_flow({}, tmp_path / "vehicle")
