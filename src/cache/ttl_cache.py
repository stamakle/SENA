"""Simple in-memory TTL cache.

This cache is used to reduce repeated retrieval and reranking work.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional


# Step 10: Add caching.


class TTLCache:
    """In-memory cache with time-based expiration."""

    def __init__(self, ttl_sec: int) -> None:
        """Initialize the cache with a TTL in seconds."""

        self._ttl_sec = ttl_sec
        self._store: Dict[str, Any] = {}
        self._expires: Dict[str, float] = {}

    def get(self, key: str) -> Optional[Any]:
        """Return a cached value if it is not expired."""

        expires_at = self._expires.get(key)
        if expires_at is None:
            return None
        if time.time() > expires_at:
            self._store.pop(key, None)
            self._expires.pop(key, None)
            return None
        return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        """Store a value with a TTL."""

        self._store[key] = value
        self._expires[key] = time.time() + self._ttl_sec
