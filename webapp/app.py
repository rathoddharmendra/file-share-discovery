"""
webapp/app.py — Flask application factory.

RBAC model:
  - All authenticated AD users can VIEW all shares (read-only).
  - Share owners (members of a share's linked AD group) can EDIT
    the user-managed fields on their share(s).
  - Members of AD_ADMIN_GROUP (from .env) can edit all shares.

Authentication: LDAP bind via ldap3 using the user's AD credentials.
  No separate user table — identity comes from AD on every login.
  Session stores: username, display_name, is_admin flag.

To run in dev:
    flask --app webapp.app run --debug

In production, run behind gunicorn + nginx with Windows SSPI for
transparent Kerberos SSO (optional enhancement — not in this version).
"""
from __future__ import annotations
import os
from flask import Flask
from flask_login import LoginManager
from isilon_discovery.config import load_secrets

login_manager = LoginManager()


def create_app(config_override: dict = None) -> Flask:
    # Load secrets into environment variables (supports ISILON_ENV_FILE).
    # For local dev, it's okay if the env file doesn't exist yet.
    try:
        load_secrets()
    except FileNotFoundError:
        pass

    app = Flask(__name__, template_folder="templates")

    # Secret key for session signing — MUST come from env, never hardcoded
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-insecure-change-me")
    app.config["DB_PATH"] = os.environ.get("DB_PATH", "./shares.db")
    app.config["AD_SERVER"] = os.environ.get("AD_SERVER", "ldap://dc01.corp.local")
    app.config["AD_DOMAIN"] = os.environ.get("AD_DOMAIN", "CORP")
    app.config["AD_BASE_DN"] = os.environ.get("AD_BASE_DN", "DC=corp,DC=local")
    app.config["AD_ADMIN_GROUP"] = os.environ.get("AD_ADMIN_GROUP", "")

    if config_override:
        app.config.update(config_override)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    # Register blueprints
    from webapp.auth import auth_bp
    from webapp.routes import shares_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(shares_bp)

    return app
