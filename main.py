"""Точка входа: запускает бота."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import db
from config import BOT_TOKEN
from handlers import ExpeditionCounter, get_routers
from integration import setup_integration


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await db.init_db()

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_routers(*get_routers())
    # Доступ только для активировавших бота регистрации + приём событий от него (выключено без BC_API_URL).
    await setup_integration(dp)
    # Экспедиция: считает сообщения в чатах. Стоит после фильтра доступа — баллы только допущенным.
    dp.message.outer_middleware(ExpeditionCounter())

    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
