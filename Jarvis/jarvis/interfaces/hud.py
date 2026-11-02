"""Panel HUD en http://127.0.0.1:8765 y API local (la usa también TRIGGERcmd para las órdenes de Alexa)."""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("jarvis.hud")
HTML = Path(__file__).with_name("hud.html")
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def make_handler(app):
    token = (app.cfg["panel"].get("token_api") or "").strip()
    port = int(app.cfg["panel"].get("puerto") or 8765)

    class Handler(BaseHTTPRequestHandler):
        server_version = "Jarvis"

        def log_message(self, fmt, *args):  # silencia el log por petición
            log.debug(fmt, *args)

        # ------------------------------------------------------------ seguridad
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0].lower()
            return host in ALLOWED_HOSTS   # bloquea ataques de 'DNS rebinding'

        def _post_ok(self) -> bool:
            # Un sitio web malicioso no puede enviar esta cabecera sin permiso CORS (que no damos).
            if self.headers.get("X-Jarvis") != "1":
                return False
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in ALLOWED_HOSTS:
                return False
            if token and self.headers.get("Authorization") != f"Bearer {token}":
                return False
            return True

        def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json_body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                return json.loads(raw.decode("utf-8") or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {"texto": raw.decode("utf-8", "replace")}

        # ----------------------------------------------------------------- GET
        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "host no permitido"})
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                html = HTML.read_text(encoding="utf-8").replace("__PORT__", str(port))
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if url.path == "/api/estado":
                return self._send(200, app.status())
            if url.path == "/api/eventos":
                since = int((parse_qs(url.query).get("desde") or ["0"])[0] or 0)
                return self._send(200, {"estado": app.events.state, "eventos": app.events.since(since)})
            return self._send(404, {"error": "no encontrado"})

        # ---------------------------------------------------------------- POST
        def do_POST(self):
            if not self._host_ok() or not self._post_ok():
                return self._send(403, {"error": "petición no autorizada"})
            url = urlparse(self.path)
            if url.path in ("/api/apagar", "/api/reiniciar"):     # los usa detener.bat
                app.shutdown(restart=url.path.endswith("reiniciar"))
                return self._send(200, {"ok": True})
            if url.path == "/api/microfono":
                app.mic_paused = not app.mic_paused
                return self._send(200, {"pausado": app.mic_paused})
            body = self._json_body()
            texto = str(body.get("texto") or "").strip()
            if not texto:
                return self._send(400, {"error": "falta 'texto'"})
            if url.path == "/api/chat":
                speak = bool(body.get("hablar", app.cfg["voz"].get("hablar_respuestas_del_panel", True)))
                reply = app.handle(texto, channel="panel", speak=speak)
                return self._send(200, {"respuesta": reply.text, "adjuntos": reply.attachments})
            if url.path == "/api/comando":        # órdenes que llegan desde Alexa vía TRIGGERcmd
                threading.Thread(target=app.handle_from_alexa, args=(texto,), daemon=True).start()
                return self._send(202, {"ok": True})
            return self._send(404, {"error": "no encontrado"})

    return Handler


class HudServer(threading.Thread):
    def __init__(self, app):
        super().__init__(name="panel", daemon=True)
        self.port = int(app.cfg["panel"].get("puerto") or 8765)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(app))
        self.httpd.daemon_threads = True

    def run(self) -> None:
        self.httpd.serve_forever()
