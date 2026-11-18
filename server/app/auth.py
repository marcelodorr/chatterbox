from __future__ import annotations

import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from . import db
from .config import settings
from .security import hash_password, login_limiter, new_id, random_token, sha256, verify_password

COOKIE = "sid"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------- helpers
def create_user(email: str, password: str, name: str = "", is_admin: bool = False) -> dict:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "E-mail inválido")
    if len(password) < 8:
        raise HTTPException(400, "A senha precisa ter pelo menos 8 caracteres")
    if db.one("SELECT id FROM users WHERE email=?", (email,)):
        raise HTTPException(409, "Já existe um usuário com este e-mail")
    uid = new_id("u_")
    db.run(
        "INSERT INTO users (id, email, name, password_hash, is_admin, created_at) VALUES (?,?,?,?,?,?)",
        (uid, email, name.strip(), hash_password(password), int(is_admin), int(time.time())),
    )
    return public_user(db.one("SELECT * FROM users WHERE id=?", (uid,)))


def public_user(u: dict | None) -> dict | None:
    if not u:
        return None
    return {"id": u["id"], "email": u["email"], "name": u["name"], "is_admin": bool(u["is_admin"])}


def ensure_admin() -> None:
    if not settings.admin_email or not settings.admin_password:
        return
    if db.one("SELECT id FROM users WHERE email=?", (settings.admin_email,)):
        return
    create_user(settings.admin_email, settings.admin_password, "Admin", is_admin=True)


def start_session(response: Response, user_id: str) -> None:
    token = random_token()
    now = int(time.time())
    db.run(
        "INSERT INTO sessions (token_hash, user_id, csrf, expires_at, created_at) VALUES (?,?,?,?,?)",
        (sha256(token), user_id, random_token(16), now + settings.session_ttl, now),
    )
    db.run("DELETE FROM sessions WHERE expires_at < ?", (now,))
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.session_ttl,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
    )


def get_session(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    s = db.one(
        "SELECT s.csrf, s.expires_at, u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?",
        (sha256(token),),
    )
    if not s or s["expires_at"] < time.time():
        return None
    return s


def current_user(request: Request) -> dict:
    s = get_session(request)
    if not s:
        raise HTTPException(401, "Não autenticado")
    # Proteção extra contra CSRF em métodos que alteram estado:
    # o front sempre envia este header; formulários de outros sites não conseguem.
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-requested-with") != "fetch":
        raise HTTPException(403, "Requisição inválida")
    return s


def admin_user(user: dict = Depends(current_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(403, "Apenas administradores")
    return user


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


# ----------------------------------------------------------------- routes
class LoginIn(BaseModel):
    email: str
    password: str


class SignupIn(BaseModel):
    email: str
    password: str
    name: str = ""


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    key = f"{client_ip(request)}:{body.email.lower()}"
    if not login_limiter.allow(key):
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")
    u = db.one("SELECT * FROM users WHERE email=?", (body.email.strip().lower(),))
    if not u or not verify_password(body.password, u["password_hash"]):
        raise HTTPException(401, "E-mail ou senha incorretos")
    start_session(response, u["id"])
    return {"user": public_user(u)}


@router.post("/signup")
def signup(body: SignupIn, request: Request, response: Response):
    first_user = db.one("SELECT COUNT(*) AS n FROM users")["n"] == 0
    if not settings.allow_signup and not first_user:
        raise HTTPException(403, "Cadastro desativado. Peça um convite ao administrador.")
    if not login_limiter.allow(f"signup:{client_ip(request)}"):
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")
    user = create_user(body.email, body.password, body.name, is_admin=first_user)
    start_session(response, user["id"])
    return {"user": user}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        db.run("DELETE FROM sessions WHERE token_hash=?", (sha256(token),))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    s = get_session(request)
    first_user = db.one("SELECT COUNT(*) AS n FROM users")["n"] == 0
    return {
        "user": public_user(s) if s else None,
        "signup_allowed": settings.allow_signup or first_user,
        "app_name": settings.app_name,
    }
