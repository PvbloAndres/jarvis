"""Control del OnePlus 15 (o cualquier Android 11+) por depuración inalámbrica ADB."""
from __future__ import annotations

import datetime as dt
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading

from ..config import DATA
from . import Ctx, Registry, ToolError

KNOWN_PACKAGES = {
    "whatsapp": "com.whatsapp", "spotify": "com.spotify.music", "youtube": "com.google.android.youtube",
    "youtube music": "com.google.android.apps.youtube.music", "instagram": "com.instagram.android",
    "chrome": "com.android.chrome", "maps": "com.google.android.apps.maps", "google maps": "com.google.android.apps.maps",
    "gmail": "com.google.android.gm", "telegram": "org.telegram.messenger", "netflix": "com.netflix.mediaclient",
    "tiktok": "com.zhiliaoapp.musically", "uber": "com.ubercab", "waze": "com.waze", "gemini": "com.google.android.apps.bard",
    "alexa": "com.amazon.dee.app", "calendario": "com.google.android.calendar", "fotos": "com.google.android.apps.photos",
    "x": "com.twitter.android", "twitter": "com.twitter.android", "facebook": "com.facebook.katana",
    "mensajes": "com.google.android.apps.messaging", "telefono": "com.google.android.dialer",
    "play store": "com.android.vending", "reloj": "com.google.android.deskclock", "discord": "com.discord",
    "mercado libre": "com.mercadolibre", "prime video": "com.amazon.avod.thirdpartyclient", "disney": "com.disney.disneyplus",
}

INTENTS = {
    "camara": "android.media.action.STILL_IMAGE_CAMERA",
    "ajustes": "android.settings.SETTINGS",
}

SETTINGS = {
    "general": "android.settings.SETTINGS",
    "wifi": "android.settings.WIFI_SETTINGS",
    "bluetooth": "android.settings.BLUETOOTH_SETTINGS",
    "pantalla": "android.settings.DISPLAY_SETTINGS",
    "sonido": "android.settings.SOUND_SETTINGS",
    "bateria": "android.intent.action.POWER_USAGE_SUMMARY",
    "ahorro_bateria": "android.settings.BATTERY_SAVER_SETTINGS",
    "no_molestar": "android.settings.ZEN_MODE_SETTINGS",
    "ubicacion": "android.settings.LOCATION_SOURCE_SETTINGS",
    "aplicaciones": "android.settings.APPLICATION_SETTINGS",
    "apps_predeterminadas": "android.settings.MANAGE_DEFAULT_APPS_SETTINGS",
    "seguridad": "android.settings.SECURITY_SETTINGS",
    "privacidad": "android.settings.PRIVACY_SETTINGS",
    "almacenamiento": "android.settings.INTERNAL_STORAGE_SETTINGS",
    "datos_moviles": "android.settings.DATA_ROAMING_SETTINGS",
    "nfc": "android.settings.NFC_SETTINGS",
    "fecha_hora": "android.settings.DATE_SETTINGS",
    "idioma": "android.settings.LOCALE_SETTINGS",
    "accesibilidad": "android.settings.ACCESSIBILITY_SETTINGS",
    "opciones_desarrollador": "android.settings.APPLICATION_DEVELOPMENT_SETTINGS",
    "acerca_del_telefono": "android.settings.DEVICE_INFO_SETTINGS",
    "notificaciones": "android.settings.NOTIFICATION_SETTINGS",
}

KEYCODES = {"play_pausa": 85, "siguiente": 87, "anterior": 88}


