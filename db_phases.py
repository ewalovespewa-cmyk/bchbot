"""Запросы к базе для фаз Экспедиции. Таблицы создаются в db.SCHEMA."""
import aiosqlite

from db import _connect


# ---------- фаза 1: слова ----------

async def create_word_task(word: str, text: str, points: int, phase: int, created_by: int) -> int:
    """Создаёт задание и закрывает предыдущие: активно всегда одно слово."""
    async with _connect() as db:
        await db.execute("UPDATE exp_word_tasks SET active=0 WHERE active=1")
        cur = await db.execute(
            "INSERT INTO exp_word_tasks (word, text, points, phase, created_by) VALUES (?, ?, ?, ?, ?)",
            (word, text, points, phase, created_by),
        )
        await db.commit()
        return cur.lastrowid


async def set_word_post(task_id: int, chat_id: int, message_id: int) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE exp_word_tasks SET post_chat_id=?, post_message_id=? WHERE id=?",
            (chat_id, message_id, task_id),
        )
        await db.commit()


async def active_word_task():
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM exp_word_tasks WHERE active=1 ORDER BY id DESC LIMIT 1")
        return await cur.fetchone()


async def word_task_by_post(chat_id: int, message_id: int):
    """Задание-слово, на пост которого ответили (активное или уже закрытое)."""
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM exp_word_tasks WHERE post_chat_id=? AND post_message_id=?", (chat_id, message_id)
        )
        return await cur.fetchone()


async def close_word_tasks() -> int:
    async with _connect() as db:
        cur = await db.execute("UPDATE exp_word_tasks SET active=0 WHERE active=1")
        await db.commit()
        return cur.rowcount


async def word_done(task_id: int, user_id: int) -> bool:
    async with _connect() as db:
        cur = await db.execute(
            "SELECT 1 FROM exp_word_done WHERE task_id=? AND user_id=?", (task_id, user_id)
        )
        return await cur.fetchone() is not None


async def complete_word(task_id: int, user_id: int, chat_id: int, message_id: int, points: int) -> bool:
    """Засчитывает слово и начисляет баллы. False — уже было засчитано."""
    async with _connect() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO exp_word_done (task_id, user_id, chat_id, message_id) VALUES (?, ?, ?, ?)",
            (task_id, user_id, chat_id, message_id),
        )
        if cur.rowcount == 0:
            return False
        await db.execute(
            "INSERT INTO points_log (user_id, amount, source, ref_id) VALUES (?, ?, 'phase_word', ?)",
            (user_id, points, task_id),
        )
        await db.commit()
        return True


async def list_word_tasks(limit: int = 15):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT t.*, (SELECT COUNT(*) FROM exp_word_done d WHERE d.task_id=t.id) AS done
               FROM exp_word_tasks t ORDER BY t.id DESC LIMIT ?""",
            (limit,),
        )
        return await cur.fetchall()


# ---------- фаза 2: фото ----------

async def create_photo_task(hashtag: str, text: str, points: int, phase: int, created_by: int) -> int | None:
    async with _connect() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO exp_photo_tasks (hashtag, text, points, phase, created_by) VALUES (?, ?, ?, ?, ?)",
            (hashtag, text, points, phase, created_by),
        )
        await db.commit()
        return cur.lastrowid if cur.rowcount > 0 else None


async def set_photo_post(task_id: int, chat_id: int, message_id: int) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE exp_photo_tasks SET post_chat_id=?, post_message_id=? WHERE id=?",
            (chat_id, message_id, task_id),
        )
        await db.commit()


async def set_photo_active(hashtag: str, active: bool) -> bool:
    async with _connect() as db:
        cur = await db.execute(
            "UPDATE exp_photo_tasks SET active=? WHERE hashtag=?", (int(active), hashtag)
        )
        await db.commit()
        return cur.rowcount > 0


async def find_photo_task(hashtags: list[str]):
    """Активное фото-задание по хэштегу из подписи."""
    if not hashtags:
        return None
    marks = ",".join("?" * len(hashtags))
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            f"SELECT * FROM exp_photo_tasks WHERE active=1 AND hashtag IN ({marks}) ORDER BY id", hashtags
        )
        return await cur.fetchone()


async def photo_task_by_post(chat_id: int, message_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM exp_photo_tasks WHERE post_chat_id=? AND post_message_id=?", (chat_id, message_id)
        )
        return await cur.fetchone()


async def close_photo_tasks() -> int:
    async with _connect() as db:
        cur = await db.execute("UPDATE exp_photo_tasks SET active=0 WHERE active=1")
        await db.commit()
        return cur.rowcount


async def list_photo_tasks(limit: int = 20):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT t.*,
                 (SELECT COUNT(*) FROM exp_photo_subs s WHERE s.task_id=t.id AND s.status='approved') AS approved,
                 (SELECT COUNT(*) FROM exp_photo_subs s WHERE s.task_id=t.id AND s.status='pending') AS pending
               FROM exp_photo_tasks t ORDER BY t.id DESC LIMIT ?""",
            (limit,),
        )
        return await cur.fetchall()


async def photo_status(task_id: int, user_id: int) -> str | None:
    """'approved' / 'pending', если уже есть такое фото у человека, иначе None."""
    async with _connect() as db:
        cur = await db.execute(
            "SELECT status FROM exp_photo_subs WHERE task_id=? AND user_id=? AND status IN ('approved','pending') "
            "ORDER BY status='approved' DESC LIMIT 1",
            (task_id, user_id),
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def create_photo_sub(task_id, user_id, chat_id, message_id, file_id, is_document) -> int:
    async with _connect() as db:
        cur = await db.execute(
            "INSERT INTO exp_photo_subs (task_id, user_id, chat_id, message_id, file_id, is_document) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, user_id, chat_id, message_id, file_id, int(is_document)),
        )
        await db.commit()
        return cur.lastrowid


async def get_photo_sub(sub_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT s.*, t.hashtag, t.text AS task_text, t.points, u.full_name, u.username
               FROM exp_photo_subs s
               JOIN exp_photo_tasks t ON t.id = s.task_id
               LEFT JOIN users u ON u.user_id = s.user_id
               WHERE s.id=?""",
            (sub_id,),
        )
        return await cur.fetchone()


async def decide_photo_sub(sub_id: int, approved: bool, reviewer_id: int) -> bool:
    """Решение по фото; при одобрении сразу начисляет баллы. False — уже решено кем-то."""
    async with _connect() as db:
        cur = await db.execute(
            "UPDATE exp_photo_subs SET status=?, reviewer_id=?, reviewed_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='pending'",
            ("approved" if approved else "rejected", reviewer_id, sub_id),
        )
        if cur.rowcount == 0:
            return False
        if approved:
            await db.execute(
                """INSERT INTO points_log (user_id, amount, source, ref_id)
                   SELECT s.user_id, t.points, 'phase_photo', s.id
                   FROM exp_photo_subs s JOIN exp_photo_tasks t ON t.id = s.task_id WHERE s.id=?""",
                (sub_id,),
            )
        await db.commit()
        return True


async def add_photo_review_msg(sub_id: int, chat_id: int, message_id: int) -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT INTO exp_photo_review_msgs (sub_id, chat_id, message_id) VALUES (?, ?, ?)",
            (sub_id, chat_id, message_id),
        )
        await db.commit()


async def get_photo_review_msgs(sub_id: int):
    async with _connect() as db:
        cur = await db.execute(
            "SELECT chat_id, message_id FROM exp_photo_review_msgs WHERE sub_id=?", (sub_id,)
        )
        return await cur.fetchall()
