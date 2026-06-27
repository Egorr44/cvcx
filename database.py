"""
Async SQLite database wrapper for the Polymarket bot.
"""

import logging
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    async def init(self) -> None:
        """Create tables if they don't exist yet."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    chat_id    INTEGER PRIMARY KEY,
                    wallet     TEXT    NOT NULL,
                    last_seen  INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            await db.commit()
        logger.info("Database ready at %s", self.path)

    # ── Write ─────────────────────────────────────────────────────────────

    async def upsert_user(self, chat_id: int, wallet: str, now_ts: int) -> None:
        """Insert or update a user record; resets last_seen when wallet changes."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO users (chat_id, wallet, last_seen, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    wallet    = excluded.wallet,
                    last_seen = excluded.last_seen
                """,
                (chat_id, wallet, now_ts, now_ts),
            )
            await db.commit()

    async def update_last_seen(self, chat_id: int, ts: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET last_seen = ? WHERE chat_id = ?",
                (ts, chat_id),
            )
            await db.commit()

    async def delete_user(self, chat_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
            await db.commit()

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_user(self, chat_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def all_users(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users") as cur:
                return [dict(r) for r in await cur.fetchall()]
