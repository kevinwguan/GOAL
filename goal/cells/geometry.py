"""Grid, rectangles and contact stacks ported from reproduction/geometry.py."""

from goal.pdk import PDK
import math
from pathlib import Path
import hashlib
import gdsfactory as gf
from gdsfactory.generic_tech import get_generic_pdk
import klayout.db as kdb

get_generic_pdk().activate()
MARGIN = 0.02  # Construction margin, not a process rule.
GRID = 0.005  # Common output grid, in micrometres.


def snap(value: float) -> float:
    return round(value / GRID) * GRID


def rect(c: gf.Component, pdk: PDK, layer: str, box: tuple) -> None:
    (x0, y0, x1, y1) = map(snap, box)
    if x1 > x0 and y1 > y0:
        c.add_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer=pdk.layer(layer))


def port(
    c: gf.Component,
    pdk: PDK,
    name: str,
    alias: str,
    box: tuple,
    layer: str = "met1",
    orientation: float = 90,
):
    (x0, y0, x1, y1) = map(snap, box)
    p = c.add_port(
        name=name,
        center=((x0 + x1) / 2, (y0 + y1) / 2),
        width=x1 - x0 if orientation in (90, 270) else y1 - y0,
        orientation=orientation,
        layer=pdk.layer(layer),
        port_type="electrical",
    )
    p.info["net"] = alias
    p.info["rect"] = [x0, y0, x1, y1]
    inverse = p.dcplx_trans.inverted()
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    p.info["rect_local"] = [
        [point.x, point.y] for point in (inverse * kdb.DPoint(*xy) for xy in corners)
    ]
    p.info["generic_layer"] = layer
    return p


def contact(c: gf.Component, pdk: PDK, x: float, y: float, poly: bool = False) -> tuple:
    (x, y) = (snap(x), snap(y))
    cut = pdk.rule("contact_size")
    landing = cut + 2 * pdk.rule("metal_surround") + 2 * MARGIN
    rect(c, pdk, "contact", (x - cut / 2, y - cut / 2, x + cut / 2, y + cut / 2))
    rect(
        c,
        pdk,
        "local",
        (x - landing / 2, y - landing / 2, x + landing / 2, y + landing / 2),
    )
    if "local_via" in pdk.data["layers"]:
        v = pdk.rule("via_size")
        rect(c, pdk, "local_via", (x - v / 2, y - v / 2, x + v / 2, y + v / 2))
        landing = max(landing, v + 2 * pdk.rule("metal_surround"))
    landing = max(landing, math.sqrt(pdk.rule("met1_area")) + 2 * MARGIN)
    rect(
        c,
        pdk,
        "met1",
        (x - landing / 2, y - landing / 2, x + landing / 2, y + landing / 2),
    )
    if poly and "poly_marker" in pdk.data["layers"]:
        e = pdk.rule("poly_surround")
        rect(
            c,
            pdk,
            "poly_marker",
            (
                x - landing / 2 - e,
                y - landing / 2 - e,
                x + landing / 2 + e,
                y + landing / 2 + e,
            ),
        )
    return (x - landing / 2, y - landing / 2, x + landing / 2, y + landing / 2)


def write_gds(c: gf.Component, path: str | Path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    options = kdb.SaveLayoutOptions()
    options.gds2_write_timestamps = False
    c.write_gds(path, save_options=options, with_metadata=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()
