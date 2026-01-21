"""In-memory cache for live command outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Tuple


@dataclass
class CacheEntry:
    output: str
    ts: float


_CACHE: Dict[Tuple[str, str], CacheEntry] = {}
_FAILURE_CACHE: Dict[Tuple[str, str], CacheEntry] = {}


def get_cached_output(host: str, command: str, ttl_sec: int) -> str | None:
    """Return cached output if fresh."""

    if ttl_sec <= 0:
        return None
    key = (host.strip().lower(), command.strip())
    entry = _CACHE.get(key)
    if not entry:
        return None
    now = datetime.now(timezone.utc).timestamp()
    if now - entry.ts > ttl_sec:
        _CACHE.pop(key, None)
        return None
    return entry.output


def set_cached_output(host: str, command: str, output: str) -> None:
    """Store cached output with current timestamp."""

    key = (host.strip().lower(), command.strip())
    ts = datetime.now(timezone.utc).timestamp()
    _CACHE[key] = CacheEntry(output=output, ts=ts)


def get_cached_failure(host: str, command: str, ttl_sec: int) -> str | None:
    """Return cached failure text if fresh."""

    if ttl_sec <= 0:
        return None
    key = (host.strip().lower(), command.strip())
    entry = _FAILURE_CACHE.get(key)
    if not entry:
        return None
    now = datetime.now(timezone.utc).timestamp()
    if now - entry.ts > ttl_sec:
        _FAILURE_CACHE.pop(key, None)
        return None
    return entry.output


def set_cached_failure(host: str, command: str, error_text: str) -> None:
    """Store cached failure with current timestamp."""

    key = (host.strip().lower(), command.strip())
    ts = datetime.now(timezone.utc).timestamp()
    _FAILURE_CACHE[key] = CacheEntry(output=error_text, ts=ts)
