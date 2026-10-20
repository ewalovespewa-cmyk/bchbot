"""Запросы к базе для бинго. Таблицы создаются в db.SCHEMA."""
import aiosqlite

from db import _connect


async def user_status(user_id: int) -> str | None:
    """'approved' — бинго уже засчитано, 'pending' — на проверке, None — можно сдавать."""
    async with _connect() as db:
        cur = await db.execute(
            "SELECT status FROM bingo_subs WHERE user_id=? AND status IN ('approved','pending') "
            "ORDER BY status='approved' DESC LIMIT 1",
            (user_id,),
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def create(user_id: int, file_ids: list[str]) -> int:
    async with _connect() as db:
        cur = await db.execute("INSERT INTO bingo_subs (user_id) VALUES (?)", (user_id,))
        sub_id = cur.lastrowid
        await db.executemany(
            "INSERT INTO bingo_photos (sub_id, idx, file_id) VALUES (?, ?, ?)",
            [(sub_id, i, f) for i, f in enumerate(file_ids, 1)],
        )
        await db.commit()
        return sub_id


async def get(sub_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT b.*, u.full_name, u.username FROM bingo_subs b
               LEFT JOIN users u ON u.user_id = b.user_id WHERE b.id=?""",
            (sub_id,),
        )
        return await cur.fetchone()


async def photos(sub_id: int) -> list[str]:
    async with _connect() as db:
        cur = await db.execute("SELECT file_id FROM bingo_photos WHERE sub_id=? ORDER BY idx", (sub_id,))
        return [r[0] for r in await cur.fetchall()]


async def decide(sub_id: int, approved: bool, reviewer_id: int, rejected_items: str | None = None) -> bool:
    """False — уже решено кем-то другим."""
    async with _connect() as db:
        cur = await db.execute(
            "UPDATE bingo_subs SET status=?, rejected_items=?, reviewer_id=?, reviewed_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='pending'",
            ("approved" if approved else "rejected", rejected_items, reviewer_id, sub_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def add_review_msg(sub_id: int, chat_id: int, message_id: int) -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT INTO bingo_review_msgs (sub_id, chat_id, message_id) VALUES (?, ?, ?)",
            (sub_id, chat_id, message_id),
        )
        await db.commit()


async def review_msgs(sub_id: int):
    async with _connect() as db:
        cur = await db.execute("SELECT chat_id, message_id FROM bingo_review_msgs WHERE sub_id=?", (sub_id,))
        return await cur.fetchall()


async def stats() -> dict:
    async with _connect() as db:
        cur = await db.execute("SELECT status, COUNT(*) FROM bingo_subs GROUP BY status")
        by = dict(await cur.fetchall())
        cur = await db.execute("SELECT COUNT(DISTINCT user_id) FROM bingo_subs WHERE status='approved'")
        done = (await cur.fetchone())[0]
    return {"pending": by.get("pending", 0), "approved": by.get("approved", 0),
            "rejected": by.get("rejected", 0), "people_done": done}
