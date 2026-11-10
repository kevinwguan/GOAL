"""Isolated multi-finger MOS devices, ported from reproduction/geometry.py."""

import gdsfactory as gf

from goal.pdk import PDK

from .geometry import MARGIN, contact, port, rect
from .guardring import ring


def mosfet(
    pdk: PDK,
    kind: str = "nmos",
    fingers: int = 4,
    width: float = 2.0,
    length: float = 0.5,
    drain: str = "D",
    source: str = "S",
    gate: str = "G",
    bulk: str = "B",
    name: str | None = None,
) -> gf.Component:
    """Construct isolated, contacted fingers inside a bulk-tapped guard ring."""
    if kind not in ("nmos", "pmos") or fingers < 1:
        raise ValueError("kind or fingers")
    if width < max(
        pdk.rule("active_width"),
        pdk.rule("contact_size") + 2 * pdk.rule("diff_surround"),
    ):
        raise ValueError("width too small")
    if length < pdk.rule("poly_width"):
        raise ValueError("length too small")
    c = gf.Component(name)
    cut = pdk.rule("contact_size")
    poly_pad = cut + 2 * pdk.rule("poly_surround") + 2 * MARGIN
    half_gap = (
        max(pdk.rule("gate_to_diffcont"), cut / 2 + pdk.rule("diff_gate_space"))
        + MARGIN
    )
    extension = (
        max(pdk.rule("diff_extension"), half_gap + cut / 2 + pdk.rule("diff_surround"))
        + MARGIN
    )
    unit = length + 2 * extension
    pitch = (
        unit
        + max(pdk.rule("diff_spacing"), pdk.rule("poly_spacing"))
        + 2 * pdk.rule("sub_surround")
    )
    gate_y = (
        width + pdk.rule("gate_extension") + poly_pad / 2 + pdk.rule("poly_spacing")
    )
    implant = "nimplant" if kind == "nmos" else "pimplant"
    enc = max(pdk.rule("sub_surround"), pdk.rule("gate_extension"))
    gate_boxes = []
    for f in range(fingers):
        x = f * pitch
        gx = x + extension + length / 2
        rect(c, pdk, "active", (x, 0, x + unit, width))
        rect(c, pdk, implant, (x - enc, -enc, x + unit + enc, width + enc))
        rect(
            c,
            pdk,
            "poly",
            (gx - length / 2, -pdk.rule("gate_extension"), gx + length / 2, gate_y),
        )
        rect(
            c,
            pdk,
            "poly",
            (
                gx - poly_pad / 2,
                gate_y - poly_pad / 2,
                gx + poly_pad / 2,
                gate_y + poly_pad / 2,
            ),
        )
        sx = gx - length / 2 - half_gap
        dx = gx + length / 2 + half_gap
        sb = contact(c, pdk, sx, width / 2)
        db = contact(c, pdk, dx, width / 2)
        port(c, pdk, f"S{f}", source, sb)
        port(c, pdk, f"D{f}", drain, db)
        gate_boxes.append(contact(c, pdk, gx, gate_y, poly=True))
    g0 = gate_boxes[0]
    gn = gate_boxes[-1]
    gb = (g0[0], g0[1], gn[2], gn[3])
    rect(c, pdk, "met1", gb)
    port(c, pdk, "G", gate, gb)
    xend = (fingers - 1) * pitch + unit
    margin = max(
        3 * pdk.rule("diff_spacing"),
        2 * pdk.rule("well_overlap_p") + pdk.rule("metal_spacing"),
    )
    ring_t = max(1.0, 2 * pdk.rule("well_overlap_p"))
    rb = (
        -margin - ring_t,
        -margin - ring_t,
        xend + margin + ring_t,
        gate_y + poly_pad / 2 + margin + ring_t,
    )
    ring(c, pdk, rb, kind, bulk)
    if kind == "pmos":
        e = pdk.rule("well_overlap_p")
        rect(c, pdk, "nwell", (rb[0] - e, rb[1] - e, rb[2] + e, rb[3] + e))
    c.info["kind"] = kind
    c.info["fingers"] = fingers
    return c
