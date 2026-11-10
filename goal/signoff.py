"""Optional full Magic DRC, reporting observed counts without fitting geometry."""

import os
import re
import shutil
import subprocess
from pathlib import Path

from .openroad.metrics import scrub


def magic_drc(pdk, gds: Path, top: str, out_dir: Path) -> dict:
    """Run drc(full), or explicitly record why it was not tested."""
    binary = shutil.which("magic")
    root = os.getenv("PDK_ROOT")
    if not binary or not root:
        return {"status": "not tested", "reason": "Magic and PDK_ROOT required"}
    rc = Path(root) / pdk.name / "libs.tech/magic" / f"{pdk.name}.magicrc"
    if not rc.is_file():
        return {"status": "not tested", "reason": f"Missing {pdk.name} Magic rc file"}
    out_dir.mkdir(parents=True, exist_ok=True)
    script = f"""gds readonly true
gds read {{{gds.resolve()}}}
load {top}
select top cell
drc style drc(full)
drc check
drc catchup
puts "GOAL_DRC_COUNT [drc list count total]"
puts [drc listall why]
quit -noprompt
"""
    (out_dir / "check.tcl").write_text(script)
    proc = subprocess.run(
        [binary, "-dnull", "-noconsole", "-rcfile", str(rc)],
        input=script,
        cwd=out_dir,
        capture_output=True,
        text=True,
        timeout=180,
    )
    log = scrub(proc.stdout + proc.stderr, {str(Path.home()): "$HOME"})
    (out_dir / "magic.log").write_text(log)
    count = re.search(r"GOAL_DRC_COUNT\s+(\d+)", log)
    if proc.returncode or not count:
        raise RuntimeError(f"Magic failed; see {out_dir / 'magic.log'}\n{log[-1500:]}")
    return {"status": "measured", "style": "drc(full)", "count": int(count[1])}
