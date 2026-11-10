#!/usr/bin/env python3
"""Verify conventional vs capillary routing metrics against Table 3.

Parses reports/{conv,cap,cap_split}/{parasitics.spef,metrics.json,stdout.log},
computes the *true* effective net resistance from the finger-shorted diffusion
node D to the I/O port(s) via nodal analysis, and emits the Table 3 body.

The three modes are:

  conv       — 1 merged LEF pin per logical net, 1 I/O port per net.
               Baseline; R_eff is the single-path series sum from macro pin to
               I/O port (the SPEF RC tree is a simple chain).

  cap        — N per-finger LEF pins per logical net, but still only 1 I/O
               port per net; the top-level netlist shorts all finger pins
               back to the same logical net. TritonRoute therefore builds a
               Steiner tree with a shared trunk and short per-finger fan-out
               stubs. All N finger iterms of the logical net are shorted at
               the transistor diffusion (inside the macro), so the true
               effective R from the diffusion short to the port is the
               resistance of the composite network with that short added. It
               is NOT the parallel combination of per-finger paths to the
               port — that formula double-counts the shared trunk and
               over-states the benefit.

  cap_split  — N per-finger LEF pins AND N separate I/O ports (one per
               finger) in the DEF. Each finger pin is in its own SPEF net
               with a single terminal + single port, so TritonRoute must
               route N disjoint paths (no shared trunk). The per-finger path
               resistance is therefore a faithful measurement, and the
               parallel combination (assuming the N destinations are shorted
               externally) is the correct effective R from the diffusion
               short to that shorted external node.

Modes:
  python3 verify.py            validate measurements against EXPECTED;
                               prints the summary table. Exit 0 on match.
  python3 verify.py --latex    emit the Table 3 body as a LaTeX fragment
                               suitable for \\input into 4_results.tex.
                               No validation; exit 0.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODES = ("conv", "cap", "cap_split")

# Logical-net groupings. In conv/cap these are individual SPEF nets; in
# cap_split they fan out to one SPEF net per finger. The "fingers" are the
# SPEF net names in each mode.
NET_GROUPS = {
    "conv":      {"drn_p": ["drn_p"], "tail": ["tail"]},
    "cap":       {"drn_p": ["drn_p"], "tail": ["tail"]},
    "cap_split": {"drn_p": [f"drn_p_{i}" for i in range(4)],
                  "tail":  [f"tail_{i}"  for i in range(8)]},
}


# ── SPEF parser ─────────────────────────────────────────────────────────────
def parse_spef(path):
    """Return dict[netname] -> {total_cap_F, port, terminals, resistors}."""
    nets = {}
    cur = None
    section = None
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("*D_NET"):
                parts = line.split()
                cur = {"total_cap_F": float(parts[2]), "port": None,
                       "terminals": [], "resistors": []}
                nets[parts[1]] = cur
                section = None
                continue
            if line == "*END":
                cur = None
                section = None
                continue
            if line == "*CAP":
                section = "CAP"
                continue
            if line == "*RES":
                section = "RES"
                continue
            if cur is None:
                continue
            if line.startswith("*I "):
                cur["terminals"].append(line.split()[1])
                continue
            if line.startswith("*P "):
                cur["port"] = line.split()[1]
                continue
            if section == "RES":
                parts = line.split()
                if len(parts) >= 4:
                    cur["resistors"].append((parts[1], parts[2], float(parts[3])))
    return nets


# ── Gaussian elimination (small dense linear solve) ─────────────────────────
def solve(A, b):
    """Solve A x = b for small dense A via Gaussian elimination with partial
    pivoting. A is a list of lists (n×n); b is a list of length n. Returns x
    as a list, or None if singular."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-18:
            return None
        M[col], M[piv] = M[piv], M[col]
        for r in range(col + 1, n):
            f = M[r][col] / M[col][col]
            for c in range(col, n + 1):
                M[r][c] -= f * M[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = M[r][n] - sum(M[r][c] * x[c] for c in range(r + 1, n))
        x[r] = s / M[r][r]
    return x


def effective_R_cap(net):
    """True effective R from the finger-shorted diffusion to the I/O port for
    a multi-terminal cap-style net. All *I terminals are treated as one node
    (electrically shorted at the transistor diffusion); the SPEF RC tree
    connects this node to the *P port through whatever topology TritonRoute
    built. Returns the R seen from D to P via nodal analysis (G V = I)."""
    port = net["port"]
    terms = net["terminals"]
    if port is None or not terms:
        return None

    # Build the node set: port, internal *-labeled nodes, and ONE merged D
    # node replacing all finger terminals.
    nodes = {port: "P"}
    D = "__D__"
    nodes[D] = D
    for t in terms:
        nodes[t] = D  # alias to D
    for n1, n2, _r in net["resistors"]:
        for n in (n1, n2):
            if n not in nodes:
                nodes[n] = n

    # Unique canonical node list; we'll solve for V at every node except the
    # port (which is ground, V=0).
    canon = {}
    for orig, c in nodes.items():
        canon[orig] = c
    unknowns = sorted({c for c in canon.values() if c != "P"})
    idx = {n: i for i, n in enumerate(unknowns)}

    n = len(unknowns)
    G = [[0.0] * n for _ in range(n)]
    for n1, n2, r in net["resistors"]:
        if r <= 0:
            # zero-ohm shorts: merge nodes by substituting the name. A fresh
            # pass handles this via canon union-find below; but per the SPEFs
            # OpenROAD emits here, zero-R edges connect already-adjacent
            # tree nodes that we can treat as the same node without pain.
            c1, c2 = canon[n1], canon[n2]
            if c1 == c2:
                continue
            # Alias c2 → c1 everywhere.
            for k, v in list(canon.items()):
                if v == c2:
                    canon[k] = c1
            continue
        g = 1.0 / r
        c1, c2 = canon[n1], canon[n2]
        if c1 == c2:
            continue
        i1 = idx.get(c1, None)
        i2 = idx.get(c2, None)
        if i1 is not None:
            G[i1][i1] += g
        if i2 is not None:
            G[i2][i2] += g
        if i1 is not None and i2 is not None:
            G[i1][i2] -= g
            G[i2][i1] -= g

    # Recompute idx/unknowns after any zero-R merges.
    unknowns2 = sorted({c for c in canon.values() if c != "P"})
    if unknowns2 != unknowns:
        # Rebuild from scratch with the post-merge canon.
        return _solve_from_canon(canon, net["resistors"])

    # Inject 1 A at D, ground P.
    b = [0.0] * n
    d_idx = idx.get(D, None)
    if d_idx is None:
        return None
    b[d_idx] = 1.0
    v = solve(G, b)
    if v is None:
        return None
    return v[d_idx]  # V_D with I=1 A ⇒ R_DP


def _solve_from_canon(canon, resistors):
    """Second-pass solver that first resolves zero-R merges, then builds the
    G matrix over the collapsed node set."""
    # Iteratively merge across zero-R edges until stable.
    changed = True
    while changed:
        changed = False
        for n1, n2, r in resistors:
            if r > 0:
                continue
            c1, c2 = canon[n1], canon[n2]
            if c1 == c2:
                continue
            # Prefer to keep "P" as the canonical name when merging.
            keep, drop = (c1, c2) if c1 == "P" or c2 != "P" else (c2, c1)
            if keep == drop:
                continue
            for k, v in list(canon.items()):
                if v == drop:
                    canon[k] = keep
            changed = True

    unknowns = sorted({c for c in canon.values() if c != "P"})
    idx = {n: i for i, n in enumerate(unknowns)}
    n = len(unknowns)
    if n == 0:
        return None
    G = [[0.0] * n for _ in range(n)]
    for n1, n2, r in resistors:
        if r <= 0:
            continue
        c1, c2 = canon[n1], canon[n2]
        if c1 == c2:
            continue
        g = 1.0 / r
        i1 = idx.get(c1, None)
        i2 = idx.get(c2, None)
        if i1 is not None:
            G[i1][i1] += g
        if i2 is not None:
            G[i2][i2] += g
        if i1 is not None and i2 is not None:
            G[i1][i2] -= g
            G[i2][i1] -= g
    D = "__D__"
    if D not in idx:
        return None
    b = [0.0] * n
    b[idx[D]] = 1.0
    v = solve(G, b)
    if v is None:
        return None
    return v[idx[D]]


def effective_R_split(nets, finger_net_names):
    """True effective R for cap_split: N separate SPEF nets, each with one
    finger terminal and one port. The finger iterms are shorted at the
    diffusion (node D); the N ports are treated as a single external output
    node (the fair parallel-path comparison, valid whenever the N distinct
    destinations are wired to a common external aggregator). Returns the
    parallel combination of the per-net series path resistances."""
    path_rs = []
    for nn in finger_net_names:
        net = nets.get(nn)
        if net is None or not net["terminals"] or net["port"] is None:
            return None
        # Each SPEF net is a tree with one terminal and one port; a simple
        # DFS along the unique tree path gives the series R.
        adj = defaultdict(list)
        for n1, n2, r in net["resistors"]:
            adj[n1].append((n2, r))
            adj[n2].append((n1, r))
        start, end = net["terminals"][0], net["port"]
        r = _tree_path_r(adj, start, end)
        if r is None:
            return None
        path_rs.append(r)
    nonzero = [r for r in path_rs if r > 0]
    if not nonzero:
        return 0.0
    return (1.0 / sum(1.0 / r for r in nonzero), path_rs)


def _tree_path_r(adj, start, end):
    """DFS along the unique path in a tree; sums edge R."""
    stack = [(start, None, 0.0)]
    while stack:
        node, parent, acc = stack.pop()
        if node == end:
            return acc
        for nb, r in adj[node]:
            if nb == parent:
                continue
            stack.append((nb, node, acc + r))
    return None


# ── stdout parser (per-layer WL) ────────────────────────────────────────────
def parse_stdout_layers(path):
    pat = re.compile(r"Total wire length on LAYER (\w+)\s*=\s*(\d+)\s*um")
    vals = {}
    with open(path) as f:
        for line in f:
            m = pat.search(line)
            if m:
                vals[m.group(1)] = int(m.group(2))
    return vals


# ── Per-mode measurement ────────────────────────────────────────────────────
def measure(mode):
    rd = ROOT / "reports" / mode
    spef = parse_spef(rd / "parasitics.spef")
    with open(rd / "metrics.json") as f:
        mj = json.load(f)
    layers = parse_stdout_layers(rd / "stdout.log")
    groups = NET_GROUPS[mode]

    def r_for(group_key):
        nns = groups[group_key]
        if mode == "cap_split":
            res = effective_R_split(spef, nns)
            if res is None:
                return None, None
            r_eff, paths = res
            return r_eff, paths
        else:
            # conv / cap: single net, possibly multi-terminal.
            net = spef.get(nns[0])
            if net is None:
                return None, None
            return effective_R_cap(net), None

    def c_for(group_key):
        # Sum total_cap_F across the grouped SPEF nets (applies to cap_split
        # which spans multiple nets).
        return sum(spef[nn]["total_cap_F"] for nn in groups[group_key]) * 1e15

    r_drn, paths_drn = r_for("drn_p")
    r_tail, paths_tail = r_for("tail")

    return {
        "wl_total":   mj["route__wirelength"],
        "wl_met1":    layers.get("met1", -1),
        "wl_met2":    layers.get("met2", -1),
        "vias":       mj["route__vias"],
        "drc":        mj["route__drc_errors"],
        "io_ports":   {"conv": 6, "cap": 6, "cap_split": 19}[mode],
        "R_drn_p":    r_drn,
        "R_tail":     r_tail,
        "paths_drn":  paths_drn,
        "paths_tail": paths_tail,
        "C_drn_p":    c_for("drn_p"),
        "C_tail":     c_for("tail"),
        # Peak per-wire current as a fraction of total device current. In
        # conv and cap, the trunk carries full I; in cap_split the N paths
        # are disjoint so each carries I/N by transistor-finger symmetry.
        "peak_I_drn": 1.0 if mode in ("conv", "cap") else 1.0 / 4,
        "peak_I_tail": 1.0 if mode in ("conv", "cap") else 1.0 / 8,
    }


# ── Expected values ─────────────────────────────────────────────────────────
# Numbers are empirically locked to the current OpenROAD build on sky130hs;
# tolerances are chosen to be robust to minor router nondeterminism.
EXPECTED = {
    "conv": {
        "wl_total": 153, "wl_met1": 53, "wl_met2": 99,
        "vias": 6, "drc": 0, "R_drn_p": 36.1, "R_tail": 29.1,
        "C_drn_p": 3.24, "C_tail": 2.54,
    },
    "cap": {
        "wl_total": 165, "wl_met1": 68, "wl_met2": 96,
        "vias": 6, "drc": 0, "R_drn_p": 27.4, "R_tail": 23.8,
        "C_drn_p": 4.13, "C_tail": 5.65,
    },
    "cap_split": {
        "wl_total": 605, "wl_met1": 200, "wl_met2": 391,
        "vias": 25, "drc": 0, "R_drn_p": 9.1, "R_tail": 4.7,
        "C_drn_p": 13.21, "C_tail": 28.34,
    },
}
TOL = {"wl_total": 2, "wl_met1": 2, "wl_met2": 2, "vias": 0, "drc": 0,
       "R_drn_p": 0.5, "R_tail": 0.5, "C_drn_p": 0.05, "C_tail": 0.05}


# ── LaTeX emission ──────────────────────────────────────────────────────────
def _r(conv, cap):
    if conv in (0, None) or cap is None:
        return "---"
    return f"${cap / conv:.2f}\\times$"


def render_latex(got):
    """Emit the Table 3 body (conv | cap | cap_split | source) for \\input
    into 4_results.tex. The outer table frame and header row stay in
    4_results.tex; this function emits only the data rows."""
    c, s, x = got["conv"], got["cap"], got["cap_split"]
    rows = [
        # Row 1–2: analytical J and MTTF claims from Eqs.(4)–(5).
        r"Per-path $J$ (analytical)          & $I/(Wt)$   & $I/(Wt)$     & $(I/N)/(Wt)$        & Eq.~(\ref{eq:jratio}) \\",
        r"EM MTTF (Black, norm.)            & $1.00$       & $1.00$         & $N^{2}$             & Eq.~(\ref{eq:mttfratio}) \\",
        # Router-level metrics.
        f"Top-level I/O ports                & {c['io_ports']}          & {s['io_ports']}            & {x['io_ports']}                 & DEF \\\\",
        f"Total wirelength [\\textmu m]       & {c['wl_total']}        & {s['wl_total']}          & {x['wl_total']}               & TritonRoute \\\\",
        f"\\quad met1 [\\textmu m]             & {c['wl_met1']}         & {s['wl_met1']}           & {x['wl_met1']}                & TritonRoute \\\\",
        f"\\quad met2 [\\textmu m]             & {c['wl_met2']}         & {s['wl_met2']}           & {x['wl_met2']}                & TritonRoute \\\\",
        f"Via count                          & {c['vias']}          & {s['vias']}            & {x['vias']}                 & TritonRoute \\\\",
        # Electrical metrics.
        f"Eff.\\ $R_{{D\\to P}}$, drn ($N{{=}}4$) [$\\Omega$]   & {c['R_drn_p']:.1f} & {s['R_drn_p']:.1f} & {x['R_drn_p']:.1f} & SPEF + nodal \\\\",
        f"Eff.\\ $R_{{D\\to P}}$, tail ($N{{=}}8$) [$\\Omega$]  & {c['R_tail']:.1f} & {s['R_tail']:.1f} & {x['R_tail']:.1f} & SPEF + nodal \\\\",
        f"Net $C$, drn\\_p [fF]              & {c['C_drn_p']:.2f}       & {s['C_drn_p']:.2f}         & {x['C_drn_p']:.2f}             & SPEF \\\\",
        f"Net $C$, tail [fF]                & {c['C_tail']:.2f}       & {s['C_tail']:.2f}         & {x['C_tail']:.2f}             & SPEF \\\\",
        # Topology-level summary.
        r"Peak per-wire $I$ (frac.\ of device $I$) & $1$          & $1$            & $1/N$               & Router topology \\",
        f"DRC violations                     & {c['drc']}          & {s['drc']}            & {x['drc']}                  & TritonRoute \\\\",
    ]
    return "\n\\hline\n".join(rows) + "\n\\hline\n"


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--latex", action="store_true",
                        help="emit Table 3 body as a LaTeX fragment and exit")
    args = parser.parse_args()

    got = {m: measure(m) for m in MODES}

    if args.latex:
        sys.stdout.write(render_latex(got))
        return 0

    # Pretty-print the summary for human inspection.
    print(f"{'Metric':<28} {'Conv':>10} {'Cap':>10} {'Cap_split':>12}  Source")
    print("-" * 78)
    rows = [
        ("Macro LEF pins",        "6", "19", "19", "LEF"),
        ("Top-level I/O ports",    str(got['conv']['io_ports']),
                                   str(got['cap']['io_ports']),
                                   str(got['cap_split']['io_ports']), "DEF"),
        ("Total wirelength (µm)",  got['conv']['wl_total'],
                                   got['cap']['wl_total'],
                                   got['cap_split']['wl_total'], "TritonRoute"),
        ("  met1 (µm)",             got['conv']['wl_met1'],
                                   got['cap']['wl_met1'],
                                   got['cap_split']['wl_met1'], "TritonRoute"),
        ("  met2 (µm)",             got['conv']['wl_met2'],
                                   got['cap']['wl_met2'],
                                   got['cap_split']['wl_met2'], "TritonRoute"),
        ("Via count",              got['conv']['vias'],
                                   got['cap']['vias'],
                                   got['cap_split']['vias'], "TritonRoute"),
        ("DRC violations",         got['conv']['drc'],
                                   got['cap']['drc'],
                                   got['cap_split']['drc'], "TritonRoute"),
        ("Eff R D→P, drn (Ω)",     f"{got['conv']['R_drn_p']:.2f}",
                                   f"{got['cap']['R_drn_p']:.2f}",
                                   f"{got['cap_split']['R_drn_p']:.2f}", "SPEF + nodal"),
        ("Eff R D→P, tail (Ω)",    f"{got['conv']['R_tail']:.2f}",
                                   f"{got['cap']['R_tail']:.2f}",
                                   f"{got['cap_split']['R_tail']:.2f}", "SPEF + nodal"),
        ("Net C, drn (fF)",        f"{got['conv']['C_drn_p']:.2f}",
                                   f"{got['cap']['C_drn_p']:.2f}",
                                   f"{got['cap_split']['C_drn_p']:.2f}", "SPEF"),
        ("Net C, tail (fF)",       f"{got['conv']['C_tail']:.2f}",
                                   f"{got['cap']['C_tail']:.2f}",
                                   f"{got['cap_split']['C_tail']:.2f}", "SPEF"),
        ("Peak per-wire I/I_tot",  f"{got['conv']['peak_I_drn']:.3f}",
                                   f"{got['cap']['peak_I_drn']:.3f}",
                                   f"{got['cap_split']['peak_I_drn']:.3f}", "Router topology"),
    ]
    for r in rows:
        print(f"{r[0]:<28} {str(r[1]):>10} {str(r[2]):>10} {str(r[3]):>12}  {r[4]}")
    print("-" * 78)

    # Per-finger path R breakdown for cap_split (to show disjoint paths).
    pds = got['cap_split'].get('paths_drn')
    pts = got['cap_split'].get('paths_tail')
    if pds:
        print(f"cap_split per-finger path R, drn: "
              f"[{', '.join(f'{r:.2f}' for r in pds)}] Ω "
              f"(parallel combo: {got['cap_split']['R_drn_p']:.2f} Ω)")
    if pts:
        print(f"cap_split per-finger path R, tail: "
              f"[{', '.join(f'{r:.2f}' for r in pts)}] Ω "
              f"(parallel combo: {got['cap_split']['R_tail']:.2f} Ω)")

    # Validate all three modes against EXPECTED (the Table 3 values).
    print()
    ok = True
    for mode in ("conv", "cap", "cap_split"):
        for key, exp in EXPECTED[mode].items():
            got_val = got[mode][key]
            tol = TOL[key]
            if got_val is None or abs(got_val - exp) > tol:
                print(f"  FAIL {mode}.{key}: got {got_val}, expected {exp} ± {tol}")
                ok = False
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
