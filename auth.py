"""
webapp/auth.py — AD LDAP authentication and RBAC helpers.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from flask import Blueprint, request, redirect, url_for, render_template_string, current_app, session
from flask_login import UserMixin, login_user, logout_user, current_user, login_required
from ldap3 import Server, Connection, ALL, NTLM, SUBTREE
from ldap3.core.exceptions import LDAPException

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)


@dataclass
class ADUser(UserMixin):
    """Flask-Login user object populated from AD."""
    username: str
    display_name: str
    email: Optional[str]
    groups: List[str] = field(default_factory=list)   # list of group CNs
    is_admin: bool = False

    def get_id(self) -> str:
        return self.username


# In-process user cache (request-scoped via session — no persistent store needed)
_user_cache: dict = {}


def get_user(username: str) -> Optional[ADUser]:
    return _user_cache.get(username.lower())


def _store_user(user: ADUser) -> None:
    _user_cache[user.username.lower()] = user


from webapp.app import login_manager

@login_manager.user_loader
def load_user(username: str) -> Optional[ADUser]:
    return get_user(username)


def ldap_authenticate(username: str, password: str) -> Optional[ADUser]:
    """
    Bind to AD with the user's credentials. Returns an ADUser on success.
    Uses NTLM bind (works with both LDAP and LDAPS).
    """
    server_url = current_app.config["AD_SERVER"]
    domain = current_app.config["AD_DOMAIN"]
    base_dn = current_app.config["AD_BASE_DN"]
    admin_group_dn = current_app.config.get("AD_ADMIN_GROUP", "")

    try:
        server = Server(server_url, get_info=ALL)
        conn = Connection(
            server,
            user=f"{domain}\\{username}",
            password=password,
            authentication=NTLM,
            auto_bind=True,
        )
    except LDAPException as exc:
        logger.warning("LDAP bind failed for %s: %s", username, exc)
        return None

    try:
        # Fetch user attributes
        conn.search(
            base_dn,
            f"(sAMAccountName={username})",
            attributes=["displayName", "mail", "memberOf"],
            search_scope=SUBTREE,
        )
        if not conn.entries:
            return None

        entry = conn.entries[0]
        display_name = str(entry.displayName) if entry.displayName else username
        email = str(entry.mail) if entry.mail else None
        groups = [str(g) for g in entry.memberOf] if entry.memberOf else []
        is_admin = any(admin_group_dn.lower() in g.lower() for g in groups) if admin_group_dn else False

        user = ADUser(
            username=username.lower(),
            display_name=display_name,
            email=email,
            groups=groups,
            is_admin=is_admin,
        )
        _store_user(user)
        return user
    finally:
        conn.unbind()


def user_can_edit_share(user: ADUser, share_groups: List[str]) -> bool:
    """
    Returns True if the user is an admin OR a member of any group
    that has access to the share.
    share_groups: list of group_name strings from the share's share_groups rows.
    """
    if user.is_admin:
        return True
    # Check if any of the share's groups appear in the user's AD groups
    share_groups_lower = {g.lower() for g in share_groups}
    for user_group in user.groups:
        cn_part = user_group.split(",")[0].replace("CN=", "").lower()
        if cn_part in share_groups_lower:
            return True
    return False


# ── Login / logout routes ────────────────────────────────────────────────────

LOGIN_TEMPLATE = """
<!doctype html><html><head><title>Sign in</title></head><body>
<h2>Isilon Share Discovery — Sign in</h2>
{% if error %}<p style="color:red">{{ error }}</p>{% endif %}
<form method="post">
  <label>Username (CORP\\user or just user): <input name="username" autofocus></label><br>
  <label>Password: <input name="password" type="password"></label><br>
  <button type="submit">Sign in</button>
</form>
</body></html>
"""


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().split("\\")[-1]
        password = request.form.get("password", "")
        user = ldap_authenticate(username, password)
        if user:
            login_user(user)
            return redirect(url_for("shares.index"))
        return render_template_string(LOGIN_TEMPLATE, error="Invalid credentials.")
    return render_template_string(LOGIN_TEMPLATE, error=None)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
