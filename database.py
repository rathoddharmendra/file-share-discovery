"""
database.py — SQLite DDL, CRUD operations, and schema management.

Design decisions:
  - Uses Python's stdlib sqlite3 — no ORM, no extra dependency.
  - Row factory set to sqlite3.Row so results behave like dicts.
  - All schema changes are additive (ALTER TABLE ADD COLUMN) to support
    upgrading a live database without data loss.
  - Write operations use context managers for automatic commit/rollback.
  - Thread safety: single connection per Database instance. The Python
    enricher is async but uses asyncio's thread executor for DB writes.
    PowerShell accesses the file as a separate process (no concurrent writes
    by design — schedule them to not overlap).
"""
from __future__ import annotations
import sqlite3
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional

from isilon_discovery.models import (
    NodeRecord, ShareRecord, QuotaRecord,
    SecurityGroupRecord, ShareGroupLink,
    ADMemberRecord, GroupMemberLink, RunLogRecord,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1   # increment when adding new tables; run migrations on open


class Database:
    """
    Single-file SQLite database wrapper.
    Instantiate once in main.py and pass to enricher + snapshot.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")   # safe for multi-process reads
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._initialise_schema()
        logger.info("Database connected: %s", self.db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager: auto-commit on exit, rollback on exception."""
        assert self._conn, "Call connect() first."
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    @property
    def conn(self) -> sqlite3.Connection:
        assert self._conn, "Call connect() first."
        return self._conn

    # ------------------------------------------------------------------
    # Schema creation and migrations
    # ------------------------------------------------------------------

    def _initialise_schema(self) -> None:
        with self.transaction() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version     INTEGER PRIMARY KEY
                );

                CREATE TABLE IF NOT EXISTS nodes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT NOT NULL UNIQUE,
                    host            TEXT NOT NULL,
                    port            INTEGER NOT NULL DEFAULT 8080,
                    onefs_version   TEXT,
                    last_seen_at    TEXT
                );

                CREATE TABLE IF NOT EXISTS shares (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id             INTEGER NOT NULL REFERENCES nodes(id),
                    name                TEXT NOT NULL,
                    share_type          TEXT NOT NULL CHECK(share_type IN ('smb','nfs')),
                    path                TEXT NOT NULL,
                    access_zone         TEXT NOT NULL DEFAULT 'System',
                    description         TEXT,
                    enabled             INTEGER NOT NULL DEFAULT 1,
                    permissions_mode    TEXT,
                    is_dfs_target       INTEGER NOT NULL DEFAULT 0,
                    owner_sid           TEXT,
                    created_at          TEXT,
                    last_enriched_at    TEXT,
                    -- ps_managed fields (PowerShell writes these)
                    dfs_pseudo_path     TEXT,
                    ps_enriched_at      TEXT,
                    -- user_managed fields (web app)
                    data_type           TEXT,
                    data_owner          TEXT,
                    migration_notes     TEXT,
                    migration_priority  INTEGER,
                    -- delta tracking
                    exists_in_snapshot  INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(node_id, name, share_type, access_zone)
                );

                CREATE TABLE IF NOT EXISTS quotas (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    share_id                INTEGER NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
                    quota_type              TEXT NOT NULL DEFAULT 'directory',
                    path                    TEXT NOT NULL,
                    hard_limit_bytes        INTEGER,
                    soft_limit_bytes        INTEGER,
                    advisory_limit_bytes    INTEGER,
                    usage_bytes             INTEGER,
                    usage_inodes            INTEGER,
                    enforced                INTEGER NOT NULL DEFAULT 1,
                    last_enriched_at        TEXT,
                    UNIQUE(share_id, quota_type)
                );

                CREATE TABLE IF NOT EXISTS security_groups (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_name          TEXT NOT NULL,
                    group_sid           TEXT UNIQUE,
                    domain              TEXT,
                    distinguished_name  TEXT,
                    member_count        INTEGER,
                    ps_resolved_at      TEXT
                );

                CREATE TABLE IF NOT EXISTS share_groups (
                    share_id            INTEGER NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
                    group_id            INTEGER NOT NULL REFERENCES security_groups(id),
                    permission_type     TEXT NOT NULL DEFAULT 'allow',
                    permission_level    TEXT,
                    inherited           INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (share_id, group_id)
                );

                CREATE TABLE IF NOT EXISTS ad_members (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    sam_account_name    TEXT NOT NULL UNIQUE,
                    display_name        TEXT,
                    email               TEXT,
                    user_principal_name TEXT,
                    object_sid          TEXT UNIQUE,
                    account_enabled     INTEGER,
                    ps_resolved_at      TEXT
                );

                CREATE TABLE IF NOT EXISTS group_members (
                    group_id    INTEGER NOT NULL REFERENCES security_groups(id) ON DELETE CASCADE,
                    member_id   INTEGER NOT NULL REFERENCES ad_members(id) ON DELETE CASCADE,
                    PRIMARY KEY (group_id, member_id)
                );

                CREATE TABLE IF NOT EXISTS run_log (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_type            TEXT NOT NULL,
                    node_name           TEXT,
                    started_at          TEXT NOT NULL,
                    finished_at         TEXT,
                    shares_discovered   INTEGER DEFAULT 0,
                    shares_added        INTEGER DEFAULT 0,
                    shares_removed      INTEGER DEFAULT 0,
                    shares_enriched     INTEGER DEFAULT 0,
                    errors              INTEGER DEFAULT 0,
                    notes               TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_shares_node ON shares(node_id);
                CREATE INDEX IF NOT EXISTS idx_shares_path ON shares(path);
                CREATE INDEX IF NOT EXISTS idx_quotas_share ON quotas(share_id);
                CREATE INDEX IF NOT EXISTS idx_share_groups_share ON share_groups(share_id);
                CREATE INDEX IF NOT EXISTS idx_group_members_group ON group_members(group_id);
            """)

    # ------------------------------------------------------------------
    # Node CRUD
    # ------------------------------------------------------------------

    def upsert_node(self, node: NodeRecord) -> int:
        with self.transaction() as c:
            c.execute("""
                INSERT INTO nodes (name, host, port, onefs_version, last_seen_at)
                VALUES (:name, :host, :port, :onefs_version, :last_seen_at)
                ON CONFLICT(name) DO UPDATE SET
                    host=excluded.host,
                    port=excluded.port,
                    onefs_version=excluded.onefs_version,
                    last_seen_at=excluded.last_seen_at
            """, node.to_db_dict())
        row = self.conn.execute("SELECT id FROM nodes WHERE name=?", (node.name,)).fetchone()
        return row["id"]

    def get_node_id(self, name: str) -> Optional[int]:
        row = self.conn.execute("SELECT id FROM nodes WHERE name=?", (name,)).fetchone()
        return row["id"] if row else None

    # ------------------------------------------------------------------
    # Share CRUD
    # ------------------------------------------------------------------

    def upsert_share(self, share: ShareRecord) -> int:
        """Insert or update a share. Returns the share id."""
        d = share.to_db_dict()
        with self.transaction() as c:
            c.execute("""
                INSERT INTO shares (
                    node_id, name, share_type, path, access_zone, description,
                    enabled, permissions_mode, is_dfs_target, owner_sid,
                    created_at, last_enriched_at, exists_in_snapshot
                ) VALUES (
                    :node_id, :name, :share_type, :path, :access_zone, :description,
                    :enabled, :permissions_mode, :is_dfs_target, :owner_sid,
                    :created_at, :last_enriched_at, :exists_in_snapshot
                )
                ON CONFLICT(node_id, name, share_type, access_zone) DO UPDATE SET
                    path=excluded.path,
                    description=excluded.description,
                    enabled=excluded.enabled,
                    permissions_mode=excluded.permissions_mode,
                    is_dfs_target=excluded.is_dfs_target,
                    owner_sid=excluded.owner_sid,
                    last_enriched_at=excluded.last_enriched_at,
                    exists_in_snapshot=1
            """, d)
        row = self.conn.execute("""
            SELECT id FROM shares
            WHERE node_id=? AND name=? AND share_type=? AND access_zone=?
        """, (share.node_id, share.name, share.share_type, share.access_zone)).fetchone()
        return row["id"]

    def get_all_shares(self) -> List[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM shares").fetchall()]

    def get_shares_for_node(self, node_id: int) -> List[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM shares WHERE node_id=?", (node_id,)
        ).fetchall()]

    def mark_all_not_in_snapshot(self, node_id: int) -> None:
        """Before a run, clear snapshot flag so we can detect removed shares."""
        with self.transaction() as c:
            c.execute(
                "UPDATE shares SET exists_in_snapshot=0 WHERE node_id=?", (node_id,)
            )

    def remove_missing_shares(self, node_id: int) -> int:
        """Delete shares that were not seen in this run. Returns count removed."""
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM shares WHERE node_id=? AND exists_in_snapshot=0",
            (node_id,)
        )
        count = cur.fetchone()[0]
        with self.transaction() as c:
            c.execute(
                "DELETE FROM shares WHERE node_id=? AND exists_in_snapshot=0", (node_id,)
            )
        return count

    # ------------------------------------------------------------------
    # Quota CRUD
    # ------------------------------------------------------------------

    def upsert_quota(self, quota: QuotaRecord) -> int:
        d = quota.to_db_dict()
        with self.transaction() as c:
            c.execute("""
                INSERT INTO quotas (
                    share_id, quota_type, path, hard_limit_bytes, soft_limit_bytes,
                    advisory_limit_bytes, usage_bytes, usage_inodes, enforced, last_enriched_at
                ) VALUES (
                    :share_id, :quota_type, :path, :hard_limit_bytes, :soft_limit_bytes,
                    :advisory_limit_bytes, :usage_bytes, :usage_inodes, :enforced, :last_enriched_at
                )
                ON CONFLICT(share_id, quota_type) DO UPDATE SET
                    hard_limit_bytes=excluded.hard_limit_bytes,
                    soft_limit_bytes=excluded.soft_limit_bytes,
                    advisory_limit_bytes=excluded.advisory_limit_bytes,
                    usage_bytes=excluded.usage_bytes,
                    usage_inodes=excluded.usage_inodes,
                    enforced=excluded.enforced,
                    last_enriched_at=excluded.last_enriched_at
            """, d)
        row = self.conn.execute(
            "SELECT id FROM quotas WHERE share_id=? AND quota_type=?",
            (quota.share_id, quota.quota_type)
        ).fetchone()
        return row["id"]

    # ------------------------------------------------------------------
    # Security group CRUD
    # ------------------------------------------------------------------

    def upsert_security_group(self, group: SecurityGroupRecord) -> int:
        d = group.to_db_dict()
        with self.transaction() as c:
            c.execute("""
                INSERT INTO security_groups (group_name, group_sid, domain)
                VALUES (:group_name, :group_sid, :domain)
                ON CONFLICT(group_sid) DO UPDATE SET
                    group_name=excluded.group_name,
                    domain=excluded.domain
            """, d)
        row = self.conn.execute(
            "SELECT id FROM security_groups WHERE group_sid=?", (group.group_sid,)
        ).fetchone()
        return row["id"]

    def link_group_to_share(self, link: ShareGroupLink) -> None:
        with self.transaction() as c:
            c.execute("""
                INSERT OR REPLACE INTO share_groups
                (share_id, group_id, permission_type, permission_level, inherited)
                VALUES (:share_id, :group_id, :permission_type, :permission_level, :inherited)
            """, link.to_db_dict())

    # ------------------------------------------------------------------
    # Run log
    # ------------------------------------------------------------------

    def insert_run_log(self, run: RunLogRecord) -> int:
        d = run.to_db_dict()
        with self.transaction() as c:
            c.execute("""
                INSERT INTO run_log (run_type, node_name, started_at, finished_at,
                    shares_discovered, shares_added, shares_removed, shares_enriched,
                    errors, notes)
                VALUES (:run_type, :node_name, :started_at, :finished_at,
                    :shares_discovered, :shares_added, :shares_removed, :shares_enriched,
                    :errors, :notes)
            """, d)
        return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def update_run_log(self, run_id: int, run: RunLogRecord) -> None:
        with self.transaction() as c:
            c.execute("""
                UPDATE run_log SET finished_at=:finished_at, shares_discovered=:shares_discovered,
                    shares_added=:shares_added, shares_removed=:shares_removed,
                    shares_enriched=:shares_enriched, errors=:errors, notes=:notes
                WHERE id=?
            """, {**run.to_db_dict(), "id": run_id})
            c.execute("UPDATE run_log SET id=? WHERE id=?", (run_id, run_id))  # noop to bind param

    def get_run_log(self, limit: int = 50) -> List[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM run_log ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()]
