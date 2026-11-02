"""Тесты бинго: каждое задание сдаётся отдельно, статусы карточки, повторная сдача после ❌."""
import importlib
import os

os.environ.setdefault("BOT_TOKEN", "1:TEST")


async def test_cells_independent(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "b.db"))
    import config, db, db_bingo

    for m in (config, db, db_bingo):
        importlib.reload(m)
    await db.init_db()
    a = await db_bingo.submit(10, 6, "photo", "f6")
    b = await db_bingo.submit(10, 2, "text", "ответ")
    assert a and b
    assert await db_bingo.submit(10, 6, "photo", "again") is None      # пока на проверке — нельзя
    assert await db_bingo.decide(a, False, 1)                           # 6 — не засчитано
    assert not await db_bingo.decide(a, True, 2)                        # уже решено
    assert await db_bingo.decide(b, True, 1)                            # 2 — засчитано
    assert await db_bingo.card(10) == {6: "rejected", 2: "approved"}
    assert await db_bingo.submit(10, 2, "text", "ещё") is None          # засчитанное не пересдать
    c = await db_bingo.submit(10, 6, "photo", "f6-new")                 # после ❌ — можно
    assert c and (await db_bingo.card(10))[6] == "pending"


def test_kinds():
    from handlers.bingo import kind_of

    assert [kind_of(n) for n in range(1, 10)] == ["text"] * 3 + ["photo"] * 6
