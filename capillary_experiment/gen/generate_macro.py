#!/usr/bin/env python3
"""Generate LEF + Verilog for a 4-finger NMOS diff pair in three modes.

Outputs three sets of files (mode ∈ {conv, cap, cap_split}) into the parent dir:
  diffpair_${mode}.lef        macro LEF
  diffpair_${mode}_bb.v       Verilog black-box declaration
  top_${mode}.v               top-level wrapper
  placed_${mode}.def          placed DEF (macro + I/O pins + net connectivity)

Modes:
  conv       — collapsed-pin LEF (one merged pin per net), single I/O port per
               logical net. Baseline.
  cap        — per-finger LEF, all finger pins shorted back to a single I/O
               port in the top-level netlist (one destination per logical
               net). Isolates LEF-pin granularity as the only variable versus
               conv.
  cap_split  — per-finger LEF, each finger pin routed to its OWN I/O port on
               the die boundary (N destinations per logical net). This is the
               realistic capillary-routing scenario: distributed destinations
               force the router to build N independent paths with no shared
               trunk.

The three DEFs share the same macro footprint and placement; only the I/O
pin count and the net-membership lists differ. Comparing conv → cap → cap_split
separates two effects: (1) pin granularity alone, and (2) pin granularity
combined with distributed endpoints.
"""

from pathlib import Path
import textwrap

OUT = Path(__file__).resolve().parent.parent

# ── Macro geometry (Sky130 met1 rules) ──────────────────────────────────────
MACRO_W = 8.0   # µm
MACRO_H = 6.0   # µm
NFINGERS = 4
PIN_W = 0.14    # met1 min width
PIN_H = 0.40    # met1 pin height (arbitrary, well above min-area)

# Finger x-offsets within each transistor half
#   Left transistor (P-side): x centres at 0.5, 1.5, 2.5, 3.5
#   Right transistor (N-side): x centres at 4.5, 5.5, 6.5, 7.5
LEFT_OFFSETS  = [0.5 + i * 1.0 for i in range(NFINGERS)]
RIGHT_OFFSETS = [4.5 + i * 1.0 for i in range(NFINGERS)]

# Pin y-bands
DRN_Y0, DRN_Y1 = 5.2, 5.2 + PIN_H   # drains at top
SRC_Y0, SRC_Y1 = 0.4, 0.4 + PIN_H    # sources at bottom (tail)
GATE_Y0, GATE_Y1 = 2.8, 2.8 + PIN_H  # gates in the middle

# Gate and bulk positions (met1)
GATE_P_X0, GATE_P_X1 = 0.0, PIN_W
GATE_N_X0, GATE_N_X1 = MACRO_W - PIN_W, MACRO_W
BULK_X0, BULK_X1 = 3.5, 4.5
BULK_Y0, BULK_Y1 = 2.8, 2.8 + PIN_H


def _rect(cx, y0, y1):
    """Return (x0, y0, x1, y1) centred on cx with met1 min-width."""
    hw = PIN_W / 2
    return (round(cx - hw, 3), round(y0, 3), round(cx + hw, 3), round(y1, 3))


def _pin_stanza(name, direction, rects, use="SIGNAL"):
    """Emit a LEF PIN block with one or more RECT entries on met1."""
    lines = [f"  PIN {name}",
             f"    DIRECTION {direction} ;",
             f"    USE {use} ;",
             f"    PORT"]
    for r in rects:
        lines.append(f"      LAYER met1 ;")
        lines.append(f"        RECT {r[0]:.3f} {r[1]:.3f} {r[2]:.3f} {r[3]:.3f} ;")
    lines += [f"    END", f"  END {name}"]
    return "\n".join(lines)


def _obs_stanza():
    """Obstruction covering the internal active area (met1, li1)."""
    # Block the interior so the router can only enter via the exposed pins
    return textwrap.dedent(f"""\
      OBS
        LAYER met1 ;
          RECT 0.200 1.000 7.800 5.000 ;
      END""")


