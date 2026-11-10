"""Independent SPEF reader and boundary-shorted nodal resistance solver."""

from dataclasses import dataclass, field
from pathlib import Path
import re
import numpy as np


@dataclass
class RCNet:
    name: str
    capacitance: float
    instances: list = field(default_factory=list)
    ports: list = field(default_factory=list)
    resistors: list = field(default_factory=list)


def parse_spef(path: str | Path) -> dict[str, RCNet]:
    """Read net boundaries, lumped capacitance and resistor edges in SI units."""
    names = {}
    nets = {}
    state = None
    net = None
    cscale = rscale = 1.0
    factors = {"F": 1.0, "PF": 1e-12, "FF": 1e-15, "OHM": 1.0, "KOHM": 1000.0}

    def resolve(token):
        m = re.match("(\\*\\d+)(.*)", token)
        return names.get(m[1], m[1]) + m[2] if m else token

    for raw in Path(path).read_text().splitlines():
        words = raw.split()
        if not words:
            continue
        head = words[0]
        if head == "*C_UNIT":
            cscale = float(words[1]) * factors[words[2].upper()]
        elif head == "*R_UNIT":
            rscale = float(words[1]) * factors[words[2].upper()]
        elif head == "*NAME_MAP":
            state = "names"
        elif head == "*D_NET":
            net = RCNet(resolve(words[1]), float(words[2]) * cscale)
            nets[net.name] = net
            state = None
        elif head in ("*CONN", "*CAP", "*RES"):
            state = head
        elif head == "*END":
            state = None
            net = None
        elif state == "names" and re.fullmatch("\\*\\d+", head):
            names[head] = words[1]
        elif net is not None and state == "*CONN":
            if head == "*I":
                net.instances.append(resolve(words[1]))
            elif head == "*P":
                net.ports.append(resolve(words[1]))
        elif net is not None and state == "*RES" and head.isdigit():
            net.resistors.append(
                (resolve(words[1]), resolve(words[2]), float(words[3]) * rscale)
            )
    return nets


class Union:
    def __init__(self):
        self.parent = {}

    def find(self, a):
        self.parent.setdefault(a, a)
        if self.parent[a] != a:
            self.parent[a] = self.find(self.parent[a])
        return self.parent[a]

    def join(self, a, b):
        (a, b) = (self.find(a), self.find(b))
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def effective(nets: list[RCNet]) -> dict:
    """Short all device terminals to D, all external ports to P; inject 1A.

    Zero-ohm resistors are unioned exactly. Positive conductances form the
    reduced Laplacian. Peak branch current is for this equipotential-boundary
    model; it does not assume equal transistor-finger currents.
    """
    resistors = [r for n in nets for r in n.resistors]
    sources = [v for n in nets for v in n.instances]
    sinks = [v for n in nets for v in n.ports]
    if not sources or not sinks:
        raise ValueError("missing boundary terminals")
    uf = Union()
    for a, b, r in resistors:
        if r < 0:
            raise ValueError("negative resistance")
        uf.find(a)
        uf.find(b)
        if r == 0:
            uf.join(a, b)
    for v in sources[1:]:
        uf.join(sources[0], v)
    for v in sinks[1:]:
        uf.join(sinks[0], v)
    (source, sink) = (uf.find(sources[0]), uf.find(sinks[0]))
    if source == sink:
        return dict(resistance_ohm=0.0, peak_branch_fraction=None)
    edges = [
        (uf.find(a), uf.find(b), r)
        for (a, b, r) in resistors
        if r > 0 and uf.find(a) != uf.find(b)
    ]
    adjacency = {}
    for a, b, r in edges:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    seen = {source}
    pending = [source]
    while pending:
        for v in adjacency.get(pending.pop(), []):
            if v not in seen:
                seen.add(v)
                pending.append(v)
    if sink not in seen:
        raise ValueError("disconnected RC network")
    unknown = sorted(seen - {sink})
    index = {v: i for (i, v) in enumerate(unknown)}
    matrix = np.zeros((len(unknown), len(unknown)))
    current = np.zeros(len(unknown))
    current[index[source]] = 1.0
    for a, b, r in edges:
        if a not in seen:
            continue
        g = 1 / r
        if a != sink:
            matrix[index[a], index[a]] += g
        if b != sink:
            matrix[index[b], index[b]] += g
        if a != sink and b != sink:
            matrix[index[a], index[b]] -= g
            matrix[index[b], index[a]] -= g
    solution = np.linalg.solve(matrix, current)
    voltage = {v: solution[i] for (v, i) in index.items()} | {sink: 0.0}
    branch = [abs(voltage[a] - voltage[b]) / r for (a, b, r) in edges if a in seen]
    return dict(
        resistance_ohm=float(voltage[source]),
        peak_branch_fraction=float(max(branch, default=0.0)),
        nodes=len(seen),
        resistor_count=len(resistors),
    )
