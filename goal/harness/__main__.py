"""Build and check the declared Sky130 demonstration pad ring."""

import argparse
import json
from pathlib import Path

from goal.pdk import PDK

from . import build_ring, check_ring, sky130_example

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
pdk = PDK.load("sky130A")
metadata = build_ring(sky130_example(), pdk, args.out)
result = check_ring(metadata, pdk, args.out)
print(
    json.dumps(
        {
            key: result[key]
            for key in (
                "ring_drc",
                "instance_weighted_baseline",
                "drc_delta",
                "lef_exit",
            )
        },
        indent=2,
    )
)
