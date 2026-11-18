from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from collections import defaultdict, deque

from .config import settings


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:20]}"


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ------------------------------------------------------------------ passwords
_SCRYPT = dict(n=2**14, r=8, p=1, dklen=64)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, dk_b64 = stored.split("$", 2)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
    except ValueError:
        return False
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return hmac.compare_digest(dk, expected)


# --------------------------------------------------------------------- PKCE
def pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ----------------------------------------------------------- signed URLs
def sign(payload: str) -> str:
    mac = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def signed_audio_url(generation_id: str, ttl: int | None = None) -> str:
    exp = int(time.time()) + (ttl or settings.audio_link_ttl)
    sig = sign(f"audio:{generation_id}:{exp}")
    return f"{settings.public_url}/files/audio/{generation_id}.wav?exp={exp}&sig={sig}"


def verify_audio_sig(generation_id: str, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    return hmac.compare_digest(sign(f"audio:{generation_id}:{exp}"), sig)


# ------------------------------------------------------------- rate limit
class RateLimiter:
    """Limite simples em memória (suficiente para 1 processo)."""

    def __init__(self, max_hits: int, window: int) -> None:
        self.max_hits = max_hits
        self.window = window
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        q = self.hits[key]
        while q and q[0] < now - self.window:
            q.popleft()
        if len(q) >= self.max_hits:
            return False
        q.append(now)
        return True


login_limiter = RateLimiter(10, 300)
register_limiter = RateLimiter(20, 3600)
