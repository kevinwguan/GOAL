"""Flat declarative process configuration, ported from reproduction/pdk.py."""

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


def layer_inventory(path: Path) -> dict[str, tuple[int, int]]:
    """Read layer pairs from a KLayout layer-properties file."""
    result = {}
    for prop in ET.parse(path).iter("properties"):
        source = prop.findtext("source") or ""
        match = re.search(r"(\d+)/(\d+)@", source)
        if match:
            pair = tuple(map(int, match.groups()))
            name = (prop.findtext("name") or source[: match.start()].strip()).split(
                " - "
            )[0]
            if name in result and result[name] != pair:
                name += f"@{pair[0]}/{pair[1]}"
            result[name] = pair
    return result


@dataclass(frozen=True)
class PDK:
    """Layer pairs, LEF vocabulary and geometric rules, all in micrometres."""

    data: dict

    @classmethod
    def load(cls, name: str | Path) -> "PDK":
        path = Path(name)
        if path.suffix != ".json":
            path = Path(__file__).parent / "data" / f"{name}.json"
        data = json.loads(path.read_text())
        for generic in data["lef_layers"]:
            if generic not in data["layers"]:
                raise ValueError(f"LEF layer {generic} lacks a GDS mapping")
        return cls(data)

    @property
    def name(self) -> str:
        return self.data["name"]

    def layer(self, name: str) -> tuple[int, int]:
        return tuple(self.data["layers"][name]["pair"])

    def rule(self, name: str) -> float:
        return self.data["rules"][name]["value"]

    def lef_layer(self, name: str) -> str:
        return self.data["lef_layers"][name]

    def validate_lef(self, tech_lef: Path) -> None:
        layers = set(re.findall(r"^\s*LAYER\s+(\S+)", tech_lef.read_text(), re.M))
        missing = set(self.data["lef_layers"].values()) - layers
        if missing:
            raise ValueError(f"LEF layers absent from technology: {sorted(missing)}")

    def verify(self, root: Path | None = None) -> dict:
        root = root or Path(os.environ["PDK_ROOT"])
        pairs = set(layer_inventory(root / self.data["layer_map"]).values())
        missing = [
            name for name in self.data["layers"] if self.layer(name) not in pairs
        ]
        if missing:
            raise ValueError(f"Unknown GDS layers: {missing}")
        return {"entries": len(self.data["layers"]), "missing_pairs": 0}