# ── Finger rectangles ───────────────────────────────────────────────────────
drn_p_rects = [_rect(cx, DRN_Y0, DRN_Y1) for cx in LEFT_OFFSETS]
drn_n_rects = [_rect(cx, DRN_Y0, DRN_Y1) for cx in RIGHT_OFFSETS]
src_p_rects = [_rect(cx, SRC_Y0, SRC_Y1) for cx in LEFT_OFFSETS]
src_n_rects = [_rect(cx, SRC_Y0, SRC_Y1) for cx in RIGHT_OFFSETS]


# ═══════════════════════════════════════════════════════════════════════════
#  CONVENTIONAL (collapsed-pin) mode
# ═══════════════════════════════════════════════════════════════════════════
def _merged_rect(rects):
    """Union bounding box of a list of (x0,y0,x1,y1)."""
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


conv_pins = []
conv_pins.append(_pin_stanza("gate_p", "INPUT",
                             [(GATE_P_X0, GATE_Y0, GATE_P_X1, GATE_Y1)]))
conv_pins.append(_pin_stanza("gate_n", "INPUT",
                             [(GATE_N_X0, GATE_Y0, GATE_N_X1, GATE_Y1)]))
conv_pins.append(_pin_stanza("drn_p", "OUTPUT", [_merged_rect(drn_p_rects)]))
conv_pins.append(_pin_stanza("drn_n", "OUTPUT", [_merged_rect(drn_n_rects)]))
conv_pins.append(_pin_stanza("tail", "INOUT",
                             [_merged_rect(src_p_rects + src_n_rects)]))
conv_pins.append(_pin_stanza("bulk", "INOUT",
                             [(BULK_X0, BULK_Y0, BULK_X1, BULK_Y1)]))

conv_port_names = ["gate_p", "gate_n", "drn_p", "drn_n", "tail", "bulk"]

# ═══════════════════════════════════════════════════════════════════════════
#  CAPILLARY (per-finger) mode — shared across cap and cap_split LEFs
# ═══════════════════════════════════════════════════════════════════════════
cap_pins = []
cap_pins.append(_pin_stanza("gate_p", "INPUT",
                            [(GATE_P_X0, GATE_Y0, GATE_P_X1, GATE_Y1)]))
cap_pins.append(_pin_stanza("gate_n", "INPUT",
                            [(GATE_N_X0, GATE_Y0, GATE_N_X1, GATE_Y1)]))
for i, r in enumerate(drn_p_rects):
    cap_pins.append(_pin_stanza(f"drn_p_{i}", "OUTPUT", [r]))
for i, r in enumerate(drn_n_rects):
    cap_pins.append(_pin_stanza(f"drn_n_{i}", "OUTPUT", [r]))
for i, r in enumerate(src_p_rects):
    cap_pins.append(_pin_stanza(f"tail_{i}", "INOUT", [r]))
for i, r in enumerate(src_n_rects):
    cap_pins.append(_pin_stanza(f"tail_{i + NFINGERS}", "INOUT", [r]))
cap_pins.append(_pin_stanza("bulk", "INOUT",
                            [(BULK_X0, BULK_Y0, BULK_X1, BULK_Y1)]))

cap_port_names = (["gate_p", "gate_n"]
                  + [f"drn_p_{i}" for i in range(NFINGERS)]
                  + [f"drn_n_{i}" for i in range(NFINGERS)]
                  + [f"tail_{i}" for i in range(2 * NFINGERS)]
                  + ["bulk"])


# ── Write LEF ───────────────────────────────────────────────────────────────
def write_lef(path, pin_stanzas):
    header = textwrap.dedent(f"""\
        VERSION 5.7 ;
        NOWIREEXTENSIONATPIN ON ;
        DIVIDERCHAR "/" ;
        BUSBITCHARS "[]" ;
        MACRO diffpair_nmos_4f
          CLASS BLOCK ;
          FOREIGN diffpair_nmos_4f ;
          ORIGIN 0.000 0.000 ;
          SIZE {MACRO_W:.3f} BY {MACRO_H:.3f} ;
        """)
    obs = _obs_stanza()
    footer = "END diffpair_nmos_4f\nEND LIBRARY\n"
    with open(path, "w") as f:
        f.write(header)
        for p in pin_stanzas:
            f.write(p + "\n")
        f.write(obs + "\n")
        f.write(footer)
    print(f"  wrote {path}")


