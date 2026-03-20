"""
Compatibility wrapper for `enricher.py` at the repository root.
"""

from enricher import IsilonSession, ShareEnricher  # type: ignore

__all__ = ["IsilonSession", "ShareEnricher"]

