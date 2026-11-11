"""LEF handoff for core-facing pad access, with conservative ring obstacles."""

from pathlib import Path

import klayout.db as kdb

from goal.lef.verilog import identifier
from goal.signoff.connectivity import conducting_region


def write_core_abstract(meta: dict, pdk, out: Path) -> None:
    """Emit a core-coordinate abstract and a full-die ring master for assembly."""
    layout = kdb.Layout()
    layout.read(str(out / "pad_ring.gds"))
    core = meta["spec"]["core"]
    w, h = meta["spec"]["die"]
    dbu = layout.dbu

    def region(box):
        return kdb.Region(kdb.Box(*(round(v / dbu) for v in box)))

    for macro, filename, origin, size in [
        (
            "goal_ring_core",
            "core_area.lef",
            core[:2],
            (core[2] - core[0], core[3] - core[1]),
        ),
        ("goal_pad_ring", "pad_ring.lef", (0, 0), (w, h)),
    ]:
        ox, oy = origin

        def rectangle(box):
            return (
                "RECT "
                + " ".join(
                    f"{v:.3f}"
                    for v in (box[0] - ox, box[1] - oy, box[2] - ox, box[3] - oy)
                )
                + " ;"
            )

        lines = [
            "VERSION 5.8 ;",
            'BUSBITCHARS "[]" ;',
            'DIVIDERCHAR "/" ;',
            f"MACRO {macro}",
            "  CLASS BLOCK ;",
            "  ORIGIN 0 0 ;",
            f"  SIZE {size[0]:.3f} BY {size[1]:.3f} ;",
        ]
        for pin in meta["core_ports"]:
            name = identifier(pin["name"])
            lines += [
                f"  PIN {name}",
                "    DIRECTION INOUT ;",
                "    USE SIGNAL ;",
                "    PORT",
                f"      LAYER {pdk.lef_layer(pin['layer'])} ;",
                "      " + rectangle(pin["box"]),
                "    END",
                f"  END {name}",
            ]
        if macro == "goal_pad_ring":
            lines.append("  OBS")
            for layer in pdk.data["lef_layers"] | pdk.data.get("obs_layers", {}):
                # Entire periphery is blocked; preserve actual interior metal.
                actual = conducting_region(layout, layout.top_cell(), pdk, layer)
                fixed = (region((0, 0, w, h)) - region(core)) | (actual & region(core))
                for pin in meta["core_ports"]:
                    if pin["layer"] == layer:
                        fixed -= region(pin["box"])
                if not fixed.is_empty():
                    lines.append(f"    LAYER {pdk.lef_layer(layer)} ;")
                    for polygon in (
                        fixed.merged().decompose_trapezoids_to_region().each()
                    ):
                        b = polygon.bbox()
                        lines.append(
                            "    "
                            + rectangle(
                                (
                                    b.left * dbu,
                                    b.bottom * dbu,
                                    b.right * dbu,
                                    b.top * dbu,
                                )
                            )
                        )
            lines.append("  END")
        lines += [f"END {macro}", "END LIBRARY"]
        (out / filename).write_text("\n".join(lines) + "\n")
