"""Re-expose routed IO pads when hardening an OpenROAD-produced DEF/GDS."""

from pathlib import Path
import re
import gdsfactory as gf
from goal.cells.geometry import port


def routed_component(def_path: Path, gds_path: Path, pdk) -> gf.Component:
    """Import routed geometry and the N-oriented rectangular IO pads we emit.

    This deliberately narrow DEF reader fails on other pin transforms/shapes;
    it is not a general DEF parser. GDSFactory/OpenROAD handle macro transforms.
    """
    text = def_path.read_text()
    units = int(re.search(r"UNITS DISTANCE MICRONS (\d+)\s*;", text)[1])
    section = re.search(r"^PINS \d+ ;(.*?)^END PINS", text, re.M | re.S)
    if section is None:
        raise ValueError("No PINS section in routed DEF")
    imported = gf.import_gds(gds_path)
    component = gf.Component()
    component << imported
    inverse = {name: generic for generic, name in pdk.data["lef_layers"].items()}
    for record in re.finditer(r"^\s*-\s+(\S+)(.*?);", section[1], re.M | re.S):
        name, body = record.groups()
        position = re.search(
            r"\+ (?:PLACED|FIXED)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\S+)", body
        )
        boxes = re.findall(
            r"\+ LAYER (\S+)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)",
            body,
        )
        if position is None or position[3] != "N" or len(boxes) != 1:
            raise ValueError(f"Unsupported routed IO geometry: {name}")
        x, y = int(position[1]), int(position[2])
        layer, x0, y0, x1, y1 = boxes[0]
        box = (
            (int(x0) + x) / units,
            (int(y0) + y) / units,
            (int(x1) + x) / units,
            (int(y1) + y) / units,
        )
        port(component, pdk, name, name, box, inverse[layer])
    return component
