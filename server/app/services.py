"""Regras de negócio compartilhadas entre a API web e o servidor MCP."""
from __future__ import annotations

import json
import time

from . import db, inference, jobs
from .audio import normalize_reference
from .config import settings
from .security import new_id, signed_audio_url


class ServiceError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------- voices
def list_voices(user_id: str, search: str = "") -> list[dict]:
    rows = db.all_(
        "SELECT * FROM voices WHERE owner_id IS NULL OR owner_id=? OR is_shared=1 "
        "ORDER BY (kind='builtin') DESC, created_at DESC",
        (user_id,),
    )
    if search:
        s = search.lower()
        rows = [r for r in rows if s in r["name"].lower() or s in (r["description"] or "").lower()]
    return [serialize_voice(r, user_id) for r in rows]


def serialize_voice(v: dict, user_id: str) -> dict:
    return {
        "id": v["id"],
        "name": v["name"],
        "description": v["description"],
        "language": v["language"],
        "kind": v["kind"],
        "is_shared": bool(v["is_shared"]),
        "is_owner": v["owner_id"] == user_id,
        "has_sample": bool(v["ref_path"]),
        "sample_duration": v["ref_duration"],
        "created_at": v["created_at"],
    }


def get_voice_for_user(voice_id: str, user_id: str) -> dict:
    v = db.one(
        "SELECT * FROM voices WHERE id=? AND (owner_id IS NULL OR owner_id=? OR is_shared=1)",
        (voice_id, user_id),
    )
    if not v:
        raise ServiceError("Voz não encontrada", 404)
    return v


async def create_cloned_voice(
    user_id: str,
    name: str,
    audio: bytes,
    consent: bool,
    description: str = "",
    language: str = "",
    shared: bool = False,
) -> dict:
    if not consent:
        raise ServiceError(
            "Para clonar uma voz é preciso confirmar que você é o dono da voz ou tem autorização expressa dele."
        )
    name = name.strip()
    if not name:
        raise ServiceError("Dê um nome para a voz")
    if len(audio) > settings.max_upload_mb * 1024 * 1024:
        raise ServiceError(f"Arquivo maior que {settings.max_upload_mb} MB")
    wav, duration = await normalize_reference(audio)
    vid = new_id("v_")
    path = settings.data_dir / "voices" / f"{vid}.wav"
    path.write_bytes(wav)
    now = int(time.time())
    db.run(
        "INSERT INTO voices (id, owner_id, name, description, language, kind, is_shared, ref_path, ref_duration, consent_at, created_at) "
        "VALUES (?,?,?,?,?, 'cloned', ?, ?, ?, ?, ?)",
        (vid, user_id, name[:80], description.strip()[:300], language.strip()[:8], int(shared), str(path), duration, now, now),
    )
    return serialize_voice(db.one("SELECT * FROM voices WHERE id=?", (vid,)), user_id)


# ---------------------------------------------------------------- generation
DEFAULT_PARAMS = {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8}


async def start_generation(
    user_id: str,
    text: str,
    voice_id: str | None = None,
    model: str | None = None,
    language: str | None = None,
    params: dict | None = None,
    source: str = "web",
) -> dict:
    text = (text or "").strip()
    if not text:
        raise ServiceError("Digite um texto")
    if len(text) > settings.max_text_chars:
        raise ServiceError(f"Texto longo demais (máximo {settings.max_text_chars} caracteres)")

    catalog = await inference.get_models()
    models = {m["id"]: m for m in catalog.get("models", [])}
    if catalog.get("online") and models:
        model = model or catalog.get("default") or next(iter(models))
        if model not in models:
            raise ServiceError(f"Modelo inválido. Disponíveis: {', '.join(models)}")
        langs = models[model]["languages"]
        language = (language or ("pt" if "pt" in langs else langs[0])).lower()
        if language not in langs:
            raise ServiceError(f"O modelo {model} não suporta '{language}'. Idiomas: {', '.join(langs)}")
    else:
        # Serviço fora do ar: aceitamos e a fila tenta quando ele voltar.
        model = model or "mtl-v3"
        language = (language or "pt").lower()

    voice = get_voice_for_user(voice_id or "default", user_id)
    p = dict(DEFAULT_PARAMS)
    for k, v in (params or {}).items():
        if k in ("exaggeration", "cfg_weight", "temperature") and v is not None:
            p[k] = float(v)
        elif k == "seed" and v not in (None, ""):
            p["seed"] = int(v)
    p["exaggeration"] = min(max(p["exaggeration"], 0.25), 2.0)
    p["cfg_weight"] = min(max(p["cfg_weight"], 0.0), 1.0)
    p["temperature"] = min(max(p["temperature"], 0.05), 2.0)
    return jobs.enqueue(user_id, voice, model, language, text, p, source)


def serialize_generation(g: dict, with_signed_url: bool = False) -> dict:
    out = {
        "id": g["id"],
        "status": g["status"],
        "error": g["error"],
        "text": g["text"],
        "voice_id": g["voice_id"],
        "voice_name": g["voice_name"],
        "model": g["model"],
        "language": g["language"],
        "params": json.loads(g["params"] or "{}"),
        "duration": g["duration"],
        "source": g["source"],
        "created_at": g["created_at"],
        "finished_at": g["finished_at"],
    }
    if g["status"] in ("queued", "running"):
        out["queue_position"] = jobs.queue_position(g["id"])
    if g["status"] == "done":
        out["audio_url"] = f"/api/generations/{g['id']}/audio"
        if with_signed_url:
            out["download_url"] = signed_audio_url(g["id"])
    return out
