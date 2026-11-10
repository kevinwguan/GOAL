# GOAL engine

GOAL (GDSFactory OpenROAD Automated Layout) turns GDSFactory components into
portable LEF/GDS/Verilog artifacts and assembles them with local OpenROAD.
This is a clean-room implementation built from the reproducibility branch,
not the authors' original generator. All G1–G6 phases, including both G5
stretch examples, were implemented locally. No paper sources or measurement
oracle files were changed.

## Install and tools

Python 3.10 or newer is supported; 3.11+ is recommended because GDSFactory
8.32.2 deprecates Python 3.10. Use a separate environment:

```sh
python3 -m venv .scratch/goal/venv
. .scratch/goal/venv/bin/activate
pip install -e '.[test]'
```

GDSFactory is pinned to 8.32.2; KLayout 0.30.13 was tested. OpenROAD and
Magic are external executables, not Python dependencies. Set these variables
for the installed toolchain (the paths below are placeholders):

```sh
export ORFS_DIR=/path/to/OpenROAD-flow-scripts
export OPENROAD="$ORFS_DIR/tools/install/OpenROAD/bin/openroad"
export PDK_ROOT=/path/to/open_pdks
# Alternatively, select the platform directory directly:
# export PLATFORM_DIR=/path/to/platforms/sky130hs
```

`OPENROAD` takes precedence over PATH. `PLATFORM_DIR` takes precedence over
`ORFS_DIR/flow/platforms/<PDK platform>`. Default technology LEF, OpenRCX
rules and KLayout technology file are relative paths in the PDK JSON.
`TECH_LEF`, `RCX_RULES`, and `KLAYOUT_TECH` override those assets; a missing
explicit override fails clearly. `PDK_ROOT` is used for PDK layer-map
verification and optional Magic DRC. No tool installs, network calls, telemetry,
or remote writes occur during a GOAL run. Dependencies installed by pip may
require a package source. Python configs are trusted executable local code.

From the repository root:

```sh
goal --help
goal lef --pdk sky130A --mode per_finger --out build/abstract
goal flow examples/diffpair_capillary/flow.py --out build/sky130
goal flow examples/diffpair_capillary/gf180.py --out build/gf180
python examples/ota5/build.py --out build/ota5
pytest -q
python3 capillary_experiment/verify.py
```

`python -m goal` also works. Every run needs a fresh output directory; prior
results are preserved. Keep generated outputs under ignored `build/` or `out/`.
Full routing tests are marked `openroad`. They skip when discovery is absent;
when OPENROAD is explicitly configured, discovery failures fail the tests.
Magic tests skip without Magic/PDK_ROOT and otherwise run the installed
`drc(full)` deck. `pytest -q -m 'not openroad and not magic'` runs offline checks.

## Architecture and source provenance

| Paper section | Responsibility | Modules | Clean-room source |
| --- | --- | --- | --- |
| 3.1 | Flat process tables and guarded MOS geometry | `goal/pdk/`, `goal/cells/` | `reproduction/pdk.py`, `config/*.json`, `geometry.py` |
| 3.2 | Diffusion graph, path cover, well-group tiling | `goal/place/` | `reproduction/placement.py` |
| 3.3, Fig. 3 | Port rectangles, pins, OBS, GDS and netlists | `goal/lef/` | `reproduction/lef.py`, extended for transformed rectangles |
| 3.4 | Tool discovery, FlowSpec, routing, RCX and GDS assembly | `goal/openroad/` | `reproduction/scripts/route_independent.py`; GDS strategy follows ORFS `def2stream.py` |
| 4.4 | Three-mode experiment, SPEF measurement | `goal/flow.py`, `goal/rc.py` | Independent floorplan policy and `reproduction/rc.py` |

Sources were copied read-only from `repro-methodology` into this package,
then split and reformatted. GOAL does not import `reproduction` or depend on
that worktree. JSON tables preserve layer/rule provenance and hashes.

