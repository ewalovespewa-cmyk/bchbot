"""Настройки интеграции с ботом регистрации (bc2regbot). Все — из переменных окружения.

Если BC_API_URL не задан, интеграция выключена и бот работает ровно как раньше.
"""
import os

# Адрес бота регистрации, например http://bc2regbot.railway.internal:8080
BC_API_URL = os.getenv("BC_API_URL", "").strip().rstrip("/")
# Тот же токен, что INTEGRATION_TOKEN у бота регистрации
BC_API_TOKEN = os.getenv("BC_API_TOKEN", "").strip()
# Тот же секрет, что GAMIFICATION_WEBHOOK_SECRET у бота регистрации
BC_WEBHOOK_SECRET = os.getenv("BC_WEBHOOK_SECRET", "").strip()
# Порт, на котором бот принимает события (POST /bc-events). На Railway — PORT.
BC_EVENTS_PORT = int(os.getenv("BC_EVENTS_PORT") or os.getenv("PORT") or "8080")
# Username бота регистрации без @ — для подсказки «сначала активируй бота участника»
BC_REG_BOT_USERNAME = os.getenv("BC_REG_BOT_USERNAME", "businesscup2_regbot").strip().lstrip("@")
# 1 → бот сам одобряет заявки в общий чат фотоханта тем, кто активировал бота регистрации
BC_AUTO_APPROVE_JOIN = os.getenv("BC_AUTO_APPROVE_JOIN", "0").strip() in {"1", "true", "yes"}

ENABLED = bool(BC_API_URL)
