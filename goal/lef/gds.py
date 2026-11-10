"""Macro-named, origin-normalized GDS geometry."""

from pathlib import Path
import klayout.db as kdb


def write_macro_gds(component, path: Path, macro_name: str) -> None:
    """Flatten and merge a component without modifying its source cells."""
    layout = kdb.Layout()
    layout.dbu = component.kcl.dbu
    top = layout.create_cell(macro_name)
    dx, dy = component.dxmin, component.dymin
    shift = kdb.Trans(round(-dx / layout.dbu), round(-dy / layout.dbu))
    for pair, polygons in component.get_polygons(by="tuple").items():
        region = kdb.Region()
        for polygon in polygons:
            region.insert(polygon)
        top.shapes(layout.layer(*pair)).insert(region.merged().transformed(shift))
    options = kdb.SaveLayoutOptions()
    options.gds2_write_timestamps = False
    layout.write(str(path), options)