## Pin and alias contract

`goal.lef.write_abstract(component, pdk, out_dir, mode, macro_name,
tech_lef=None, coarse_obs=False)` emits:

- `<name>.lef`: plain LEF 5.8, BLOCK, micrometre dimensions, RECT geometry.
- `<name>.gds`: merged, flattened geometry with a macro-named top at LEF origin.
- `<name>_bb.v`: a standard Verilog blackbox for external consumers.
- `<name>.json`: physical pin → logical net aliases, rectangles, layers,
  dimensions, original origin and obstruction count.

Ports are electrical GDSFactory ports with `info` fields:

| Field | Meaning |
| --- | --- |
| `net` | Logical net identifier, shared by fingers of one electrical node |
| `generic_layer` | Generic process key, resolved through `pdk.lef_layers` |
| `rect_local` | Four rectangle corners in the port's local transform frame |
| `rect` | Snapped source rectangle retained for inspection |

Use the construction helper to create correct metadata:

```python
import gdsfactory as gf
from goal.pdk import PDK
from goal.cells.geometry import rect, port
from goal.lef import write_abstract

pdk = PDK.load('sky130A')
c = gf.Component()
rect(c, pdk, 'met1', (0, 0, 1, 0.5))
port(c, pdk, 'D0', 'drain', (0, 0, 1, 0.5))
write_abstract(c, pdk, 'build/custom', macro_name='custom')
```

Copy transformed ports with `parent.add_port(name=..., port=ref.ports[...])`.
The engine transforms each stored corner using `port.dcplx_trans`, including
rotation and reflection. Nested references preserve the same contract.
Orthogonal unit-scale transforms are supported. Oblique rotations or scaling
fail rather than expose a spurious bounding rectangle. Add top-level ports
explicitly; internal unexposed reference ports are not exported automatically.
Identifiers use `[A-Za-z_][A-Za-z0-9_]*` for portable Verilog/LEF/DEF/Tcl.

`merged` emits one PIN per logical net with all its access rectangles;
`per_finger` emits one PIN per component port. The four-finger pair has
6 merged pins or 19 per-finger pins: 4+4 drain, 8 tail, 2 gate, 1 bulk.
The oracle conventional abstract instead uses six solid bounding rectangles;
our merged mode retains all 19 physical access rectangles under six pins.
The structural tests assert this deliberate difference.

`cap_split` is a wrapper choice, not a LEF mode. Call
`goal.lef.verilog.write_wrapper(..., cap_split=True)` to give each physical
pin an independent top net. Without it, aliases connect pins to shared nets.
`external_nets=[...]` exposes selected subcircuit nets and declares other nets
as internal wires (used by the OTA example). All ports currently use INOUT.
LEF contains no alias extensions or custom properties.

OBS starts from fixed metal, subtracts exposed pin rectangles and decomposes
orthogonal polygons into rectangles. `coarse_obs=True` first replaces each
occupied metal layer with its bounding box, then cuts the same pin apertures.
Nonrectangular decomposition pieces fail explicitly. All LEF layer names come
from `lef_layers`; pass `tech_lef=` for validation against the platform's LAYER
inventory. Routing always validates through its selected technology.

## Routing and final GDS

`FlowSpec` accepts macro LEFs, top Verilog files, die/core coordinates,
fixed macro coordinates, IO coordinates/layer/size, routing layers, optional
placed DEF, timeout and thread count. Default runs use one thread. Sizes and
coordinates are micrometres. Single macros are LOCKED (DEF FIXED). Multiple
specified placements are supported; `auto_place=True` requests
`rtl_macro_placer`. With no explicit IO coordinates the backend calls
`place_pins`. Technology SITE rows are used for floorplan initialization.
Default square IO size satisfies the technology LEF WIDTH and AREA rules,
rounded upward on a 5nm construction grid.

