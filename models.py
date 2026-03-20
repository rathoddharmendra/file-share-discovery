"""
models.py — Pydantic property objects for every entity.

These are the canonical Python representations of DB rows.
They serialize directly to dicts for SQLite INSERT/UPDATE,
and are constructed from API responses and DB SELECT results.

Design intent:
  - Fields marked `ps_managed` in comments are left None by Python enricher.
    PowerShell writes them. The web app also exposes them for user edits.
  - Fields marked `user_managed` are blank until a share owner fills them in
    via the web app.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class NodeRecord(BaseModel):
    """Isilon node from inventory.yaml, stored for FK references."""
    id: Optional[int] = None
    name: str
    host: str
    port: int = 8080
    onefs_version: Optional[str] = None   # populated by enricher on first contact
    last_seen_at: Optional[str] = None

    def to_db_dict(self) -> dict:
        d = self.model_dump(exclude={"id"})
        return d


# ---------------------------------------------------------------------------
# Share  (core discovery object)
# ---------------------------------------------------------------------------

class ShareRecord(BaseModel):
    """
    One SMB share or NFS export discovered on an Isilon node.
    This is the central table. All other tables reference it.
    """
    id: Optional[int] = None
    node_id: int
    name: str
    share_type: str                        # "smb" | "nfs"
    path: str                              # actual OneFS path e.g. /ifs/data/finance
    access_zone: str = "System"

    # — populated by Isilon PAPI —
    description: Optional[str] = None
    enabled: bool = True
    permissions_mode: Optional[str] = None   # "acl" | "unix" | "combined"
    is_dfs_target: bool = False
    owner_sid: Optional[str] = None          # raw SID from PAPI, PS resolves to name
    created_at: Optional[str] = None
    last_enriched_at: Optional[str] = Field(default_factory=_utcnow)

    # — ps_managed: PowerShell fills these —
    dfs_pseudo_path: Optional[str] = None    # \\dfs.corp\dept\share
    ps_enriched_at: Optional[str] = None

    # — user_managed: owner fills via web app —
    data_type: Optional[str] = None          # Finance | HR | Engineering | etc.
    data_owner: Optional[str] = None         # business contact name or email
    migration_notes: Optional[str] = None    # free-text migration planning notes
    migration_priority: Optional[int] = None # 1=high, 2=medium, 3=low

    # — internal delta tracking —
    exists_in_snapshot: bool = True

    def to_db_dict(self) -> dict:
        return self.model_dump(exclude={"id"})

    @classmethod
    def from_smb_api(cls, node_id: int, zone: str, raw: dict) -> "ShareRecord":
        """
        Construct from a raw /platform/12/protocols/smb/shares/{share} response.
        Only maps fields that PAPI actually returns. Everything else stays None.
        """
        return cls(
            node_id=node_id,
            name=raw["name"],
            share_type="smb",
            path=raw.get("path", ""),
            access_zone=zone,
            description=raw.get("description"),
            enabled=raw.get("browsable", True),
            permissions_mode="acl",          # SMB always uses ACL mode
            is_dfs_target=raw.get("dfs_target", False),
            created_at=raw.get("created", None),
        )

    @classmethod
    def from_nfs_api(cls, node_id: int, zone: str, raw: dict) -> "ShareRecord":
        """
        Construct from a raw /platform/12/protocols/nfs/exports/{id} response.
        """
        paths = raw.get("paths", [])
        return cls(
            node_id=node_id,
            name=paths[0] if paths else f"nfs-export-{raw.get('id')}",
            share_type="nfs",
            path=paths[0] if paths else "",
            access_zone=zone,
            description=raw.get("comment"),
            enabled=raw.get("enabled", True),
            permissions_mode="unix" if raw.get("map_root") else "combined",
        )


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------

class QuotaRecord(BaseModel):
    """
    Smart quota for a share path. OneFS can have multiple quota types
    on the same path (directory, user, default-user). We capture the
    directory-level quota as the primary migration signal.
    """
    id: Optional[int] = None
    share_id: int
    quota_type: str = "directory"          # "directory" | "user" | "default-user"
    path: str
    hard_limit_bytes: Optional[int] = None
    soft_limit_bytes: Optional[int] = None
    advisory_limit_bytes: Optional[int] = None
    usage_bytes: Optional[int] = None
    usage_inodes: Optional[int] = None
    enforced: bool = True
    last_enriched_at: Optional[str] = Field(default_factory=_utcnow)

    def to_db_dict(self) -> dict:
        return self.model_dump(exclude={"id"})

    @classmethod
    def from_api(cls, share_id: int, raw: dict) -> "QuotaRecord":
        thresholds = raw.get("thresholds", {})
        usage = raw.get("usage", {})
        return cls(
            share_id=share_id,
            quota_type=raw.get("type", "directory"),
            path=raw.get("path", ""),
            hard_limit_bytes=thresholds.get("hard"),
            soft_limit_bytes=thresholds.get("soft"),
            advisory_limit_bytes=thresholds.get("advisory"),
            usage_bytes=usage.get("fslogical"),
            usage_inodes=usage.get("inodes"),
            enforced=thresholds.get("hard") is not None,
        )

    @property
    def hard_limit_gb(self) -> Optional[float]:
        return round(self.hard_limit_bytes / 1_073_741_824, 2) if self.hard_limit_bytes else None

    @property
    def usage_gb(self) -> Optional[float]:
        return round(self.usage_bytes / 1_073_741_824, 2) if self.usage_bytes else None


# ---------------------------------------------------------------------------
# Security group (AD group on a share ACL)
# ---------------------------------------------------------------------------

class SecurityGroupRecord(BaseModel):
    """
    An AD security group found on a share's ACL.
    Python extracts the SID / group name from Isilon ACL.
    PowerShell resolves members and emails.
    """
    id: Optional[int] = None
    group_name: str
    group_sid: Optional[str] = None
    domain: Optional[str] = None
    distinguished_name: Optional[str] = None   # ps_managed
    member_count: Optional[int] = None         # ps_managed
    ps_resolved_at: Optional[str] = None       # ps_managed

    def to_db_dict(self) -> dict:
        return self.model_dump(exclude={"id"})


class ShareGroupLink(BaseModel):
    """M2M: which security groups are on which share's ACL."""
    share_id: int
    group_id: int
    permission_type: str = "allow"       # "allow" | "deny"
    permission_level: Optional[str] = None  # "full_control" | "change" | "read" etc.
    inherited: bool = False

    def to_db_dict(self) -> dict:
        return self.model_dump()


