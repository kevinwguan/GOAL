# Guarded four-finger pair

Install GOAL and configure local tools as described in [ENGINE.md](../../docs/ENGINE.md).
Run from the repository root:

```sh
goal flow examples/diffpair_capillary/flow.py --out build/pair_sky130
goal flow examples/diffpair_capillary/gf180.py --out build/pair_gf180
```

Both configs use the same process-independent cell code and 40um floorplan
margin. conv uses merged pins; cap uses per-finger pins with shared top nets;
cap_split uses the same per-finger abstract with independent top nets. Outputs
include per-mode LEF/GDS/JSON/Verilog, routed DEF/ODB/SPEF, final GDS, Magic
logs, metrics.json, measurement.json, and combined summary.json/metrics.md.
Use a fresh output directory for every run.

The measured clean-room results and Table 3 context are in ENGINE.md. They
are distinct experiments, with no numerical fitting. In particular, merged
access rectangles assume internal electrical shorts; isolated built-in
fingers have no internal drain/source straps. LVS is not implemented. The
per-finger modes route the aliases externally. See ENGINE.md for scope and
installed-deck limitations.
