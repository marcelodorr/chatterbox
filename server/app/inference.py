from __future__ import annotations

import time

import httpx

from .config import settings

_models_cache: tuple[float, dict] | None = None


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.inference_token}"} if settings.inference_token else {}


async def get_models(force: bool = False) -> dict:
    """Catálogo de modelos do serviço de inferência (cache de 30 s)."""
    global _models_cache
    if not force and _models_cache and time.time() - _models_cache[0] < 30:
        return _models_cache[1]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{settings.inference_url}/models", headers=_headers())
            r.raise_for_status()
            data = r.json()
            data["online"] = True
    except Exception as e:  # noqa: BLE001
        data = {"online": False, "error": str(e), "models": [], "default": None, "device": None}
    _models_cache = (time.time(), data)
    return data


class InferenceError(RuntimeError):
    pass


async def synthesize(
    text: str,
    model: str,
    language: str,
    ref_audio: bytes | None,
    params: dict,
) -> tuple[bytes, float]:
    form = {
        "text": text,
        "model": model,
        "language": language,
        "exaggeration": str(params.get("exaggeration", 0.5)),
        "cfg_weight": str(params.get("cfg_weight", 0.5)),
        "temperature": str(params.get("temperature", 0.8)),
    }
    if params.get("seed") is not None:
        form["seed"] = str(int(params["seed"]))
    files = {"ref_audio": ("ref.wav", ref_audio, "audio/wav")} if ref_audio else None
    try:
        async with httpx.AsyncClient(timeout=settings.inference_timeout) as client:
            r = await client.post(f"{settings.inference_url}/synthesize", data=form, files=files, headers=_headers())
    except httpx.HTTPError as e:
        raise InferenceError(f"Serviço de inferência indisponível: {e}") from e
    if r.status_code != 200:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise InferenceError(str(detail)[:500])
    duration = float(r.headers.get("x-audio-duration", "0") or 0)
    return r.content, duration
