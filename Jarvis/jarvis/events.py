"""Bus de eventos: alimenta el panel HUD y el registro en disco."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

log = logging.getLogger("jarvis")


class EventBus:
    def __init__(self, maxlen: int = 400) -> None:
        self._events: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._next_id = 1
        self.state = "en espera"   # en espera | escuchando | pensando | hablando

    def emit(self, tipo: str, texto: str, canal: str = "", **extra) -> dict:
        with self._lock:
            ev = {"id": self._next_id, "t": time.time(), "tipo": tipo, "texto": texto, "canal": canal, **extra}
            self._next_id += 1
            self._events.append(ev)
        if tipo in ("usuario", "jarvis"):
            log.info("[%s] %s: %s", canal, "Tú" if tipo == "usuario" else "Jarvis", texto)
        elif tipo == "error":
            log.error("%s", texto)
        else:
            log.debug("%s: %s", tipo, texto)
        return ev

    def set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.emit("estado", state)

    def since(self, last_id: int) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e["id"] > last_id]
