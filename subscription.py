"""Оркестрация подписок: выдача/продление в 3x-ui + запись в БД.

Одна подписка на пользователя. Email клиента в панели — tg{user_id} (стабильный).
При продлении время добавляется к текущему сроку (если подписка ещё активна),
иначе отсчёт идёт от «сейчас». Ссылка-подписка (subId) сохраняется навсегда.
"""
from datetime import datetime, timezone, timedelta

import database as db
from xui import xui, new_uuid, new_sub_id, sub_link

DAY = 86400
MSK = timezone(timedelta(hours=3))


def fmt_date(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, MSK).strftime("%d.%m.%Y %H:%M")


def sub_link_for(sub) -> str:
    """Ссылка-подписка для строки БД subscriptions."""
    return sub_link(sub["sub_id"])


async def grant(user_id: int, days: int) -> tuple[str, int]:
    """Создаёт или продлевает подписку. Возвращает (ссылка, новый срок в epoch)."""
    sub = await db.get_subscription(user_id)
    base = max(sub["expires_at"], db.now()) if sub else db.now()
    new_expiry = base + days * DAY
    expiry_ms = new_expiry * 1000
    email = f"tg{user_id}"

    if sub and sub["xui_uuid"]:
        # продлеваем существующего клиента
        await xui.update_client(sub["xui_uuid"], email, sub["sub_id"], expiry_ms)
        await db.set_expiry(user_id, new_expiry)
        return sub_link(sub["sub_id"]), new_expiry

    # новый клиент
    client_uuid = new_uuid()
    sub_id = new_sub_id()
    await xui.add_client(email, client_uuid, sub_id, expiry_ms)
    await db.save_subscription(user_id, client_uuid, email, sub_id, new_expiry)
    return sub_link(sub_id), new_expiry
