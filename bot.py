"""Точка входа VPN-бота.

Запуск:  python bot.py
Перед запуском заполни .env (см. .env.example) и requirements.txt установлен.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, TelegramObject, CallbackQuery, ErrorEvent

import config
import database as db
import runtime
import scheduler
from xui import xui
import handlers_user
import handlers_admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("bot")


class BanMiddleware(BaseMiddleware):
    """Тихо игнорирует апдейты от забаненных пользователей (кроме админов)."""
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if user and user.id not in config.ADMIN_IDS:
            row = await db.get_user(user.id)
            if row and row["banned"]:
                return
        return await handler(event, data)


class CallbackAckMiddleware(BaseMiddleware):
    """Мгновенно подтверждает нажатие кнопки (убирает «часики») до тяжёлой работы.

    Это устраняет ситуацию, когда медленный ответ приводит к «query is too old»
    и кнопка визуально «не срабатывает».
    """
    async def __call__(self, handler, event: CallbackQuery, data: dict):
        try:
            await event.answer()
        except Exception:
            pass
        return await handler(event, data)


async def on_startup(bot: Bot):
    await db.init_db()
    me = await bot.get_me()
    runtime.BOT_USERNAME = me.username
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить бота / меню"),
    ])
    scheduler.start(bot)
    log.info("Бот @%s запущен. Админы: %s", me.username, config.ADMIN_IDS)


async def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан. Заполни .env (см. .env.example).")

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(BanMiddleware())
    dp.callback_query.outer_middleware(BanMiddleware())
    # Ack идёт после Ban: забаненным подтверждать нечего.
    dp.callback_query.outer_middleware(CallbackAckMiddleware())
    dp.include_router(handlers_admin.router)
    dp.include_router(handlers_user.router)

    @dp.errors()
    async def on_error(event: ErrorEvent):
        # Глобально гасим ошибки, чтобы один сбойный апдейт не «ронял» обработку.
        log.warning("Update error: %s", event.exception)
        return True

    dp.startup.register(on_startup)
    try:
        # drop_pending_updates: при старте отбрасываем накопившийся «хвост» кликов,
        # чтобы старые (уже протухшие) колбэки не обрабатывались.
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        await xui.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
