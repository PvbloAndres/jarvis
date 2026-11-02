"""Vigilante de Jarvis: lo enciende con Windows, sin ventana, y lo vuelve a encender si se cae.

    pythonw -m jarvis.servicio                 vigila (esto es lo que abre el acceso directo de Inicio)
    python  -m jarvis.servicio --activar       arranque automático al iniciar sesión en Windows
    python  -m jarvis.servicio --desactivar    quita el arranque automático
    python  -m jarvis.servicio --detener       apaga a Jarvis (y al vigilante)
    python  -m jarvis.servicio --estado        dice si está encendido
"""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .app import EXIT_RESTART
from .config import LOGS, ROOT
from .instancia import single_instance

log = logging.getLogger("jarvis.vigilante")
STARTUP = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
SHORTCUT = STARTUP / "JARVIS.lnk"


def _pythonw() -> str:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def _message_box(text: str) -> None:
    """Aviso visible aunque Jarvis corra sin ventana."""
    if sys.platform != "win32":
        return
    import ctypes
    threading.Thread(target=lambda: ctypes.windll.user32.MessageBoxW(None, text, "JARVIS", 0x40030),
                     daemon=True).start()


# --------------------------------------------------------------------- vigilar
def vigilar(retraso: int, abrir_panel: bool = False) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s vigilante: %(message)s",
                        handlers=[logging.handlers.RotatingFileHandler(
                            LOGS / "vigilante.log", maxBytes=500_000, backupCount=1, encoding="utf-8")])
    if not single_instance("vigilante"):
        log.info("Ya hay un vigilante en marcha; salgo.")
        if abrir_panel:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{int(_panel_cfg().get('puerto') or 8765)}")
        return
    if retraso:
        time.sleep(retraso)      # deja que Windows termine de levantar audio, Wi-Fi y OneDrive

    cmd = [_pythonw(), "-m", "jarvis", "--segundo-plano"]
    fast_fails, wait = 0, 5
    first = True
    while True:
        started = time.time()
        run_cmd = cmd + (["--abrir-panel"] if abrir_panel and first else [])
        first = False
        log.info("Encendiendo Jarvis: %s", " ".join(run_cmd))
        with open(LOGS / "consola.log", "a", encoding="utf-8") as out:
            out.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} inicio =====\n")
            out.flush()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            code = subprocess.call(run_cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, creationflags=flags)
        ran = time.time() - started
        log.info("Jarvis terminó con código %s tras %.0f s", code, ran)
        if code == 0:
            log.info("Apagado a pedido. El vigilante también se retira.")
            return
        if code == EXIT_RESTART:
            fast_fails, wait = 0, 5
            continue
        if ran > 300:                    # funcionó un buen rato: fue un tropiezo aislado
            fast_fails, wait = 0, 5
        fast_fails += 1
        if fast_fails == 4:
            _message_box("Jarvis se cae apenas enciende. Ejecuta probar.bat para ver qué falta "
                         f"(detalle en {LOGS / 'consola.log'}). Seguiré reintentando cada pocos minutos.")
        time.sleep(wait)
        wait = min(wait * 2, 300)


# ------------------------------------------------------------ arranque con Windows
def activar() -> None:
    STARTUP.mkdir(parents=True, exist_ok=True)
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:J_LNK);"
        "$s.TargetPath=$env:J_EXE; $s.Arguments='-m jarvis.servicio --retraso 20';"
        "$s.WorkingDirectory=$env:J_ROOT; $s.Description='Asistente JARVIS'; $s.WindowStyle=7; $s.Save()"
    )
    env = {**os.environ, "J_LNK": str(SHORTCUT), "J_EXE": _pythonw(), "J_ROOT": str(ROOT)}
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, capture_output=True, text=True)
    if r.returncode != 0 or not SHORTCUT.exists():
        sys.exit(f"No pude crear el acceso directo de inicio: {r.stderr.strip()}")
    print(f"Listo: Jarvis se encenderá solo cada vez que inicies sesión en Windows.\n  ({SHORTCUT})")


def desactivar() -> None:
    SHORTCUT.unlink(missing_ok=True)
    print("Listo: Jarvis ya no arranca solo con Windows.")


# ------------------------------------------------------------------ detener/estado
def _jarvis_processes():
    import psutil
    # Excluye este proceso y su lanzador (el python.exe del venv abre otro python.exe por debajo).
    me = {os.getpid()} | {p.pid for p in psutil.Process().parents()}
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = p.info["cmdline"] or []
            if p.info["pid"] not in me and "python" in (p.info["name"] or "").lower() and "-m" in cmd and \
                    any(a in ("jarvis", "jarvis.servicio") for a in cmd):
                yield p
        except Exception:  # noqa: BLE001
            continue


def _panel_cfg() -> dict:
    import yaml
    try:
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        cfg = {}
    return cfg.get("panel") or {}


def _api(path: str) -> bool:
    panel = _panel_cfg()
    headers = {"Content-Type": "application/json", "X-Jarvis": "1"}
    if (panel.get("token_api") or "").strip():
        headers["Authorization"] = f"Bearer {panel['token_api'].strip()}"
    req = urllib.request.Request(f"http://127.0.0.1:{int(panel.get('puerto') or 8765)}{path}", method="POST",
                                 headers=headers, data=json.dumps({}).encode())
    try:
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:  # noqa: BLE001
        return False


def detener() -> None:
    procs = list(_jarvis_processes())
    if not procs:
        print("Jarvis no estaba encendido.")
        return
    if _api("/api/apagar"):
        for _ in range(20):
            time.sleep(0.5)
            if not list(_jarvis_processes()):
                print("Jarvis apagado.")
                return
    # Plan B: cerrar primero al vigilante (para que no lo reviva) y luego a Jarvis.
    procs = sorted(_jarvis_processes(), key=lambda p: "jarvis.servicio" not in (p.info["cmdline"] or []))
    for p in procs:
        try:
            p.kill()
        except Exception:  # noqa: BLE001
            pass
    print("Jarvis apagado.")


def estado() -> None:
    procs = list(_jarvis_processes())
    vig = any("jarvis.servicio" in (p.info["cmdline"] or []) for p in procs)
    print(f"Jarvis: {'ENCENDIDO' if procs else 'apagado'}"
          + (" (vigilado: se reinicia solo si falla)" if vig else ""))
    print(f"Arranque con Windows: {'ACTIVADO' if SHORTCUT.exists() else 'desactivado'}")
    print(f"Registros: {LOGS}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="jarvis.servicio")
    ap.add_argument("--activar", action="store_true")
    ap.add_argument("--desactivar", action="store_true")
    ap.add_argument("--detener", action="store_true")
    ap.add_argument("--estado", action="store_true")
    ap.add_argument("--retraso", type=int, default=0, help="segundos de espera antes de encender")
    ap.add_argument("--abrir-panel", action="store_true", help="abre el panel la primera vez que enciende")
    a = ap.parse_args()
    if a.activar:
        activar()
    elif a.desactivar:
        desactivar()
    elif a.detener:
        detener()
    elif a.estado:
        estado()
    else:
        vigilar(a.retraso, a.abrir_panel)


if __name__ == "__main__":
    main()
