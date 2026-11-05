"""Hash password (PBKDF2, pustaka standar) dan token JWT."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from mab_api.config import get_settings

_ITERATIONS = 240_000


def hash_secret(secret: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_secret(secret: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iterations, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), base64.b64decode(salt_b64), int(iterations))
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def create_access_token(user_id: str, role: str, insurer_id: str | None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "insurer_id": insurer_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """Melempar jwt.PyJWTError bila token tidak valid atau kedaluwarsa."""
    return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])


API_KEY_PREFIX = "mab"


def generate_api_key() -> tuple[str, str, str]:
    """(kunci lengkap, prefix untuk pencarian, hash SHA-256). Kunci lengkap hanya ditampilkan sekali."""
    prefix = secrets.token_hex(4)
    key = f"{API_KEY_PREFIX}_{prefix}_{secrets.token_urlsafe(32)}"
    return key, prefix, hash_api_key(key)


def hash_api_key(key: str) -> str:
    # Kunci acak 256-bit: SHA-256 cukup (tidak perlu PBKDF2 seperti password manusia).
    return hashlib.sha256(key.encode()).hexdigest()


def split_api_key(key: str) -> str | None:
    """Prefix dari kunci berformat mab_<prefix>_<rahasia>, atau None bila formatnya salah."""
    parts = key.split("_", 2)
    if len(parts) != 3 or parts[0] != API_KEY_PREFIX or len(parts[1]) != 8:
        return None
    return parts[1]
