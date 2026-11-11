"""Declared centre-line resistor model for the optional source/drain straps."""

import re
from pathlib import Path

import klayout.db as kdb

from goal.rc import RCNet, effective


def strap_resistance(
    gds: Path, meta: dict, pdk, tech_lef: Path, placement: tuple
) -> dict:
    """Measure rail/stem lengths and routed access from delivered GDS geometry.

    M1/M2 sheet R comes from tech LEF; via1 R from the PDK typical-corner
    table. All finger centres are equipotential. The single connected routed
    aperture is an equipotential sink. Add this internal R in series with
    OpenRCX's macro-pin-to-IO result. This is a 1D approximation, not field
    solving; current spreading and FEOL/contact R are excluded in every mode.
    Reject multiple disconnected route apertures (requires a coupled model).
    """
    text = tech_lef.read_text()
    sheet = {}
    for generic in ("met1", "met2"):
        name = pdk.lef_layer(generic)
        body = re.search(
            r"^LAYER " + name + r"\s*$(.*?)^END " + name + r"\s*$", text, re.M | re.S
        )[1]
        sheet[generic] = float(re.search(r"RESISTANCE RPERSQ ([\d.]+)", body)[1])
    layout = kdb.Layout()
    layout.read(str(gds))
    layout.cell(meta["macro"]).clear()
    dbu = layout.dbu
    routes = kdb.Region(
        layout.top_cell().begin_shapes_rec(layout.layer(*pdk.layer("met2")))
    )
    measured = {}
    px, py = placement
    for alias in ("drn_p", "drn_n", "tail"):
        boxes = meta["rectangles"][alias]
        y = (boxes[0][1] + boxes[0][3]) / 2 + py
        width = boxes[0][3] - boxes[0][1]
        rail = kdb.Region()
        for b in boxes:
            rail.insert(
                kdb.Box(
                    *(
                        round(v / dbu)
                        for v in (b[0] + px, b[1] + py, b[2] + px, b[3] + py)
                    )
                )
            )
        access = list((rail & routes).merged().each())
        if len(access) != 1:
            raise ValueError(f"{alias}: expected one route aperture, got {len(access)}")
        sink_x = access[0].bbox().center().x * dbu
        terminals = [t for t in meta["terminals"] if t["net"] == alias]
        xs = sorted(
            set([(t["box"][0] + t["box"][2]) / 2 + px for t in terminals] + [sink_x])
        )
        nodes = {x: f"rail_{i}" for i, x in enumerate(xs)}
        net = RCNet(alias, 0, ports=[nodes[sink_x]])
        for i, (a, b) in enumerate(zip(xs, xs[1:])):
            net.resistors.append((nodes[a], nodes[b], (b - a) / width * sheet["met2"]))
        stem_width = (
            round(
                (pdk.rule("via_size") + 2 * pdk.rule("metal_surround") + 0.04) / 0.005
            )
            * 0.005
        )
        for i, t in enumerate(terminals):
            x = (t["box"][0] + t["box"][2]) / 2 + px
            ty = (t["box"][1] + t["box"][3]) / 2 + py
            node = f"finger_{i}"
            net.instances.append(node)
            resistance = (
                abs(y - ty) / stem_width * sheet["met1"]
                + pdk.data["strap_rc"]["via1_ohm"]
            )
            net.resistors.append((node, nodes[x], resistance))
        measured[alias] = effective([net]) | dict(
            sheet_ohm=sheet,
            via1_ohm=pdk.data["strap_rc"]["via1_ohm"],
            access_x_um=sink_x,
            model="centre-line M1 stems/via1/M2 rail; equipotential aperture",
        )
    return measured
