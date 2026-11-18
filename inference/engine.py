"""Wrapper em torno dos modelos Chatterbox.

- Carrega modelos sob demanda (com limite de modelos em memória).
- Faz cache dos "conditionals" (embedding da voz de referência) por hash do áudio.
- Divide textos longos em trechos e concatena o resultado.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import tempfile
import threading
import time
import wave
from collections import OrderedDict
from pathlib import Path

import numpy as np
import torch

log = logging.getLogger("inference.engine")

MTL_LANGUAGES = [
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja",
    "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh",
]

# Catálogo de modelos expostos pela API.
MODEL_CATALOG: dict[str, dict] = {
    "mtl-v3": {
        "label": "Multilingual V3",
        "description": "Modelo geral, 23 idiomas (inclui português).",
        "kind": "mtl",
        "languages": MTL_LANGUAGES,
        "max_chunk_chars": 280,
    },
    "pt-br": {
        "label": "Português (Brasil)",
        "description": "Finetune dedicado ao português brasileiro.",
        "kind": "mtl",
        "languages": ["pt"],
        "max_chunk_chars": 280,
    },
    "turbo": {
        "label": "Turbo (inglês)",
        "description": "Baixa latência, aceita tags como [laugh] e [cough].",
        "kind": "turbo",
        "languages": ["en"],
        "max_chunk_chars": 400,
    },
    "nano": {
        "label": "Nano (inglês, CPU)",
        "description": "Modelo leve, ideal para CPU. Aceita tags como [laugh].",
        "kind": "turbo",
        "languages": ["en"],
        "max_chunk_chars": 400,
    },
}


def _env_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


def pick_device() -> str:
    forced = os.getenv("DEVICE", "").strip()
    if forced:
        return forced
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class Engine:
    def __init__(self) -> None:
        self.device = pick_device()
        self.enabled = [m for m in _env_list("ENABLED_MODELS", "mtl-v3,nano") if m in MODEL_CATALOG]
        if not self.enabled:
            raise RuntimeError("ENABLED_MODELS não contém nenhum modelo válido")
        self.default_model = os.getenv("DEFAULT_MODEL", self.enabled[0])
        if self.default_model not in self.enabled:
            self.default_model = self.enabled[0]
        self.max_loaded = max(1, int(os.getenv("MAX_LOADED_MODELS", "1")))
        self.cache_dir = Path(os.getenv("HF_HOME", str(Path.home() / ".cache" / "huggingface")))
        self._models: "OrderedDict[str, object]" = OrderedDict()
        self._builtin_conds: dict[str, object] = {}
        self._conds_cache: "OrderedDict[tuple[str, str], object]" = OrderedDict()
        self._conds_cache_size = int(os.getenv("VOICE_CACHE_SIZE", "32"))
        # Inferência é serializada: um modelo por vez, uma geração por vez.
        self.lock = threading.Lock()
        threads = os.getenv("TORCH_NUM_THREADS")
        if threads:
            torch.set_num_threads(int(threads))
        log.info("device=%s enabled=%s default=%s", self.device, self.enabled, self.default_model)

    # ------------------------------------------------------------------ models
    def catalog(self) -> list[dict]:
        out = []
        for mid in self.enabled:
            m = MODEL_CATALOG[mid]
            out.append({
                "id": mid,
                "label": m["label"],
                "description": m["description"],
                "kind": m["kind"],
                "languages": m["languages"],
                "loaded": mid in self._models,
                "default": mid == self.default_model,
            })
        return out

    def _load(self, model_id: str):
        kind = MODEL_CATALOG[model_id]["kind"]
        t0 = time.time()
        log.info("carregando modelo %s ...", model_id)
        if model_id == "mtl-v3":
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            model = ChatterboxMultilingualTTS.from_pretrained(self.device, t3_model="v3")
        elif model_id == "pt-br":
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            ckpt = self._prepare_ptbr_dir()
            model = ChatterboxMultilingualTTS.from_local(ckpt, self.device, t3_model="t3_pt_br.safetensors")
        elif kind == "turbo":
            from chatterbox.tts_turbo import ChatterboxTurboTTS
            model = ChatterboxTurboTTS.from_pretrained(self.device, nano=(model_id == "nano"))
        else:  # pragma: no cover
            raise ValueError(model_id)
        log.info("modelo %s carregado em %.1fs", model_id, time.time() - t0)
        return model

    def _prepare_ptbr_dir(self) -> Path:
        """Monta um diretório combinando o finetune pt-BR com os arquivos compartilhados do repo base."""
        from huggingface_hub import snapshot_download

        token = os.getenv("HF_TOKEN") or None
        base = Path(snapshot_download(
            repo_id="ResembleAI/chatterbox",
            allow_patterns=["ve.pt", "conds.pt", "Cangjie5_TC.json"],
            token=token,
        ))
        br = Path(snapshot_download(
            repo_id="ResembleAI/Chatterbox-Multilingual-pt-br",
            allow_patterns=["t3_pt_br.safetensors", "s3gen_v3.pt", "grapheme_mtl_merged_expanded_v1.json"],
            token=token,
        ))
        target = self.cache_dir / "combined" / "pt-br"
        target.mkdir(parents=True, exist_ok=True)
        links = {
            "ve.pt": base / "ve.pt",
            "conds.pt": base / "conds.pt",
            "Cangjie5_TC.json": base / "Cangjie5_TC.json",
            "t3_pt_br.safetensors": br / "t3_pt_br.safetensors",
            "grapheme_mtl_merged_expanded_v1.json": br / "grapheme_mtl_merged_expanded_v1.json",
            # O loader procura "s3gen.pt"; o pack pt-BR usa o decoder V3.
            "s3gen.pt": br / "s3gen_v3.pt",
        }
        for name, src in links.items():
            dst = target / name
            if dst.is_symlink() or dst.exists():
                dst.unlink()
            dst.symlink_to(src.resolve())
        return target

    def get_model(self, model_id: str):
        if model_id not in self.enabled:
            raise ValueError(f"Modelo '{model_id}' não está habilitado. Disponíveis: {', '.join(self.enabled)}")
        if model_id in self._models:
            self._models.move_to_end(model_id)
            return self._models[model_id]
        while len(self._models) >= self.max_loaded:
            old_id, _ = self._models.popitem(last=False)
            self._builtin_conds.pop(old_id, None)
            for key in [k for k in self._conds_cache if k[0] == old_id]:
                self._conds_cache.pop(key, None)
            log.info("descarregando modelo %s", old_id)
            if self.device == "cuda":
                torch.cuda.empty_cache()
        model = self._load(model_id)
        self._models[model_id] = model
        self._builtin_conds[model_id] = getattr(model, "conds", None)
        return model

    # ------------------------------------------------------------- conditionals
    def _set_voice(self, model_id: str, model, ref_audio: bytes | None, exaggeration: float):
        if not ref_audio:
            conds = self._builtin_conds.get(model_id)
            if conds is None:
                raise ValueError("Este modelo não tem voz padrão; escolha uma voz clonada.")
            model.conds = conds
            return
        key = (model_id, hashlib.sha256(ref_audio).hexdigest())
        cached = self._conds_cache.get(key)
        if cached is not None:
            self._conds_cache.move_to_end(key)
            model.conds = cached
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            tmp.write(ref_audio)
            tmp.flush()
            model.prepare_conditionals(tmp.name, exaggeration=exaggeration)
        self._conds_cache[key] = model.conds
        while len(self._conds_cache) > self._conds_cache_size:
            self._conds_cache.popitem(last=False)

    # --------------------------------------------------------------- synthesis
    def synthesize(
        self,
        text: str,
        model_id: str | None = None,
        language: str | None = None,
        ref_audio: bytes | None = None,
        exaggeration: float = 0.5,
        cfg_weight: float = 0.5,
        temperature: float = 0.8,
        seed: int | None = None,
    ) -> tuple[bytes, float]:
        model_id = model_id or self.default_model
        spec = MODEL_CATALOG.get(model_id)
        if spec is None:
            raise ValueError(f"Modelo desconhecido: {model_id}")
        language = (language or spec["languages"][0]).lower()
        if language not in spec["languages"]:
            raise ValueError(f"O modelo '{model_id}' não suporta o idioma '{language}'")
        text = text.strip()
        if not text:
            raise ValueError("Texto vazio")

        chunks = split_text(text, spec["max_chunk_chars"])
        with self.lock:
            model = self.get_model(model_id)
            self._set_voice(model_id, model, ref_audio, exaggeration)
            if seed is not None:
                torch.manual_seed(int(seed))
            sr = model.sr
            pieces: list[np.ndarray] = []
            gap = np.zeros(int(sr * 0.18), dtype=np.float32)
            for i, chunk in enumerate(chunks):
                log.info("[%s] trecho %d/%d (%d chars)", model_id, i + 1, len(chunks), len(chunk))
                if spec["kind"] == "mtl":
                    wav = model.generate(
                        chunk,
                        language_id=language,
                        exaggeration=exaggeration,
                        cfg_weight=cfg_weight,
                        temperature=temperature,
                    )
                else:
                    wav = model.generate(chunk, temperature=temperature)
                arr = wav.squeeze().detach().cpu().numpy().astype(np.float32)
                if pieces:
                    pieces.append(gap)
                pieces.append(arr)
        audio = np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.float32)
        return to_wav_bytes(audio, sr), len(audio) / sr


# ---------------------------------------------------------------------- utils
_SENTENCE_RE = re.compile(r"(?<=[.!?…。！？;])\s+|\n+")


def split_text(text: str, max_chars: int) -> list[str]:
    """Divide em frases e agrupa em trechos de até max_chars."""
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s and s.strip()]
    parts: list[str] = []
    for s in sentences:
        if len(s) <= max_chars:
            parts.append(s)
            continue
        # frase longa demais: quebra por vírgula e depois por espaço
        buf = ""
        for piece in re.split(r"(?<=[,:])\s+|\s+", s):
            if len(buf) + len(piece) + 1 > max_chars and buf:
                parts.append(buf)
                buf = piece
            else:
                buf = f"{buf} {piece}".strip()
        if buf:
            parts.append(buf)
    chunks: list[str] = []
    buf = ""
    for p in parts:
        if buf and len(buf) + len(p) + 1 > max_chars:
            chunks.append(buf)
            buf = p
        else:
            buf = f"{buf} {p}".strip()
    if buf:
        chunks.append(buf)
    return chunks


def to_wav_bytes(audio: np.ndarray, sr: int) -> bytes:
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()
