#!/usr/bin/env python3
"""CLI utility to provision the global stack registry database (registry.db)."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from agent_forge.db.registry import DEFAULT_REGISTRY_PATH, init_registry_db


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize the local-agent-stack global registry database."
    )
    parser.add_argument(
        "--db-path",
        "-d",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help=f"Target SQLite database path (default: {DEFAULT_REGISTRY_PATH})",
    )
    args = parser.parse_args()

    target_path = args.db_path.resolve()
    print(f"Initializing registry database at: {target_path}")

    asyncio.run(init_registry_db(target_path))
    print("✅ registry.db tables, indexes, and foreign key constraints successfully configured.")


if __name__ == "__main__":
    main()
