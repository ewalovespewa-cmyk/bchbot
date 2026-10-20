"""Тесты бинго: выбор фото на переработку и запись решений."""
import importlib
import os

os.environ.setdefault("BOT_TOKEN", "1:TEST")


def test_select_keyboard_toggles():
    from handlers.bingo import _numbers, _select_kb

    mask = (1 << 2) | (1 << 6)
    assert _numbers(mask) == [3, 7]
    texts = [b.text for row in _select_kb(1, mask).inline_keyboard for b in row]
    assert "❌ 3" in texts and "❌ 7" in texts and "📨 Отправить на переработку" in texts
    assert "📨 Отправить на переработку" not in [b.text for row in _select_kb(1, 0).inline_keyboard for b in row]


async def test_decide_once(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "b.db"))
    import config, db, db_bingo

    for m in (config, db, db_bingo):
        importlib.reload(m)
    await db.init_db()
    sub = await db_bingo.create(10, [f"f{i}" for i in range(9)])
    assert await db_bingo.user_status(10) == "pending"
    assert await db_bingo.decide(sub, False, 1, "3,7")
    assert not await db_bingo.decide(sub, True, 2)  # уже решено
    assert await db_bingo.user_status(10) is None    # можно сдавать заново
