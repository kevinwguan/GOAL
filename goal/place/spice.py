"""SPICE connectivity reader ported from reproduction/placement.py."""

import re
import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    name: str
    kind: str
    nets: tuple
    model: str
    params: dict


def parse_spice(text: str) -> list[Device]:
    """Parse MOS, resistor and capacitor connectivity, ignoring directives."""
    lines = []
    for raw in text.splitlines():
        line = raw.split("$")[0].strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            if not lines:
                raise ValueError("orphan continuation")
            lines[-1] += " " + line[1:]
        else:
            lines.append(line)
    devices = []
    for line in lines:
        words = shlex.split(line)
        if words[0].startswith("."):
            continue
        cls = words[0][0].upper()
        if cls == "M":
            if len(words) < 6:
                raise ValueError(line)
            model = words[5]
            kind = (
                "pmos"
                if "pfet" in model.lower() or model.lower().startswith("p")
                else "nmos"
            )
            params = {}
            for item in words[6:]:
                (k, v) = item.split("=", 1)
                params[k.lower()] = v
            devices.append(Device(words[0], kind, tuple(words[1:5]), model, params))
        elif cls in ("R", "C"):
            if len(words) < 4:
                raise ValueError(line)
            devices.append(
                Device(
                    words[0],
                    "resistor" if cls == "R" else "capacitor",
                    tuple(words[1:3]),
                    words[3],
                    {},
                )
            )
        else:
            raise ValueError(f"unsupported element: {words[0]}")
    if len({d.name for d in devices}) != len(devices):
        raise ValueError("duplicate device name")
    return sorted(devices, key=lambda d: d.name)


def micron(value: str | None, default: float) -> float:
    """Convert a SPICE SI length literal into micrometres."""
    if value is None:
        return default
    match = re.fullmatch("([\\d.eE+-]+)([a-zA-Z]*)", value)
    if not match:
        raise ValueError(value)
    (number, suffix) = match.groups()
    scales = {"": 1000000.0, "u": 1.0, "n": 0.001, "m": 1000.0, "p": 1e-06}
    return float(number) * scales[suffix.lower()]
