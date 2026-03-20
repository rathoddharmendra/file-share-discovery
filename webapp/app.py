"""
Compatibility wrapper for `app.py` at the repository root.
"""

from app import create_app, login_manager  # type: ignore

__all__ = ["create_app", "login_manager"]

