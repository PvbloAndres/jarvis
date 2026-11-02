"""Punto de entrada:  python -m jarvis  [--probar | --consola | --sin-voz | --preparar | --segundo-plano]"""
from __future__ import annotations

import argparse
import os
import sys


def _no_console_fix() -> None:
    """Con pythonw no hay consola: sin esto, cualquier print o barra de descarga haría caer a Jarvis."""
    if sys.stdout is None or sys.stderr is None:
        from .config import LOGS
        LOGS.mkdir(parents=True, exist_ok=True)
        f = open(LOGS / "consola.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def preparar(cfg: dict) -> None:
    """Descarga ahora los modelos de voz para que Jarvis arranque rápido y sin internet."""
    import time
    print("Descargando modelo de la palabra clave \"Hey Jarvis\"...")
    from .voice.listener import VoiceLoop
    VoiceLoop.load_wakeword()
    print("Descargando y probando Whisper (la primera vez puede tardar varios minutos)...")
    from .voice.stt import STT
    t0 = time.time()
    stt = STT(cfg)
    stt.warmup()
    print(f"Whisper listo: {stt.describe()} ({time.time() - t0:.0f} s)")


def main() -> None:
    _no_console_fix()
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    ap = argparse.ArgumentParser(prog="jarvis", description="Asistente personal JARVIS")
    ap.add_argument("--probar", action="store_true", help="Revisa cada pieza (cerebro, micrófono, teléfono, Alexa, Telegram)")
    ap.add_argument("--consola", action="store_true", help="Chatear por texto en esta ventana (sin voz)")
    ap.add_argument("--sin-voz", action="store_true", help="Arranca sin micrófono ni palabra clave")
    ap.add_argument("--preparar", action="store_true", help="Descarga los modelos de voz y termina")
    ap.add_argument("--segundo-plano", action="store_true", help="Arranque automático con Windows (lo usa servicio.py)")
    ap.add_argument("--abrir-panel", action="store_true", help="Abre el panel aunque arranque en segundo plano")
    args = ap.parse_args()

    from .app import Jarvis, setup_logging
    from .config import ConfigError, load_config
    setup_logging()

    def fatal(title: str, msg: str) -> None:
        print(f"\n[{title}] {msg}\n")
        if args.segundo_plano and sys.platform == "win32":
            # Sin ventana nadie leería el error: se muestra en un aviso y no se reintenta en bucle.
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, f"{msg}\n\nCorrígelo y vuelve a abrir iniciar.bat.", f"JARVIS — {title.lower()}", 0x40030)
            sys.exit(0)
        sys.exit(1)

    try:
        cfg = load_config()
    except ConfigError as e:
        fatal("CONFIGURACIÓN", str(e))

    if args.probar:
        from .doctor import run_checks
        run_checks(cfg)
        return
    if args.preparar:
        preparar(cfg)
        return

    if not args.consola:
        from .instancia import single_instance
        if not single_instance("asistente"):
            print("Jarvis ya está encendido (mira el ícono junto al reloj).")
            if cfg["panel"].get("activado") and not args.segundo_plano:
                import webbrowser
                webbrowser.open(f"http://127.0.0.1:{int(cfg['panel'].get('puerto') or 8765)}")
            return

    from .brain import BrainError
    try:
        jarvis = Jarvis(cfg, voice=not (args.sin_voz or args.consola))
    except BrainError as e:
        fatal("CEREBRO", str(e))
    except ConfigError as e:          # rutinas.yaml mal escrito
        fatal("CONFIGURACIÓN", str(e))

    if args.consola:
        print("Consola de Jarvis. Escribe 'salir' para terminar.\n")
        while True:
            try:
                text = input("Tú> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text.lower() in ("salir", "exit", "quit"):
                break
            if text:
                reply = jarvis.handle(text, channel="consola")
                print(f"Jarvis> {reply.text}\n")
        return

    code = 0
    try:
        if args.abrir_panel:
            cfg["panel"]["abrir_al_iniciar"] = True
        jarvis.run(background=args.segundo_plano and not args.abrir_panel)
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("jarvis").exception("Jarvis se cayó")
        code = 2                     # el vigilante lo volverá a encender
    finally:
        print("\nJarvis desconectado.")
        os._exit(code)   # cierra también los hilos de voz y panel


if __name__ == "__main__":
    main()