# ── Write Verilog blackbox ──────────────────────────────────────────────────
def write_bb(path, port_names):
    """Write blackbox Verilog for the macro."""
    ports = ", ".join(port_names)
    decls = []
    for p in port_names:
        if p.startswith("gate"):
            decls.append(f"  input  {p};")
        elif p.startswith("drn"):
            decls.append(f"  output {p};")
        else:
            decls.append(f"  inout  {p};")
    with open(path, "w") as f:
        # No (* blackbox *) — OpenROAD resolves from the LEF macro name match
        f.write(f"module diffpair_nmos_4f ({ports});\n")
        f.write("\n".join(decls) + "\n")
        f.write("endmodule\n")
    print(f"  wrote {path}")


def _top_net_for(macro_pin, split):
    """Map a macro pin name to its top-level net.

    split=False: all fingers of a logical net share one top-level net.
    split=True : each finger gets its own top-level net (name == macro pin).
    """
    if macro_pin.startswith("gate") or macro_pin == "bulk":
        return macro_pin
    if not split:
        if macro_pin.startswith("drn_p"):
            return "drn_p"
        if macro_pin.startswith("drn_n"):
            return "drn_n"
        if macro_pin.startswith("tail"):
            return "tail"
    return macro_pin


def _top_ports_for(port_names, split):
    """Return the ordered list of distinct top-level net names."""
    seen = []
    for p in port_names:
        n = _top_net_for(p, split)
        if n not in seen:
            seen.append(n)
    return seen


def _direction_of(name):
    if name.startswith("gate"):
        return "INPUT"
    if name.startswith("drn"):
        return "OUTPUT"
    return "INOUT"


# ── Write top-level Verilog ─────────────────────────────────────────────────
def write_top(path, port_names, split):
    """The top module exposes one port per distinct top-level net.

    split=False: 6 ports (gate_p, gate_n, drn_p, drn_n, tail, bulk); finger
                 pins are shorted back to the merged net.
    split=True : 2 + 4 + 4 + 8 + 1 = 19 ports; each finger pin maps to its
                 own top-level port (no external short).
    """
    top_ports = _top_ports_for(port_names, split)
    port_str = ", ".join(top_ports)
    inputs  = [p for p in top_ports if _direction_of(p) == "INPUT"]
    outputs = [p for p in top_ports if _direction_of(p) == "OUTPUT"]
    inouts  = [p for p in top_ports if _direction_of(p) == "INOUT"]

    inst_conns = [f"    .{p}({_top_net_for(p, split)})" for p in port_names]

    with open(path, "w") as f:
        f.write(f"module top ({port_str});\n")
        if inputs:
            f.write(f"  input  {', '.join(inputs)};\n")
        if outputs:
            f.write(f"  output {', '.join(outputs)};\n")
        if inouts:
            f.write(f"  inout  {', '.join(inouts)};\n")
        f.write("\n")
        f.write(f"  diffpair_nmos_4f u0 (\n")
        f.write(",\n".join(inst_conns) + "\n")
        f.write(f"  );\n")
        f.write(f"endmodule\n")
    print(f"  wrote {path}")


# ── Write DEF ───────────────────────────────────────────────────────────────
# Macro placement (same for all modes).
MACRO_X, MACRO_Y = 21000, 22000  # nm (centre-ish in 50×50 µm die)
DB_UNITS = 1000  # DEF DATABASE UNITS (nm per µm)

# I/O pin positions for the shared (non-split) layout: one port per logical net.
# Coordinates in nm on the 50 × 50 µm die boundary.
IO_PINS_SHARED = {
    "gate_p": (0,     22000, "met2"),
    "gate_n": (50000, 22000, "met2"),
    "drn_p":  (15000, 50000, "met2"),
    "drn_n":  (35000, 50000, "met2"),
    "tail":   (25000, 0,     "met2"),
    "bulk":   (25000, 50000, "met2"),
}

