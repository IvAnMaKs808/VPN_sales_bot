"""Админ-панель: статистика, выдача дней, бан, рассылка, промокоды, поиск юзера.

Колбэки подтверждаются middleware (bot.py) — cq.answer() здесь не вызываем.
"""
import asyncio
import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database as db
import keyboards as kb
import subscription
import ui
from config import ADMIN_IDS, CURRENCY_SYMBOL

log = logging.getLogger("admin")
router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


class Adm(StatesGroup):
    give_days = State()
    ban = State()
    broadcast = State()
    promo = State()
    find_user = State()


ADMIN_MENU = "🛠 <b>Админ-панель</b>\n\nВыбери раздел:"


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(ADMIN_MENU, reply_markup=kb.admin_menu_kb())


@router.callback_query(F.data == "adm:main")
async def adm_main(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    await ui.edit(cq, ADMIN_MENU, kb.admin_menu_kb())


@router.callback_query(F.data == "adm:stats")
async def adm_stats(cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        return
    users = await db.users_count()
    active = await db.active_subscriptions_count()
    revenue = await db.total_revenue()
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👤 Пользователей: <b>{users}</b>\n"
        f"🔑 Активных подписок: <b>{active}</b>\n"
        f"💵 Выручка (карта+крипта): <b>{revenue}{CURRENCY_SYMBOL}</b>"
    )
    await ui.edit(cq, text, kb.admin_back_kb())


# --------------------- выдать дни ---------------------
@router.callback_query(F.data == "adm:givedays")
async def adm_givedays(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.set_state(Adm.give_days)
    await ui.edit(
        cq,
        "Отправь: <code>user_id количество_дней</code>\nНапример: <code>123456789 30</code>",
        kb.admin_back_kb(),
    )


@router.message(Adm.give_days)
async def adm_givedays_input(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    try:
        uid_s, days_s = message.text.split()
        uid, days = int(uid_s), int(days_s)
    except ValueError:
        await message.answer("Формат: user_id дни. Попробуй снова.")
        return
    if not await db.get_user(uid):
        await message.answer("Пользователь не найден.")
        return
    try:
        link, expires = await subscription.grant(uid, days)
    except Exception as e:
        await message.answer(f"Ошибка 3x-ui: {e}")
        return
    await state.clear()
    await message.answer(
        f"✅ Выдано {days} дн. пользователю {uid}. Срок до: {subscription.fmt_date(expires)}",
        reply_markup=kb.admin_menu_kb(),
    )
    try:
        await bot.send_message(uid, f"🎁 Тебе начислено <b>{days} дней</b> подписки!")
    except Exception:
        pass


# --------------------- бан/разбан ---------------------
@router.callback_query(F.data == "adm:ban")
async def adm_ban(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.set_state(Adm.ban)
    await ui.edit(cq, "Отправь <code>user_id</code> для переключения бан/разбан.", kb.admin_back_kb())


@router.message(Adm.ban)
async def adm_ban_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text.strip().isdigit():
        await message.answer("Нужен числовой user_id.")
        return
    uid = int(message.text.strip())
    user = await db.get_user(uid)
    if not user:
        await message.answer("Пользователь не найден.")
        return
    new_state = not bool(user["banned"])
    await db.set_banned(uid, new_state)
    await state.clear()
    await message.answer(
        f"{'🚫 Забанен' if new_state else '✅ Разбанен'}: {uid}",
        reply_markup=kb.admin_menu_kb(),
    )


# --------------------- рассылка ---------------------
@router.callback_query(F.data == "adm:broadcast")
async def adm_broadcast(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.set_state(Adm.broadcast)
    await ui.edit(
        cq,
        "Отправь текст рассылки (поддерживается HTML). Будет отправлено всем.",
        kb.admin_back_kb(),
    )


@router.message(Adm.broadcast)
async def adm_broadcast_input(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    ids = await db.all_user_ids()
    await message.answer(f"Начинаю рассылку на {len(ids)} пользователей…")
    sent = failed = 0
    for uid in ids:
        try:
            await bot.send_message(uid, message.html_text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # ~20 msg/sec, чтобы не поймать flood limit
    await message.answer(
        f"📢 Готово. Доставлено: {sent}, ошибок: {failed}.",
        reply_markup=kb.admin_menu_kb(),
    )


# --------------------- промокод ---------------------
@router.callback_query(F.data == "adm:promo")
async def adm_promo(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.set_state(Adm.promo)
    await ui.edit(
        cq,
        "Создать промокод. Формат:\n"
        "<code>КОД процент фикс дни лимит</code>\n\n"
        "• процент — скидка в %, • фикс — скидка в ₽, • дни — бонусные дни, "
        "• лимит — макс. использований (0 = без лимита)\n\n"
        "Примеры:\n"
        "<code>SUMMER 20 0 0 100</code> — скидка 20%, 100 активаций\n"
        "<code>FREE7 0 0 7 50</code> — 7 дней бесплатно, 50 активаций",
        kb.admin_back_kb(),
    )


@router.message(Adm.promo)
async def adm_promo_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        code, percent, fixed, days, limit = message.text.split()
        code = code.upper()
        percent, fixed, days, limit = int(percent), int(fixed), int(days), int(limit)
    except ValueError:
        await message.answer("Формат: КОД процент фикс дни лимит")
        return
    await db.create_promo(code, percent, fixed, days, limit)
    await state.clear()
    await message.answer(
        f"✅ Промокод <code>{code}</code> создан.\n"
        f"Скидка: {percent}% / {fixed}{CURRENCY_SYMBOL}, дни: {days}, лимит: {limit or '∞'}",
        reply_markup=kb.admin_menu_kb(),
    )


# --------------------- поиск пользователя ---------------------
@router.callback_query(F.data == "adm:finduser")
async def adm_finduser(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.set_state(Adm.find_user)
    await ui.edit(cq, "Отправь <code>user_id</code>.", kb.admin_back_kb())


@router.message(Adm.find_user)
async def adm_finduser_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text.strip().isdigit():
        await message.answer("Нужен числовой user_id.")
        return
    uid = int(message.text.strip())
    user = await db.get_user(uid)
    if not user:
        await message.answer("Пользователь не найден.")
        return
    sub = await db.get_subscription(uid)
    refs = await db.count_referrals(uid)
    sub_line = (
        f"до {subscription.fmt_date(sub['expires_at'])}"
        if sub and sub["expires_at"] > db.now() else "нет активной"
    )
    await state.clear()
    await message.answer(
        f"👤 <b>Пользователь {uid}</b>\n"
        f"Username: @{user['username'] or '—'}\n"
        f"Подписка: {sub_line}\n"
        f"Баланс: {user['balance']}{CURRENCY_SYMBOL}\n"
        f"Рефералов: {refs}\n"
        f"Реферер: {user['referrer_id'] or '—'}\n"
        f"Бан: {'да' if user['banned'] else 'нет'}",
        reply_markup=kb.admin_menu_kb(),
    )
