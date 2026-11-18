"""Servidor de autorização OAuth 2.1 para os conectores MCP (Claude e ChatGPT).

Implementa:
- RFC 8414  Authorization Server Metadata
- RFC 9728  Protected Resource Metadata
- RFC 7591  Dynamic Client Registration
- Client ID Metadata Documents (client_id = URL https)
- Authorization Code + PKCE (S256 obrigatório), refresh token com rotação
- RFC 7009  Token Revocation
- RFC 8707  Resource Indicators (token vinculado ao recurso /mcp)
"""
from __future__ import annotations

import base64
import hmac
import json
import time
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import db
from .audio import AudioError, safe_fetch
from .auth import get_session
from .config import settings
from .oauth_pages import consent_page, error_page
from .security import new_id, pkce_s256, random_token, register_limiter, sha256

router = APIRouter(tags=["oauth"])

SCOPES = ["voice"]
CODE_TTL = 600
CIMD_TTL = 3600
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}
BLOCKED_SCHEMES = {"javascript", "data", "file", "vbscript", "about", "blob"}


# ------------------------------------------------------------------ metadata
def as_metadata() -> dict:
    base = settings.public_url
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "revocation_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "scopes_supported": SCOPES,
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
        "service_documentation": f"{base}/integrations",
    }


def resource_metadata() -> dict:
    return {
        "resource": settings.mcp_resource,
        "authorization_servers": [settings.public_url],
        "scopes_supported": SCOPES,
        "bearer_methods_supported": ["header"],
        "resource_name": settings.app_name,
        "resource_documentation": f"{settings.public_url}/integrations",
    }


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/oauth-authorization-server/{_path:path}")
def well_known_as(_path: str = ""):
    return JSONResponse(as_metadata(), headers={"Cache-Control": "public, max-age=3600"})


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/{_path:path}")
def well_known_pr(_path: str = ""):
    return JSONResponse(resource_metadata(), headers={"Cache-Control": "public, max-age=3600"})


# --------------------------------------------------------------- utilities
def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _valid_redirect_uri(uri: str) -> bool:
    try:
        p = urlparse(uri)
    except ValueError:
        return False
    if not p.scheme or p.fragment:
        return False
    scheme = p.scheme.lower()
    host = (p.hostname or "").lower()
    if scheme in BLOCKED_SCHEMES:
        return False
    if settings.oauth_allowed_redirect_hosts:
        return scheme in ("https", "http") and (
            host in settings.oauth_allowed_redirect_hosts
            or any(host.endswith("." + h) for h in settings.oauth_allowed_redirect_hosts)
        ) and (scheme == "https" or host in LOOPBACK_HOSTS)
    if scheme == "https":
        return bool(host)
    if scheme == "http":
        return host in LOOPBACK_HOSTS
    # esquemas customizados de apps nativos (ex.: cursor://)
    return True


def _redirect_matches(registered: list[str], uri: str) -> bool:
    if uri in registered:
        return True
    # RFC 8252 §7.3: em loopback a porta pode variar
    try:
        p = urlparse(uri)
    except ValueError:
        return False
    if p.scheme == "http" and (p.hostname or "") in LOOPBACK_HOSTS:
        for r in registered:
            rp = urlparse(r)
            if rp.scheme == "http" and rp.hostname == p.hostname and rp.path == p.path and rp.query == p.query:
                return True
    return False


def _with_params(uri: str, params: dict) -> str:
    p = urlparse(uri)
    q = parse_qsl(p.query, keep_blank_values=True)
    q.extend((k, v) for k, v in params.items() if v is not None)
    return urlunparse(p._replace(query=urlencode(q)))


def _normalize_resource(resource: str | None) -> str | None:
    if not resource:
        return settings.mcp_resource
    r = resource.rstrip("/")
    if r in (settings.mcp_resource, settings.public_url):
        return settings.mcp_resource
    return None


def _parse_scope(scope: str | None) -> str:
    # Escopos desconhecidos são ignorados; o acesso sempre é "voice".
    return "voice"


async def get_client(client_id: str) -> dict | None:
    if not client_id:
        return None
    if client_id.startswith("https://"):
        return await _get_cimd_client(client_id)
    c = db.one("SELECT * FROM oauth_clients WHERE client_id=?", (client_id,))
    if c:
        c["redirect_uris"] = json.loads(c["redirect_uris"])
    return c


