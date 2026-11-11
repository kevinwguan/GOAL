"""Manifest-driven composition of an abutted hardened pad ring."""

import json
from dataclasses import asdict
from pathlib import Path

import gdsfactory as gf
import klayout.db as kdb

from goal.cells.geometry import write_gds
from goal.lef.ports import port_box

from .library import PadLibrary
from .manifest import BUSES, PREFIX, RingSpec


def transform_box(box: tuple, transform) -> tuple:
    points = [
        transform * kdb.DPoint(x, y)
        for x, y in [
            (box[0], box[1]),
            (box[2], box[1]),
            (box[2], box[3]),
            (box[0], box[3]),
        ]
    ]
    return (
        min(p.x for p in points),
        min(p.y for p in points),
        max(p.x for p in points),
        max(p.y for p in points),
    )


def build_ring(spec: RingSpec, pdk, out: Path) -> dict:
    """Place corners and ordered side cells; fill only the declared die span.

    The common-bus reference line is read from the LEF alignment pin. Rotated
    corner extents determine all four span endpoints. Reject off-grid gaps,
    excess pad widths and ambiguous orders instead of changing the die size.
    """
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    lib = PadLibrary(pdk)
    ring = gf.Component()
    corner = lib.load(spec.corner)
    cw, ch = corner.width, corner.height
    w, h = spec.die
    reference = lib.load(spec.reference_filler)
    baseline = min(b[1] for _, b in reference.pins[spec.bus_alignment_pin])
    corner_line = min(b[1] for _, b in corner.pins[spec.bus_alignment_pin] if b[0] == 0)
    inset = ch - (corner_line - baseline)
    records, terminals, core_ports = [], [], []
    tie_terminals = []
    corner_placements = [
        ("ne", 0, (w - cw, h - ch)),
        ("nw", 90, (ch, h - cw)),
        ("sw", 180, (cw, ch)),
        ("se", 270, (w - ch, cw)),
    ]

    def insert(
        cell, name, angle, origin, bindings, core_pin=None, chip_net=None, side=None
    ):
        ref = ring << cell.component
        ref.drotate(angle)
        ref.dmove(origin)
        transformed = []
        for pin in ref.ports:
            native = pin.info["pad_pin"]
            box = port_box(pin)
            alias = bindings.get(
                native, native if native in BUSES else f"{name}_{native}"
            )
            transformed.append(
                dict(
                    name=f"{name}_{pin.name}",
                    pin=native,
                    net=alias,
                    layer=pin.info["generic_layer"],
                    box=list(box),
                )
            )
        records.append(
            dict(
                name=name,
                cell=cell.name,
                side=side,
                rotation=angle,
                origin=list(origin),
                bindings=bindings,
                ports=transformed,
            )
        )
        # Probe edge landings, not abstract polygons spanning cell interiors.
        for native in BUSES:
            samples = set()
            for layer, box in cell.pins[native]:
                if box[2] - box[0] < 0.05 or box[3] - box[1] < 0.05:
                    continue
                for edge in (0, cell.width):
                    if abs(box[0] - edge) < 0.001 or abs(box[2] - edge) < 0.001:
                        x = (
                            min(0.1, (box[2] - box[0]) / 2)
                            if edge == 0
                            else edge - min(0.1, (box[2] - box[0]) / 2)
                        )
                        samples.add((layer, x, (box[1] + box[3]) / 2))
                if side is None and abs(box[1]) < 0.001:
                    samples.add(
                        (layer, (box[0] + box[2]) / 2, min(0.1, (box[3] - box[1]) / 2))
                    )
            for j, (layer, x, y) in enumerate(sorted(samples)):
                sample = transform_box(
                    (x - 0.01, y - 0.01, x + 0.01, y + 0.01), ref.dcplx_trans
                )
                terminals.append(
                    dict(
                        name=f"{name}_{native}_{j}",
                        net=native,
                        layer=layer,
                        box=list(sample),
                    )
                )
        if core_pin:
            choices = [t for t in transformed if t["pin"] == core_pin]
            if not choices:
                raise ValueError(f"No core pin {cell.name}/{core_pin}")
            # Choose core-facing metal, clip to explicit core rectangle.
            clipped = []
            x0, y0, x1, y1 = spec.core
            for t in choices:
                b = t["box"]
                b = [max(x0, b[0]), max(y0, b[1]), min(x1, b[2]), min(y1, b[3])]
                if b[2] > b[0] and b[3] > b[1]:
                    clipped.append(dict(t, box=b))
            if not clipped:
                raise ValueError(f"Core does not reach {name}/{core_pin}")
            chosen = max(
                clipped,
                key=lambda t: (t["box"][2] - t["box"][0]) * (t["box"][3] - t["box"][1]),
            )
            core_ports.append(dict(chosen, name=chip_net, net=chip_net))
        return ref

    for name, angle, origin in corner_placements:
        ref = insert(corner, name, angle, origin, {})
        if spec.strap_buses:
            from .buses import strap_corner

            strap_corner(ring, corner, ref.dcplx_trans, pdk)
    abutments = {}
    sides = {
        "north": (0, (ch, h - inset), w - cw - ch),
        "east": (270, (w - inset, h - ch), h - cw - ch),
        "south": (180, (w - ch, inset), w - cw - ch),
        "west": (90, (inset, ch), h - cw - ch),
    }
    for side, (angle, start, span) in sides.items():
        entries = sorted(
            [p for p in spec.pads if p.side == side], key=lambda p: p.order
        )
        if len({p.order for p in entries}) != len(entries):
            raise ValueError(f"Duplicate order on {side}")
        cells = [(lib.load(p.cell), p) for p in entries]
        gap = span - sum(c.width for c, p in cells)
        if gap < 0 or abs(gap - round(gap)) > 1e-6:
            raise ValueError(f"Unfillable {side} gap {gap}")
        remaining = round(gap)
        for size in spec.fillers:
            count, remaining = divmod(remaining, size)
            cells += [(lib.load(PREFIX + f"com_bus_slice_{size}um"), None)] * count
        if remaining:
            raise ValueError(f"Fillers cannot cover {side}")
        cursor = 0
        intervals = []
        # Rotate longitudinal and transverse offsets in the native pad frame.
        bridge_count = 0
        for i, (cell, pad) in enumerate(cells):
            line = min(b[1] for _, b in cell.pins[spec.bus_alignment_pin])
            delta = baseline - line
            rotation = kdb.DCplxTrans(1, angle, False, 0, 0)
            offset = rotation * kdb.DPoint(cursor, delta)
            bindings = dict(pad.bindings) if pad else {}
            if pad and pad.core_pin:
                bindings[pad.core_pin] = pad.net
                if pad.core_pin == "P_CORE":
                    bindings["P_PAD"] = pad.net
            ref = insert(
                cell,
                f"{side}_{i}",
                angle,
                (start[0] + offset.x, start[1] + offset.y),
                bindings,
                pad.core_pin if pad else None,
                pad.net if pad else None,
                side,
            )
            if pad and spec.strap_buses:
                from .buses import strap_side

                strap_side(ring, cell, ref.dcplx_trans, lib, spec)
            if not pad and bridge_count < len(spec.bridge_buses) and spec.strap_buses:
                from .buses import bridge_return

                bridge_return(
                    ring,
                    cell,
                    ref.dcplx_trans,
                    pdk,
                    dict(spec.return_bridge, net=spec.bridge_buses[bridge_count]),
                )
                bridge_count += 1
            if pad and pad.bindings:
                from .ties import distribute

                tie_terminals.extend(
                    distribute(
                        ring,
                        cell,
                        ref.dcplx_trans,
                        pad.bindings,
                        spec.tie_geometry,
                        pdk,
                    )
                )
            intervals.append([cursor, cursor + cell.width])
            cursor += cell.width
        abutments[side] = dict(
            span_um=span,
            intervals_um=intervals,
            gaps_um=[intervals[0][0]]
            + [b[0] - a[1] for a, b in zip(intervals, intervals[1:])]
            + [span - cursor],
        )
    for p in spec.pads:
        if p.side not in sides:
            raise ValueError(f"Unknown manifest side {p.side}")
    write_gds(ring, out / "pad_ring.gds")
    exported = kdb.Layout()
    exported.read(str(out / "pad_ring.gds"))
    exported.top_cell().name = "goal_pad_ring"
    exported.write(str(out / "pad_ring.gds"))
    metadata = dict(
        spec=asdict(spec),
        top="goal_pad_ring",
        instances=records,
        core_ports=core_ports,
        bus_terminals=terminals,
        tie_terminals=tie_terminals,
        abutments=abutments,
        sources={
            name: dict(gds=str(cell.gds.relative_to(lib.root)), sha256=cell.sha256)
            for name, cell in lib.cache.items()
        },
    )
    (out / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (out / "chip_aliases.json").write_text(
        json.dumps({t["name"]: t["net"] for r in records for t in r["ports"]}, indent=2)
        + "\n"
    )
    from .abstract import write_core_abstract

    write_core_abstract(metadata, pdk, out)
    return metadata
