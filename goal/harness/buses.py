"""Separate bus-overlay components for supplied masters with open bus stubs."""

from goal.cells.geometry import rect

from .manifest import BUSES, PREFIX
from .ring import transform_box


def strap_corner(component, cell, transform, pdk) -> None:
    """Join each left/bottom LEF band with its corresponding rectilinear elbow."""
    for net in BUSES:
        for layer, box in cell.pins[net]:
            if abs(box[0]) > 0.001:
                continue
            vertical = [
                b
                for band_layer, b in cell.pins[net]
                if band_layer == layer and abs(b[1]) < 0.001
            ]
            if not vertical:
                continue
            # Native corner width/height asymmetry is defined by its LEF.
            offset = cell.height - cell.width
            target = min(
                vertical,
                key=lambda b: abs((b[0] + b[2]) / 2 + offset - (box[1] + box[3]) / 2),
            )
            if abs((target[0] + target[2]) / 2 + offset - (box[1] + box[3]) / 2) > 0.2:
                raise ValueError(f"Unmatched corner bus {net}/{layer}")
            for b in [
                (0, box[1], target[2], box[3]),
                (target[0], 0, target[2], box[3]),
            ]:
                rect(component, pdk, layer, transform_box(b, transform))


def strap_side(component, cell, transform, library, spec) -> None:
    """Overlay unmodified PDK common-bus slices across a side master."""
    base = library.load(spec.reference_filler)
    baseline = min(b[1] for _, b in base.pins[spec.bus_alignment_pin])
    line = min(b[1] for _, b in cell.pins[spec.bus_alignment_pin])
    remaining = round(cell.width)
    if abs(remaining - cell.width) > 1e-6:
        raise ValueError("Bus overlay needs integer-width masters")
    cursor = 0
    for size in spec.fillers:
        count, remaining = divmod(remaining, size)
        for _ in range(count):
            overlay = library.load(PREFIX + f"com_bus_slice_{size}um")
            ref = component << overlay.component
            import klayout.db as kdb

            ref.dcplx_trans = transform * kdb.DCplxTrans(
                1, 0, False, cursor, line - baseline
            )
            cursor += size
    if remaining:
        raise ValueError("Cannot cover cell with common-bus slices")


def bridge_return(component, cell, transform, pdk, geometry):
    """Join inner and outer return bands at one declared filler on each side."""
    bands = cell.pins[geometry["net"]]
    x = cell.width / 2
    ys = sorted(set((b[1] + b[3]) / 2 for layer, b in bands))
    width = geometry["width_um"]
    rect(
        component,
        pdk,
        "met3",
        transform_box(
            (x - width / 2, min(ys) - width / 2, x + width / 2, max(ys) + width / 2),
            transform,
        ),
    )
    for layer, box in bands:
        y = (box[1] + box[3]) / 2
        shapes = [("met3", width), ("native.via3.drawing", geometry["via_size_um"])]
        if layer == "met4":
            shapes.append(("met4", min(0.4, box[3] - box[1])))
        elif layer == "met5":
            shapes += [
                ("met4", geometry["upper_landing_um"]),
                ("met5", geometry["upper_landing_um"]),
                ("native.via4.drawing", geometry["upper_via_size_um"]),
            ]
        else:
            raise ValueError(f"Unsupported bus layer {layer}")
        for drawing, size in shapes:
            rect(
                component,
                pdk,
                drawing,
                transform_box(
                    (x - size / 2, y - size / 2, x + size / 2, y + size / 2), transform
                ),
            )