async def _get_cimd_client(client_id: str) -> dict | None:
    cached = db.one("SELECT * FROM oauth_clients WHERE client_id=?", (client_id,))
    if cached and cached["fetched_at"] and time.time() - cached["fetched_at"] < CIMD_TTL:
        cached["redirect_uris"] = json.loads(cached["redirect_uris"])
        return cached
    try:
        raw = await safe_fetch(client_id, max_bytes=64 * 1024, timeout=8)
        doc = json.loads(raw)
    except (AudioError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("client_id") != client_id:
        return None
    uris = doc.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) and _valid_redirect_uri(u) for u in uris):
        return None
    now = int(time.time())
    db.run(
        "INSERT INTO oauth_clients (client_id, client_name, client_uri, logo_uri, redirect_uris, "
        "token_endpoint_auth_method, kind, fetched_at, created_at) VALUES (?,?,?,?,?, 'none', 'cimd', ?, ?) "
        "ON CONFLICT(client_id) DO UPDATE SET client_name=excluded.client_name, client_uri=excluded.client_uri, "
        "logo_uri=excluded.logo_uri, redirect_uris=excluded.redirect_uris, fetched_at=excluded.fetched_at",
        (client_id, str(doc.get("client_name", ""))[:100], doc.get("client_uri"), doc.get("logo_uri"),
         json.dumps(uris), now, now),
    )
    c = db.one("SELECT * FROM oauth_clients WHERE client_id=?", (client_id,))
    c["redirect_uris"] = uris
    return c


# ------------------------------------------------------------- registration
@router.post("/oauth/register")
async def register(request: Request):
    ip = request.client.host if request.client else "?"
    if not register_limiter.allow(ip):
        return _oauth_error("invalid_request", "Muitos registros; tente mais tarde", 429)
    try:
        body = await request.json()
        assert isinstance(body, dict)
    except Exception:  # noqa: BLE001
        return _oauth_error("invalid_client_metadata", "JSON inválido")
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not uris or len(uris) > 10:
        return _oauth_error("invalid_redirect_uri", "redirect_uris é obrigatório")
    for u in uris:
        if not isinstance(u, str) or not _valid_redirect_uri(u):
            return _oauth_error("invalid_redirect_uri", f"redirect_uri não permitido: {u}")
    method = body.get("token_endpoint_auth_method") or "none"
    if method not in ("none", "client_secret_post", "client_secret_basic"):
        return _oauth_error("invalid_client_metadata", "token_endpoint_auth_method não suportado")
    grant_types = body.get("grant_types") or ["authorization_code", "refresh_token"]
    if "authorization_code" not in grant_types:
        return _oauth_error("invalid_client_metadata", "grant_types deve incluir authorization_code")

    client_id = new_id("mcp_")
    secret = random_token(32) if method != "none" else None
    now = int(time.time())
    db.run(
        "INSERT INTO oauth_clients (client_id, client_secret_hash, client_name, client_uri, logo_uri, redirect_uris, "
        "token_endpoint_auth_method, kind, created_at) VALUES (?,?,?,?,?,?,?, 'dcr', ?)",
        (client_id, sha256(secret) if secret else None, str(body.get("client_name", ""))[:100],
         body.get("client_uri"), body.get("logo_uri"), json.dumps(uris), method, now),
    )
    resp = {
        "client_id": client_id,
        "client_id_issued_at": now,
        "client_name": body.get("client_name", ""),
        "redirect_uris": uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": method,
        "scope": " ".join(SCOPES),
    }
    if secret:
        resp["client_secret"] = secret
        resp["client_secret_expires_at"] = 0
    return JSONResponse(resp, status_code=201, headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------- authorization
AUTH_PARAMS = ("response_type", "client_id", "redirect_uri", "state", "scope",
               "code_challenge", "code_challenge_method", "resource")


async def _validate_authorize(params: dict) -> tuple[dict | None, HTMLResponse | RedirectResponse | None]:
    """Retorna (client, None) se ok, ou (None, resposta de erro)."""
    client = await get_client(params.get("client_id") or "")
    if not client:
        return None, HTMLResponse(error_page("Aplicativo (client_id) desconhecido."), status_code=400)
    redirect_uri = params.get("redirect_uri") or ""
    if not redirect_uri and len(client["redirect_uris"]) == 1:
        redirect_uri = params["redirect_uri"] = client["redirect_uris"][0]
    if not _redirect_matches(client["redirect_uris"], redirect_uri):
        return None, HTMLResponse(error_page("redirect_uri não corresponde ao registrado."), status_code=400)

    def fail(err: str, desc: str):
        return None, RedirectResponse(
            _with_params(redirect_uri, {"error": err, "error_description": desc,
                                        "state": params.get("state"), "iss": settings.public_url}),
            status_code=302,
        )

    if params.get("response_type") != "code":
        return fail("unsupported_response_type", "Apenas response_type=code")
    if not params.get("code_challenge") or params.get("code_challenge_method") != "S256":
        return fail("invalid_request", "PKCE com S256 é obrigatório")
    if _normalize_resource(params.get("resource")) is None:
        return fail("invalid_target", "resource desconhecido")
    return client, None


@router.get("/oauth/authorize")
async def authorize_get(request: Request):
    params = {k: request.query_params.get(k) for k in AUTH_PARAMS}
    client, err = await _validate_authorize(params)
    if err:
        return err
    session = get_session(request)
    if not session:
        next_url = request.url.path + "?" + request.url.query
        return RedirectResponse(f"/login?next={quote(next_url, safe='')}", status_code=302)
    host = urlparse(params["redirect_uri"]).hostname or params["redirect_uri"]
    return HTMLResponse(
        consent_page(client, session, params, session["csrf"], host),
        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                 "Content-Security-Policy": "frame-ancestors 'none'"},
    )


