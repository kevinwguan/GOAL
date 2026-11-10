"""Measured route metrics, with absent observations represented as null."""

import re


def scrub(text: str, replacements: dict[str, str] | None = None) -> str:
    """Remove absolute user/tool paths from captured logs and diagnostic text."""
    for source, target in sorted(
        (replacements or {}).items(), key=lambda x: -len(x[0])
    ):
        text = text.replace(source, target)
    return re.sub(r"/(?:home|Users)/[^\s{}\[\](),;]+", "$PRIVATE_PATH", text)


def parse_metrics(log: str, raw: dict, runtime: float, method: str) -> dict:
    def last(pattern: str):
        values = re.findall(pattern, log, re.I)
        return float(values[-1]) if values else None

    length = raw.get("route__wirelength", raw.get("detailedroute__route__wirelength"))
    vias = raw.get("route__vias", raw.get("detailedroute__route__vias"))
    violations = raw.get(
        "route__drc_errors", raw.get("detailedroute__route__drc_errors")
    )
    return dict(
        wirelength_um=length
        if length is not None
        else last(r"(?:total wire length|wire length)\s*[:=]\s*([\d.]+)"),
        via_count=vias
        if vias is not None
        else last(r"(?:total number of vias|total via count)\s*[:=]\s*(\d+)"),
        drc_violations=violations
        if violations is not None
        else last(r"(?:number of violations|total violations)\s*[:=]\s*(\d+)"),
        runtime_s=runtime,
        parasitics=method,
        errors=re.findall(r"\[ERROR[^\n]*", log),
        warnings=re.findall(r"\[WARNING[^\n]*", log),
    )
