"""Independent geometry checks, including the original conv failure."""

import klayout.db as kdb
import pytest

from goal.cells import diffpair
from goal.lef import write_abstract
from goal.pdk import PDK
from goal.signoff import magic_drc
from goal.signoff.connectivity import Connectivity


@pytest.mark.parametrize("name", ["sky130A", "gf180mcuD"])
def test_straps_and_original_open(tmp_path, name):
    pdk = PDK.load(name)
    plain, strapped = diffpair(pdk), diffpair(pdk, strapped=True)
    a = write_abstract(plain, pdk, tmp_path / "plain", mode="merged")
    b = write_abstract(strapped, pdk, tmp_path / "strapped", mode="merged")
    with pytest.raises(ValueError, match="Disconnected net"):
        Connectivity(tmp_path / "plain/goal_macro.gds", pdk).check(a["terminals"])
    result = Connectivity(tmp_path / "strapped/goal_macro.gds", pdk).check(
        b["terminals"]
    )
    assert result["tail"]["terminals"] == 8
    assert result["drn_p"]["terminals"] == 4
    assert (a["width"], a["height"]) == (b["width"], b["height"])
    for layer in pdk.data["layers"]:
        pa = kdb.Region()
        pb = kdb.Region()
        for polygon in plain.get_polygons(by="tuple").get(pdk.layer(layer), []):
            pa.insert(polygon)
        for polygon in strapped.get_polygons(by="tuple").get(pdk.layer(layer), []):
            pb.insert(polygon)
        assert (pa - pb).is_empty(), layer
        if pdk.layer(layer) not in [pdk.layer(v) for v in ("met1", "met2", "via1")]:
            assert (pa ^ pb).is_empty(), layer
    assert set(b["layers"]["drn_p"]) == {pdk.lef_layer("met2")}


@pytest.mark.magic
@pytest.mark.parametrize("name", ["sky130A", "gf180mcuD"])
def test_strapped_drc(tmp_path, name):
    import os
    import shutil

    if not shutil.which("magic") or not os.getenv("PDK_ROOT"):
        pytest.skip("Magic and PDK_ROOT required")
    from goal.cells import mosfet

    pdk = PDK.load(name)
    for kind in ("nmos", "pmos"):
        out = tmp_path / kind
        write_abstract(mosfet(pdk, kind=kind, strapped=True), pdk, out)
        assert (
            magic_drc(pdk, out / "goal_macro.gds", "goal_macro", out / "magic")["count"]
            == 0
        )
