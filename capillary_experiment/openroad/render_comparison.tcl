# render_comparison.tcl — Render a routed design to PNG for the paper figure.
#
# Expects env vars:
#   PLATFORM_DIR  — sky130hs platform root
#   EXPERIMENT    — capillary_experiment root
#   MODE          — "conv" or "cap"
#
# Invoked by run.sh with QT_QPA_PLATFORM=offscreen so no X display is needed.
# gui::save_image returns a PNG covering the given micron bbox at the given
# pixel width.

set PLATFORM_DIR $::env(PLATFORM_DIR)
set EXPERIMENT   $::env(EXPERIMENT)
set MODE         $::env(MODE)

set tech_lef   "$PLATFORM_DIR/lef/sky130_fd_sc_hs.tlef"
set cell_lef   "$PLATFORM_DIR/lef/sky130_fd_sc_hs_merged.lef"
set macro_lef  "$EXPERIMENT/diffpair_${MODE}.lef"
set routed_def "$EXPERIMENT/reports/$MODE/routed.def"
set out_png    "$EXPERIMENT/reports/$MODE/route.png"

read_lef $tech_lef
read_lef $cell_lef
read_lef $macro_lef
read_def $routed_def

# Zoom window in microns.  All three modes MUST share the same window or the
# comparison stops being visually fair.
# The die is 50x50 with the macro at (21,22)-(29,28), but routing reaches every
# die edge in all three modes, so there is no empty margin to reclaim -- any
# zoom crops real geometry.  The central 34 um is the chosen trade: it is where
# the per-finger pin abstraction becomes legible at the paper's ~1.07 in panel
# width (at full-die zoom, Conv and Cap are indistinguishable blobs) while still
# leaving air around the fan-out.  What it gives up is the die boundary and the
# I/O ports sitting on it.  Override with RENDER_WINDOW="lo hi".
lassign [split [expr {[info exists ::env(RENDER_WINDOW)] ? $::env(RENDER_WINDOW) : "8 42"}]] xlo xhi
set ylo $xlo
set yhi $xhi
# Rendered at 2x the 1600 px the paper ships.  render_post.py thickens the
# wires to clear the print hairline floor and then downsamples back to 1600,
# which is what antialiases the thickened edges -- growth is hard-edged by
# construction, so without the supersample the result has stair-stepped
# diagonals and via corners.
set width_px 3200

# Hide noise so pin/route geometry dominates: the "u0" instance name label
# and the macro's met1 OBS blockage fill (stippled pink interior). The macro
# outline stays via Instances/Macro; pins stay via Misc/Instances/Pins.
# set_display_controls only works inside a GUI session, so wrap the render in
# gui::show (second arg false = run then close, works under offscreen Qt).
puts ">>> Saving image $out_png (area $xlo,$ylo .. $xhi,$yhi, $width_px px wide)"
gui::show "
  gui::set_display_controls {Misc/Instances/Names} visible false
  gui::set_display_controls {Misc/Instances/Blockages} visible false
  gui::save_image $out_png $xlo $ylo $xhi $yhi $width_px
" false
puts ">>> Wrote $out_png"
exit
