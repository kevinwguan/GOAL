"""Plain LEF 5.8 abstract emission, refactored from reproduction/lef.py."""

import json
from collections import defaultdict
from pathlib import Path

from .gds import write_macro_gds
from .obs import obstructions
from .ports import port_box
from .verilog import blackbox, identifier


def write_abstract(
    component,
    pdk,
    out_dir: str | Path,
    mode: str = "per_finger",
    macro_name: str = "goal_macro",
    tech_lef: Path | None = None,
    coarse_obs: bool = False,
) -> dict:
    """Emit LEF, merged GDS, blackbox and the physical-pin → logical-net map.

    Ports need `net`, `generic_layer` and `rect_local` metadata (see ENGINE.md).
    `merged` combines access rectangles under one PIN per logical net;
    `per_finger` preserves every physical port. cap_split belongs in the wrapper.
    """
    if mode not in ("merged", "per_finger"):
        raise ValueError("LEF mode must be merged or per_finger")
    identifier(macro_name)
    if tech_lef is not None:
        pdk.validate_lef(Path(tech_lef))
    grouped = defaultdict(list)
    for pin in sorted(component.ports, key=lambda p: p.name):
        identifier(pin.name)
        identifier(pin.info["net"])
        pdk.lef_layer(pin.info["generic_layer"])
        grouped[pin.info["net"]].append(pin)
    pins, aliases = {}, {}
    for net, ports in sorted(grouped.items()):
        if mode == "merged":
            pins[net], aliases[net] = ports, net
        else:
            for pin in ports:
                pins[pin.name], aliases[pin.name] = [pin], net
    xoff, yoff = component.dxmin, component.dymin

    def shifted(box):
        return (box[0] - xoff, box[1] - yoff, box[2] - xoff, box[3] - yoff)

    def rectangle(box):
        return "RECT " + " ".join(f"{v:.3f}" for v in box) + " ;"

    lines = [
        "VERSION 5.8 ;",
        'BUSBITCHARS "[]" ;',
        'DIVIDERCHAR "/" ;',
        f"MACRO {macro_name}",
        "  CLASS BLOCK ;",
        "  ORIGIN 0 0 ;",
        f"  SIZE {component.dxsize:.3f} BY {component.dysize:.3f} ;",
        "  SYMMETRY X Y ;",
    ]
    rectangles, layers = {}, {}
    for name, ports in pins.items():
        lines += [
            f"  PIN {name}",
            "    DIRECTION INOUT ;",
            "    USE SIGNAL ;",
            "    PORT",
        ]
        rectangles[name], layers[name] = [], []
        for pin in ports:
            box = shifted(port_box(pin))
            layer = pdk.lef_layer(pin.info["generic_layer"])
            lines += [f"      LAYER {layer} ;", "      " + rectangle(box)]
            rectangles[name].append(list(box))
            layers[name].append(layer)
        lines += ["    END", f"  END {name}"]
    lines.append("  OBS")
    obs = obstructions(component, pdk, coarse_obs)
    for layer, boxes in obs.items():
        lines.append(f"    LAYER {layer} ;")
        lines += ["    " + rectangle(shifted(box)) for box in boxes]
    lines += ["  END", f"END {macro_name}", "END LIBRARY"]
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{macro_name}.lef").write_text("\n".join(lines) + "\n")
    (dest / f"{macro_name}_bb.v").write_text(blackbox(macro_name, aliases))
    write_macro_gds(component, dest / f"{macro_name}.gds", macro_name)
    metadata = dict(
        macro=macro_name,
        mode=mode,
        pins=aliases,
        rectangles=rectangles,
        layers=layers,
        width=component.dxsize,
        height=component.dysize,
        source_origin=[xoff, yoff],
        obs_rectangles=sum(map(len, obs.values())),
    )
    (dest / f"{macro_name}.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata
