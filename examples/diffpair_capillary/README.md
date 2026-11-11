# Guarded four-finger pair

Install GOAL and configure local tools as described in [ENGINE.md](../../docs/ENGINE.md).
Run from the repository root:

```sh
goal flow examples/diffpair_capillary/flow.py --out build/pair_sky130
goal flow examples/diffpair_capillary/gf180.py --out build/pair_gf180
```

Both configs use the same process-independent cell code and 40um floorplan
margin. conv adds internal M1/via1/M2 source/drain straps and uses merged pins; cap uses per-finger pins with shared top nets;
cap_split uses the same per-finger abstract with independent top nets. Outputs
include per-mode LEF/GDS/JSON/Verilog, routed DEF/ODB/SPEF, final GDS, Magic
logs, metrics.json, measurement.json, and combined summary.json/metrics.md.
Use a fresh output directory for every run.

The measured clean-room results and Table 3 context are in ENGINE.md. They
are distinct experiments, with no numerical fitting. Conv differs from cap
only by its physical straps, and its R includes their centre-line resistance
model. Cap modes retain isolated fingers and route aliases externally. Final
GDS connectivity checks every finger and IO terminal. Current Sky130
wirelength/vias are 314/9, 351/11, 889/23; GF180 gives 309/7, 357/11, 905/27.
All six runs have zero detailed-route and Magic drc(full) counts. LVS is not
implemented. See ENGINE.md for the old/new RC tables and model limitations.
