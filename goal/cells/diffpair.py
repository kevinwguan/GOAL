"""Guarded pair ported from reproduction/lef.py, independent of LEF emission."""

import gdsfactory as gf
from goal.pdk import PDK
from .geometry import rect, port
from .mosfet import mosfet


def diffpair(pdk: PDK) -> gf.Component:
    """Two four-finger NMOS devices with a shared guard-ring bulk rail."""
    c = gf.Component()
    bulk_boxes = []
    for side in ("p", "n"):
        cell = mosfet(
            pdk,
            fingers=4,
            drain="drn_" + side,
            source="tail",
            gate="gate_" + side,
            bulk="bulk",
            name=None,
        )
        ref = c << cell
        x = (
            -ref.dxmin
            if side == "p"
            else c.dxmax - ref.dxmin + pdk.rule("well_spacing")
        )
        ref.dmove((x, -ref.dymin))
        for pin in ref.ports:
            x0, y0, x1, y1 = pin.info["rect"]
            w, h = x1 - x0, y1 - y0
            cx, cy = pin.dcenter
            box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            if pin.name == "B":
                bulk_boxes.append(box)
            else:
                port(
                    c,
                    pdk,
                    side + "_" + pin.name,
                    pin.info["net"],
                    box,
                    orientation=pin.orientation,
                )
    rail = (
        min(b[0] for b in bulk_boxes),
        min(b[1] for b in bulk_boxes),
        max(b[2] for b in bulk_boxes),
        max(b[3] for b in bulk_boxes),
    )
    rect(c, pdk, "met1", rail)
    port(c, pdk, "bulk", "bulk", bulk_boxes[0])
    c.info["vehicle"] = "guarded four-finger MOS pair; block LVS not asserted"
    return c