class Adb:
    def __init__(self, cfg: dict):
        t = cfg["telefono"]
        self.path = t.get("adb_ruta") or "adb"
        self.serial = (t.get("serie") or "").strip()
        self.ip = (t.get("ip") or "").strip()
        self._lock = threading.Lock()
        self._current = ""

    def available(self) -> bool:
        return bool(shutil.which(self.path)) or os.path.exists(self.path)

    def _run(self, args: list[str], timeout: float = 15, binary: bool = False):
        kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}   # sin ventana negra
        try:
            r = subprocess.run([self.path, *args], capture_output=True, timeout=timeout, **kw)
        except FileNotFoundError as e:
            raise ToolError("No encuentro adb. Instala Android Platform Tools y revisa 'adb_ruta' en config.yaml.") from e
        except subprocess.TimeoutExpired as e:
            raise ToolError("El teléfono no respondió a tiempo.") from e
        if binary:
            return r.returncode, r.stdout
        out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
        return r.returncode, out.strip()

    def devices(self) -> list[str]:
        _, out = self._run(["devices"])
        return [ln.split()[0] for ln in out.splitlines()
                if "\t" in ln and ln.strip().endswith("device") and not ln.startswith("*")]

    def connect(self) -> str:
        """Busca el teléfono: dispositivos ya conectados, mDNS (depuración inalámbrica) o IP fija."""
        with self._lock:
            devs = self.devices()
            if self.serial and self.serial in devs:
                self._current = self.serial
                return self._current
            if devs and not self.serial:
                self._current = devs[0]
                return self._current
            _, out = self._run(["mdns", "services"], timeout=8)
            for ln in out.splitlines():
                if "_adb-tls-connect" in ln:
                    m = re.search(r"(\d+\.\d+\.\d+\.\d+:\d+)", ln)
                    if m:
                        self._run(["connect", m[1]], timeout=8)
            if self.ip:
                target = self.ip if ":" in self.ip else f"{self.ip}:5555"
                self._run(["connect", target], timeout=8)
            devs = self.devices()
            if self.serial and self.serial in devs:
                self._current = self.serial
            elif devs:
                self._current = devs[0]
            else:
                self._current = ""
                raise ToolError("El teléfono no está conectado. Revisa que esté en el mismo Wi-Fi que el PC y "
                                "que la depuración inalámbrica esté activada (Opciones de desarrollador).")
            return self._current

    def shell(self, cmd: str, timeout: float = 15) -> str:
        serial = self._current or self.connect()
        code, out = self._run(["-s", serial, "shell", cmd], timeout=timeout)
        if code != 0 and ("not found" in out or "offline" in out or "no devices" in out):
            serial = self.connect()
            code, out = self._run(["-s", serial, "shell", cmd], timeout=timeout)
        return out

    def exec_out(self, cmd: str) -> bytes:
        serial = self._current or self.connect()
        _, data = self._run(["-s", serial, "exec-out", cmd], timeout=30, binary=True)
        return data


