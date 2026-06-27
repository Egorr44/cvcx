"""
Async SQLite database wrapper for the Polymarket bot.
Schema v2: one user → many wallets.
Automatically migrates from v1 (users table) on first run.
"""

import logging
from typing import Any, Dict, List, Literal

import aiosqlite

logger = logging.getLogger(__name__)

MAX_WALLETS_PER_USER = 10   # hard cap per Telegram chat


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    # ── Setup / migration ─────────────────────────────────────────────────

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            # v2 table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS wallets (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id    INTEGER NOT NULL,
                    wallet     TEXT    NOT NULL,
                    last_seen  INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(chat_id, wallet)
                )
            """)

            # Migrate from v1 'users' table if it still exists
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
            ) as cur:
                if await cur.fetchone():
                    logger.info("Migrating v1 → v2 schema…")
                    async with db.execute(
                        "SELECT chat_id, wallet, last_seen, created_at FROM users"
                    ) as cur2:
                        rows = await cur2.fetchall()
                    for row in rows:
                        await db.execute(
                            "INSERT OR IGNORE INTO wallets "
                            "(chat_id, wallet, last_seen, created_at) VALUES (?,?,?,?)",
                            row,
                        )
                    await db.execute("DROP TABLE users")
                    logger.info("Migrated %d record(s) from v1", len(rows))

            await db.commit()
        logger.info("Database ready at %s", self.path)

    # ── Write ─────────────────────────────────────────────────────────────

    async def add_wallet(
        self, chat_id: int, wallet: str, now_ts: int
    ) -> Literal["added", "exists", "limit"]:
        """
        Add a wallet for a user.
        Returns:
          "added"  – success
          "exists" – already tracking this wallet
          "limit"  – MAX_WALLETS_PER_USER reached
        """
        current = await self.get_wallets(chat_id)
        if any(w["wallet"] == wallet for w in current):
            return "exists"
        if len(current) >= MAX_WALLETS_PER_USER:
            return "limit"

        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO wallets "
                "(chat_id, wallet, last_seen, created_at) VALUES (?,?,?,?)",
                (chat_id, wallet, now_ts, now_ts),
            )
            await db.commit()
        return "added"

    async def remove_wallet(self, chat_id: int, wallet: str) -> bool:
        """Remove one wallet. Returns True if it existed."""
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "DELETE FROM wallets WHERE chat_id = ? AND wallet = ?",
                (chat_id, wallet),
            )
            await db.commit()
            return cur.rowcount > 0

    async def remove_all_wallets(self, chat_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM wallets WHERE chat_id = ?", (chat_id,))
            await db.commit()

    async def update_last_seen(self, row_id: int, ts: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE wallets SET last_seen = ? WHERE id = ?", (ts, row_id)
            )
            await db.commit()

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_wallets(self, chat_id: int) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM wallets WHERE chat_id = ? ORDER BY created_at",
                (chat_id,),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def all_wallets(self) -> List[Dict[str, Any]]:
        """Returns every wallet row across all users (for the poll loop)."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM wallets") as cur:
                return [dict(r) for r in await cur.fetchall()]
