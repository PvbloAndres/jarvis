"""Puente con Alexa a través de Voice Monkey (API v3).

- Anuncios: Alexa dice en voz alta lo que Jarvis quiera, en el parlante Echo elegido.
- Rutinas: Jarvis 'toca' un Routine Trigger de Voice Monkey y la app Alexa ejecuta la rutina
  que tú hayas creado (luces, enchufes, TV, música...).
"""
from __future__ import annotations

import requests

from . import Ctx, Registry, ToolError

API = "https://api-v3.voicemonkey.io"


class VoiceMonkey:
    def __init__(self, cfg: dict):
        a = cfg["alexa"]
        self.token = (a.get("voicemonkey_token") or "").strip()
        self.speakers: dict[str, str] = {k: v for k, v in (a.get("parlantes") or {}).items() if v}
        self.main = a.get("parlante_principal") or next(iter(self.speakers), "")
        self.voice = (a.get("voz_polly") or "").strip()
        self.lang = (a.get("idioma") or "").strip()
        self.routines: dict[str, dict] = {}
        for k, v in (a.get("rutinas") or {}).items():
            v = v if isinstance(v, dict) else {"id": v}
            if v.get("id"):
                self.routines[k] = v

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def _post(self, endpoint: str, payload: dict) -> None:
        if not self.token:
            raise ToolError("Alexa no está configurada: falta voicemonkey_token en config.yaml.")
        r = requests.post(f"{API}/{endpoint}", json={"token": self.token, **payload}, timeout=15)
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code == 401:
            raise ToolError("Voice Monkey rechazó el token (revisa voicemonkey_token).")
        if r.status_code >= 400 or data.get("success") is False:
            raise ToolError(f"Voice Monkey respondió con error: {data or r.text[:200]}")

    def announce(self, text: str, speaker: str = "") -> str:
        name = speaker or self.main
        device = self.speakers.get(name) or (name if name in self.speakers.values() else "")
        if not device:
            raise ToolError("No hay parlantes configurados en config.yaml (alexa > parlantes). "
                            f"Disponibles: {', '.join(self.speakers) or 'ninguno'}.")
        payload = {"device": device, "speech": text}
        if self.voice:
            payload["voice"] = self.voice
        if self.lang:
            payload["language"] = self.lang
        self._post("announce", payload)
        return name

    def trigger(self, routine: str) -> dict:
        r = self.routines.get(routine)
        if not r:
            raise ToolError(f"No conozco la rutina de Alexa '{routine}'. Disponibles: {', '.join(self.routines) or 'ninguna'}.")
        self._post("trigger", {"device": r["id"]})
        return r


def register(reg: Registry, app) -> None:
    vm = VoiceMonkey(app.cfg)
    app.voicemonkey = vm
    g = "alexa"

    parlantes = ", ".join(vm.speakers) or "ninguno configurado"
    rutinas = "; ".join(f"{k}: {v.get('descripcion', '')}" for k, v in vm.routines.items()) or "ninguna configurada"

    @reg.add("alexa_anunciar", "Hace que Alexa diga un mensaje en voz alta en un parlante Echo. "
             f"Parlantes: {parlantes}.",
             {"properties": {
                 "mensaje": {"type": "string"},
                 "parlante": {"type": "string", "description": "Nombre del parlante (opcional)"},
             }, "required": ["mensaje"]}, group=g)
    def alexa_anunciar(ctx: Ctx, mensaje: str, parlante: str = ""):
        name = vm.announce(mensaje, parlante)
        return f"Alexa lo anunció en el parlante '{name}'."

    @reg.add("alexa_rutina", "Ejecuta una rutina de la app Alexa (luces, enchufes, TV, etc.). "
             f"Rutinas disponibles: {rutinas}.",
             {"properties": {"nombre": {"type": "string", "enum": sorted(vm.routines) or ["ninguna"]}},
              "required": ["nombre"]}, group=g)
    def alexa_rutina(ctx: Ctx, nombre: str):
        r = vm.trigger(nombre)
        return f"Rutina de Alexa '{nombre}' activada ({r.get('descripcion', '')})."
