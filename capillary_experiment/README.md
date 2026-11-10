# Capillary vs. Conventional LEF Routing

Empirical test of LEF pin granularity AND destination granularity on OpenROAD
routing, using a 4-finger NMOS diff-pair macro on sky130hs. Holds the physical
footprint, placement, tracks, and TritonRoute version constant; varies only
the `PIN` stanzas in the LEF and the I/O port count / net membership in the
DEF.

## Claims under test

- **Conventional (`conv`)** — one merged `PIN` per electrical net, one I/O
  port per net. Router sees a single entry point; full device current flows
  through one min-width trace.
- **Capillary, shared port (`cap`)** — one `PIN` per finger (min-width met1
  stubs), but all finger pins wire back to a single I/O port at the top
  level. TritonRoute builds a Steiner tree with a shared trunk back to the
  single port and short fan-out stubs to each finger — the trunk still
  carries the full device current, so the 1/N claim does NOT materialize.
- **Capillary, split ports (`cap_split`)** — one `PIN` per finger AND one
  dedicated I/O port per finger (19 ports total for the diff-pair). Router
  is forced to build N disjoint paths; each path carries I/N by
  transistor-finger symmetry, and the effective R from the finger-shorted
  diffusion node to the externally-shorted output drops close to 1/N.

Electrically all three LEFs describe the same device. The three-mode sweep
separates pin granularity (necessary) from destination granularity
(also necessary) for realising the capillary topology.

## Test vehicle

`diffpair_nmos_4f` — a `CLASS BLOCK` macro, 8.0 × 6.0 µm:

- Left transistor fingers at x = 0.5, 1.5, 2.5, 3.5 µm.
- Right transistor fingers at x = 4.5, 5.5, 6.5, 7.5 µm.
- Drain band at y ≈ 5.2–5.6 µm, source (tail) band at y ≈ 0.4–0.8 µm,
  gates on the left/right edges, bulk tap in the centre.
- Met1 obstruction `RECT 0.200 1.000 7.800 5.000 ;` blocks the interior,
  so the router can only enter via declared pins.

This is a routing-topology vehicle, not a DRC-clean transistor. Only pin
granularity matters for the experiment.

## Three LEF / DEF variants

| variant   | LEF                         | top-level I/O ports |
| ---       | ---                         | --- |
| conv      | `diffpair_conv.lef`  (6)    | 6 — one per logical net |
| cap       | `diffpair_cap.lef`  (19)    | 6 — fingers shorted back to 6 nets in `top_cap.v` |
| cap_split | `diffpair_cap_split.lef` (19) | 19 — each finger routed to its own die-boundary port |

`diffpair_cap.lef` and `diffpair_cap_split.lef` are identical (same 19 PINs).
Only the top-level Verilog and DEF differ: `top_cap.v` / `placed_cap.def`
short finger pins back to 6 logical nets, while `top_cap_split.v` /
`placed_cap_split.def` assign each finger pin to its own net and
dedicated I/O port on the die boundary.

The macro placement (`u0 PLACED ( 21000 22000 )` in a 50 × 50 µm die) is
identical across all three modes, as are the gate_p / gate_n / bulk I/O
ports.

## Flow

For each mode, `openroad/run_comparison.tcl`:

1. `read_lef` — tech LEF + sky130hs cell LEF + `diffpair_${MODE}.lef`.
2. `read_def` — `placed_${MODE}.def` (macro placement + I/O pins + net
   connectivity).
3. `make_tracks`.
4. `global_route -congestion_iterations 50`.
5. `detailed_route`.
6. `estimate_parasitics -global_routing` → `parasitics.spef`.
7. `write_def` → `routed.def`.

`run.sh` wraps this with env vars (`EXPERIMENT`, `PLATFORM_DIR`, `MODE`)
and captures OpenROAD's own `-metrics` JSON plus stdout.

## Directory layout

```
gen/generate_macro.py                generator (Python stdlib only) for LEF /
                                     blackbox Verilog / top Verilog / DEF across
                                     all three modes
openroad/run_comparison.tcl          OpenROAD routing driver, parameterised by $MODE
run.sh                               wrapper — ./run.sh [conv|cap|cap_split|all]
diffpair_{conv,cap,cap_split}.lef    generated macro LEFs (cap and cap_split
                                     LEFs are identical)
diffpair_{conv,cap,cap_split}_bb.v   generated blackbox Verilog
top_{conv,cap,cap_split}.v           generated top wrappers (cap shorts finger
                                     pins back to 6 logical nets; cap_split
                                     exposes 19 separate nets)
placed_{conv,cap,cap_split}.def      generated DEFs with fixed macro + I/O pins
reports/{conv,cap,cap_split}/        per-mode outputs: openroad.log, stdout.log,
                                     metrics.json, route.guide, routed.def,
                                     parasitics.spef, drc.rpt, route.png
```

The generated artifacts are checked in; re-running the generator is
only needed when tweaking geometry or port placement.

## Running

```bash
python3 gen/generate_macro.py   # regenerate LEF/DEF/Verilog (optional)
./run.sh                        # run all three modes (routing + SPEF)
./run.sh conv                   # single mode
./run.sh cap
./run.sh cap_split
./run.sh render                 # re-render reports/*/route.png
./run.sh latex                  # emit Table 3 body to the paper tree
./run.sh paper                  # run + render + latex in one go
```

