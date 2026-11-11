"""Hardened LEF/GDS ingestion; no regeneration of supplied pad geometry."""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import gdsfactory as gf
import klayout.db as kdb

from .sources import declared_cells


@dataclass
class PadCell:
    name: str
    width: float
    height: float
    pins: dict
    component: gf.Component
    gds: Path
    sha256: str
    polygons: dict


class PadLibrary:
    """Read cells only from the explicitly supplied PDK library directory."""

    def __init__(self, pdk, root: Path | None = None):
        self.pdk = pdk
        self.root = (
            root or Path(os.environ["PDK_ROOT"]) / pdk.name / "libs.ref/sky130_fd_io"
        )
        self.text = (self.root / "lef/sky130_ef_io.lef").read_text()
        self.cache = {}
        self.gds_index = {}
        self.layout = kdb.Layout()
        self.sources = {}
        self.declared = set()
        self.empty_sources = set()
        for path in sorted((self.root / "gds").glob("*.gds")):
            layout = kdb.Layout()
            layout.read(str(path))
            self.declared.update(declared_cells(path))
            self.layout.read(str(path))
            self.sources[str(path.relative_to(self.root))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for cell in layout.each_cell():
                if not cell.is_empty() and (
                    cell.name not in self.gds_index or path.stem == cell.name
                ):
                    self.gds_index[cell.name] = path

    def load(self, name: str) -> PadCell:
        if name in self.cache:
            return self.cache[name]
        match = re.search(
            r"^MACRO "
            + re.escape(name)
            + r"\s*$(.*?)^END "
            + re.escape(name)
            + r"\s*$",
            self.text,
            re.M | re.S,
        )
        if not match:
            raise ValueError(f"Missing pad LEF master {name}")
        body = match[1]
        size = re.search(r"\bSIZE ([\d.]+) BY ([\d.]+)", body)
        width, height = map(float, size.groups())
        inverse = {v: k for k, v in self.pdk.data["lef_layers"].items()}
        pins = {}
        polygons = {}
        for pin in re.finditer(
            r"^  PIN (\S+)\s*$(.*?)^  END \1\s*$", body, re.M | re.S
        ):
            pin_name, pin_body = pin.groups()
            shapes = []
            layer = None
            for record in re.finditer(
                r"\bLAYER (\S+)\s*;|\bRECT ([\d.\s-]+);|\bPOLYGON ([\d.\s-]+);|\b(PATH|VIA)\b",
                pin_body,
            ):
                if record[1]:
                    layer = inverse[record[1]]
                elif record[2]:
                    box = tuple(map(float, record[2].split()))
                    if layer is None or len(box) != 4:
                        raise ValueError(f"Malformed pad pin {name}/{pin_name}")
                    shapes.append((layer, box))
                elif record[3]:
                    polygons.setdefault(pin_name, []).append((layer, record[3].split()))
                    # Preserve polygon provenance; ports carry bounding access
                    # frames, while electrical checks use actual GDS metal.
                    xy = list(map(float, record[3].split()))
                    box = (min(xy[::2]), min(xy[1::2]), max(xy[::2]), max(xy[1::2]))
                    shapes.append((layer, box))
                else:
                    raise ValueError(f"Unsupported pad pin primitive {record[4]}")
            pins.setdefault(pin_name, []).extend(shapes)
        path = self.gds_index[name]
        # Library files contain cross-file references. Resolve the complete
        # supplied library before copying the chosen hardened tree unchanged.
        native = self.layout.cell(name)
        reachable = {native.cell_index(), *native.called_cells()}
        empty = [
            self.layout.cell(i).name
            for i in reachable
            if self.layout.cell(i).is_empty()
            and self.layout.cell(i).name not in self.declared
        ]
        if empty:
            raise ValueError(f"Unresolved pad GDS dependencies: {empty}")
        self.empty_sources.update(
            self.layout.cell(i).name
            for i in reachable
            if self.layout.cell(i).is_empty()
        )
        imported = gf.Component()
        imported.copy_tree(native)
        c = gf.Component()
        c << imported
        for pin_name, shapes in pins.items():
            for i, (layer, box) in enumerate(shapes):
                safe = re.sub(r"\W", "_", pin_name)
                x0, y0, x1, y1 = box
                frame_width = max(0.002, round((x1 - x0) / 0.002) * 0.002)
                p = c.add_port(
                    name=f"{safe}_{i}",
                    center=((x0 + x1) / 2, (y0 + y1) / 2),
                    width=frame_width,
                    orientation=90,
                    layer=self.pdk.layer(layer),
                    port_type="electrical",
                )
                inv = p.dcplx_trans.inverted()
                p.info["rect_local"] = [
                    [q.x, q.y]
                    for q in [
                        inv * kdb.DPoint(x, y)
                        for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                    ]
                ]
                p.info["generic_layer"] = layer
                p.info["net"] = safe
                p.info["pad_pin"] = pin_name
                p.info["lef_polygons"] = polygons.get(pin_name, [])
        cell = PadCell(
            name,
            width,
            height,
            pins,
            c,
            path,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            polygons,
        )
        self.cache[name] = cell
        return cell
