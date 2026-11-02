"""Transcripción de voz a texto con faster-whisper (local, gratis y privado).

Usa la tarjeta gráfica NVIDIA si existe (mucho más rápido y permite un modelo más preciso);
si no, o si algo falla con CUDA, vuelve solo al procesador.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
from pathlib import Path

log = logging.getLogger("jarvis.stt")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


def _whisper(size: str, **kw):
    """Carga el modelo desde el disco (sirve sin internet); solo si no está, lo descarga."""
    from faster_whisper import WhisperModel
    try:
        return WhisperModel(size, local_files_only=True, **kw)
    except Exception:  # noqa: BLE001
        return WhisperModel(size, **kw)

# Frases que Whisper suele "alucinar" con silencio o ruido.
HALLUCINATIONS = [
    "subtítulos realizados por la comunidad de amara.org", "subtitulado por la comunidad de amara.org",
    "gracias por ver el video", "gracias por ver", "suscríbete", "¡suscríbete!", "amara.org", "música",
]
MODELO_GPU = "large-v3-turbo"   # casi la precisión de large-v3, varias veces más rápido
MODELO_CPU = "small"


def _add_nvidia_dlls() -> None:
    """Hace visibles las DLL de CUDA/cuDNN que instala pip (paquetes nvidia-*-cu12)."""
    if sys.platform != "win32":
        return
    for base in map(Path, sys.path):
        nv = base / "nvidia"
        if not nv.is_dir():
            continue
        for bin_dir in nv.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except OSError:
                pass
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def cuda_available() -> bool:
    try:
        _add_nvidia_dlls()
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


class STT:
    def __init__(self, cfg: dict):
        v = cfg["voz"]
        self.size_cfg = str(v.get("modelo_whisper") or "auto").strip().lower()
        self.device_cfg = str(v.get("dispositivo_whisper") or "auto").strip().lower()
        self._model = None
        self.device = "cpu"
        self.size = MODELO_CPU
        self._lock = threading.Lock()

    def _load_cpu(self):
        self.size = MODELO_CPU if self.size_cfg == "auto" else self.size_cfg
        log.info("Cargando Whisper '%s' en CPU...", self.size)
        self._model = _whisper(self.size, device="cpu", compute_type="int8")
        self.device = "cpu"
        return self._model

    def _load(self):
        if self._model is not None:
            return self._model
        if self.device_cfg != "cpu" and cuda_available():
            size = MODELO_GPU if self.size_cfg == "auto" else self.size_cfg
            try:
                log.info("Cargando Whisper '%s' en la GPU (la primera vez se descarga, puede tardar)...", size)
                model = _whisper(size, device="cuda", compute_type="float16")
                import numpy as np
                # cuDNN/cuBLAS recién se cargan al transcribir: pruébalo ahora y no con la primera orden.
                list(model.transcribe(np.zeros(16000, dtype=np.float32), language="es", beam_size=1)[0])
                self._model, self.size, self.device = model, size, "cuda"
                return model
            except Exception as e:  # noqa: BLE001
                log.warning("Whisper no pudo usar la GPU (%s); uso el procesador.", e)
        return self._load_cpu()

    def warmup(self) -> None:
        with self._lock:
            self._load()

    def describe(self) -> str:
        return f"{self.size} en {'GPU' if self.device == 'cuda' else 'CPU'}" if self._model else "sin cargar"

    def _run(self, model, audio) -> str:
        segments, _info = model.transcribe(
            audio, language="es", beam_size=5 if self.device == "cuda" else 1, vad_filter=True,
            initial_prompt="Jarvis, asistente. Alexa, OnePlus, Spotify, WhatsApp.")
        return " ".join(s.text.strip() for s in segments).strip()

    def transcribe(self, audio) -> str:
        """audio: ruta a un archivo (ogg, mp3, wav...) o numpy float32 mono 16 kHz."""
        with self._lock:
            model = self._load()
            try:
                text = self._run(model, audio)
            except RuntimeError as e:
                if self.device != "cuda":
                    raise
                log.warning("Falla de Whisper en la GPU (%s); paso al procesador.", e)
                text = self._run(self._load_cpu(), audio)
        clean = re.sub(r"[\s.!¡?¿,]+", " ", text.lower()).strip()
        if not clean or any(clean == re.sub(r"[\s.!¡?¿,]+", " ", h).strip() for h in HALLUCINATIONS):
            return ""
        return text
