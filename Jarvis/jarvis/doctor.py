"""Diagnóstico: revisa cada pieza de Jarvis y dice qué falta."""
from __future__ import annotations

import shutil
import sys
import time

OK, FAIL, SKIP = "[ OK ]", "[FALLA]", "[ -- ]"


def line(tag: str, name: str, detail: str = "") -> None:
    print(f"{tag} {name}" + (f": {detail}" if detail else ""))


def run_checks(cfg: dict) -> None:
    print("\n=== Diagnóstico de JARVIS ===\n")
    print(f"Python {sys.version.split()[0]} en {sys.platform}")

    # 1. Cerebro
    from .brain import BrainError, make_brain
    from .tools import Registry
    try:
        brain = make_brain(cfg, Registry(), lambda ctx: ("", ""))
        t0 = time.time()
        out = brain.ping()
        line(OK, "Cerebro", f"{cfg['cerebro']['proveedor']} respondió «{out.strip()[:40]}» en {time.time() - t0:.1f} s")
    except BrainError as e:
        line(FAIL, "Cerebro", str(e))
    except Exception as e:  # noqa: BLE001
        line(FAIL, "Cerebro", f"{type(e).__name__}: {str(e)[:200]}")

    # 2. Audio
    if cfg["voz"].get("activada"):
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            default_in = sd.default.device[0]
            print("     Micrófonos disponibles (usa el número en voz > microfono si el predeterminado no sirve):")
            for i, d in enumerate(devs):
                if d["max_input_channels"] > 0:
                    mark = "  <- predeterminado" if i == default_in else ""
                    print(f"       {i}: {d['name']}{mark}")
            line(OK, "Audio", "sounddevice funciona")
        except Exception as e:  # noqa: BLE001
            line(FAIL, "Audio", str(e))
        try:
            from .voice.listener import VoiceLoop
            VoiceLoop.load_wakeword()
            line(OK, "Palabra clave", "modelo \"hey jarvis\" cargado")
        except Exception as e:  # noqa: BLE001
            line(FAIL, "Palabra clave", str(e))
        try:
            from .voice.stt import STT, cuda_available
            t0 = time.time()
            stt = STT(cfg)
            stt.warmup()
            line(OK, "Whisper", f"{stt.describe()} listo en {time.time() - t0:.0f} s")
            if stt.device == "cpu" and cuda_available():
                print("     Hay una GPU NVIDIA pero Whisper no pudo usarla: ejecuta instalar.bat de nuevo.")
        except Exception as e:  # noqa: BLE001
            line(FAIL, "Whisper", str(e))
    else:
        line(SKIP, "Voz", "desactivada en config.yaml")

    try:
        from .voice.tts import Speaker
        sp = Speaker(cfg)
        sp.say("Diagnóstico en curso. Si me escucha, la voz funciona.", wait=True)
        line(OK, "Voz de Jarvis", f"{cfg['voz']['voz_tts']} (¿la escuchaste?)")
    except Exception as e:  # noqa: BLE001
        line(FAIL, "Voz de Jarvis", str(e))

    # 3. Teléfono
    if cfg["telefono"].get("activado"):
        from .tools.phone import Adb
        adb = Adb(cfg)
        if not (shutil.which(adb.path) or adb.available()):
            line(FAIL, "Teléfono", "no encuentro adb (instala Platform Tools y revisa adb_ruta)")
        else:
            try:
                serial = adb.connect()
                model = adb.shell("getprop ro.product.model")
                ver = adb.shell("getprop ro.build.version.release")
                line(OK, "Teléfono", f"{model} (Android {ver}) conectado como {serial}")
            except Exception as e:  # noqa: BLE001
                line(FAIL, "Teléfono", str(e))
    else:
        line(SKIP, "Teléfono", "desactivado en config.yaml")

    # 4. Alexa
    if cfg["alexa"].get("activado"):
        from .tools.alexa import VoiceMonkey
        vm = VoiceMonkey(cfg)
        if not vm.enabled:
            line(FAIL, "Alexa", "falta voicemonkey_token")
        elif not vm.speakers:
            line(FAIL, "Alexa", "token presente, pero no hay parlantes en alexa > parlantes")
        else:
            try:
                name = vm.announce("Prueba de Jarvis. Conexión con Alexa correcta.")
                line(OK, "Alexa", f"anuncio enviado a '{name}'; rutinas configuradas: {', '.join(vm.routines) or 'ninguna'}")
            except Exception as e:  # noqa: BLE001
                line(FAIL, "Alexa", str(e))
    else:
        line(SKIP, "Alexa", "desactivada en config.yaml")

    # 5. Telegram
    tg = cfg["telegram"]
    if tg.get("activado"):
        import requests
        try:
            r = requests.get(f"https://api.telegram.org/bot{tg['token']}/getMe", timeout=10).json()
            if r.get("ok"):
                users = tg.get("usuarios_permitidos") or []
                extra = "" if users else " — escríbele al bot para conocer tu ID y ponlo en usuarios_permitidos"
                line(OK, "Telegram", f"bot @{r['result']['username']}{extra}")
            else:
                line(FAIL, "Telegram", "token inválido")
        except Exception as e:  # noqa: BLE001
            line(FAIL, "Telegram", str(e))
    else:
        line(SKIP, "Telegram", "desactivado en config.yaml")

    # 6. Arranque con Windows
    from .servicio import SHORTCUT
    if SHORTCUT.exists():
        line(OK, "Arranque con Windows", "activado (se enciende solo al iniciar sesión)")
    else:
        line(SKIP, "Arranque con Windows", "desactivado: ejecuta arranque-automatico.bat para activarlo")

    print("\nListo. Corrige lo que salga como [FALLA] y vuelve a ejecutar probar.bat.\n")
