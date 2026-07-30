"""Конфигурация бота. Значения читаются из .env.

ЦЕНЫ И ТАРИФЫ редактируются здесь, в списке PLANS. Всё остальное — в .env.
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# --- Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
]
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "support").lstrip("@")

# --- 3x-ui ---
XUI_BASE_URL = os.getenv("XUI_BASE_URL", "").rstrip("/")
XUI_USERNAME = os.getenv("XUI_USERNAME", "admin")
XUI_PASSWORD = os.getenv("XUI_PASSWORD", "admin")
XUI_INBOUND_ID = _int("XUI_INBOUND_ID", 1)
XUI_SUB_BASE_URL = os.getenv("XUI_SUB_BASE_URL", "").rstrip("/")
XUI_FLOW = os.getenv("XUI_FLOW", "xtls-rprx-vision")

# --- ЮKassa ---
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")
YOOKASSA_RETURN_URL = os.getenv("YOOKASSA_RETURN_URL", "https://t.me")
YOOKASSA_ENABLED = bool(YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY)

# --- CryptoBot ---
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN", "")
CRYPTOBOT_FIAT = os.getenv("CRYPTOBOT_FIAT", "RUB")
CRYPTOBOT_ENABLED = bool(CRYPTOBOT_TOKEN)

# --- Бизнес-логика ---
TRIAL_DAYS = _int("TRIAL_DAYS", 3)
REFERRAL_PERCENT = _int("REFERRAL_PERCENT", 30)
REFERRAL_BONUS_DAYS = _int("REFERRAL_BONUS_DAYS", 10)
TRAFFIC_LIMIT_GB = _int("TRAFFIC_LIMIT_GB", 0)

# --- БД ---
DB_PATH = os.getenv("DB_PATH", "vpnbot.db")

CURRENCY = "RUB"
CURRENCY_SYMBOL = "₽"


@dataclass(frozen=True)
class Plan:
    code: str          # уникальный идентификатор
    title: str         # как показывается в кнопке
    days: int          # длительность в днях
    price: int         # цена в рублях


# ============================================================
#  ТАРИФЫ — РЕДАКТИРУЙ ЗДЕСЬ.
#  Цены-заглушки в стиле YummyVPN. Поставь свои реальные.
# ============================================================
PLANS = [
    Plan(code="m1",  title="1 месяц",   days=30,  price=149),
    Plan(code="m3",  title="3 месяца",  days=90,  price=399),
    Plan(code="m6",  title="6 месяцев", days=180, price=699),
    Plan(code="m12", title="1 год",     days=365, price=1199),
]

PLANS_BY_CODE = {p.code: p for p in PLANS}
