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
# 1 (по умолчанию) — все игры только для активировавших бота регистрации.
# 0 — Экспедиция и ФотоХант открыты всем, проверка нужна только для бинго (по чекину).
BC_GATE_ALL = os.getenv("BC_GATE_ALL", "1").strip() in {"1", "true", "yes"}
# Дни мероприятия через запятую (YYYY-MM-DD). Если заданы, бинго открыто тем, кто отметился
# в любой из этих дней; иначе — только тем, кто отметился сегодня.
BC_CHECKIN_DAYS = [d.strip() for d in os.getenv("BC_CHECKIN_DAYS", "").split(",") if d.strip()]

ENABLED = bool(BC_API_URL)
