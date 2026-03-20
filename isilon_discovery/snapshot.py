"""
snapshot.py — Per-run share snapshot for delta detection.

Every successful run writes a snapshot file:
  snapshots/snapshot_YYYYMMDD_HHMMSS_<nodename>.json

The snapshot contains the minimal set of identifiers needed to
detect additions and removals without querying Isilon again:
  { "node": "isilon-prod-1", "run_at": "...", "shares": [
      {"name": "Finance", "share_type": "smb", "access_zone": "Finance"},
      ...
  ]}

On the NEXT run, the orchestrator:
  1. Loads the most recent snapshot for this node.
  2. Compares it to the live share list from PAPI.
  3. Shares in PAPI but NOT in snapshot → newly added.
  4. Shares in snapshot but NOT in PAPI → removed (delete from DB).

This avoids re-querying the full DB for every share and speeds up
the "is this share new?" check significantly at scale.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShareIdentity:
    """Minimal identity tuple used for set comparison."""
    name: str
    share_type: str
    access_zone: str

    def to_dict(self) -> dict:
        return {"name": self.name, "share_type": self.share_type, "access_zone": self.access_zone}

    @classmethod
    def from_dict(cls, d: dict) -> "ShareIdentity":
        return cls(name=d["name"], share_type=d["share_type"], access_zone=d["access_zone"])


class SnapshotManager:
    """
    Reads and writes share snapshots to disk.
    One snapshot file per node per run.
    """

    def __init__(self, snapshot_dir: str) -> None:
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def write(self, node_name: str, shares: List[ShareIdentity]) -> Path:
        """Write a new snapshot. Returns the path of the written file."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_name = node_name.replace(" ", "_").replace("/", "_")
        path = self.snapshot_dir / f"snapshot_{ts}_{safe_name}.json"

        payload = {
            "node": node_name,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "share_count": len(shares),
            "shares": [s.to_dict() for s in shares],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Snapshot written: %s (%d shares)", path.name, len(shares))
        return path

    def load_latest(self, node_name: str) -> Optional[Set[ShareIdentity]]:
        """
        Load the most recent snapshot for this node.
        Returns None if no snapshot exists (first run).
        """
        pattern = f"snapshot_*_{node_name.replace(' ', '_').replace('/', '_')}.json"
        candidates = sorted(self.snapshot_dir.glob(pattern), reverse=True)

        if not candidates:
            logger.info("No previous snapshot for node '%s' — this is a first run.", node_name)
            return None

        latest = candidates[0]
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
            shares = {ShareIdentity.from_dict(s) for s in payload.get("shares", [])}
            logger.info(
                "Loaded snapshot %s (%d shares, run at %s)",
                latest.name, len(shares), payload.get("run_at", "?"),
            )
            return shares
        except Exception as exc:
            logger.warning("Failed to load snapshot %s: %s", latest.name, exc)
            return None

    def diff(
        self,
        previous: Optional[Set[ShareIdentity]],
        current: Set[ShareIdentity],
    ) -> Tuple[Set[ShareIdentity], Set[ShareIdentity]]:
        """
        Compare previous snapshot to current live share list.

        Returns:
            added   — shares in current but not in previous (new this run)
            removed — shares in previous but not in current (gone this run)

        If previous is None (first run), all shares are considered 'added'
        and nothing is 'removed'.
        """
        if previous is None:
            return current, set()

        added = current - previous
        removed = previous - current
        return added, removed

    def prune_old_snapshots(self, node_name: str, keep: int = 10) -> int:
        """
        Keep only the N most recent snapshots for a node.
        Returns the count of deleted files.
        """
        pattern = f"snapshot_*_{node_name.replace(' ', '_').replace('/', '_')}.json"
        candidates = sorted(self.snapshot_dir.glob(pattern), reverse=True)
        to_delete = candidates[keep:]
        for f in to_delete:
            f.unlink(missing_ok=True)
        if to_delete:
            logger.info("Pruned %d old snapshot(s) for %s", len(to_delete), node_name)
        return len(to_delete)
