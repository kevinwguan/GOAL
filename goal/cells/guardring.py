"""Contacted guard rings, ported from reproduction/geometry.py."""

import gdsfactory as gf

from goal.pdk import PDK

from .geometry import MARGIN, contact, port, rect, snap


def ring(c: gf.Component, pdk: PDK, box: tuple, kind: str, alias: str) -> float:
    (x0, y0, x1, y1) = map(snap, box)
    t = max(
        pdk.rule("contact_size") + 2 * pdk.rule("tap_surround") + 4 * MARGIN,
        2 * pdk.rule("metal_surround") + pdk.rule("contact_size"),
        2 * pdk.rule("well_overlap_p"),
    )
    e = max(pdk.rule("sub_surround"), pdk.rule("gate_extension"))
    strips = [
        (x0, y0, x1, y0 + t),
        (x0, y1 - t, x1, y1),
        (x0, y0 + t, x0 + t, y1 - t),
        (x1 - t, y0 + t, x1, y1 - t),
    ]
    implant = "pimplant" if kind == "nmos" else "nimplant"
    for b in strips:
        rect(c, pdk, "tap", b)
        (a, b0, d, f) = b
        rect(c, pdk, implant, (a - e, b0 - e, d + e, f + e))
        rect(c, pdk, "met1", b)
    pitch = max(2 * pdk.rule("contact_size") + pdk.rule("metal_spacing"), t)
    for y in [y0 + t / 2, y1 - t / 2]:
        n = max(1, int((x1 - x0 - t) / pitch))
        for i in range(n + 1):
            contact(c, pdk, x0 + t / 2 + (x1 - x0 - t) * i / n, y)
    for x in [x0 + t / 2, x1 - t / 2]:
        n = max(0, int((y1 - y0 - t) / pitch) - 1)
        for i in range(1, n + 1):
            contact(c, pdk, x, y0 + t / 2 + pitch * i)
    port(c, pdk, "B", alias, (x0, y0, x0 + t, y0 + t))
    return t


def guardring(
    pdk: PDK, box: tuple, kind: str = "nmos", net: str = "bulk"
) -> gf.Component:
    """Build a standalone contacted ring exposing the B tap port."""
    c = gf.Component()
    ring(c, pdk, box, kind, net)
    return c
