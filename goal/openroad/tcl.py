"""Generate a reusable macro-assembly routing flow."""

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from goal.lef.verilog import identifier

from .locate import Toolchain


def quote(value: str | Path) -> str:
    """Tcl braced word; reject delimiters rather than risk script injection."""
    text = str(value)
    if any(c in text for c in "{}\n\r"):
        raise ValueError("Unsupported Tcl path/name delimiters")
    return "{" + text + "}"


@dataclass
class FlowSpec:
    """Coordinates and sizes are micrometres; DEF fallback preserves its floorplan."""

    macro_lefs: list[Path]
    verilog: list[Path] = field(default_factory=list)
    top: str = "goal_top"
    die: tuple[float, float, float, float] = (0, 0, 120, 100)
    core: tuple[float, float, float, float] = (1, 1, 119, 99)
    placements: dict[str, tuple[float, float]] = field(default_factory=dict)
    io_pins: dict[str, tuple[float, float]] = field(default_factory=dict)
    routing_layers: tuple[str, str] = ("met1", "met5")
    io_layer: str = "met2"
    io_size: float | None = None
    placed_def: Path | None = None
    auto_place: bool = False
    site: str | None = None
    timeout: float = 300
    threads: int = 1


def generate(spec: FlowSpec, tools: Toolchain, out_dir: Path) -> tuple[str, str]:
    """Read/link Verilog by default, route, extract RC, and write all products."""
    out = out_dir.resolve()
    identifier(spec.top)
    if not spec.verilog and spec.placed_def is None:
        raise ValueError("FlowSpec needs Verilog or a placed DEF")
    sites = re.findall(r"^SITE\s+(\S+)", tools.tech_lef.read_text(), re.M)
    site = spec.site or (sites[0] if sites else None)
    if not site and not spec.placed_def:
        raise ValueError("Technology has no SITE; set FlowSpec.site")
    io_size = spec.io_size
    if io_size is None:
        text = tools.tech_lef.read_text()
        block = re.search(
            r"^LAYER "
            + re.escape(spec.io_layer)
            + r"\s*$(.*?)^END "
            + re.escape(spec.io_layer)
            + r"\s*$",
            text,
            re.M | re.S,
        )
        if block is None:
            raise ValueError(f"No IO layer {spec.io_layer} in technology")
        width = re.search(r"\bWIDTH\s+([\d.eE+-]+)", block[1])
        area = re.search(r"\bAREA\s+([\d.eE+-]+)", block[1])
        # Quantize up on a conservative 5nm construction grid.
        io_size = (
            math.ceil(
                max(
                    0.28,
                    float(width[1]) if width else 0,
                    math.sqrt(float(area[1])) if area else 0,
                )
                / 0.005
                - 1e-9
            )
            * 0.005
        )
    lines = [f"read_lef {quote(tools.tech_lef)}"]
    lines += [f"read_lef {quote(p.resolve())}" for p in spec.macro_lefs]
    if spec.placed_def:
        lines.append(f"read_def {quote(spec.placed_def.resolve())}")
    else:
        lines += [f"read_verilog {quote(p.resolve())}" for p in spec.verilog]
        lines += [
            f"link_design {spec.top}",
            f"initialize_floorplan -site {identifier(site)} -die_area {{"
            + " ".join(map(str, spec.die))
            + "} -core_area {"
            + " ".join(map(str, spec.core))
            + "}",
        ]
        lines.append("make_tracks")
        if spec.auto_place:
            lines.append(
                "rtl_macro_placer -report_directory " + quote(out / "placement")
            )
            lines.append(
                "foreach inst [[ord::get_db_block] getInsts] { if {[[$inst getMaster] isBlock]} { $inst setPlacementStatus LOCKED } }"
            )
        for name, (x, y) in spec.placements.items():
            lines.append(
                f"place_macro -macro_name {identifier(name)} -location {{{x} {y}}} -orientation R0 -exact"
            )
            lines.append(
                f"[[ord::get_db_block] findInst {identifier(name)}] setPlacementStatus LOCKED"
            )
        if spec.io_pins:
            for name, (x, y) in spec.io_pins.items():
                lines.append(
                    f"place_pin -pin_name {identifier(name)} -layer {identifier(spec.io_layer)} -location {{{x} {y}}} -pin_size {{{io_size} {io_size}}} -placed_status"
                )
        else:
            directions = []
            for layer, body in re.findall(
                r"^LAYER (\S+)\s*$(.*?)^END \1\s*$",
                tools.tech_lef.read_text(),
                re.M | re.S,
            ):
                direction = re.search(r"DIRECTION\s+(HORIZONTAL|VERTICAL)", body)
                if direction:
                    directions.append((layer, direction[1]))
            names = [layer for layer, _ in directions]
            lo_index, hi_index = (names.index(layer) for layer in spec.routing_layers)
            allowed = directions[lo_index : hi_index + 1]
            horizontal = next(
                (layer for layer, direction in allowed if direction == "HORIZONTAL"),
                None,
            )
            vertical = next(
                (layer for layer, direction in allowed if direction == "VERTICAL"), None
            )
            if not horizontal or not vertical:
                raise ValueError(
                    "Automatic IO placement needs horizontal and vertical routing layers"
                )
            lines += [
                f"place_pins -hor_layers {identifier(horizontal)} -ver_layers {identifier(vertical)}"
            ]
    lo, hi = map(identifier, spec.routing_layers)
    if spec.placed_def:
        lines.append("make_tracks")
    lines += [
        f"set_routing_layers -signal {lo}-{hi}",
        f"global_route -congestion_iterations 50 -guide_file {quote(out / 'global.guide')}",
        f"detailed_route -output_drc {quote(out / 'detailed.drc')}",
        f"write_def {quote(out / 'routed.def')}",
    ]
    if tools.rc_rules:
        method = "openrcx"
        lines += [
            "define_process_corner -ext_model_index 0 goal_typ",
            f"extract_parasitics -ext_model_file {quote(tools.rc_rules)}",
            f"write_spef {quote(out / 'routed.spef')}",
        ]
    else:
        method = "estimated_global_routing"
        lines += [
            f"estimate_parasitics -global_routing -spef_file {quote(out / 'routed.spef')}"
        ]
    lines += [f"write_db {quote(out / 'routed.odb')}", "exit"]
    return "\n".join(lines) + "\n", method
