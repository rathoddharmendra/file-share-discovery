"""
Isilon file share discovery.

This package provides an import-friendly structure for the project so that
modules can be referenced as `isilon_discovery.*` and can be installed/run
from Windows without relying on the repository root layout.
"""

from .config import Config, NodeConfig, AppSettings, IsilonCredentials, GraphCredentials, load_secrets
from .database import Database
from .enricher import IsilonSession, ShareEnricher
from .models import (
    NodeRecord,
    ShareRecord,
    QuotaRecord,
    SecurityGroupRecord,
    ShareGroupLink,
    ADMemberRecord,
    GroupMemberLink,
    RunLogRecord,
)
from .snapshot import ShareIdentity, SnapshotManager

__all__ = [
    "Config",
    "NodeConfig",
    "AppSettings",
    "IsilonCredentials",
    "GraphCredentials",
    "load_secrets",
    "Database",
    "IsilonSession",
    "ShareEnricher",
    "NodeRecord",
    "ShareRecord",
    "QuotaRecord",
    "SecurityGroupRecord",
    "ShareGroupLink",
    "ADMemberRecord",
    "GroupMemberLink",
    "RunLogRecord",
    "ShareIdentity",
    "SnapshotManager",
]

