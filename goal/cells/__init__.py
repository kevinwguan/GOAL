"""Process-independent primitive geometry."""

from .diffpair import diffpair
from .guardring import guardring, ring
from .mosfet import mosfet

__all__ = ["mosfet", "ring", "guardring", "diffpair"]
