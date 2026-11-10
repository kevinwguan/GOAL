#!/usr/bin/env python3
"""render_post.py -- make the OpenROAD route renders legible at print size.

Problem this solves
-------------------
The paper places the three route.png panels at 0.32\\columnwidth, i.e. about
1.12 in wide for a 50 um die.  A sky130 min-width wire is 0.14 um, so it lands
on paper at roughly 0.23 pt -- well under the ~0.5 pt hairline floor -- and the
die/macro outline OpenROAD draws is a single pixel, or about 0.05 pt.  Both are
effectively invisible in print.

Naive thickening does not work either: the dense fan-out over the macro is
routed on the met1 track pitch, so wires are 6 px wide with 6 px gaps at the
1600 px render.  Dilating uniformly past +3 px/side fuses adjacent parallel
paths into a blob -- destroying exactly the "N disjoint paths" reading panel
(c) exists to show.

So the growth here is collision-aware.  Each wire is a labelled connected
component and is grown one pixel per step, but only into pixels whose
neighbourhood contains a single label.  Isolated trunks in the open field grow
to the full cap; wires in the dense centre stop on their own once the mandated
gap is reached.  Centrelines do not move, because growth is symmetric wherever
it is not blocked.

Usage
-----
    python3 render_post.py reports/cap_split/route.png -o out.png --theme light

    # or via run.sh, which post-processes all three modes and copies them to
    # the paper's figure directory.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

# ---------------------------------------------------------------------------
# Layer classification
# ---------------------------------------------------------------------------
# Colours OpenROAD's GUI uses for the sky130hs layers in these renders, sampled
# from the raw PNGs.  Antialiased pixels are handled by the rules in classify()
# rather than by exact match.
LAYERS = ("met1", "met2", "met3", "li1", "outline")

# Draw order, bottom to top: structure first, then the layers the figure is
# actually about, with met1 (the per-finger pin geometry) on top.
DRAW_ORDER = ("outline", "li1", "met3", "met2", "met1")

THEMES = {
    # Dark keeps OpenROAD's screenshot look but brightens the wires; thin bright
    # strokes on black lose contrast fast once a printer's ink spreads.
    "dark": {
        "bg": (0, 0, 0),
        "met1": (255, 72, 62),
        "met2": (60, 214, 60),
        "met3": (90, 140, 255),
        "li1": (196, 214, 96),
        "outline": (150, 150, 155),
        "frame": (104, 104, 110),
    },
    # Light is the print-friendly option: dark strokes on white survive hairline
    # widths far better, and three panels of black background is a lot of toner.
    "light": {
        "bg": (255, 255, 255),
        "met1": (176, 26, 26),
        "met2": (20, 110, 48),
        "met3": (28, 74, 158),
        "li1": (138, 116, 24),
        "outline": (96, 96, 102),
        "frame": (150, 150, 156),
    },
    # Same as light but on the Wong colour-blind-safe palette: red/green is the
    # one pair deuteranopes cannot separate, and this figure's whole argument is
    # met1-versus-met2.  Using it means the caption must say vermilion/blue
    # instead of red/green.
    "cb": {
        "bg": (255, 255, 255),
        "met1": (213, 94, 0),
        "met2": (0, 114, 178),
        "met3": (204, 121, 167),
        "li1": (150, 122, 20),
        "outline": (96, 96, 102),
        "frame": (150, 150, 156),
    },
}

# Panel border width in pixels of the 1600 px output.  The 30 um crop took away
# the die boundary that used to delineate each panel; this puts a delineation
# back.  It is lighter in value than "outline" on purpose -- it is a crop frame,
# not geometry, and must not be mistaken for the die edge -- but it still has to
# clear the same ~0.5 pt hairline floor as everything else here, so it is set by
# weight (10 px = ~0.48 pt) and separated from the outline by value, not by width.
FRAME_PX = 10

# Target on-page stroke width per layer, in pixels of the 1600 px output.  The
# panel prints at ~1.07 in, so 1600 px maps to ~77 pt: 18 px is ~0.87 pt, comfortably
# clear of the ~0.5 pt hairline floor, and 5 px keeps the die/macro outline visible
# without turning it into a frame that competes with the wires.
TARGET_PX = {"met1": 18, "met2": 18, "met3": 16, "li1": 16, "outline": 5}

# Ceiling on growth per side, so a pathological classification cannot balloon a
# layer.  Also at the 1600 px reference.
GROW_CAP = {"met1": 7, "met2": 7, "met3": 6, "li1": 5, "outline": 4}


def modal_stroke_width(mask: np.ndarray) -> int:
    """The most common run length across rows and columns.

    Wires are axis-aligned rectangles, so the modal run is the stroke width --
    long runs along a wire's length are individually rare, while its width
    repeats once per pixel of length.  This is what makes the growth
    zoom-independent: a tighter render window puts more pixels on the same
    0.14 um wire, and the steps needed to reach TARGET_PX drop accordingly.
    """
    counts: dict[int, int] = {}
    for arr in (mask, mask.T):
        flat = np.concatenate(
            [np.zeros((arr.shape[0], 1), dtype=np.int8),
             arr.astype(np.int8),
             np.zeros((arr.shape[0], 1), dtype=np.int8)], axis=1)
        d = np.diff(flat, axis=1)
        starts = np.argwhere(d == 1)
        ends = np.argwhere(d == -1)
        if len(starts) != len(ends):
            continue
        for (r0, c0), (r1, c1) in zip(starts, ends):
            if r0 != r1:
                continue
            w = c1 - c0
            if 0 < w <= 200:
                counts[w] = counts.get(w, 0) + 1
    return max(counts, key=counts.get) if counts else 1


def classify(rgb: np.ndarray, bg_cut: int = 45) -> dict[str, np.ndarray]:
    """Split an RGB render into one boolean mask per layer.

    Dominant-channel rules rather than nearest-anchor, so the antialiased
    fringe around each wire is claimed by the wire it belongs to instead of
    being split between a layer and the background.
    """
    a = rgb.astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    total = a.sum(axis=2)
    mx, mn = a.max(axis=2), a.min(axis=2)

    lit = total >= bg_cut
    gray = lit & ((mx - mn) < 30)
    chroma = lit & ~gray

    red = chroma & (r >= g) & (r >= b)
    blue = chroma & (b > r) & (b > g)
    greenish = chroma & ~red & ~blue
    # li1's olive (134,172,57) is green-dominant too; what separates it from
    # met2's (6,156,0) is that it carries substantial red and blue.
    olive = greenish & (r > g // 2) & (b > 25)

    return {
        "met1": red,
        "met2": greenish & ~olive,
        "met3": blue,
        "li1": olive,
        "outline": gray,
    }


# ---------------------------------------------------------------------------
# Collision-aware growth
# ---------------------------------------------------------------------------
def grow_preserving_gaps(mask: np.ndarray, steps: int, gap: int) -> np.ndarray:
    """Dilate `mask` by `steps` px/side without merging distinct components.

    A background pixel is claimed only when every label inside a
    (2*gap+1)-square window around it is the same, which guarantees at least
    `gap` px of clear background between any two components that were separate
    to begin with.
    """
    if steps <= 0 or not mask.any():
        return mask.copy()

    labels, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    if n == 0:
        return mask.copy()

    win = 2 * gap + 1
    big = n + 1
    for _ in range(steps):
        empty = labels == 0
        if not empty.any():
            break
        # Any label in the 8-neighbourhood is a growth candidate...
        cand = ndimage.grey_dilation(labels, size=(3, 3))
        # ...but only if the wider window holds exactly one label, so growth
        # halts before two components can close the mandated gap.
        hi = ndimage.grey_dilation(labels, size=(win, win))
        lo = ndimage.grey_erosion(
            np.where(labels > 0, labels, big), size=(win, win)
        )
        grow = empty & (cand > 0) & (hi == lo)
        if not grow.any():
            break
        labels[grow] = cand[grow]
    return labels > 0


# ---------------------------------------------------------------------------
# Compositing
# ---------------------------------------------------------------------------
def grow_masks(
    rgb: np.ndarray, gap: int, grow_scale: float
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Classify, then grow every layer.

    Returns (cores, grown): the raw per-layer geometry and its thickened
    version.  Both are theme-independent, so they are computed once and
    composited as many times as there are themes.
    """
    cores, grown = {}, {}
    for layer, mask in classify(rgb).items():
        if not mask.any():
            continue
        # Grow to the target on-page width, not by a fixed amount: a zoomed-in
        # render already draws the same wire fatter, and would end up bloated
        # under a fixed cap.
        core = modal_stroke_width(mask)
        deficit = TARGET_PX[layer] * grow_scale - core
        steps = int(round(max(0.0, deficit) / 2))
        steps = min(steps, int(round(GROW_CAP[layer] * grow_scale)))
        cores[layer] = mask
        grown[layer] = grow_preserving_gaps(mask, steps, gap)
    return cores, grown


