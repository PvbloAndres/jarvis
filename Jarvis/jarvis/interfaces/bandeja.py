"""Ícono junto al reloj de Windows: muestra el estado y permite pausar, reiniciar o apagar a Jarvis."""
from __future__ import annotations

import logging
import os
import threading
import time
import webbrowser

from ..config import LOGS

log = logging.getLogger("jarvis.bandeja")

COLORES = {
    "en espera": (0, 200, 255),
    "escuchando": (60, 230, 120),
    "pensando": (255, 176, 32),
    "hablando": (120, 170, 255),
    "pausado": (120, 120, 130),
}


def _icon_image(rgb: tuple[int, int, int]):
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, size - 4, size - 4), outline=rgb + (255,), width=6)       # anillo
    d.ellipse((22, 22, size - 22, size - 22), fill=rgb + (255,))                # núcleo
    return img


class Bandeja(threading.Thread):
    def __init__(self, app, panel_url: str | None):
        super().__init__(name="bandeja", daemon=True)
        self.app = app
        self.panel_url = panel_url
        self.icon = None
        self._images: dict = {}

    def _image(self, state: str):
        if state not in self._images:
            self._images[state] = _icon_image(COLORES.get(state, COLORES["en espera"]))
        return self._images[state]

    def run(self) -> None:
        try:
            import pystray
            from pystray import Menu, MenuItem as Item
        except Exception as e:  # noqa: BLE001
            log.warning("Sin ícono en la bandeja (falta pystray): %s", e)
            return
        app = self.app

        def abrir_panel(icon, item):
            if self.panel_url:
                webbrowser.open(self.panel_url)

        def pausar(icon, item):
            app.mic_paused = not app.mic_paused
            app.events.emit("sistema", "Micrófono en pausa." if app.mic_paused else "Micrófono activo.")

        def ver_registro(icon, item):
            os.startfile(LOGS / "jarvis.log")  # type: ignore[attr-defined]

        menu = Menu(
            Item("Abrir panel", abrir_panel, default=True, enabled=bool(self.panel_url)),
            Item("Pausar micrófono", pausar, checked=lambda item: app.mic_paused, enabled=app.voice_enabled),
            Item("Ver registro", ver_registro),
            Menu.SEPARATOR,
            Item("Reiniciar Jarvis", lambda icon, item: app.shutdown(restart=True)),
            Item("Apagar Jarvis", lambda icon, item: app.shutdown()),
        )
        self.icon = pystray.Icon("jarvis", self._image("en espera"), "JARVIS — en espera", menu)
        threading.Thread(target=self._follow_state, daemon=True).start()
        try:
            self.icon.run()
        except Exception as e:  # noqa: BLE001
            log.warning("El ícono de la bandeja se cerró: %s", e)

    def _follow_state(self) -> None:
        shown = None
        while True:
            state = self.app.events.state
            if state != shown and self.icon is not None:
                try:
                    self.icon.icon = self._image(state)
                    self.icon.title = f"JARVIS — {state}"
                    shown = state
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(0.4)
