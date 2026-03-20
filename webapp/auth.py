"""
Compatibility wrapper for `auth.py` at the repository root.
"""

from auth import (  # type: ignore
    ADUser,
    auth_bp,
    ldap_authenticate,
    user_can_edit_share,
    get_user,
)

__all__ = [
    "ADUser",
    "auth_bp",
    "ldap_authenticate",
    "user_can_edit_share",
    "get_user",
]

