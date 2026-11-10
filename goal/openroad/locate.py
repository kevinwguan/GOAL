"""Discover tools and platform assets exclusively from environment and PATH."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Toolchain:
    binary: Path
    platform: Path
    tech_lef: Path
    klayout_tech: Path | None = None
    rc_rules: Path | None = None


def locate(pdk) -> Toolchain:
    """Resolve OPENROAD, ORFS_DIR/PLATFORM_DIR and optional asset overrides."""
    binary = os.getenv("OPENROAD") or shutil.which("openroad")
    if not binary or not Path(binary).is_file() or not os.access(binary, os.X_OK):
        raise FileNotFoundError(
            "Set OPENROAD to an executable, or add openroad to PATH"
        )
    platform = os.getenv("PLATFORM_DIR")
    if not platform:
        orfs = os.getenv("ORFS_DIR")
        if not orfs:
            raise FileNotFoundError(
                "Set PLATFORM_DIR, or ORFS_DIR to the ORFS checkout"
            )
        platform = str(Path(orfs) / "flow/platforms" / pdk.data["platform"])
    platform = Path(platform).resolve()

    def asset(variable: str, key: str, required: bool = False) -> Path | None:
        value = os.getenv(variable)
        path = Path(value) if value else platform / pdk.data[key]
        if path.is_file():
            return path.resolve()
        if required or value:
            raise FileNotFoundError(f"Missing {variable}: {path}")
        return None

    return Toolchain(
        Path(binary).resolve(),
        platform,
        asset("TECH_LEF", "tech_lef", True),
        asset("KLAYOUT_TECH", "klayout_tech"),
        asset("RCX_RULES", "rc_rules"),
    )
