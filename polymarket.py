"""
Async client for the public Polymarket Data API.

No authentication required — uses only the public /activity endpoint.
https://data-api.polymarket.com
"""

import logging
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

DATA_API = "https://data-api.polymarket.com"
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class PolymarketClient:
    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Public methods ────────────────────────────────────────────────────

    async def get_activity(
        self,
        wallet: str,
        since_ts: int,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Return activities with timestamp > since_ts, sorted oldest-first.

        Uses GET /activity from the public Data API.
        https://docs.polymarket.com/api-reference/core/get-user-activity
        """
        params = {
            "user": wallet,
            "start": since_ts + 1,   # API 'start' is inclusive; +1 avoids duplicates
            "limit": limit,
            "sortBy": "TIMESTAMP",
            "sortDirection": "ASC",
        }
        try:
            async with self._sess().get(f"{DATA_API}/activity", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data if isinstance(data, list) else []
                logger.warning(
                    "Activity API returned HTTP %s for wallet %s…", resp.status, wallet[:10]
                )
                return []
        except Exception as exc:
            logger.error("Error fetching activity for %s…: %s", wallet[:10], exc)
            return []

    async def has_history(self, wallet: str) -> bool:
        """Return True if this wallet has ANY activity on Polymarket."""
        try:
            async with self._sess().get(
                f"{DATA_API}/activity", params={"user": wallet, "limit": 1}
            ) as resp:
                if resp.status == 200:
                    return bool(await resp.json())
        except Exception:
            pass
        return False
