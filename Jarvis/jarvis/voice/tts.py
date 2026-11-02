"""Voz de Jarvis: edge-tts (voces neuronales de Microsoft, gratis) + reproducción local."""
from __future__ import annotations

import asyncio
import io
import logging
import queue
import re
import threading

log = logging.getLogger("jarvis.tts")


def speakable(text: str) -> str:
    """Quita lo que no se debe leer en voz alta (markdown, enlaces, emojis)."""
    t = re.sub(r"https?://\S+", "", text)
    t = re.sub(r"[*_`#>|~]+", "", t)
    t = re.sub(r"^\s*(?:[-•]|\d+[.)])\s*", "", t, flags=re.M)
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", t)
    t = re.sub(r"\s*\n+\s*", ". ", t.strip())
    t = re.sub(r"([.!?,:;])\s*\.", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


class Speaker:
    def __init__(self, cfg: dict, events=None):
        v = cfg["voz"]
        self.voice = v.get("voz_tts") or "es-CL-LorenzoNeural"
        self.rate = v.get("velocidad_tts") or "+0%"
        self.events = events
        self._q: queue.Queue = queue.Queue()
        self._busy = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="tts", daemon=True)
        self._thread.start()

    @property
    def busy(self) -> bool:
        return self._busy.is_set() or not self._q.empty()

    def say(self, text: str, wait: bool = False) -> None:
        text = speakable(text)
        if not text:
            return
        done = threading.Event()
        self._busy.set()
        self._q.put((text, done))
        if wait:
            done.wait(timeout=120)

    def beep(self) -> None:
        try:
            import winsound
            winsound.Beep(1100, 90)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ interno
    async def _synth(self, text: str) -> bytes:
        import edge_tts
        comm = edge_tts.Communicate(text, self.voice, rate=self.rate)
        buf = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)

    def synth(self, text: str) -> bytes:
        return asyncio.run(self._synth(text))

    @staticmethod
    def _decode(mp3: bytes):
        import av
        import numpy as np
        container = av.open(io.BytesIO(mp3))
        res = av.AudioResampler(format="s16", layout="mono", rate=24000)
        chunks = []
        for frame in container.decode(audio=0):
            for f in res.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        for f in res.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
        container.close()
        return (np.concatenate(chunks) if chunks else np.zeros(1, dtype="int16")), 24000

    def _play(self, mp3: bytes) -> None:
        import sounddevice as sd

        from . import AUDIO_LOCK
        pcm, sr = self._decode(mp3)
        with AUDIO_LOCK:
            sd.play(pcm, sr)
            sd.wait()

    @staticmethod
    def _say_offline(text: str) -> None:
        """Respaldo sin internet: la voz local de Windows (SAPI), en español si está instalada."""
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        voice = comtypes.client.CreateObject("SAPI.SpVoice")
        voices = voice.GetVoices()
        for i in range(voices.Count):
            tok = voices.Item(i)
            try:
                lcid = int(str(tok.GetAttribute("Language")).split(";")[0], 16)
            except (ValueError, OSError):
                continue
            if lcid & 0x3FF == 0x0A:          # cualquier variante de español
                voice.Voice = tok
                break
        voice.Speak(text)

    def _worker(self) -> None:
        while True:
            text, done = self._q.get()
            self._busy.set()
            try:
                if self.events:
                    self.events.set_state("hablando")
                try:
                    mp3 = self.synth(text)
                except Exception as e:  # noqa: BLE001
                    log.warning("Voz en línea no disponible (%s); uso la voz de Windows.", e)
                    self._say_offline(text)
                else:
                    self._play(mp3)
            except Exception as e:  # noqa: BLE001
                log.error("No pude hablar: %s", e)
            finally:
                done.set()
                if self._q.empty():
                    self._busy.clear()
                    if self.events:
                        self.events.set_state("en espera")
