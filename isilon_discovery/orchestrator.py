"""
orchestrator.py — Orchestrator entry point.

Run this script on a schedule (cron / Windows Task Scheduler) or manually.

What it does per node:
  1. Load config (inventory.yaml + .env)
  2. Load previous snapshot for delta detection
  3. Run async ShareEnricher → discovers shares, writes to DB
  4. Diff current shares vs snapshot → log added/removed
  5. Write new snapshot for next run
  6. Prune old snapshots (keep last 10)

Usage:
    python -m isilon_discovery
    python -m isilon_discovery --inventory /path/to/inventory.yaml
    python -m isilon_discovery --node isilon-prod-1   # run only one node
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import sys
from typing import Optional

from isilon_discovery.config import load_secrets, Config
from isilon_discovery.database import Database
from isilon_discovery.enricher import ShareEnricher
from isilon_discovery.snapshot import SnapshotManager, ShareIdentity

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


async def run_node(node_name: str, config: Config, db: Database, snapshot_mgr: SnapshotManager) -> None:
    """Run discovery + enrichment for one node."""
    node = next((n for n in config.active_nodes if n.name == node_name), None)
    if not node:
        logger.error("Node '%s' not found or disabled in inventory.", node_name)
        return

    logger.info("=" * 60)
    logger.info("Starting enrichment: %s (%s)", node.name, node.host)

    # --- Load previous snapshot ---
    previous_snap = snapshot_mgr.load_latest(node.name)

    # --- Run enricher ---
    enricher = ShareEnricher(node, config.credentials, config.settings, db)
    run_log = await enricher.run()

    # --- Build current share identity set from DB ---
    current_shares = {
        ShareIdentity(
            name=s["name"],
            share_type=s["share_type"],
            access_zone=s["access_zone"],
        )
        for s in db.get_shares_for_node(db.get_node_id(node.name) or 0)
    }

    # --- Diff ---
    added, removed = snapshot_mgr.diff(previous_snap, current_shares)
    if added:
        logger.info("NEW shares detected (%d): %s", len(added), [s.name for s in added])
    if removed:
        logger.info("REMOVED shares (%d): %s", len(removed), [s.name for s in removed])
    if not added and not removed and previous_snap is not None:
        logger.info("No share changes detected.")

    # --- Write new snapshot ---
    snapshot_mgr.write(node.name, list(current_shares))
    snapshot_mgr.prune_old_snapshots(node.name, keep=10)

    logger.info(
        "Finished %s — discovered: %d  enriched: %d  added: %d  removed: %d  errors: %d",
        node.name,
        run_log.shares_discovered,
        run_log.shares_enriched,
        run_log.shares_added,
        run_log.shares_removed,
        run_log.errors,
    )


async def main(inventory_path: str, target_node: Optional[str]) -> None:
    # 1. Load secrets from .env
    load_secrets()

    # 2. Load inventory + config
    config = Config.load(inventory_path)
    logger.info(
        "Loaded %d active node(s) from %s", len(config.active_nodes), inventory_path
    )

    # 3. Open DB
    db = Database(config.settings.db_path)
    db.connect()

    # 4. Snapshot manager
    snapshot_mgr = SnapshotManager(config.settings.snapshot_dir)

    # 5. Run each node
    nodes_to_run = (
        [target_node] if target_node
        else [n.name for n in config.active_nodes]
    )

    for node_name in nodes_to_run:
        try:
            await run_node(node_name, config, db, snapshot_mgr)
        except Exception:
            logger.exception("Unhandled error processing node '%s'", node_name)

    db.close()
    logger.info("All done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Isilon file share discovery")
    parser.add_argument("--inventory", default="inventory.yaml", help="Path to inventory.yaml")
    parser.add_argument("--node", default=None, help="Run only this node (by name)")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.inventory, args.node))
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        sys.exit(0)
