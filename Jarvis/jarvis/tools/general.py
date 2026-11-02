"""Herramientas generales: hora, clima, web, memoria, recordatorios, rutinas, Telegram."""
from __future__ import annotations

import datetime as dt
import re

import requests

from ..persona import fecha_larga
from . import Ctx, Registry, ToolError

WMO = {
    0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "niebla", 48: "niebla con escarcha", 51: "llovizna débil", 53: "llovizna", 55: "llovizna intensa",
    61: "lluvia débil", 63: "lluvia", 65: "lluvia intensa", 66: "lluvia helada", 67: "lluvia helada intensa",
    71: "nieve débil", 73: "nieve", 75: "nieve intensa", 77: "granizo fino", 80: "chubascos débiles",
    81: "chubascos", 82: "chubascos fuertes", 85: "chubascos de nieve", 86: "chubascos de nieve fuertes",
    95: "tormenta", 96: "tormenta con granizo", 99: "tormenta fuerte con granizo",
}


def register(reg: Registry, app) -> None:
    cfg = app.cfg

    @reg.add("hora_y_fecha", "Devuelve la fecha y hora actuales.")
    def hora_y_fecha(ctx: Ctx):
        return fecha_larga()

    @reg.add("clima", "Clima actual y pronóstico de hoy y mañana para una ciudad (por defecto, la del usuario).",
             {"properties": {"ciudad": {"type": "string", "description": "Ciudad, ej: 'Valparaíso, Chile'"}}})
    def clima(ctx: Ctx, ciudad: str = ""):
        ciudad = (ciudad or cfg["usuario"].get("ciudad") or "Santiago, Chile").strip()
        nombre = ciudad.split(",")[0].strip()
        g = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": nombre, "count": 5, "language": "es"}, timeout=10).json()
        res = g.get("results") or []
        if not res:
            raise ToolError(f"No encontré la ciudad '{ciudad}'.")
        pais = ciudad.split(",")[1].strip().lower() if "," in ciudad else ""
        lugar = next((r for r in res if pais and pais in (r.get("country") or "").lower()), res[0])
        w = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lugar["latitude"], "longitude": lugar["longitude"], "timezone": "auto", "forecast_days": 2,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        }, timeout=10).json()
        c, d = w["current"], w["daily"]
        return (f"{lugar['name']}, {lugar.get('country', '')}: ahora {round(c['temperature_2m'])}°C "
                f"(sensación {round(c['apparent_temperature'])}°C), {WMO.get(c['weather_code'], 'sin dato')}, "
                f"humedad {c['relative_humidity_2m']}%, viento {round(c['wind_speed_10m'])} km/h. "
                f"Hoy: mín {round(d['temperature_2m_min'][0])}°C, máx {round(d['temperature_2m_max'][0])}°C, "
                f"lluvia {d['precipitation_probability_max'][0]}%. "
                f"Mañana: {WMO.get(d['weather_code'][1], '')}, mín {round(d['temperature_2m_min'][1])}°C, "
                f"máx {round(d['temperature_2m_max'][1])}°C, lluvia {d['precipitation_probability_max'][1]}%.")

    @reg.add("buscar_web", "Busca información actual en internet (noticias, datos, precios). Devuelve resultados breves.",
             {"properties": {"consulta": {"type": "string"}}, "required": ["consulta"]})
    def buscar_web(ctx: Ctx, consulta: str):
        try:
            from ddgs import DDGS
        except ImportError as e:
            raise ToolError("Falta el paquete 'ddgs' para buscar en la web.") from e
        results = DDGS().text(consulta, region="cl-es", max_results=5) or []
        if not results:
            return "Sin resultados."
        return "\n".join(f"- {r.get('title')}: {r.get('body')} ({r.get('href')})" for r in results)

    # ------------------------------------------------------------------ memoria
    @reg.add("recordar", "Guarda un dato permanente sobre el usuario (gustos, datos, preferencias).",
             {"properties": {"dato": {"type": "string", "description": "Frase completa, ej: 'Su equipo es Colo-Colo'"}},
              "required": ["dato"]})
    def recordar(ctx: Ctx, dato: str):
        return app.memory.add(dato)

    @reg.add("olvidar", "Borra de la memoria los datos que contengan el texto indicado.",
             {"properties": {"texto": {"type": "string"}}, "required": ["texto"]})
    def olvidar(ctx: Ctx, texto: str):
        return app.memory.forget(texto)

    # ------------------------------------------------------------ recordatorios
    @reg.add("programar_recordatorio",
             "Programa un aviso. Usa 'minutos' para 'en X minutos' o 'hora' (HH:MM, 24 h) para una hora concreta.",
             {"properties": {
                 "mensaje": {"type": "string", "description": "Qué hay que recordar"},
                 "minutos": {"type": "number", "description": "Dentro de cuántos minutos"},
                 "hora": {"type": "string", "description": "Hora exacta HH:MM (hoy o mañana si ya pasó)"},
             }, "required": ["mensaje"]})
    def programar_recordatorio(ctx: Ctx, mensaje: str, minutos: float | None = None, hora: str | None = None):
        now = dt.datetime.now()
        if minutos:
            when = now + dt.timedelta(minutes=float(minutos))
        elif hora:
            m = re.match(r"^\s*(\d{1,2})[:.h](\d{2})", hora)
            if not m:
                raise ToolError("La hora debe tener formato HH:MM.")
            when = now.replace(hour=int(m[1]), minute=int(m[2]), second=0, microsecond=0)
            if when <= now:
                when += dt.timedelta(days=1)
        else:
            raise ToolError("Indica 'minutos' u 'hora'.")
        app.reminders.add(when.timestamp(), mensaje)
        return f"Recordatorio programado para las {when:%H:%M} del {when:%d/%m}: {mensaje}"

    @reg.add("ver_recordatorios", "Lista los recordatorios pendientes.")
    def ver_recordatorios(ctx: Ctx):
        items = app.reminders.pending()
        if not items:
            return "No hay recordatorios pendientes."
        return "\n".join(f"- {dt.datetime.fromtimestamp(i['cuando']):%d/%m %H:%M}: {i['mensaje']}" for i in items)

    @reg.add("cancelar_recordatorio", "Cancela los recordatorios cuyo mensaje contenga el texto indicado.",
             {"properties": {"texto": {"type": "string"}}, "required": ["texto"]})
    def cancelar_recordatorio(ctx: Ctx, texto: str):
        n = app.reminders.cancel(texto)
        return f"Cancelé {n} recordatorio(s)." if n else "No encontré recordatorios con ese texto."

    # ------------------------------------------------------------------ rutinas
    def _desc_rutinas() -> str:
        if not app.routines:
            return "No hay rutinas definidas en rutinas.yaml."
        return "; ".join(f"{k}: {v.get('descripcion', '')}" for k, v in app.routines.items())

    @reg.add("listar_rutinas", "Lista las rutinas personalizadas disponibles (definidas en rutinas.yaml).")
    def listar_rutinas(ctx: Ctx):
        return _desc_rutinas()

    @reg.add("ejecutar_rutina",
             "Ejecuta una rutina personalizada por su nombre (varias acciones en PC, teléfono y Alexa). "
             "Rutinas disponibles: " + _desc_rutinas(),
             {"properties": {"nombre": {"type": "string"}}, "required": ["nombre"]})
    def ejecutar_rutina(ctx: Ctx, nombre: str):
        return app.run_routine(nombre, ctx)

    # ----------------------------------------------------------------- Telegram
    @reg.add("enviar_al_telefono", "Envía un mensaje de texto al teléfono del usuario por Telegram.",
             {"properties": {"mensaje": {"type": "string"}}, "required": ["mensaje"]})
    def enviar_al_telefono(ctx: Ctx, mensaje: str):
        if not app.notifier.enabled:
            raise ToolError("Telegram no está configurado.")
        app.notifier.send(mensaje)
        return "Mensaje enviado al teléfono."

    @reg.add("olvidar_conversacion", "Borra el historial de la conversación actual (no la memoria permanente).")
    def olvidar_conversacion(ctx: Ctx):
        app.brain.request_reset()
        return "Conversación reiniciada."