# I/O pin positions for cap_split: one port per finger, spread along the
# appropriate die edge. Chosen so each per-finger destination sits far enough
# apart that the router cannot merge paths into a shared trunk, while keeping
# the per-finger path length comparable to the conv baseline (~22 µm).
#   drn_p_0..3 → top edge, left half  (x = 5, 10, 15, 20 µm)
#   drn_n_0..3 → top edge, right half (x = 30, 35, 40, 45 µm)
#   tail_0..7  → bottom edge, spread  (x = 3, 9, 15, 21, 29, 35, 41, 47 µm)
IO_PINS_SPLIT = dict(IO_PINS_SHARED)
# Overwrite drn_p / drn_n / tail with per-finger ports; keep gate_*, bulk.
for key in ("drn_p", "drn_n", "tail"):
    IO_PINS_SPLIT.pop(key)
for i, x in enumerate((5000, 10000, 15000, 20000)):
    IO_PINS_SPLIT[f"drn_p_{i}"] = (x, 50000, "met2")
for i, x in enumerate((30000, 35000, 40000, 45000)):
    IO_PINS_SPLIT[f"drn_n_{i}"] = (x, 50000, "met2")
for i, x in enumerate((3000, 9000, 15000, 21000, 29000, 35000, 41000, 47000)):
    IO_PINS_SPLIT[f"tail_{i}"]  = (x, 0, "met2")


def write_def(path, port_names, split):
    """Write a DEF with the macro placed, I/O pins, and net connectivity.

    split=False: single I/O port per logical net (IO_PINS_SHARED).
    split=True : one I/O port per finger pin (IO_PINS_SPLIT).
    """
    io_pins = IO_PINS_SPLIT if split else IO_PINS_SHARED
    top_ports = _top_ports_for(port_names, split)

    lines = [
        "VERSION 5.8 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        "DESIGN top ;",
        f"UNITS DISTANCE MICRONS {DB_UNITS} ;",
        "DIEAREA ( 0 0 ) ( 50000 50000 ) ;",
        "",
        "COMPONENTS 1 ;",
        f"  - u0 diffpair_nmos_4f + PLACED ( {MACRO_X} {MACRO_Y} ) N ;",
        "END COMPONENTS",
        "",
    ]

    lines.append(f"PINS {len(top_ports)} ;")
    for pname in top_ports:
        x, y, layer = io_pins[pname]
        lines.append(
            f"  - {pname} + NET {pname} + DIRECTION {_direction_of(pname)}"
            f" + FIXED ( {x} {y} ) N"
            f" + LAYER {layer} ( -140 -500 ) ( 140 500 ) ;")
    lines.append("END PINS")
    lines.append("")

    # Build net → [macro pins] from the mapping.
    net_to_macropins = {n: [] for n in top_ports}
    for pname in port_names:
        net_to_macropins[_top_net_for(pname, split)].append(pname)

    lines.append(f"NETS {len(top_ports)} ;")
    for net_name in top_ports:
        conn_parts = [f"( PIN {net_name} )"]
        for mp in net_to_macropins[net_name]:
            conn_parts.append(f"( u0 {mp} )")
        lines.append(f"  - {net_name} " + " ".join(conn_parts) + " ;")
    lines.append("END NETS")
    lines.append("")
    lines.append("END DESIGN")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  wrote {path}")


# ── Main ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Generating conventional (collapsed-pin) files:")
    write_lef(OUT / "diffpair_conv.lef", conv_pins)
    write_bb(OUT / "diffpair_conv_bb.v", conv_port_names)
    write_top(OUT / "top_conv.v", conv_port_names, split=False)
    write_def(OUT / "placed_conv.def", conv_port_names, split=False)

    print("\nGenerating capillary (per-finger, shared I/O port) files:")
    write_lef(OUT / "diffpair_cap.lef", cap_pins)
    write_bb(OUT / "diffpair_cap_bb.v", cap_port_names)
    write_top(OUT / "top_cap.v", cap_port_names, split=False)
    write_def(OUT / "placed_cap.def", cap_port_names, split=False)

    print("\nGenerating cap_split (per-finger, N-port) files:")
    # LEF and blackbox are identical to cap mode; only the top/DEF differ.
    write_lef(OUT / "diffpair_cap_split.lef", cap_pins)
    write_bb(OUT / "diffpair_cap_split_bb.v", cap_port_names)
    write_top(OUT / "top_cap_split.v", cap_port_names, split=True)
    write_def(OUT / "placed_cap_split.def", cap_port_names, split=True)

    print("\nDone. Twelve files written (three modes × four files each).")
