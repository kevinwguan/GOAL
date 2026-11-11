"""Fixed metal minus exposed access rectangles, from reproduction/lef.py."""

import klayout.db as kdb

from .ports import port_box


def obstructions(component, pdk, coarse: bool = False) -> dict[str, list[tuple]]:
    """Decompose orthogonal metal into LEF RECTs, preserving pin holes.

    Coarse mode starts with each occupied layer's bounding box before cutting
    the pin apertures, so it is conservative without blocking the pins.
    """
    polygons = component.get_polygons(by="tuple")
    dbu = component.kcl.dbu
    result = {}
    for layer in pdk.data["lef_layers"] | pdk.data.get("obs_layers", {}):
        fixed = kdb.Region()
        for polygon in polygons.get(pdk.layer(layer), []):
            fixed.insert(polygon)
        if fixed.is_empty():
            continue
        if coarse:
            fixed = kdb.Region(fixed.bbox())
        exposed = kdb.Region()
        for pin in component.ports:
            if pin.info["generic_layer"] == layer and not pin.info.get(
                "terminal_only", False
            ):
                exposed.insert(kdb.Box(*(round(v / dbu) for v in port_box(pin))))
        rectangles = []
        for polygon in (
            (fixed - exposed).merged().decompose_trapezoids_to_region().each()
        ):
            box = polygon.bbox()
            if polygon.area() != box.area():
                raise ValueError(
                    "Nonorthogonal fixed metal cannot be represented by RECT"
                )
            rectangles.append(
                (box.left * dbu, box.bottom * dbu, box.right * dbu, box.top * dbu)
            )
        if rectangles:
            result[pdk.lef_layer(layer)] = rectangles
    return result
