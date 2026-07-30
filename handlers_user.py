"""Пользовательские хендлеры: меню, покупка, оплата, рефералка, промокоды, триал.

Колбэки подтверждаются мгновенно в middleware (bot.py), поэтому здесь НЕ вызываем
cq.answer() в конце — используем ui.edit()/ui.toast() для отзывчивости.
"""
import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database as db
import texts
import keyboards as kb
import payments
import runtime
import subscription
import ui
from config import (
    PLANS_BY_CODE, TRIAL_DAYS, REFERRAL_PERCENT, REFERRAL_BONUS_DAYS,
    CURRENCY_SYMBOL,
)

log = logging.getLogger("user")
router = Router()


class Flow(StatesGroup):
    promo = State()


# --------------------------- helpers ---------------------------
def _trial_available(user) -> bool:
    return TRIAL_DAYS > 0 and not user["trial_used"]


async def show_menu(target, user):
    trial = _trial_available(user)
    sub = await db.get_subscription(user["telegram_id"])
    has_sub = bool(sub and sub["expires_at"] > db.now())
    markup = kb.main_menu(has_sub, trial)
    if isinstance(target, CallbackQuery):
        await ui.edit(target, texts.MENU, markup)
    else:
        await target.answer(texts.MENU, reply_markup=markup)


def _compute_price(plan, promo) -> int:
    """Цена тарифа с учётом промокода-скидки."""
    price = plan.price
    if promo:
        if promo["discount_percent"] > 0:
            price -= price * promo["discount_percent"] // 100
        price -= promo["discount_fixed"]
    return max(price, 1)


# --------------------------- /start ---------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    referrer_id = None
    if command.args and command.args.isdigit():
        referrer_id = int(command.args)
    user, _ = await db.ensure_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
        referrer_id,
    )
    if user["banned"]:
        return
    await message.answer(texts.WELCOME)
    if _trial_available(user):
        await message.answer(texts.TRIAL_OFFER)
    await show_menu(message, user)


