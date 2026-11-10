"""Well-group tiling ported from reproduction/placement.py."""

import math
from .spice import micron
from .chains import graph, cover, ordered_devices


def tile(devices: list, pdk, aspect: float = 1.0, name: str = "placed_block") -> tuple:
    import gdsfactory as gf
    from goal.cells import mosfet, ring

    if not devices:
        raise ValueError("No devices to tile")
    if any(d.kind not in ("nmos", "pmos") for d in devices):
        raise NotImplementedError(
            "Physical tiling supports MOS only; passive PCells are not implemented"
        )
    if aspect <= 0:
        raise ValueError("aspect must be positive")
    result = cover(graph(devices))
    ordered = ordered_devices(devices, result)
    c = gf.Component()
    xoffset = 0.0
    groups = []
    for kind in ("nmos", "pmos"):
        ds = [d for d in ordered if d.kind == kind]
        if not ds:
            continue
        group = gf.Component()
        cells = []
        for d in ds:
            cells.append(
                mosfet(
                    pdk,
                    kind=kind,
                    fingers=int(d.params.get("nf", "1")),
                    width=micron(d.params.get("w"), 2.0),
                    length=micron(d.params.get("l"), 0.5),
                    drain=d.nets[0],
                    gate=d.nets[1],
                    source=d.nets[2],
                    bulk=d.nets[3],
                    name=None,
                )
            )
        gap = pdk.rule("well_spacing") + 2 * pdk.rule("well_overlap_p")
        cw = max((x.dxsize for x in cells)) + gap
        ch = max((x.dysize for x in cells)) + gap
        cols = min(
            range(1, len(ds) + 1),
            key=lambda n: (
                abs(math.log(n * cw / (math.ceil(len(ds) / n) * ch) / aspect)),
                n,
            ),
        )
        for i, (d, cell) in enumerate(zip(ds, cells)):
            ref = group << cell
            ref.dmove((i % cols * cw - ref.dxmin, i // cols * ch - ref.dymin))
            for p in ref.ports:
                group.add_port(name=d.name + "_" + p.name, port=p)
        bulks = {d.nets[3] for d in ds}
        if len(bulks) != 1:
            raise ValueError("mixed bulk group requires separate well domains")
        margin = gap + 1.0
        ring(
            group,
            pdk,
            (-margin, -margin, group.dxmax + margin, group.dymax + margin),
            kind,
            next(iter(bulks)),
        )
        if kind == "pmos":
            from goal.cells.geometry import rect

            e = pdk.rule("well_overlap_p")
            rect(
                group,
                pdk,
                "nwell",
                (group.dxmin - e, group.dymin - e, group.dxmax + e, group.dymax + e),
            )
        ref = c << group
        ref.dmove((xoffset - ref.dxmin, -ref.dymin))
        for p in ref.ports:
            c.add_port(name=kind + "_" + p.name, port=p)
        groups.append(
            dict(
                kind=kind,
                order=[d.name for d in ds],
                columns=cols,
                width=ref.dxsize,
                height=ref.dysize,
            )
        )
        xoffset = ref.dxmax + gap
    result.update(
        groups=groups,
        passive_order=[d.name for d in ordered if d.kind not in ("nmos", "pmos")],
        physical_diffusion_sharing=False,
        requested_group_aspect=aspect,
        actual_block_aspect=c.dxsize / c.dysize,
    )
    return (c, result)
