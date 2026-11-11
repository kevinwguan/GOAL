"""DEF → final GDS, using the ORFS def2stream.py merge strategy."""

import re
from pathlib import Path

import klayout.db as kdb

from .locate import Toolchain


def merge_gds(
    def_path: Path,
    macro_gds: list[Path],
    macro_lefs: list[Path],
    tools: Toolchain,
    top_name: str,
    output: Path,
    stdcell_gds: list[Path] | None = None,
) -> dict:
    """Preserve routed wires/vias, replace LEF placeholders with source GDS."""
    if tools.klayout_tech is None:
        raise FileNotFoundError("Set KLAYOUT_TECH to a platform .lyt for final GDS")
    technology = kdb.Technology()
    technology.load(str(tools.klayout_tech))
    options = technology.load_layout_options
    config = options.lefdef_config
    config.lef_files = [str(tools.tech_lef)] + [str(p.resolve()) for p in macro_lefs]
    config.read_lef_with_def = True
    if not tools.gds_layers:
        raise ValueError("Toolchain needs an explicit PDK GDS layer map")
    layer_map = kdb.LayerMap()
    for name, (layer, datatype) in tools.gds_layers.items():
        layer_map.map(f"{name}.drawing : {layer}/{datatype}")
    config.layer_map = layer_map
    config.routing_suffix = ".drawing"
    config.via_geometry_suffix = ".drawing"
    config.pins_suffix = ".drawing"
    config.produce_cell_outlines = False
    config.produce_labels = False
    config.produce_obstructions = False
    config.produce_blockages = False
    config.create_other_layers = False
    units = re.search(r"UNITS DISTANCE MICRONS (\d+)\s*;", def_path.read_text())
    if units is None:
        raise ValueError("DEF lacks distance units")
    config.dbu = 1 / int(units[1])
    options.lefdef_config = config
    layout = kdb.Layout()
    layout.read(str(def_path), options)
    if layout.cell(top_name) is None:
        raise ValueError(f"DEF lacks design {top_name}")
    for cell in layout.each_cell():
        if (
            cell.name != top_name
            and not cell.name.startswith("VIA_")
            and not cell.name.endswith("_DEF_FILL")
        ):
            cell.clear()
    macro_names = []
    for path in [*macro_gds, *(stdcell_gds or [])]:
        source = kdb.Layout()
        source.read(str(path))
        if path in macro_gds:
            macro_names += [cell.name for cell in source.top_cells()]
        for source_top in source.top_cells():
            target = layout.cell(source_top.name) or layout.create_cell(source_top.name)
            target.copy_tree(source_top)
    final = kdb.Layout()
    final.dbu = layout.dbu
    top = final.create_cell(top_name)
    top.copy_tree(layout.cell(top_name))
    empty = [cell.name for cell in final.each_cell() if cell.is_empty()]
    if empty:
        raise ValueError(f"Missing GDS geometry for cells: {empty}")
    for name in macro_names:
        if final.cell(name) is None:
            raise ValueError(f"Final GDS lacks macro {name}")
    final.write(str(output))
    check = kdb.Layout()
    check.read(str(output))
    if check.top_cell().name != top_name:
        raise ValueError("Final GDS top-cell verification failed")
    return dict(top=top_name, macros=macro_names, cells=check.cells())
