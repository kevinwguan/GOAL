from collections import Counter
from pathlib import Path
import re
import gdsfactory as gf
import klayout.db as kdb
import pytest
from goal.cells import diffpair
from goal.cells.geometry import port, rect
from goal.lef import write_abstract
from goal.lef.ports import port_box
from goal.pdk import PDK


def parse_lef(path):
    """Small independent structural parser for emitted and oracle LEF."""
    pins, name, layer = {}, None, None
    for line in path.read_text().splitlines():
        words = line.split()
        if not words:
            continue
        if words[0] == "PIN":
            name = words[1]
            pins[name] = []
        elif words[0] == "END" and len(words) > 1 and words[1] == name:
            name = None
        elif words[0] == "LAYER":
            layer = words[1]
        elif words[0] == "RECT" and name is not None:
            pins[name].append((layer, tuple(map(float, words[1:5]))))
    return pins


@pytest.mark.parametrize(
    "mode,oracle,count", [("merged", "conv", 6), ("per_finger", "cap", 19)]
)
def test_roundtrip(tmp_path, mode, oracle, count):
    pdk = PDK.load("sky130A")
    c = diffpair(pdk)
    meta = write_abstract(c, pdk, tmp_path, mode, "pair")
    parsed = parse_lef(tmp_path / "pair.lef")
    reference = parse_lef(Path(f"capillary_experiment/diffpair_{oracle}.lef"))
    assert len(parsed) == len(reference) == count
    assert set(layer for shapes in parsed.values() for layer, _ in shapes) == {"met1"}
    assert sum(map(len, parsed.values())) == 19
    # Oracle merged pins use solid bounding rectangles; retain separate access
    # rectangles here, as required by the clean-room abstraction contract.
    assert sum(map(len, reference.values())) == (6 if mode == "merged" else 19)
    assert Counter(meta["pins"].values()) == (
        Counter(dict(bulk=1, drn_p=1, drn_n=1, gate_p=1, gate_n=1, tail=1))
        if mode == "merged"
        else Counter(dict(bulk=1, drn_p=4, drn_n=4, gate_p=1, gate_n=1, tail=8))
    )
    for pin, shapes in parsed.items():
        assert [list(b) for _, b in shapes] == [
            [round(v, 3) for v in b] for b in meta["rectangles"][pin]
        ]
    layout = kdb.Layout()
    layout.read(str(tmp_path / "pair.gds"))
    assert layout.top_cell().name == "pair"
    assert not layout.top_cell().is_empty()


@pytest.mark.parametrize(
    "angle,mirror", [(90, False), (180, False), (0, True), (90, True), (180, True)]
)
def test_transformed_access_rectangle(tmp_path, angle, mirror):
    pdk = PDK.load("sky130A")
    cell, parent = gf.Component(), gf.Component()
    box = (1, 2, 5, 3)
    rect(cell, pdk, "met1", box)
    original = port(cell, pdk, "P", "net", box)
    ref = parent << cell
    ref.dcplx_trans = kdb.DCplxTrans(1, angle, mirror, 11, 13)
    parent.add_port("P", port=ref.ports["P"])
    expected = ref.dcplx_trans * kdb.DBox(*box)
    got = port_box(parent.ports["P"])
    assert got == pytest.approx(
        (expected.left, expected.bottom, expected.right, expected.top)
    )
    meta = write_abstract(parent, pdk, tmp_path, macro_name="transformed")
    assert meta["rectangles"]["P"][0] == pytest.approx(
        [0, 0, parent.dxsize, parent.dysize]
    )


@pytest.mark.openroad
@pytest.mark.parametrize("mode", ["merged", "per_finger"])
def test_openroad_read_lef(tmp_path, mode):
    import os
    import shutil
    import subprocess

    binary = os.getenv("OPENROAD") or shutil.which("openroad")
    platform = os.getenv("PLATFORM_DIR")
    if not platform and os.getenv("ORFS_DIR"):
        platform = str(Path(os.environ["ORFS_DIR"]) / "flow/platforms/sky130hs")
    if not binary or not platform:
        pytest.skip("OPENROAD and PLATFORM_DIR/ORFS_DIR required")
    tech = Path(platform) / "lef/sky130_fd_sc_hs.tlef"
    pdk = PDK.load("sky130A")
    write_abstract(diffpair(pdk), pdk, tmp_path, mode, "pair", tech)
    script = tmp_path / "read.tcl"
    script.write_text(
        f"read_lef {{{tech}}}\nread_lef {{{tmp_path / 'pair.lef'}}}\nexit\n"
    )
    proc = subprocess.run(
        [binary, "-no_init", "-exit", str(script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not re.search(r"\[(WARNING|ERROR)", proc.stdout + proc.stderr)
