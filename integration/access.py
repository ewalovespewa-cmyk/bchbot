"""Кто может играть: активировал ли человек бота регистрации и отметился ли на входе.

Статус приходит событиями от бота регистрации (см. events.py) и хранится в той же SQLite,
в отдельных таблицах bc_access / bc_events. Если статуса нет или «нет доступа» устарело,
бот спрашивает API бота регистрации. Если API недоступен — используется последний
известный статус.
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import aiohttp
import aiosqlite

from config import DB_PATH
from integration import config

log = logging.getLogger(__name__)

# Казахстан с 2024 года живёт в UTC+5 круглый год.
LOCAL_TZ = timezone(timedelta(hours=5))
NEGATIVE_TTL = 60  # «нет доступа» перепроверяем не чаще раза в минуту
POSITIVE_TTL = 600  # «доступ есть» из API перепроверяем раз в 10 минут (события приходят сразу)
API_TIMEOUT = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS bc_access (
    user_id INTEGER PRIMARY KEY,
    activated INTEGER NOT NULL DEFAULT 0,
    checkin_days TEXT NOT NULL DEFAULT '[]',   -- JSON-список дат YYYY-MM-DD
    source TEXT NOT NULL,                      -- 'event' или 'api'
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS bc_events (
    event_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    received_at REAL NOT NULL
);
"""


def today() -> str:
    return datetime.now(LOCAL_TZ).date().isoformat()


async def init() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def _get(user_id: int) -> tuple[bool, list[str], str, float] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT activated, checkin_days, source, updated_at FROM bc_access WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()
    if row is None:
        return None
    return bool(row[0]), json.loads(row[1]), row[2], row[3]


async def save(user_id: int, activated: bool, checkin_days: list[str], source: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO bc_access (user_id, activated, checkin_days, source, updated_at) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET activated=excluded.activated, checkin_days=excluded.checkin_days,
               source=excluded.source, updated_at=excluded.updated_at""",
            (user_id, int(activated), json.dumps(sorted(set(checkin_days))), source, time.time()),
        )
        await db.commit()


async def fetch_from_api(user_id: int) -> tuple[bool, list[str]] | None:
    """Спрашивает бота регистрации. None — API недоступен."""
    url = f"{config.BC_API_URL}/api/participant-status"
    headers = {"Authorization": f"Bearer {config.BC_API_TOKEN}"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)) as http:
            async with http.get(url, params={"telegram_user_id": str(user_id)}, headers=headers) as resp:
                if resp.status != 200:
                    log.warning("BC API ответил %s для %s", resp.status, user_id)
                    return None
                data = await resp.json()
    except Exception as e:
        log.warning("BC API недоступен: %s", e)
        return None
    return bool(data.get("activated")), [c["day"] for c in data.get("checkins", [])]


async def status(user_id: int) -> tuple[bool, list[str]] | None:
    """(активировал, дни чекина) или None, если узнать не удалось."""
    cached = await _get(user_id)
    if cached is not None:
        activated, days, source, updated_at = cached
        age = time.time() - updated_at
        fresh = source == "event" or age < (POSITIVE_TTL if activated else NEGATIVE_TTL)
        if fresh:
            return activated, days
    fetched = await fetch_from_api(user_id)
    if fetched is not None:
        await save(user_id, fetched[0], fetched[1], "api")
        return fetched
    return (cached[0], cached[1]) if cached else None


async def is_activated(user_id: int) -> bool | None:
    result = await status(user_id)
    return None if result is None else result[0]


async def is_checked_in(user_id: int, day: str | None = None) -> bool:
    result = await status(user_id)
    return bool(result and result[0] and (day or today()) in result[1])
