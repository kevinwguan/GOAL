"""DEF → final GDS, using the ORFS def2stream.py merge strategy."""

from pathlib import Path
import re
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
    options.lefdef_config.lef_files = [str(tools.tech_lef)] + [
        str(p.resolve()) for p in macro_lefs
    ]
    options.lefdef_config.read_lef_with_def = True
    units = re.search(r"UNITS DISTANCE MICRONS (\d+)\s*;", def_path.read_text())
    if units is None:
        raise ValueError("DEF lacks distance units")
    options.lefdef_config.dbu = 1 / int(units[1])
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
        layout.read(str(path))
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
