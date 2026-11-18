from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import db, inference, jobs, services
from .audio import AudioError
from .auth import admin_user, create_user, current_user, public_user
from .config import settings
from .security import verify_audio_sig

router = APIRouter(prefix="/api", tags=["api"])
files_router = APIRouter(tags=["files"])


def _svc(fn):
    """Converte erros de serviço em HTTP."""
    try:
        return fn()
    except services.ServiceError as e:
        raise HTTPException(e.status, str(e)) from e


# --------------------------------------------------------------------- config
@router.get("/config")
async def config(user: dict = Depends(current_user)):
    models = await inference.get_models()
    return {
        "app_name": settings.app_name,
        "public_url": settings.public_url,
        "mcp_url": settings.mcp_resource,
        "max_text_chars": settings.max_text_chars,
        "inference": models,
    }


# --------------------------------------------------------------------- voices
@router.get("/voices")
def voices(search: str = "", user: dict = Depends(current_user)):
    return {"voices": services.list_voices(user["id"], search)}


@router.post("/voices")
async def create_voice(
    name: str = Form(...),
    consent: bool = Form(False),
    description: str = Form(""),
    language: str = Form(""),
    shared: bool = Form(False),
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
):
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    try:
        voice = await services.create_cloned_voice(
            user["id"], name, data, consent, description, language, shared=shared and bool(user["is_admin"])
        )
    except (services.ServiceError, AudioError) as e:
        raise HTTPException(getattr(e, "status", 400), str(e)) from e
    return {"voice": voice}


class VoicePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    language: str | None = None
    is_shared: bool | None = None


@router.patch("/voices/{voice_id}")
def update_voice(voice_id: str, body: VoicePatch, user: dict = Depends(current_user)):
    v = db.one("SELECT * FROM voices WHERE id=?", (voice_id,))
    if not v or v["kind"] == "builtin" or (v["owner_id"] != user["id"] and not user["is_admin"]):
        raise HTTPException(404, "Voz não encontrada")
    fields, values = [], []
    if body.name is not None and body.name.strip():
        fields.append("name=?"); values.append(body.name.strip()[:80])
    if body.description is not None:
        fields.append("description=?"); values.append(body.description.strip()[:300])
    if body.language is not None:
        fields.append("language=?"); values.append(body.language.strip()[:8])
    if body.is_shared is not None:
        if not user["is_admin"]:
            raise HTTPException(403, "Só administradores podem compartilhar vozes")
        fields.append("is_shared=?"); values.append(int(body.is_shared))
    if fields:
        db.run(f"UPDATE voices SET {', '.join(fields)} WHERE id=?", (*values, voice_id))
    return {"voice": services.serialize_voice(db.one("SELECT * FROM voices WHERE id=?", (voice_id,)), user["id"])}


@router.delete("/voices/{voice_id}")
def delete_voice(voice_id: str, user: dict = Depends(current_user)):
    v = db.one("SELECT * FROM voices WHERE id=?", (voice_id,))
    if not v or v["kind"] == "builtin" or (v["owner_id"] != user["id"] and not user["is_admin"]):
        raise HTTPException(404, "Voz não encontrada")
    db.run("DELETE FROM voices WHERE id=?", (voice_id,))
    if v["ref_path"]:
        Path(v["ref_path"]).unlink(missing_ok=True)
    return {"ok": True}


@router.get("/voices/{voice_id}/sample")
def voice_sample(voice_id: str, user: dict = Depends(current_user)):
    v = _svc(lambda: services.get_voice_for_user(voice_id, user["id"]))
    if not v["ref_path"] or not Path(v["ref_path"]).exists():
        raise HTTPException(404, "Esta voz não tem amostra")
    return FileResponse(v["ref_path"], media_type="audio/wav")


# ---------------------------------------------------------------- generations
class GenerateIn(BaseModel):
    text: str
    voice_id: str | None = None
    model: str | None = None
    language: str | None = None
    exaggeration: float | None = Field(default=None)
    cfg_weight: float | None = None
    temperature: float | None = None
    seed: int | None = None


@router.post("/generations")
async def generate(body: GenerateIn, user: dict = Depends(current_user)):
    try:
        g = await services.start_generation(
            user["id"], body.text, body.voice_id, body.model, body.language,
            {"exaggeration": body.exaggeration, "cfg_weight": body.cfg_weight,
             "temperature": body.temperature, "seed": body.seed},
        )
    except services.ServiceError as e:
        raise HTTPException(e.status, str(e)) from e
    return {"generation": services.serialize_generation(g)}


