"""Code-defined GPIO tie distribution outside the hardened pad masters."""

from goal.cells.geometry import rect

from .ring import transform_box


def distribute(
    component, cell, transform, bindings: dict, geometry: dict, pdk
) -> list[dict]:
    """Connect manifest-bound M2 controls to two declared M3 tie rails."""
    groups = {}
    for pin, net in bindings.items():
        shapes = cell.pins[pin]
        if len(shapes) != 1 or shapes[0][0] != "met2":
            raise ValueError(f"Tie distribution needs one M2 rectangle: {pin}")
        groups.setdefault(net, []).append((pin, shapes[0][1]))
    if len(groups) > len(geometry["rail_y_um"]):
        raise ValueError("Tie geometry lacks rail offsets")
    terminals = []
    for (net, pins), y in zip(sorted(groups.items()), geometry["rail_y_um"]):
        xs = [(b[0] + b[2]) / 2 for _, b in pins]

        def paint(layer, box):
            rect(component, pdk, layer, transform_box(box, transform))

        half = geometry["rail_width_um"] / 2
        paint("met3", (min(xs) - half, y - half, max(xs) + half, y + half))
        for (pin, box), x in zip(pins, xs):
            stem = geometry["stem_width_um"] / 2
            via = geometry["via_size_um"] / 2
            landing = geometry["lower_landing_height_um"] / 2
            paint("met2", (x - stem, y - landing, x + stem, box[3]))
            paint("native.via2.drawing", (x - via, y - via, x + via, y + via))
            terminals.append(
                dict(
                    name=pin,
                    net=net,
                    layer="met2",
                    box=list(transform_box(box, transform)),
                )
            )
    return terminals