def composite(
    cores: dict[str, np.ndarray],
    grown: dict[str, np.ndarray],
    shape: tuple[int, int],
    theme: str = "light",
    out_px: int | None = None,
    frame: bool = True,
) -> Image.Image:
    palette = THEMES[theme]
    canvas = np.empty((*shape, 3), dtype=np.uint8)
    canvas[:] = palette["bg"]
    for layer in DRAW_ORDER:
        if layer in grown:
            canvas[grown[layer]] = palette[layer]

    # Repaint the true geometry on top of the halos.  classify() gives every
    # pixel exactly one layer, so these masks are disjoint and the pass is
    # order-independent: whatever was visible in the OpenROAD render keeps its
    # own layer colour, and thickening can only ever add to a wire, never
    # bury a neighbouring one.  Without this, met2's halo swallows the li1
    # stripe next to it entirely.  The outline is excluded -- it is the one
    # thing wires are meant to cross over.
    for layer in DRAW_ORDER:
        if layer != "outline" and layer in cores:
            canvas[cores[layer]] = palette[layer]

    if frame:
        t = max(1, int(round(FRAME_PX * (shape[0] / 1600.0))))
        col = palette.get("frame", palette["outline"])
        canvas[:t, :] = col
        canvas[-t:, :] = col
        canvas[:, :t] = col
        canvas[:, -t:] = col

    out = Image.fromarray(canvas)
    if out_px and out_px != out.width:
        # Downsampling after growth is what antialiases the result -- the
        # growth itself is hard-edged by construction.
        out = out.resize((out_px, out_px), Image.LANCZOS)
    return out