# --------------------------- меню ---------------------------
@router.callback_query(F.data == "menu:main")
async def cb_main(cq: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    user = await db.get_user(cq.from_user.id)
    if not user:
        user, _ = await db.ensure_user(
            cq.from_user.id, cq.from_user.username or "",
            cq.from_user.first_name or "", None,
        )
    await show_menu(cq, user)


@router.callback_query(F.data == "menu:buy")
async def cb_buy(cq: CallbackQuery):
    await ui.edit(cq, texts.BUY_TITLE, kb.plans_kb())


@router.callback_query(F.data == "menu:mysubs")
async def cb_mysubs(cq: CallbackQuery):
    sub = await db.get_subscription(cq.from_user.id)
    if sub and sub["expires_at"] > db.now():
        text = texts.subscription_active(
            subscription.sub_link_for(sub), subscription.fmt_date(sub["expires_at"])
        )
        await ui.edit(cq, text, kb.mysubs_kb(True))
    else:
        await ui.edit(cq, texts.NO_SUBSCRIPTION, kb.mysubs_kb(False))


@router.callback_query(F.data == "menu:ref")
async def cb_ref(cq: CallbackQuery):
    user = await db.get_user(cq.from_user.id)
    link = f"https://t.me/{runtime.BOT_USERNAME}?start={user['telegram_id']}"
    count = await db.count_referrals(user["telegram_id"])
    text = texts.referral_info(link, count, user["balance"])
    await ui.edit(cq, text, kb.back_kb())


@router.callback_query(F.data == "menu:howto")
async def cb_howto(cq: CallbackQuery):
    await ui.edit(cq, texts.HOWTO, kb.back_kb())


@router.callback_query(F.data == "menu:support")
async def cb_support(cq: CallbackQuery):
    await ui.edit(cq, texts.SUPPORT, kb.support_kb())


@router.callback_query(F.data == "menu:faq")
async def cb_faq(cq: CallbackQuery):
    await ui.edit(cq, texts.FAQ, kb.back_kb())


# --------------------------- промокод ---------------------------
@router.callback_query(F.data == "menu:promo")
async def cb_promo(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.promo)
    await ui.edit(cq, texts.PROMO_ASK, kb.back_kb("menu:buy"))


@router.message(Flow.promo)
async def promo_entered(message: Message, state: FSMContext, bot: Bot):
    code = message.text.strip().upper()
    promo = await db.get_promo(code)
    valid = (
        promo and promo["active"]
        and (promo["max_uses"] == 0 or promo["used_count"] < promo["max_uses"])
        and not await db.promo_used_by(code, message.from_user.id)
    )
    if not valid:
        await message.answer(texts.PROMO_INVALID, reply_markup=kb.back_kb("menu:buy"))
        return

    # промокод на бонусные дни — активируем сразу
    if promo["bonus_days"] > 0 and promo["discount_percent"] == 0 and promo["discount_fixed"] == 0:
        await db.register_promo_use(code, message.from_user.id)
        try:
            link, expires = await subscription.grant(message.from_user.id, promo["bonus_days"])
        except Exception as e:
            log.exception("promo bonus grant failed: %s", e)
            await message.answer(texts.ERROR_GENERIC, reply_markup=kb.back_kb())
            return
        await state.clear()
        await message.answer(texts.promo_applied(f"+{promo['bonus_days']} дней подписки"))
        await message.answer(
            texts.subscription_active(link, subscription.fmt_date(expires)),
            reply_markup=kb.back_kb(),
        )
        return

    # промокод-скидка — запоминаем до оплаты
    await state.update_data(promo=code)
    await state.set_state(None)
    if promo["discount_percent"] > 0:
        desc = f"скидка {promo['discount_percent']}%"
    else:
        desc = f"скидка {promo['discount_fixed']}{CURRENCY_SYMBOL}"
    await message.answer(texts.promo_applied(desc))
    await message.answer(texts.BUY_TITLE, reply_markup=kb.plans_kb())


# --------------------------- триал ---------------------------
@router.callback_query(F.data == "trial:activate")
async def cb_trial(cq: CallbackQuery):
    user = await db.get_user(cq.from_user.id)
    if not _trial_available(user):
        await ui.toast(cq, "Пробный период уже был использован.")
        return
    try:
        link, expires = await subscription.grant(user["telegram_id"], TRIAL_DAYS)
    except Exception as e:
        log.exception("trial grant failed: %s", e)
        await ui.toast(cq, texts.ERROR_GENERIC)
        return
    await db.mark_trial_used(user["telegram_id"])
    await ui.edit(
        cq,
        texts.subscription_active(link, subscription.fmt_date(expires)),
        kb.back_kb(),
    )


# --------------------------- выбор тарифа/оплаты ---------------------------
@router.callback_query(F.data.startswith("buy:"))
async def cb_choose_plan(cq: CallbackQuery, state: FSMContext):
    plan_code = cq.data.split(":", 1)[1]
    plan = PLANS_BY_CODE.get(plan_code)
    if not plan:
        await ui.toast(cq, texts.ERROR_GENERIC)
        return
    data = await state.get_data()
    promo = await db.get_promo(data["promo"]) if data.get("promo") else None
    price = _compute_price(plan, promo)
    user = await db.get_user(cq.from_user.id)
    show_balance = user["balance"] >= price
    if not (config.YOOKASSA_ENABLED or config.CRYPTOBOT_ENABLED or show_balance):
        await ui.edit(
            cq,
            "⚠️ Оплата пока не настроена администратором.\n"
            "Способы оплаты появятся, как только владелец подключит ЮKassa/крипту.",
            kb.back_kb("menu:buy"),
        )
        return
    text = (
        f"Тариф: <b>{plan.title}</b>\n"
        f"К оплате: <b>{price}{CURRENCY_SYMBOL}</b>\n\n" + texts.PAY_CHOOSE
    )
    await ui.edit(cq, text, kb.payment_methods_kb(plan_code, show_balance))


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(cq: CallbackQuery, state: FSMContext, bot: Bot):
    _, provider, plan_code = cq.data.split(":")
    plan = PLANS_BY_CODE.get(plan_code)
    if not plan:
        await ui.toast(cq, texts.ERROR_GENERIC)
        return
    data = await state.get_data()
    promo_code = data.get("promo")
    promo = await db.get_promo(promo_code) if promo_code else None
    price = _compute_price(plan, promo)
    uid = cq.from_user.id

    if provider == "balance":
        if not await db.deduct_balance(uid, price):
            await ui.toast(cq, texts.BALANCE_NOT_ENOUGH)
            return
        pid = await db.add_payment(uid, "balance", price, plan_code, "", promo_code)
        await _finalize_payment(bot, pid)
        await state.update_data(promo=None)
        return

    desc = f"VPN подписка: {plan.title}"
    try:
        if provider == "yookassa":
            ext_id, url = await payments.create_yookassa(price, desc)
        elif provider == "crypto":
            ext_id, url = await payments.create_crypto(price, desc, f"user{uid}")
        else:
            await ui.toast(cq, texts.ERROR_GENERIC)
            return
    except Exception as e:
        log.exception("create payment failed: %s", e)
        await ui.toast(cq, texts.ERROR_GENERIC)
        return

    pid = await db.add_payment(uid, provider, price, plan_code, ext_id, promo_code)
    await ui.edit(cq, texts.PAY_PENDING, kb.check_payment_kb(pid, url))


@router.callback_query(F.data.startswith("check:"))
async def cb_check(cq: CallbackQuery, state: FSMContext, bot: Bot):
    pid = int(cq.data.split(":", 1)[1])
    payment = await db.get_payment(pid)
    if not payment or payment["user_id"] != cq.from_user.id:
        await ui.toast(cq, texts.ERROR_GENERIC)
        return
    if payment["status"] == "succeeded":
        await ui.toast(cq, "Уже оплачено ✅")
        return
    paid = await payments.check_payment(payment["provider"], payment["external_id"])
    if not paid:
        await ui.toast(cq, texts.PAY_NOT_YET)
        return
    await _finalize_payment(bot, pid)
    await state.update_data(promo=None)


# --------------------------- финализация оплаты ---------------------------
async def _finalize_payment(bot: Bot, payment_id: int):
    """Идемпотентно: активирует подписку, начисляет рефереру, применяет промокод."""
    payment = await db.get_payment(payment_id)
    if not payment or payment["status"] == "succeeded":
        return
    plan = PLANS_BY_CODE.get(payment["plan_code"])
    if not plan:
        return
    uid = payment["user_id"]

    # «Заявляем» платёж сразу, чтобы поллинг и ручная проверка не начислили дважды.
    await db.set_payment_status(payment_id, "succeeded")
    try:
        link, expires = await subscription.grant(uid, plan.days)
    except Exception as e:
        log.exception("grant failed for payment %s: %s", payment_id, e)
        # возвращаем платёж в очередь автопроверки; для баланса — возврат средств
        await db.set_payment_status(payment_id, "pending")
        if payment["provider"] == "balance":
            await db.add_balance(uid, payment["amount"])
        try:
            await bot.send_message(uid, texts.ERROR_GENERIC)
        except Exception:
            pass
        return

    if payment["promo_code"]:
        await db.register_promo_use(payment["promo_code"], uid)

    # реферальные начисления только с реальных платежей
    if payment["provider"] in ("yookassa", "crypto"):
        await _reward_referrer(bot, uid, payment_id, payment["amount"])

    await bot.send_message(
        uid,
        texts.PAY_SUCCESS + "\n\n" +
        texts.subscription_active(link, subscription.fmt_date(expires)),
        reply_markup=kb.back_kb(),
    )


async def _reward_referrer(bot: Bot, referred_id: int, payment_id: int, amount: int):
    user = await db.get_user(referred_id)
    ref_id = user["referrer_id"] if user else None
    if not ref_id:
        return
    # 30% на баланс — пожизненно, с каждой оплаты
    commission = amount * REFERRAL_PERCENT // 100
    if commission > 0:
        await db.add_balance(ref_id, commission)
        await db.add_referral_earning(ref_id, referred_id, payment_id, commission)
        try:
            await bot.send_message(
                ref_id,
                f"💰 Реферальное начисление: <b>+{commission}{CURRENCY_SYMBOL}</b> "
                f"за оплату приглашённого. Баланс пополнен.",
            )
        except Exception:
            pass
    # +N дней за первую оплату приглашённого
    if await db.mark_first_paid(referred_id) and REFERRAL_BONUS_DAYS > 0:
        try:
            await subscription.grant(ref_id, REFERRAL_BONUS_DAYS)
            await bot.send_message(
                ref_id,
                f"🎁 Тебе начислено <b>+{REFERRAL_BONUS_DAYS} дней</b> подписки "
                f"за приглашённого друга!",
            )
        except Exception as e:
            log.warning("referral bonus days failed: %s", e)