# ---------------------------------------------------------------------------
# AD member  (user inside a security group)
# ---------------------------------------------------------------------------

class ADMemberRecord(BaseModel):
    """
    One AD user, resolved by PowerShell from a SecurityGroupRecord.
    Python never writes this table — it is entirely ps_managed.
    """
    id: Optional[int] = None
    sam_account_name: str                  # ps_managed
    display_name: Optional[str] = None     # ps_managed
    email: Optional[str] = None            # ps_managed
    user_principal_name: Optional[str] = None  # ps_managed
    object_sid: Optional[str] = None       # ps_managed
    account_enabled: Optional[bool] = None # ps_managed
    ps_resolved_at: Optional[str] = None   # ps_managed

    def to_db_dict(self) -> dict:
        return self.model_dump(exclude={"id"})


class GroupMemberLink(BaseModel):
    """M2M: which AD members belong to which security group."""
    group_id: int
    member_id: int

    def to_db_dict(self) -> dict:
        return self.model_dump()


# ---------------------------------------------------------------------------
# Run log  (audit trail)
# ---------------------------------------------------------------------------

class RunLogRecord(BaseModel):
    id: Optional[int] = None
    run_type: str                    # "python_enricher" | "ps_enricher"
    node_name: Optional[str] = None
    started_at: str = Field(default_factory=_utcnow)
    finished_at: Optional[str] = None
    shares_discovered: int = 0
    shares_added: int = 0
    shares_removed: int = 0
    shares_enriched: int = 0
    errors: int = 0
    notes: Optional[str] = None

    def finish(self, **kwargs) -> None:
        self.finished_at = _utcnow()
        for k, v in kwargs.items():
            setattr(self, k, v)

    def to_db_dict(self) -> dict:
        return self.model_dump(exclude={"id"})
