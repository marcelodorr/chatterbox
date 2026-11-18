from __future__ import annotations

import asyncio
import io
import ipaddress
import socket
import tempfile
import wave
from urllib.parse import urlparse

import httpx

MAX_REF_SECONDS = 30
MIN_REF_SECONDS = 4


class AudioError(ValueError):
    pass


async def normalize_reference(data: bytes) -> tuple[bytes, float]:
    """Converte qualquer formato (mp3, m4a, webm, wav...) em WAV mono 24 kHz, até 30 s."""
    # Arquivo temporário (e não pipe): MP4/M4A podem ter o índice no fim do arquivo.
    with tempfile.NamedTemporaryFile(suffix=".bin") as src:
        src.write(data)
        src.flush()
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", src.name,
            "-t", str(MAX_REF_SECONDS),
            "-ac", "1", "-ar", "24000",
            "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    if proc.returncode != 0 or not out:
        raise AudioError("Não foi possível ler o arquivo de áudio. Envie WAV, MP3, M4A, OGG ou WEBM.")
    out = _pcm_to_wav(out)
    duration = wav_duration(out)
    if duration < MIN_REF_SECONDS:
        raise AudioError(f"O áudio precisa ter pelo menos {MIN_REF_SECONDS} segundos de fala (recomendado: 10 a 20 s).")
    return out, duration


def _pcm_to_wav(pcm: bytes, sr: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_duration(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        frames = w.getnframes()
        rate = w.getframerate()
    return frames / float(rate) if rate else 0.0


# ------------------------------------------------------------ safe fetching
def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


async def safe_fetch(url: str, max_bytes: int, timeout: float = 20.0) -> bytes:
    """Baixa uma URL pública (https) evitando SSRF para a rede interna."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise AudioError("A URL precisa ser https://")
    if not await asyncio.to_thread(_is_public_host, parsed.hostname):
        raise AudioError("URL não permitida")
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        async with client.stream("GET", url) as r:
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("location", "")
                if not loc:
                    raise AudioError("Redirecionamento inválido")
                return await safe_fetch(str(httpx.URL(url).join(loc)), max_bytes, timeout)
            if r.status_code != 200:
                raise AudioError(f"Falha ao baixar a URL (HTTP {r.status_code})")
            chunks: list[bytes] = []
            total = 0
            async for chunk in r.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise AudioError("Arquivo grande demais")
                chunks.append(chunk)
    return b"".join(chunks)
