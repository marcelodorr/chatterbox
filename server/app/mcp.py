"""Servidor MCP (transporte Streamable HTTP, modo sem estado, respostas JSON).

Endpoint: POST {PUBLIC_URL}/mcp com Authorization: Bearer <token OAuth>.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from . import db, inference, jobs, services
from .audio import AudioError, safe_fetch
from .config import settings
from .oauth import verify_access_token

log = logging.getLogger("mcp")
router = APIRouter(tags=["mcp"])

SUPPORTED_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
SERVER_INFO = {"name": "estudio-de-voz", "title": settings.app_name, "version": "1.0.0"}
INSTRUCTIONS = (
    "Ferramentas de texto-para-fala e clonagem de voz. Fluxo típico: chame list_voices para escolher "
    "uma voz e depois generate_speech. A geração pode demorar (o servidor pode estar em CPU); se o "
    "resultado vier com status 'queued' ou 'running', chame get_generation com o id até ficar 'done'. "
    "Entregue ao usuário o link download_url do áudio. Para clonar uma voz, o usuário precisa "
    "confirmar explicitamente que é dono da voz ou tem autorização."
)


# ------------------------------------------------------------------- tools
ToolFn = Callable[[dict, dict], Awaitable[dict]]
TOOLS: dict[str, tuple[dict, ToolFn]] = {}


def tool(definition: dict):
    def deco(fn: ToolFn) -> ToolFn:
        TOOLS[definition["name"]] = (definition, fn)
        return fn
    return deco


def _gen_payload(g: dict) -> dict:
    out = services.serialize_generation(g, with_signed_url=True)
    out.pop("audio_url", None)
    return out


def _gen_text(g: dict) -> str:
    if g["status"] == "done":
        return (f"Áudio pronto ({g['duration']:.1f}s, voz '{g['voice_name']}').\n"
                f"Download: {g['download_url']}\n(o link expira em {settings.audio_link_ttl // 86400} dias)")
    if g["status"] == "error":
        return f"A geração falhou: {g['error']}"
    pos = g.get("queue_position", 0)
    return (f"Geração {g['id']} está '{g['status']}'"
            + (f" ({pos} na frente na fila)" if pos else "")
            + ". Chame get_generation com este id para acompanhar.")


@tool({
    "name": "list_voices",
    "title": "Listar vozes",
    "description": "Lista as vozes disponíveis para o usuário (voz padrão, vozes clonadas e compartilhadas).",
    "inputSchema": {
        "type": "object",
        "properties": {"search": {"type": "string", "description": "Filtro opcional por nome/descrição"}},
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
})
async def t_list_voices(args: dict, user: dict) -> dict:
    voices = services.list_voices(user["id"], args.get("search") or "")
    slim = [{k: v[k] for k in ("id", "name", "description", "language", "kind")} for v in voices]
    text = "\n".join(f"- {v['name']} (id: {v['id']}){' — ' + v['description'] if v['description'] else ''}" for v in slim)
    return {"text": text or "Nenhuma voz encontrada.", "structured": {"voices": slim}}


@tool({
    "name": "list_models",
    "title": "Listar modelos",
    "description": "Lista os modelos de fala disponíveis e os idiomas suportados por cada um.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
})
async def t_list_models(args: dict, user: dict) -> dict:
    cat = await inference.get_models()
    if not cat.get("online"):
        return {"text": "O serviço de inferência está fora do ar no momento.", "structured": cat, "error": True}
    models = [{k: m[k] for k in ("id", "label", "description", "languages", "default")} for m in cat["models"]]
    text = "\n".join(f"- {m['id']}: {m['label']} — idiomas: {', '.join(m['languages'])}" for m in models)
    return {"text": text, "structured": {"models": models}}


@tool({
    "name": "generate_speech",
    "title": "Gerar fala",
    "description": (
        "Converte texto em áudio falado com uma voz da biblioteca. Retorna um link para download do WAV. "
        "Se não terminar dentro de wait_seconds, retorna o id para acompanhar com get_generation."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Texto a ser falado", "maxLength": settings.max_text_chars},
            "voice_id": {"type": "string", "description": "Id da voz (de list_voices). Padrão: 'default'"},
            "language": {"type": "string", "description": "Código do idioma, ex.: pt, en, es. Padrão: pt"},
            "model": {"type": "string", "description": "Id do modelo (de list_models). Opcional"},
            "exaggeration": {"type": "number", "minimum": 0.25, "maximum": 2.0,
                             "description": "Expressividade/emoção (0.5 = neutro)"},
            "cfg_weight": {"type": "number", "minimum": 0, "maximum": 1,
                           "description": "Ritmo/aderência à voz (menor = mais lento e deliberado)"},
            "temperature": {"type": "number", "minimum": 0.05, "maximum": 2.0},
            "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 55, "default": 45,
                             "description": "Quanto tempo esperar pelo resultado antes de retornar"},
        },
        "required": ["text"],
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
})
async def t_generate(args: dict, user: dict) -> dict:
    g = await services.start_generation(
        user["id"], args.get("text", ""), args.get("voice_id"), args.get("model"), args.get("language"),
        {k: args.get(k) for k in ("exaggeration", "cfg_weight", "temperature")}, source="mcp",
    )
    g = await jobs.wait(g["id"], float(args.get("wait_seconds", 45)))
    payload = _gen_payload(g)
    return {"text": _gen_text(payload), "structured": payload, "error": g["status"] == "error"}


@tool({
    "name": "get_generation",
    "title": "Status da geração",
    "description": "Consulta uma geração pelo id e retorna o link do áudio quando estiver pronta.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "generation_id": {"type": "string"},
            "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 55, "default": 30},
        },
        "required": ["generation_id"],
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
})
async def t_get_generation(args: dict, user: dict) -> dict:
    g = jobs.get(str(args.get("generation_id", "")))
    if not g or g["user_id"] != user["id"]:
        raise services.ServiceError("Geração não encontrada", 404)
    g = await jobs.wait(g["id"], float(args.get("wait_seconds", 30)))
    payload = _gen_payload(g)
    return {"text": _gen_text(payload), "structured": payload, "error": g["status"] == "error"}


@tool({
    "name": "list_generations",
    "title": "Histórico de gerações",
    "description": "Lista as gerações mais recentes do usuário.",
    "inputSchema": {
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}},
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
})
async def t_list_generations(args: dict, user: dict) -> dict:
    rows = db.all_(
        "SELECT * FROM generations WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user["id"], int(args.get("limit", 10))),
    )
    items = [_gen_payload(r) for r in rows]
    text = "\n".join(
        f"- {g['id']} [{g['status']}] voz {g['voice_name']}: \"{g['text'][:60]}\""
        + (f" → {g['download_url']}" if g.get("download_url") else "")
        for g in items
    )
    return {"text": text or "Nenhuma geração ainda.", "structured": {"generations": items}}


@tool({
    "name": "clone_voice",
    "title": "Clonar voz",
    "description": (
        "Cria uma nova voz a partir de um áudio de referência (10–30 s de fala limpa, uma só pessoa) "
        "disponível numa URL https pública. Só use com confirmação explícita do usuário de que ele é o "
        "dono da voz ou tem autorização."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "maxLength": 80},
            "audio_url": {"type": "string", "description": "URL https do áudio (wav, mp3, m4a, ogg, webm)"},
            "consent": {"type": "boolean",
                        "description": "true somente se o usuário confirmou ter direito/autorização sobre a voz"},
            "description": {"type": "string", "maxLength": 300},
            "language": {"type": "string", "description": "Idioma principal da voz, ex.: pt"},
        },
        "required": ["name", "audio_url", "consent"],
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
})
async def t_clone_voice(args: dict, user: dict) -> dict:
    if args.get("consent") is not True:
        raise services.ServiceError("É preciso o consentimento explícito do usuário (consent=true).")
    data = await safe_fetch(str(args.get("audio_url", "")), settings.max_upload_mb * 1024 * 1024)
    voice = await services.create_cloned_voice(
        user["id"], str(args.get("name", "")), data, True,
        str(args.get("description", "")), str(args.get("language", "")),
    )
    return {"text": f"Voz '{voice['name']}' criada (id: {voice['id']}).", "structured": {"voice": voice}}


# --------------------------------------------------------------- JSON-RPC
def _rpc_result(mid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _rpc_error(mid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


async def _handle(msg: dict, user: dict) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _rpc_error(None, -32600, "Invalid Request")
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    is_notification = "id" not in msg

    if method is None:  # resposta do cliente a algo nosso (não usamos)
        return None
    if is_notification:
        return None

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return _rpc_result(mid, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _rpc_result(mid, {})
    if method == "tools/list":
        return _rpc_result(mid, {"tools": [d for d, _ in TOOLS.values()]})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in TOOLS:
            return _rpc_error(mid, -32602, f"Ferramenta desconhecida: {name}")
        _, fn = TOOLS[name]
        try:
            out = await fn(args, user)
            result = {
                "content": [{"type": "text", "text": out["text"]}],
                "isError": bool(out.get("error")),
            }
            if out.get("structured") is not None:
                result["structuredContent"] = out["structured"]
            return _rpc_result(mid, result)
        except (services.ServiceError, AudioError, ValueError) as e:
            return _rpc_result(mid, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception as e:  # noqa: BLE001
            log.exception("erro na ferramenta %s", name)
            return _rpc_result(mid, {"content": [{"type": "text", "text": f"Erro interno: {e}"}], "isError": True})
    if method in ("resources/list", "prompts/list"):
        key = "resources" if method.startswith("resources") else "prompts"
        return _rpc_result(mid, {key: []})
    return _rpc_error(mid, -32601, f"Método não suportado: {method}")


def _unauthorized(error: str | None = None) -> Response:
    meta = f"{settings.public_url}/.well-known/oauth-protected-resource/mcp"
    value = f'Bearer resource_metadata="{meta}", scope="voice"'
    if error:
        value += f', error="{error}"'
    return JSONResponse(
        {"error": error or "unauthorized", "error_description": "Autenticação OAuth necessária"},
        status_code=401,
        headers={"WWW-Authenticate": value},
    )


def _origin_ok(request: Request) -> bool:
    """Proteção contra DNS rebinding: navegadores enviam Origin; clientes servidor-a-servidor não."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = urlparse(origin).hostname or ""
    allowed = {urlparse(settings.public_url).hostname, "claude.ai", "claude.com", "chatgpt.com",
               "chat.openai.com", "platform.openai.com", "localhost", "127.0.0.1"}
    return host in allowed or host.endswith(".claude.ai") or host.endswith(".openai.com")


@router.post("/mcp")
async def mcp_post(request: Request):
    if not _origin_ok(request):
        return JSONResponse({"error": "origin não permitida"}, status_code=403)
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return _unauthorized()
    user = verify_access_token(auth[7:].strip())
    if not user:
        return _unauthorized("invalid_token")

    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(_rpc_error(None, -32700, "Parse error"), status_code=400)

    if isinstance(body, list):  # lote (versões antigas do protocolo)
        responses = [r for r in [await _handle(m, user) for m in body] if r is not None]
        return JSONResponse(responses) if responses else Response(status_code=202)
    resp = await _handle(body, user)
    if resp is None:
        return Response(status_code=202)
    return JSONResponse(resp)


@router.get("/mcp")
async def mcp_get(request: Request):
    # Sem stream SSE iniciado pelo servidor (modo sem estado).
    if not request.headers.get("authorization"):
        return _unauthorized()
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp")
async def mcp_delete():
    return Response(status_code=405, headers={"Allow": "POST"})
