#!/usr/bin/env python3
"""CLI utility to provision an empty, valid documentation database (docs.db) with FTS5 triggers."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from agent_forge.db.docs import init_docs_db


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize a domain documentation SQLite database (docs.db) with FTS5 indexing."
    )
    parser.add_argument(
        "--db-path",
        "-d",
        type=Path,
        default=Path("./.agent/docs.db"),
        help="Target SQLite database path (default: ./.agent/docs.db)",
    )
    args = parser.parse_args()

    target_path = args.db_path.resolve()
    print(f"Initializing docs database at: {target_path}")

    asyncio.run(init_docs_db(target_path))
    print("✅ docs.db schema, FTS5 virtual table, and auto-sync triggers successfully created.")


if __name__ == "__main__":
    main()
