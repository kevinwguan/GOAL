"""Guarded pair ported from reproduction/lef.py, independent of LEF emission."""

import gdsfactory as gf

from goal.lef.ports import port_box
from goal.pdk import PDK

from .geometry import port, rect
from .mosfet import mosfet


def diffpair(pdk: PDK, strapped: bool = False) -> gf.Component:
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
            strapped=strapped,
        )
        ref = c << cell
        x = (
            -ref.dxmin
            if side == "p"
            else c.dxmax - ref.dxmin + pdk.rule("well_spacing")
        )
        ref.dmove((x, -ref.dymin))
        for pin in ref.ports:
            box = port_box(pin)
            if pin.name == "B":
                bulk_boxes.append(box)
            else:
                copied = port(
                    c,
                    pdk,
                    side + "_" + pin.name,
                    pin.info["net"],
                    box,
                    layer=pin.info["generic_layer"],
                    orientation=pin.orientation,
                )
                if pin.info.get("terminal_only", False):
                    copied.info["terminal_only"] = True
    if strapped:
        boxes = [
            port_box(p)
            for p in c.ports
            if p.info["net"] == "tail" and not p.info.get("terminal_only", False)
        ]
        bridge = (
            min(b[0] for b in boxes),
            boxes[0][1],
            max(b[2] for b in boxes),
            boxes[0][3],
        )
        rect(c, pdk, "met2", bridge)
        port(c, pdk, "tail_bridge", "tail", bridge, layer="met2")
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