@router.post("/oauth/authorize")
async def authorize_post(request: Request):
    form = await request.form()
    params = {k: (str(form.get(k)) if form.get(k) is not None else None) for k in AUTH_PARAMS}
    client, err = await _validate_authorize(params)
    if err:
        return err
    session = get_session(request)
    if not session:
        return HTMLResponse(error_page("Sessão expirada. Tente conectar novamente."), status_code=401)
    if not hmac.compare_digest(str(form.get("csrf") or ""), session["csrf"]):
        return HTMLResponse(error_page("Requisição inválida (CSRF)."), status_code=400)

    redirect_uri = params["redirect_uri"]
    if form.get("action") != "allow":
        return RedirectResponse(
            _with_params(redirect_uri, {"error": "access_denied", "error_description": "Usuário negou o acesso",
                                        "state": params.get("state"), "iss": settings.public_url}),
            status_code=302,
        )

    code = random_token(32)
    now = int(time.time())
    scope = _parse_scope(params.get("scope"))
    db.run(
        "INSERT INTO oauth_codes (code_hash, client_id, user_id, redirect_uri, code_challenge, scope, resource, expires_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (sha256(code), client["client_id"], session["id"], redirect_uri, params["code_challenge"],
         scope, _normalize_resource(params.get("resource")), now + CODE_TTL),
    )
    db.run(
        "INSERT INTO oauth_grants (user_id, client_id, scope, created_at) VALUES (?,?,?,?) "
        "ON CONFLICT(user_id, client_id) DO UPDATE SET scope=excluded.scope",
        (session["id"], client["client_id"], scope, now),
    )
    db.run("DELETE FROM oauth_codes WHERE expires_at < ?", (now,))
    return RedirectResponse(
        _with_params(redirect_uri, {"code": code, "state": params.get("state"), "iss": settings.public_url}),
        status_code=302,
    )


# --------------------------------------------------------------------- token
def _client_credentials(request: Request, form) -> tuple[str | None, str | None]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            raw = base64.b64decode(auth[6:]).decode()
            cid, _, secret = raw.partition(":")
            from urllib.parse import unquote
            return unquote(cid), unquote(secret)
        except Exception:  # noqa: BLE001
            return None, None
    return form.get("client_id"), form.get("client_secret")


async def _authenticate_client(request: Request, form) -> tuple[dict | None, JSONResponse | None]:
    cid, secret = _client_credentials(request, form)
    client = await get_client(cid or "")
    if not client:
        return None, _oauth_error("invalid_client", "Cliente desconhecido", 401)
    if client.get("client_secret_hash"):
        if not secret or not hmac.compare_digest(sha256(secret), client["client_secret_hash"]):
            return None, _oauth_error("invalid_client", "Credenciais do cliente inválidas", 401)
    return client, None


def _issue_tokens(client_id: str, user_id: str, scope: str, resource: str, family_id: str | None = None) -> dict:
    now = int(time.time())
    family_id = family_id or new_id("f_")
    access = "at_" + random_token(32)
    refresh = "rt_" + random_token(32)
    db.run(
        "INSERT INTO oauth_tokens (token_hash, kind, family_id, client_id, user_id, scope, resource, expires_at, created_at) "
        "VALUES (?, 'access', ?,?,?,?,?,?,?)",
        (sha256(access), family_id, client_id, user_id, scope, resource, now + settings.access_token_ttl, now),
    )
    db.run(
        "INSERT INTO oauth_tokens (token_hash, kind, family_id, client_id, user_id, scope, resource, expires_at, created_at) "
        "VALUES (?, 'refresh', ?,?,?,?,?,?,?)",
        (sha256(refresh), family_id, client_id, user_id, scope, resource, now + settings.refresh_token_ttl, now),
    )
    db.run("DELETE FROM oauth_tokens WHERE expires_at < ?", (now - 86400,))
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": settings.access_token_ttl,
        "refresh_token": refresh,
        "scope": scope,
    }


