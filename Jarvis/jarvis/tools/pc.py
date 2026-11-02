"""Control del PC con Windows."""
from __future__ import annotations

import datetime as dt
import difflib
import os
import subprocess
import sys
import time
import unicodedata
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

import psutil

from ..config import DATA
from . import Ctx, Registry, ToolError

IS_WIN = sys.platform == "win32"

# Nombre hablado -> ejecutable o URI que Windows sabe abrir.
BUILTIN_APPS = {
    "calculadora": "calc.exe",
    "bloc de notas": "notepad.exe",
    "notepad": "notepad.exe",
    "explorador": "explorer.exe",
    "explorador de archivos": "explorer.exe",
    "mis documentos": str(Path.home() / "Documents"),
    "descargas": str(Path.home() / "Downloads"),
    "configuracion": "ms-settings:",
    "ajustes": "ms-settings:",
    "administrador de tareas": "taskmgr.exe",
    "paint": "mspaint.exe",
    "terminal": "wt.exe",
    "simbolo del sistema": "cmd.exe",
    "powershell": "powershell.exe",
    "spotify": "spotify:",
    "whatsapp": "whatsapp:",
    "tienda": "ms-windows-store:",
    "microsoft store": "ms-windows-store:",
    "camara": "microsoft.windows.camera:",
    "reloj": "ms-clock:",
    "alarmas": "ms-clock:",
    "fotos": "ms-photos:",
    "correo": "outlook:",
    "recortes": "ms-screenclip:",
    "enlace movil": "ms-phone:",
    "phone link": "ms-phone:",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "navegador": "https://www.google.com",
}

SETTINGS = {
    "inicio": "ms-settings:",
    "bluetooth": "ms-settings:bluetooth",
    "wifi": "ms-settings:network-wifi",
    "red": "ms-settings:network-status",
    "pantalla": "ms-settings:display",
    "sonido": "ms-settings:sound",
    "notificaciones": "ms-settings:notifications",
    "no_molestar": "ms-settings:notifications",
    "windows_update": "ms-settings:windowsupdate",
    "energia": "ms-settings:powersleep",
    "bateria": "ms-settings:batterysaver",
    "fondo": "ms-settings:personalization-background",
    "colores": "ms-settings:personalization-colors",
    "temas": "ms-settings:themes",
    "aplicaciones": "ms-settings:appsfeatures",
    "apps_predeterminadas": "ms-settings:defaultapps",
    "inicio_de_windows": "ms-settings:startupapps",
    "almacenamiento": "ms-settings:storagesense",
    "privacidad": "ms-settings:privacy",
    "microfono": "ms-settings:privacy-microphone",
    "camara": "ms-settings:privacy-webcam",
    "dispositivos_moviles": "ms-settings:mobile-devices",
    "raton": "ms-settings:mousetouchpad",
    "teclado": "ms-settings:typing",
    "fecha_hora": "ms-settings:dateandtime",
    "idioma": "ms-settings:regionlanguage",
    "voz": "ms-settings:speech",
    "juegos": "ms-settings:gaming-gamemode",
    "cuentas": "ms-settings:yourinfo",
    "acerca_de": "ms-settings:about",
    "impresoras": "ms-settings:printers",
    "vpn": "ms-settings:network-vpn",
}

PROTECTED = {"system", "system idle process", "csrss.exe", "winlogon.exe", "services.exe", "lsass.exe",
             "smss.exe", "wininit.exe", "svchost.exe", "dwm.exe", "explorer.exe", "python.exe", "pythonw.exe",
             "fontdrvhost.exe", "registry", "memcompression"}

VK = {"vol_up": 0xAF, "vol_down": 0xAE, "mute": 0xAD, "play_pause": 0xB3, "next": 0xB0, "prev": 0xB1}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


def _need_windows():
    if not IS_WIN:
        raise ToolError("Esta acción solo funciona en Windows.")


def _press(vk: int, times: int = 1):
    import ctypes
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.01)


def _endpoint_volume():
    """Devuelve el control de volumen de pycaw o None si no está disponible."""
    try:
        import comtypes
        comtypes.CoInitialize()
        from pycaw.pycaw import AudioUtilities
        dev = AudioUtilities.GetSpeakers()
        vol = getattr(dev, "EndpointVolume", None)   # pycaw moderno
        if vol is not None:
            return vol
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume
        iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(iface, POINTER(IAudioEndpointVolume))
    except Exception:  # noqa: BLE001
        return None


