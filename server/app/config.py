from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str) -> list[str]:
    return [x.strip().lower() for x in os.getenv(name, "").split(",") if x.strip()]


@dataclass
class Settings:
    app_name: str = os.getenv("APP_NAME", "Estúdio de Voz")
    public_url: str = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
    secret_key: str = os.getenv("SECRET_KEY", "")
    data_dir: Path = Path(os.getenv("DATA_DIR", "./data"))
    inference_url: str = os.getenv("INFERENCE_URL", "http://localhost:8001").rstrip("/")
    inference_token: str = os.getenv("INFERENCE_TOKEN", "")
    inference_timeout: float = float(os.getenv("INFERENCE_TIMEOUT", "1800"))
    admin_email: str = os.getenv("ADMIN_EMAIL", "").strip().lower()
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    allow_signup: bool = _bool("ALLOW_SIGNUP", False)
    max_text_chars: int = int(os.getenv("MAX_TEXT_CHARS", "5000"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "25"))
    job_concurrency: int = int(os.getenv("JOB_CONCURRENCY", "1"))
    session_ttl: int = int(os.getenv("SESSION_TTL", str(30 * 24 * 3600)))
    access_token_ttl: int = int(os.getenv("ACCESS_TOKEN_TTL", "3600"))
    refresh_token_ttl: int = int(os.getenv("REFRESH_TOKEN_TTL", str(60 * 24 * 3600)))
    audio_link_ttl: int = int(os.getenv("AUDIO_LINK_TTL", str(7 * 24 * 3600)))
    # Se definido, só aceita redirect_uri nesses hosts (ex.: claude.ai,claude.com,chatgpt.com,localhost)
    oauth_allowed_redirect_hosts: list[str] = field(default_factory=lambda: _list("OAUTH_ALLOWED_REDIRECT_HOSTS"))
    web_dist: Path = Path(os.getenv("WEB_DIST", "./web/dist"))

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def mcp_resource(self) -> str:
        return f"{self.public_url}/mcp"


settings = Settings()

if not settings.secret_key:
    # Persistimos uma chave gerada para não invalidar sessões a cada restart.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key_file = settings.data_dir / ".secret_key"
    if key_file.exists():
        settings.secret_key = key_file.read_text().strip()
    else:
        settings.secret_key = secrets.token_urlsafe(48)
        key_file.write_text(settings.secret_key)
        key_file.chmod(0o600)

for sub in ("voices", "generations"):
    (settings.data_dir / sub).mkdir(parents=True, exist_ok=True)