@router.post("/oauth/token")
async def token(request: Request):
    form = await request.form()
    client, err = await _authenticate_client(request, form)
    if err:
        return err
    grant = form.get("grant_type")
    now = int(time.time())

    if grant == "authorization_code":
        code = str(form.get("code") or "")
        verifier = str(form.get("code_verifier") or "")
        with db.tx() as c:
            row = c.execute("SELECT * FROM oauth_codes WHERE code_hash=?", (sha256(code),)).fetchone()
            if row:
                c.execute("DELETE FROM oauth_codes WHERE code_hash=?", (sha256(code),))
        if not row:
            return _oauth_error("invalid_grant", "Código inválido ou já utilizado")
        row = dict(row)
        if row["expires_at"] < now:
            return _oauth_error("invalid_grant", "Código expirado")
        if row["client_id"] != client["client_id"]:
            return _oauth_error("invalid_grant", "Código emitido para outro cliente")
        if form.get("redirect_uri") and form.get("redirect_uri") != row["redirect_uri"]:
            return _oauth_error("invalid_grant", "redirect_uri diferente")
        if not verifier or not hmac.compare_digest(pkce_s256(verifier), row["code_challenge"]):
            return _oauth_error("invalid_grant", "code_verifier inválido")
        resource = form.get("resource")
        if resource and _normalize_resource(str(resource)) != row["resource"]:
            return _oauth_error("invalid_target", "resource diferente do autorizado")
        tokens = _issue_tokens(client["client_id"], row["user_id"], row["scope"], row["resource"])
        return JSONResponse(tokens, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    if grant == "refresh_token":
        rt = str(form.get("refresh_token") or "")
        row = db.one("SELECT * FROM oauth_tokens WHERE token_hash=? AND kind='refresh'", (sha256(rt),))
        if not row or row["client_id"] != client["client_id"]:
            return _oauth_error("invalid_grant", "Refresh token inválido")
        if row["revoked"]:
            # Reuso de refresh token já rotacionado: revoga toda a família.
            db.run("UPDATE oauth_tokens SET revoked=1 WHERE family_id=?", (row["family_id"],))
            return _oauth_error("invalid_grant", "Refresh token já utilizado")
        if row["expires_at"] < now:
            return _oauth_error("invalid_grant", "Refresh token expirado")
        if not db.one("SELECT 1 FROM oauth_grants WHERE user_id=? AND client_id=?", (row["user_id"], row["client_id"])):
            return _oauth_error("invalid_grant", "Acesso revogado")
        db.run("UPDATE oauth_tokens SET revoked=1 WHERE token_hash=?", (row["token_hash"],))
        tokens = _issue_tokens(row["client_id"], row["user_id"], row["scope"], row["resource"], row["family_id"])
        return JSONResponse(tokens, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    return _oauth_error("unsupported_grant_type", "grant_type não suportado")


@router.post("/oauth/revoke")
async def revoke(request: Request):
    form = await request.form()
    client, err = await _authenticate_client(request, form)
    if err:
        return err
    tok = str(form.get("token") or "")
    row = db.one("SELECT * FROM oauth_tokens WHERE token_hash=?", (sha256(tok),))
    if row and row["client_id"] == client["client_id"]:
        if row["kind"] == "refresh":
            db.run("UPDATE oauth_tokens SET revoked=1 WHERE family_id=?", (row["family_id"],))
        else:
            db.run("UPDATE oauth_tokens SET revoked=1 WHERE token_hash=?", (row["token_hash"],))
    return JSONResponse({}, status_code=200)


# ---------------------------------------------------------------- validation
def verify_access_token(token: str) -> dict | None:
    row = db.one(
        "SELECT t.*, u.email, u.name, u.is_admin FROM oauth_tokens t JOIN users u ON u.id=t.user_id "
        "WHERE t.token_hash=? AND t.kind='access'",
        (sha256(token),),
    )
    now = int(time.time())
    if not row or row["revoked"] or row["expires_at"] < now:
        return None
    if row["resource"] != settings.mcp_resource:
        return None
    if not row["last_used_at"] or now - row["last_used_at"] > 60:
        db.run("UPDATE oauth_tokens SET last_used_at=? WHERE token_hash=?", (now, row["token_hash"]))
    return {"id": row["user_id"], "email": row["email"], "name": row["name"],
            "is_admin": row["is_admin"], "client_id": row["client_id"]}
