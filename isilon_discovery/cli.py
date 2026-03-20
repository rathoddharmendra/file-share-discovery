"""
User-facing CLI entry point for running the Python enricher.

This is a thin wrapper around the existing `main.py` orchestrator so the
project can be executed as:

  python -m isilon_discovery
  python -m isilon_discovery.cli
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Optional

from main import main as orchestrator_main  # type: ignore


def run(inventory_path: str, target_node: Optional[str]) -> None:
    asyncio.run(orchestrator_main(inventory_path=inventory_path, target_node=target_node))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Isilon file share discovery (Python enricher)")
    parser.add_argument("--inventory", default="inventory.yaml", help="Path to inventory.yaml")
    parser.add_argument("--node", default=None, help="Run only this node (by name)")
    args = parser.parse_args(argv)

    try:
        run(inventory_path=args.inventory, target_node=args.node)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Interrupted.")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

