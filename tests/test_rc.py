import pytest
from goal.rc import RCNet, effective, parse_spef


def net(resistors, sources=("d1", "d2"), ports=("p",)):
    return RCNet("n", 0.0, list(sources), list(ports), resistors)


def test_shared_trunk_is_counted_once():
    result = effective([net([("d1", "j", 2.0), ("d2", "j", 2.0), ("j", "p", 5.0)])])
    assert result["resistance_ohm"] == pytest.approx(6.0)
    assert result["peak_branch_fraction"] == pytest.approx(1.0)


def test_unequal_split_paths_and_zero_ohm_short():
    result = effective(
        [
            net(
                [("d1", "x", 0.0), ("x", "p1", 10.0), ("d2", "p2", 30.0)],
                ports=("p1", "p2"),
            )
        ]
    )
    assert result["resistance_ohm"] == pytest.approx(7.5)
    assert result["peak_branch_fraction"] == pytest.approx(0.75)


def test_disconnected_network_rejected():
    with pytest.raises(ValueError, match="disconnected"):
        effective([net([("d1", "d2", 1.0), ("p", "q", 2.0)])])


def test_spef_units_and_name_map(tmp_path):
    p = tmp_path / "test.spef"
    p.write_text("""*C_UNIT 1 PF
*R_UNIT 1 KOHM
*NAME_MAP
*1 signal
*2 inst
*D_NET *1 0.01
*CONN
*I *2:pin B
*P *1 B
*RES
1 *2:pin *1 0.002
*END
""")
    parsed = parse_spef(p)
    assert parsed["signal"].capacitance == pytest.approx(1e-14)
    assert effective([parsed["signal"]])["resistance_ohm"] == pytest.approx(2.0)
