# GOAL engine

GOAL (GDSFactory OpenROAD Automated Layout) turns GDSFactory components into
portable LEF/GDS/Verilog artifacts and assembles them with local OpenROAD.
This is a clean-room implementation built from the reproducibility branch,
not the authors' original generator. It includes guarded primitives, OTA
hardening and a manifest-defined Sky130 pad harness. No paper sources or measurement
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
python -m goal.harness --out build/ring
python examples/chip_sky130/build.py --out build/chip
pytest -q
python3 capillary_experiment/verify.py
```

`python -m goal` also works. Pytest adds the checkout root to its import path,
so a dependency-equipped fresh checkout supports plain `pytest` without an
editable install. Every run needs a fresh output directory; prior
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
| 3.5 | Hardened pad ingestion, manifest composition and core abstracts | `goal/harness/` | Supplied PDK LEF/GDS; no ORFS design or private generator sources |
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
The unstrapped merged abstract retains the 19 separate access rectangles
under six pins. The runnable conv vehicle instead exposes its connected M2
source/drain straps. The oracle uses six solid bounding rectangles; these are
deliberately different physical geometries.

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
`place_pins`; `place_io=False` disables top IO placement.
`peripheral_placements` fixes full-die peripheral masters directly through
OpenDB and checks their actual bbox against the die. Ordinary `placements`
retain core/site checks. Technology SITE rows are used for floorplan initialization.
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
`goal flow`, OTA and chip examples additionally assemble final GDS and run Magic.
`allow_global_congestion` defaults to false. The chip explicitly enables it:
the VSSA pin has zero-capacity coarse bins even though detailed routing closes.
`global_congestion.rpt` and the warning are retained; detailed-route DRC and
final-GDS connectivity remain required.

Final GDS uses the platform KLayout `.lyt`, matches DEF units, clears LEF
placeholders, loads macro/optional standard-cell GDS, preserves routed vias,
and copies the routed top hierarchy. Missing macro geometry fails. Empty
leaf structures explicitly present in source GDS are preserved and reported
in `source_empty_cells`; empty source tops are rejected. It reopens the
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
| sky130A | conv | 314 | 9 | 0 | 0 | 58.0484 | 52.6406 |
| sky130A | cap | 351 | 11 | 0 | 0 | 59.1939 | 54.1526 |
| sky130A | cap_split | 889 | 23 | 0 | 0 | 14.3198 | 6.54297 |
| gf180mcuD | conv | 309 | 7 | 0 | 0 | 16.3737 | 14.7152 |
| gf180mcuD | cap | 357 | 11 | 0 | 0 | 19.9448 | 17.5224 |
| gf180mcuD | cap_split | 905 | 27 | 0 | 0 | 4.96403 | 2.33479 |

Conv/split R ratios (drain_p/drain_n/tail) are now
4.05372/3.98723/8.04536 on sky130A and 3.29846/2.77487/6.30257 on GF180.
The new conv includes its internal strap R; cap and cap_split remain unstrapped.
The measured change from the former, electrically open conv baseline is:

| PDK | quantity | old conv | strapped conv |
| --- | --- | ---: | ---: |
| sky130A | wirelength / vias | 318 / 10 | 314 / 9 |
| sky130A | drain_p / drain_n / tail R, ohm | 60.1364 / 59.5013 / 56.7086 | 58.0484 / 57.4144 / 52.6406 |
| sky130A | conv/split drain_p / drain_n / tail | 4.19953 / 4.13215 / 8.66710 | 4.05372 / 3.98723 / 8.04536 |
| gf180mcuD | wirelength / vias | 316 / 10 | 309 / 7 |
| gf180mcuD | drain_p / drain_n / tail R, ohm | 20.0140 / 20.0935 / 19.6434 | 16.3737 / 16.1036 / 14.7152 |
| gf180mcuD | conv/split drain_p / drain_n / tail | 4.03181 / 3.46240 / 8.41334 | 3.29846 / 2.77487 / 6.30257 |

Old and new detailed-route DRC counts are zero. Earlier Magic zero counts used
incorrectly mapped streams; the corrected streams in the current table are
freshly measured. All finger/IO terminals pass physical connectivity in all six
current flows. A regression rejects the former unstrapped merged macro.

For context, Table 3's different routing-only macro gives wirelength
153/165/605um, vias 6/6/25, drain_p R 36.1/27.4/9.1ohm and tail R
29.1/23.8/4.7ohm (conv/split ratios approximately 3.97 and 6.19).
Those are not equality targets for this geometry or extraction method.

The sky130A 5T OTA measures 528um, 39 vias, zero route DRC and zero Magic
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
Declare the `connectivity` conductor/via stack, `lef_vias` and `stream_layers`
for final-GDS extraction/streaming, and any non-routing `obs_layers`. Add
`conductor_purposes` only when the actual PDK input deck treats that purpose
as physical metal; labels never join nets. The strap model additionally needs
tech-LEF sheet resistance and a documented typical via resistance.

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

Merged LEF requires internally connected access shapes. Conv uses the
strapped variant; cap modes and the OTA connect isolated fingers through
external routing. The OTA is checked before hardening and its original device
landings are checked again in the assembled chip. These metal/via checks do
not establish transistor/block LVS, matching or electrical specifications.

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

The configured suite passes **43 tests**, covering both PDKs' three-mode flows, primitive Magic
checks, transformed ports, obstruction holes, Verilog/DEF input, automatic
placement/IO, OTA hardening, complete-library pad ingestion and the routed chip.
See the example READMEs for current measurements. The capillary oracle,
Ruff lint/format and whitespace checks are required. Modules stay below 400
lines; generated outputs and tool environments remain ignored.

### Physical conventional baseline (H1)

`mosfet(..., strapped=True)` and `diffpair(..., strapped=True)` add only M1
stems, via1 cuts and M2 source/drain rails to the unstrapped geometry. The
pair's M2 tail bridge connects its two source rails. Device geometry, guard
rings, footprint and placement are identical. Conv uses this variant and
exposes its M2 rails in the merged LEF; cap and cap_split remain unstrapped.
The original M1 finger landings remain in JSON `terminals` for verification.

`goal.signoff.connectivity.Connectivity` extracts conductors from the final
GDS with KLayout, using explicit PDK metal/via tables (including Sky130 LI and
mcon). It checks every finger and IO landing, rejects disconnected aliases
and shorts between different nets. This exposed two earlier stream-out bugs:
DEF reader configuration was modified through a copy without assigning it
back, and importing GF180 macro GDS changed the destination DBU. Stream-out
now assigns the configuration, explicitly maps routing/via/pin shapes to PDK
drawing layers, and copies macro trees across layouts with DBU conversion.
Local-interconnect OBS also prevent pin-access routes through the bulk ring.
Earlier final-GDS Magic counts did not check correctly mapped routed metal.

Conv R includes OpenRCX routing R plus the measured internal strap network:
M1 stem centre-line length/width and M2 rail segment length/width, multiplied
by the tech LEF sheet resistance, plus 4.5 ohm per via1 (PDK typical-corner
Magic `contact m2c 4500` milliohm). A nodal solve shorts all finger centres
and uses the single actual routed M2 aperture, measured from final GDS, as
the other boundary. Multiple disconnected apertures are rejected. This is
a 1D resistance approximation; current spreading, FEOL/contact R, gate/bulk
internal R and internal capacitance are excluded. It is not field extraction
or electrical signoff. Cap/split still use routing-only OpenRCX R.


## Harness manifest and chip assembly (§3.5)

`python -m goal.harness --out build/ring` builds and checks `sky130_example()`.
The `RingSpec` defines die `(1004, 1004)` and core `(180, 180, 824, 824)` in um.
Each `Pad(side, order, cell, net, core_pin, bindings={}, ties={}, gap_after_um=0)`
selects a hardened master and maps its native pins to chip nets. `bindings`
only names connections; `ties` explicitly requests the M2/M3 GPIO tie wiring.
`gap_after_um` inserts declared common-bus filler widths immediately after a
pad. VCCD requests 20um because its GDS protrudes 11.195um past its LEF width;
placing VSSIO immediately after it causes real supply shorts. Other remaining
space is filled with the specified 20/10/5/1um `com_bus_slice` cells. Corner
LEF dimensions, reference bus line and the manifest determine every transform;
the builder rejects excess widths, ambiguous orders and unfillable gaps.

The example includes four corners, four analog pads, one input-configured
GPIO and six clamped supply pads (VCCD/VSSD/VDDA/VSSA/VDDIO/VSSIO). Native
power-pad geometry joins VDDIO_Q to VDDIO and VSSIO_Q to VSSIO; explicit
`bus_aliases` record these physical joins. Twelve named buses therefore form
ten net aliases. The GPIO package pad and its core IN remain distinct metal
nets because a transistor input is not a metal short. GPIO controls use the
hardened TIE_LO_ESD/TIE_HI_ESD outputs. Electrical configuration and ESD sizing
are not verified.

`PadLibrary` resolves cross-file dependencies across the supplied PDK GDS
library before copying a selected hierarchy unchanged. Single-file imports
are insufficient: wrappers reference base cells in `sky130_fd_io.gds`.
All input GDS hashes are retained. GDS STRNAME records distinguish undefined
references from declared empty structures. The selected hierarchy contains
one vendor-declared empty guard-ring placeholder,
`sky130_fd_pr__gendlring__example_559591418081`; it is preserved and reported,
not populated or treated as independently verified geometry. Tests compare
imported geometry to the resolved source on every layer.

LEF RECT/POLYGON pin frames become GDSFactory electrical ports. The core
abstract chooses a solid actual-GDS rectangle within each LEF access frame;
frames sometimes exceed physical metal. Original frames remain in metadata.
Package probes cover each disconnected metal island within its LEF frame.
Current complete-library geometry needs no added bus overlays: `strap_buses`
is false. The earlier experimental overlay option has not been validated on
the complete library and is not used by either example.

Outputs include `pad_ring.gds`, `manifest.json`, `chip_aliases.json`,
`core_area.lef` (core coordinates), and `pad_ring.lef` (full-die master with
periphery/actual-interior OBS). `checks.json` records independent abutment
intervals, extracted connectivity, raw Magic counts, standalone resolved-cell
baselines and OpenROAD abstract loading. All 95 primary placement intervals
have zero gaps over each 600um side. All 5,362 bus probes and 21 tie probes
connect, with no shorts between declared aliases. Both abstracts load with
zero OpenROAD errors. Ring Magic drc(full) is **4978**, versus instance-weighted
standalone baseline **4806**, delta **+172**. This ring is not DRC-clean.
The earlier 5013/961/+4052 measurements used incomplete dependencies and are
superseded. Current standalone counts are:

| master suffix | count | instances |
| --- | ---: | ---: |
| corner_pad | 3 | 4 |
| analog_pad | 34 | 4 |
| vdda_hvc_clamped_pad / vddio_hvc_clamped_pad | 376 each | 1 each |
| vssa_hvc_clamped_pad / vssio_hvc_clamped_pad | 378 each | 1 each |
| vssd_lvc_clamped_pad / vccd_lvc_clamped_pad | 48 each | 1 each |
| gpiov2_pad_wrapped | 3054 | 1 |
| com_bus_slice_20um / 10um | 0 | 77 / 3 |

`examples/chip_sky130/build.py` fixes the ring at the die origin and the routed
OTA at `(400, 400)`, maps vdd/vss to VDDA/VSSA, and routes the four analog nets.
Its no-top-IO Verilog connects actual ring-core pins to the six OTA ports.
The OpenROAD floorplan core spans the die to admit the full-die BLOCK master;
ring OBS enforce the manifest core/periphery. Peripheral placement bypasses
site-row clipping while still enforcing the declared die. The example checks
all ring/tie/package/core access plus original OTA finger landings in final
GDS. Chip routing measures 2775um and 26 vias, with zero detailed-route
DRC. Full-die Magic drc(full) reports **5022** errors. All 5437 physical
terminals across 20 net aliases pass connectivity, with no inter-alias shorts.
LVS, ESD sizing/verification, seal ring, density fill and antenna are not done.
The analog_pad master itself has no ESD structures; the presence of supply
clamps/GPIO protection does not establish chip ESD protection.

To add a pad type in this library, add a manifest entry with explicit native
core pin, aliases, physical tie requests and any required filler spacing, then
check its resolved hierarchy and all final-GDS terminals. The LEF reader
supports RECT and POLYGON frames; PATH/VIA access primitives fail explicitly.
To add another PDK's harness, supply its library paths/master names, bus and
corner alignment conventions, tie geometry and process layer/via mapping;
`PadLibrary` and filler naming currently target Sky130. A PDK JSON alone does
not make a new IO library supported. Re-run standalone/ring Magic and LEF
loading before claiming support. No LVS, ESD, seal-ring or foundry waiver is
inferred from the raw DRC delta.