def render(
    src: Image.Image,
    theme: str = "light",
    gap: int = 2,
    grow_scale: float = 1.0,
    out_px: int | None = None,
    frame: bool = True,
) -> Image.Image:
    rgb = np.asarray(src.convert("RGB"))
    cores, grown = grow_masks(rgb, gap, grow_scale)
    return composite(cores, grown, rgb.shape[:2], theme, out_px, frame)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", type=Path, help="raw OpenROAD route.png")
    p.add_argument("-o", "--out", type=Path, required=True,
                   help="output PNG; with several --theme values, {theme} in the "
                        "path is substituted per theme")
    p.add_argument("--theme", action="append", choices=sorted(THEMES),
                   help="repeatable; default light")
    p.add_argument("--gap", type=int, default=2,
                   help="px of background kept between distinct wires (default 2)")
    p.add_argument("--out-px", type=int, default=1600,
                   help="output width in px (default 1600)")
    p.add_argument("--no-frame", dest="frame", action="store_false",
                   help="omit the panel border")
    args = p.parse_args(argv)
    themes = args.theme or ["light"]

    src = Image.open(args.src)
    rgb = np.asarray(src.convert("RGB"))
    # Growth caps are calibrated for a 1600 px render; scale them if the source
    # was rendered larger so the printed stroke width is the same either way.
    scale = src.width / 1600.0
    cores, grown = grow_masks(rgb, max(1, int(round(args.gap * scale))), scale)

    for theme in themes:
        out = composite(cores, grown, rgb.shape[:2], theme, args.out_px, args.frame)
        dest = Path(str(args.out).format(theme=theme))
        dest.parent.mkdir(parents=True, exist_ok=True)
        out.save(dest, optimize=True)
        print(f"wrote {dest} ({out.width}x{out.height}, theme={theme})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
