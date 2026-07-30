"""Платёжные провайдеры: ЮKassa (карты + СБП) и CryptoBot (крипта).

Модель без публичного вебхука: создаём счёт → пользователь платит по ссылке →
статус проверяем опросом (кнопка «Я оплатил» + фоновый поллинг в scheduler).
"""
import asyncio
import uuid as uuidlib
import logging

import aiohttp

import config

log = logging.getLogger("payments")

# --- ЮKassa ---
if config.YOOKASSA_ENABLED:
    from yookassa import Configuration, Payment
    Configuration.account_id = config.YOOKASSA_SHOP_ID
    Configuration.secret_key = config.YOOKASSA_SECRET_KEY


async def create_yookassa(amount: int, description: str) -> tuple[str, str]:
    """Возвращает (payment_id, ссылка на оплату)."""
    def _create():
        payment = Payment.create({
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": config.YOOKASSA_RETURN_URL},
            "capture": True,
            "description": description,
        }, uuidlib.uuid4().hex)
        return payment.id, payment.confirmation.confirmation_url
    return await asyncio.to_thread(_create)


async def check_yookassa(payment_id: str) -> bool:
    def _check():
        p = Payment.find_one(payment_id)
        return p.status == "succeeded"
    try:
        return await asyncio.to_thread(_check)
    except Exception as e:
        log.warning("YooKassa check failed: %s", e)
        return False


# --- CryptoBot ---
CRYPTO_API = "https://pay.crypt.bot/api"


def _crypto_headers() -> dict:
    return {"Crypto-Pay-API-Token": config.CRYPTOBOT_TOKEN}


async def create_crypto(amount: int, description: str, payload: str) -> tuple[str, str]:
    data = {
        "currency_type": "fiat",
        "fiat": config.CRYPTOBOT_FIAT,
        "amount": str(amount),
        "description": description,
        "payload": payload,
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{CRYPTO_API}/createInvoice", json=data, headers=_crypto_headers()) as r:
            j = await r.json()
    if not j.get("ok"):
        raise RuntimeError(f"CryptoBot createInvoice error: {j}")
    res = j["result"]
    url = res.get("bot_invoice_url") or res.get("pay_url") or res.get("mini_app_invoice_url")
    return str(res["invoice_id"]), url


async def check_crypto(invoice_id: str) -> bool:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{CRYPTO_API}/getInvoices",
                params={"invoice_ids": invoice_id},
                headers=_crypto_headers(),
            ) as r:
                j = await r.json()
        if not j.get("ok"):
            return False
        items = j["result"].get("items", [])
        return bool(items) and items[0].get("status") == "paid"
    except Exception as e:
        log.warning("CryptoBot check failed: %s", e)
        return False


async def check_payment(provider: str, external_id: str) -> bool:
    if provider == "yookassa":
        return await check_yookassa(external_id)
    if provider == "crypto":
        return await check_crypto(external_id)
    return False
