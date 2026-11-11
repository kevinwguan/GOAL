"""KLayout metal/via extraction with explicit terminal and short checks."""

from pathlib import Path

import klayout.db as kdb


class Connectivity:
    """Extract physical conductors without labels or implicit logical shorts."""

    def __init__(self, gds: str | Path, pdk, top: str | None = None):
        self.layout = kdb.Layout()
        self.layout.read(str(gds))
        self.top = self.layout.cell(top) if top else self.layout.top_cell()
        if self.top is None:
            raise ValueError(f"Missing GDS top {top}")
        self.extractor = kdb.LayoutToNetlist(self.top.name, self.layout.dbu)
        self.layers = {}
        stack = pdk.data["connectivity"]
        for name in stack["conductors"] + [v[1] for v in stack["vias"]]:
            region = kdb.Region(
                self.top.begin_shapes_rec(self.layout.layer(*pdk.layer(name)))
            )
            self.extractor.register(region, name)
            self.layers[name] = region
            self.extractor.connect(region)
        for below, via, above in stack["vias"]:
            self.extractor.connect(self.layers[below], self.layers[via])
            self.extractor.connect(self.layers[via], self.layers[above])
        self.extractor.extract_netlist()

    def check(self, terminals: list[dict]) -> dict:
        """Require complete terminal coverage, one component/net and no shorts.

        A terminal is {net, layer, box, name}. Each rectangle must lie entirely
        on metal. Probe every intersecting polygon, not merely its centre.
        Distinct aliases may not share any physical component.
        """
        found = {}
        counts = {}
        dbu = self.layout.dbu
        for terminal in terminals:
            alias, layer = terminal["net"], terminal["layer"]
            box = kdb.Box(*(round(v / dbu) for v in terminal["box"]))
            aperture = kdb.Region(box)
            metal = self.layers[layer]
            if not (aperture - metal).is_empty():
                raise ValueError(f"Uncovered terminal: {terminal}")
            ids = set()
            for polygon in (metal & aperture).merged().each():
                # Pick an interior point via rectangular decomposition.
                piece = polygon.decompose_trapezoids()[0]
                point = piece.bbox().center()
                net = self.extractor.probe_net(metal, point)
                if net is None:
                    raise ValueError(f"No extracted conductor: {terminal}")
                ids.add(net.cluster_id)
            if len(ids) != 1:
                raise ValueError(f"Terminal spans disconnected conductors: {terminal}")
            found.setdefault(alias, set()).update(ids)
            counts[alias] = counts.get(alias, 0) + 1
        owners = {}
        for alias, ids in found.items():
            if len(ids) != 1:
                raise ValueError(f"Disconnected net {alias}: {len(ids)} components")
            identity = next(iter(ids))
            if identity in owners and owners[identity] != alias:
                raise ValueError(f"Short: {alias} and {owners[identity]}")
            owners[identity] = alias
        return {alias: {"components": 1, "terminals": counts[alias]} for alias in found}


def macro_terminals(
    metadata: dict, placement: tuple, split: bool = False
) -> list[dict]:
    """Move physical finger landings into final-die coordinates."""
    from goal.lef.verilog import connections

    mapping = connections(metadata["pins"], split)
    x, y = placement
    return [
        dict(
            t,
            net=mapping.get(t["name"], t["net"]),
            box=[t["box"][0] + x, t["box"][1] + y, t["box"][2] + x, t["box"][3] + y],
        )
        for t in metadata["terminals"]
    ]
