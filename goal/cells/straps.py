"""Optional physical source/drain shorts; the unstrapped device is unchanged."""

from .geometry import MARGIN, port, rect, snap


def add_straps(component, pdk, terminals: dict, width: float) -> None:
    """M1 stems reach separated M2 rails through individual via1 cuts.

    Rails stay inside the existing guard-ring footprint. M2 crosses the M1
    bulk ring without connecting to it. Original terminal ports are retained
    for connectivity checking but hidden from the merged abstract.
    """
    cut = pdk.rule("via_size")
    landing = snap(max(cut + 2 * pdk.rule("metal_surround") + 2 * MARGIN, 0.5))
    stem = snap(cut + 2 * pdk.rule("metal_surround") + 2 * MARGIN)
    for index, (net, boxes) in enumerate(terminals.items()):
        y = snap(-landing if index == 0 else width - landing / 2)
        xs = [(b[0] + b[2]) / 2 for b in boxes]
        rail = (
            min(xs) - landing / 2,
            y - landing / 2,
            max(xs) + landing / 2,
            y + landing / 2,
        )
        rect(component, pdk, "met2", rail)
        for x, box in zip(xs, boxes):
            rect(
                component,
                pdk,
                "met1",
                (
                    x - stem / 2,
                    min(y - stem / 2, box[1]),
                    x + stem / 2,
                    max(y + stem / 2, box[3]),
                ),
            )
            rect(
                component,
                pdk,
                "via1",
                (x - cut / 2, y - cut / 2, x + cut / 2, y + cut / 2),
            )
        for pin in component.ports:
            if pin.info["net"] == net:
                pin.info["terminal_only"] = True
        port(component, pdk, net + "_strap", net, rail, layer="met2")
