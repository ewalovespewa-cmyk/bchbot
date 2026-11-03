"""Запросы к базе для бинго: 14 заданий, каждое сдаётся и проверяется отдельно.
Таблицы — в db.SCHEMA (bingo_items, bingo_item_msgs, bingo_done)."""
import aiosqlite

from db import _connect


async def card(user_id: int) -> dict[int, str]:
    """{номер задания: статус последней сдачи} — 'pending' / 'approved' / 'rejected'.
    Если задание уже засчитано, оно остаётся засчитанным."""
    async with _connect() as db:
        cur = await db.execute(
            "SELECT cell, status FROM bingo_items WHERE user_id=? ORDER BY id", (user_id,)
        )
        rows = await cur.fetchall()
    out: dict[int, str] = {}
    for cell, status in rows:
        if out.get(cell) != "approved":
            out[cell] = status
    return out


async def submit(user_id: int, cell: int, kind: str, content: str) -> int | None:
    """Новая сдача. None — по этому заданию уже есть засчитанная или ждущая проверки."""
    async with _connect() as db:
        cur = await db.execute(
            "SELECT 1 FROM bingo_items WHERE user_id=? AND cell=? AND status IN ('pending','approved')",
            (user_id, cell),
        )
        if await cur.fetchone():
            return None
        cur = await db.execute(
            "INSERT INTO bingo_items (user_id, cell, kind, content) VALUES (?, ?, ?, ?)",
            (user_id, cell, kind, content),
        )
        await db.commit()
        return cur.lastrowid


async def get(item_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT i.*, u.full_name, u.username FROM bingo_items i
               LEFT JOIN users u ON u.user_id = i.user_id WHERE i.id=?""",
            (item_id,),
        )
        return await cur.fetchone()


async def decide(item_id: int, approved: bool, reviewer_id: int) -> bool:
    """False — уже решено кем-то другим."""
    async with _connect() as db:
        cur = await db.execute(
            "UPDATE bingo_items SET status=?, reviewer_id=?, reviewed_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='pending'",
            ("approved" if approved else "rejected", reviewer_id, item_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def mark_done(user_id: int) -> bool:
    """Отметить, что всё бинго собрано. False — уже отмечали (поздравляем один раз)."""
    async with _connect() as db:
        cur = await db.execute("INSERT OR IGNORE INTO bingo_done (user_id) VALUES (?)", (user_id,))
        await db.commit()
        return cur.rowcount > 0


async def add_msg(item_id: int, chat_id: int, message_id: int, is_photo: bool) -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT INTO bingo_item_msgs (item_id, chat_id, message_id, is_photo) VALUES (?, ?, ?, ?)",
            (item_id, chat_id, message_id, int(is_photo)),
        )
        await db.commit()


async def msgs(item_id: int):
    async with _connect() as db:
        cur = await db.execute(
            "SELECT chat_id, message_id, is_photo FROM bingo_item_msgs WHERE item_id=?", (item_id,)
        )
        return await cur.fetchall()


async def stats() -> dict:
    async with _connect() as db:
        cur = await db.execute("SELECT status, COUNT(*) FROM bingo_items GROUP BY status")
        by = dict(await cur.fetchall())
        cur = await db.execute("SELECT COUNT(DISTINCT user_id) FROM bingo_items")
        people = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM bingo_done")
        done = (await cur.fetchone())[0]
    return {"pending": by.get("pending", 0), "approved": by.get("approved", 0),
            "rejected": by.get("rejected", 0), "people": people, "done": done}
