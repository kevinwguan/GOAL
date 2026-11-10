"""Timeout-bounded local OpenROAD execution, ported from route_independent.py."""

import json
import subprocess
import time
from pathlib import Path

from .locate import Toolchain
from .metrics import parse_metrics, scrub
from .tcl import FlowSpec, generate


def run(spec: FlowSpec, tools: Toolchain, out_dir: str | Path) -> dict:
    """Capture logs and metrics; fail visibly on exit, timeout or missing outputs."""
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(
        (out / name).exists() for name in ("route.tcl", "routed.def", "metrics.json")
    ):
        raise FileExistsError(
            f"Route output already exists: {out}; choose a fresh directory"
        )
    script, method = generate(spec, tools, out)
    (out / "route.tcl").write_text(script)
    start = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(
            [
                str(tools.binary),
                "-no_init",
                "-threads",
                str(spec.threads),
                "-exit",
                str(out / "route.tcl"),
                "-metrics",
                str(out / "openroad_metrics.json"),
            ],
            cwd=out,
            capture_output=True,
            text=True,
            timeout=spec.timeout,
        )
        log, code = proc.stdout + "\n" + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:

        def decoded(value):
            return (
                value.decode(errors="replace")
                if isinstance(value, bytes)
                else value or ""
            )

        log, code = decoded(exc.stdout) + decoded(exc.stderr), None
        timed_out = True
    log = scrub(
        log,
        {
            str(out): "$OUT",
            str(tools.platform): "$PLATFORM",
            str(tools.binary): "$OPENROAD",
            str(Path.home()): "$HOME",
        },
    )
    (out / "openroad.log").write_text(log)
    raw_path = out / "openroad_metrics.json"
    raw = json.loads(raw_path.read_text()) if raw_path.exists() else {}
    result = parse_metrics(log, raw, time.monotonic() - start, method)
    result.update(exit_code=code, timed_out=timed_out)
    (out / "metrics.json").write_text(json.dumps(result, indent=2) + "\n")
    if timed_out or code != 0 or result["errors"]:
        raise RuntimeError(
            f"OpenROAD failed; see {out / 'openroad.log'}\n{log[-3000:]}"
        )
    for name in ("routed.def", "routed.odb", "routed.spef", "detailed.drc"):
        if not (out / name).is_file():
            raise RuntimeError(
                f"OpenROAD did not produce {name}; see {out / 'openroad.log'}"
            )
    return result