`goal route spec.json --out build/route` routes a JSON-encoded FlowSpec.
File paths are relative to the JSON file. For example, after `goal lef`:

```json
{
  "macro_lefs": ["abstract/goal_pair.lef"],
  "verilog": ["abstract/top.v"],
  "die": [0, 0, 110, 90],
  "core": [0, 0, 110, 90],
  "placements": {"pair": [40, 40]},
  "io_layer": "met2",
  "routing_layers": ["met1", "met5"]
}
```

The supplied built-in abstract fits this example. Save it as `build/spec.json`.
Only pass the top wrapper to OpenROAD: this installed OpenSTA flattens an empty
blackbox Verilog definition. LEF supplies the physical master during linking.
The no-Liberty warning is retained; these macros have no timing models.
For `placed_def`, placement/IO/floorplan come from that DEF.

Routing calls `make_tracks`, `set_routing_layers`, `global_route`, and
`detailed_route`, writes DEF/ODB and a DRC report, then uses OpenRCX when its
platform rules exist. Otherwise it records `estimated_global_routing` and calls
`estimate_parasitics`. `metrics.json` includes measured wirelength, vias,
DRC count, elapsed runtime, extraction method, warnings/errors and exit state.
Missing measurements are null, not invented zeros. Logs scrub private paths;
local Tcl scripts retain actual paths to be executable. Failed/timeout attempts
retain diagnostic logs. The lower-level route CLI emits routing products;
`goal flow` and the OTA example additionally assemble final GDS and run Magic.

Final GDS uses the platform KLayout `.lyt`, matches DEF units, clears LEF
placeholders, loads macro/optional standard-cell GDS, preserves routed vias,
and copies the routed top hierarchy. Missing/empty cells fail. It reopens the
written GDS and checks the macro cells exist. `routed_component` supports the
N-oriented single-rectangle IO pads emitted here; unsupported DEF pin geometry
fails rather than guessing. This permits a routed OTA to become a new macro.

## Measured results

The declared floorplan uses 40um margin; shared IO x is the mean access x,
split IO x follows its access rectangle. Drain IOs are north, tail south,
gates east/west and bulk west. No dimensions or routing parameters were fitted
to paper numbers. Tested binary reports `HEAD-HASH-NOTFOUND`; its SHA-256 is
`8591e9119d91e80409d4456b885620554c25cae42b8c6e6a760741d5b08db205`.
Both platforms use their installed OpenRCX rules, not the oracle's estimated RC.

| PDK | mode | wirelength um | vias | route DRC | Magic full DRC | drain_p R ohm | tail R ohm |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| sky130A | conv | 318 | 10 | 0 | 0 | 60.1364 | 56.7086 |
| sky130A | cap | 351 | 11 | 0 | 0 | 59.1939 | 54.1526 |
| sky130A | cap_split | 889 | 23 | 0 | 0 | 14.3198 | 6.54297 |
| gf180mcuD | conv | 316 | 10 | 0 | 0 | 20.0140 | 19.6434 |
| gf180mcuD | cap | 357 | 11 | 0 | 0 | 19.9448 | 17.5224 |
| gf180mcuD | cap_split | 905 | 27 | 0 | 0 | 4.96403 | 2.33479 |

Measured conv/split R ratios (drain_p/drain_n/tail) are
4.19953/4.13215/8.66710 on sky130A and 4.03181/3.46240/8.41334 on GF180.
For context, Table 3's different routing-only macro gives wirelength
153/165/605um, vias 6/6/25, drain_p R 36.1/27.4/9.1ohm and tail R
29.1/23.8/4.7ohm (conv/split ratios approximately 3.97 and 6.19).
Those are not equality targets for this geometry or extraction method.

The sky130A 5T OTA measures 529um, 41 vias, zero route DRC and zero Magic
errors after re-abstraction. It has six external nets and internally routed
n1/tail nets. Block LVS and analog performance are not tested.

