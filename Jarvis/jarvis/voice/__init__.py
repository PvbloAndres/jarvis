"""Voz de Jarvis: oídos (listener, stt) y boca (tts)."""
import threading

# Protege a PortAudio: no se puede reiniciar la lista de dispositivos mientras suena la voz.
AUDIO_LOCK = threading.Lock()


def refresh_audio_devices() -> None:
    """Vuelve a leer micrófonos y parlantes (tras enchufar audífonos o despertar el PC)."""
    import sounddevice as sd
    with AUDIO_LOCK:
        try:
            sd._terminate()
        finally:
            sd._initialize()
