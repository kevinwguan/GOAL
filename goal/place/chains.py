"""Bounded exact path covers, ported from reproduction/placement.py."""

from functools import lru_cache
import networkx as nx


def graph(devices: list) -> nx.Graph:
    g = nx.Graph()
    for d in sorted(devices, key=lambda d: d.name):
        if d.kind not in ("nmos", "pmos"):
            continue
        node = "d:" + d.name
        g.add_node(node, kind="device", device=d)
        for net in (d.nets[0], d.nets[2]):
            g.add_node("n:" + net, kind="net")
            g.add_edge(node, "n:" + net)
    return g


def canonical(path):
    path = tuple(path)
    return min(path, path[::-1])


def cover(g: nx.Graph, exact_limit: int = 20) -> dict:
    all_paths = []
    methods = []
    for nodes in sorted(nx.connected_components(g), key=lambda x: sorted(x)):
        sub = g.subgraph(nodes)
        vertices = sorted(nodes)
        if max(dict(sub.degree()).values(), default=0) <= 2:
            start = min(vertices, key=lambda v: (sub.degree(v) != 1, v))
            used = set()
            path = []
            v = start
            while v is not None:
                used.add(v)
                path.append(v)
                v = next((x for x in sorted(sub[v]) if x not in used), None)
            all_paths.append(canonical(path))
            methods.append("linear-degree-2")
        elif len(vertices) <= exact_limit:
            index = {v: i for (i, v) in enumerate(vertices)}
            candidates = {}

            def visit(path, mask):
                value = canonical(path)
                if mask not in candidates or value < candidates[mask]:
                    candidates[mask] = value
                for v in sorted(sub[path[-1]]):
                    bit = 1 << index[v]
                    if not mask & bit:
                        visit(path + [v], mask | bit)

            for v in vertices:
                visit([v], 1 << index[v])
            by_vertex = {i: [] for i in range(len(vertices))}
            for mask, path in candidates.items():
                for i in by_vertex:
                    if mask & 1 << i:
                        by_vertex[i].append((mask, path))
            for items in by_vertex.values():
                items.sort(key=lambda x: (-x[0].bit_count(), x[1]))

            @lru_cache(None)
            def solve(remaining):
                if not remaining:
                    return ()
                i = (remaining & -remaining).bit_length() - 1
                best = None
                for mask, path in by_vertex[i]:
                    if mask & remaining != mask:
                        continue
                    result = tuple(sorted((path,) + solve(remaining ^ mask)))
                    if best is None or (len(result), result) < (len(best), best):
                        best = result
                    if len(best) == 1:
                        break
                return best

            all_paths.extend(solve((1 << len(vertices)) - 1))
            methods.append("exact-subset-dp")
        else:
            remaining = set(vertices)
            while remaining:
                v = min(
                    remaining, key=lambda x: (sum((y in remaining for y in sub[x])), x)
                )
                path = []
                while v is not None:
                    path.append(v)
                    remaining.remove(v)
                    v = next((x for x in sorted(sub[v]) if x in remaining), None)
                all_paths.append(canonical(path))
            methods.append("greedy-nonminimal-fallback")
    return dict(
        paths=[list(p) for p in sorted(all_paths)],
        methods=methods,
        minimum_certified=all((m != "greedy-nonminimal-fallback" for m in methods)),
    )


def ordered_devices(devices, result):
    names = [v[2:] for p in result["paths"] for v in p if v.startswith("d:")]
    by_name = {d.name: d for d in devices}
    return [by_name[n] for n in names] + sorted(
        (d for d in devices if d.kind not in ("nmos", "pmos")),
        key=lambda d: (d.kind, d.name),
    )
