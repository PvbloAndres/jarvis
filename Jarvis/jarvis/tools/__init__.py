"""Registro de herramientas: funciones que el cerebro de Jarvis puede llamar."""
from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("jarvis.tools")

CONFIRM_PARAM = {
    "type": "boolean",
    "description": (
        "Pon true SOLO si el usuario ya confirmó explícitamente esta acción en la conversación. "
        "Si no lo ha hecho, llama sin este campo o con false y pregúntale primero."
    ),
}


@dataclass
class Ctx:
    """Contexto de una petición: por dónde llegó y qué archivos hay que devolver."""
    channel: str = "consola"          # voz | telegram | panel | alexa | rutina | consola
    attachments: list[str] = field(default_factory=list)  # rutas de imágenes a enviar
    app: Any = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., Any]
    dangerous: bool = False
    group: str = "general"


class Registry:
    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    # ------------------------------------------------------------------ alta
    def add(self, name: str, description: str, parameters: dict | None = None,
            dangerous: bool = False, group: str = "general"):
        """Decorador para registrar una función como herramienta.

        La función recibe (ctx, **args) y devuelve un texto (o algo convertible a texto).
        """
        params = json.loads(json.dumps(parameters or {"type": "object", "properties": {}}))
        params.setdefault("type", "object")
        params.setdefault("properties", {})
        if dangerous:
            params["properties"]["confirmado"] = CONFIRM_PARAM

        def deco(func):
            self.tools[name] = Tool(name, description, params, func, dangerous, group)
            return func
        return deco

    def remove_group(self, group: str) -> None:
        for n in [n for n, t in self.tools.items() if t.group == group]:
            del self.tools[n]

    # --------------------------------------------------------------- esquemas
    def schemas_claude(self) -> list[dict]:
        out = []
        for t in self.tools.values():
            out.append({"name": t.name, "description": t.description, "input_schema": t.parameters})
        return out

    def schemas_gemini(self):
        from google.genai import types  # import tardío: solo si se usa Gemini
        decls = []
        for t in self.tools.values():
            has_params = bool(t.parameters.get("properties"))
            if not has_params:
                decls.append(types.FunctionDeclaration(name=t.name, description=t.description))
                continue
            try:
                decls.append(types.FunctionDeclaration(
                    name=t.name, description=t.description, parameters_json_schema=t.parameters))
            except Exception:  # SDK antiguo sin parameters_json_schema
                decls.append(types.FunctionDeclaration(
                    name=t.name, description=t.description, parameters=t.parameters))
        return decls

    # ------------------------------------------------------------- ejecución
    def call(self, name: str, args: dict | None, ctx: Ctx) -> tuple[str, bool]:
        """Ejecuta una herramienta. Devuelve (texto_resultado, es_error)."""
        args = dict(args or {})
        tool = self.tools.get(name)
        if tool is None:
            return f"No existe la herramienta '{name}'.", True
        if tool.dangerous and not bool(args.get("confirmado")):
            return ("ACCIÓN NO EJECUTADA: requiere confirmación. Pregunta al usuario si está seguro "
                    "y vuelve a llamar con confirmado=true solo si dice que sí."), False
        if not _accepts(tool.func, "confirmado"):
            args.pop("confirmado", None)
        events = getattr(ctx.app, "events", None)
        try:
            result = tool.func(ctx, **args)
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            if events:
                events.emit("herramienta", f"{name} ✓", canal=ctx.channel, detalle=_short(args))
            return text, False
        except ToolError as e:
            log.warning("%s: %s", name, e)
            if events:
                events.emit("herramienta", f"{name} ✗ {e}", canal=ctx.channel, detalle=_short(args))
            return str(e), True
        except TypeError as e:
            log.warning("Argumentos inválidos para %s: %s", name, e)
            return f"Argumentos inválidos para {name}: {e}", True
        except Exception as e:  # noqa: BLE001
            log.error("Error en herramienta %s: %s\n%s", name, e, traceback.format_exc())
            if events:
                events.emit("herramienta", f"{name} ✗ {e}", canal=ctx.channel, detalle=_short(args))
            return f"Error al ejecutar {name}: {e}", True


def _accepts(func, param: str) -> bool:
    import inspect
    try:
        return param in inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False


def _short(args: dict) -> str:
    s = json.dumps(args, ensure_ascii=False, default=str)
    return s if len(s) < 160 else s[:157] + "..."


class ToolError(Exception):
    """Error con un mensaje pensado para que Jarvis se lo explique al usuario."""
