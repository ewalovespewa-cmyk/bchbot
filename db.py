"""Работа с базой данных (SQLite — один файл)."""
import os

import aiosqlite

from config import DB_PATH


async def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        await db.execute(
            """CREATE TABLE IF NOT EXISTS moderators (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        await db.commit()


async def save_user(user_id: int, username: str | None, full_name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
               full_name=excluded.full_name""",
            (user_id, username, full_name),
        )
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, username, full_name FROM users WHERE user_id=?", (user_id,)
        )
        return await cur.fetchone()


async def count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        return (await cur.fetchone())[0]


async def is_moderator(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM moderators WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None


async def add_moderator(user_id: int, added_by: int) -> bool:
    """True — добавлен, False — уже был модератором."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO moderators (user_id, added_by) VALUES (?, ?)",
            (user_id, added_by),
        )
        await db.commit()
        return cur.rowcount > 0


async def remove_moderator(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM moderators WHERE user_id=?", (user_id,))
        await db.commit()
        return cur.rowcount > 0


async def list_moderators():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """SELECT m.user_id, u.username, u.full_name FROM moderators m
               LEFT JOIN users u ON u.user_id = m.user_id ORDER BY m.added_at"""
        )
        return await cur.fetchall()
