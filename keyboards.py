"""Клавиатуры (инлайн)."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from config import CURRENCY_SYMBOL, SUPPORT_USERNAME


def main_menu(has_sub: bool, trial_available: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💳 Купить подписку", callback_data="menu:buy")
    if trial_available:
        b.button(text="🎁 Пробный период", callback_data="trial:activate")
    b.button(text="🔑 Мои подписки", callback_data="menu:mysubs")
    b.button(text="👥 Реферальная программа", callback_data="menu:ref")
    b.button(text="📲 Как подключить", callback_data="menu:howto")
    b.button(text="🆘 Поддержка", callback_data="menu:support")
    b.button(text="❓ FAQ", callback_data="menu:faq")
    b.adjust(1, 1, 1, 1, 2)
    return b.as_markup()


def plans_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in config.PLANS:
        b.button(text=f"{p.title} — {p.price}{CURRENCY_SYMBOL}", callback_data=f"buy:{p.code}")
    b.button(text="🎟 Ввести промокод", callback_data="menu:promo")
    b.button(text="⬅️ Назад", callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()


def payment_methods_kb(plan_code: str, show_balance: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if config.YOOKASSA_ENABLED:
        b.button(text="💳 Карта / СБП (ЮKassa)", callback_data=f"pay:yookassa:{plan_code}")
    if config.CRYPTOBOT_ENABLED:
        b.button(text="🪙 Криптовалюта", callback_data=f"pay:crypto:{plan_code}")
    if show_balance:
        b.button(text="👛 Оплатить с баланса", callback_data=f"pay:balance:{plan_code}")
    b.button(text="⬅️ Назад", callback_data="menu:buy")
    b.adjust(1)
    return b.as_markup()


def check_payment_kb(payment_id: int, pay_url: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔗 Перейти к оплате", url=pay_url)
    b.button(text="✅ Я оплатил", callback_data=f"check:{payment_id}")
    b.button(text="⬅️ В меню", callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()


def support_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✍️ Написать в поддержку", url=f"https://t.me/{SUPPORT_USERNAME}")
    b.button(text="⬅️ Назад", callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()


def back_kb(target: str = "menu:main") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Назад", callback_data=target)
    return b.as_markup()


def mysubs_kb(has_sub: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if has_sub:
        b.button(text="🔄 Продлить", callback_data="menu:buy")
        b.button(text="📲 Как подключить", callback_data="menu:howto")
    else:
        b.button(text="💳 Купить подписку", callback_data="menu:buy")
    b.button(text="⬅️ Назад", callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()


# --- админка ---
def admin_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📊 Статистика", callback_data="adm:stats")
    b.button(text="🎁 Выдать дни", callback_data="adm:givedays")
    b.button(text="🚫 Бан / разбан", callback_data="adm:ban")
    b.button(text="📢 Рассылка", callback_data="adm:broadcast")
    b.button(text="🎟 Создать промокод", callback_data="adm:promo")
    b.button(text="🔍 Найти пользователя", callback_data="adm:finduser")
    b.adjust(2)
    return b.as_markup()


def admin_back_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ В админку", callback_data="adm:main")
    return b.as_markup()
