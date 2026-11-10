#!/usr/bin/env bash
# run.sh — Run the capillary-vs-conventional routing comparison.
#
# Usage:  ./run.sh [conv|cap|cap_split|all|render|post|latex|paper]
#   conv | cap | cap_split   single-mode route + parasitics (overwrites reports/$MODE)
#   all                      conv, cap, and cap_split (default)
#   render                   render reports/*/routed.def → route.png, then
#                            post-process → $FIG_DIR/capillary_*.png
#                            (set FIG_THEME=light|dark|cb; default light)
#   post                     post-process only (no OpenROAD): committed
#                            reports/*/route.png → $FIG_DIR/capillary_*.png
#   latex                    regenerate the Table 3 body via `verify.py --latex`
#                            → $TABLE_DIR/capillary_comparison_body.tex
#   paper                    all + render + latex (produces everything the paper
#                            ingests: routed.def, SPEF, PNGs, LaTeX fragment)
#
# Tool locations (environment):
#   ORFS_DIR      OpenROAD-flow-scripts checkout (default: ./OpenROAD-flow-scripts
#                 next to this script; a symlink is fine and is git-ignored)
#   OPENROAD      openroad binary   (default: $ORFS_DIR/tools/install/OpenROAD/bin/openroad)
#   PLATFORM_DIR  sky130hs platform (default: $ORFS_DIR/flow/platforms/sky130hs)
# Output locations (environment):
#   PAPER_DIR     paper LaTeX root; if set, figures go to $PAPER_DIR/figures and
#                 the table body to $PAPER_DIR/tables. Otherwise both go to ./out/.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORFS_DIR="${ORFS_DIR:-$SCRIPT_DIR/OpenROAD-flow-scripts}"
OPENROAD="${OPENROAD:-$ORFS_DIR/tools/install/OpenROAD/bin/openroad}"
PLATFORM_DIR="${PLATFORM_DIR:-$ORFS_DIR/flow/platforms/sky130hs}"
TCL="$SCRIPT_DIR/openroad/run_comparison.tcl"
RENDER_TCL="$SCRIPT_DIR/openroad/render_comparison.tcl"
if [[ -n "${PAPER_DIR:-}" ]]; then
    FIG_DIR="$PAPER_DIR/figures"
    TABLE_DIR="$PAPER_DIR/tables"
else
    FIG_DIR="$SCRIPT_DIR/out"
    TABLE_DIR="$SCRIPT_DIR/out"
fi
PAPER_TABLE="$TABLE_DIR/capillary_comparison_body.tex"
PAPER_FIGS="$FIG_DIR"
FIG_THEME="${FIG_THEME:-light}"

need_openroad() {
    if [[ ! -x "$OPENROAD" ]]; then
        echo "openroad not found at $OPENROAD (set ORFS_DIR or OPENROAD)" >&2; exit 1
    fi
    if [[ ! -d "$PLATFORM_DIR/lef" ]]; then
        echo "sky130hs platform not found at $PLATFORM_DIR (set ORFS_DIR or PLATFORM_DIR)" >&2; exit 1
    fi
}

run_mode() {
    local mode=$1
    need_openroad
    mkdir -p "$SCRIPT_DIR/reports/${mode}"
    echo "============================================"
    echo "  Running $mode mode"
    echo "============================================"
    PLATFORM_DIR="$PLATFORM_DIR" \
    EXPERIMENT="$SCRIPT_DIR" \
    MODE="$mode" \
    "$OPENROAD" -no_splash -exit "$TCL" \
        -log "$SCRIPT_DIR/reports/${mode}/openroad.log" \
        -metrics "$SCRIPT_DIR/reports/${mode}/metrics.json" \
        2>&1 | tee "$SCRIPT_DIR/reports/${mode}/stdout.log"
    echo ""
}

render_mode() {
    local mode=$1
    need_openroad
    echo "--- Rendering $mode to reports/$mode/route.png ---"
    # QT_QPA_PLATFORM=offscreen avoids needing an X display.
    QT_QPA_PLATFORM=offscreen \
    PLATFORM_DIR="$PLATFORM_DIR" \
    EXPERIMENT="$SCRIPT_DIR" \
    MODE="$mode" \
    "$OPENROAD" -no_splash -exit "$RENDER_TCL" 2>&1 | tail -5
}

# The raw render is a 3200 px screenshot; the paper places it at 0.32\columnwidth
# (~1.12 in), where a min-width wire lands at ~0.3 pt and the outline at ~0.05 pt.
# render_post.py thickens both without fusing adjacent parallel paths, and writes
# the 1600 px PNG the paper actually ingests.  Panel (c) is reports/cap_split but
# ships as capillary_split.png, hence the mapping.
post_mode() {
    local mode=$1
    local fig
    case "$mode" in
        conv)      fig=capillary_conv.png  ;;
        cap)       fig=capillary_cap.png   ;;
        cap_split) fig=capillary_split.png ;;
        *) echo "post_mode: unknown mode $mode" >&2; return 1 ;;
    esac
    echo "--- Post-processing $mode -> $fig (theme=$FIG_THEME) ---"
    mkdir -p "$PAPER_FIGS"
    python3 -I "$SCRIPT_DIR/render_post.py" \
        "$SCRIPT_DIR/reports/$mode/route.png" \
        -o "$PAPER_FIGS/$fig" --theme "$FIG_THEME"
}

emit_latex() {
    echo "--- Emitting Table 3 body → $PAPER_TABLE ---"
    mkdir -p "$(dirname "$PAPER_TABLE")"
    python3 -I "$SCRIPT_DIR/verify.py" --latex > "$PAPER_TABLE"
    echo "Wrote $PAPER_TABLE ($(wc -l < "$PAPER_TABLE") lines)"
}

TARGET="${1:-all}"

case "$TARGET" in
    conv)      run_mode conv ;;
    cap)       run_mode cap  ;;
    cap_split) run_mode cap_split ;;
    both)  # backward-compat alias
        run_mode conv
        run_mode cap
        ;;
    all)
        run_mode conv
        run_mode cap
        run_mode cap_split
        echo "============================================"
        echo "  Comparison complete. Reports in:"
        echo "    $SCRIPT_DIR/reports/conv/"
        echo "    $SCRIPT_DIR/reports/cap/"
        echo "    $SCRIPT_DIR/reports/cap_split/"
        echo "============================================"
        ;;
    render)
        for m in conv cap cap_split; do render_mode "$m"; post_mode "$m"; done
        ;;
    post)
        for m in conv cap cap_split; do post_mode "$m"; done
        ;;
    latex)
        emit_latex
        ;;
    paper)
        run_mode conv
        run_mode cap
        run_mode cap_split
        for m in conv cap cap_split; do render_mode "$m"; post_mode "$m"; done
        emit_latex
        echo "============================================"
        echo "  Paper artifacts refreshed:"
        echo "    $PAPER_FIGS/capillary_{conv,cap,split}.png (figure)"
        echo "    $PAPER_TABLE (Table 3 body)"
        echo "============================================"
        ;;
    *)
        echo "Usage: $0 [conv|cap|cap_split|all|render|post|latex|paper]"
        exit 1
        ;;
esac
