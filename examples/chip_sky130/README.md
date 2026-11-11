# Sky130 chip with a hardened OTA and pad harness

With GOAL, OpenROAD, Magic and the PDK configured as in
[ENGINE.md](../../docs/ENGINE.md), run from the repository root:

```sh
python -m goal.harness --out build/ring
python examples/chip_sky130/build.py --out build/chip
# Optional reuse of previously checked raw inputs:
python examples/chip_sky130/build.py --out build/chip_reuse --ring build/ring --ota build/ota5
```

A fresh run builds and checks the ring, routes/hardens the 5T OTA, fixes it at
(400, 400)um, and routes its six core connections. The die is 1004um square;
the manifest core is (180, 180)–(824, 824)um. Supplies map vdd/vss to VDDA/VSSA.
Analog pad package/core ports share metal; the digital package pad and IN
remain distinct because the input buffer is a circuit. The chosen power pads
join quiet/main IO rails, explicitly recorded in the manifest. GPIO tie
controls use the native hardened ESD tie outputs.

The PDK GDS dependencies are resolved across files; hardened cell geometry is
copied unchanged. The VCCD pad's 11.195um LEF overhang is separated from the
next pad by a manifest-specified 20um filler. All four side spans abut with
zero gaps. Core pin apertures are restricted to solid actual GDS metal.
One declared empty vendor guard-ring placeholder is retained and disclosed.
No added bus overlays are used. Twelve named buses form ten net aliases.

Chip routing measures 2775um and 26 vias, with zero detailed-route
DRC. Full-die Magic drc(full) reports **5022** errors. All 5437 physical
terminals across 20 net aliases pass connectivity, with no inter-alias shorts.
The coarse global-route VSSA congestion report is retained even though detailed
routing closes. Final-GDS connectivity covers bus/tie probes, core/package
pads, OTA access pins and every original OTA finger terminal. Both masters
are FIXED in the emitted DEF; final GDS merges their trees with the routes.

Outputs include connected `top.v`, `route/{routed.def,routed.odb,routed.spef,
final.gds,detailed.drc,global_congestion.rpt}`, `connectivity_terminals.json`,
Magic logs and `summary.json`, plus ring/OTA inputs when built fresh.
Reused input directories must come from the same builder/toolchain; reuse
reads their metadata but does not repeat standalone/ring checks.

Ring Magic drc(full)=4978, instance-weighted standalone baseline=4806,
delta=+172; per-master counts are in ENGINE.md and `ring/checks.json`.
These raw errors remain unresolved. Analog pads have no ESD structures;
supply clamps and GPIO protection do not establish chip protection.
LVS, ESD sizing/verification, seal ring, density fill, antenna and analog
performance are not done. This is an integration example, not tapeout signoff.
