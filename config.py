"""Настройки бота. Все секреты берутся из переменных окружения (на Railway — вкладка Variables)."""
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Добавь его в переменные окружения.")

# Главные админы: Telegram ID через запятую, например "1999072927,123456"
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
}

# Где хранить базу. На Railway это /data/bot.db (постоянный диск).
DB_PATH = os.getenv("DB_PATH", "data/bot.db")
