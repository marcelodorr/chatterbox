from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from .config import settings

_DB_PATH = settings.data_dir / "app.db"
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS voices (
    id TEXT PRIMARY KEY,
    owner_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,                -- builtin | cloned
    is_shared INTEGER NOT NULL DEFAULT 0,
    ref_path TEXT,
    ref_duration REAL,
    consent_at INTEGER,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS generations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    voice_id TEXT,
    voice_name TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL,
    language TEXT NOT NULL,
    text TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,              -- queued | running | done | error
    error TEXT,
    audio_path TEXT,
    duration REAL,
    source TEXT NOT NULL DEFAULT 'web', -- web | mcp
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    finished_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_generations_user ON generations(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id TEXT PRIMARY KEY,
    client_secret_hash TEXT,
    client_name TEXT NOT NULL DEFAULT '',
    client_uri TEXT,
    logo_uri TEXT,
    redirect_uris TEXT NOT NULL,       -- JSON
    token_endpoint_auth_method TEXT NOT NULL DEFAULT 'none',
    kind TEXT NOT NULL DEFAULT 'dcr',  -- dcr | cimd
    fetched_at INTEGER,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_codes (
    code_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    scope TEXT NOT NULL,
    resource TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    token_hash TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                -- access | refresh
    family_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    resource TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    last_used_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tokens_family ON oauth_tokens(family_id);

CREATE TABLE IF NOT EXISTS oauth_grants (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, client_id)
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = _connect()
        _local.conn = c
    return c


def init_db() -> None:
    c = conn()
    c.executescript(SCHEMA)
    now = int(time.time())
    c.execute(
        "INSERT OR IGNORE INTO voices (id, owner_id, name, description, language, kind, is_shared, created_at) "
        "VALUES ('default', NULL, 'Padrão', 'Voz padrão que acompanha o modelo.', '', 'builtin', 1, ?)",
        (now,),
    )


def one(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    row = conn().execute(sql, params).fetchone()
    return dict(row) if row else None


def all_(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn().execute(sql, params).fetchall()]


def run(sql: str, params: tuple | list = ()) -> int:
    cur = conn().execute(sql, params)
    return cur.rowcount


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
