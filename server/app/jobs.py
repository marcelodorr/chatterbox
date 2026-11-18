"""Fila de geração em processo (asyncio). Rode a API com 1 worker do uvicorn."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from . import db, inference
from .config import settings
from .security import new_id

log = logging.getLogger("jobs")

_queue: "asyncio.Queue[str]" = asyncio.Queue()
_events: dict[str, asyncio.Event] = {}
_workers: list[asyncio.Task] = []


def _event(gid: str) -> asyncio.Event:
    ev = _events.get(gid)
    if ev is None:
        ev = _events[gid] = asyncio.Event()
    return ev


def enqueue(
    user_id: str,
    voice: dict,
    model: str,
    language: str,
    text: str,
    params: dict,
    source: str = "web",
) -> dict:
    gid = new_id("g_")
    db.run(
        "INSERT INTO generations (id, user_id, voice_id, voice_name, model, language, text, params, status, source, created_at) "
        "VALUES (?,?,?,?,?,?,?,?, 'queued', ?, ?)",
        (gid, user_id, voice["id"], voice["name"], model, language, text, json.dumps(params), source, int(time.time())),
    )
    _event(gid)
    _queue.put_nowait(gid)
    return get(gid)


def get(gid: str) -> dict | None:
    return db.one("SELECT * FROM generations WHERE id=?", (gid,))


def queue_position(gid: str) -> int:
    row = db.one(
        "SELECT COUNT(*) AS n FROM generations WHERE status IN ('queued','running') "
        "AND created_at <= (SELECT created_at FROM generations WHERE id=?) AND id != ?",
        (gid, gid),
    )
    return int(row["n"]) if row else 0


async def wait(gid: str, timeout: float) -> dict | None:
    g = get(gid)
    if not g or g["status"] in ("done", "error") or timeout <= 0:
        return g
    try:
        await asyncio.wait_for(_event(gid).wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    return get(gid)


async def _process(gid: str) -> None:
    g = get(gid)
    if not g or g["status"] not in ("queued", "running"):
        return
    db.run("UPDATE generations SET status='running', started_at=? WHERE id=?", (int(time.time()), gid))
    ref_audio = None
    try:
        voice = db.one("SELECT * FROM voices WHERE id=?", (g["voice_id"],)) if g["voice_id"] else None
        if voice and voice["ref_path"]:
            ref_audio = Path(voice["ref_path"]).read_bytes()
        wav, duration = await inference.synthesize(
            g["text"], g["model"], g["language"], ref_audio, json.loads(g["params"] or "{}")
        )
        path = settings.data_dir / "generations" / f"{gid}.wav"
        path.write_bytes(wav)
        db.run(
            "UPDATE generations SET status='done', audio_path=?, duration=?, finished_at=? WHERE id=?",
            (str(path), duration, int(time.time()), gid),
        )
    except Exception as e:  # noqa: BLE001
        log.exception("falha na geração %s", gid)
        db.run(
            "UPDATE generations SET status='error', error=?, finished_at=? WHERE id=?",
            (str(e)[:500], int(time.time()), gid),
        )
    finally:
        _event(gid).set()
        # limpa eventos antigos depois de um tempo
        asyncio.get_running_loop().call_later(600, _events.pop, gid, None)


async def _worker(n: int) -> None:
    while True:
        gid = await _queue.get()
        try:
            await _process(gid)
        finally:
            _queue.task_done()


def start() -> None:
    # Reenfileira o que ficou pendente num restart.
    for row in db.all_("SELECT id FROM generations WHERE status IN ('queued','running') ORDER BY created_at"):
        db.run("UPDATE generations SET status='queued' WHERE id=?", (row["id"],))
        _queue.put_nowait(row["id"])
    for i in range(max(1, settings.job_concurrency)):
        _workers.append(asyncio.create_task(_worker(i)))


async def stop() -> None:
    for t in _workers:
        t.cancel()
    _workers.clear()