Each route invocation overwrites `reports/${MODE}/`. The `render` step
uses OpenROAD `gui::save_image` with `QT_QPA_PLATFORM=offscreen` so no
X display is needed. The `latex` step writes
`../methodology/new/tables/capillary_comparison_body.tex`, which
`4_results.tex` then `\input`s into Table 3.

## Verifying the paper's numbers

```bash
python3 verify.py           # validate conv/cap values, print 3-mode summary
python3 verify.py --latex   # emit Table 3 body for \input
```

Parses `reports/{conv,cap,cap_split}/{parasitics.spef,metrics.json,stdout.log}`.
Computes the **true** effective resistance $R_{D\to P}$ from the
finger-shorted diffusion node $D$ to the I/O port $P$ via nodal analysis
(Gaussian elimination on the conductance matrix), not the flawed
parallel-combination-of-per-finger-paths formula that double-counts the
shared trunk when present. Compares against the Table 3 values and exits
0 on match.

## Dependencies

- OpenROAD binary at `~/Vibe/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad`
  (path hardcoded in `run.sh`).
- sky130hs platform LEFs under
  `~/Vibe/OpenROAD-flow-scripts/flow/platforms/sky130hs/lef/`.
- Python 3 standard library only — no third-party deps.

## Relation to `capillary_ablation`

A later, broader version of the same question lives at
`~/Vibe/paper/methodology/experiments/capillary_ablation/`: a 16-finger
synthetic macro on sky130hd with gdsfactory-generated GDS and a larger
harness. This directory is the smaller, dep-free precursor using a
diff-pair and hand-written LEFs; use it when iterating on the
pin-granularity question without pulling in gdsfactory.

## Results (current run)

These are the numbers that back Table 3 (`tab:capillary_comparison`) in
`~/Vibe/paper/methodology/new/4_results.tex`. All values come from:

- `reports/*/metrics.json` — router totals (wirelength, vias, DRC).
- `reports/*/stdout.log` — per-layer wirelength and per-pin warnings
  (`Total wire length on LAYER ...`, `DRT-0419`).
- `reports/*/parasitics.spef` — per-net capacitance and the RC tree
  used to derive effective net resistance.

All three modes complete with zero DRC violations in a single detail-route
iteration on sky130hs.

### Wirelength and vias

| metric                      | conv | cap  | cap_split |
| ---                         | ---  | ---  | ---       |
| total wirelength (µm)       | 153  | 165  | 605       |
| &nbsp;&nbsp;met1 (µm)       | 53   | 68   | 200       |
| &nbsp;&nbsp;met2 (µm)       | 99   | 96   | 391       |
| vias (all met1→met2)        | 6    | 6    | 25        |
| DRC violations              | 0    | 0    | 0         |

`cap` moves 15 µm of routing into met1 (the local fan-out to each finger
stub) while the met2 trunk shrinks slightly. `cap_split` quadruples the
total wirelength — the N disjoint routes to N distinct die-boundary ports
are the cost of realising the parallel-path topology.

### Effective net resistance and capacitance (SPEF)

`verify.py` computes the **true** effective resistance $R_{D\to P}$ from
the finger-shorted diffusion node $D$ (the electrical short inside the
transistor) to the I/O port $P$ via nodal analysis of the extracted RC
network (Gaussian elimination on the conductance matrix). For `cap_split`,
the $N$ per-finger ports are treated as externally shorted.

| net         | metric        | conv | cap  | cap_split |
| ---         | ---           | ---  | ---  | ---       |
| drn_p (N=4) | R (Ω)         | 36.1 | 27.4 |  9.1      |
| tail  (N=8) | R (Ω)         | 29.1 | 23.8 |  4.7      |
| drn_p       | net C (fF)    |  3.24 | 4.13 | 13.21     |
| tail        | net C (fF)    |  2.54 | 5.65 | 28.34     |

`cap` delivers only a modest ~24% R reduction: pin granularity alone
lets the router build a Steiner tree with a shared trunk back to the
single I/O port, and the trunk dominates the series resistance.
`cap_split` delivers close to the analytical 1/N prediction (4.0× for
the four-finger drain, 6.2× for the eight-finger tail — the shortfall
at N=8 reflects unequal per-finger path lengths given the distribution
of I/O ports across the die boundary). By transistor-finger symmetry
each of the N routes carries I/N in the `cap_split` case; in `conv` and
`cap` the full current flows through one trunk.

### Per-finger SPEF paths (cap_split)

| net        | per-finger path R (Ω)                               |
| ---        | ---                                                 |
| drn_p      | 40.5, 39.7, 34.3, 32.3                              |
| drn_n      | 40.5, 39.7, 34.3, 32.3 (symmetric)                  |
| tail       | 42.0, 31.9, 36.3, 35.1, 35.2, 35.2, 41.4, 47.7      |

Each path is a simple tree from one finger iterm to one I/O port, so
per-path R is just the SPEF series sum. Their parallel combination (with
the diffusion-shorted external-shorted model) gives the 9.1 Ω / 4.7 Ω
effective R above.

### Reproducing

```bash
./run.sh           # regenerate reports/{conv,cap,cap_split}/
python3 verify.py  # print 3-mode summary + per-finger path breakdown
```

### Scope

A single 4-finger diff-pair on sky130hs. Numbers are a direct
attachment to the analytical ratios in
`~/Vibe/paper/methodology/new/3_methodology.tex`, not a broad
characterization. For a wider sweep (16 fingers, sky130hd, gdsfactory
macro), see `~/Vibe/paper/methodology/experiments/capillary_ablation/`.
