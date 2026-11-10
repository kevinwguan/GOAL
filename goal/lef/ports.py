"""Access rectangles follow the complete GDSFactory port transform."""

import klayout.db as kdb


def port_box(port) -> tuple[float, float, float, float]:
    """Transform stored port-local corners, including rotation and reflection.

    Rectangular LEF supports orthogonal unit-scale transforms only; reject
    oblique rotations instead of silently exposing a larger access rectangle.
    """
    transform = port.dcplx_trans
    if abs(transform.angle % 90) > 1e-6 or abs(transform.mag - 1) > 1e-6:
        raise ValueError("LEF port rectangles require orthogonal unit-scale transforms")
    points = [transform * kdb.DPoint(*xy) for xy in port.info["rect_local"]]
    return (
        min(p.x for p in points),
        min(p.y for p in points),
        max(p.x for p in points),
        max(p.y for p in points),
    )
