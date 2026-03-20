"""
Compatibility wrapper for `routes.py` at the repository root.
"""

from routes import shares_bp, USER_EDITABLE_FIELDS  # type: ignore

__all__ = ["shares_bp", "USER_EDITABLE_FIELDS"]

