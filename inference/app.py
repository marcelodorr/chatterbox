"""Serviço HTTP de inferência (interno). Só deve ser acessado pela API principal.

Pode rodar no mesmo VPS (CPU) ou numa máquina com GPU; a API aponta para ele via INFERENCE_URL.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response

from engine import Engine

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("inference")

TOKEN = os.getenv("INFERENCE_TOKEN", "")
engine: Engine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    engine = Engine()
    preload = [m.strip() for m in os.getenv("PRELOAD_MODELS", "").split(",") if m.strip()]
    for mid in preload[: engine.max_loaded]:
        try:
            await asyncio.to_thread(_preload, mid)
        except Exception:  # noqa: BLE001
            log.exception("falha ao pré-carregar %s", mid)
    yield


def _preload(mid: str) -> None:
    assert engine is not None
    with engine.lock:
        engine.get_model(mid)


app = FastAPI(title="Chatterbox inference", lifespan=lifespan)


def _check(auth: str | None) -> None:
    if not TOKEN:
        return
    expected = f"Bearer {TOKEN}"
    if not auth or not hmac.compare_digest(auth, expected):
        raise HTTPException(401, "unauthorized")


@app.get("/health")
def health():
    assert engine is not None
    return {"status": "ok", "device": engine.device}


@app.get("/models")
def models(authorization: str | None = Header(default=None)):
    _check(authorization)
    assert engine is not None
    return {"device": engine.device, "default": engine.default_model, "models": engine.catalog()}


@app.post("/synthesize")
async def synthesize(
    text: str = Form(...),
    model: str = Form(""),
    language: str = Form(""),
    exaggeration: float = Form(0.5),
    cfg_weight: float = Form(0.5),
    temperature: float = Form(0.8),
    seed: int | None = Form(None),
    ref_audio: UploadFile | None = File(None),
    authorization: str | None = Header(default=None),
):
    _check(authorization)
    assert engine is not None
    ref = await ref_audio.read() if ref_audio is not None else None
    try:
        wav, duration = await asyncio.to_thread(
            engine.synthesize,
            text,
            model or None,
            language or None,
            ref or None,
            float(exaggeration),
            float(cfg_weight),
            float(temperature),
            seed,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return Response(wav, media_type="audio/wav", headers={"X-Audio-Duration": f"{duration:.3f}"})
