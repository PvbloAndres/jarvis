"""Envía una orden de texto a Jarvis (que debe estar en marcha).

Uso:  orden.bat activa la rutina modo trabajo
Lo usa TRIGGERcmd para que Alexa pueda darle órdenes a Jarvis.
"""
import json
import sys
import urllib.request
from pathlib import Path

import yaml

root = Path(__file__).resolve().parent
cfg = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")) or {}
panel = cfg.get("panel") or {}
port = int(panel.get("puerto") or 8765)
token = (panel.get("token_api") or "").strip()

# TRIGGERcmd agrega "on"/"off" al final cuando la orden viene de "Alexa, enciende/apaga ...".
words = [w for w in sys.argv[1:] if w.lower() not in ("on", "off")]
text = " ".join(words).strip()
if not text:
    sys.exit("Uso: orden.bat <texto de la orden>")

headers = {"Content-Type": "application/json", "X-Jarvis": "1"}
if token:
    headers["Authorization"] = f"Bearer {token}"
req = urllib.request.Request(f"http://127.0.0.1:{port}/api/comando", method="POST", headers=headers,
                             data=json.dumps({"texto": text}).encode("utf-8"))
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print("Orden enviada:", text, r.status)
except Exception as e:  # noqa: BLE001
    sys.exit(f"No pude contactar a Jarvis (¿está encendido?): {e}")
