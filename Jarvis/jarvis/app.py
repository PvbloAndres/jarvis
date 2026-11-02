"""Jarvis: une el cerebro, las herramientas, la voz y las interfaces."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import logging.handlers
import os
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field

from .brain import BrainError, make_brain
from .config import LOGS, load_routines
from .events import EventBus
from .memory import Memory, Reminders
from .persona import dynamic_prompt, static_prompt
from .tools import Ctx, Registry

log = logging.getLogger("jarvis")
DIAS = {"lun": 0, "mar": 1, "mie": 2, "mié": 2, "jue": 3, "vie": 4, "sab": 5, "sáb": 5, "dom": 6}
EXIT_RESTART = 3        # código de salida que le pide al vigilante (servicio.py) volver a encender a Jarvis


@dataclass
class Reply:
    text: str
    attachments: list[str] = field(default_factory=list)


class Jarvis:
    def __init__(self, cfg: dict, voice: bool = True):
        self.cfg = cfg
        self.events = EventBus()
        self.memory = Memory()
        self.reminders = Reminders()
        self.routines = load_routines()
        self.adb = None
        self.voicemonkey = None
        self.mic_paused = False
        self._lock = threading.RLock()

        from .interfaces.telegram_bot import Notifier
        self.notifier = Notifier(cfg)

        # ---- herramientas
        self.registry = Registry()
        from .tools import general, pc
        general.register(self.registry, self)
        pc.register(self.registry, self)
        if cfg["telefono"].get("activado"):
            from .tools import phone
            phone.register(self.registry, self)
        if cfg["alexa"].get("activado"):
            from .tools import alexa
            alexa.register(self.registry, self)

        # ---- cerebro
        self._fixed_prompt = static_prompt(cfg)
        self.brain = make_brain(cfg, self.registry, self._prompts)

        # ---- voz (la salida por altavoz se usa también para recordatorios)
        self.voice_enabled = bool(voice and cfg["voz"].get("activada"))
        from .voice.stt import STT
        self.stt = STT(cfg)
        self.speaker = None
        try:
            from .voice.tts import Speaker
            self.speaker = Speaker(cfg, self.events)
        except Exception as e:  # noqa: BLE001
            log.warning("Sin voz de salida: %s", e)

    # ------------------------------------------------------------------ prompt
    def _prompts(self, ctx: Ctx) -> tuple[str, str]:
        extras = []
        if not self.cfg["telefono"].get("activado"):
            extras.append("- Teléfono: puente desactivado en config.yaml.")
        if not self.cfg["alexa"].get("activado"):
            extras.append("- Alexa: puente desactivado en config.yaml.")
        if not self.notifier.enabled:
            extras.append("- Telegram: no configurado.")
        return self._fixed_prompt, dynamic_prompt(self.cfg, self.memory.as_prompt(), ctx.channel, "\n".join(extras))

    # ---------------------------------------------------------------- peticiones
    def handle(self, text: str, channel: str = "consola", speak: bool = False) -> Reply:
        ctx = Ctx(channel=channel, app=self)
        self.events.emit("usuario", text, canal=channel)
        with self._lock:
            self.events.set_state("pensando")
            try:
                answer = self.brain.ask(text, ctx)
            except BrainError as e:
                answer = f"Lo siento, {self.cfg['usuario'].get('tratamiento') or 'señor'}: {e}"
                self.events.emit("error", str(e), canal=channel)
            except Exception as e:  # noqa: BLE001
                log.exception("Fallo inesperado")
                answer = f"Ha ocurrido un error inesperado: {e}"
                self.events.emit("error", str(e), canal=channel)
            finally:
                busy = bool(self.speaker and self.speaker.busy)
                self.events.set_state("hablando" if busy else "en espera")
        self.events.emit("jarvis", answer, canal=channel)
        if speak and self.speaker:
            self.speaker.say(answer)
        return Reply(answer, ctx.attachments)

    def handle_from_alexa(self, text: str) -> None:
        """Orden que llegó desde Alexa (TRIGGERcmd): responde por el Echo si se puede, si no por el PC."""
        reply = self.handle(text, channel="alexa")
        vm = self.voicemonkey
        if self.cfg["alexa"].get("responder_por_alexa") and vm and vm.enabled and vm.speakers:
            try:
                vm.announce(reply.text)
                return
            except Exception as e:  # noqa: BLE001
                log.warning("No pude responder por Alexa: %s", e)
        if self.speaker:
            self.speaker.say(reply.text)

    # ------------------------------------------------------------------ rutinas
    def run_routine(self, name: str, ctx: Ctx) -> str:
        key = name.strip().lower().replace(" ", "_")
        routine = self.routines.get(key) or next(
            (v for k, v in self.routines.items() if key in k or k in key), None)
        if not routine:
            return f"No existe la rutina '{name}'. Disponibles: {', '.join(self.routines) or 'ninguna'}."
        lines = []
        for step in routine.get("pasos") or []:
            if "decir" in step:
                lines.append(f"(decir) {step['decir']}")
                continue
            tool = step.get("herramienta")
            args = dict(step.get("args") or {})
            args.setdefault("confirmado", True)      # la rutina la escribiste tú: ya está autorizada
            out, err = self.registry.call(tool, args, ctx)
            lines.append(f"{tool}: {'ERROR ' if err else ''}{out}")
        return "Resultado de la rutina:\n" + "\n".join(lines)

    # ------------------------------------------------------------- avisos
    def notify(self, text: str, where: list[str] | None = None) -> None:
        where = where or self.cfg["general"].get("recordatorios_en") or ["pc", "telegram"]
        self.events.emit("jarvis", text, canal="rutina")
        if "pc" in where and self.speaker:
            self.speaker.say(text)
        if "telegram" in where:
            self.notifier.send(text)
        if "alexa" in where and self.voicemonkey and self.voicemonkey.enabled:
            try:
                self.voicemonkey.announce(text)
            except Exception as e:  # noqa: BLE001
                log.warning("Alexa no pudo anunciar: %s", e)

    def _scheduler(self) -> None:
        fired: set[str] = set()
        while True:
            try:
                for r in self.reminders.pop_due():
                    trato = self.cfg["usuario"].get("tratamiento") or "señor"
                    self.notify(f"Recordatorio, {trato}: {r['mensaje']}")
                now = dt.datetime.now()
                for name, rt in self.routines.items():
                    hora = str(rt.get("horario") or "").strip()
                    if not hora:
                        continue
                    dias_cfg = rt.get("dias")
                    dias = [DIAS.get(str(d).lower()[:3], -1) for d in dias_cfg] if dias_cfg else list(range(7))
                    tag = f"{name}@{now:%Y-%m-%d}"
                    if now.weekday() in dias and now.strftime("%H:%M") == hora.zfill(5) and tag not in fired:
                        fired.add(tag)
                        threading.Thread(target=self._scheduled_routine, args=(name, rt), daemon=True).start()
            except Exception:  # noqa: BLE001
                log.exception("Error en el programador")
            time.sleep(15)

    def _scheduled_routine(self, name: str, rt: dict) -> None:
        reply = self.handle(f"[Sistema] Es la hora de la rutina programada '{name}'. Ejecútala con ejecutar_rutina "
                            "y luego dame un saludo o aviso muy breve con lo importante del resultado.", channel="rutina")
        where = rt.get("anunciar_en") or ["pc", "telegram"]
        if "pc" in where and self.speaker:
            self.speaker.say(reply.text)
        if "telegram" in where:
            self.notifier.send(reply.text)
        if "alexa" in where and self.voicemonkey and self.voicemonkey.enabled:
            try:
                self.voicemonkey.announce(reply.text)
            except Exception as e:  # noqa: BLE001
                log.warning("Alexa no pudo anunciar: %s", e)

    # ------------------------------------------------------------------ estado
    def status(self) -> dict:
        c = self.cfg
        prov = c["cerebro"].get("proveedor", "claude")
        modelo = c["cerebro"].get("claude_modelo" if prov == "claude" else "gemini_modelo")
        items = [{"nombre": "Cerebro", "detalle": f"{prov} · {modelo}", "nivel": "on"}]
        if not self.voice_enabled:
            items.append({"nombre": "Voz", "detalle": "desactivada", "nivel": "warn"})
        elif self.mic_paused:
            items.append({"nombre": "Voz", "detalle": "micrófono en pausa", "nivel": "warn"})
        else:
            items.append({"nombre": "Voz", "detalle": f"\"Hey Jarvis\" · Whisper {self.stt.describe()}", "nivel": "on"})
        if c["telefono"].get("activado") and self.adb:
            try:
                devs = self.adb.devices()
                items.append({"nombre": "OnePlus 15", "detalle": "conectado" if devs else "no conectado",
                              "nivel": "on" if devs else "warn"})
            except Exception:  # noqa: BLE001
                items.append({"nombre": "OnePlus 15", "detalle": "adb no encontrado", "nivel": ""})
        else:
            items.append({"nombre": "OnePlus 15", "detalle": "desactivado", "nivel": ""})
        vm = self.voicemonkey
        items.append({"nombre": "Alexa", "detalle": (f"{len(vm.speakers)} parlante(s), {len(vm.routines)} rutina(s)"
                                                     if vm and vm.enabled else "desactivada"),
                      "nivel": "on" if vm and vm.enabled else ""})
        items.append({"nombre": "Telegram", "detalle": "activo" if self.notifier.enabled else "no configurado",
                      "nivel": "on" if self.notifier.enabled else ""})
        items.append({"nombre": "Rutinas", "detalle": f"{len(self.routines)} definidas", "nivel": "on" if self.routines else "warn"})
        return {"estado": self.events.state, "sistemas": items}

    # ---------------------------------------------------------------- apagado
    def shutdown(self, restart: bool = False) -> None:
        """Apaga a Jarvis (o lo reinicia si lo vigila servicio.py). Se puede llamar desde cualquier hilo."""
        self.events.emit("sistema", "Reiniciando Jarvis..." if restart else "Apagando Jarvis...")
        log.info("Salida pedida (reiniciar=%s)", restart)

        def _bye():
            time.sleep(0.5)          # deja responder a quien lo pidió (panel, bandeja)
            logging.shutdown()
            os._exit(EXIT_RESTART if restart else 0)
        threading.Thread(target=_bye, daemon=True).start()

    # -------------------------------------------------------------------- run
    def run(self, background: bool = False) -> None:
        """background=True: arrancó solo con Windows (sin ventana ni navegador)."""
        threading.Thread(target=self._scheduler, name="programador", daemon=True).start()

        url = None
        if self.cfg["panel"].get("activado"):
            from .interfaces.hud import HudServer
            try:
                hud = HudServer(self)
                hud.start()
                url = f"http://127.0.0.1:{hud.port}"
                self.events.emit("sistema", f"Panel en {url}")
                print(f"Panel HUD: {url}")
                if self.cfg["panel"].get("abrir_al_iniciar") and not background:
                    webbrowser.open(url)
            except OSError as e:
                self.events.emit("error", f"No pude abrir el panel (¿puerto ocupado?): {e}")

        if sys.platform == "win32":
            from .interfaces.bandeja import Bandeja
            Bandeja(self, url).start()

        if self.voice_enabled:
            from .voice.listener import VoiceLoop
            threading.Thread(target=self.stt.warmup, daemon=True).start()
            VoiceLoop(self).start()

        if self.speaker and self.voice_enabled:
            trato = self.cfg["usuario"].get("tratamiento") or "señor"
            self.speaker.say(f"Sistemas en línea. A su servicio, {trato}.")

        tg = self.cfg["telegram"]
        if tg.get("activado") and tg.get("token"):
            self._run_telegram()         # bloquea hasta Ctrl+C
        else:
            print("Jarvis en marcha. Pulsa Ctrl+C para salir.")
            while True:
                time.sleep(3600)

    def _run_telegram(self) -> None:
        """Mantiene vivo el bot: si no hay internet (p. ej. justo al encender el PC) reintenta solo."""
        from .interfaces.telegram_bot import TelegramBot
        wait, warned = 15, False
        while True:
            asyncio.set_event_loop(asyncio.new_event_loop())
            started = time.time()
            try:
                TelegramBot(self).run()
                return                   # terminó normalmente (Ctrl+C)
            except Exception as e:  # noqa: BLE001
                if time.time() - started > 300:
                    wait, warned = 15, False
                if not warned:
                    self.events.emit("error", f"Telegram sin conexión ({type(e).__name__}: {e}). Reintentando solo.")
                    warned = True
                log.warning("Telegram caído: %s. Reintento en %d s.", e, wait)
                time.sleep(wait)
                wait = min(wait * 2, 300)


def setup_logging() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.handlers.RotatingFileHandler(
        LOGS / "jarvis.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")]
    if sys.stderr is not None and sys.stderr.isatty():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)
    for noisy in ("httpx", "httpcore", "telegram", "urllib3", "faster_whisper", "anthropic", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
