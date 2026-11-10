import itertools
import os

import networkx as nx
import pytest

from goal.place import Device, cover, graph, parse_spice


def brute_force(g):
    # Independent oracle: enumerate edge subsets forming a spanning linear forest.
    edges = list(g.edges)
    best = len(g)
    for bits in range(1 << len(edges)):
        if len(g) - bits.bit_count() >= best:
            continue
        h = nx.Graph()
        h.add_nodes_from(g)
        h.add_edges_from(e for i, e in enumerate(edges) if bits & (1 << i))
        if max(dict(h.degree()).values(), default=0) <= 2 and nx.is_forest(h):
            best = len(g) - h.number_of_edges()
    return best


def validate(g, result):
    flat = [x for p in result["paths"] for x in p]
    assert len(flat) == len(set(flat)) and set(flat) == set(g)
    for path in result["paths"]:
        assert all(g.has_edge(a, b) for a, b in zip(path, path[1:]))
        devices = [v[2:] for v in path if v.startswith("d:")]
        for a, b in zip(devices, devices[1:]):
            da = g.nodes["d:" + a]["device"]
            db = g.nodes["d:" + b]["device"]
            assert {da.nets[0], da.nets[2]} & {db.nets[0], db.nets[2]}


def test_exact_cover_against_edge_subset_oracle():
    endpoints = [("a", "b"), ("a", "c"), ("b", "c")]
    for chosen in itertools.product(endpoints, repeat=4):
        ds = [
            Device("M" + str(i), "nmos", (a, "gate", b, "bulk"), "nmos", {})
            for i, (a, b) in enumerate(chosen)
        ]
        g = graph(ds)
        result = cover(g)
        validate(g, result)
        assert len(result["paths"]) == brute_force(g)
        assert result == cover(g)
        assert "n:gate" not in g


def test_high_fanout_does_not_prohibit_spanning_path():
    ds = [
        Device("M" + str(i), "nmos", (a, "g", b, "vss"), "nmos", {})
        for i, (a, b) in enumerate([("a", "b"), ("a", "b"), ("a", "c")])
    ]
    g = graph(ds)
    assert g.degree("n:a") == 3
    assert len(cover(g)["paths"]) == 1


def test_large_graph_labels_approximate_fallback():
    ds = [
        Device(str(i), "nmos", ("hub", "g", "out" + str(i), "b"), "nmos", {})
        for i in range(11)
    ]
    g = graph(ds)
    result = cover(g)
    validate(g, result)
    assert not result["minimum_certified"]


def test_tiling_rejects_unimplemented_passives():
    import pytest

    from goal.pdk import PDK
    from goal.place import tile

    with pytest.raises(NotImplementedError, match="passive"):
        tile(parse_spice("R1 a b 1k"), PDK.load("sky130A"))


def test_parse_spice_continuations_and_duplicates():
    import pytest

    devices = parse_spice("M1 a gate b bulk nmos W=2u\n+ L=0.5u nf=2")
    assert devices[0].params["nf"] == "2"
    with pytest.raises(ValueError, match="duplicate"):
        parse_spice("R1 a b 1k\nR1 b c 2k")


@pytest.mark.openroad
def test_ota_hardened_macro(tmp_path):
    import runpy

    from goal.openroad import locate
    from goal.pdk import PDK

    try:
        locate(PDK.load("sky130A"))
    except FileNotFoundError as error:
        if os.getenv("OPENROAD"):
            raise
        pytest.skip(str(error))
    build = runpy.run_path("examples/ota5/build.py")["build"]
    result = build(tmp_path / "ota5")
    assert result["drc_violations"] == 0
    assert result["ordering"]["minimum_certified"]
    assert result["external_nets"] == ["bias", "inn", "inp", "out", "vdd", "vss"]
    if result["magic_drc"]["status"] == "measured":
        assert result["magic_drc"]["count"] == 0
