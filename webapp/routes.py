"""
webapp/routes.py — Share views and edit endpoints.

Endpoints:
  GET  /             → share list (all users, read-only)
  GET  /shares/<id>  → share detail
  GET  /shares/<id>/edit → edit form (owners + admins only)
  POST /shares/<id>/edit → save user-managed fields
  GET  /api/shares   → JSON API for the share table
"""
from __future__ import annotations
import sqlite3
from flask import Blueprint, current_app, jsonify, redirect, request, url_for, render_template_string, abort
from flask_login import login_required, current_user

from webapp.auth import user_can_edit_share

shares_bp = Blueprint("shares", __name__)

# ── User-editable fields (intentionally left blank by Python enricher) ───────
USER_EDITABLE_FIELDS = ["dfs_pseudo_path", "data_type", "data_owner", "migration_notes", "migration_priority"]


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(current_app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_share_groups(conn: sqlite3.Connection, share_id: int) -> list:
    return [row["group_name"] for row in conn.execute("""
        SELECT g.group_name FROM share_groups sg
        JOIN security_groups g ON g.id = sg.group_id
        WHERE sg.share_id = ?
    """, (share_id,)).fetchall()]


# ── Share list ────────────────────────────────────────────────────────────────

INDEX_TEMPLATE = """
<!doctype html><html><head><title>Share Inventory</title></head><body>
<h2>File Share Inventory</h2>
<p>Logged in as <strong>{{ user.display_name }}</strong>
{% if user.is_admin %}<span style="color:green">[Admin]</span>{% endif %}
— <a href="/logout">sign out</a></p>
<table border="1" cellpadding="4">
<tr>
  <th>Node</th><th>Name</th><th>Type</th><th>Path</th>
  <th>DFS Path</th><th>Data Type</th><th>Quota (GB)</th>
  <th>Groups</th><th>PS Enriched</th><th>Actions</th>
</tr>
{% for s in shares %}
<tr>
  <td>{{ s.node_name }}</td>
  <td>{{ s.name }}</td>
  <td>{{ s.share_type }}</td>
  <td><small>{{ s.path }}</small></td>
  <td>{{ s.dfs_pseudo_path or '' }}</td>
  <td>{{ s.data_type or '' }}</td>
  <td>{{ s.quota_hard_gb or '' }}</td>
  <td>{{ s.group_count }}</td>
  <td>{{ '✓' if s.ps_enriched_at else '…' }}</td>
  <td><a href="/shares/{{ s.id }}">view</a>
  {% if s.can_edit %} | <a href="/shares/{{ s.id }}/edit">edit</a>{% endif %}</td>
</tr>
{% endfor %}
</table>
</body></html>
"""


@shares_bp.route("/")
@login_required
def index():
    conn = get_db()
    rows = conn.execute("""
        SELECT s.id, s.name, s.share_type, s.path, s.access_zone,
               s.dfs_pseudo_path, s.data_type, s.data_owner,
               s.ps_enriched_at, s.migration_priority,
               n.name AS node_name,
               q.hard_limit_bytes,
               COUNT(DISTINCT sg.group_id) AS group_count
        FROM shares s
        LEFT JOIN nodes n ON n.id = s.node_id
        LEFT JOIN quotas q ON q.share_id = s.id AND q.quota_type='directory'
        LEFT JOIN share_groups sg ON sg.share_id = s.id
        GROUP BY s.id
        ORDER BY n.name, s.name
    """).fetchall()

    shares = []
    for r in rows:
        d = dict(r)
        hard_bytes = d.pop("hard_limit_bytes", None)
        d["quota_hard_gb"] = round(hard_bytes / 1_073_741_824, 1) if hard_bytes else None
        share_groups = get_share_groups(conn, d["id"])
        d["can_edit"] = user_can_edit_share(current_user, share_groups)
        shares.append(d)

    conn.close()
    return render_template_string(INDEX_TEMPLATE, shares=shares, user=current_user)


# ── Share detail ─────────────────────────────────────────────────────────────

@shares_bp.route("/shares/<int:share_id>")
@login_required
def detail(share_id: int):
    conn = get_db()
    share = conn.execute("SELECT s.*, n.name AS node_name FROM shares s LEFT JOIN nodes n ON n.id=s.node_id WHERE s.id=?", (share_id,)).fetchone()
    if not share:
        abort(404)
    share = dict(share)

    quota = conn.execute("SELECT * FROM quotas WHERE share_id=? AND quota_type='directory'", (share_id,)).fetchone()
    groups = conn.execute("""
        SELECT g.*, sg.permission_type, sg.permission_level
        FROM share_groups sg JOIN security_groups g ON g.id=sg.group_id
        WHERE sg.share_id=?
    """, (share_id,)).fetchall()
    members = conn.execute("""
        SELECT m.*, g.group_name FROM group_members gm
        JOIN ad_members m ON m.id=gm.member_id
        JOIN security_groups g ON g.id=gm.group_id
        WHERE gm.group_id IN (SELECT group_id FROM share_groups WHERE share_id=?)
        ORDER BY g.group_name, m.display_name
    """, (share_id,)).fetchall()
    conn.close()

    share_group_names = [g["group_name"] for g in groups]
    can_edit = user_can_edit_share(current_user, share_group_names)

    return jsonify({
        "share": share,
        "quota": dict(quota) if quota else None,
        "security_groups": [dict(g) for g in groups],
        "members": [dict(m) for m in members],
        "can_edit": can_edit,
    })


# ── Edit share (user-managed fields) ─────────────────────────────────────────

EDIT_TEMPLATE = """
<!doctype html><html><head><title>Edit Share</title></head><body>
<h2>Edit: {{ share.name }}</h2>
<p><a href="/">← back</a></p>
<form method="post">
  <label>DFS pseudo-path (\\\\dfs\\dept\\share):<br>
    <input name="dfs_pseudo_path" value="{{ share.dfs_pseudo_path or '' }}" size="60">
  </label><br><br>
  <label>Data type (Finance / HR / Engineering / etc):<br>
    <input name="data_type" value="{{ share.data_type or '' }}" size="40">
  </label><br><br>
  <label>Business data owner (name or email):<br>
    <input name="data_owner" value="{{ share.data_owner or '' }}" size="40">
  </label><br><br>
  <label>Migration notes:<br>
    <textarea name="migration_notes" rows="4" cols="60">{{ share.migration_notes or '' }}</textarea>
  </label><br><br>
  <label>Migration priority (1=high, 2=medium, 3=low):<br>
    <select name="migration_priority">
      <option value="">— not set —</option>
      <option value="1" {% if share.migration_priority == 1 %}selected{% endif %}>1 — High</option>
      <option value="2" {% if share.migration_priority == 2 %}selected{% endif %}>2 — Medium</option>
      <option value="3" {% if share.migration_priority == 3 %}selected{% endif %}>3 — Low</option>
    </select>
  </label><br><br>
  <button type="submit">Save</button>
</form>
</body></html>
"""


@shares_bp.route("/shares/<int:share_id>/edit", methods=["GET", "POST"])
@login_required
def edit(share_id: int):
    conn = get_db()
    share = conn.execute("SELECT * FROM shares WHERE id=?", (share_id,)).fetchone()
    if not share:
        abort(404)

    share_group_names = get_share_groups(conn, share_id)
    if not user_can_edit_share(current_user, share_group_names):
        abort(403)

    if request.method == "POST":
        updates = {f: request.form.get(f) or None for f in USER_EDITABLE_FIELDS}
        if updates.get("migration_priority"):
            updates["migration_priority"] = int(updates["migration_priority"])
        set_clause = ", ".join(f"{k}=:{k}" for k in updates)
        conn.execute(f"UPDATE shares SET {set_clause} WHERE id=:id", {**updates, "id": share_id})
        conn.commit()
        conn.close()
        return redirect(url_for("shares.index"))

    conn.close()
    return render_template_string(EDIT_TEMPLATE, share=dict(share))


# ── JSON API ──────────────────────────────────────────────────────────────────

@shares_bp.route("/api/shares")
@login_required
def api_shares():
    conn = get_db()
    rows = conn.execute("""
        SELECT s.*, n.name AS node_name,
               q.hard_limit_bytes, q.usage_bytes
        FROM shares s
        LEFT JOIN nodes n ON n.id=s.node_id
        LEFT JOIN quotas q ON q.share_id=s.id AND q.quota_type='directory'
        ORDER BY n.name, s.name
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])
