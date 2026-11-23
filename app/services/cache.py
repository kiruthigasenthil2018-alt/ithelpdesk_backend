"""Redis cache with an in-memory fallback so the app still runs without Redis."""

import json
import logging
import time
from functools import lru_cache

from app.config import get_settings

log = logging.getLogger(__name__)


class Cache:
    def __init__(self, redis_url: str = "", ttl: int = 300, client=None):
        self.ttl = ttl
        self._mem: dict[str, tuple[float, str]] = {}
        self._redis = client
        if client is None and redis_url:
            try:
                import redis

                self._redis = redis.Redis.from_url(
                    redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
                )
            except Exception as exc:  # pragma: no cover
                log.warning("Redis setup failed, using memory cache: %s", exc)

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"

    def ping(self) -> bool:
        if self._redis is None:
            return True
        try:
            return bool(self._redis.ping())
        except Exception:
            return False

    def get_json(self, key: str):
        try:
            if self._redis is not None:
                raw = self._redis.get(key)
            else:
                item = self._mem.get(key)
                raw = item[1] if item and item[0] > time.time() else None
            return json.loads(raw) if raw else None
        except Exception as exc:
            log.warning("cache get failed: %s", exc)
            return None

    def set_json(self, key: str, value, ttl: int | None = None) -> None:
        ttl = ttl or self.ttl
        raw = json.dumps(value, default=str)
        try:
            if self._redis is not None:
                self._redis.setex(key, ttl, raw)
            else:
                self._mem[key] = (time.time() + ttl, raw)
        except Exception as exc:
            log.warning("cache set failed: %s", exc)

    def delete_prefix(self, prefix: str) -> None:
        try:
            if self._redis is not None:
                for key in self._redis.scan_iter(f"{prefix}*"):
                    self._redis.delete(key)
            else:
                for key in [k for k in self._mem if k.startswith(prefix)]:
                    del self._mem[key]
        except Exception as exc:
            log.warning("cache delete failed: %s", exc)


@lru_cache
def get_cache() -> Cache:
    s = get_settings()
    return Cache(s.redis_url, s.cache_ttl_seconds)