def register(reg: Registry, app) -> None:
    adb = Adb(app.cfg)
    app.adb = adb
    g = "telefono"

    @reg.add("tel_estado", "Comprueba si el teléfono está conectado y da su batería, carga y temperatura.", group=g)
    def tel_estado(ctx: Ctx):
        serial = adb.connect()
        out = adb.shell("dumpsys battery")
        vals = dict(re.findall(r"^\s*([\w ]+):\s*(.+)$", out, re.M))
        level = vals.get("level", "?")
        status = {"2": "cargando", "3": "descargando", "4": "sin cargar", "5": "carga completa"}.get(vals.get("status", ""), "")
        temp = vals.get("temperature")
        temp_txt = f", {int(temp) / 10:.0f}°C" if temp and temp.isdigit() else ""
        return f"Teléfono conectado ({serial}). Batería {level}% {status}{temp_txt}."

    @reg.add("tel_volumen", "Cambia el volumen del teléfono (multimedia o timbre).",
             {"properties": {
                 "accion": {"type": "string", "enum": ["subir", "bajar", "fijar", "silenciar", "consultar"]},
                 "tipo": {"type": "string", "enum": ["multimedia", "timbre"], "description": "Por defecto multimedia"},
                 "nivel": {"type": "integer", "description": "0-100 para 'fijar'"},
             }, "required": ["accion"]}, group=g)
    def tel_volumen(ctx: Ctx, accion: str, tipo: str = "multimedia", nivel: int | None = None):
        stream = 2 if tipo == "timbre" else 3
        out = adb.shell(f"cmd media_session volume --stream {stream} --get")
        m = re.search(r"volume is (\d+) in range \[(\d+)\.\.(\d+)\]", out)
        cur, lo, hi = (int(m[1]), int(m[2]), int(m[3])) if m else (None, 0, 15)
        if accion == "consultar":
            return f"Volumen de {tipo}: {round(100 * cur / hi)}%." if cur is not None else "No pude leer el volumen."
        if accion == "silenciar":
            new = lo
        elif accion == "fijar":
            new = round(hi * max(0, min(100, int(nivel or 0))) / 100)
        else:
            base = cur if cur is not None else hi // 2
            step = max(1, round(hi * (nivel or 15) / 100))
            new = base + step if accion == "subir" else base - step
        new = max(lo, min(hi, new))
        adb.shell(f"cmd media_session volume --stream {stream} --set {new}")
        return f"Volumen de {tipo} del teléfono al {round(100 * new / hi)}%."

    @reg.add("tel_no_molestar", "Activa o desactiva el modo No molestar del teléfono.",
             {"properties": {"activar": {"type": "boolean"}}, "required": ["activar"]}, group=g)
    def tel_no_molestar(ctx: Ctx, activar: bool):
        out = adb.shell(f"cmd notification set_dnd {'on' if activar else 'off'}")
        if "Unknown" in out or "Error" in out:
            raise ToolError("El teléfono no aceptó el comando de No molestar.")
        return f"No molestar {'activado' if activar else 'desactivado'} en el teléfono."

    @reg.add("tel_abrir_app", "Abre una app en el teléfono por su nombre (ej: WhatsApp, Spotify, cámara).",
             {"properties": {"nombre": {"type": "string"}}, "required": ["nombre"]}, group=g)
    def tel_abrir_app(ctx: Ctx, nombre: str):
        q = re.sub(r"[^a-z0-9 ]", "", nombre.lower().replace("á", "a").replace("é", "e").replace("í", "i")
                   .replace("ó", "o").replace("ú", "u")).strip()
        if q in INTENTS:
            adb.shell(f"am start -a {INTENTS[q]}")
            return f"Abrí {nombre} en el teléfono."
        pkg = KNOWN_PACKAGES.get(q)
        if not pkg:
            pkgs = [ln.replace("package:", "").strip() for ln in adb.shell("pm list packages").splitlines()]
            token = q.replace(" ", "")
            cands = [p for p in pkgs if token and token in p.lower().replace(".", "").replace("_", "")]
            pkg = min(cands, key=len) if cands else None
        if not pkg or not re.fullmatch(r"[\w.]+", pkg):
            raise ToolError(f"No encontré la app '{nombre}' en el teléfono.")
        out = adb.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
        if "No activities found" in out:
            raise ToolError(f"La app {pkg} no se puede abrir directamente.")
        return f"Abrí {nombre} en el teléfono."

    @reg.add("tel_abrir_ajustes", "Abre una pantalla concreta de Ajustes en el teléfono (para guiar al usuario).",
             {"properties": {"seccion": {"type": "string", "enum": sorted(SETTINGS)}}, "required": ["seccion"]}, group=g)
    def tel_abrir_ajustes(ctx: Ctx, seccion: str):
        out = adb.shell(f"am start -a {SETTINGS.get(seccion, SETTINGS['general'])}")
        if "Error" in out:
            adb.shell(f"am start -a {SETTINGS['general']}")
            return f"No existe un acceso directo a '{seccion}' en este teléfono; abrí Ajustes generales."
        return f"Abrí Ajustes > {seccion.replace('_', ' ')} en el teléfono."

    @reg.add("tel_multimedia", "Controla la música o el video del teléfono.",
             {"properties": {"accion": {"type": "string", "enum": list(KEYCODES)}}, "required": ["accion"]}, group=g)
    def tel_multimedia(ctx: Ctx, accion: str):
        adb.shell(f"input keyevent {KEYCODES[accion]}")
        return "Listo."

    @reg.add("tel_brillo", "Fija el brillo de la pantalla del teléfono (desactiva el brillo automático).",
             {"properties": {"nivel": {"type": "integer", "description": "0-100"}}, "required": ["nivel"]}, group=g)
    def tel_brillo(ctx: Ctx, nivel: int):
        n = max(0, min(100, int(nivel)))
        adb.shell("settings put system screen_brightness_mode 0")
        out = adb.shell(f"cmd display set-brightness {n / 100:.2f}")
        if "Unknown" in out or "Error" in out:
            adb.shell(f"settings put system screen_brightness {round(255 * n / 100)}")
        return f"Brillo del teléfono al {n}%."

    @reg.add("tel_conectividad", "Enciende o apaga el Wi-Fi o el Bluetooth del teléfono.",
             {"properties": {
                 "radio": {"type": "string", "enum": ["wifi", "bluetooth"]},
                 "activar": {"type": "boolean"},
                 "confirmado": {"type": "boolean", "description": "Necesario para APAGAR el Wi-Fi (corta la conexión con Jarvis)."},
             }, "required": ["radio", "activar"]}, group=g)
    def tel_conectividad(ctx: Ctx, radio: str, activar: bool, confirmado: bool = False):
        if radio == "wifi":
            if not activar and not confirmado:
                return ("ACCIÓN NO EJECUTADA: apagar el Wi-Fi del teléfono cortará mi conexión con él hasta que "
                        "lo vuelva a encender a mano. Pregunta al usuario si está seguro.")
            adb.shell(f"cmd wifi set-wifi-enabled {'enabled' if activar else 'disabled'}")
            return f"Wi-Fi del teléfono {'encendido' if activar else 'apagado'}."
        out = adb.shell(f"cmd bluetooth_manager {'enable' if activar else 'disable'}")
        if "Unknown" in out or "not found" in out:
            adb.shell(f"svc bluetooth {'enable' if activar else 'disable'}")
        return f"Bluetooth del teléfono {'encendido' if activar else 'apagado'}."

    @reg.add("tel_ahorro_bateria", "Activa o desactiva el ahorro de batería del teléfono.",
             {"properties": {"activar": {"type": "boolean"}}, "required": ["activar"]}, group=g)
    def tel_ahorro_bateria(ctx: Ctx, activar: bool):
        out = adb.shell(f"cmd power set-mode {1 if activar else 0}")
        if "Unknown" in out or "Error" in out:
            adb.shell(f"settings put global low_power {1 if activar else 0}")
        return f"Ahorro de batería {'activado' if activar else 'desactivado'}."

    @reg.add("tel_pantalla", "Apaga o enciende la pantalla del teléfono.",
             {"properties": {"accion": {"type": "string", "enum": ["apagar", "encender"]}}, "required": ["accion"]}, group=g)
    def tel_pantalla(ctx: Ctx, accion: str):
        adb.shell(f"input keyevent {223 if accion == 'apagar' else 224}")
        return f"Pantalla del teléfono {'apagada' if accion == 'apagar' else 'encendida'}."

    @reg.add("tel_abrir_url", "Abre una web o enlace en el teléfono.",
             {"properties": {"url": {"type": "string"}}, "required": ["url"]}, group=g)
    def tel_abrir_url(ctx: Ctx, url: str):
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        adb.shell(f"am start -a android.intent.action.VIEW -d {shlex.quote(url)}")
        return f"Abrí {url} en el teléfono."

    @reg.add("tel_captura", "Toma una captura de la pantalla del teléfono.", group=g)
    def tel_captura(ctx: Ctx):
        data = adb.exec_out("screencap -p")
        if not data.startswith(b"\x89PNG"):
            raise ToolError("No pude capturar la pantalla del teléfono.")
        path = DATA / "capturas" / f"tel_{dt.datetime.now():%Y%m%d_%H%M%S}.png"
        path.write_bytes(data)
        ctx.attachments.append(str(path))
        return f"Captura del teléfono guardada en {path}"
