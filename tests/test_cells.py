"""Primitive geometry and optional full Magic DRC."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import pytest
from goal.cells import mosfet, diffpair
from goal.cells.geometry import write_gds
from goal.pdk import PDK


@pytest.mark.parametrize("name", ["sky130A", "gf180mcuD"])
def test_cells(name):
    pdk = PDK.load(name)
    assert len(list(diffpair(pdk).ports)) == 19
    assert len(list(mosfet(pdk).ports)) == 10
    for path in Path("goal/cells").glob("*.py"):
        assert not re.search(r"sky130|gf180|layer\s*=\s*\(\s*\d", path.read_text())


@pytest.mark.magic
@pytest.mark.parametrize("name", ["sky130A", "gf180mcuD"])
@pytest.mark.parametrize("kind", ["nmos", "pmos"])
def test_full_drc(name, kind):
    if not shutil.which("magic") or not os.getenv("PDK_ROOT"):
        pytest.skip("Magic and PDK_ROOT required")
    pdk = PDK.load(name)
    c = mosfet(pdk, kind=kind)
    dest = Path("build/primitives") / name / kind
    dest.mkdir(parents=True, exist_ok=True)
    gds = (dest / "cell.gds").resolve()
    write_gds(c, gds)
    rc = Path(os.environ["PDK_ROOT"]) / name / "libs.tech/magic" / f"{name}.magicrc"
    script = f"""gds readonly true
gds read {{{gds}}}
load {c.name}
select top cell
drc style drc(full)
drc check
drc catchup
puts "GOAL_DRC_COUNT [drc list count total]"
puts [drc listall why]
quit -noprompt
"""
    proc = subprocess.run(
        ["magic", "-dnull", "-noconsole", "-rcfile", str(rc)],
        input=script,
        cwd=dest,
        capture_output=True,
        text=True,
        timeout=180,
    )
    log = proc.stdout + proc.stderr
    (dest / "magic.log").write_text(log)
    assert proc.returncode == 0, log
    assert re.search(r"GOAL_DRC_COUNT\s+0\b", log), log