@router.get("/generations")
def list_generations(
    limit: int = Query(30, le=100),
    before: int | None = None,
    user: dict = Depends(current_user),
):
    rows = db.all_(
        "SELECT * FROM generations WHERE user_id=? AND created_at < ? ORDER BY created_at DESC LIMIT ?",
        (user["id"], before or int(time.time()) + 1, limit),
    )
    return {"generations": [services.serialize_generation(r) for r in rows]}


@router.get("/generations/{gid}")
async def get_generation(gid: str, wait: float = Query(0, le=25), user: dict = Depends(current_user)):
    g = jobs.get(gid)
    if not g or g["user_id"] != user["id"]:
        raise HTTPException(404, "Geração não encontrada")
    if wait:
        g = await jobs.wait(gid, wait)
    return {"generation": services.serialize_generation(g)}


@router.get("/generations/{gid}/audio")
def generation_audio(gid: str, download: bool = False, user: dict = Depends(current_user)):
    g = jobs.get(gid)
    if not g or g["user_id"] != user["id"] or g["status"] != "done":
        raise HTTPException(404, "Áudio não encontrado")
    return FileResponse(
        g["audio_path"], media_type="audio/wav",
        filename=f"{gid}.wav" if download else None,
    )


@router.delete("/generations/{gid}")
def delete_generation(gid: str, user: dict = Depends(current_user)):
    g = jobs.get(gid)
    if not g or g["user_id"] != user["id"]:
        raise HTTPException(404, "Geração não encontrada")
    if g["status"] in ("queued", "running"):
        raise HTTPException(409, "Aguarde a geração terminar")
    db.run("DELETE FROM generations WHERE id=?", (gid,))
    if g["audio_path"]:
        Path(g["audio_path"]).unlink(missing_ok=True)
    return {"ok": True}


@files_router.get("/files/audio/{gid}.wav")
def signed_audio(gid: str, exp: int, sig: str):
    """Link assinado usado pelo MCP (Claude/ChatGPT) para o usuário baixar o áudio."""
    if not verify_audio_sig(gid, exp, sig):
        raise HTTPException(403, "Link expirado ou inválido")
    g = jobs.get(gid)
    if not g or g["status"] != "done":
        raise HTTPException(404, "Áudio não encontrado")
    return FileResponse(g["audio_path"], media_type="audio/wav", filename=f"{gid}.wav")


# ---------------------------------------------------------- connected apps
@router.get("/connections")
def connections(user: dict = Depends(current_user)):
    rows = db.all_(
        "SELECT g.client_id, g.scope, g.created_at, c.client_name, c.client_uri, c.logo_uri, "
        "(SELECT MAX(COALESCE(t.last_used_at, t.created_at)) FROM oauth_tokens t "
        "  WHERE t.user_id=g.user_id AND t.client_id=g.client_id) AS last_used_at "
        "FROM oauth_grants g LEFT JOIN oauth_clients c ON c.client_id=g.client_id "
        "WHERE g.user_id=? ORDER BY g.created_at DESC",
        (user["id"],),
    )
    return {"connections": rows}


@router.delete("/connections/{client_id:path}")
def revoke_connection(client_id: str, user: dict = Depends(current_user)):
    db.run("UPDATE oauth_tokens SET revoked=1 WHERE user_id=? AND client_id=?", (user["id"], client_id))
    db.run("DELETE FROM oauth_grants WHERE user_id=? AND client_id=?", (user["id"], client_id))
    return {"ok": True}


# ---------------------------------------------------------------------- admin
class NewUser(BaseModel):
    email: str
    password: str
    name: str = ""
    is_admin: bool = False


@router.get("/admin/users")
def admin_list_users(_: dict = Depends(admin_user)):
    rows = db.all_("SELECT * FROM users ORDER BY created_at")
    return {"users": [dict(public_user(r), created_at=r["created_at"]) for r in rows]}


@router.post("/admin/users")
def admin_create_user(body: NewUser, _: dict = Depends(admin_user)):
    return {"user": create_user(body.email, body.password, body.name, body.is_admin)}


@router.delete("/admin/users/{uid}")
def admin_delete_user(uid: str, me: dict = Depends(admin_user)):
    if uid == me["id"]:
        raise HTTPException(400, "Você não pode remover a si mesmo")
    for v in db.all_("SELECT ref_path FROM voices WHERE owner_id=?", (uid,)):
        if v["ref_path"]:
            Path(v["ref_path"]).unlink(missing_ok=True)
    for g in db.all_("SELECT audio_path FROM generations WHERE user_id=?", (uid,)):
        if g["audio_path"]:
            Path(g["audio_path"]).unlink(missing_ok=True)
    db.run("DELETE FROM users WHERE id=?", (uid,))
    return {"ok": True}
