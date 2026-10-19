"""Настройки бота. Все секреты берутся из переменных окружения (на Railway — вкладка Variables)."""
import os
from datetime import timedelta, timezone

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

# Часовой пояс проекта: «день» для ФотоХанта считается по нему. Казахстан — UTC+5.
LOCAL_TZ = timezone(timedelta(hours=int(os.getenv("TZ_OFFSET_HOURS", "5"))))

# ---- Экспедиция: сколько стоит каждое действие ----
EXP_MESSAGE_POINTS = int(os.getenv("EXP_MESSAGE_POINTS", "1"))   # любое сообщение, стикер
EXP_VOICE_POINTS = int(os.getenv("EXP_VOICE_POINTS", "3"))       # голосовое или кружок
EXP_PHOTOHUNT_DAY_POINTS = int(os.getenv("EXP_PHOTOHUNT_DAY_POINTS", "5"))  # день с засчитанным фото
# Антиспам: сообщения одного человека чаще, чем раз в N секунд, не считаются (0 — выключить)
EXP_COOLDOWN_SECONDS = float(os.getenv("EXP_COOLDOWN_SECONDS", "2"))
# Сколько мест в лидерборде и сколько из них с главными подарками
EXP_TOP_SIZE = int(os.getenv("EXP_TOP_SIZE", "15"))
EXP_PRIZE_PLACES = int(os.getenv("EXP_PRIZE_PLACES", "10"))

# ---- Фазы Экспедиции: баллы по умолчанию (в каждом задании можно указать своё число) ----
PHASE_WORD_POINTS = int(os.getenv("PHASE_WORD_POINTS", "5"))     # фаза 1: предложение со словом
PHASE_WORD_MIN_WORDS = int(os.getenv("PHASE_WORD_MIN_WORDS", "3"))  # минимум слов в «предложении»
PHASE_PHOTO_POINTS = int(os.getenv("PHASE_PHOTO_POINTS", "10"))  # фаза 2: засчитанное фото
