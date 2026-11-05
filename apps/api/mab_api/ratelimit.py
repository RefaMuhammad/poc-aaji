"""Batas percobaan gagal (login, PIN tanda tangan) supaya password dan PIN tidak bisa ditebak beruntun.

Disimpan di Redis supaya berlaku di semua replika API. Tes dan dev tanpa Redis memakai versi memori.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)


class FailureLimiter:
    """Hitung kegagalan per kunci. Setelah `max_failures` dalam `window` detik, kunci diblokir sampai jendela habis."""

    def __init__(self, max_failures: int = 5, window: int = 900, redis=None, prefix: str = "mab:fail:"):
        self.max_failures = max_failures
        self.window = window
        self.redis = redis
        self.prefix = prefix
        self._memory: dict[str, tuple[int, float]] = {}

    def _count(self, key: str) -> int:
        if self.redis is not None:
            try:
                return int(self.redis.get(self.prefix + key) or 0)
            except Exception:  # Redis mati: jangan kunci semua orang, tapi catat
                log.warning("Redis tidak bisa dihubungi untuk batas percobaan; memakai hitungan lokal")
        count, expires = self._memory.get(key, (0, 0.0))
        return count if expires > time.time() else 0

    def blocked(self, key: str, limit: int | None = None) -> bool:
        return self._count(key) >= (limit or self.max_failures)

    def retry_after(self, key: str) -> int:
        if self.redis is not None:
            try:
                ttl = int(self.redis.ttl(self.prefix + key))
                return max(ttl, 1)
            except Exception:
                pass
        _, expires = self._memory.get(key, (0, 0.0))
        return max(int(expires - time.time()), 1)

    def fail(self, key: str) -> int:
        if self.redis is not None:
            try:
                pipe = self.redis.pipeline()
                pipe.incr(self.prefix + key)
                pipe.expire(self.prefix + key, self.window, nx=True)
                return int(pipe.execute()[0])
            except Exception:
                log.warning("Redis tidak bisa dihubungi untuk batas percobaan; memakai hitungan lokal")
        count = self._count(key) + 1
        _, expires = self._memory.get(key, (0, 0.0))
        self._memory[key] = (count, expires if expires > time.time() else time.time() + self.window)
        return count

    def reset(self, key: str) -> None:
        if self.redis is not None:
            try:
                self.redis.delete(self.prefix + key)
            except Exception:
                pass
        self._memory.pop(key, None)


def guard_pin(request, db, user, pin: str, audit_action: str, **audit_kwargs) -> None:
    """Periksa PIN tanda tangan dengan batas percobaan per akun. Melempar 409/403/429."""
    from fastapi import HTTPException, status

    from mab_api import audit
    from mab_api.observability import AUTH_LOCKOUTS
    from mab_api.security import verify_secret

    limiter: FailureLimiter = request.app.state.limiter
    key = f"pin:{user.id}"
    if not user.pin_hash:
        raise HTTPException(status.HTTP_409_CONFLICT, "PIN tanda tangan Anda belum diatur. Hubungi admin.")
    if limiter.blocked(key):
        AUTH_LOCKOUTS.labels("pin").inc()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Terlalu banyak PIN salah. Coba lagi nanti.",
                            headers={"Retry-After": str(limiter.retry_after(key))})
    if not verify_secret(pin, user.pin_hash):
        limiter.fail(key)
        audit.record(db, audit_action, user_id=user.id, user_role=user.role, request=request, **audit_kwargs)
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "PIN salah")
    limiter.reset(key)
