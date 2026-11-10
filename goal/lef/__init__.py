"""Port-driven LEF engine. Imports are lazy to avoid cell/engine cycles."""


def write_abstract(*args, **kwargs):
    from .engine import write_abstract as emit

    return emit(*args, **kwargs)


__all__ = ["write_abstract"]
