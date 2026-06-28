"""
Async SQLite database wrapper — schema v3 (wallets + labels).
Auto-migrates from v1 (users table) and v2 (wallets without label column).
"""

import logging
from typing import Any, Dict, List, Literal

import aiosqlite

logger = logging.getLogger(__name__)

MAX_WALLETS_PER_USER = 10
MAX_LABEL_LEN = 32


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:

            # ── Ensure wallets table exists with label column ──────────────
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='wallets'"
            ) as cur:
                wallets_exists = bool(await cur.fetchone())

            if wallets_exists:
                # v2 → v3: add label column if missing
                async with db.execute("PRAGMA table_info(wallets)") as cur:
                    cols = {row[1] for row in await cur.fetchall()}
                if "label" not in cols:
                    logger.info("v2→v3: adding label column…")
                    await db.execute(
                        "ALTER TABLE wallets ADD COLUMN label TEXT NOT NULL DEFAULT ''"
                    )
                    await db.commit()
            else:
                await db.execute("""
                    CREATE TABLE wallets (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id    INTEGER NOT NULL,
                        wallet     TEXT    NOT NULL,
                        label      TEXT    NOT NULL DEFAULT '',
                        last_seen  INTEGER NOT NULL DEFAULT 0,
                        created_at INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(chat_id, wallet)
                    )
                """)
                await db.commit()

            # ── Migrate v1 'users' table if present ───────────────────────
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
            ) as cur:
                if await cur.fetchone():
                    logger.info("Migrating v1 users → wallets…")
                    async with db.execute(
                        "SELECT chat_id, wallet, last_seen, created_at FROM users"
                    ) as cur2:
                        rows = await cur2.fetchall()
                    for row in rows:
                        await db.execute(
                            "INSERT OR IGNORE INTO wallets "
                            "(chat_id, wallet, label, last_seen, created_at) "
                            "VALUES (?,?,?,?,?)",
                            (row[0], row[1], "", row[2], row[3]),
                        )
                    await db.execute("DROP TABLE users")
                    logger.info("Migrated %d record(s)", len(rows))
                    await db.commit()

        logger.info("Database ready at %s", self.path)

    # ── Write ─────────────────────────────────────────────────────────────

    async def add_wallet(
        self, chat_id: int, wallet: str, label: str, now_ts: int
    ) -> Literal["added", "exists", "limit"]:
        current = await self.get_wallets(chat_id)
        if any(w["wallet"] == wallet for w in current):
            return "exists"
        if len(current) >= MAX_WALLETS_PER_USER:
            return "limit"
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO wallets "
                "(chat_id, wallet, label, last_seen, created_at) VALUES (?,?,?,?,?)",
                (chat_id, wallet, label[:MAX_LABEL_LEN], now_ts, now_ts),
            )
            await db.commit()
        return "added"

    async def update_label(self, chat_id: int, wallet: str, label: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "UPDATE wallets SET label = ? WHERE chat_id = ? AND wallet = ?",
                (label[:MAX_LABEL_LEN], chat_id, wallet),
            )
            await db.commit()
            return cur.rowcount > 0

    async def remove_wallet(self, chat_id: int, wallet: str) -> bool:
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
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM wallets") as cur:
                return [dict(r) for r in await cur.fetchall()]
