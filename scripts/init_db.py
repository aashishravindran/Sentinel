#!/usr/bin/env python3
"""
Initialize the SQLite permissions database.

Usage:
    python scripts/init_db.py                        # uses SQLITE_DB_PATH env var or ./data/permissions.db
    python scripts/init_db.py --no-seed              # schema only, no example users
"""
import asyncio
import argparse
import os

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS permissions (
    user_id TEXT NOT NULL,
    tag     TEXT NOT NULL,
    PRIMARY KEY (user_id, tag)
);
"""

SEED_DATA = [
    ("alice",   "finance"),
    ("alice",   "public"),
    ("bob",     "public"),
    ("bob",     "engineering"),
    ("charlie", "finance"),
    ("charlie", "engineering"),
    ("charlie", "public"),
]


async def init_db(db_path: str, seed: bool = True) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA)

        if seed:
            await db.executemany(
                "INSERT OR IGNORE INTO permissions (user_id, tag) VALUES (?, ?)",
                SEED_DATA,
            )
            print(f"Seeded {len(SEED_DATA)} permission rows.")

        await db.commit()

    print(f"Database ready: {db_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-seed", action="store_true", help="Skip seed data")
    args = parser.parse_args()

    db_path = os.environ.get("SQLITE_DB_PATH", "./data/permissions.db")
    asyncio.run(init_db(db_path, seed=not args.no_seed))
