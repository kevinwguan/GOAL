"""Explicit pad-ring specification and a runnable six-supply Sky130 example."""

from dataclasses import dataclass, field

PREFIX = "sky130_ef_io__"
BUSES = (
    "AMUXBUS_A",
    "AMUXBUS_B",
    "VSSA",
    "VDDA",
    "VSWITCH",
    "VDDIO_Q",
    "VCCHIB",
    "VDDIO",
    "VCCD",
    "VSSIO",
    "VSSD",
    "VSSIO_Q",
)


@dataclass(frozen=True)
class Pad:
    side: str
    order: int
    cell: str
    net: str
    core_pin: str | None = None
    bindings: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RingSpec:
    die: tuple[float, float]
    core: tuple[float, float, float, float]
    pads: tuple[Pad, ...]
    corner: str = PREFIX + "corner_pad"
    fillers: tuple[int, ...] = (20, 10, 5, 1)
    bus_alignment_pin: str = "AMUXBUS_A"
    reference_filler: str = PREFIX + "com_bus_slice_20um"
    strap_buses: bool = True
    bridge_buses: tuple[str, ...] = BUSES
    return_bridge: dict = field(
        default_factory=lambda: dict(
            net="VSSIO",
            width_um=0.5,
            via_size_um=0.2,
            upper_landing_um=1.6,
            upper_via_size_um=0.8,
        )
    )
    tie_geometry: dict = field(
        default_factory=lambda: dict(
            rail_y_um=[-3.0, -5.0],
            rail_width_um=0.4,
            stem_width_um=0.28,
            via_size_um=0.2,
            lower_landing_height_um=0.37,
        )
    )


def sky130_example() -> RingSpec:
    """Illustrative OTA harness. Digital pad is explicitly configured as input.

    GPIO controls bind to its hardened ESD tie outputs. It is not a verified
    electrical/ESD configuration. IN is the digital core signal; PAD remains
    a separate transistor-side package terminal, never a fabricated metal short.
    """
    p = PREFIX
    low = [
        "ANALOG_EN",
        "ANALOG_POL",
        "ANALOG_SEL",
        "DM[2]",
        "DM[1]",
        "DM[0]",
        "ENABLE_H",
        "ENABLE_INP_H",
        "ENABLE_VDDA_H",
        "ENABLE_VDDIO",
        "ENABLE_VSWITCH_H",
        "HLD_OVR",
        "IB_MODE_SEL",
        "INP_DIS",
        "OUT",
        "SLOW",
        "VTRIP_SEL",
    ]
    bindings = {pin: "gpio_tie_lo" for pin in low}
    bindings.update(
        {
            "TIE_LO_ESD": "gpio_tie_lo",
            "TIE_HI_ESD": "gpio_tie_hi",
            "OE_N": "gpio_tie_hi",
            "HLD_H_N": "gpio_tie_hi",
        }
    )
    return RingSpec(
        (1004, 1004),
        (180, 180, 824, 824),
        (
            Pad("north", 0, p + "analog_pad", "inp", "P_CORE"),
            Pad("north", 1, p + "analog_pad", "inn", "P_CORE"),
            Pad("north", 2, p + "analog_pad", "bias", "P_CORE"),
            Pad("north", 3, p + "vdda_hvc_clamped_pad", "VDDA", "VDDA"),
            Pad("east", 0, p + "analog_pad", "out", "P_CORE"),
            Pad("east", 1, p + "vddio_hvc_clamped_pad", "VDDIO", "VDDIO"),
            Pad("east", 2, p + "gpiov2_pad_wrapped", "digital_in", "IN", bindings),
            Pad("south", 0, p + "vssa_hvc_clamped_pad", "VSSA", "VSSA"),
            Pad("south", 1, p + "vssd_lvc_clamped_pad", "VSSD", "VSSD"),
            Pad("west", 0, p + "vccd_lvc_clamped_pad", "VCCD", "VCCD"),
            Pad("west", 1, p + "vssio_hvc_clamped_pad", "VSSIO", "VSSIO"),
        ),
    )
