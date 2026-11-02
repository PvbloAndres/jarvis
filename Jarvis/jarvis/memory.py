"""Memoria de largo plazo (datos que pides recordar) y recordatorios, en JSON."""
from __future__ import annotations

import json
import threading
import time
import unicodedata
from pathlib import Path

from .config import DATA


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


class JsonStore:
    def __init__(self, path: Path, default):
        self.path = path
        self._lock = threading.Lock()
        self._default = default

    def load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return json.loads(json.dumps(self._default))

    def save(self, data) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


class Memory:
    """Datos permanentes sobre el usuario: 'mi color favorito es el rojo', etc."""

    def __init__(self, path: Path | None = None) -> None:
        self.store = JsonStore(path or DATA / "memoria.json", [])

    def all(self) -> list[dict]:
        return self.store.load()

    def add(self, dato: str) -> str:
        with self.store._lock:
            items = self.store.load()
            if any(_norm(i["dato"]) == _norm(dato) for i in items):
                return "Ya lo tenía anotado."
            items.append({"dato": dato.strip(), "fecha": time.strftime("%Y-%m-%d")})
            self.store.save(items)
        return f"Anotado: {dato.strip()}"

    def forget(self, texto: str) -> str:
        with self.store._lock:
            items = self.store.load()
            keep = [i for i in items if _norm(texto) not in _norm(i["dato"])]
            removed = len(items) - len(keep)
            self.store.save(keep)
        return f"Olvidé {removed} dato(s)." if removed else "No encontré nada parecido en mi memoria."

    def as_prompt(self) -> str:
        items = self.all()
        if not items:
            return "(vacía)"
        return "\n".join(f"- {i['dato']}" for i in items[-60:])


class Reminders:
    def __init__(self, path: Path | None = None) -> None:
        self.store = JsonStore(path or DATA / "recordatorios.json", [])

    def add(self, when_ts: float, mensaje: str) -> dict:
        with self.store._lock:
            items = self.store.load()
            item = {"id": int(time.time() * 1000), "cuando": when_ts, "mensaje": mensaje}
            items.append(item)
            self.store.save(items)
        return item

    def pending(self) -> list[dict]:
        return sorted(self.store.load(), key=lambda i: i["cuando"])

    def pop_due(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        with self.store._lock:
            items = self.store.load()
            due = [i for i in items if i["cuando"] <= now]
            if due:
                self.store.save([i for i in items if i["cuando"] > now])
        return due

    def cancel(self, texto: str) -> int:
        with self.store._lock:
            items = self.store.load()
            keep = [i for i in items if _norm(texto) not in _norm(i["mensaje"])]
            self.store.save(keep)
        return len(items) - len(keep)
