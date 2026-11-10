"""Blackboxes and net aliases use ordinary Verilog, never LEF extensions."""

import re
from pathlib import Path


def identifier(value: str) -> str:
    """Accept a portable subset shared by Verilog, LEF, DEF and Tcl."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Unsupported identifier: {value!r}")
    return value


def blackbox(macro: str, aliases: dict[str, str]) -> str:
    macro = identifier(macro)
    pins = [identifier(p) for p in aliases]
    return (
        f"(* blackbox *) module {macro}({', '.join(pins)});\n"
        + "".join(f"  inout {p};\n" for p in pins)
        + "endmodule\n"
    )


def connections(aliases: dict[str, str], cap_split: bool = False) -> dict[str, str]:
    return {
        identifier(pin): identifier(pin if cap_split else net)
        for pin, net in aliases.items()
    }


def write_wrapper(
    macro: str,
    aliases: dict[str, str],
    path: Path,
    cap_split: bool = False,
    top: str = "goal_top",
) -> dict[str, str]:
    """Join aliases electrically, or expose each physical pin as its own IO."""
    mapping = connections(aliases, cap_split)
    nets = sorted(set(mapping.values()))
    text = f"module {identifier(top)}({', '.join(nets)});\n"
    text += "".join(f"  inout {net};\n" for net in nets)
    text += (
        f"  {identifier(macro)} pair ("
        + ", ".join(f".{pin}({net})" for pin, net in mapping.items())
        + ");\nendmodule\n"
    )
    Path(path).write_text(text)
    return mapping