The resistor solver shorts all device terminals together and all external
ports together, then solves the reduced conductance Laplacian with 1A injection.
Zero-ohm edges are unioned exactly. Shared trunks are counted once; unequal
split paths need not share current equally. This is a boundary model, not an
independent device-current, electromigration or lifetime simulation.

## Extend the PDK or cells

Copy one PDK JSON and change `name`, layer pairs/provenance, scalar rule values,
`lef_layers`, and relative platform asset paths. Generic keys describe geometry;
`lef_layers` explicitly supplies the platform vocabulary (e.g. met1 → Metal1).
Keep rules out of cell modules. Use `PDK.verify()` with PDK_ROOT to validate
layer pairs, and `validate_lef()` to check platform names. Test both MOS
polarities with the installed Magic deck before claiming primitive support.

A new cell needs fixed polygons plus electrical ports following the metadata
contract. Use rule values for process-specific dimensions and the shared grid
helpers. Preserve copied-port transforms, supply unique physical pin names and
logical `net` names, then round-trip its LEF and load it in OpenROAD. The engine
is independent of the built-in diffpair; only the demonstration `run_flow`
policy is specific to that vehicle.

## Ordering and remaining limits

Paths cover every vertex of the drain/source device-net bipartite graph once.
Gates and bulk do not add graph edges. Degree-two components use a linear walk;
other components up to 20 vertices use exact subset DP over simple paths.
The general problem is exponential. Larger components use a deterministic
greedy cover explicitly marked `minimum_certified: false`.

The paper's statement that fan-out above two prevents a spanning path is false
as stated. Devices M0=(a,b), M1=(a,b), M2=(a,c) have degree(a)=3, yet
`c–M2–a–M0–b–M1` spans all vertices. The independent edge-subset oracle tests
this behavior and all 81 four-device graphs over three diffusion nets.
Well tiling preserves traversal order within nmos/pmos groups and chooses
columns for a requested group aspect. Whole-block aspect may differ.
Individual isolated fingers and guard rings are retained; diffusion is not
physically shared. Mixed-bulk groups and unimplemented physical passives fail.

Merged LEF assumes all access shapes of one PIN are electrically connected
inside the macro. The built-in isolated fingers do not add internal source/drain
straps: conventional mode is an abstraction experiment, not an LVS-verified
hardened transistor. Per-finger alias routing provides those external wires.
The OTA uses per-finger internal routing before re-abstraction. None of these
results establishes transistor/block LVS, matching, electrical specifications,
antenna/density closure or foundry signoff.

The installed GF180 Magic deck warns that `ndiff_missing_pwell` and
`mvndiff_missing_pwell` CIF layers are unknown; reported zero counts reflect
that installed deck's coverage. OpenROAD routing retains its unsupported
LEF58 enclosure warnings and no-timing warnings in metrics. The emitted macro
LEFs themselves load without warnings/errors on sky130hs.

Multi-macro automatic placement, automatic IO placement, RC-estimation fallback
and two-instance GDS assembly are integration tested on sky130hs: 522um,
27 vias and zero route DRC in the additional two-macro run. Its macro placer
reports pin-to-track alignment warnings, retained in the log. Standard-cell GDS
assembly is not tested because the examples instantiate no standard cells. LVS, analog simulation, real
shared-diffusion abutment and passive PCells are not done. No root README was
created, preserving the planned paper-artifacts README destination.

## Verification record

The final configured suite passes 37 tests, including both PDKs' three-mode
routes, all four primitive Magic checks, transformed ports, obstruction pin
holes, Verilog/DEF input, two-macro automatic placement/IO with estimated RC,
and OTA hardening. The capillary oracle remains PASS. Ruff lint/format and
whitespace checks pass. The installable wheel includes both PDK tables; the
installed `goal` entry point was exercised for help, LEF emission and routing.
All new Python modules are below 400 lines. New tracked files contain no
machine-specific home paths, generated outputs or files above 1MB.
