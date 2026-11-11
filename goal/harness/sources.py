"""Distinguish declared empty GDS structures from unresolved cross-file refs."""

import struct
from pathlib import Path


def declared_cells(path: Path) -> set[str]:
    """Read STRNAME records without interpreting geometry or changing the input."""
    names = set()
    with path.open("rb") as stream:
        while header := stream.read(4):
            if len(header) != 4:
                raise ValueError(f"Truncated GDS header: {path}")
            size, kind = struct.unpack(">HH", header)
            if size < 4 or size % 2:
                raise ValueError(f"Invalid GDS record length: {path}")
            payload = stream.read(size - 4)
            if len(payload) != size - 4:
                raise ValueError(f"Truncated GDS record: {path}")
            if kind == 0x0606:
                names.add(payload.rstrip(b"\0").decode("ascii"))
    return names
