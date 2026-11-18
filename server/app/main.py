from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import api, auth, db, inference, jobs, mcp, oauth
from .config import settings

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    auth.ensure_admin()
    jobs.start()
    yield
    await jobs.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

app.include_router(oauth.router)
app.include_router(mcp.router)
app.include_router(auth.router)
app.include_router(api.router)
app.include_router(api.files_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if not request.url.path.startswith("/oauth/authorize"):
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


@app.get("/healthz")
async def healthz():
    models = await inference.get_models()
    return {"status": "ok", "inference_online": models.get("online", False)}


# ------------------------------------------------------------ SPA (React)
_dist = settings.web_dist
_RESERVED = ("api/", "oauth/", "mcp", ".well-known/", "files/", "healthz")

if (_dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    if full_path.startswith(_RESERVED):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    candidate = (_dist / full_path).resolve()
    if full_path and candidate.is_file() and _dist.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = _dist / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "Frontend não compilado. Rode `npm run build` em web/."}, status_code=404)
