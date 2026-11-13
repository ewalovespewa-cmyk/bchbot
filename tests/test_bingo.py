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

    kinds = [kind_of(n) for n in range(1, 13)]
    assert kinds[6] == kinds[8] == "text" and kinds[7] == "both"
    assert kinds.count("photo") == 9


async def test_task_1_has_aiesec_link(monkeypatch):
    from unittest.mock import AsyncMock

    from handlers import bingo

    monkeypatch.setattr(bingo, "custom_text", AsyncMock(return_value=None))
    html_text = await bingo.task_html(1)
    assert '<a href="https://aieseckz.vercel.app/r/bc2-tg-bot14"><b>aiesec.org</b></a>' in html_text
    assert "<b>Подтверждение:</b>" in html_text
    monkeypatch.setattr(bingo, "custom_text", AsyncMock(return_value="свой <текст>"))
    assert await bingo.task_html(1) == "свой &lt;текст&gt;"  # текст от OC экранируется как раньше


async def test_editor_keeps_links(monkeypatch):
    from handlers import bingo

    store = {}

    async def set_setting(key, value):
        store[key] = value

    async def get_setting(key):
        return store.get(key)

    monkeypatch.setattr(bingo.db, "set_setting", set_setting)
    monkeypatch.setattr(bingo.db, "get_setting", get_setting)
    html_text = 'Зарегистрируйся на <a href="https://aieseckz.vercel.app/r/bc2-tg-bot14">aiesec.org</a>'
    await bingo.set_task_text(1, "Зарегистрируйся на aiesec.org", html_text)
    assert await bingo.task_html(1) == html_text  # ссылка за словом не потерялась
    await bingo.set_task_text(1, "-", "-")
    assert "bc2-tg-bot14" in await bingo.task_html(1)  # «-» вернул стандартный текст со ссылкой


def test_title_has_no_autolink():
    from handlers.bingo import title

    assert title(1) == "01. AIESEC.​ORG REGISTRATION"  # Telegram не сделает из названия ссылку
    assert title(2) == "02. TEAM CHECK"


async def test_partner_handles_link_to_instagram(monkeypatch):
    from unittest.mock import AsyncMock

    from handlers import bingo

    monkeypatch.setattr(bingo, "custom_text", AsyncMock(return_value=None))
    t10 = await bingo.task_html(10)
    assert '<a href="https://instagram.com/flip.kz">flip.kz</a>' in t10
    assert '<a href="https://instagram.com/rpk.kz_">rpk.kz_</a>' in t10
    assert "Подпишись на Instagram одного из наших партнёров:" in t10
    t11 = await bingo.task_html(11)
    assert '<a href="https://instagram.com/dikiilori">dikiilori</a>' in t11
    assert "Наши Coffee Break partners:" in t11
