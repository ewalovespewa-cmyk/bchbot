"""Работа с базой данных (SQLite — один файл)."""
import os

import aiosqlite

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    joined_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS moderators (
    user_id INTEGER PRIMARY KEY,
    added_by INTEGER,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
-- Простые настройки бота (ключ -> значение), например чат для ФотоХанта
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- Задания ФотоХанта
CREATE TABLE IF NOT EXISTS photo_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hashtag TEXT UNIQUE NOT NULL,      -- без '#', в нижнем регистре
    text TEXT NOT NULL,
    points INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
-- Фото, которые делегаты прислали на проверку
CREATE TABLE IF NOT EXISTS photo_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    file_id TEXT NOT NULL,
    is_document INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending / approved / rejected
    reviewer_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT
);
-- Какие сообщения с кнопками кому отправили (чтобы обновить у всех после решения)
CREATE TABLE IF NOT EXISTS review_messages (
    submission_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL
);
-- Общий журнал баллов. Сюда же потом будет писать вторая механика.
CREATE TABLE IF NOT EXISTS points_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    source TEXT NOT NULL,        -- например 'photohunt'
    ref_id INTEGER,              -- id записи-источника
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def _connect():
    return aiosqlite.connect(DB_PATH)


async def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    async with _connect() as db:
        await db.executescript(SCHEMA)
        await db.commit()


# ---------- пользователи ----------

async def save_user(user_id: int, username: str | None, full_name: str) -> None:
    async with _connect() as db:
        await db.execute(
            """INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
               full_name=excluded.full_name""",
            (user_id, username, full_name),
        )
        await db.commit()


async def count_users() -> int:
    async with _connect() as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        return (await cur.fetchone())[0]


# ---------- модераторы ----------

async def is_moderator(user_id: int) -> bool:
    async with _connect() as db:
        cur = await db.execute("SELECT 1 FROM moderators WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None


async def add_moderator(user_id: int, added_by: int) -> bool:
    async with _connect() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO moderators (user_id, added_by) VALUES (?, ?)",
            (user_id, added_by),
        )
        await db.commit()
        return cur.rowcount > 0


async def remove_moderator(user_id: int) -> bool:
    async with _connect() as db:
        cur = await db.execute("DELETE FROM moderators WHERE user_id=?", (user_id,))
        await db.commit()
        return cur.rowcount > 0


async def list_moderators():
    async with _connect() as db:
        cur = await db.execute(
            """SELECT m.user_id, u.username, u.full_name FROM moderators m
               LEFT JOIN users u ON u.user_id = m.user_id ORDER BY m.added_at"""
        )
        return await cur.fetchall()


async def moderator_ids() -> list[int]:
    async with _connect() as db:
        cur = await db.execute("SELECT user_id FROM moderators")
        return [r[0] for r in await cur.fetchall()]


# ---------- настройки ----------

async def get_setting(key: str) -> str | None:
    async with _connect() as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else None


async def set_setting(key: str, value: str | None) -> None:
    async with _connect() as db:
        if value is None:
            await db.execute("DELETE FROM settings WHERE key=?", (key,))
        else:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        await db.commit()


# ---------- задания ФотоХанта ----------

async def create_task(hashtag: str, text: str, points: int, created_by: int) -> int | None:
    """Возвращает id задания или None, если такой хэштег уже есть."""
    async with _connect() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO photo_tasks (hashtag, text, points, created_by) "
            "VALUES (?, ?, ?, ?)",
            (hashtag, text, points, created_by),
        )
        await db.commit()
        return cur.lastrowid if cur.rowcount > 0 else None


async def get_task_by_hashtag(hashtag: str):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM photo_tasks WHERE hashtag=?", (hashtag,))
        return await cur.fetchone()


async def get_active_tasks_by_hashtags(hashtags: list[str]):
    if not hashtags:
        return []
    marks = ",".join("?" * len(hashtags))
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            f"SELECT * FROM photo_tasks WHERE active=1 AND hashtag IN ({marks})", hashtags
        )
        return await cur.fetchall()


