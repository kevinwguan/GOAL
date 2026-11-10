# run_comparison.tcl — Route a diffpair macro in conventional or capillary
# LEF mode and dump routing metrics.
#
# Expects environment variables:
#   PLATFORM_DIR  — path to sky130hs platform
#   EXPERIMENT    — path to capillary_experiment root
#   MODE          — "conv" or "cap"

set PLATFORM_DIR $::env(PLATFORM_DIR)
set EXPERIMENT   $::env(EXPERIMENT)
set MODE         $::env(MODE)

set tech_lef   "$PLATFORM_DIR/lef/sky130_fd_sc_hs.tlef"
set cell_lef   "$PLATFORM_DIR/lef/sky130_fd_sc_hs_merged.lef"
set macro_lef  "$EXPERIMENT/diffpair_${MODE}.lef"
set placed_def "$EXPERIMENT/placed_${MODE}.def"
set report_dir "$EXPERIMENT/reports/$MODE"

file mkdir $report_dir

# ── 1. Read technology + macro LEF ──────────────────────────────────────────
puts ">>> Reading LEFs..."
read_lef $tech_lef
read_lef $cell_lef
read_lef $macro_lef

# ── 2. Read pre-placed DEF (has macro + I/O pins + net connectivity) ───────
puts ">>> Reading placed DEF ($MODE)..."
read_def $placed_def

# ── 3. Create routing tracks ───────────────────────────────────────────────
make_tracks

# ── 4. Verify net connectivity ─────────────────────────────────────────────
set db [::ord::get_db]
set chip [$db getChip]
set block [$chip getBlock]
set nets [$block getNets]
puts "\n>>> Design has [llength $nets] nets:"
foreach net $nets {
    set nname [$net getName]
    set iterms [$net getITerms]
    set bterms [$net getBTerms]
    puts "  net $nname: [llength $iterms] iterm(s), [llength $bterms] bterm(s)"
}

# ── 5. Global route ────────────────────────────────────────────────────────
puts "\n>>> Running global route ($MODE mode)..."
global_route -guide_file $report_dir/route.guide \
             -congestion_iterations 50

# ── 6. Detailed route ──────────────────────────────────────────────────────
puts "\n>>> Running detailed route ($MODE mode)..."
detailed_route -output_drc $report_dir/drc.rpt

# ── 7. Collect metrics ─────────────────────────────────────────────────────
puts "\n========== RESULTS ($MODE mode) =========="

# Parasitic estimation (post-global-route gives RC estimates)
puts "--- Parasitic estimation ---"
estimate_parasitics -global_routing -spef_file $report_dir/parasitics.spef

# Per-net wirelength from the DB
set nets [$block getNets]
puts "\n--- Per-net wirelength (from detailed route) ---"
foreach net $nets {
    set nname [$net getName]
    set wire [$net getWire]
    if {$wire != "NULL"} {
        puts "  net $nname: wire exists"
    } else {
        puts "  net $nname: no wire"
    }
}

# Write routed DEF for inspection
write_def $report_dir/routed.def

# The key metrics (total wirelength and via count) are printed by
# TritonRoute in the stdout above; they'll be captured in stdout.log
# by the run.sh wrapper.

puts "\n>>> Reports written to $report_dir/"
puts ">>> Done ($MODE mode)."
