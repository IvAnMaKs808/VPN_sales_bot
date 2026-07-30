"""Фоновые задачи: авто-подтверждение оплат и напоминания об окончании подписки."""
import asyncio
import logging

from aiogram import Bot

import database as db
import payments
import subscription
import keyboards as kb
from handlers_user import _finalize_payment

log = logging.getLogger("scheduler")

POLL_INTERVAL = 30           # сек — как часто проверяем неоплаченные счета
NOTIFY_INTERVAL = 3600       # сек — как часто проверяем истекающие подписки
NOTIFY_WINDOW = 24 * 3600    # за сколько до конца предупреждаем
PAYMENT_TTL = 3 * 3600       # сколько держим счёт «живым» для автопроверки


async def payment_poller(bot: Bot):
    while True:
        try:
            since = db.now() - PAYMENT_TTL
            for p in await db.pending_payments(since):
                if await payments.check_payment(p["provider"], p["external_id"]):
                    await _finalize_payment(bot, p["id"])
        except Exception as e:
            log.warning("payment_poller error: %s", e)
        await asyncio.sleep(POLL_INTERVAL)


async def expiry_notifier(bot: Bot):
    while True:
        try:
            window_end = db.now() + NOTIFY_WINDOW
            for s in await db.subs_needing_expiry_notice(window_end):
                try:
                    await bot.send_message(
                        s["user_id"],
                        "⏳ <b>Твоя подписка скоро закончится</b>\n"
                        f"Действует до: <b>{subscription.fmt_date(s['expires_at'])}</b>\n\n"
                        "Продли, чтобы не потерять доступ 👇",
                        reply_markup=kb.mysubs_kb(True),
                    )
                    await db.mark_expiry_notified(s["user_id"])
                except Exception:
                    # напр. пользователь заблокировал бота — считаем уведомление отправленным
                    await db.mark_expiry_notified(s["user_id"])
        except Exception as e:
            log.warning("expiry_notifier error: %s", e)
        await asyncio.sleep(NOTIFY_INTERVAL)


def start(bot: Bot):
    asyncio.create_task(payment_poller(bot))
    asyncio.create_task(expiry_notifier(bot))