async def list_tasks():
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT t.*,
                 (SELECT COUNT(*) FROM photo_submissions s WHERE s.task_id=t.id AND s.status='approved') AS approved,
                 (SELECT COUNT(*) FROM photo_submissions s WHERE s.task_id=t.id AND s.status='pending') AS pending
               FROM photo_tasks t ORDER BY t.id"""
        )
        return await cur.fetchall()


async def set_task_active(hashtag: str, active: bool) -> bool:
    async with _connect() as db:
        cur = await db.execute(
            "UPDATE photo_tasks SET active=? WHERE hashtag=?", (int(active), hashtag)
        )
        await db.commit()
        return cur.rowcount > 0


# ---------- присланные фото ----------

async def user_has_approved(task_id: int, user_id: int) -> bool:
    async with _connect() as db:
        cur = await db.execute(
            "SELECT 1 FROM photo_submissions WHERE task_id=? AND user_id=? AND status='approved'",
            (task_id, user_id),
        )
        return await cur.fetchone() is not None


async def user_has_pending(task_id: int, user_id: int) -> bool:
    async with _connect() as db:
        cur = await db.execute(
            "SELECT 1 FROM photo_submissions WHERE task_id=? AND user_id=? AND status='pending'",
            (task_id, user_id),
        )
        return await cur.fetchone() is not None


async def create_submission(task_id, user_id, chat_id, message_id, file_id, is_document) -> int:
    async with _connect() as db:
        cur = await db.execute(
            "INSERT INTO photo_submissions (task_id, user_id, chat_id, message_id, file_id, is_document) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, user_id, chat_id, message_id, file_id, int(is_document)),
        )
        await db.commit()
        return cur.lastrowid


async def get_submission(submission_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT s.*, t.hashtag, t.text AS task_text, t.points,
                      u.full_name, u.username
               FROM photo_submissions s
               JOIN photo_tasks t ON t.id = s.task_id
               LEFT JOIN users u ON u.user_id = s.user_id
               WHERE s.id=?""",
            (submission_id,),
        )
        return await cur.fetchone()


async def decide_submission(submission_id: int, status: str, reviewer_id: int) -> bool:
    """Ставит решение, только если фото ещё ждёт проверки.
    False — кто-то из команды уже успел решить раньше."""
    async with _connect() as db:
        cur = await db.execute(
            "UPDATE photo_submissions SET status=?, reviewer_id=?, reviewed_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='pending'",
            (status, reviewer_id, submission_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def add_review_message(submission_id: int, chat_id: int, message_id: int) -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT INTO review_messages (submission_id, chat_id, message_id) VALUES (?, ?, ?)",
            (submission_id, chat_id, message_id),
        )
        await db.commit()


async def get_review_messages(submission_id: int):
    async with _connect() as db:
        cur = await db.execute(
            "SELECT chat_id, message_id FROM review_messages WHERE submission_id=?",
            (submission_id,),
        )
        return await cur.fetchall()


# ---------- баллы ----------

async def add_points(user_id: int, amount: int, source: str, ref_id: int | None = None) -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT INTO points_log (user_id, amount, source, ref_id) VALUES (?, ?, ?, ?)",
            (user_id, amount, source, ref_id),
        )
        await db.commit()


async def get_points(user_id: int) -> int:
    async with _connect() as db:
        cur = await db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM points_log WHERE user_id=?", (user_id,)
        )
        return (await cur.fetchone())[0]


async def leaderboard(limit: int = 20):
    async with _connect() as db:
        cur = await db.execute(
            """SELECT p.user_id, u.full_name, u.username, SUM(p.amount) AS total
               FROM points_log p LEFT JOIN users u ON u.user_id = p.user_id
               GROUP BY p.user_id HAVING total <> 0
               ORDER BY total DESC LIMIT ?""",
            (limit,),
        )
        return await cur.fetchall()
