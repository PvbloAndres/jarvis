"""Carga de config.yaml y rutinas.yaml con valores por defecto."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"                      # memoria y recordatorios (se respaldan con OneDrive)
# Lo pesado o que cambia a cada rato vive fuera de OneDrive para no saturar la sincronización.
LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".jarvis") / "Jarvis"
LOGS = LOCAL / "logs"

DEFAULTS: dict = {
    "usuario": {"nombre": "", "tratamiento": "señor", "ciudad": "Santiago, Chile"},
    "cerebro": {
        "proveedor": "claude",
        "claude_api_key": "",
        "claude_modelo": "claude-haiku-4-5-20251001",
        "gemini_api_key": "",
        "gemini_modelo": "gemini-flash-latest",
        "minutos_para_olvidar_conversacion": 20,
        "max_tokens_respuesta": 800,
    },
    "voz": {
        "activada": True,
        "palabra_clave_umbral": 0.5,
        "voz_tts": "es-CL-LorenzoNeural",
        "velocidad_tts": "+8%",
        "modelo_whisper": "auto",
        "dispositivo_whisper": "auto",
        "microfono": None,
        "pitido_al_escuchar": True,
        "hablar_respuestas_del_panel": True,
    },
    "telegram": {"activado": False, "token": "", "usuarios_permitidos": []},
    "telefono": {"activado": False, "adb_ruta": "adb", "serie": "", "ip": ""},
    "alexa": {
        "activado": False,
        "voicemonkey_token": "",
        "parlantes": {},
        "parlante_principal": "",
        "voz_polly": "",
        "idioma": "es-US",
        "responder_por_alexa": True,
        "rutinas": {},
    },
    "panel": {"activado": True, "puerto": 8765, "abrir_al_iniciar": True, "token_api": ""},
    "pc": {"apps": {}, "comandos": {}},
    "general": {"recordatorios_en": ["pc", "telegram"]},
}


class ConfigError(Exception):
    pass


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path | None = None) -> dict:
    path = path or ROOT / "config.yaml"
    if not path.exists():
        raise ConfigError(
            f"No encuentro {path.name}. Copia config.example.yaml como config.yaml y rellénalo "
            "(instalar.bat lo hace por ti).")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"config.yaml tiene un error de formato: {e}") from e
    cfg = _merge(DEFAULTS, raw)

    # Las variables de entorno tienen prioridad (útil para no dejar claves en el archivo).
    env_map = {
        ("cerebro", "claude_api_key"): "ANTHROPIC_API_KEY",
        ("cerebro", "gemini_api_key"): "GEMINI_API_KEY",
        ("telegram", "token"): "JARVIS_TELEGRAM_TOKEN",
        ("alexa", "voicemonkey_token"): "VOICEMONKEY_TOKEN",
    }
    for (sec, key), env in env_map.items():
        if os.environ.get(env):
            cfg[sec][key] = os.environ[env]

    # Normalizaciones
    for sec in ("parlantes", "rutinas"):
        cfg["alexa"][sec] = cfg["alexa"].get(sec) or {}
    cfg["pc"]["apps"] = cfg["pc"].get("apps") or {}
    cfg["pc"]["comandos"] = cfg["pc"].get("comandos") or {}
    cfg["telegram"]["usuarios_permitidos"] = [
        int(x) for x in (cfg["telegram"].get("usuarios_permitidos") or []) if str(x).strip().lstrip("-").isdigit()
    ]
    DATA.mkdir(exist_ok=True)
    (DATA / "capturas").mkdir(exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    return cfg


def load_routines(path: Path | None = None) -> dict:
    path = path or ROOT / "rutinas.yaml"
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"rutinas.yaml tiene un error de formato: {e}") from e
    return raw.get("rutinas") or {}
