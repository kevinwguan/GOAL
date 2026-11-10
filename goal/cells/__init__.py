"""Process-independent primitive geometry."""

from .mosfet import mosfet
from .guardring import ring, guardring
from .diffpair import diffpair

__all__ = ["mosfet", "ring", "guardring", "diffpair"]
