"""Безопасные помощники для ответов на колбэки и редактирования сообщений.

Цель — устойчивость к сетевым задержкам/«протухшим» колбэкам, чтобы кнопки
всегда ощущались отзывчивыми и ничего не «висело».
"""
import logging

from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

log = logging.getLogger("ui")


async def ack(cq: CallbackQuery):
    """Мгновенно подтвердить колбэк (убрать «часики»). Ошибки игнорируем."""
    try:
        await cq.answer()
    except Exception:
        pass


async def edit(cq: CallbackQuery, text: str, markup=None):
    """Отредактировать сообщение; при невозможности — прислать новое."""
    try:
        await cq.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message is not modified" in msg:
            return
        try:
            await cq.message.answer(text, reply_markup=markup)
        except Exception as e2:
            log.warning("edit fallback failed: %s", e2)
    except Exception as e:
        log.warning("edit failed: %s", e)
        try:
            await cq.message.answer(text, reply_markup=markup)
        except Exception:
            pass


async def toast(cq: CallbackQuery, text: str):
    """Короткое уведомление пользователю отдельным сообщением.

    Используется вместо show_alert, т.к. колбэк уже подтверждён middleware.
    """
    try:
        await cq.message.answer(text)
    except Exception as e:
        log.warning("toast failed: %s", e)
