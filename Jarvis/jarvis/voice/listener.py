"""Oídos de Jarvis: detecta "Hey Jarvis", graba la orden y la transcribe."""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("jarvis.voice")

RATE = 16000
FRAME = 1280            # 80 ms, lo que espera openWakeWord


class VoiceLoop(threading.Thread):
    def __init__(self, app):
        super().__init__(name="voz", daemon=True)
        self.app = app
        v = app.cfg["voz"]
        self.threshold = float(v.get("palabra_clave_umbral") or 0.5)
        self.device = v.get("microfono")
        self.beep = bool(v.get("pitido_al_escuchar", True))
        self.running = True

    # ----------------------------------------------------------------- modelo
    @staticmethod
    def load_wakeword():
        import openwakeword
        from openwakeword.model import Model

        def build():
            try:
                return Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
            except TypeError:
                return Model(wakeword_models=["hey_jarvis"])
        try:
            return build()                # ya descargado: no necesita internet
        except Exception:  # noqa: BLE001
            pass
        try:
            openwakeword.utils.download_models(model_names=["hey_jarvis"])
        except TypeError:
            openwakeword.utils.download_models()
        return build()

    # ---------------------------------------------------------------- grabación
    def _record_command(self, stream, noise_floor: float):
        import numpy as np
        start_thr = max(noise_floor * 3.0, 350.0)
        stop_thr = max(noise_floor * 2.0, 250.0)
        frames, speaking, silent, waited = [], False, 0, 0
        max_frames = int(12 * RATE / FRAME)          # 12 s como máximo
        while len(frames) < max_frames:
            data, _ = stream.read(FRAME)
            chunk = data.reshape(-1)
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
            if not speaking:
                waited += 1
                frames.append(chunk)
                frames = frames[-4:]                   # guarda un poco de audio previo
                if rms > start_thr:
                    speaking = True
                elif waited > int(5 * RATE / FRAME):   # 5 s sin hablar: cancela
                    return None
                continue
            frames.append(chunk)
            silent = silent + 1 if rms < stop_thr else 0
            if silent > int(0.9 * RATE / FRAME):       # 0,9 s de silencio: fin de la orden
                break
        audio = np.concatenate(frames).astype(np.float32) / 32768.0
        return audio

    # --------------------------------------------------------------- bucle
    def _load_wakeword_retrying(self):
        """Al encender el PC puede no haber internet todavía: reintenta sin rendirse."""
        warned = False
        while self.running:
            try:
                return self.load_wakeword()
            except ImportError as e:
                self.app.events.emit("error", f"La voz no pudo iniciar: {e}. Ejecuta instalar.bat.")
                return None
            except Exception as e:  # noqa: BLE001
                if not warned:
                    self.app.events.emit("error", f"No pude cargar \"Hey Jarvis\" ({e}). Reintento cada 30 s.")
                    warned = True
                time.sleep(30)
        return None

    def run(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except Exception as e:  # noqa: BLE001
            self.app.events.emit("error", f"La voz no pudo iniciar: {e}. Jarvis sigue por Telegram y el panel.")
            return
        oww = self._load_wakeword_retrying()
        if oww is None:
            return
        from . import refresh_audio_devices
        app = self.app
        app.events.emit("sistema", "Micrófono activo. Diga \"Hey Jarvis\".")
        noise = 200.0
        failures = 0
        while self.running:
            if app.mic_paused:
                app.events.set_state("pausado")
                while app.mic_paused and self.running:
                    time.sleep(0.5)
                app.events.set_state("en espera")
                oww.reset()
            try:
                with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=FRAME,
                                    device=self.device) as stream:
                    failures = 0
                    last = time.monotonic()
                    while self.running and not app.mic_paused:
                        data, _ = stream.read(FRAME)
                        now = time.monotonic()
                        if now - last > 5:
                            # Hubo una pausa larga: el PC se suspendió. Reabre el micrófono por si cambió.
                            log.info("Reanudación detectada: reabro el micrófono.")
                            break
                        last = now
                        chunk = data.reshape(-1)
                        if app.speaker and app.speaker.busy:
                            oww.reset()
                            continue
                        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                        noise = 0.98 * noise + 0.02 * rms
                        scores = oww.predict(chunk)
                        if max(scores.values() or [0]) < self.threshold:
                            continue
                        oww.reset()
                        app.events.set_state("escuchando")
                        if self.beep and app.speaker:
                            app.speaker.beep()
                        audio = self._record_command(stream, noise)
                        if audio is None:
                            app.events.set_state("en espera")
                            last = time.monotonic()
                            continue
                        app.events.set_state("pensando")
                        text = app.stt.transcribe(audio)
                        last = time.monotonic()
                        if not text:
                            app.events.set_state("en espera")
                            continue
                        reply = app.handle(text, channel="voz")
                        if app.speaker:
                            app.speaker.say(reply.text, wait=True)
                        # descarta el audio acumulado mientras hablaba
                        avail = stream.read_available
                        if avail:
                            stream.read(avail)
                        oww.reset()
                        last = time.monotonic()
                if self.running and not app.mic_paused:
                    refresh_audio_devices()
            except Exception as e:  # noqa: BLE001
                failures += 1
                log.exception("Fallo en el micrófono")
                if failures in (1, 10) or failures % 60 == 0:     # no llenar el panel de avisos
                    app.events.emit("error", f"Micrófono: {e}. Sigo reintentando.")
                time.sleep(5 if failures < 10 else 30)
                try:
                    if not (app.speaker and app.speaker.busy):
                        refresh_audio_devices()     # por si enchufaste otro micrófono
                except Exception:  # noqa: BLE001
                    pass
