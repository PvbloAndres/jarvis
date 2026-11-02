"""El cerebro: un modelo de lenguaje que conversa y llama herramientas.

Dos proveedores intercambiables:
- ClaudeBrain  (Anthropic, recomendado: muy fiable usando herramientas; de pago, barato)
- GeminiBrain  (Google, tiene nivel gratuito con límites)
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from .tools import Ctx, Registry

log = logging.getLogger("jarvis.brain")

MAX_STEPS = 8          # rondas de herramientas por petición
MAX_TURNS = 12         # turnos del usuario que se conservan en la conversación


class BrainError(Exception):
    pass


class BaseBrain:
    def __init__(self, cfg: dict, registry: Registry, prompt_fn: Callable[[Ctx], tuple[str, str]]):
        self.cfg = cfg
        self.registry = registry
        self.prompt_fn = prompt_fn   # devuelve (parte_fija, parte_dinámica)
        self.last_use = 0.0
        self.forget_after = float(cfg["cerebro"].get("minutos_para_olvidar_conversacion") or 20) * 60
        self.max_tokens = int(cfg["cerebro"].get("max_tokens_respuesta") or 800)
        self._reset_pending = False

    def _maybe_reset(self) -> None:
        if self.last_use and time.time() - self.last_use > self.forget_after:
            self.reset()
        self.last_use = time.time()

    def reset(self) -> None:
        raise NotImplementedError

    def request_reset(self) -> None:
        """Reinicia la conversación al terminar la petición en curso."""
        self._reset_pending = True

    def ask(self, text: str, ctx: Ctx) -> str:
        self._reset_pending = False
        try:
            return self._ask(text, ctx)
        finally:
            if self._reset_pending:
                self.reset()
                self._reset_pending = False

    def _ask(self, text: str, ctx: Ctx) -> str:
        raise NotImplementedError

    def ping(self) -> str:
        raise NotImplementedError


# =========================================================================== Claude
class ClaudeBrain(BaseBrain):
    def __init__(self, cfg, registry, prompt_fn):
        super().__init__(cfg, registry, prompt_fn)
        try:
            import anthropic
        except ImportError as e:
            raise BrainError("Falta el paquete 'anthropic'. Ejecuta instalar.bat.") from e
        key = cfg["cerebro"].get("claude_api_key")
        if not key:
            raise BrainError("Falta claude_api_key en config.yaml (sección cerebro).")
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=key, max_retries=2, timeout=60)
        self.model = cfg["cerebro"].get("claude_modelo") or "claude-haiku-4-5-20251001"
        self.history: list[dict] = []

    def reset(self) -> None:
        self.history = []

    def _tools(self) -> list[dict]:
        tools = self.registry.schemas_claude()
        if tools:
            tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
        return tools

    def _trim(self) -> None:
        # Conserva los últimos MAX_TURNS mensajes de usuario "de texto" (no resultados de herramientas).
        starts = [i for i, m in enumerate(self.history)
                  if m["role"] == "user" and any(b.get("type") == "text" for b in m["content"])]
        if len(starts) > MAX_TURNS:
            self.history = self.history[starts[-MAX_TURNS]:]

    def _ask(self, text: str, ctx: Ctx) -> str:
        self._maybe_reset()
        fixed, dynamic = self.prompt_fn(ctx)
        system = [
            {"type": "text", "text": fixed, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dynamic},
        ]
        start_len = len(self.history)
        self.history.append({"role": "user", "content": [{"type": "text", "text": text}]})
        try:
            for _ in range(MAX_STEPS):
                resp = self.client.messages.create(
                    model=self.model, max_tokens=self.max_tokens, system=system,
                    tools=self._tools(), messages=self.history)
                blocks, texts, calls = [], [], []
                for b in resp.content:
                    if b.type == "text":
                        blocks.append({"type": "text", "text": b.text})
                        texts.append(b.text)
                    elif b.type == "tool_use":
                        blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                        calls.append(b)
                if not blocks:
                    blocks = [{"type": "text", "text": "(sin respuesta)"}]
                self.history.append({"role": "assistant", "content": blocks})
                if resp.stop_reason != "tool_use" or not calls:
                    self._trim()
                    return "\n".join(t for t in texts if t.strip()).strip() or "Hecho."
                results = []
                for c in calls:
                    out, is_err = self.registry.call(c.name, c.input or {}, ctx)
                    results.append({"type": "tool_result", "tool_use_id": c.id,
                                    "content": out[:8000], "is_error": is_err})
                self.history.append({"role": "user", "content": results})
            self._trim()
            return "He encadenado demasiadas acciones seguidas; me detengo aquí por seguridad."
        except self._anthropic.AuthenticationError as e:
            self.history = self.history[:start_len]
            raise BrainError("La clave de Claude no es válida (revisa claude_api_key).") from e
        except self._anthropic.APIError as e:
            self.history = self.history[:start_len]
            raise BrainError(f"Error de la API de Claude: {getattr(e, 'message', e)}") from e

    def ping(self) -> str:
        r = self.client.messages.create(model=self.model, max_tokens=20,
                                        messages=[{"role": "user", "content": "Responde solo: en línea"}])
        return "".join(b.text for b in r.content if b.type == "text")


# =========================================================================== Gemini
class GeminiBrain(BaseBrain):
    def __init__(self, cfg, registry, prompt_fn):
        super().__init__(cfg, registry, prompt_fn)
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise BrainError("Falta el paquete 'google-genai'. Ejecuta instalar.bat.") from e
        key = cfg["cerebro"].get("gemini_api_key")
        if not key:
            raise BrainError("Falta gemini_api_key en config.yaml (sección cerebro).")
        self.types = types
        self.client = genai.Client(api_key=key)
        self.model = cfg["cerebro"].get("gemini_modelo") or "gemini-flash-latest"
        self.history: list = []   # objetos types.Content (conservan las 'thought signatures')

    def reset(self) -> None:
        self.history = []

    def _trim(self) -> None:
        def is_user_text(c):
            return c.role == "user" and any(getattr(p, "text", None) for p in (c.parts or []))
        starts = [i for i, c in enumerate(self.history) if is_user_text(c)]
        if len(starts) > MAX_TURNS:
            self.history = self.history[starts[-MAX_TURNS]:]

    def _ask(self, text: str, ctx: Ctx) -> str:
        t = self.types
        self._maybe_reset()
        fixed, dynamic = self.prompt_fn(ctx)
        config = t.GenerateContentConfig(
            system_instruction=fixed + "\n\n" + dynamic,
            tools=[t.Tool(function_declarations=self.registry.schemas_gemini())],
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
            max_output_tokens=self.max_tokens * 4,   # margen para el 'pensamiento' interno del modelo
        )
        start_len = len(self.history)
        self.history.append(t.Content(role="user", parts=[t.Part(text=text)]))
        try:
            for _ in range(MAX_STEPS):
                resp = self.client.models.generate_content(model=self.model, contents=self.history, config=config)
                cand = (resp.candidates or [None])[0]
                content = getattr(cand, "content", None)
                if content is None or not content.parts:
                    self.history = self.history[:start_len]
                    return "No obtuve respuesta del modelo; inténtelo de nuevo, por favor."
                self.history.append(content)
                calls = [p.function_call for p in content.parts if getattr(p, "function_call", None)]
                if not calls:
                    self._trim()
                    txt = "".join(p.text for p in content.parts
                                  if getattr(p, "text", None) and not getattr(p, "thought", False))
                    return txt.strip() or "Hecho."
                parts = []
                for fc in calls:
                    out, is_err = self.registry.call(fc.name, dict(fc.args or {}), ctx)
                    key = "error" if is_err else "resultado"
                    parts.append(t.Part(function_response=t.FunctionResponse(
                        id=getattr(fc, "id", None), name=fc.name, response={key: out[:8000]})))
                self.history.append(t.Content(role="user", parts=parts))
            self._trim()
            return "He encadenado demasiadas acciones seguidas; me detengo aquí por seguridad."
        except Exception as e:  # noqa: BLE001 - el SDK de Google lanza varias clases
            self.history = self.history[:start_len]
            msg = str(e)
            if "API key" in msg or "API_KEY" in msg or "PERMISSION_DENIED" in msg:
                raise BrainError("La clave de Gemini no es válida (revisa gemini_api_key).") from e
            if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
                raise BrainError("Se acabó la cuota gratuita de Gemini por ahora; espera un rato o usa Claude.") from e
            raise BrainError(f"Error de la API de Gemini: {msg[:300]}") from e

    def ping(self) -> str:
        r = self.client.models.generate_content(model=self.model, contents="Responde solo: en línea")
        return (r.text or "").strip()


def make_brain(cfg: dict, registry: Registry, prompt_fn) -> BaseBrain:
    prov = (cfg["cerebro"].get("proveedor") or "claude").lower().strip()
    if prov == "gemini":
        return GeminiBrain(cfg, registry, prompt_fn)
    if prov in ("claude", "anthropic"):
        return ClaudeBrain(cfg, registry, prompt_fn)
    raise BrainError(f"Proveedor desconocido '{prov}'. Usa 'claude' o 'gemini'.")
