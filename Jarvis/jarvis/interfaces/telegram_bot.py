"""Telegram: habla con Jarvis desde el OnePlus 15, estés donde estés (texto o notas de voz)."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import requests

from ..config import DATA

log = logging.getLogger("jarvis.telegram")


class Notifier:
    """Envía mensajes al teléfono desde cualquier hilo (API HTTP directa de Telegram)."""

    def __init__(self, cfg: dict):
        t = cfg["telegram"]
        self.token = (t.get("token") or "").strip()
        self.chat_ids = list(t.get("usuarios_permitidos") or [])
        self.enabled = bool(t.get("activado") and self.token and self.chat_ids)

    def send(self, text: str, photo: str | None = None) -> None:
        if not self.enabled:
            return
        base = f"https://api.telegram.org/bot{self.token}"
        for chat in self.chat_ids[:1]:     # el primero de la lista es el dueño
            try:
                if photo:
                    with open(photo, "rb") as f:
                        requests.post(f"{base}/sendPhoto", data={"chat_id": chat, "caption": text[:1000]},
                                      files={"photo": f}, timeout=30)
                else:
                    for part in _split(text):
                        requests.post(f"{base}/sendMessage", data={"chat_id": chat, "text": part}, timeout=15)
            except requests.RequestException as e:
                log.warning("No pude enviar a Telegram: %s", e)


def _split(text: str, n: int = 4000) -> list[str]:
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]


class TelegramBot:
    def __init__(self, app):
        self.app = app
        t = app.cfg["telegram"]
        self.token = t["token"]
        self.allowed = set(t.get("usuarios_permitidos") or [])

    async def _authorized(self, update) -> bool:
        uid = update.effective_user.id if update.effective_user else None
        if uid in self.allowed:
            return True
        self.app.events.emit("sistema", f"Telegram: acceso rechazado al usuario {uid}", canal="telegram")
        if update.message:
            await update.message.reply_text(
                f"Acceso denegado. Tu ID de Telegram es {uid}. Si eres el dueño, agrégalo en config.yaml "
                "(telegram > usuarios_permitidos) y reinicia Jarvis.")
        return False

    async def _answer(self, update, context, text: str) -> None:
        from telegram.constants import ChatAction
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        reply = await asyncio.to_thread(self.app.handle, text, "telegram")
        for part in _split(reply.text):
            await update.message.reply_text(part)
        for path in reply.attachments:
            with open(path, "rb") as f:
                await update.message.reply_photo(photo=f)

    async def on_start(self, update, context) -> None:
        if not await self._authorized(update):
            return
        await update.message.reply_text("A su servicio. Escríbame o envíeme una nota de voz.")

    async def on_text(self, update, context) -> None:
        if not await self._authorized(update):
            return
        await self._answer(update, context, update.message.text)

    async def on_voice(self, update, context) -> None:
        if not await self._authorized(update):
            return
        media = update.message.voice or update.message.audio
        tg_file = await media.get_file()
        path = DATA / f"nota_{int(time.time())}.ogg"
        await tg_file.download_to_drive(custom_path=str(path))
        try:
            text = await asyncio.to_thread(self.app.stt.transcribe, str(path))
        finally:
            Path(path).unlink(missing_ok=True)
        if not text:
            await update.message.reply_text("No logré entender la nota de voz.")
            return
        await update.message.reply_text(f"Escuché: «{text}»")
        await self._answer(update, context, text)

    def run(self) -> None:
        """Bloqueante: se ejecuta en el hilo principal."""
        from telegram import Update
        from telegram.ext import Application, CommandHandler, MessageHandler, filters

        application = Application.builder().token(self.token).build()
        application.add_handler(CommandHandler("start", self.on_start))
        application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self.on_voice))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        self.app.events.emit("sistema", "Telegram conectado.")
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