class StartMenu:
    """Índice de accesos directos del menú Inicio para abrir cualquier programa instalado."""

    def __init__(self):
        self._items: dict[str, str] = {}
        self._built = 0.0

    def _build(self):
        roots = [Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
                 Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
                 Path.home() / "Desktop"]
        items = {}
        for r in roots:
            if not r.exists():
                continue
            for p in list(r.rglob("*.lnk")) + list(r.rglob("*.url")):
                name = _norm(p.stem)
                if "uninstall" in name or "desinstalar" in name:
                    continue
                items.setdefault(name, str(p))
        self._items, self._built = items, time.time()

    def find(self, query: str) -> tuple[str, str] | None:
        if time.time() - self._built > 600:
            self._build()
        q = _norm(query)
        if q in self._items:
            return q, self._items[q]
        contains = [n for n in self._items if q in n]
        if contains:
            best = min(contains, key=len)
            return best, self._items[best]
        close = difflib.get_close_matches(q, list(self._items), n=1, cutoff=0.6)
        return (close[0], self._items[close[0]]) if close else None


def register(reg: Registry, app) -> None:
    cfg = app.cfg
    menu = StartMenu()
    custom_apps = {_norm(k): v for k, v in (cfg["pc"].get("apps") or {}).items()}
    comandos = cfg["pc"].get("comandos") or {}

    @reg.add("pc_abrir", "Abre un programa, carpeta o app del PC por su nombre (busca en el menú Inicio).",
             {"properties": {"nombre": {"type": "string", "description": "Ej: 'Spotify', 'Visual Studio Code', 'descargas'"}},
              "required": ["nombre"]}, group="pc")
    def pc_abrir(ctx: Ctx, nombre: str):
        _need_windows()
        q = _norm(nombre)
        target = custom_apps.get(q) or BUILTIN_APPS.get(q)
        label = nombre
        if not target:
            hit = menu.find(q)
            if hit:
                label, target = hit
        if not target:
            raise ToolError(f"No encontré '{nombre}' en el menú Inicio. Puedes añadirlo en config.yaml (pc > apps).")
        os.startfile(target)  # type: ignore[attr-defined]
        return f"Abriendo {label}."

    @reg.add("pc_cerrar_app", "Cierra un programa abierto por su nombre (ej: 'chrome', 'spotify').",
             {"properties": {"nombre": {"type": "string"}}, "required": ["nombre"]}, group="pc")
    def pc_cerrar_app(ctx: Ctx, nombre: str):
        q = _norm(nombre).replace(" ", "")
        alias = {"googlechrome": "chrome", "edge": "msedge", "word": "winword", "vscode": "code",
                 "visualstudiocode": "code", "bloc de notas": "notepad", "blocdenotas": "notepad"}
        q = alias.get(q, q)
        killed = set()
        for p in psutil.process_iter(["pid", "name"]):
            name = (p.info["name"] or "").lower()
            if p.info["pid"] == os.getpid() or name in PROTECTED:
                continue
            if q and q in name.replace(" ", ""):
                try:
                    p.terminate()
                    killed.add(p.info["name"])
                except psutil.Error:
                    pass
        return f"Cerré: {', '.join(sorted(killed))}." if killed else f"No vi ningún programa abierto llamado '{nombre}'."

    @reg.add("pc_abrir_web", "Abre una web en el navegador del PC, o busca en Google o YouTube.",
             {"properties": {
                 "url": {"type": "string", "description": "Dirección completa, ej: https://gmail.com"},
                 "buscar": {"type": "string", "description": "Texto a buscar"},
                 "sitio": {"type": "string", "enum": ["google", "youtube"], "description": "Dónde buscar (por defecto google)"},
             }}, group="pc")
    def pc_abrir_web(ctx: Ctx, url: str = "", buscar: str = "", sitio: str = "google"):
        if url:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
        elif buscar:
            url = (f"https://www.youtube.com/results?search_query={quote_plus(buscar)}" if sitio == "youtube"
                   else f"https://www.google.com/search?q={quote_plus(buscar)}")
        else:
            raise ToolError("Indica una url o qué buscar.")
        webbrowser.open(url)
        return f"Abrí {url}"

    @reg.add("pc_volumen", "Controla el volumen del PC.",
             {"properties": {
                 "accion": {"type": "string", "enum": ["subir", "bajar", "silenciar", "activar_sonido", "fijar", "consultar"]},
                 "nivel": {"type": "integer", "description": "0-100, solo para 'fijar'; para subir/bajar, cuántos puntos (por defecto 10)"},
             }, "required": ["accion"]}, group="pc")
    def pc_volumen(ctx: Ctx, accion: str, nivel: int | None = None):
        _need_windows()
        vol = _endpoint_volume()
        if vol is not None:
            cur = round(vol.GetMasterVolumeLevelScalar() * 100)
            if accion == "consultar":
                muted = bool(vol.GetMute())
                return f"Volumen al {cur}%" + (" (silenciado)" if muted else "")
            if accion == "silenciar":
                vol.SetMute(1, None)
                return "PC silenciado."
            if accion == "activar_sonido":
                vol.SetMute(0, None)
                return f"Sonido activado, volumen al {cur}%."
            step = int(nivel if nivel is not None else 10)
            new = {"subir": cur + step, "bajar": cur - step}.get(accion, nivel if nivel is not None else cur)
            new = max(0, min(100, int(new)))
            vol.SetMute(0, None)
            vol.SetMasterVolumeLevelScalar(new / 100, None)
            return f"Volumen del PC al {new}%."
        # Sin pycaw: teclas multimedia (cada pulsación = 2%)
        if accion == "consultar":
            return "No puedo leer el volumen exacto (falta pycaw), pero puedo subirlo o bajarlo."
        if accion in ("silenciar", "activar_sonido"):
            _press(VK["mute"])
            return "Alterné el silencio del PC."
        if accion == "fijar":
            _press(VK["vol_down"], 50)
            _press(VK["vol_up"], max(0, min(100, int(nivel or 0))) // 2)
            return f"Volumen del PC aproximadamente al {nivel}%."
        _press(VK["vol_up" if accion == "subir" else "vol_down"], max(1, int(nivel or 10) // 2))
        return f"Volumen {'subido' if accion == 'subir' else 'bajado'}."

    @reg.add("pc_multimedia", "Controla la música o el video que suena en el PC (Spotify, YouTube, etc.).",
             {"properties": {"accion": {"type": "string", "enum": ["play_pausa", "siguiente", "anterior"]}},
              "required": ["accion"]}, group="pc")
    def pc_multimedia(ctx: Ctx, accion: str):
        _need_windows()
        _press({"play_pausa": VK["play_pause"], "siguiente": VK["next"], "anterior": VK["prev"]}[accion])
        return {"play_pausa": "Reproducir/pausa.", "siguiente": "Siguiente pista.", "anterior": "Pista anterior."}[accion]

    @reg.add("pc_bloquear", "Bloquea la sesión de Windows (pantalla de inicio de sesión).", group="pc")
    def pc_bloquear(ctx: Ctx):
        _need_windows()
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return "PC bloqueado."

    @reg.add("pc_energia", "Apaga, reinicia o suspende el PC, o cancela un apagado programado.",
             {"properties": {
                 "accion": {"type": "string", "enum": ["apagar", "reiniciar", "suspender", "cancelar_apagado"]},
                 "minutos": {"type": "integer", "description": "Retraso en minutos para apagar/reiniciar (por defecto 1)"},
             }, "required": ["accion"]}, dangerous=True, group="pc")
    def pc_energia(ctx: Ctx, accion: str, minutos: int = 1):
        _need_windows()
        secs = max(0, int(minutos or 0)) * 60
        if accion == "cancelar_apagado":
            subprocess.run(["shutdown", "/a"], capture_output=True)
            return "Apagado cancelado."
        if accion == "apagar":
            subprocess.run(["shutdown", "/s", "/t", str(secs)], capture_output=True)
            return f"El PC se apagará en {minutos} minuto(s). Diga 'cancela el apagado' si cambia de opinión."
        if accion == "reiniciar":
            subprocess.run(["shutdown", "/r", "/t", str(secs)], capture_output=True)
            return f"El PC se reiniciará en {minutos} minuto(s)."
        import ctypes
        ctypes.windll.powrprof.SetSuspendState(False, True, False)
        return "Suspendiendo el PC."

    @reg.add("pc_ajustes", "Abre una sección concreta de la Configuración de Windows (ideal para guiar al usuario).",
             {"properties": {"seccion": {"type": "string", "enum": sorted(SETTINGS)}}, "required": ["seccion"]}, group="pc")
    def pc_ajustes(ctx: Ctx, seccion: str):
        _need_windows()
        os.startfile(SETTINGS.get(seccion, "ms-settings:"))  # type: ignore[attr-defined]
        return f"Abrí Configuración > {seccion.replace('_', ' ')}."

    @reg.add("pc_modo_oscuro", "Activa o desactiva el modo oscuro de Windows.",
             {"properties": {"activar": {"type": "boolean"}}, "required": ["activar"]}, group="pc")
    def pc_modo_oscuro(ctx: Ctx, activar: bool):
        _need_windows()
        import ctypes
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", 0, winreg.KEY_SET_VALUE)
        val = 0 if activar else 1
        winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, val)
        winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, val)
        winreg.CloseKey(key)
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "ImmersiveColorSet", 2, 3000, None)
        return f"Modo {'oscuro' if activar else 'claro'} activado."

    @reg.add("pc_brillo", "Cambia el brillo de la pantalla del PC (solo notebooks o pantallas compatibles).",
             {"properties": {"nivel": {"type": "integer", "description": "0-100"}}, "required": ["nivel"]}, group="pc")
    def pc_brillo(ctx: Ctx, nivel: int):
        _need_windows()
        n = max(0, min(100, int(nivel)))
        ps = f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{n})"
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=15)
        if r.returncode != 0 or r.stderr.strip():
            raise ToolError("Esta pantalla no permite cambiar el brillo por software (suele pasar en monitores de escritorio).")
        return f"Brillo al {n}%."

    @reg.add("pc_captura_pantalla", "Toma una captura de la pantalla del PC (se envía por Telegram si la pides desde ahí).",
             group="pc")
    def pc_captura_pantalla(ctx: Ctx):
        from PIL import ImageGrab
        path = DATA / "capturas" / f"pc_{dt.datetime.now():%Y%m%d_%H%M%S}.png"
        ImageGrab.grab(all_screens=True).save(path)
        ctx.attachments.append(str(path))
        return f"Captura guardada en {path}"

    @reg.add("pc_estado", "Estado del PC: CPU, memoria, disco, batería y tiempo encendido.", group="pc")
    def pc_estado(ctx: Ctx):
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\" if IS_WIN else "/")
        up = dt.timedelta(seconds=int(time.time() - psutil.boot_time()))
        txt = (f"CPU {cpu:.0f}%, RAM {mem.percent:.0f}% ({mem.used / 2**30:.1f} de {mem.total / 2**30:.1f} GB), "
               f"disco {disk.percent:.0f}% usado ({disk.free / 2**30:.0f} GB libres), encendido hace {up}.")
        bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if bat:
            txt += f" Batería {bat.percent:.0f}%{' cargando' if bat.power_plugged else ''}."
        top = sorted(psutil.process_iter(["name", "memory_info"]),
                     key=lambda p: (p.info["memory_info"].rss if p.info["memory_info"] else 0), reverse=True)[:3]
        txt += " Más memoria: " + ", ".join(p.info["name"] for p in top) + "."
        return txt

    if comandos:
        lista = "; ".join(f"{k}: {v.get('descripcion', '')}" for k, v in comandos.items())

        @reg.add("pc_comando", "Ejecuta uno de los comandos personalizados que el usuario definió en config.yaml. "
                 "Disponibles: " + lista,
                 {"properties": {"nombre": {"type": "string", "enum": sorted(comandos)}}, "required": ["nombre"]},
                 dangerous=True, group="pc")
        def pc_comando(ctx: Ctx, nombre: str):
            c = comandos.get(nombre)
            if not c:
                raise ToolError(f"No existe el comando '{nombre}'.")
            r = subprocess.run(c["comando"], shell=True, capture_output=True, text=True, timeout=120)
            out = (r.stdout or "") + (r.stderr or "")
            return f"Terminado (código {r.returncode}). {out.strip()[:1500]}"
